"""Behavior tests for the offline eval CLI.

Every assertion goes through ``main()``. Composition collaborators are
monkeypatched at the symbols imported into ``presentation.cli.evaluate`` unless
the test is exercising dataset load errors through composition path constants.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.errors import ApplicationValidationError
from application.evaluation_contracts import (
    EVAL_SCHEMA_VERSION,
    REQUIRED_CASE_CLASSES,
    EvalAggregate,
    EvalCase,
    EvalCaseResult,
    EvalCoverageEntry,
    EvalReport,
    eval_report_to_dict,
)
from composition.errors import KnowledgeLoadError
from presentation.cli import evaluate as evaluate_cli


def _empty_coverage() -> dict[str, EvalCoverageEntry]:
    return {
        name: EvalCoverageEntry("skipped", "no_case_configured")
        for name in REQUIRED_CASE_CLASSES
    }


def _report(*, fail_count: int = 0, skip_count: int = 0) -> EvalReport:
    results: tuple[EvalCaseResult, ...] = ()
    if fail_count:
        results = (
            EvalCaseResult(
                case_id="fail-1",
                case_class="single_source",
                kind="retrieve",
                status="fail",
                metrics={"hit_at_k": 0.0, "mrr": 0.0, "source_recall_at_k": 0.0},
                checks={"hit_at_k": False},
                failed_checks=("hit_at_k",),
            ),
        )
        coverage = dict(_empty_coverage())
        coverage["single_source"] = EvalCoverageEntry("exercised")
    elif skip_count:
        results = (
            EvalCaseResult(
                case_id="tool-1",
                case_class="tool",
                kind="invoke_tool",
                status="skip",
                metrics={},
                checks={},
                failed_checks=(),
                skip_reason="tool_unavailable",
            ),
        )
        coverage = dict(_empty_coverage())
        coverage["tool"] = EvalCoverageEntry("skipped", "tool_unavailable")
    else:
        coverage = _empty_coverage()
    return EvalReport(
        schema_version=EVAL_SCHEMA_VERSION,
        mode="offline",
        results=results,
        pass_count=0,
        fail_count=fail_count,
        skip_count=skip_count,
        aggregates={
            "hit_at_k": EvalAggregate(0.0, 0),
            "mrr": EvalAggregate(0.0, 0),
            "source_recall_at_k": EvalAggregate(0.0, 0),
        },
        coverage=coverage,
    )


class _RecordingEvaluate:
    def __init__(self, report: EvalReport) -> None:
        self.report = report
        self.calls: list[object] = []

    def execute(self, cases: object) -> EvalReport:
        self.calls.append(cases)
        return self.report


def _patch_success(
    monkeypatch: pytest.MonkeyPatch,
    report: EvalReport,
    cases: tuple[EvalCase, ...] = (),
) -> _RecordingEvaluate:
    use_case = _RecordingEvaluate(report)
    monkeypatch.setattr(evaluate_cli, "build_evaluate_knowledge", lambda: use_case)
    monkeypatch.setattr(evaluate_cli, "load_eval_cases", lambda: cases)
    return use_case


def test_cli_writes_json_and_markdown_to_tmp_path_and_prints_both(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _report()
    output = tmp_path / "out"
    _patch_success(monkeypatch, report)

    code = evaluate_cli.main(["--output", str(output)])

    captured = capsys.readouterr()
    json_path = output / "eval-report.json"
    md_path = output / "eval-report.md"
    assert code == 0
    assert json_path.is_file()
    assert md_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload == eval_report_to_dict(report)
    markdown = md_path.read_text(encoding="utf-8")
    assert "schema_version: kernector.eval.v1" in markdown
    assert "mode: offline" in markdown
    assert "- pass: 0" in markdown
    assert str(json_path) in captured.out
    assert str(md_path) in captured.out
    assert captured.err == ""
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_cli_exit_zero_when_only_skips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_success(monkeypatch, _report(skip_count=1))

    code = evaluate_cli.main(["--output", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 0
    assert "Traceback" not in captured.err
    assert (tmp_path / "eval-report.json").is_file()


def test_cli_exit_one_when_failures_and_still_writes_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_success(monkeypatch, _report(fail_count=1))

    code = evaluate_cli.main(["--output", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 1
    assert (tmp_path / "eval-report.json").is_file()
    assert (tmp_path / "eval-report.md").is_file()
    assert "Traceback" not in captured.err


def test_cli_invalid_argv_returns_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = evaluate_cli.main(["--unknown"])

    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err


def test_cli_missing_dataset_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        evaluate_cli,
        "build_evaluate_knowledge",
        lambda: (_ for _ in ()).throw(
            KnowledgeLoadError("eval corpus not found: missing.json")
        ),
    )
    monkeypatch.setattr(evaluate_cli, "load_eval_cases", lambda: ())

    code = evaluate_cli.main(["--output", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 2
    assert "eval corpus not found" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert not (tmp_path / "eval-report.json").exists()


def test_cli_malformed_json_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        evaluate_cli,
        "build_evaluate_knowledge",
        lambda: _RecordingEvaluate(_report()),
    )
    monkeypatch.setattr(
        evaluate_cli,
        "load_eval_cases",
        lambda: (_ for _ in ()).throw(
            ApplicationValidationError("eval cases are not valid JSON")
        ),
    )

    code = evaluate_cli.main(["--output", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 2
    assert "eval cases are not valid JSON" in captured.err
    assert "Traceback" not in captured.err


def test_cli_invalid_case_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        evaluate_cli,
        "build_evaluate_knowledge",
        lambda: _RecordingEvaluate(_report()),
    )
    monkeypatch.setattr(
        evaluate_cli,
        "load_eval_cases",
        lambda: (_ for _ in ()).throw(
            ApplicationValidationError("tool_name is not allowed for kind retrieve")
        ),
    )

    code = evaluate_cli.main(["--output", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 2
    assert "tool_name is not allowed" in captured.err
    assert "Traceback" not in captured.err


def test_cli_unwritable_output_returns_one_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_success(monkeypatch, _report())
    output = tmp_path / "out"
    output.mkdir()
    (output / "eval-report.json").mkdir()

    code = evaluate_cli.main(["--output", str(output)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.strip()
    assert "Traceback" not in captured.err


def test_cli_malformed_cases_file_through_composition_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import composition.evaluate as eval_comp

    corpus = tmp_path / "corpus.json"
    cases = tmp_path / "cases.json"
    corpus.write_text(
        json.dumps(
            [
                {
                    "source_id": "doc-a",
                    "source_type": "knowledge_document",
                    "title": "A",
                    "content": "alpha token unique-here",
                }
            ]
        ),
        encoding="utf-8",
    )
    cases.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(eval_comp, "EVAL_CORPUS_PATH", corpus)
    monkeypatch.setattr(eval_comp, "EVAL_CASES_PATH", cases)

    code = evaluate_cli.main(["--output", str(tmp_path / "out")])

    captured = capsys.readouterr()
    assert code == 2
    assert "not valid JSON" in captured.err
    assert "Traceback" not in captured.err


def test_cli_invalid_kind_fields_through_composition_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import composition.evaluate as eval_comp

    corpus = tmp_path / "corpus.json"
    cases = tmp_path / "cases.json"
    corpus.write_text("[]", encoding="utf-8")
    cases.write_text(
        json.dumps(
            {
                "schema_version": EVAL_SCHEMA_VERSION,
                "cases": [
                    {
                        "id": "bad",
                        "case_class": "single_source",
                        "kind": "retrieve",
                        "query": "q",
                        "k": 5,
                        "expected_source_ids": ["a"],
                        "tool_name": "nope",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(eval_comp, "EVAL_CORPUS_PATH", corpus)
    monkeypatch.setattr(eval_comp, "EVAL_CASES_PATH", cases)

    code = evaluate_cli.main(["--output", str(tmp_path / "out")])

    captured = capsys.readouterr()
    assert code == 2
    assert "tool_name is not allowed" in captured.err
    assert "Traceback" not in captured.err


def test_cli_missing_cases_file_through_composition_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import composition.evaluate as eval_comp

    corpus = tmp_path / "corpus.json"
    corpus.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(eval_comp, "EVAL_CORPUS_PATH", corpus)
    monkeypatch.setattr(eval_comp, "EVAL_CASES_PATH", tmp_path / "absent.json")

    code = evaluate_cli.main(["--output", str(tmp_path / "out")])

    captured = capsys.readouterr()
    assert code == 2
    assert "eval cases not found" in captured.err
    assert "Traceback" not in captured.err


def test_cli_offline_dataset_writes_reports_to_tmp_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "out"

    code = evaluate_cli.main(["--output", str(output)])

    captured = capsys.readouterr()
    json_path = output / "eval-report.json"
    md_path = output / "eval-report.md"
    assert json_path.is_file()
    assert md_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "offline"
    assert payload["schema_version"] == EVAL_SCHEMA_VERSION
    assert set(payload["coverage"]) == set(REQUIRED_CASE_CLASSES)
    assert "Traceback" not in captured.err
    assert str(json_path) in captured.out
    assert code == 0
