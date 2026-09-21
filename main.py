import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from core.edge_errors import install_exception_handlers
from core.logging_config import configure_logging
from core.settings import get_settings
from core.tracing import flush as flush_tracing, log_tracing_status
from llm_gateway.client import create_llm_client
from repositories.mongo_repository import MongoRepository
from repositories.storage_repository import ObjectStorageRepository
from services.narrative_artifacts_service import NarrativeArtifactsService
from routers.routes import router as narrative_feedback_router
from routers.health import router as health_router

configure_logging(get_settings().log_level)
logger = logging.getLogger("api.requests")
startup_logger = logging.getLogger("api.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Process-lifetime resources.

    These are built ONCE and shared. Per-request construction meant every call — even
    one about to 404 — re-opened a MongoClient (throwing away its connection pool) and
    re-parsed every artifact. It was also a correctness problem: FastAPI tears down
    `yield` dependencies BEFORE background tasks run, so the pipeline was finishing its
    run against a repository whose client had already been closed.

    The Depends(...) providers still yield; they just hand out what is built here.
    """
    import os

    settings = get_settings()
    log_tracing_status(emit_test_span=os.getenv("LANGFUSE_SELFCHECK") == "1")

    app.state.storage = ObjectStorageRepository(settings=settings)
    # loads the release manifest, framework rows and competency descriptions; the
    # loaders record failures internally rather than raising, so a storage outage
    # leaves a degraded (not dead) service — see GET /api/v1/health
    app.state.artifacts = NarrativeArtifactsService(settings, app.state.storage)
    app.state.mongo = MongoRepository(settings)
    app.state.llm = create_llm_client(settings)

    startup_logger.info(
        "Startup: artifacts ready=%s framework_rows=%d competency_descriptions=%d | "
        "mongo region=%s database=%s enabled=%s | llm provider=%s",
        app.state.artifacts.ready,
        app.state.artifacts.framework_rows_loaded,
        app.state.artifacts.competency_descriptions_loaded,
        app.state.mongo.region,
        settings.mongo_database,
        app.state.mongo.enabled,
        settings.llm_provider,
    )

    yield

    startup_logger.info("Shutdown: releasing shared resources")
    try:
        await app.state.llm.aclose()
    except Exception:
        startup_logger.warning("Error closing the LLM client", exc_info=True)
    for label, resource in (
        ("artifacts", app.state.artifacts),
        ("mongo", app.state.mongo),
        ("storage", app.state.storage),
    ):
        try:
            resource.close()
        except Exception:
            startup_logger.warning("Error closing %s", label, exc_info=True)
    # background runs can be cut off mid-flight on shutdown; push what is buffered
    flush_tracing()


app = FastAPI(
    title="Manager Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

install_exception_handlers(app)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
        raise
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "%s %s -> %s (%.1fms)", request.method, request.url.path, response.status_code, duration_ms
    )
    return response


app.include_router(health_router, prefix="/api/v1")
app.include_router(narrative_feedback_router, prefix="/api/v1")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Manager Agent API is running."}
