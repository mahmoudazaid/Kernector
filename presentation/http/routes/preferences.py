"""Per-user preferences routes (#182)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from application.auth.preferences import (
    catalog_allows_pair,
    project_preferences,
)
from composition.auth import build_auth_store, require_csrf, resolve_session
from presentation.http.auth_session import (
    CSRF_HEADER,
    with_no_store,
)
from presentation.http.deps import RuntimeSettingsDep, get_settings
from presentation.http.errors import Problem, problem_responses

router = APIRouter(prefix="/api/v1/me", tags=["preferences"])


class PreferencesResponse(BaseModel):
    provider: str | None = None
    model: str | None = None
    usable: bool = False


class PreferencesUpdate(BaseModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Authentication is required.")


@router.get(
    "/preferences",
    responses=problem_responses(401, 500),
)
def get_preferences(
    request: Request,
    response: Response,
    runtime: RuntimeSettingsDep,
) -> PreferencesResponse:
    settings = get_settings()
    auth = settings.auth
    store = build_auth_store(settings)
    resolved = resolve_session(
        store, auth, request.cookies.get(auth.cookie_name)
    )
    if resolved is None:
        raise _unauthorized()
    catalog = runtime.execute()
    stored = store.get_preferences(resolved.principal.user_id)
    view = project_preferences(
        catalog,
        provider=None if stored is None else stored.provider,
        model=None if stored is None else stored.model,
    )
    with_no_store(response)
    return PreferencesResponse(
        provider=view.provider,
        model=view.model,
        usable=view.usable,
    )


@router.put(
    "/preferences",
    responses=problem_responses(401, 403, 422, 500),
)
def put_preferences(
    body: PreferencesUpdate,
    request: Request,
    response: Response,
    runtime: RuntimeSettingsDep,
    x_csrf_token: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> PreferencesResponse:
    settings = get_settings()
    auth = settings.auth
    store = build_auth_store(settings)
    resolved = resolve_session(
        store, auth, request.cookies.get(auth.cookie_name)
    )
    if resolved is None:
        raise _unauthorized()
    if not require_csrf(x_csrf_token, resolved.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    catalog = runtime.execute()
    if not catalog_allows_pair(catalog, body.provider, body.model):
        problem = Problem(
            type="https://kernector.dev/problems/invalid_preferences",
            title="Invalid preferences",
            status=422,
            detail="provider/model pair is not available in the runtime catalog",
            code="invalid_preferences",
            instance=str(request.url.path),
        )
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content=problem.model_dump(exclude_none=True),
            media_type="application/problem+json",
            headers={"Cache-Control": "no-store"},
        )
    store.put_preferences(
        resolved.principal.user_id,
        provider=body.provider,
        model=body.model,
    )
    view = project_preferences(
        catalog, provider=body.provider, model=body.model
    )
    with_no_store(response)
    return PreferencesResponse(
        provider=view.provider,
        model=view.model,
        usable=view.usable,
    )
