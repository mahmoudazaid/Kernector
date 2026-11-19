"""Interim Admin API bearer gate (#324)."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from composition.mcp_access.admin_auth import require_admin_api_token_from_env

_UNAUTHORIZED = HTTPException(
    status_code=401,
    detail="Unauthorized",
    headers={"WWW-Authenticate": "Bearer"},
)


def require_admin(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Reject the request unless ``Authorization: Bearer ${ADMIN_API_TOKEN}``.

    Fail closed when ``ADMIN_API_TOKEN`` is unset. Never include the presented
    or configured secret in the exception detail.
    """
    try:
        expected = require_admin_api_token_from_env()
    except ValueError as exc:
        raise _UNAUTHORIZED from exc
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise _UNAUTHORIZED
    presented = authorization[7:].strip()
    if not hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    ):
        raise _UNAUTHORIZED


AdminAuthDep = Annotated[None, Depends(require_admin)]
