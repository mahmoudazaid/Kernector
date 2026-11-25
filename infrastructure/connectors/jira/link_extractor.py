"""Jira provider-declared link transport and ExplicitLinkExtractor (#374)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from domain.knowledge import SourceDocument
from domain.relationship.models import ProviderLink

PROVIDER_LINKS_EXTRA_KEY = "kernector.jira.provider_links.v1"
LINKS_FINGERPRINT_EXTRA_KEY = "kernector.jira.links_fingerprint.v1"
EXTRACTOR_ID = "jira_explicit_links"
_PROVIDER_LINKS_VERSION = 1

DEFAULT_TYPE_MAP: dict[str, tuple[str, str]] = {
    # type_name / inward / outward phrase.casefold() -> (canonical, outward_role)
    # role: "subject" means the outward end is the canonical subject.
    "tests": ("tests", "subject"),
    "test": ("tests", "subject"),  # Xray default link type name
    "is tested by": ("tests", "object"),
    "relates": ("relates_to", "subject"),
    "blocks": ("blocks", "subject"),
    "is blocked by": ("blocks", "object"),
    "defect": ("affects", "subject"),
    "causes": ("affects", "subject"),
    "is caused by": ("affects", "object"),
}


def fingerprint_provider_links(encoded_payload: str) -> str:
    """Return a stable hash of an encoded provider-links transport blob."""
    return hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest()


def encode_provider_links(payload: Mapping[str, object]) -> str:
    """Serialize the versioned Jira links transport blob."""
    return json.dumps(dict(payload), separators=(",", ":"), sort_keys=True)


def decode_provider_links_raw(extra: Mapping[str, str]) -> dict[str, object]:
    """Decode ``kernector.jira.provider_links.v1`` from document extra."""
    raw = extra.get(PROVIDER_LINKS_EXTRA_KEY)
    if raw is None:
        raise ValueError("provider links transport key is missing")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("provider links transport is not JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("provider links transport must be an object")
    if payload.get("v") != _PROVIDER_LINKS_VERSION:
        raise ValueError("unsupported provider links transport version")
    return payload


def build_provider_links_payload(
    *,
    issue_key: str,
    fields: Mapping[str, object],
) -> dict[str, object]:
    """Build the versioned transport payload from Jira issue fields."""
    links: list[dict[str, str]] = []
    parent = fields.get("parent")
    if isinstance(parent, Mapping):
        parent_key = parent.get("key")
        if isinstance(parent_key, str) and parent_key.strip():
            links.append(
                {
                    "field": "parent",
                    "type_name": "parent",
                    "direction": "outward",
                    "other_key": parent_key.strip(),
                }
            )
    subtasks = fields.get("subtasks")
    if isinstance(subtasks, Sequence) and not isinstance(subtasks, (str, bytes)):
        for item in subtasks:
            if not isinstance(item, Mapping):
                continue
            key = item.get("key")
            if isinstance(key, str) and key.strip():
                links.append(
                    {
                        "field": "subtasks",
                        "type_name": "subtask",
                        "direction": "outward",
                        "other_key": key.strip(),
                    }
                )
    issuelinks = fields.get("issuelinks")
    if isinstance(issuelinks, Sequence) and not isinstance(issuelinks, (str, bytes)):
        for item in issuelinks:
            if not isinstance(item, Mapping):
                continue
            type_map = item.get("type")
            type_name = ""
            type_inward = ""
            type_outward = ""
            if isinstance(type_map, Mapping):
                name = type_map.get("name")
                if isinstance(name, str):
                    type_name = name.strip()
                inward = type_map.get("inward")
                if isinstance(inward, str):
                    type_inward = inward.strip()
                outward = type_map.get("outward")
                if isinstance(outward, str):
                    type_outward = outward.strip()
            outward = item.get("outwardIssue")
            inward = item.get("inwardIssue")
            outward_key = (
                outward.get("key")
                if isinstance(outward, Mapping)
                else None
            )
            inward_key = (
                inward.get("key") if isinstance(inward, Mapping) else None
            )
            if isinstance(outward_key, str) and outward_key.strip() and type_name:
                entry = {
                    "field": "issuelinks",
                    "type_name": type_name,
                    "direction": "outward",
                    "other_key": outward_key.strip(),
                }
                if type_inward:
                    entry["type_inward"] = type_inward
                if type_outward:
                    entry["type_outward"] = type_outward
                links.append(entry)
            elif isinstance(inward_key, str) and inward_key.strip() and type_name:
                entry = {
                    "field": "issuelinks",
                    "type_name": type_name,
                    "direction": "inward",
                    "other_key": inward_key.strip(),
                }
                if type_inward:
                    entry["type_inward"] = type_inward
                if type_outward:
                    entry["type_outward"] = type_outward
                links.append(entry)
    return {"v": _PROVIDER_LINKS_VERSION, "issue_key": issue_key, "links": links}


def _token_for_unknown(type_name: str) -> str:
    cleaned = re.sub(r"[^\w-]+", "_", type_name.strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("_")
    if not cleaned:
        digest = hashlib.sha256(type_name.encode("utf-8")).hexdigest()[:12]
        cleaned = f"x{digest}"
    return f"jira:{cleaned}"


@dataclass(frozen=True, slots=True)
class JiraLinkTypeMapping:
    """Configurable Jira link-type name → canonical relation mapping."""

    by_name: Mapping[str, tuple[str, str]] = frozenset()  # replaced in post_init

    def __post_init__(self) -> None:
        if not self.by_name:
            mapping = dict(DEFAULT_TYPE_MAP)
        else:
            mapping = {key.casefold(): value for key, value in self.by_name.items()}
        object.__setattr__(self, "by_name", mapping)

    def resolve(
        self,
        type_name: str,
        *,
        type_inward: str = "",
        type_outward: str = "",
    ) -> tuple[str, str]:
        """Return ``(relation_type, outward_role)`` for a Jira type.

        Phrases are checked before ``type.name`` so a type named ``Tests`` with
        outward ``is tested by`` keeps the phrase's role. An outward-phrase hit
        uses the table role as-is; an inward-phrase hit flips it.
        """
        if type_outward:
            found = self.by_name.get(type_outward.casefold())
            if found is not None:
                return found
        if type_inward:
            found = self.by_name.get(type_inward.casefold())
            if found is not None:
                relation_type, role = found
                flipped = "object" if role == "subject" else "subject"
                return relation_type, flipped
        found = self.by_name.get(type_name.casefold())
        if found is not None:
            return found
        return _token_for_unknown(type_name), "subject"


class JiraExplicitLinkExtractor:
    """Map Jira transport links to canonical ProviderLink observations."""

    def __init__(self, mapping: JiraLinkTypeMapping | None = None) -> None:
        self._mapping = mapping or JiraLinkTypeMapping()

    def extract(
        self, document: SourceDocument, raw: Mapping[str, object]
    ) -> tuple[ProviderLink, ...]:
        del document
        issue_key = raw.get("issue_key")
        if not isinstance(issue_key, str) or not issue_key.strip():
            return ()
        issue_key = issue_key.strip()
        entries = raw.get("links")
        if not isinstance(entries, list):
            return ()
        links: list[ProviderLink] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            field = entry.get("field")
            type_name = entry.get("type_name")
            direction = entry.get("direction")
            other_key = entry.get("other_key")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (field, type_name, direction, other_key)
            ):
                continue
            assert isinstance(field, str)
            assert isinstance(type_name, str)
            assert isinstance(direction, str)
            assert isinstance(other_key, str)
            type_inward = entry.get("type_inward")
            type_outward = entry.get("type_outward")
            link = self._canonicalize(
                issue_key=issue_key,
                field=field.strip(),
                type_name=type_name.strip(),
                direction=direction.strip(),
                other_key=other_key.strip(),
                type_inward=(
                    type_inward.strip()
                    if isinstance(type_inward, str)
                    else ""
                ),
                type_outward=(
                    type_outward.strip()
                    if isinstance(type_outward, str)
                    else ""
                ),
            )
            if link is not None:
                links.append(link)
        return tuple(links)

    def _canonicalize(
        self,
        *,
        issue_key: str,
        field: str,
        type_name: str,
        direction: str,
        other_key: str,
        type_inward: str = "",
        type_outward: str = "",
    ) -> ProviderLink | None:
        if field == "parent":
            return ProviderLink(
                relation_type="child_of",
                subject_key=issue_key,
                object_key=other_key,
                locator=f"field=parent;key={other_key}",
            )
        if field == "subtasks":
            return ProviderLink(
                relation_type="child_of",
                subject_key=other_key,
                object_key=issue_key,
                locator=f"field=subtasks;key={other_key}",
            )
        if field != "issuelinks":
            return None
        relation_type, outward_role = self._mapping.resolve(
            type_name,
            type_inward=type_inward,
            type_outward=type_outward,
        )
        if direction == "outward":
            if outward_role == "subject":
                subject_key, object_key = issue_key, other_key
            else:
                subject_key, object_key = other_key, issue_key
            locator = (
                f"field=issuelinks;type={type_name};dir=out;key={other_key}"
            )
        elif direction == "inward":
            # Current issue is the inward end; other_key is the outward issue.
            if outward_role == "subject":
                subject_key, object_key = other_key, issue_key
            else:
                subject_key, object_key = issue_key, other_key
            locator = (
                f"field=issuelinks;type={type_name};dir=in;key={other_key}"
            )
        else:
            return None
        return ProviderLink(
            relation_type=relation_type,
            subject_key=subject_key,
            object_key=object_key,
            locator=locator,
        )
