"""Tool adapter for ``software_delivery.write_xray_keys_to_files`` (#399).

Pure: tags the caller's ``.robot`` / ``.feature`` scenarios with their Xray
keys and returns the full rewritten text plus a unified diff for the caller
to apply. It never reads or writes the disk or a repository and never calls
Jira/Xray.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import (
    TestFileValidationError,
    XrayKeyWritebackValidationError,
)
from packs.software_delivery.limits import (
    MAX_TEST_FILE_SCENARIOS,
    MAX_XRAY_KEY_WRITEBACK_RESULT_BYTES,
)
from packs.software_delivery.test_files.key_ownership import assign_keys
from packs.software_delivery.test_files.matching import reject_duplicate_identities
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.test_files.request import (
    parse_files,
    read_files,
    reject_duplicate_paths,
)
from packs.software_delivery.test_files.writeback import (
    WRITE_STATUSES,
    FileRewrite,
    rewrite_file,
)

TOOL_NAME = "software_delivery.write_xray_keys_to_files"
TOOL_DESCRIPTION = (
    "Tag the scenarios of Cucumber/Gherkin (.feature) and Robot Framework (.robot) "
    "files with their Xray test keys, so the next Xray sync updates those tests "
    "instead of creating duplicates. Use it after Xray tests were created or matched "
    "from files, or when the user asks to tag, stamp or write Xray keys into a test "
    "file. Read each file from the workspace yourself and pass its workspace-relative "
    "path and exact full text, unchanged, plus keys mapping path::scenario to the Xray "
    "key (the created map of the create tool, and the path, summary and key of its "
    "EXISTS_UNTAGGED results). Returns each file's full new text and a unified diff "
    "for you to apply; Kernector writes nothing and makes no Jira/Xray calls."
)

_ALLOWED_KEYS = frozenset({"files", "keys"})


class WriteXrayKeysToFilesTool:
    """Implements ``domain.ports.Tool``; no approval and no Jira/Xray client."""

    def __init__(
        self,
        tags: TestFileTagConfig,
        *,
        args_schema: type | None = None,
        output_schema: type | None = None,
    ) -> None:
        self._tags = tags
        self.args_schema = args_schema
        self.output_schema = output_schema

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        if not isinstance(arguments, Mapping):
            raise XrayKeyWritebackValidationError("arguments must be an object")
        if set(arguments) != _ALLOWED_KEYS:
            raise XrayKeyWritebackValidationError("arguments must contain only files and keys")
        files = read_files(arguments["files"], XrayKeyWritebackValidationError)
        keys = _read_keys(arguments["keys"])
        reject_duplicate_paths(files)
        parsed = parse_files(files, self._tags)
        reject_duplicate_identities(parsed, include_tagged=True)
        assigned = assign_keys(parsed, keys)
        rewrites = [
            rewrite_file(path, content, assigned.get(path, {}), self._tags)
            for path, content in files
        ]
        raw = _payload(rewrites)
        if len(raw.encode("utf-8")) > MAX_XRAY_KEY_WRITEBACK_RESULT_BYTES:
            raise TestFileValidationError(None, None, Reason.RESULT_TOO_LARGE)
        return raw


def _read_keys(keys: object) -> dict[str, str]:
    if not isinstance(keys, Mapping) or not keys:
        raise XrayKeyWritebackValidationError("keys must be a non-empty object")
    if len(keys) > MAX_TEST_FILE_SCENARIOS:
        raise XrayKeyWritebackValidationError(
            f"keys must have at most {MAX_TEST_FILE_SCENARIOS} entries"
        )
    for identity, key in keys.items():
        if not isinstance(identity, str) or not identity.strip() or not isinstance(key, str):
            raise XrayKeyWritebackValidationError(
                "keys must map path::scenario strings to Xray key strings"
            )
    return dict(keys)


def _payload(rewrites: list[FileRewrite]) -> str:
    counts = dict.fromkeys(WRITE_STATUSES, 0)
    results: list[dict[str, object]] = []
    for rewrite in rewrites:
        for scenario in rewrite.scenarios:
            counts[scenario.status] += 1
            results.append(
                {
                    "path": rewrite.path,
                    "line": scenario.line,
                    "summary": scenario.summary,
                    "key": scenario.key,
                    "previous_key": scenario.previous_key,
                    "status": scenario.status,
                }
            )
    return json.dumps(
        {
            "files": [
                {
                    "path": rewrite.path,
                    "changed": rewrite.changed,
                    "content": rewrite.content,
                    "diff": rewrite.diff,
                }
                for rewrite in rewrites
            ],
            "results": results,
            "counts": counts,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
