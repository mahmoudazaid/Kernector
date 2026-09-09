"""Suite-wide isolation from a developer ``.env``."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop ``load_settings`` from rewriting ``os.environ`` via ``.env``.

    ``load_runtime_settings`` calls ``load_dotenv(override=True)``. Without
    this, the first settings load permanently copies a developer's ``.env``
    into the process for the rest of the session.
    """
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
