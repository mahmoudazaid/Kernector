"""Tool adapter for ``software_delivery.export_test_cases_google_drive``."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence

from domain.artifacts import Artifact
from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorUnavailableError,
    ToolFailureError,
)
from domain.ports import ArtifactUploader
from packs.software_delivery.errors import GoogleDriveExportValidationError
from packs.software_delivery.limits import (
    DEFAULT_EXPORT_FILE_NAME,
    MAX_EXPORT_ARTIFACT_BYTES,
    MAX_EXPORT_DOCUMENT_TITLE_CHARS,
    MAX_EXPORT_FILE_NAME_CHARS,
    MAX_EXPORT_TITLE_CHARS,
    MAX_EXPORT_TITLES,
)

TOOL_NAME = "software_delivery.export_test_cases_google_drive"
TOOL_DESCRIPTION = (
    "Export selected Software Delivery test-case titles to Google Drive "
    "as Markdown."
)

_ALLOWED_ROOT_KEYS = frozenset(
    {"document_title", "titles", "file_name", "folder_id"}
)
_ALLOWED_ROOT_KEYS_DISPLAY = str(sorted(_ALLOWED_ROOT_KEYS))
_MARKDOWN_MEDIA_TYPE = "text/markdown"
_MSG_RENDER_FAILED = "Markdown rendering failed."
_MSG_UPLOAD_UNAVAILABLE = "Google Drive is temporarily unavailable."
_MSG_UPLOAD_FAILED = "Google Drive export failed."
_UNSAFE_FILE_CHARS = frozenset('<>:"|?*')
_CONTROL_OR_SEP = re.compile(r"[\x00-\x1f\x7f/\\]")
_SLUG_KEEP = re.compile(r"[^\w\-]+", re.UNICODE)
_FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

RenderExportMarkdown = Callable[[str, Sequence[str]], str]


class ExportTestCasesGoogleDriveTool:
    """Implements ``domain.ports.Tool`` for titles-only Drive export."""

    def __init__(
        self,
        *,
        render: RenderExportMarkdown,
        uploader: ArtifactUploader,
    ) -> None:
        self._render = render
        self._uploader = uploader

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        """Validate titles-only args, render, upload, and return a safe receipt.

        Raises:
            GoogleDriveExportValidationError: Invalid or incomplete arguments.
            ConnectorAuthError: Propagated so composition can surface reauth.
            ToolFailureError: Render or upload failed after valid arguments.
        """
        document_title, titles, file_name, folder_id = _parse_request(arguments)
        try:
            markdown = self._render(document_title, titles)
        except ToolFailureError:
            raise
        except Exception as exc:  # noqa: BLE001 - map unexpected renderer failures
            raise ToolFailureError(_MSG_RENDER_FAILED) from exc
        if not isinstance(markdown, str):
            raise ToolFailureError(_MSG_RENDER_FAILED)
        content = markdown.encode("utf-8")
        if len(content) > MAX_EXPORT_ARTIFACT_BYTES:
            raise ToolFailureError(_MSG_RENDER_FAILED)
        artifact = Artifact(
            file_name=file_name,
            media_type=_MARKDOWN_MEDIA_TYPE,
            content=content,
        )
        try:
            receipt = self._uploader.upload(artifact, parent_id=folder_id)
        except ToolFailureError:
            raise
        except ConnectorAuthError:
            raise
        except ConnectorUnavailableError as exc:
            raise ToolFailureError(_MSG_UPLOAD_UNAVAILABLE) from exc
        except ConnectorError as exc:
            raise ToolFailureError(_MSG_UPLOAD_FAILED) from exc
        except Exception as exc:  # noqa: BLE001 - map unexpected uploader failures
            raise ToolFailureError(_MSG_UPLOAD_FAILED) from exc
        return json.dumps(
            {"file_id": receipt.artifact_id, "file_name": receipt.file_name},
            separators=(",", ":"),
        )


def _parse_request(
    arguments: Mapping[str, object],
) -> tuple[str, tuple[str, ...], str, str]:
    if not isinstance(arguments, Mapping):
        raise GoogleDriveExportValidationError(
            f"arguments must be a mapping, got {type(arguments).__name__}"
        )
    _validate_mapping_keys(arguments, field_name="arguments")
    unknown = set(arguments) - _ALLOWED_ROOT_KEYS
    if unknown:
        raise GoogleDriveExportValidationError(
            f"unknown argument keys: {len(unknown)} not in "
            f"{_ALLOWED_ROOT_KEYS_DISPLAY}"
        )
    if "document_title" not in arguments:
        raise GoogleDriveExportValidationError("document_title is required")
    if "titles" not in arguments:
        raise GoogleDriveExportValidationError("titles is required")
    if "folder_id" not in arguments:
        raise GoogleDriveExportValidationError("folder_id is required")

    document_title = _require_bounded_str(
        arguments["document_title"],
        "document_title",
        MAX_EXPORT_DOCUMENT_TITLE_CHARS,
    )
    titles = _parse_titles(arguments["titles"])
    folder_id = _validate_folder_id(arguments["folder_id"])
    raw_file_name = arguments.get("file_name")
    if raw_file_name is None:
        file_name = _default_file_name(document_title)
    else:
        file_name = _validate_file_name(raw_file_name)
    return document_title, titles, file_name, folder_id


def _parse_titles(raw: object) -> tuple[str, ...]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise GoogleDriveExportValidationError(
            f"titles must be a sequence, got {type(raw).__name__}"
        )
    if len(raw) == 0:
        raise GoogleDriveExportValidationError("titles must be non-empty")
    if len(raw) > MAX_EXPORT_TITLES:
        raise GoogleDriveExportValidationError(
            f"titles must have at most {MAX_EXPORT_TITLES} items, got {len(raw)}"
        )
    titles: list[str] = []
    for index, item in enumerate(raw):
        titles.append(
            _require_bounded_str(
                item,
                f"titles[{index}]",
                MAX_EXPORT_TITLE_CHARS,
            )
        )
    return tuple(titles)


def _validate_mapping_keys(mapping: Mapping[object, object], *, field_name: str) -> None:
    for key in mapping:
        if not isinstance(key, str) or not key.strip():
            raise GoogleDriveExportValidationError(
                f"{field_name} keys must be non-blank strings, got {type(key).__name__}"
            )


def _require_nonblank_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GoogleDriveExportValidationError(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    if not value.strip():
        raise GoogleDriveExportValidationError(f"{field_name} must be non-empty")
    return value


def _validate_folder_id(value: object) -> str:
    if not isinstance(value, str):
        raise GoogleDriveExportValidationError(
            f"folder_id must be a non-empty string, got {type(value).__name__}"
        )
    stripped = value.strip()
    if not stripped or not _FOLDER_ID.fullmatch(stripped):
        raise GoogleDriveExportValidationError("folder_id is invalid")
    return stripped


def _require_bounded_str(value: object, field_name: str, max_chars: int) -> str:
    text = _require_nonblank_str(value, field_name)
    if len(text) > max_chars:
        raise GoogleDriveExportValidationError(
            f"{field_name} must be at most {max_chars} characters, got {len(text)}"
        )
    return text


def _default_file_name(document_title: str) -> str:
    slug = _SLUG_KEEP.sub("-", document_title.strip()).strip("-_.")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        return DEFAULT_EXPORT_FILE_NAME
    candidate = f"{slug}.md"
    if len(candidate) > MAX_EXPORT_FILE_NAME_CHARS:
        stem_max = MAX_EXPORT_FILE_NAME_CHARS - 3
        candidate = f"{slug[:stem_max].rstrip('-_.')}.md"
    try:
        return _validate_file_name(candidate)
    except GoogleDriveExportValidationError:
        return DEFAULT_EXPORT_FILE_NAME


def default_export_file_name(document_title: str) -> str:
    """Public default Markdown file name for a document title (HITL preview)."""
    return _default_file_name(document_title)


def _validate_file_name(value: object) -> str:
    if not isinstance(value, str):
        raise GoogleDriveExportValidationError(
            f"file_name must be a non-empty string, got {type(value).__name__}"
        )
    name = value.strip()
    if not name:
        raise GoogleDriveExportValidationError("file_name must be non-empty")
    if name in {".", ".."}:
        raise GoogleDriveExportValidationError("file_name is invalid")
    if _CONTROL_OR_SEP.search(name):
        raise GoogleDriveExportValidationError(
            "file_name must not contain path separators or control characters"
        )
    if any(char in _UNSAFE_FILE_CHARS for char in name):
        raise GoogleDriveExportValidationError("file_name contains reserved characters")
    if not name.endswith(".md"):
        raise GoogleDriveExportValidationError("file_name must end with .md")
    if len(name) > MAX_EXPORT_FILE_NAME_CHARS:
        raise GoogleDriveExportValidationError(
            f"file_name must be at most {MAX_EXPORT_FILE_NAME_CHARS} characters, "
            f"got {len(name)}"
        )
    return name
