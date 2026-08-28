"""Behavior tests for the knowledge-base ingest CLI.

Every assertion goes through ``main()``. Composition collaborators are
monkeypatched at the symbols imported into ``presentation.cli.ingest`` so
tests stay offline and never touch infrastructure.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from application.contracts import IngestRequest, IngestResponse
from application.errors import ApplicationValidationError, ConfigurationError
from composition import KnowledgeLoadError
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from presentation.cli import ingest as ingest_cli


def _document(source_id: str, doc_type: str) -> SourceDocument:
    return SourceDocument(
        metadata=SourceMetadata(
            reference=SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
            title=source_id,
            extra={"doc_type": doc_type},
        ),
        content=f"body for {source_id}",
    )


class _RecordingIngest:
    """Records the request and returns a fixed response."""

    def __init__(self, response: IngestResponse) -> None:
        self.response = response
        self.calls: list[IngestRequest] = []

    def execute(self, request: IngestRequest) -> IngestResponse:
        self.calls.append(request)
        return self.response


class _FailingIngest:
    """Raises when execute is called."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[IngestRequest] = []

    def execute(self, request: IngestRequest) -> IngestResponse:
        self.calls.append(request)
        raise self.error


def _patch_success(
    monkeypatch: pytest.MonkeyPatch,
    *,
    documents: Sequence[SourceDocument],
    response: IngestResponse,
    settings: object = object(),
) -> _RecordingIngest:
    use_case = _RecordingIngest(response)
    monkeypatch.setattr(ingest_cli, "load_runtime_settings", lambda: settings)
    monkeypatch.setattr(
        ingest_cli, "load_knowledge_documents", lambda _settings: tuple(documents)
    )
    monkeypatch.setattr(ingest_cli, "build_ingest_knowledge", lambda _settings: use_case)
    return use_case


def test_successful_ingest_prints_counts_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    documents = (
        _document("openapi-001", "openapi"),
        _document("bug-001", "bug"),
    )
    use_case = _patch_success(
        monkeypatch,
        documents=documents,
        response=IngestResponse(
            accepted_ids=["openapi-001", "bug-001"],
            chunk_count=5,
        ),
    )

    code = ingest_cli.main()

    captured = capsys.readouterr()
    assert code == 0
    assert len(use_case.calls) == 1
    request = use_case.calls[0]
    assert list(request.documents) == list(documents)
    assert "accepted_documents=2" in captured.out
    assert "chunk_count=5" in captured.out
    assert captured.err == ""
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_settings_configuration_failure_returns_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    load_docs_calls: list[object] = []
    build_calls: list[object] = []

    def _boom() -> object:
        raise ConfigurationError("CHUNK_SIZE must be an integer")

    monkeypatch.setattr(ingest_cli, "load_runtime_settings", _boom)
    monkeypatch.setattr(
        ingest_cli,
        "load_knowledge_documents",
        lambda settings: load_docs_calls.append(settings),
    )
    monkeypatch.setattr(
        ingest_cli,
        "build_ingest_knowledge",
        lambda settings: build_calls.append(settings),
    )

    code = ingest_cli.main()

    captured = capsys.readouterr()
    assert code == 2
    assert "CHUNK_SIZE must be an integer" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert load_docs_calls == []
    assert build_calls == []


def test_embedding_configuration_failure_returns_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    documents = (_document("openapi-001", "openapi"),)
    settings = object()

    monkeypatch.setattr(ingest_cli, "load_runtime_settings", lambda: settings)
    monkeypatch.setattr(
        ingest_cli, "load_knowledge_documents", lambda _settings: documents
    )
    monkeypatch.setattr(
        ingest_cli,
        "build_ingest_knowledge",
        lambda _settings: (_ for _ in ()).throw(
            ConfigurationError("Missing OPENROUTER_API_KEY")
        ),
    )

    code = ingest_cli.main()

    captured = capsys.readouterr()
    assert code == 2
    assert "Missing OPENROUTER_API_KEY" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_corpus_load_failure_returns_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = object()
    build_calls: list[object] = []

    monkeypatch.setattr(ingest_cli, "load_runtime_settings", lambda: settings)
    monkeypatch.setattr(
        ingest_cli,
        "load_knowledge_documents",
        lambda _settings: (_ for _ in ()).throw(
            KnowledgeLoadError("knowledge corpus not found: /tmp/absent.json")
        ),
    )
    monkeypatch.setattr(
        ingest_cli,
        "build_ingest_knowledge",
        lambda s: build_calls.append(s),
    )

    code = ingest_cli.main()

    captured = capsys.readouterr()
    assert code == 1
    assert "knowledge corpus not found" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert build_calls == []


def test_application_validation_failure_returns_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    documents = (_document("dup-001", "openapi"),)
    use_case = _FailingIngest(
        ApplicationValidationError("duplicate source reference")
    )
    monkeypatch.setattr(ingest_cli, "load_runtime_settings", lambda: object())
    monkeypatch.setattr(
        ingest_cli, "load_knowledge_documents", lambda _settings: documents
    )
    monkeypatch.setattr(ingest_cli, "build_ingest_knowledge", lambda _settings: use_case)

    code = ingest_cli.main()

    captured = capsys.readouterr()
    assert code == 1
    assert "duplicate source reference" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert len(use_case.calls) == 1


def test_module_main_guard_exits_zero_on_successful_ingest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``python -m presentation.cli.ingest`` runs ``main`` via the module guard."""
    import runpy
    import sys

    documents = (
        _document("openapi-001", "openapi"),
        _document("bug-001", "bug"),
    )
    use_case = _RecordingIngest(
        IngestResponse(accepted_ids=["openapi-001", "bug-001"], chunk_count=5)
    )

    # Patch composition exports so a fresh ``run_module`` import stays offline.
    monkeypatch.setattr(
        "composition.load_runtime_settings", lambda: object()
    )
    monkeypatch.setattr(
        "composition.load_knowledge_documents",
        lambda _settings: documents,
    )
    monkeypatch.setattr(
        "composition.build_ingest_knowledge",
        lambda _settings: use_case,
    )
    sys.modules.pop("presentation.cli.ingest", None)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("presentation.cli.ingest", run_name="__main__")

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert len(use_case.calls) == 1
    assert "accepted_documents=2" in captured.out
    assert "chunk_count=5" in captured.out
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_module_subprocess_exits_one_when_corpus_is_missing(
    tmp_path: Path,
) -> None:
    """Packaging smoke: discoverable ``-m`` entry exits 1 for a missing corpus."""
    import os
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    missing = tmp_path / "absent" / "corpus.json"
    chroma = tmp_path / "chroma"

    env = {
        **os.environ,
        "KNOWLEDGE_CORPUS_PATH": str(missing),
        "CHROMA_PERSIST_PATH": str(chroma),
        "OPENROUTER_API_KEY": "test-key",
        "OPENROUTER_BASE_URL": "https://openrouter.test/api/v1",
        "OPENROUTER_EMBEDDING_MODEL": "test/embedding-model",
    }
    # Prevent .env from overriding the missing corpus path.
    code = (
        "import infrastructure.config as config\n"
        "config.load_dotenv = lambda *a, **k: False\n"
        "import runpy\n"
        "runpy.run_module('presentation.cli.ingest', run_name='__main__')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    assert result.returncode == 1
    assert "knowledge corpus not found" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
