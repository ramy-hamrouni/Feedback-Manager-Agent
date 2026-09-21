"""Langfuse observability for the narrative-feedback pipeline.

Observability contract (same as the notebook):
  * ONE trace per pipeline run — the trace IS the graph.
  * Node spans come from the official LangGraph integration
    (``langfuse.langchain.CallbackHandler`` passed as ``config={"callbacks": [...]}``),
    so each node appears with the state it received and the update it returned.
  * Individual LLM calls get NO observation: they go through our own OpenAI/Anthropic
    clients, not LangChain, so the handler never sees them. Per-call generations are
    what made the trace unreadable.
  * COST is Langfuse's job: at the end of a run each model used gets ONE usage-rollup
    generation carrying that model's aggregated tokens, priced by Langfuse's own model
    pricing. There is no pricing table here.
  * latency / tokens / groundedness go out as numeric trace SCORES so they can be
    filtered, charted and alerted on.

Difference from the notebook: the notebook keeps run telemetry in module globals.
This is a server — runs are concurrent background tasks — so every accumulator here
lives in a ContextVar and is reset per run. Globals would cross-contaminate runs.

Every function degrades to a no-op when langfuse is not installed or not configured,
so the pipeline runs identically with tracing off.
"""

from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

# ── optional dependency ────────────────────────────────────────────────────
try:  # pragma: no cover - import guard
    from langfuse import get_client as _lf_get_client
    from langfuse import observe as _lf_observe

    _LANGFUSE_IMPORTED = True
except Exception as exc:  # pragma: no cover
    _lf_get_client = None
    _lf_observe = None
    _LANGFUSE_IMPORTED = False
    logger.error("Langfuse not importable (%s); TRACING DISABLED", type(exc).__name__)

try:  # pragma: no cover - present from langfuse v3
    from langfuse import propagate_attributes as _lf_propagate
except Exception:  # pragma: no cover
    _lf_propagate = None

_HANDLER_IMPORT_ERROR: str | None = None
try:  # pragma: no cover
    from langfuse.langchain import CallbackHandler as _LfCallbackHandler
except Exception as exc:  # pragma: no cover
    _LfCallbackHandler = None
    _HANDLER_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    # This failure silently costs every node span while the trace itself still works:
    # langfuse.langchain needs the `langchain` package, not just `langchain-core`.
    logger.error(
        "Langfuse LangGraph CallbackHandler unavailable (%s) — traces will still be "
        "created but NODE SPANS WILL BE MISSING. Fix: pip install langchain",
        _HANDLER_IMPORT_ERROR,
    )


# ── per-run telemetry (ContextVar, NOT globals) ────────────────────────────
# default=None, never default=[] — a mutable default is ONE shared list across every
# context, so a call recorded before reset_run_telemetry() would leak into other runs.
_llm_calls: ContextVar[list[dict[str, Any]] | None] = ContextVar("lf_llm_calls", default=None)
_current_node: ContextVar[str] = ContextVar("lf_current_node", default="-")


def _calls() -> list[dict[str, Any]]:
    """This context's call list, created on first use."""
    calls = _llm_calls.get()
    if calls is None:
        calls = []
        _llm_calls.set(calls)
    return calls

_client_cache: list[Any] = []
_handler_cache: list[Any] = []


def get_langfuse_client() -> Any | None:
    """The Langfuse client, or None when unavailable/unconfigured. Cached."""
    if not _LANGFUSE_IMPORTED:
        return None
    if _client_cache:
        return _client_cache[0]
    try:
        client = _lf_get_client()
    except Exception as exc:
        logger.warning("Langfuse client unavailable (%s: %s); tracing disabled", type(exc).__name__, exc)
        _client_cache.append(None)
        return None
    _client_cache.append(client)
    return client


def get_callback_handler() -> Any | None:
    """The LangGraph callback handler, reused across runs; it inherits the active trace."""
    if _LfCallbackHandler is None:
        logger.warning(
            "No LangGraph callback handler (%s); node spans will not be recorded",
            _HANDLER_IMPORT_ERROR or "unavailable",
        )
        return None
    if get_langfuse_client() is None:
        return None
    if _handler_cache:
        return _handler_cache[0]
    try:
        handler = _LfCallbackHandler()
    except Exception as exc:
        logger.warning("Langfuse CallbackHandler unavailable (%s: %s)", type(exc).__name__, exc)
        _handler_cache.append(None)
        return None
    _handler_cache.append(handler)
    return handler


def graph_config(run_name: str) -> dict[str, Any]:
    """LangGraph `config=` for an invoke: node spans + a readable run name.

    Returns just the run_name when tracing is off, so call sites stay identical.
    """
    config: dict[str, Any] = {"run_name": run_name}
    handler = get_callback_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    return config


def observe(name: str) -> Callable:
    """`langfuse.observe` when available, otherwise a transparent decorator."""
    if _lf_observe is None:
        def _noop(fn):
            return fn
        return _noop
    return _lf_observe(name=name)


@contextlib.contextmanager
def propagate_attributes(**kwargs: Any) -> Iterator[None]:
    """`langfuse.propagate_attributes`, or a no-op context manager."""
    if _lf_propagate is None or get_langfuse_client() is None:
        yield
        return
    try:
        with _lf_propagate(**kwargs):
            yield
    except Exception as exc:
        logger.warning("Langfuse propagate_attributes failed (%s: %s)", type(exc).__name__, exc)
        yield


# ── run telemetry ──────────────────────────────────────────────────────────
def reset_run_telemetry() -> None:
    """Start a fresh accumulator for THIS run. Must be called once per run."""
    _llm_calls.set([])
    _current_node.set("-")


