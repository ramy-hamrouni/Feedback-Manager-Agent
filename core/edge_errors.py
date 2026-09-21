from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


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


class ScoreDataError(EdgeHandledError):
    """Raised when a score document exists but is malformed (missing/invalid fields)."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            status_code=422,
            code="SCORE_DATA_INVALID",
            message=message,
            details=details,
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
