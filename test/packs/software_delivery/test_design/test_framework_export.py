"""Tests for packaging framework artifacts into the #359 file contract."""

from __future__ import annotations

from packs.software_delivery.test_design.framework_contracts import (
    FrameworkArtifactResult,
    FrameworkFile,
)
from packs.software_delivery.test_design.framework_export import package_framework_files


def test_package_ok_result_normalizes_paths_and_trailing_newline() -> None:
    result = FrameworkArtifactResult(
        status="ok",
        framework_id="robot_framework",
        files=(
            FrameworkFile(
                filename="cancel.robot",
                suggested_path="./tests/cancel.robot",
                content="*** Test Cases ***\nCancel\n",
            ),
        ),
        tests=(),
        implementation_required=(),
        skipped=(),
        untrusted_model_output=False,
        evidence_origin="client_supplied",
    )
    packaged = package_framework_files(result)
    assert packaged[0].suggested_path == "tests/cancel.robot"
    assert packaged[0].content.endswith("\n")


def test_package_unsupported_yields_no_files() -> None:
    result = FrameworkArtifactResult(
        status="unsupported_framework",
        framework_id="playwright",
        files=(),
        tests=(),
        implementation_required=(),
        skipped=(),
        untrusted_model_output=False,
        evidence_origin="client_supplied",
    )
    assert package_framework_files(result) == ()