@contextlib.contextmanager
def node_scope(name: str) -> Iterator[None]:
    """Attribute every LLM call made inside to `name` (the running node)."""
    token = _current_node.set(name)
    try:
        yield
    finally:
        _current_node.reset(token)


def record_llm_call(
    *,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    label: str | None = None,
) -> None:
    """Called by the LLM client instead of opening a generation observation."""
    try:
        _calls().append(
            {
                "step": _current_node.get(),
                "label": label or _current_node.get(),
                "model": model or "unknown",
                "provider": provider,
                "tokens_in": int(input_tokens or 0),
                "tokens_out": int(output_tokens or 0),
                "latency_ms": float(latency_ms or 0.0),
            }
        )
    except Exception:  # telemetry must never break a run
        logger.debug("record_llm_call failed", exc_info=True)


def run_tokens() -> dict[str, int]:
    calls = _calls()
    return {
        "input": sum(c["tokens_in"] for c in calls),
        "output": sum(c["tokens_out"] for c in calls),
        "total": sum(c["tokens_in"] + c["tokens_out"] for c in calls),
        "calls": len(calls),
    }


def usage_by_model() -> dict[str, dict[str, Any]]:
    """Per-model token totals — one entry becomes one usage-rollup generation, which is
    what lets Langfuse price the run with its own model pricing."""
    out: dict[str, dict[str, Any]] = {}
    for c in _calls():
        e = out.setdefault(
            c["model"],
            {"input": 0, "output": 0, "calls": 0, "latency_ms": 0.0, "provider": c["provider"], "labels": []},
        )
        e["input"] += c["tokens_in"]
        e["output"] += c["tokens_out"]
        e["calls"] += 1
        e["latency_ms"] += c["latency_ms"]
        e["labels"].append(c["label"])
    for e in out.values():
        e["latency_ms"] = round(e["latency_ms"], 1)
    return out


def tokens_by_node() -> dict[str, dict[str, int]]:
    """Per-node token totals — the 'what did each node cost me' breakdown."""
    out: dict[str, dict[str, int]] = {}
    for c in _calls():
        e = out.setdefault(c["step"], {"calls": 0, "tokens": 0})
        e["calls"] += 1
        e["tokens"] += c["tokens_in"] + c["tokens_out"]
    return out


def emit_run_telemetry(metadata: dict[str, Any], scores: dict[str, Any] | None = None) -> None:
    """Attach run metadata to the current span, emit one usage-rollup generation per
    model, and send the numeric trace scores. Never raises."""
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.update_current_span(metadata=metadata)

        for model, usage in usage_by_model().items():
            generation = client.start_observation(
                as_type="generation",
                name=f"usage · {model}",
                model=model,
                model_parameters={"provider": usage["provider"]},
                usage_details={
                    "input": usage["input"],
                    "output": usage["output"],
                    "total": usage["input"] + usage["output"],
                },
                metadata={
                    "llm_calls": usage["calls"],
                    "llm_latency_ms": usage["latency_ms"],
                    "steps": sorted(set(usage["labels"])),
                },
            )
            generation.end()

        for name, payload in (scores or {}).items():
            if payload is None:
                continue
            value, comment = payload if isinstance(payload, tuple) else (payload, None)
            if value is None:
                continue
            client.score_current_trace(name=name, value=value, comment=comment)
    except Exception as exc:
        logger.warning("Langfuse reporting failed (%s: %s)", type(exc).__name__, exc)


def log_tracing_status(emit_test_span: bool = False) -> bool:
    """Log loudly, at startup, whether tracing will actually work.

    Everything else in this module degrades to a silent no-op by design, which is right
    for production and useless for debugging — this is the one place that says out loud
    what state tracing is in. Set LANGFUSE_SELFCHECK=1 to also push a probe span, which
    proves end-to-end delivery without waiting for a successful pipeline run.
    """
    import os

    if not _LANGFUSE_IMPORTED:
        logger.error("LANGFUSE TRACING OFF: the langfuse package could not be imported")
        return False

    def _mask(value: str | None) -> str:
        if not value:
            return "<MISSING>"
        return f"{value[:6]}...{value[-4:]} (len={len(value)})"

    public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret = os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("LANGFUSE_HOST")
    logger.info("Langfuse config: host=%s public_key=%s secret_key=%s",
                host or "<MISSING>", _mask(public), _mask(secret))

    if not (public and secret):
        logger.error(
            "LANGFUSE TRACING OFF: keys missing from the environment. Settings."
            "apply_runtime_env() exports MANAGER_AGENT_LANGFUSE_* -> LANGFUSE_*; check .env"
        )
        return False

    client = get_langfuse_client()
    handler = get_callback_handler()
    if client is None:
        logger.error("LANGFUSE TRACING OFF: could not create the Langfuse client")
        return False
    if handler is None:
        logger.error(
            "Traces will be created but LANGGRAPH NODE SPANS ARE DISABLED (%s). "
            "Fix: pip install langchain",
            _HANDLER_IMPORT_ERROR or "handler unavailable",
        )
        return False

    logger.info("Langfuse tracing ON (client and LangGraph callback handler ready)")
    logger.info("LangGraph node spans: ENABLED")

    if emit_test_span:
        try:
            span = client.start_observation(as_type="span", name="tracing_selfcheck")
            span.end()
            client.flush()
            logger.info(
                "Langfuse self-check span sent — if 'tracing_selfcheck' does NOT appear in "
                "the Langfuse UI within a minute, the keys or host are wrong"
            )
        except Exception as exc:
            logger.error("Langfuse self-check FAILED (%s: %s)", type(exc).__name__, exc)
            return False
    return True


def flush() -> None:
    """Flush pending events — important in a background task that may end abruptly."""
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.debug("Langfuse flush failed", exc_info=True)
