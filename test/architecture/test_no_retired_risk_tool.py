"""The retired Software Delivery risk-score tool stays gone from tracked files."""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SELF = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
_FORBIDDEN = re.compile(
    r"risk_score|RiskScore|RiskFactor|RiskAssessment|RiskEvidence", re.IGNORECASE
)
_HISTORICAL_PREFIXES = ("docs/sprint-2-", "docs/sprint-3-")
_HISTORICAL_FILES = {_SELF}


def _tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    return [
        name
        for name in completed.stdout.decode("utf-8").split("\0")
        if name
        and name not in _HISTORICAL_FILES
        and not name.startswith(_HISTORICAL_PREFIXES)
    ]


def test_tracked_files_never_reference_the_retired_risk_tool() -> None:
    files = _tracked_files()
    offenders = []
    for name in files:
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders.extend(
            f"{name}: {match.group(0)}" for match in _FORBIDDEN.finditer(text)
        )

    assert files, "no tracked files were found"
    assert offenders == []
