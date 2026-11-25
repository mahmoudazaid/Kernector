"""Local user auth routes (#182)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from application.auth.login import LoginFailedError
from composition import Settings
from composition.auth import (
    build_auth_store,
    build_login,
    derive_session_csrf,
    require_csrf,
    resolve_session,
)
from presentation.http.auth_session import (
    CSRF_HEADER,
    GENERIC_LOGIN_FAILURE,
    clear_session_cookie,
    origin_is_trusted,
    request_wants_secure_cookie,
    set_session_cookie,
    with_no_store,
)
from presentation.http.deps import get_settings
from presentation.http.errors import problem_responses

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_USERNAME_MAX_LEN = 64


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=_USERNAME_MAX_LEN)
    password: str = Field(min_length=1, max_length=1024)


class MeResponse(BaseModel):
    user_id: str
    username: str
    csrf_token: str


def _settings() -> Settings:
    return get_settings()


@router.post(
    "/login",
    response_model=MeResponse,
    responses=problem_responses(401, 403, 415, 422, 500),
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    content_type: Annotated[str | None, Header(alias="Content-Type")] = None,
) -> MeResponse:
    """Authenticate and issue a fresh session cookie plus CSRF token."""
    settings = _settings()
    auth = settings.auth
    if content_type is None or "application/json" not in content_type.lower():
        raise HTTPException(status_code=415, detail="application/json required")
    origin = request.headers.get("origin")
    if not origin_is_trusted(origin, auth.trusted_origins):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    login_uc = build_login(settings)
    try:
        result = login_uc.execute(
            body.username,
            body.password,
            prior_session_id=request.cookies.get(auth.cookie_name),
        )
    except LoginFailedError as error:
        raise HTTPException(
            status_code=401, detail=GENERIC_LOGIN_FAILURE
        ) from error

    csrf = derive_session_csrf(auth, result.session_id)
    secure = request_wants_secure_cookie(request)
    set_session_cookie(
        response,
        cookie_name=auth.cookie_name,
        session_id=result.session_id,
        max_age=auth.session_ttl_seconds,
        secure=secure,
    )
    with_no_store(response)
    return MeResponse(
        user_id=result.principal.user_id,
        username=result.principal.username,
        csrf_token=csrf,
    )


@router.get(
    "/me",
    response_model=MeResponse,
    responses=problem_responses(401, 500),
)
def me(request: Request, response: Response) -> MeResponse:
    """Return the current principal and re-derived CSRF (no rotation)."""
    settings = _settings()
    auth = settings.auth
    store = build_auth_store(settings)
    resolved = resolve_session(
        store, auth, request.cookies.get(auth.cookie_name)
    )
    if resolved is None:
        raise HTTPException(status_code=401, detail="Authentication is required.")
    with_no_store(response)
    return MeResponse(
        user_id=resolved.principal.user_id,
        username=resolved.principal.username,
        csrf_token=resolved.csrf_token,
    )


@router.post(
    "/logout",
    status_code=204,
    response_class=Response,
    responses=problem_responses(401, 403, 500),
)
def logout(
    request: Request,
    response: Response,
    x_csrf_token: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> Response:
    """Revoke the session and clear the cookie. Requires CSRF."""
    settings = _settings()
    auth = settings.auth
    store = build_auth_store(settings)
    session_id = request.cookies.get(auth.cookie_name)
    resolved = resolve_session(store, auth, session_id)
    if resolved is None:
        raise HTTPException(status_code=401, detail="Authentication is required.")
    if not require_csrf(x_csrf_token, resolved.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    store.revoke_session(resolved.session_id)
    secure = request_wants_secure_cookie(request)
    out = Response(status_code=204)
    clear_session_cookie(out, cookie_name=auth.cookie_name, secure=secure)
    with_no_store(out)
    return out
