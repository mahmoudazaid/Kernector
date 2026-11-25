"""Local user authentication domain types (#182)."""

from domain.auth.principal import Principal, new_user_id

__all__ = ["Principal", "new_user_id"]


# Models and ports live in domain.auth.models / domain.auth.ports.
