"""Load the Part A0 profile-evidence fixture tree (#371 / #387)."""

from __future__ import annotations

from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent / "v1"

REQUIRED_PATHS: tuple[str, ...] = (
    "README.md",
    "acme/proj-orders/pyproject.toml",
    "acme/proj-orders/.github/workflows/ci.yml",
    "acme/proj-orders/Dockerfile",
    "acme/proj-orders/.env",
    "acme/proj-tests/requirements.txt",
    "acme/proj-tests/tests/orders/cancel_order.robot",
    "acme/proj-tests/resources/orders.resource",
    "acme/proj-e2e/package.json",
    "acme/proj-e2e/e2e/cancel-order.spec.ts",
    "acme/proj-web/package.json",
    "acme/proj-web/app/orders/[id]/page.tsx",
    "acme/proj-web/components/CancelOrderButton.tsx",
    "acme/proj-web/lib/api/orders.ts",
    "profile_variants/mixed/requirements.txt",
    "profile_variants/thin/README.md",
    "profile_variants/unrecognized/tests/manifest.weird",
    "profile_variants/unrecognized/tests/WeirdTest.xyz",
    "gold/profile_proj.yaml",
)

GOLD_SCHEMA_FIELDS: frozenset[str] = frozenset(
    {
        "profile_fingerprint",
        "evidence_origin",
        "facet_status",
        "facts",
        "conventions",
        "reusable_components",
        "approved_conventions",
        "conflicts",
        "diagnostics",
        "context_status",
        "untrusted_evidence",
    }
)

COMPONENT_LABELS: tuple[str, ...] = (
    "proj-orders",
    "proj-tests",
    "proj-e2e",
    "proj-web",
)


def fixture_path(*parts: str) -> Path:
    """Return an absolute path under the v1 fixture root."""
    return FIXTURE_ROOT.joinpath(*parts)


def iter_required_paths() -> list[Path]:
    """Return absolute paths for every Part A0 required file."""
    return [fixture_path(relative) for relative in REQUIRED_PATHS]


def read_text(relative: str) -> str:
    """Read a fixture file as UTF-8 text."""
    return fixture_path(relative).read_text(encoding="utf-8")


def gold_text() -> str:
    """Return the raw gold profile document."""
    return read_text("gold/profile_proj.yaml")


def gold_lists_schema_fields() -> bool:
    """Return whether the gold file names every TechnologyProfile schema field."""
    text = gold_text()
    return all(field in text for field in GOLD_SCHEMA_FIELDS)


def secret_env_value() -> str:
    """Return the fixture `.env` secret that must never appear in profile output."""
    for line in read_text("acme/proj-orders/.env").splitlines():
        if line.startswith("SECRET_DATABASE_PASSWORD="):
            return line.split("=", 1)[1]
    raise LookupError("SECRET_DATABASE_PASSWORD missing from fixture .env")
