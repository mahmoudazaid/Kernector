"""Behavior tests for the OpenAPI export CLI used by the Next.js typed client."""

from __future__ import annotations

import json
from pathlib import Path

from presentation.cli import export_openapi as export_cli


def test_export_openapi_writes_health_and_problem(tmp_path: Path) -> None:
    """Exported document includes /health and Problem schema."""
    out = tmp_path / "openapi.json"
    code = export_cli.main(output_path=out)
    assert code == 0

    schema = json.loads(out.read_text(encoding="utf-8"))
    assert "/health" in schema["paths"]
    assert "HealthResponse" in schema["components"]["schemas"]
    assert "Problem" in schema["components"]["schemas"]
    assert out.read_text(encoding="utf-8").endswith("\n")


def test_export_openapi_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    """Two consecutive exports produce identical bytes."""
    out = tmp_path / "openapi.json"
    assert export_cli.main(output_path=out) == 0
    first = out.read_bytes()
    assert export_cli.main(output_path=out) == 0
    second = out.read_bytes()
    assert first == second
