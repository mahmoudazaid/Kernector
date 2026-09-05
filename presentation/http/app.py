"""FastAPI application factory for the HTTP presentation adapter."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from composition import Settings, load_runtime_settings
from presentation.http.errors import (
    Problem,
    ProblemError,
    UploadTooLargeError,
    problem_from_exception,
    problem_from_validation_errors,
    register_problem_schemas,
)
from presentation.http.routes import capabilities as capabilities_routes
from presentation.http.routes import chat as chat_routes
from presentation.http.routes import documents as documents_routes
from presentation.http.routes import health as health_routes
from presentation.http.routes import ollama_status as ollama_status_routes
from presentation.http.routes import settings as settings_routes

_PROBLEM_MEDIA_TYPE = "application/problem+json"
_LOG = logging.getLogger("presentation.http")
# Multipart framing adds path/headers beyond the file bytes themselves.
_MULTIPART_OVERHEAD_BYTES = 64_000
_DOCUMENT_UPLOAD_METHODS = frozenset({"POST", "PUT"})
_DOCUMENT_UPLOAD_PREFIX = "/api/v1/documents"


def cors_origins_from_settings(settings: Settings) -> tuple[str, ...]:
    """Return the CORS allowlist for *settings*, or empty when dev CORS is off.

    Never returns ``*`` — that is rejected when Settings are loaded.
    """
    if not settings.http.dev_cors:
        return ()
    return settings.http.cors_origins


def cors_origins_from_env() -> tuple[str, ...]:
    """Resolve CORS allowlist via composition settings (``.env`` included).

    Prefer :func:`cors_origins_from_settings` when Settings are already loaded.
    """
    return cors_origins_from_settings(load_runtime_settings())


def _problem_response(
    problem: Problem,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    payload = problem.model_dump(exclude_none=True)
    return JSONResponse(
        status_code=problem.status,
        content=payload,
        media_type=_PROBLEM_MEDIA_TYPE,
        headers=dict(headers) if headers else None,
    )


def create_app(*, cors_origins: Sequence[str] | None = None) -> FastAPI:
    """Build the HTTP adapter application.

    Args:
        cors_origins: Explicit allowlist for tests and callers. When ``None``,
            origins come from Settings (``HTTP_DEV_CORS`` / ``HTTP_CORS_ORIGINS``
            after ``load_dotenv``).
    """
    app = FastAPI(
        title="Kernector API",
        version="0.1.0",
        description=(
            "Minimal versioned HTTP adapter over composition. "
            "Unknown paths return RFC 9457 Problem Details with status 404 "
            "(app-level; not declared per operation)."
        ),
    )
    origins = list(
        cors_origins_from_env() if cors_origins is None else cors_origins
    )
    _LOG.info(
        "HTTP CORS allowlist: %s",
        ", ".join(origins) if origins else "(empty — production default)",
    )
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    max_upload_bytes = load_runtime_settings().max_upload_bytes

    @app.middleware("http")
    async def reject_oversized_document_uploads(
        request: Request, call_next: Any
    ) -> Response:
        """Reject oversized document uploads before multipart buffering."""
        path = request.url.path
        if (
            request.method in _DOCUMENT_UPLOAD_METHODS
            and (
                path == _DOCUMENT_UPLOAD_PREFIX
                or path.startswith(f"{_DOCUMENT_UPLOAD_PREFIX}/")
            )
        ):
            raw = request.headers.get("content-length")
            if raw is not None:
                try:
                    length = int(raw)
                except ValueError:
                    length = -1
                if length > max_upload_bytes + _MULTIPART_OVERHEAD_BYTES:
                    problem = problem_from_exception(
                        UploadTooLargeError(max_bytes=max_upload_bytes),
                        instance=path,
                    )
                    return _problem_response(problem)
        return await call_next(request)

    # Taxonomy failures are ValueError / RuntimeError subclasses. Registering
    # those roots (not bare Exception) keeps handlers on ExceptionMiddleware,
    # which sits inside CORSMiddleware — so error responses still get CORS
    # headers. Starlette walks ``type(exc).__mro__``, so RequestValidationError
    # (ValueError subclass) still hits its more-specific handler first.
    # A bare Exception handler remains last-resort and is served by
    # ServerErrorMiddleware (outside CORS); log with exc_info because handled
    # exceptions are no longer re-raised to uvicorn.

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            ProblemError(
                pointer=_json_pointer(err.get("loc", ())),
                detail=str(err.get("msg", "Invalid value")),
            )
            for err in exc.errors()
        ]
        problem = problem_from_validation_errors(
            errors, instance=str(request.url.path)
        )
        return _problem_response(problem)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == 404:
            problem = Problem(
                type="https://kernector.dev/problems/not_found",
                title="Not found",
                status=404,
                detail="The requested resource was not found.",
                code="not_found",
                instance=str(request.url.path),
            )
            return _problem_response(problem, headers=exc.headers)
        problem = Problem(
            type=f"https://kernector.dev/problems/http_{exc.status_code}",
            title="HTTP error",
            status=exc.status_code,
            detail="The request could not be completed.",
            code=f"http_{exc.status_code}",
            instance=str(request.url.path),
        )
        return _problem_response(problem, headers=exc.headers)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        _LOG.warning("Mapped ValueError on %s", request.url.path, exc_info=exc)
        problem = problem_from_exception(exc, instance=str(request.url.path))
        return _problem_response(problem)

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(
        request: Request, exc: RuntimeError
    ) -> JSONResponse:
        _LOG.warning("Mapped RuntimeError on %s", request.url.path, exc_info=exc)
        problem = problem_from_exception(exc, instance=str(request.url.path))
        return _problem_response(problem)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        _LOG.exception("Unhandled exception on %s", request.url.path)
        problem = problem_from_exception(exc, instance=str(request.url.path))
        return _problem_response(problem)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        """Browsers probe this automatically; avoid a noisy Problem Details 404."""
        return Response(status_code=204)

    app.include_router(health_routes.router)
    app.include_router(capabilities_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(ollama_status_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(documents_routes.router)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        register_problem_schemas(components.setdefault("schemas", {}))
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


def _json_pointer(loc: Sequence[object]) -> str:
    """Build an RFC 6901 JSON Pointer from a FastAPI/Pydantic ``loc`` tuple.

    Strips only a leading ``body`` / ``query`` / ``path`` / ``header`` marker,
    then escapes ``~`` and ``/`` in remaining segments.
    """
    parts = list(loc)
    if parts and parts[0] in {"body", "query", "path", "header"}:
        parts = parts[1:]
    if not parts:
        return "#"
    escaped = [
        str(part).replace("~", "~0").replace("/", "~1") for part in parts
    ]
    return "#/" + "/".join(escaped)


app = create_app()
