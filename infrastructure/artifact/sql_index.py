"""SQLite ArtifactIndex bound to one workspace (catalog DB, migration 009)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from domain.artifact.models import (
    ArtifactDescriptor,
    ArtifactPart,
    ContextAssignment,
)
from domain.knowledge import SourceReference
from infrastructure.catalog import _connection
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import require_workspace_id


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _contexts_json(contexts: tuple[ContextAssignment, ...]) -> str:
    return json.dumps(
        [{"context": item.context, "reason": item.reason} for item in contexts]
    )


def _parts_json(parts: tuple[ArtifactPart, ...]) -> str:
    return json.dumps(
        [
            {
                "kind": part.kind,
                "part_key": part.part_key,
                "operation_id": part.operation_id,
                "summary": part.summary,
                "response_codes": list(part.response_codes),
            }
            for part in parts
        ]
    )


def _descriptor_from_row(row: sqlite3.Row) -> ArtifactDescriptor:
    contexts = tuple(
        ContextAssignment(item["context"], item["reason"])
        for item in json.loads(row["contexts_json"])
    )
    parts = tuple(
        ArtifactPart(
            kind=item["kind"],
            part_key=item["part_key"],
            operation_id=item.get("operation_id"),
            summary=item.get("summary"),
            response_codes=tuple(item.get("response_codes") or ()),
        )
        for item in json.loads(row["parts_json"])
    )
    return ArtifactDescriptor(
        reference=SourceReference(row["source_id"], row["source_type"]),
        revision=row["revision"],
        kind=row["kind"],
        contexts=contexts,
        component_ids=tuple(json.loads(row["component_ids_json"])),
        external_keys=tuple(json.loads(row["external_keys_json"])),
        parts=parts,
        title=row["title"],
        url=row["url"],
        diagnostic=row["diagnostic"],
    )


class SqlArtifactIndex:
    """Workspace-scoped artifact descriptor store."""

    def __init__(self, path: Path, workspace_id: str) -> None:
        self._path = path
        self._workspace_id = require_workspace_id(workspace_id)
        apply_migrations(path)

    def upsert(self, descriptor: ArtifactDescriptor) -> None:
        connection = _connection.connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO artifact_descriptors (
                    workspace_id, source_type, source_id, revision, kind,
                    title, url, diagnostic, contexts_json, component_ids_json,
                    parts_json, external_keys_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, source_type, source_id) DO UPDATE SET
                    revision = excluded.revision,
                    kind = excluded.kind,
                    title = excluded.title,
                    url = excluded.url,
                    diagnostic = excluded.diagnostic,
                    contexts_json = excluded.contexts_json,
                    component_ids_json = excluded.component_ids_json,
                    parts_json = excluded.parts_json,
                    external_keys_json = excluded.external_keys_json,
                    updated_at = excluded.updated_at
                """,
                (
                    self._workspace_id,
                    descriptor.reference.source_type,
                    descriptor.reference.source_id,
                    descriptor.revision,
                    descriptor.kind,
                    descriptor.title,
                    descriptor.url,
                    descriptor.diagnostic,
                    _contexts_json(descriptor.contexts),
                    json.dumps(list(descriptor.component_ids)),
                    _parts_json(descriptor.parts),
                    json.dumps(list(descriptor.external_keys)),
                    _now(),
                ),
            )
            connection.execute(
                """
                DELETE FROM artifact_external_keys
                WHERE workspace_id = ? AND source_type = ? AND source_id = ?
                """,
                (
                    self._workspace_id,
                    descriptor.reference.source_type,
                    descriptor.reference.source_id,
                ),
            )
            for key in descriptor.external_keys:
                connection.execute(
                    """
                    INSERT INTO artifact_external_keys (
                        workspace_id, external_key, source_type, source_id
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        self._workspace_id,
                        key,
                        descriptor.reference.source_type,
                        descriptor.reference.source_id,
                    ),
                )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def remove(self, reference: SourceReference) -> None:
        connection = _connection.connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM artifact_external_keys
                WHERE workspace_id = ? AND source_type = ? AND source_id = ?
                """,
                (self._workspace_id, reference.source_type, reference.source_id),
            )
            connection.execute(
                """
                DELETE FROM artifact_descriptors
                WHERE workspace_id = ? AND source_type = ? AND source_id = ?
                """,
                (self._workspace_id, reference.source_type, reference.source_id),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def get(self, reference: SourceReference) -> ArtifactDescriptor | None:
        connection = _connection.connect(self._path)
        try:
            row = connection.execute(
                """
                SELECT * FROM artifact_descriptors
                WHERE workspace_id = ? AND source_type = ? AND source_id = ?
                """,
                (self._workspace_id, reference.source_type, reference.source_id),
            ).fetchone()
            return _descriptor_from_row(row) if row is not None else None
        finally:
            connection.close()

    def find_by_key(self, keys: tuple[str, ...]) -> tuple[ArtifactDescriptor, ...]:
        if not keys:
            return ()
        connection = _connection.connect(self._path)
        try:
            placeholders = ", ".join("?" for _ in keys)
            rows = connection.execute(
                f"""
                SELECT DISTINCT d.*
                FROM artifact_descriptors AS d
                JOIN artifact_external_keys AS k
                  ON d.workspace_id = k.workspace_id
                 AND d.source_type = k.source_type
                 AND d.source_id = k.source_id
                WHERE d.workspace_id = ?
                  AND k.external_key IN ({placeholders})
                ORDER BY d.source_type COLLATE BINARY, d.source_id COLLATE BINARY
                """,
                (self._workspace_id, *keys),
            ).fetchall()
            return tuple(_descriptor_from_row(row) for row in rows)
        finally:
            connection.close()

    def list_for_scope(
        self, *, source_type: str | None = None
    ) -> tuple[ArtifactDescriptor, ...]:
        connection = _connection.connect(self._path)
        try:
            if source_type is None:
                rows = connection.execute(
                    """
                    SELECT * FROM artifact_descriptors
                    WHERE workspace_id = ?
                    ORDER BY source_type COLLATE BINARY, source_id COLLATE BINARY
                    """,
                    (self._workspace_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM artifact_descriptors
                    WHERE workspace_id = ? AND source_type = ?
                    ORDER BY source_id COLLATE BINARY
                    """,
                    (self._workspace_id, source_type),
                ).fetchall()
            return tuple(_descriptor_from_row(row) for row in rows)
        finally:
            connection.close()
