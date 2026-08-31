"""Guards the domain layer's stdlib-only, no-I/O import rule."""

import sys
from pathlib import Path

import pytest

from test.architecture.import_scan import find_non_allowed_imports

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "domain"
DOMAIN_MODULES = sorted(DOMAIN_DIR.rglob("*.py"))

# Stdlib modules that perform I/O or reach outside process memory.
# Being in sys.stdlib_module_names does not make these valid for domain.
FORBIDDEN_STDLIB = {
    "os",
    "pathlib",
    "shutil",
    "io",
    "sqlite3",
    "urllib",
    "http",
    "socket",
}

ALLOWED = set(sys.stdlib_module_names) | {"domain"}


def test_domain_modules_are_discovered() -> None:
    assert DOMAIN_MODULES, f"no domain modules found under {DOMAIN_DIR}"


@pytest.mark.parametrize("module_path", DOMAIN_MODULES, ids=lambda p: p.name)
def test_domain_module_imports_only_allowed_packages(module_path: Path) -> None:
    disallowed = find_non_allowed_imports(
        module_path, allowed=ALLOWED, forbidden=FORBIDDEN_STDLIB
    )
    assert not disallowed, f"{module_path.name} imports {sorted(disallowed)}"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import rich\n", {"rich"}),
        ("import boto3\n", {"boto3"}),
        ("import pathlib\n", {"pathlib"}),
        ("import composition\n", {"composition"}),
        ("from composition import build_app\n", {"composition"}),
        ("import packs\n", {"packs"}),
        ("from packs.software_delivery.scoring import score_risk\n", {"packs"}),
    ],
)
def test_planted_domain_disallowed_import_is_detected(
    tmp_path: Path, source: str, expected: set[str]
) -> None:
    module = tmp_path / "bad_domain.py"
    module.write_text(source, encoding="utf-8")
    assert (
        find_non_allowed_imports(module, allowed=ALLOWED, forbidden=FORBIDDEN_STDLIB)
        == expected
    )


@pytest.mark.parametrize(
    "source",
    [
        "import domain.models\n",
        "from domain.errors import DomainValidationError\n",
        "from .errors import DomainValidationError\n",
    ],
)
def test_planted_domain_allowed_import_is_accepted(tmp_path: Path, source: str) -> None:
    module = tmp_path / "ok_domain.py"
    module.write_text(source, encoding="utf-8")
    assert not find_non_allowed_imports(
        module, allowed=ALLOWED, forbidden=FORBIDDEN_STDLIB
    )
