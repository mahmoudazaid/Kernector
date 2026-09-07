"""Guard: validation raises under domain/ and application/ must not use ``!r``.

See :mod:`test.architecture.raise_scan` for known evasions (plain ``{value}``,
hoisted messages) that this scanner does not catch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from test.architecture.raise_scan import repr_conversions_in_validation_raises

REPO_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_DIR = REPO_ROOT / "domain"
APPLICATION_DIR = REPO_ROOT / "application"
SCANNED_MODULES = sorted(DOMAIN_DIR.rglob("*.py")) + sorted(
    APPLICATION_DIR.rglob("*.py")
)


def test_scanned_modules_are_discovered() -> None:
    assert SCANNED_MODULES, "no domain/application modules found"


def test_helper_flags_repr_in_validation_raise(tmp_path: Path) -> None:
    module = tmp_path / "leaky.py"
    module.write_text(
        "raise DomainValidationError(f'x, got {v!r}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_validation_raises(module) == [1]


def test_helper_allows_type_name_and_plain_number(tmp_path: Path) -> None:
    module = tmp_path / "safe.py"
    module.write_text(
        "raise DomainValidationError(f'x, got {type(v).__name__}')\n"
        "raise ApplicationValidationError(f'x, got {v}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_validation_raises(module) == []


@pytest.mark.parametrize(
    "module_path",
    SCANNED_MODULES,
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_validation_raises_do_not_embed_repr(module_path: Path) -> None:
    offenders = repr_conversions_in_validation_raises(module_path)
    assert not offenders, (
        f"{module_path.relative_to(REPO_ROOT)} embeds !r in validation "
        f"raises at lines {offenders}"
    )
