"""Behavior tests for the filter-metadata reindex CLI."""

from __future__ import annotations

import pytest

from infrastructure.vectorstore.chroma import ChromaStoreError
from presentation.cli import reindex_filter_metadata as reindex_cli


def test_successful_reindex_prints_count_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(reindex_cli, "load_runtime_settings", lambda: object())
    monkeypatch.setattr(reindex_cli, "reindex_filter_metadata", lambda _settings: 7)

    code = reindex_cli.main()

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "rewritten_records=7"
    assert captured.err == ""


def test_store_failure_prints_to_stderr_and_returns_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(reindex_cli, "load_runtime_settings", lambda: object())

    def _boom(_settings: object) -> int:
        raise ChromaStoreError("could not rewrite collection")

    monkeypatch.setattr(reindex_cli, "reindex_filter_metadata", _boom)

    code = reindex_cli.main()

    captured = capsys.readouterr()
    assert code == 1
    assert "could not rewrite collection" in captured.err
    assert captured.out == ""
