"""Interim Admin API credential loader (#324)."""

from __future__ import annotations

from infrastructure.config import require_admin_api_token_from_env

__all__ = ["require_admin_api_token_from_env"]
