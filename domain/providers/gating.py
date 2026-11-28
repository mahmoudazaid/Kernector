"""Pre-activation purpose gating for provider builders (#462)."""

from __future__ import annotations

from domain.errors import UnsupportedProviderPurposeError
from domain.providers.capabilities import Purpose, supports


def require_provider_purpose(provider: str, purpose: Purpose) -> None:
    """Raise when ``provider`` does not advertise ``purpose``.

    Raises:
        UnknownProviderError: ``provider`` is not registered.
        UnsupportedProviderPurposeError: purpose is not advertised.
    """
    if not supports(provider, purpose):
        raise UnsupportedProviderPurposeError(
            "Provider does not support this purpose."
        )
