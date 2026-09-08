"""Guard: raises under scanned first-party packages must not embed repr.

See :mod:`test.architecture.raise_scan` for forms caught mechanically and the
review obligations (plain ``{value}``, hoisted messages) that remain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from test.architecture.raise_scan import repr_conversions_in_raises

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("domain", "application", "packs", "presentation")
SCANNED_MODULES = [
    module
    for directory in SCANNED_DIRS
    for module in sorted((REPO_ROOT / directory).rglob("*.py"))
]


def test_scanned_dirs_cover_every_first_party_package() -> None:
    assert set(SCANNED_DIRS) == {
        "domain",
        "application",
        "packs",
        "presentation",
    }, (
        "a first-party package is unscanned; add it to SCANNED_DIRS and fix "
        "any !r sites it reports"
    )


def test_scanned_modules_are_discovered() -> None:
    assert SCANNED_MODULES, "no scanned first-party modules found"


def test_every_scanned_directory_contributes_modules() -> None:
    for directory in SCANNED_DIRS:
        assert any(
            module.is_relative_to(REPO_ROOT / directory)
            for module in SCANNED_MODULES
        ), f"{directory}/ contributed no modules to the scan"


def test_helper_flags_repr_in_validation_raise(tmp_path: Path) -> None:
    module = tmp_path / "leaky.py"
    module.write_text(
        "raise DomainValidationError(f'x, got {v!r}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_repr_behind_a_renamed_subclass(tmp_path: Path) -> None:
    module = tmp_path / "subclass.py"
    module.write_text(
        "class MarkdownExportValidationError(DomainValidationError):\n"
        "    pass\n"
        "raise MarkdownExportValidationError(f'x, got {v!r}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [3]


def test_helper_flags_repr_behind_an_indirect_error_type(tmp_path: Path) -> None:
    module = tmp_path / "indirect.py"
    module.write_text(
        "def check(value, error_type):\n"
        "    raise error_type(f'x, got {value!r}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [2]


def test_helper_allows_type_name_and_plain_number(tmp_path: Path) -> None:
    module = tmp_path / "safe.py"
    module.write_text(
        "raise DomainValidationError(f'x, got {type(v).__name__}')\n"
        "raise ApplicationValidationError(f'x, got {v}')\n"
        "raise ValueError(f'unknown keys: {len(unknown)} not in {ALLOWED}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == []


def test_helper_flags_container_interpolation(tmp_path: Path) -> None:
    module = tmp_path / "container.py"
    module.write_text(
        "raise ValueError(f'keys: {sorted(unknown)}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_repr_call_inside_fstring(tmp_path: Path) -> None:
    module = tmp_path / "repr_call.py"
    module.write_text(
        "raise ValueError(f'got {repr(v)}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_percent_r_interpolation(tmp_path: Path) -> None:
    module = tmp_path / "percent.py"
    module.write_text(
        "raise ValueError('got %r' % v)\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_repr_concatenated_with_plus(tmp_path: Path) -> None:
    module = tmp_path / "plus.py"
    module.write_text(
        "raise ValueError('got ' + repr(v))\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_format_repr_placeholder(tmp_path: Path) -> None:
    module = tmp_path / "format.py"
    module.write_text(
        "raise ValueError('got {!r}'.format(v))\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_repr_on_raise_cause(tmp_path: Path) -> None:
    module = tmp_path / "cause.py"
    module.write_text(
        "raise ValueError('x') from ValueError(f'got {v!r}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


@pytest.mark.parametrize(
    "module_path",
    SCANNED_MODULES,
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_raises_do_not_embed_repr(module_path: Path) -> None:
    offenders = repr_conversions_in_raises(module_path)
    assert not offenders, (
        f"{module_path.relative_to(REPO_ROOT)} embeds !r in raise messages "
        f"at lines {offenders}"
    )
