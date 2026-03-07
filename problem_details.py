"""
RFC 7807 Problem Details — Drop-in module for FastAPI applications.

Enterprise standard: https://github.com/Acidni-LLC/acidni-config/.github/standards/rfc7807/

Usage:
    # main.py
    from your_app.problem_details import register_problem_handlers

    app = FastAPI(...)
    register_problem_handlers(app, app_name="your-app")

    # For custom errors:
    from your_app.problem_details import problem_response, ProblemAction

    @app.exception_handler(YourCustomError)
    async def handler(request, exc):
        return problem_response(503, request,
            code="YOUR_CODE",
            title="Descriptive title.",
            detail=str(exc),
        )

    # Or raise inline:
    from your_app.problem_details import ProblemException

    raise ProblemException(404,
        code="INDEX_NOT_FOUND",
        title="We couldn't find what you requested.",
        detail=f"No index exists for repository '{repo}'.",
    )
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

BASE_TYPE_URL = "https://api.acidni.net/problems"


# ── Models ────────────────────────────────────────────────────────────


class ProblemAction(BaseModel):
    """Optional actionable recovery step for Copilot to render."""

    label: str
    type: str = "openUrl"  # openUrl | retry | signIn
    url: Optional[str] = None


class FieldError(BaseModel):
    """Per-field validation error."""

    field: str
    message: str


class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details with Acidni extensions."""

    type: str = Field(
        default=f"{BASE_TYPE_URL}/error",
        description="URI identifying the problem type",
    )
    title: str = Field(..., description="Short human-readable summary (safe for Copilot chat)")
    status: int = Field(..., description="HTTP status code")
    detail: Optional[str] = Field(
        None, description="Explanation specific to this occurrence"
    )
    instance: Optional[str] = Field(
        None, description="URI of the request that caused the problem"
    )
    code: str = Field(..., description="Machine-readable error code (SCREAMING_SNAKE)")
    action: Optional[ProblemAction] = None
    errors: Optional[list[FieldError]] = None
    retryAfterSeconds: Optional[int] = None
    correlationId: Optional[str] = None
    traceId: Optional[str] = None


# ── Predefined problem types ─────────────────────────────────────────

# (slug, default_title, default_code)
PROBLEMS: dict[int, tuple[str, str, str]] = {
    400: ("bad-request", "Bad request.", "BAD_REQUEST"),
    401: ("authentication-failed", "Authentication required.", "AUTH_INVALID_TOKEN"),
    403: ("forbidden", "You don't have access to this resource.", "AUTH_FORBIDDEN"),
    404: ("not-found", "We couldn't find what you requested.", "NOT_FOUND"),
    405: ("method-not-allowed", "Method not allowed.", "METHOD_NOT_ALLOWED"),
    409: ("conflict", "Resource conflict.", "CONFLICT"),
    422: ("validation-failed", "Some inputs aren't valid.", "VALIDATION_FAILED"),
    429: ("rate-limited", "Too many requests.", "RATE_LIMITED"),
    500: ("internal-error", "An unexpected error occurred.", "INTERNAL_ERROR"),
    502: ("bad-gateway", "Upstream service error.", "BAD_GATEWAY"),
    503: ("service-unavailable", "Service temporarily unavailable.", "SERVICE_UNAVAILABLE"),
    504: ("gateway-timeout", "Upstream service timeout.", "GATEWAY_TIMEOUT"),
}


# ── Helpers ───────────────────────────────────────────────────────────


def _get_correlation_id(request: Request | None) -> str:
    """Extract or mint a correlation ID from the request."""
    if request is None:
        return str(uuid.uuid4())
    return (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-Id")
        or request.headers.get("x-ms-client-request-id")
        or str(uuid.uuid4())
    )


