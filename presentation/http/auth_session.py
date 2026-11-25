"""Session cookie helpers for the HTTP adapter (#182)."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.responses import JSONResponse

NO_STORE = "no-store"
CSRF_HEADER = "X-CSRF-Token"
GENERIC_LOGIN_FAILURE = "Invalid username or password"
COOKIE_NAME_DEFAULT = "kernector_session"


def set_session_cookie(
    response: Response,
    *,
    cookie_name: str,
    session_id: str,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        key=cookie_name,
        value=session_id,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
        max_age=max_age,
    )


def clear_session_cookie(
    response: Response,
    *,
    cookie_name: str,
    secure: bool,
) -> None:
    response.delete_cookie(
        key=cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def request_wants_secure_cookie(request: Request) -> bool:
    """HTTPS determination for cookie Secure (direct API; BFF may override)."""
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    if forwarded:
        return forwarded.lower() == "https"
    return request.url.scheme == "https"


def origin_is_trusted(origin: str | None, trusted: tuple[str, ...]) -> bool:
    if origin is None:
        return False
    return origin in trusted


def with_no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = NO_STORE
    return response


def json_no_store(content: dict, *, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(content=content, status_code=status_code)
    response.headers["Cache-Control"] = NO_STORE
    return response
