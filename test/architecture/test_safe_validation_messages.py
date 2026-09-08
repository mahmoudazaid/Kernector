"""Guard: raises under scanned first-party packages must not embed repr.

See :mod:`test.architecture.raise_scan` for forms caught mechanically and the
review obligations (plain ``{value}`` / ``str(v)`` / ``"%s" % v`` /
``"{}".format(v)`` on a dataclass, hoisted messages, class-composed plain
values) that remain.
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
_NON_FIRST_PARTY = frozenset(
    {
        "test",
        "web",
        "node_modules",
        "data",
        "output",
        "docs",
        "prompts",
        "curriculum",
        "learning",
    }
)
_KNOWN_UNSCANNED = frozenset({"infrastructure", "composition"})


def test_every_first_party_package_is_scanned_or_explicitly_deferred() -> None:
    discovered = {
        directory.name
        for directory in REPO_ROOT.iterdir()
        if directory.is_dir()
        and not directory.name.startswith((".", "_"))
        and directory.name not in _NON_FIRST_PARTY
        and any(directory.rglob("*.py"))
    }
    assert discovered == set(SCANNED_DIRS) | _KNOWN_UNSCANNED, (
        "a first-party package is neither scanned nor explicitly deferred; "
        "add it to SCANNED_DIRS and fix any repr sites it reports"
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
        "raise ValueError(f'keys: {sorted(unknown)}')\n"
        "raise ValueError(f'keys: {list(unknown)}')\n"
        "raise ValueError(f'keys: {tuple(unknown)}')\n"
        "raise ValueError(f'keys: {set(unknown)}')\n"
        "raise ValueError(f'keys: {frozenset(unknown)}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1, 2, 3, 4, 5]


def test_helper_flags_str_wrapped_container_interpolation(tmp_path: Path) -> None:
    module = tmp_path / "str_wrap.py"
    module.write_text(
        "raise ValueError(f'keys: {str(sorted(unknown))}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_percent_s_of_container(tmp_path: Path) -> None:
    module = tmp_path / "percent_s.py"
    module.write_text(
        "raise ValueError('keys: %s' % sorted(unknown))\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_empty_format_of_container(tmp_path: Path) -> None:
    module = tmp_path / "empty_format.py"
    module.write_text(
        "raise ValueError('keys: {}'.format(sorted(unknown)))\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_ascii_conversion(tmp_path: Path) -> None:
    module = tmp_path / "ascii_conv.py"
    module.write_text(
        "raise ValueError(f'got {v!a}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_flags_str_join_of_non_constant(tmp_path: Path) -> None:
    module = tmp_path / "join.py"
    module.write_text(
        "raise ValueError(f'missing: {\", \".join(missing)}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1]


def test_helper_allows_str_join_of_module_constant(tmp_path: Path) -> None:
    module = tmp_path / "join_const.py"
    module.write_text(
        "SAFE_CONSTANT = ('Given', 'When', 'Then')\n"
        "_PHASE_ORDER = {'Given': 0, 'When': 1, 'Then': 2}\n"
        "raise ValueError(f'missing: {\", \".join(SAFE_CONSTANT)}')\n"
        "raise ValueError(f'missing: {\", \".join(_PHASE_ORDER)}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == []


def test_helper_flags_str_join_of_variable_separator(tmp_path: Path) -> None:
    module = tmp_path / "join_var.py"
    module.write_text(
        "sep = ', '\n"
        "raise ValueError(f'missing: {sep.join(missing)}')\n"
        "raise ValueError(f'missing: {self._sep.join(missing)}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [2, 3]


def test_helper_flags_local_uppercase_join_argument(tmp_path: Path) -> None:
    module = tmp_path / "join_local.py"
    module.write_text(
        "def f(untrusted):\n"
        "    KEYS = untrusted\n"
        "    raise ValueError(f'bad: {\", \".join(KEYS)}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [3]


def test_helper_allows_os_path_join(tmp_path: Path) -> None:
    module = tmp_path / "path_join.py"
    module.write_text(
        "import os\n"
        "raise ValueError(f'path: {os.path.join(base, name)}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == []


def test_helper_flags_dict_and_view_interpolation(tmp_path: Path) -> None:
    module = tmp_path / "views.py"
    module.write_text(
        "raise ValueError(f'keys: {unknown.keys()}')\n"
        "raise ValueError(f'vals: {unknown.values()}')\n"
        "raise ValueError(f'dict: {dict(unknown)}')\n"
        "raise ValueError(f'slice: {unknown[:3]}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [1, 2, 3, 4]


def test_helper_honours_noqa_raise_scan(tmp_path: Path) -> None:
    module = tmp_path / "noqa.py"
    module.write_text(
        "raise ValueError(f'keys: {sorted(unknown)}')  # noqa: raise-scan\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == []


_NOQA_ALLOWLIST: frozenset[str] = frozenset()


def test_noqa_suppressions_are_inventoried() -> None:
    found = {
        str(module.relative_to(REPO_ROOT))
        for module in SCANNED_MODULES
        for line in module.read_text(encoding="utf-8").splitlines()
        if "noqa: raise-scan" in line
    }
    assert found == _NOQA_ALLOWLIST, (
        "a raise-scan suppression was added or moved; justify it in "
        "_NOQA_ALLOWLIST or remove it"
    )


def test_helper_flags_repr_in_exception_init(tmp_path: Path) -> None:
    module = tmp_path / "init_leak.py"
    module.write_text(
        "class LeakyError(ValueError):\n"
        "    def __init__(self, value):\n"
        "        super().__init__(f'got {value!r}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [3]


def test_helper_flags_repr_behind_indirect_exception_base(tmp_path: Path) -> None:
    module = tmp_path / "indirect_base.py"
    module.write_text(
        "class Base(ValueError):\n"
        "    pass\n"
        "class Leak(Base):\n"
        "    def __init__(self, v):\n"
        "        super().__init__(f'got {v!r}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [5]


def test_helper_flags_repr_in_str_and_helper_methods(tmp_path: Path) -> None:
    module = tmp_path / "methods.py"
    module.write_text(
        "class Leak:\n"
        "    def __str__(self):\n"
        "        return f'got {self.v!r}'\n"
        "    def _msg(self, v):\n"
        "        return f'got {v!r}'\n"
        "    def __init__(self, v):\n"
        "        super().__init__(self._msg(v))\n"
        "    @classmethod\n"
        "    def of(cls, v):\n"
        "        return cls(f'got {v!r}')\n",
        encoding="utf-8",
    )
    assert repr_conversions_in_raises(module) == [3, 5, 10]


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
        f"{module_path.relative_to(REPO_ROOT)} embeds a repr-equivalent form "
        f"in a raise (or exception __init__) at lines {offenders}"
    )
