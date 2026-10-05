"""Shared ``SoftwareDeliveryRunView`` builders for presentation/composition tests.

Not collected by pytest: the basename lacks the ``test_`` prefix.
"""

from __future__ import annotations

from dataclasses import replace

from composition.software_delivery.tools import SoftwareDeliveryRunView
from composition.tools.runs import ToolCallView


def software_delivery_run_view(**changes: object) -> SoftwareDeliveryRunView:
    """Return a populated run view; pass dataclass fields to override.

    Defaults cover multi-element ``calls`` and a Drive export receipt so
    projection tests can pin ordering and multiplicity.
    """
    view = SoftwareDeliveryRunView(
        summary="Export finished.",
        calls=(
            ToolCallView(
                "pack.example_tool",
                ok=True,
                summary="Ran the example tool",
            ),
            ToolCallView(
                "software_delivery.export_test_cases_google_drive",
                ok=True,
                summary="Exported test cases to Google Drive",
            ),
        ),
        drive_file_id="file-1",
        drive_file_name="test-cases.md",
        drive_destination_label="My Drive",
    )
    return replace(view, **changes)
