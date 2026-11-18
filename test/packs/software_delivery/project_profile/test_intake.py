"""Client-supplied profile evidence intake (#387 slice 2)."""

from __future__ import annotations

import pytest

from packs.software_delivery.project_profile.errors import ProjectProfileValidationError
from packs.software_delivery.project_profile.intake import ingest_profile_evidence
from packs.software_delivery.project_profile.limits import (
    MAX_PROFILE_FILE_BYTES,
    MAX_PROFILE_FILES,
)
from packs.software_delivery.project_profile.models import IMPLICIT_COMPONENT


def test_ingest_normalizes_paths_and_hashes_content() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "oie-orders",
                "files": [{"path": "pyproject.toml", "content": "[project]\nname='x'\n"}],
            }
        ]
    )
    assert evidence.evidence_origin == "client_supplied"
    assert evidence.untrusted_evidence is True
    assert len(evidence.components) == 1
    file = evidence.components[0].files[0]
    assert file.path == "pyproject.toml"
    assert file.content_hash
    assert file.content.startswith("[project]")


def test_unlabelled_group_becomes_implicit_component() -> None:
    evidence = ingest_profile_evidence(
        [{"files": [{"path": "README.md", "content": "hello\n"}]}]
    )
    assert evidence.components[0].label == IMPLICIT_COMPONENT


def test_rejects_unsafe_paths() -> None:
    for path in (
        "/etc/passwd",
        "../secret",
        "C:\\windows\\system32",
        "foo\\bar",
        "~/.ssh/id_rsa",
    ):
        with pytest.raises(ProjectProfileValidationError):
            ingest_profile_evidence(
                [{"files": [{"path": path, "content": "x\n"}]}]
            )


def test_rejects_duplicate_path_within_component() -> None:
    with pytest.raises(ProjectProfileValidationError, match="duplicate"):
        ingest_profile_evidence(
            [
                {
                    "component": "oie-web",
                    "files": [
                        {"path": "package.json", "content": "{}\n"},
                        {"path": "package.json", "content": '{"a":1}\n'},
                    ],
                }
            ]
        )


def test_rejects_duplicate_component_labels() -> None:
    with pytest.raises(ProjectProfileValidationError, match="duplicate component label"):
        ingest_profile_evidence(
            [
                {"files": [{"path": "components/A.tsx", "content": "x\n"}]},
                {"files": [{"path": "components/B.tsx", "content": "y\n"}]},
            ]
        )


def test_rejects_unsupported_fields_without_list_repr() -> None:
    with pytest.raises(
        ProjectProfileValidationError, match="unsupported fields: extra"
    ) as caught:
        ingest_profile_evidence(
            [{"files": [{"path": "a.txt", "content": "x\n"}], "extra": 1}]
        )
    assert "[" not in str(caught.value)


def test_same_path_allowed_across_components() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "oie-web",
                "files": [{"path": "package.json", "content": '{"name":"web"}\n'}],
            },
            {
                "component": "oie-e2e",
                "files": [{"path": "package.json", "content": '{"name":"e2e"}\n'}],
            },
        ]
    )
    assert len(evidence.components) == 2
    assert evidence.components[0].files[0].path == "package.json"
    assert evidence.components[1].files[0].path == "package.json"
    assert (
        evidence.components[0].files[0].content_hash
        != evidence.components[1].files[0].content_hash
    )


def test_drops_secret_filename_with_sanitized_diagnostic() -> None:
    secret = "super-secret-password-never-leak"
    evidence = ingest_profile_evidence(
        [
            {
                "component": "oie-orders",
                "files": [
                    {"path": "pyproject.toml", "content": "[project]\n"},
                    {"path": ".env", "content": f"SECRET_DATABASE_PASSWORD={secret}\n"},
                ],
            }
        ]
    )
    paths = [f.path for f in evidence.components[0].files]
    assert paths == ["pyproject.toml"]
    assert any(".env" in d and "excluded" in d for d in evidence.diagnostics)
    joined = "\n".join(evidence.diagnostics)
    assert secret not in joined


def test_drops_secret_bearing_content_without_echoing_value() -> None:
    token = "sk_live_fixture_secret_value_do_not_echo"
    evidence = ingest_profile_evidence(
        [
            {
                "files": [
                    {
                        "path": "config.txt",
                        "content": f"API_KEY={token}\n",
                    }
                ]
            }
        ]
    )
    assert evidence.components[0].files == ()
    assert any("secret" in d.lower() for d in evidence.diagnostics)
    assert token not in "\n".join(evidence.diagnostics)


def test_rejects_too_many_files() -> None:
    files = [
        {"path": f"f{i}.txt", "content": "x\n"} for i in range(MAX_PROFILE_FILES + 1)
    ]
    with pytest.raises(ProjectProfileValidationError, match="files"):
        ingest_profile_evidence([{"files": files}])


def test_rejects_oversized_file() -> None:
    content = "a" * (MAX_PROFILE_FILE_BYTES + 1)
    with pytest.raises(ProjectProfileValidationError, match="large|bytes|size"):
        ingest_profile_evidence([{"files": [{"path": "big.txt", "content": content}]}])


def test_drops_null_byte_content_with_diagnostic() -> None:
    evidence = ingest_profile_evidence(
        [{"files": [{"path": "bin.dat", "content": "ok\x00bad"}]}]
    )
    assert evidence.components[0].files == ()
    assert any("binary" in d.lower() or "null" in d.lower() for d in evidence.diagnostics)
