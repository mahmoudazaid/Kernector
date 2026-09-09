"""Run the offline RAG and tool eval harness.

Run with::

    uv run python -m presentation.cli.evaluate [--output DIR]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from application.errors import ApplicationValidationError, ConfigurationError
from application.evaluation_contracts import eval_report_to_json, eval_report_to_markdown
from composition.errors import KnowledgeLoadError
from composition.evaluate import build_evaluate_knowledge, load_eval_cases

_DEFAULT_OUTPUT = "output/eval"


def main(argv: Sequence[str] | None = None) -> int:
    """Load the curated suite, score it offline, and write JSON plus Markdown.

    Args:
        argv (Sequence[str] | None): CLI arguments without the program name.
            Defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` when the suite completed with no failures and every required
        class was configured,
        ``1`` when the suite completed with failures, required classes were
        missing, or report write failed,
        ``2`` for invalid argv, missing/malformed dataset, or configuration
        errors before execute.
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
    if report.fail_count >= 1:
        return 1
    unmet = sorted(
        name
        for name, entry in report.coverage.items()
        if entry.state == "skipped" and entry.reason == "no_case_configured"
    )
    if unmet:
        print(
            f"required eval classes not configured: {', '.join(unmet)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
