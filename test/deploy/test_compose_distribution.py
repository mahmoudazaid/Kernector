"""Offline checks for the self-hosted Compose distribution (#486)."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "compose.yaml"


def test_compose_file_exists() -> None:
    assert COMPOSE_PATH.is_file()


def test_compose_defines_required_services() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    for name in ("migrate:", "api:", "mcp:", "web:"):
        assert re.search(rf"^  {re.escape(name)}$", text, re.MULTILINE)


def test_migrate_runs_cli_and_api_depends_on_success() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "presentation.cli.migrate_sqlite" in text
    assert "service_completed_successfully" in text
    assert 'restart: "no"' in text or "restart: 'no'" in text or "restart: no" in text


def test_web_waits_for_healthy_api() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "service_healthy" in text


def test_services_use_healthchecks_not_sleeps() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "sleep" not in text.lower()
    assert text.count("healthcheck:") >= 3


def test_named_volume_persists_data() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "kernector-data:/data" in text
    assert "kernector-data:" in text


def test_images_target_ghcr() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "ghcr.io/mahmoudazaid/kernector-api:" in text
    assert "ghcr.io/mahmoudazaid/kernector-web:" in text


def test_api_image_build_declared_once() -> None:
    """migrate/mcp reuse the api image; parallel Bake must not race one tag."""
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert text.count("dockerfile: deploy/docker/Dockerfile.api") == 1
    assert "Dockerfile.api" in text


def test_dockerfiles_exist() -> None:
    assert (REPO_ROOT / "deploy/docker/Dockerfile.api").is_file()
    assert (REPO_ROOT / "deploy/docker/Dockerfile.web").is_file()


def test_self_hosted_docs_warn_about_down_v() -> None:
    docs = (REPO_ROOT / "docs/self-hosted-docker.md").read_text(encoding="utf-8")
    assert "docker compose down -v" in docs
    assert "docker compose up -d --pull always" in docs
