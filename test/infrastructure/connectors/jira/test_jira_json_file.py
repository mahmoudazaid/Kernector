"""Atomic Jira JSON writes keep temp files under the gitignored target prefix."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from infrastructure.connectors.jira import json_file
from infrastructure.connectors.jira.json_file import atomic_write_json


@pytest.mark.parametrize("name", ["jira-oauth-connection.json", "jira-dc-connection.json"])
def test_temp_file_keeps_the_target_filename_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    target = tmp_path / name
    temp_names: list[str] = []
    real_replace = os.replace

    def _replace(src: str, dst: Path) -> None:
        temp_names.append(Path(src).name)
        real_replace(src, dst)

    monkeypatch.setattr(json_file.os, "replace", _replace)

    atomic_write_json(target, {"access_token": "secret"})

    [temp_name] = temp_names
    assert temp_name.startswith(f"{target.stem}-tmp-")
    assert temp_name.endswith(".json")
    assert json.loads(target.read_text(encoding="utf-8")) == {"access_token": "secret"}
    assert target.stat().st_mode & 0o777 == 0o600
