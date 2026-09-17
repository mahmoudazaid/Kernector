"""SQLite adapter for response feedback, bound to one workspace."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from domain.response_feedback import FeedbackRating, ResponseFeedback
from infrastructure.catalog import _connection
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import require_workspace_id
from infrastructure.feedback.errors import FeedbackStoreError

_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_SELECT_COLUMNS = (
    "workspace_id, request_id, rating, conversation_id, client_message_id, "
    "run_id, reason, comment, prompt_key, prompt_version, model, tools_json, "
    "created_at, updated_at"
)
_UPSERT_SQL = f"""
INSERT INTO response_feedback (
    {_SELECT_COLUMNS}
) VALUES (
    :workspace_id, :request_id, :rating, :conversation_id, :client_message_id,
    :run_id, :reason, :comment, :prompt_key, :prompt_version, :model, :tools_json,
    :created_at, :updated_at
)
ON CONFLICT (workspace_id, request_id) DO UPDATE SET
    rating = excluded.rating,
    conversation_id = excluded.conversation_id,
    client_message_id = excluded.client_message_id,
    run_id = excluded.run_id,
    reason = excluded.reason,
    comment = excluded.comment,
    prompt_key = excluded.prompt_key,
    prompt_version = excluded.prompt_version,
    model = excluded.model,
    tools_json = excluded.tools_json,
    updated_at = excluded.updated_at
"""


class SqlResponseFeedbackRepository:
    """Persist response feedback rows in SQLite, isolated to one workspace."""

    def __init__(self, path: Path, workspace_id: str) -> None:
        self._workspace_id = require_workspace_id(workspace_id)
        self._path = path
        try:
            apply_migrations(path, migrations_dir=_MIGRATIONS)
        except CatalogError as error:
            raise FeedbackStoreError(
                f"could not apply feedback migrations at {path}"
            ) from error

    def upsert(self, feedback: ResponseFeedback) -> ResponseFeedback:
        """Insert or replace the in-workspace rating for ``feedback.request_id``."""
        if feedback.workspace_id != self._workspace_id:
            raise FeedbackStoreError(
                "feedback.workspace_id does not match repository workspace"
            )
        params = _row_params(feedback)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT created_at FROM response_feedback "
                    "WHERE workspace_id = ? AND request_id = ?",
                    (self._workspace_id, feedback.request_id),
                ).fetchone()
                if existing is not None:
                    params["created_at"] = str(existing["created_at"])
                connection.execute(_UPSERT_SQL, params)
                connection.commit()
            except sqlite3.Error as error:
                connection.rollback()
                raise FeedbackStoreError(
                    f"could not write feedback at {self._path}"
                ) from error
            except Exception:
                connection.rollback()
                raise
        stored = self.get(feedback.request_id)
        if stored is None:
            raise FeedbackStoreError(
                f"feedback for request_id {feedback.request_id!r} missing after upsert"
            )
        return stored

    def get(self, request_id: str) -> ResponseFeedback | None:
        """Return the in-workspace rating for ``request_id``, or ``None``."""
        request_id = _require_request_id(request_id)
        with self._connect() as connection:
            try:
                row = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM response_feedback "
                    "WHERE workspace_id = ? AND request_id = ?",
                    (self._workspace_id, request_id),
                ).fetchone()
            except sqlite3.Error as error:
                raise FeedbackStoreError(
                    f"could not read feedback at {self._path}"
                ) from error
        if row is None:
            return None
        return _feedback_from_row(row)

    def delete(self, request_id: str) -> bool:
        """Remove the in-workspace rating. Return whether a row was deleted."""
        request_id = _require_request_id(request_id)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "DELETE FROM response_feedback "
                    "WHERE workspace_id = ? AND request_id = ?",
                    (self._workspace_id, request_id),
                )
                connection.commit()
            except sqlite3.Error as error:
                connection.rollback()
                raise FeedbackStoreError(
                    f"could not write feedback at {self._path}"
                ) from error
            except Exception:
                connection.rollback()
                raise
        return cursor.rowcount > 0

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = _connection.connect(self._path)
        except sqlite3.Error as error:
            raise FeedbackStoreError(
                f"could not open feedback database at {self._path}"
            ) from error
        try:
            yield connection
        finally:
            connection.close()


def _require_request_id(request_id: str) -> str:
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id must be a non-empty string")
    return request_id.strip()


def _row_params(feedback: ResponseFeedback) -> dict[str, Any]:
    return {
        "workspace_id": feedback.workspace_id,
        "request_id": feedback.request_id,
        "rating": feedback.rating,
        "conversation_id": feedback.conversation_id,
        "client_message_id": feedback.client_message_id,
        "run_id": feedback.run_id,
        "reason": feedback.reason,
        "comment": feedback.comment,
        "prompt_key": feedback.prompt_key,
        "prompt_version": feedback.prompt_version,
        "model": feedback.model,
        "tools_json": json.dumps(list(feedback.tools)),
        "created_at": feedback.created_at,
        "updated_at": feedback.updated_at,
    }


def _feedback_from_row(row: sqlite3.Row) -> ResponseFeedback:
    tools_raw = json.loads(str(row["tools_json"] or "[]"))
    tools = tuple(
        name for name in tools_raw if isinstance(name, str) and name.strip()
    )
    reason_raw = row["reason"]
    rating: FeedbackRating = str(row["rating"])  # type: ignore[assignment]
    return ResponseFeedback(
        workspace_id=str(row["workspace_id"]),
        request_id=str(row["request_id"]),
        rating=rating,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        conversation_id=_optional_str(row["conversation_id"]),
        client_message_id=_optional_str(row["client_message_id"]),
        run_id=_optional_str(row["run_id"]),
        reason=None if reason_raw is None else str(reason_raw),  # type: ignore[arg-type]
        comment=_optional_str(row["comment"]),
        prompt_key=_optional_str(row["prompt_key"]),
        prompt_version=_optional_str(row["prompt_version"]),
        model=_optional_str(row["model"]),
        tools=tools,
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