def _get_trace_id() -> str | None:
    """Extract W3C trace ID from OpenTelemetry context if available."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            return f"{ctx.trace_id:032x}"
    except Exception:
        pass
    return None


def build_problem(
    status: int,
    *,
    detail: str | None = None,
    instance: str | None = None,
    code: str | None = None,
    title: str | None = None,
    action: ProblemAction | None = None,
    errors: list[FieldError] | None = None,
    retry_after: int | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> ProblemDetail:
    """Build a ProblemDetail with sensible defaults per status code."""
    slug, default_title, default_code = PROBLEMS.get(
        status, ("error", "Error", "ERROR")
    )
    return ProblemDetail(
        type=f"{BASE_TYPE_URL}/{slug}",
        title=title or default_title,
        status=status,
        detail=detail,
        instance=instance,
        code=code or default_code,
        action=action,
        errors=errors,
        retryAfterSeconds=retry_after,
        correlationId=correlation_id,
        traceId=trace_id or _get_trace_id(),
    )


def _log_problem(problem: ProblemDetail, request: Request | None) -> None:
    """Log the problem to Application Insights via structured logging."""
    log_fn = logger.error if problem.status >= 500 else logger.warning
    dimensions = {
        "problem_type": problem.type,
        "problem_code": problem.code,
        "problem_status": str(problem.status),
        "problem_title": problem.title,
        "correlation_id": problem.correlationId or "",
    }
    if request is not None:
        dimensions["request_path"] = request.url.path
        dimensions["request_method"] = request.method
        dimensions["client_ip"] = request.client.host if request.client else "unknown"

    log_fn(
        "ProblemDetail %d %s %s",
        problem.status,
        problem.code,
        request.url.path if request else "unknown",
        extra={"custom_dimensions": dimensions},
    )


def problem_response(
    status: int,
    request: Request | None = None,
    **kwargs: Any,
) -> JSONResponse:
    """Build a JSONResponse with RFC 7807 content type and App Insights logging."""
    rid = _get_correlation_id(request)
    instance = str(request.url) if request else None

    kwargs.setdefault("correlation_id", rid)
    kwargs.setdefault("instance", instance)

    problem = build_problem(status, **kwargs)
    _log_problem(problem, request)

    headers = {"X-Request-Id": rid}
    if problem.retryAfterSeconds is not None:
        headers["Retry-After"] = str(problem.retryAfterSeconds)

    return JSONResponse(
        status_code=status,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
        headers=headers,
    )


# ── ProblemException (raise inline) ──────────────────────────────────


class ProblemException(HTTPException):
    """Raise an HTTPException that the global handler serializes as RFC 7807.

    Usage:
        raise ProblemException(404,
            code="INDEX_NOT_FOUND",
            title="We couldn't find what you requested.",
            detail="No index exists for repository 'foo/bar'.",
        )
    """

    def __init__(
        self,
        status_code: int,
        *,
        code: str,
        title: str,
        detail: str | None = None,
        action: dict | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail={
                "code": code,
                "title": title,
                "detail": detail,
                "action": action,
                **extra,
            },
        )


# ── Global handler registration ──────────────────────────────────────


def register_problem_handlers(app: FastAPI, *, app_name: str = "service") -> None:
    """Register global exception handlers that emit RFC 7807 responses.

    Call this once from your FastAPI main.py:

        from your_app.problem_details import register_problem_handlers
        register_problem_handlers(app, app_name="repolens")

    This registers handlers for:
    - RequestValidationError → 422 with field-level errors
    - StarletteHTTPException → maps status to problem type
    - HTTPException → maps status to problem type (supports ProblemException detail dicts)
    - Exception → 500 catch-all with correlation ID for support
    """

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        field_errors = []
        messages = []
        for err in exc.errors():
            loc = " -> ".join(str(x) for x in err.get("loc", []))
            msg = err.get("msg", "validation error")
            field_errors.append(FieldError(field=loc, message=msg))
            messages.append(f"{loc}: {msg}" if loc else msg)
        return problem_response(
            422,
            request,
            detail="; ".join(messages) or "Request validation failed.",
            errors=field_errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_http_handler(request: Request, exc: StarletteHTTPException):
        detail_text = getattr(exc, "detail", str(exc))
        if not isinstance(detail_text, str):
            detail_text = str(detail_text)
        return problem_response(exc.status_code, request, detail=detail_text)

    @app.exception_handler(HTTPException)
    async def _http_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        kwargs: dict[str, Any] = {}
        if isinstance(detail, dict):
            # ProblemException passes a dict with code, title, detail, action
            kwargs["code"] = detail.get("code")
            kwargs["title"] = detail.get("title")
            kwargs["action"] = (
                ProblemAction(**detail["action"])
                if isinstance(detail.get("action"), dict)
                else None
            )
            detail_text = detail.get("detail") or detail.get("message") or str(detail)
        else:
            detail_text = str(detail) if detail else None
        return problem_response(exc.status_code, request, detail=detail_text, **kwargs)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        rid = _get_correlation_id(request)
        logger.error(
            "Unhandled exception (rid=%s, path=%s, app=%s): %s",
            rid,
            request.url.path,
            app_name,
            exc,
            exc_info=True,
        )
        return problem_response(
            500,
            request,
            detail=(
                f"An unexpected error occurred in {app_name}. "
                f"Quote correlation ID '{rid}' when contacting support."
            ),
        )
