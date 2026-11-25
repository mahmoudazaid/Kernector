"""Local user auth routes (#182)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from composition import Settings
from composition.auth import (
    build_auth_store,
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


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class MeResponse(BaseModel):
    user_id: str
    username: str
    csrf_token: str


def _settings() -> Settings:
    return get_settings()


@router.post(
    "/login",
    responses=problem_responses(401, 403, 415, 422, 500),
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    content_type: Annotated[str | None, Header(alias="Content-Type")] = None,
) -> dict:
    """Authenticate and issue a fresh session cookie plus CSRF token."""
    settings = _settings()
    auth = settings.auth
    if content_type is None or "application/json" not in content_type.lower():
        raise HTTPException(status_code=415, detail="application/json required")
    origin = request.headers.get("origin")
    if not origin_is_trusted(origin, auth.trusted_origins):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    store = build_auth_store(settings)
    if store.is_locked(body.username):
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_FAILURE)

    principal = store.authenticate(body.username, body.password)
    if principal is None:
        store.record_login_failure(
            body.username,
            max_failures=auth.login_max_failures,
            lockout_seconds=auth.login_lockout_seconds,
        )
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_FAILURE)

    store.clear_login_attempts(body.username)
    prior = request.cookies.get(auth.cookie_name)
    if prior:
        store.revoke_session(prior)

    session_id, _ = store.create_session(
        principal.user_id, ttl_seconds=auth.session_ttl_seconds
    )
    csrf = derive_session_csrf(auth, session_id)
    secure = request_wants_secure_cookie(request)
    set_session_cookie(
        response,
        cookie_name=auth.cookie_name,
        session_id=session_id,
        max_age=auth.session_ttl_seconds,
        secure=secure,
    )
    with_no_store(response)
    return {
        "user_id": principal.user_id,
        "username": principal.username,
        "csrf_token": csrf,
    }


@router.get(
    "/me",
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
