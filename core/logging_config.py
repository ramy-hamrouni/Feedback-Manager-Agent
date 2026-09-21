import logging
import sys
from contextvars import ContextVar

# Set once per pipeline run so every log line emitted while that run is on the
# stack (including the detached asyncio task) can be correlated.
run_id_var: ContextVar[str] = ContextVar("run_id", default="-")

# Libraries that log every HTTP request/response at INFO and drown the pipeline.
NOISY_LOGGERS = (
    "pymongo",
    "azure",
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.identity",
    "adlfs",
    "fsspec",
    "httpx",
    "httpcore",
    "urllib3",
    "openai",
    "anthropic",
)


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:
        # already configured (e.g. re-import under a test runner/reloader)
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s [run=%(run_id)s] %(message)s")
    )
    handler.addFilter(RunIdFilter())
    root.addHandler(handler)
    root.setLevel(level)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))
