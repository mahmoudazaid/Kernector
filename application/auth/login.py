"""Login use case: lockout, credential check, session rotation (#182)."""

from __future__ import annotations

from dataclasses import dataclass

from domain.auth.ports import AuthStore
from domain.auth.principal import Principal


class LoginFailedError(Exception):
    """Credentials rejected or account locked (generic to callers)."""


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Successful login: principal plus new plaintext session id."""

    principal: Principal
    session_id: str


@dataclass(frozen=True, slots=True)
class Login:
    """Authenticate a local user and issue a fresh session."""

    store: AuthStore
    max_failures: int
    lockout_seconds: int
    session_ttl_seconds: int

    def execute(
        self,
        username: str,
        password: str,
        *,
        prior_session_id: str | None = None,
    ) -> LoginResult:
        """Return a new session or raise :class:`LoginFailedError`."""
        claim = self.store.claim_login_attempt(
            username,
            max_failures=self.max_failures,
            lockout_seconds=self.lockout_seconds,
        )
        if claim == "locked":
            raise LoginFailedError()

        principal = self.store.authenticate(username, password)
        if principal is None:
            raise LoginFailedError()

        self.store.clear_login_attempts(username)
        if prior_session_id:
            self.store.revoke_session(prior_session_id)

        session_id, _ = self.store.create_session(
            principal.user_id, ttl_seconds=self.session_ttl_seconds
        )
        return LoginResult(principal=principal, session_id=session_id)
