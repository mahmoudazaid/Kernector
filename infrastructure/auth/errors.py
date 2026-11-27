"""Errors for the local auth SQLite store (#182)."""


class AuthStoreError(RuntimeError):
    """SQLite access to auth tables failed."""


class DuplicateUsernameError(AuthStoreError):
    """A user with the same username already exists."""


class UserNotFoundError(AuthStoreError):
    """No user matched the lookup."""


class MembershipRequiredError(AuthStoreError):
    """Project grant requires an active workspace membership."""
