"""Run the offline RAG and tool eval harness, with optional LLM-as-Judge.

Run with::

    uv run python -m presentation.cli.evaluate [--output DIR] [--judge-mode off]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from application.errors import ApplicationValidationError, ConfigurationError
from application.evaluate_rag import rag_judge_report_to_csv, rag_judge_report_to_json
from application.evaluation_contracts import eval_report_to_json, eval_report_to_markdown
from application.rag_judge_contracts import RagJudgeReport
from composition.errors import KnowledgeLoadError
from composition.evaluate import (
    JudgeSkipped,
    build_evaluate_knowledge,
    load_eval_cases,
    run_rag_judge,
)
from domain.errors import DomainValidationError, ProviderError, VectorStoreError

_DEFAULT_OUTPUT = "output/eval"
_JUDGE_MODES = ("off", "live", "fake", "auto")


def main(argv: Sequence[str] | None = None) -> int:
    """Load the curated suite, score it offline, and write JSON plus Markdown.

    Args:
        argv (Sequence[str] | None): CLI arguments without the program name.
            Defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` when the suite completed with no failures and every required
        class was configured (and live Judge passed when enabled),
        ``1`` when the suite completed with failures, required classes were
        missing, or an eligible live quality gate failed,
        ``2`` for invalid argv, missing/malformed dataset, configuration
        errors, skipped ``auto``, fake/ineligible Judge, or refused baseline.
    """
    parser = argparse.ArgumentParser(
        prog="python -m presentation.cli.evaluate",
        description="Run the offline RAG and tool eval harness.",
    )
    parser.add_argument(
        "--output",
        default=_DEFAULT_OUTPUT,
        help="Directory for eval-report.json and eval-report.md",
    )
    parser.add_argument(
        "--judge-mode",
        choices=_JUDGE_MODES,
        default="off",
        help="off: #102 offline only. live/fake/auto: also write rag-judge reports.",
    )
    try:
        args = parser.parse_args(None if argv is None else list(argv))
    except SystemExit as error:
        if error.code in (0, None):
            return 0
        return 2

    try:
        use_case = build_evaluate_knowledge()
        cases = load_eval_cases()
        report = use_case.execute(cases)
    except (ApplicationValidationError, KnowledgeLoadError, ConfigurationError) as error:
        print(str(error), file=sys.stderr)
        return 2

    output_dir = Path(args.output)
    json_path = output_dir / "eval-report.json"
    md_path = output_dir / "eval-report.md"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(eval_report_to_json(report), encoding="utf-8")
        md_path.write_text(eval_report_to_markdown(report), encoding="utf-8")
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 1

    print(json_path)
    print(md_path)
    offline_code = _offline_exit_code(report)
    if args.judge_mode == "off":
        return offline_code

    try:
        judge_report = run_rag_judge(args.judge_mode, cases)
    except JudgeSkipped as error:
        print(str(error), file=sys.stderr)
        return 2
    except (ApplicationValidationError, KnowledgeLoadError, ConfigurationError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except (ProviderError, VectorStoreError, DomainValidationError):
        print("live Judge answer path failed", file=sys.stderr)
        return 2

    judge_json_path = output_dir / "rag-judge-report.json"
    judge_csv_path = output_dir / "rag-judge-report.csv"
    try:
        judge_json_path.write_text(
            rag_judge_report_to_json(judge_report), encoding="utf-8"
        )
        judge_csv_path.write_text(
            rag_judge_report_to_csv(judge_report), encoding="utf-8"
        )
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 2

    print(judge_json_path)
    print(judge_csv_path)
    return _combined_exit_code(offline_code, judge_report, args.judge_mode)


def _offline_exit_code(report: object) -> int:
    fail_count = getattr(report, "fail_count")
    if fail_count >= 1:
        return 1
    coverage = getattr(report, "coverage")
    unmet = sorted(
        name
        for name, entry in coverage.items()
        if entry.state == "skipped" and entry.reason == "no_case_configured"
    )
    if unmet:
        print(
            f"required eval classes not configured: {', '.join(unmet)}",
            file=sys.stderr,
        )
        return 1
    return 0


def _combined_exit_code(
    offline_code: int, judge_report: RagJudgeReport, mode: str
) -> int:
    if mode == "fake" or not judge_report.quality_gate_eligible:
        return 2
    if judge_report.gate_status == "refused_baseline":
        return 2
    if offline_code == 1:
        return 1
    if not judge_report.quality_gate_passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
