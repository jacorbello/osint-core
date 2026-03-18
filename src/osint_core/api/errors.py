"""Shared API error helpers and exception handlers."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from osint_core.schemas.common import FieldError, ProblemDetails


class ProblemError(Exception):
    """Application exception that serializes into a ProblemDetails payload."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        detail: str,
        title: str | None = None,
        errors: list[FieldError] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.title = title or HTTPStatus(status_code).phrase
        self.errors = errors or []
        self.headers = headers or {}
        super().__init__(detail)


def problem_response_docs(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Return OpenAPI response metadata for the shared problem schema."""
    return {
        status_code: {"model": ProblemDetails, "description": HTTPStatus(status_code).phrase}
        for status_code in statuses
    }


def collection_page(*, offset: int, limit: int, total: int) -> dict[str, int | bool]:
    """Build the standard collection page metadata."""
    return {
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": offset + limit < total,
    }


def _problem_payload(
    request: Request,
    *,
    status_code: int,
    code: str,
    detail: str,
    title: str,
    errors: list[FieldError] | None = None,
) -> ProblemDetails:
    request_id = request.headers.get("x-request-id") or str(uuid4())
    return ProblemDetails(
        title=title,
        status=status_code,
        code=code,
        detail=detail,
        instance=str(request.url.path),
        request_id=request_id,
        errors=errors or [],
    )


def _default_error_code(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "auth_required",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_failed",
        503: "dependency_unavailable",
    }.get(status_code, "request_failed")


async def problem_exception_handler(
    request: Request,
    exc: ProblemError,
) -> JSONResponse:
    """Serialize a ProblemError as a standard API error."""
    payload = _problem_payload(
        request,
        status_code=exc.status_code,
        code=exc.code,
        detail=exc.detail,
        title=exc.title,
        errors=exc.errors,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=payload.model_dump(mode="json"),
        headers=exc.headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Normalize FastAPI HTTPException responses into ProblemDetails."""
    status_code = exc.status_code
    detail = exc.detail if isinstance(exc.detail, str) else HTTPStatus(status_code).phrase
    payload = _problem_payload(
        request,
        status_code=status_code,
        code=_default_error_code(status_code),
        detail=detail,
        title=HTTPStatus(status_code).phrase,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Normalize request validation errors into ProblemDetails."""
    errors = [
        FieldError(
            field=".".join(str(part) for part in err["loc"] if part != "body"),
            message=err["msg"],
            code=err["type"],
        )
        for err in exc.errors()
    ]
    payload = _problem_payload(
        request,
        status_code=422,
        code="validation_failed",
        detail="Request validation failed",
        title="Unprocessable Entity",
        errors=errors,
    )
    return JSONResponse(status_code=422, content=payload.model_dump(mode="json"))


def problem_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    detail: str,
    title: str | None = None,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a JSON error response without relying on FastAPI exception handlers."""
    payload = _problem_payload(
        request,
        status_code=status_code,
        code=code,
        detail=detail,
        title=title or HTTPStatus(status_code).phrase,
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=headers,
    )
