"""Composition tests for lazy domain tool pack registration."""

import importlib
from dataclasses import replace

import pytest

from application.errors import ConfigurationError
from composition import tool_registry as tool_registry_module
from composition.tool_registry import build_tool_registry
from infrastructure.config import DomainToolSettings, load_settings

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


def test_disabled_registry_does_not_import_software_delivery_pack(
    env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported: list[str] = []
    real_import = importlib.import_module

    def _spy(name: str, package: str | None = None):
        imported.append(name)
        return real_import(name, package)

    monkeypatch.setattr(tool_registry_module.importlib, "import_module", _spy)
    settings = load_settings()
    registry = build_tool_registry(settings)
    assert len(registry) == 0
    assert not any(
        name == "packs.software_delivery"
        or name.startswith("packs.software_delivery.")
        for name in imported
    )


def test_enabled_registry_imports_registration_module(
    env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported: list[str] = []
    real_import = importlib.import_module

    def _spy(name: str, package: str | None = None):
        imported.append(name)
        return real_import(name, package)

    monkeypatch.setattr(tool_registry_module.importlib, "import_module", _spy)
    env.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    registry = build_tool_registry(load_settings())
    assert TOOL_NAME in registry
    assert "packs.software_delivery.registration" in imported
