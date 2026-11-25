"""SQLite RelationshipStore bound to one workspace (catalog DB, migration 010)."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from domain.artifact.models import ArtifactRef
from domain.knowledge import SourceReference
from domain.relationship.errors import RelationshipInputError
from domain.relationship.models import (
    VERIFICATION_REJECTED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
    Relationship,
    UnresolvedKey,
)
from infrastructure.catalog import _connection
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import require_workspace_id

_KIND_REF = "ref"
_KIND_UNRESOLVED = "unresolved"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_relationship_id() -> str:
    """Return a new opaque relationship identifier."""
    return f"rel_{uuid.uuid4().hex}"


def endpoint_token(endpoint: ArtifactRef | UnresolvedKey) -> str:
    """Stable identity token for an edge endpoint."""
    if isinstance(endpoint, UnresolvedKey):
        part = endpoint.part_key or ""
        return f"u:{endpoint.key}\n{part}"
    part = endpoint.part_key or ""
    return (
        f"r:{endpoint.reference.source_type}\n"
        f"{endpoint.reference.source_id}\n{part}"
    )


def unresolved_token(key: str, *, part_key: str | None = None) -> str:
    """Identity token for an unresolved external key."""
    return f"u:{key}\n{part_key or ''}"


def _endpoint_columns(
    endpoint: ArtifactRef | UnresolvedKey, prefix: str
) -> dict[str, str | None]:
    if isinstance(endpoint, UnresolvedKey):
        return {
            f"{prefix}_kind": _KIND_UNRESOLVED,
            f"{prefix}_source_type": None,
            f"{prefix}_source_id": None,
            f"{prefix}_part_key": endpoint.part_key,
            f"{prefix}_unresolved_key": endpoint.key,
        }
    return {
        f"{prefix}_kind": _KIND_REF,
        f"{prefix}_source_type": endpoint.reference.source_type,
        f"{prefix}_source_id": endpoint.reference.source_id,
        f"{prefix}_part_key": endpoint.part_key,
        f"{prefix}_unresolved_key": None,
    }


def _endpoint_from_row(row: sqlite3.Row, prefix: str) -> ArtifactRef | UnresolvedKey:
    kind = row[f"{prefix}_kind"]
    if kind == _KIND_UNRESOLVED:
        return UnresolvedKey(
            row[f"{prefix}_unresolved_key"],
            part_key=row[f"{prefix}_part_key"],
        )
    return ArtifactRef(
        SourceReference(row[f"{prefix}_source_id"], row[f"{prefix}_source_type"]),
        part_key=row[f"{prefix}_part_key"],
    )


def _prefer_resolved(
    current: ArtifactRef | UnresolvedKey, incoming: ArtifactRef | UnresolvedKey
) -> ArtifactRef | UnresolvedKey:
    if isinstance(incoming, ArtifactRef):
        return incoming
    if isinstance(current, ArtifactRef):
        return current
    return incoming


def _verification_priority(verification: str) -> int:
    """Higher means a stronger human decision that should survive merges."""
    if verification == VERIFICATION_REJECTED:
        return 2
    if verification == VERIFICATION_VERIFIED:
        return 1
    return 0


def _pick_merge_survivor(matches: Sequence[sqlite3.Row]) -> sqlite3.Row:
    """Prefer rejected, then confirmed, then earliest first_seen_at, then id."""

    def rank(row: sqlite3.Row) -> tuple[int, str, str]:
        # Negate priority so min() prefers the strongest decision.
        return (
            -_verification_priority(row["verification"]),
            row["first_seen_at"],
            row["relationship_id"],
        )

    return min(matches, key=rank)


class SqlRelationshipStore:
    """Workspace-scoped evidence-backed relationship store."""

    def __init__(self, path: Path, workspace_id: str) -> None:
        self._path = path
        self._workspace_id = require_workspace_id(workspace_id)
        apply_migrations(path)

    def upsert_from_evidence(
        self,
        *,
        project_id: str,
        subject: ArtifactRef | UnresolvedKey,
        relation_type: str,
        object: ArtifactRef | UnresolvedKey,
        origin: str,
        verification: str,
        confidence: float,
        freshness: str,
        evidence: EvidenceRef,
        seen_at: str,
        subject_aliases: tuple[str, ...] = (),
        object_aliases: tuple[str, ...] = (),
    ) -> Relationship:
        # Validate create-time invariants before opening a write transaction.
        Relationship(
            relationship_id=new_relationship_id(),
            project_id=project_id,
            subject=subject,
            relation_type=relation_type,
            object=object,
            origin=origin,
            verification=verification,
            confidence=confidence,
            freshness=freshness,
            evidence=(evidence,),
            first_seen_at=seen_at,
            last_verified_at=(
                seen_at if verification == VERIFICATION_VERIFIED else None
            ),
        )

        subject_tokens = self._candidate_tokens(subject, subject_aliases)
        object_tokens = self._candidate_tokens(object, object_aliases)
        connection = _connection.connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            matches = self._find_matches(
                connection,
                project_id=project_id,
                relation_type=relation_type,
                subject_tokens=subject_tokens,
                object_tokens=object_tokens,
            )
            if not matches:
                relationship_id = new_relationship_id()
                self._insert_edge(
                    connection,
                    relationship_id=relationship_id,
                    project_id=project_id,
                    subject=subject,
                    relation_type=relation_type,
                    object=object,
                    origin=origin,
                    verification=verification,
                    confidence=confidence,
                    freshness=freshness,
                    seen_at=seen_at,
                    last_verified_at=(
                        seen_at if verification == VERIFICATION_VERIFIED else None
                    ),
                )
            else:
                survivor = _pick_merge_survivor(matches)
                relationship_id = survivor["relationship_id"]
                merged_subject = subject
                merged_object = object
                for row in matches:
                    merged_subject = _prefer_resolved(
                        _endpoint_from_row(row, "subject"), merged_subject
                    )
                    merged_object = _prefer_resolved(
                        _endpoint_from_row(row, "object"), merged_object
                    )
                keep_id = relationship_id
                for row in matches:
                    if row["relationship_id"] == keep_id:
                        continue
                    self._merge_into(
                        connection, keep_id=keep_id, drop_id=row["relationship_id"]
                    )
                self._rewrite_endpoints(
                    connection,
                    relationship_id=keep_id,
                    project_id=project_id,
                    relation_type=relation_type,
                    subject=merged_subject,
                    object=merged_object,
                    freshness=freshness,
                )
                if verification == VERIFICATION_VERIFIED:
                    connection.execute(
                        """
                        UPDATE relationships
                        SET last_verified_at = ?
                        WHERE workspace_id = ? AND relationship_id = ?
                          AND (last_verified_at IS NULL OR last_verified_at < ?)
                        """,
                        (seen_at, self._workspace_id, keep_id, seen_at),
                    )
                relationship_id = keep_id

            # Replace superseded evidence from this source so freshness stays
            # current when every remaining row matches the latest revision.
            connection.execute(
                """
                DELETE FROM relationship_evidence
                WHERE workspace_id = ?
                  AND relationship_id = ?
                  AND source_type = ?
                  AND source_id = ?
                  AND revision != ?
                """,
                (
                    self._workspace_id,
                    relationship_id,
                    evidence.source.source_type,
                    evidence.source.source_id,
                    evidence.revision,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO relationship_evidence (
                    workspace_id, relationship_id, source_type, source_id,
                    revision, locator, extractor_id, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._workspace_id,
                    relationship_id,
                    evidence.source.source_type,
                    evidence.source.source_id,
                    evidence.revision,
                    evidence.locator,
                    evidence.extractor_id,
                    seen_at,
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

        loaded = self.get(relationship_id)
        if loaded is None:
            raise RelationshipInputError("relationship upsert failed to persist")
        return loaded

    def mark_stale_for_evidence(
        self, source_ref: SourceReference, revision: str
    ) -> None:
        connection = _connection.connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE relationships
                SET freshness = 'stale'
                WHERE workspace_id = ?
                  AND relationship_id IN (
                    SELECT relationship_id
                    FROM relationship_evidence
                    WHERE workspace_id = ?
                      AND source_type = ?
                      AND source_id = ?
                    GROUP BY relationship_id
                    HAVING SUM(CASE WHEN revision = ? THEN 1 ELSE 0 END) = 0
                  )
                """,
                (
                    self._workspace_id,
                    self._workspace_id,
                    source_ref.source_type,
                    source_ref.source_id,
                    revision,
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def list_for_artifact(
        self,
        project_id: str,
        ref: ArtifactRef | UnresolvedKey,
        filters: Mapping[str, str] | None = None,
        *,
        aliases: tuple[str, ...] = (),
    ) -> tuple[Relationship, ...]:
        tokens = self._candidate_tokens(ref, aliases)
        connection = _connection.connect(self._path)
        try:
            placeholders = ", ".join("?" for _ in tokens)
            rows = connection.execute(
                f"""
                SELECT * FROM relationships
                WHERE workspace_id = ?
                  AND project_id = ?
                  AND (
                    subject_token IN ({placeholders})
                    OR object_token IN ({placeholders})
                  )
                ORDER BY relationship_id COLLATE BINARY
                """,
                (self._workspace_id, project_id, *tokens, *tokens),
            ).fetchall()
            relationships = []
            for row in rows:
                edge = self._relationship_from_row(connection, row)
                if filters:
                    if (
                        filters.get("origin") is not None
                        and edge.origin != filters["origin"]
                    ):
                        continue
                    if (
                        filters.get("verification") is not None
                        and edge.verification != filters["verification"]
                    ):
                        continue
                    if (
                        filters.get("freshness") is not None
                        and edge.freshness != filters["freshness"]
                    ):
                        continue
                relationships.append(edge)
            return tuple(relationships)
        finally:
            connection.close()

    def list_unresolved_for_key(
        self,
        key: str,
        *,
        part_key: str | None = None,
    ) -> tuple[Relationship, ...]:
        connection = _connection.connect(self._path)
        try:
            # Exact unresolved_key matches (indexed). Avoid LIKE so '_' in
            # Jira keys is literal and skipped syncs stay cheap. Sort in
            # Python — an SQL ORDER BY on the UNION prevents index use.
            if part_key is not None:
                rows = connection.execute(
                    """
                    SELECT * FROM relationships
                    WHERE workspace_id = ?
                      AND subject_unresolved_key = ?
                      AND subject_part_key = ?
                    UNION ALL
                    SELECT * FROM relationships
                    WHERE workspace_id = ?
                      AND object_unresolved_key = ?
                      AND object_part_key = ?
                    """,
                    (
                        self._workspace_id,
                        key,
                        part_key,
                        self._workspace_id,
                        key,
                        part_key,
                    ),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM relationships
                    WHERE workspace_id = ?
                      AND subject_unresolved_key = ?
                    UNION ALL
                    SELECT * FROM relationships
                    WHERE workspace_id = ?
                      AND object_unresolved_key = ?
                    """,
                    (
                        self._workspace_id,
                        key,
                        self._workspace_id,
                        key,
                    ),
                ).fetchall()
            seen: set[str] = set()
            relationships: list[Relationship] = []
            for row in sorted(
                rows,
                key=lambda item: (item["project_id"], item["relationship_id"]),
            ):
                relationship_id = row["relationship_id"]
                if relationship_id in seen:
                    continue
                seen.add(relationship_id)
                relationships.append(self._relationship_from_row(connection, row))
            return tuple(relationships)
        finally:
            connection.close()

    def resolve_endpoints(
        self,
        relationship_id: str,
        *,
        subject: ArtifactRef | UnresolvedKey,
        object: ArtifactRef | UnresolvedKey,
        freshness: str,
    ) -> Relationship:
        """Upgrade endpoints on an existing edge without create-time validation."""
        connection = _connection.connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM relationships
                WHERE workspace_id = ? AND relationship_id = ?
                """,
                (self._workspace_id, relationship_id),
            ).fetchone()
            if row is None:
                raise RelationshipInputError("relationship not found")
            self._rewrite_endpoints(
                connection,
                relationship_id=relationship_id,
                project_id=row["project_id"],
                relation_type=row["relation_type"],
                subject=subject,
                object=object,
                freshness=freshness,
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        loaded = self.get(relationship_id)
        if loaded is None:
            raise RelationshipInputError("relationship resolve failed to persist")
        return loaded

    def apply_decision(
        self,
        relationship_id: str,
        *,
        verification: str,
        actor: str,
        at: datetime,
        expected_version: int,
    ) -> Relationship:
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise RelationshipInputError("expected_version must be an integer")
        if expected_version < 1:
            raise RelationshipInputError("expected_version must be at least 1")
        connection = _connection.connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM relationships
                WHERE workspace_id = ? AND relationship_id = ?
                """,
                (self._workspace_id, relationship_id),
            ).fetchone()
            if row is None:
                raise RelationshipInputError(
                    f"relationship not found: {relationship_id}"
                )
            current = self._relationship_from_row(connection, row)
            if int(row["decision_version"]) != expected_version:
                raise RelationshipInputError(
                    "relationship decision conflict: concurrent update"
                )
            if verification == VERIFICATION_VERIFIED:
                updated = current.confirm(actor=actor, at=at)
            elif verification == VERIFICATION_REJECTED:
                updated = current.reject(actor=actor, at=at)
            else:
                raise RelationshipInputError(
                    "apply_decision verification must be verified or rejected"
                )
            cursor = connection.execute(
                """
                UPDATE relationships
                SET verification = ?, decision_actor = ?, decision_at = ?,
                    last_verified_at = ?, decision_version = ?
                WHERE workspace_id = ? AND relationship_id = ?
                  AND decision_version = ?
                """,
                (
                    updated.verification,
                    updated.decision_actor,
                    updated.decision_at,
                    updated.last_verified_at,
                    expected_version + 1,
                    self._workspace_id,
                    relationship_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RelationshipInputError(
                    "relationship decision conflict: concurrent update"
                )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        loaded = self.get(relationship_id)
        if loaded is None:
            raise RelationshipInputError("relationship decision failed to persist")
        return loaded

    def get(self, relationship_id: str) -> Relationship | None:
        connection = _connection.connect(self._path)
        try:
            row = connection.execute(
                """
                SELECT * FROM relationships
                WHERE workspace_id = ? AND relationship_id = ?
                """,
                (self._workspace_id, relationship_id),
            ).fetchone()
            if row is None:
                return None
            return self._relationship_from_row(connection, row)
        finally:
            connection.close()

    def set_record_watermark(
        self, reference: SourceReference, links_fingerprint: str
    ) -> None:
        """Record that relationships for ``reference`` were written successfully."""
        connection = _connection.connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO relationship_record_watermarks (
                    workspace_id, source_type, source_id, links_fingerprint,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, source_type, source_id) DO UPDATE SET
                    links_fingerprint = excluded.links_fingerprint,
                    recorded_at = excluded.recorded_at
                """,
                (
                    self._workspace_id,
                    reference.source_type,
                    reference.source_id,
                    links_fingerprint,
                    _now(),
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def get_record_watermark(self, reference: SourceReference) -> str | None:
        """Return the last successful links fingerprint, or ``None``."""
        connection = _connection.connect(self._path)
        try:
            row = connection.execute(
                """
                SELECT links_fingerprint FROM relationship_record_watermarks
                WHERE workspace_id = ? AND source_type = ? AND source_id = ?
                """,
                (
                    self._workspace_id,
                    reference.source_type,
                    reference.source_id,
                ),
            ).fetchone()
            return None if row is None else str(row["links_fingerprint"])
        finally:
            connection.close()

    def clear_record_watermark(self, reference: SourceReference) -> None:
        """Drop the record watermark so a returning artifact re-records."""
        connection = _connection.connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM relationship_record_watermarks
                WHERE workspace_id = ? AND source_type = ? AND source_id = ?
                """,
                (
                    self._workspace_id,
                    reference.source_type,
                    reference.source_id,
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _candidate_tokens(
        self,
        endpoint: ArtifactRef | UnresolvedKey,
        aliases: Sequence[str],
    ) -> tuple[str, ...]:
        tokens = [endpoint_token(endpoint)]
        part_key = endpoint.part_key
        for key in aliases:
            token = unresolved_token(key, part_key=part_key)
            if token not in tokens:
                tokens.append(token)
        return tuple(tokens)

    def _find_matches(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        relation_type: str,
        subject_tokens: Sequence[str],
        object_tokens: Sequence[str],
    ) -> list[sqlite3.Row]:
        subject_ph = ", ".join("?" for _ in subject_tokens)
        object_ph = ", ".join("?" for _ in object_tokens)
        return list(
            connection.execute(
                f"""
                SELECT * FROM relationships
                WHERE workspace_id = ?
                  AND project_id = ?
                  AND relation_type = ?
                  AND subject_token IN ({subject_ph})
                  AND object_token IN ({object_ph})
                ORDER BY relationship_id COLLATE BINARY
                """,
                (
                    self._workspace_id,
                    project_id,
                    relation_type,
                    *subject_tokens,
                    *object_tokens,
                ),
            ).fetchall()
        )

    def _insert_edge(
        self,
        connection: sqlite3.Connection,
        *,
        relationship_id: str,
        project_id: str,
        subject: ArtifactRef | UnresolvedKey,
        relation_type: str,
        object: ArtifactRef | UnresolvedKey,
        origin: str,
        verification: str,
        confidence: float,
        freshness: str,
        seen_at: str,
        last_verified_at: str | None,
    ) -> None:
        subject_cols = _endpoint_columns(subject, "subject")
        object_cols = _endpoint_columns(object, "object")
        connection.execute(
            """
            INSERT INTO relationships (
                workspace_id, relationship_id, project_id, relation_type,
                subject_token, object_token,
                subject_kind, subject_source_type, subject_source_id,
                subject_part_key, subject_unresolved_key,
                object_kind, object_source_type, object_source_id,
                object_part_key, object_unresolved_key,
                origin, verification, confidence, freshness,
                first_seen_at, last_verified_at, decision_actor, decision_at,
                decision_version
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, NULL, NULL, 1
            )
            """,
            (
                self._workspace_id,
                relationship_id,
                project_id,
                relation_type,
                endpoint_token(subject),
                endpoint_token(object),
                subject_cols["subject_kind"],
                subject_cols["subject_source_type"],
                subject_cols["subject_source_id"],
                subject_cols["subject_part_key"],
                subject_cols["subject_unresolved_key"],
                object_cols["object_kind"],
                object_cols["object_source_type"],
                object_cols["object_source_id"],
                object_cols["object_part_key"],
                object_cols["object_unresolved_key"],
                origin,
                verification,
                confidence,
                freshness,
                seen_at,
                last_verified_at,
            ),
        )

    def _rewrite_endpoints(
        self,
        connection: sqlite3.Connection,
        *,
        relationship_id: str,
        project_id: str,
        relation_type: str,
        subject: ArtifactRef | UnresolvedKey,
        object: ArtifactRef | UnresolvedKey,
        freshness: str,
    ) -> None:
        subject_cols = _endpoint_columns(subject, "subject")
        object_cols = _endpoint_columns(object, "object")
        new_subject = endpoint_token(subject)
        new_object = endpoint_token(object)
        conflict = connection.execute(
            """
            SELECT relationship_id FROM relationships
            WHERE workspace_id = ?
              AND project_id = ?
              AND relation_type = ?
              AND subject_token = ?
              AND object_token = ?
              AND relationship_id != ?
            """,
            (
                self._workspace_id,
                project_id,
                relation_type,
                new_subject,
                new_object,
                relationship_id,
            ),
        ).fetchone()
        if conflict is not None:
            self._merge_into(
                connection,
                keep_id=relationship_id,
                drop_id=conflict["relationship_id"],
            )
        connection.execute(
            """
            UPDATE relationships SET
                subject_token = ?,
                object_token = ?,
                subject_kind = ?,
                subject_source_type = ?,
                subject_source_id = ?,
                subject_part_key = ?,
                subject_unresolved_key = ?,
                object_kind = ?,
                object_source_type = ?,
                object_source_id = ?,
                object_part_key = ?,
                object_unresolved_key = ?,
                freshness = ?
            WHERE workspace_id = ? AND relationship_id = ?
            """,
            (
                new_subject,
                new_object,
                subject_cols["subject_kind"],
                subject_cols["subject_source_type"],
                subject_cols["subject_source_id"],
                subject_cols["subject_part_key"],
                subject_cols["subject_unresolved_key"],
                object_cols["object_kind"],
                object_cols["object_source_type"],
                object_cols["object_source_id"],
                object_cols["object_part_key"],
                object_cols["object_unresolved_key"],
                freshness,
                self._workspace_id,
                relationship_id,
            ),
        )

    def _merge_into(
        self,
        connection: sqlite3.Connection,
        *,
        keep_id: str,
        drop_id: str,
    ) -> None:
        keep = connection.execute(
            """
            SELECT verification, decision_actor, decision_at, first_seen_at,
                   decision_version, origin, confidence, last_verified_at
            FROM relationships
            WHERE workspace_id = ? AND relationship_id = ?
            """,
            (self._workspace_id, keep_id),
        ).fetchone()
        drop = connection.execute(
            """
            SELECT verification, decision_actor, decision_at, first_seen_at,
                   decision_version, origin, confidence, last_verified_at
            FROM relationships
            WHERE workspace_id = ? AND relationship_id = ?
            """,
            (self._workspace_id, drop_id),
        ).fetchone()
        if keep is not None and drop is not None:
            # Preserve human rejection/confirmation and the earliest first_seen_at.
            # Copy origin/confidence/last_verified_at with verification so a
            # verified provider_declared row cannot leave inferred+verified
            # without a decision on the survivor.
            drop_rank = _verification_priority(drop["verification"])
            keep_rank = _verification_priority(keep["verification"])
            if drop_rank > keep_rank or (
                drop_rank == keep_rank
                and keep["decision_actor"] is None
                and drop["decision_actor"] is not None
            ):
                connection.execute(
                    """
                    UPDATE relationships
                    SET verification = ?, decision_actor = ?, decision_at = ?,
                        decision_version = ?, origin = ?, confidence = ?,
                        last_verified_at = ?
                    WHERE workspace_id = ? AND relationship_id = ?
                    """,
                    (
                        drop["verification"],
                        drop["decision_actor"],
                        drop["decision_at"],
                        max(
                            int(keep["decision_version"]),
                            int(drop["decision_version"]),
                        )
                        + 1,
                        drop["origin"],
                        drop["confidence"],
                        drop["last_verified_at"],
                        self._workspace_id,
                        keep_id,
                    ),
                )
            if drop["first_seen_at"] < keep["first_seen_at"]:
                connection.execute(
                    """
                    UPDATE relationships
                    SET first_seen_at = ?
                    WHERE workspace_id = ? AND relationship_id = ?
                    """,
                    (drop["first_seen_at"], self._workspace_id, keep_id),
                )
        connection.execute(
            """
            INSERT OR IGNORE INTO relationship_evidence (
                workspace_id, relationship_id, source_type, source_id,
                revision, locator, extractor_id, recorded_at
            )
            SELECT workspace_id, ?, source_type, source_id, revision, locator,
                   extractor_id, recorded_at
            FROM relationship_evidence
            WHERE workspace_id = ? AND relationship_id = ?
            """,
            (keep_id, self._workspace_id, drop_id),
        )
        connection.execute(
            """
            DELETE FROM relationship_evidence
            WHERE workspace_id = ? AND relationship_id = ?
            """,
            (self._workspace_id, drop_id),
        )
        connection.execute(
            """
            DELETE FROM relationships
            WHERE workspace_id = ? AND relationship_id = ?
            """,
            (self._workspace_id, drop_id),
        )
        self._retain_newest_evidence_per_source(connection, keep_id)

    def _retain_newest_evidence_per_source(
        self, connection: sqlite3.Connection, relationship_id: str
    ) -> None:
        """Drop superseded revisions so merged edges keep one revision per source.

        Newest is by ``recorded_at`` (when Kernector wrote the row), not by the
        opaque connector ``revision`` string.
        """
        rows = connection.execute(
            """
            SELECT source_type, source_id, revision, recorded_at
            FROM relationship_evidence
            WHERE workspace_id = ? AND relationship_id = ?
            """,
            (self._workspace_id, relationship_id),
        ).fetchall()
        newest: dict[tuple[str, str], tuple[str, str]] = {}
        for row in rows:
            key = (row["source_type"], row["source_id"])
            recorded_at = row["recorded_at"] or ""
            current = newest.get(key)
            if current is None or recorded_at > current[0]:
                newest[key] = (recorded_at, row["revision"])
        for (source_type, source_id), (_recorded_at, revision) in newest.items():
            connection.execute(
                """
                DELETE FROM relationship_evidence
                WHERE workspace_id = ?
                  AND relationship_id = ?
                  AND source_type = ?
                  AND source_id = ?
                  AND revision != ?
                """,
                (
                    self._workspace_id,
                    relationship_id,
                    source_type,
                    source_id,
                    revision,
                ),
            )

    def _relationship_from_row(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> Relationship:
        evidence_rows = connection.execute(
            """
            SELECT * FROM relationship_evidence
            WHERE workspace_id = ? AND relationship_id = ?
            ORDER BY source_type, source_id, revision, locator, extractor_id
            """,
            (self._workspace_id, row["relationship_id"]),
        ).fetchall()
        evidence = tuple(
            EvidenceRef(
                source=SourceReference(item["source_id"], item["source_type"]),
                revision=item["revision"],
                locator=item["locator"],
                extractor_id=item["extractor_id"],
            )
            for item in evidence_rows
        )
        return Relationship(
            relationship_id=row["relationship_id"],
            project_id=row["project_id"],
            subject=_endpoint_from_row(row, "subject"),
            relation_type=row["relation_type"],
            object=_endpoint_from_row(row, "object"),
            origin=row["origin"],
            verification=row["verification"],
            confidence=float(row["confidence"]),
            freshness=row["freshness"],
            evidence=evidence,
            first_seen_at=row["first_seen_at"],
            last_verified_at=row["last_verified_at"],
            decision_actor=row["decision_actor"],
            decision_at=row["decision_at"],
            decision_version=int(row["decision_version"]),
        )
