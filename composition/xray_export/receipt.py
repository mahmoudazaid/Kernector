"""Safe Xray creation receipt copy shared by chat projections (#199)."""

from __future__ import annotations

from collections.abc import Sequence


def xray_receipt_summary(
    created_keys: Sequence[str], failed_count: int, project_key: str | None = None
) -> str:
    """One line with counts, the project key, and created issue keys only."""
    count = len(created_keys)
    noun = "test" if count == 1 else "tests"
    summary = f"Created {count} Xray {noun}"
    if project_key:
        summary += f" in {project_key}"
    summary += f": {', '.join(created_keys)}." if created_keys else "."
    if failed_count:
        summary += f" {failed_count} could not be created."
    return summary
