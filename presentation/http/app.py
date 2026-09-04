"""FastAPI application factory for the HTTP presentation adapter."""

from __future__ import annotations

import os
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from presentation.http.errors import (
    Problem,
    ProblemError,
    problem_from_exception,
    problem_from_validation_errors,
)
from presentation.http.routes import capabilities as capabilities_routes
from presentation.http.routes import health as health_routes

_PROBLEM_MEDIA_TYPE = "application/problem+json"


def cors_origins_from_env() -> tuple[str, ...]:
    """Resolve CORS allowlist from environment.

    Origins are allowed only when ``HTTP_DEV_CORS`` is truthy. Production and
    unset defaults yield an empty allowlist (never ``*``).
    """
    flag = os.getenv("HTTP_DEV_CORS", "").strip().lower()
    if flag not in {"1", "true", "yes"}:
        return ()
    raw = os.getenv("HTTP_CORS_ORIGINS", "http://localhost:3000")
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())


def _problem_response(problem: Problem) -> JSONResponse:
    payload = problem.model_dump(exclude_none=True)
    return JSONResponse(
        status_code=problem.status,
        content=payload,
        media_type=_PROBLEM_MEDIA_TYPE,
    )


def create_app(*, cors_origins: Sequence[str] | None = None) -> FastAPI:
    """Build the HTTP adapter application.

    Args:
        cors_origins: Explicit allowlist for tests and callers. When ``None``,
            origins are read via :func:`cors_origins_from_env`.
    """
    app = FastAPI(
        title="Kernector API",
        version="0.1.0",
        description="Minimal versioned HTTP adapter over composition.",
    )
    origins = list(cors_origins_from_env() if cors_origins is None else cors_origins)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["*"],
        )

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
            return _problem_response(problem)
        problem = Problem(
            type=f"https://kernector.dev/problems/http_{exc.status_code}",
            title="HTTP error",
            status=exc.status_code,
            detail="The request could not be completed.",
            code=f"http_{exc.status_code}",
            instance=str(request.url.path),
        )
        return _problem_response(problem)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        problem = problem_from_exception(exc, instance=str(request.url.path))
        return _problem_response(problem)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        """Browsers probe this automatically; avoid a noisy Problem Details 404."""
        return Response(status_code=204)

    app.include_router(health_routes.router)
    app.include_router(capabilities_routes.router)
    return app


def _json_pointer(loc: Sequence[object]) -> str:
    parts = [str(part) for part in loc if part != "body"]
    if not parts:
        return "#"
    return "#/" + "/".join(parts)


app = create_app()
