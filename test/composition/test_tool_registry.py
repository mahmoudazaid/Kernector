"""Composition tests for lazy domain tool pack registration."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from application.errors import ConfigurationError
from composition.tool_registry import build_tool_registry
from infrastructure.config import DomainToolSettings, load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_NAME = "software_delivery.risk_score"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("DOMAIN_TOOL_PACKS", raising=False)
    return monkeypatch


def test_empty_config_builds_empty_registry(env: pytest.MonkeyPatch) -> None:
    settings = load_settings()
    registry = build_tool_registry(settings)
    assert len(registry) == 0
    assert registry.names() == ()


def test_software_delivery_registers_risk_tool(env: pytest.MonkeyPatch) -> None:
    env.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    settings = load_settings()
    registry = build_tool_registry(settings)
    assert registry.names() == (TOOL_NAME,)
    assert TOOL_NAME in registry
    tool = registry.get(TOOL_NAME)
    assert tool is not None
    assert tool.name == TOOL_NAME


def test_unknown_pack_id_is_configuration_error(env: pytest.MonkeyPatch) -> None:
    settings = load_settings()
    bad = replace(
        settings,
        domain_tools=DomainToolSettings(enabled_packs=("no-such-pack",)),
    )
    with pytest.raises(ConfigurationError, match="unknown domain tool pack"):
        build_tool_registry(bad)


def test_disabled_registry_does_not_import_software_delivery_pack() -> None:
    """Fresh interpreter: empty DOMAIN_TOOL_PACKS must not load the pack."""
    script = r"""
import sys
from dataclasses import replace

import infrastructure.config as config

config.load_dotenv = lambda *a, **k: False

from composition.tool_registry import build_tool_registry
from infrastructure.config import DomainToolSettings, load_settings

settings = replace(
    load_settings(),
    domain_tools=DomainToolSettings(enabled_packs=()),
)
registry = build_tool_registry(settings)
assert len(registry) == 0
assert registry.names() == ()
assert not any(
    name == "packs.software_delivery"
    or name.startswith("packs.software_delivery.")
    for name in sys.modules
)
print("ok", flush=True)
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT),
        "DOMAIN_TOOL_PACKS": "",
        "PYTHONUNBUFFERED": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "ok" in completed.stdout
