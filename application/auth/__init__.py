"""Application use cases for local auth (#182)."""

from application.auth.login import Login, LoginFailedError, LoginResult
from application.auth.preferences import (
    PreferenceView,
    catalog_allows_pair,
    project_preferences,
    require_catalog_pair,
)

__all__ = [
    "Login",
    "LoginFailedError",
    "LoginResult",
    "PreferenceView",
    "catalog_allows_pair",
    "project_preferences",
    "require_catalog_pair",
]
