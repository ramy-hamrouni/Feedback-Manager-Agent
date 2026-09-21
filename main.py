import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from core.edge_errors import install_exception_handlers
from core.logging_config import configure_logging
from core.settings import get_settings
from core.tracing import flush as flush_tracing, log_tracing_status
from routers.routes import router as narrative_feedback_router
from routers.health import router as health_router

configure_logging(get_settings().log_level)
logger = logging.getLogger("api.requests")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Resources are per-request: each Depends(...) provider closes what it opened.
    """TODO:Include initialization for the artificats used by the application"""
    import os

    log_tracing_status(emit_test_span=os.getenv("LANGFUSE_SELFCHECK") == "1")
    yield
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
