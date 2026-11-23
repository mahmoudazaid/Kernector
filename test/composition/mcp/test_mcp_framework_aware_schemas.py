"""Strict MCP schemas for framework-aware Test Design tools (#368)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from composition.mcp.test_design import (
    TestDesignConfirmProfileArgs,
    TestDesignGenerateFrameworkArgs,
)


def test_confirm_profile_args_require_evidence_not_profile_object() -> None:
    args = TestDesignConfirmProfileArgs.model_validate(
        {
            "draft_id": "draft-1",
            "expected_version": 2,
            "framework_id": "robot_framework",
            "profile_fingerprint": "fp",
            "evidence": [
                {
                    "component": "oie-tests",
                    "files": [{"path": "requirements.txt", "content": "robotframework\n"}],
                }
            ],
            "component_id": "oie-tests",
        }
    )
    assert args.framework_id == "robot_framework"
    with pytest.raises(ValidationError):
        TestDesignConfirmProfileArgs.model_validate(
            {
                "draft_id": "draft-1",
                "expected_version": 2,
                "framework_id": "robot_framework",
                "profile_fingerprint": "fp",
                "evidence": [],
            }
        )


def test_confirm_profile_forbids_extra_profile_field() -> None:
    with pytest.raises(ValidationError):
        TestDesignConfirmProfileArgs.model_validate(
            {
                "draft_id": "draft-1",
                "expected_version": 2,
                "framework_id": "robot_framework",
                "profile_fingerprint": "fp",
                "evidence": [
                    {"files": [{"path": "a.robot", "content": "*** Test Cases ***\n"}]}
                ],
                "profile": {"profile_fingerprint": "fp"},
            }
        )


def test_generate_framework_args_are_minimal() -> None:
    args = TestDesignGenerateFrameworkArgs.model_validate(
        {"draft_id": "draft-1", "expected_version": 3}
    )
    assert args.expected_version == 3
