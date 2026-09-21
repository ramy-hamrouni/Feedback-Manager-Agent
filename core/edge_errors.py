from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError


logger = logging.getLogger(__name__)


class EdgeHandledError(HTTPException):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        detail = {
            "code": code,
            "message": message,
            "details": details or {},
        }
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
        self.message = message
        self.details = detail["details"]


class RunFailedError(EdgeHandledError):
    def __init__(self, run_id: str, message: str) -> None:
        super().__init__(
            status_code=409,
            code="RUN_FAILED",
            message=message or "Run failed.",
            details={"score_id": run_id},
        )



class FeedbackAlreadyGeneratedError(EdgeHandledError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="FEEDBACK_ALREADY_GENERATED",
            message="Feedback has already been generated for this assessment.",
        )


class FeedbackGenerationInProgressError(EdgeHandledError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="FEEDBACK_GENERATION_IN_PROGRESS",
            message="Feedback generation is already in progress for this assessment.",
        )


class FeedbackGenerationFailedError(EdgeHandledError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="FEEDBACK_GENERATION_FAILED",
            message="Previous feedback generation failed for this assessment.",
        )


class ScoreNotFoundError(EdgeHandledError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="SCORE_NOT_FOUND",
            message=f"No score found for this assessment.",
            
        )


def _jsonable(value: object, *, max_len: int = 200) -> object:
    """Anything that must survive JSON encoding in an error body."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= max_len else text[:max_len] + "…"


class ScoreDataError(EdgeHandledError):
    """Raised when a score document exists but is not usable.

    Build these with the classmethods rather than formatting a message at the call
    site: a raw ValidationError stringifies into a multi-line pydantic dump (complete
    with a docs URL) that is unreadable in an API response and impossible for a client
    to branch on. The field-level facts belong in `details`, not in `message`.
    """

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            status_code=422,
            code="SCORE_DATA_INVALID",
            message=message,
            details=details,
        )

    @classmethod
    def from_validation_error(
        cls, exc: ValidationError, *, context: dict | None = None
    ) -> "ScoreDataError":
        """Turn a pydantic ValidationError into one field-per-entry error body."""
        errors: list[dict] = []
        for err in exc.errors(include_url=False):
            errors.append(
                {
                    "field": ".".join(str(part) for part in err.get("loc", ())) or "<root>",
                    "rule": err.get("type"),
                    "message": err.get("msg"),
                    "received": _jsonable(err.get("input")),
                }
            )
        first = errors[0] if errors else None
        if first:
            summary = f"This score document is malformed: {first['field']} — {first['message']}."
            if len(errors) > 1:
                summary += f" ({len(errors) - 1} further problem(s); see details.)"
        else:
            summary = "This score document is malformed."
        return cls(
            summary,
            details={"error_count": len(errors), "errors": errors, **(context or {})},
        )

    @classmethod
    def no_competencies(cls, context: dict | None = None) -> "ScoreDataError":
        return cls(
            "This score document has no competency scores.",
            details={"competency_count": 0, **(context or {})},
        )

    @classmethod
    def too_few_competencies(
        cls, count: int, minimum: int, context: dict | None = None
    ) -> "ScoreDataError":
        return cls(
            f"This score document has {count} competency score(s); at least {minimum} are "
            "required to generate feedback.",
            details={"competency_count": count, "minimum_required": minimum, **(context or {})},
        )




def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and {"code", "message", "details"}.issubset(detail.keys()):
            error_payload = {
                "code": detail["code"],
                "message": detail["message"],
                "details": detail["details"],
            }
        else:
            error_payload = {
                "code": "HTTP_ERROR",
                "message": str(detail),
                "details": {},
            }
        logger.warning(
            "Handled error %s at %s (%s): %s",
            error_payload["code"],
            request.url.path,
            exc.status_code,
            error_payload["message"],
        )
        payload = {
            "error": error_payload
        }
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(Exception)
    async def _handle_untyped_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception at %s", request.url.path)
        payload = {
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Internal server error",
                "details": {"path": request.url.path},
            }
        }
        return JSONResponse(status_code=500, content=payload)
