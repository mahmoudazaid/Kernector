"""Architecture guards for framework-aware Test Design (#368)."""

from __future__ import annotations

import ast
from pathlib import Path

from test.architecture.import_scan import find_forbidden_module_prefixes

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DESIGN_ROOT = REPO_ROOT / "packs" / "software_delivery" / "test_design"
MCP_TEST_DESIGN = REPO_ROOT / "composition" / "mcp" / "test_design.py"
FACADE = REPO_ROOT / "composition" / "test_design" / "facade.py"
GENERATOR_ROOT = TEST_DESIGN_ROOT / "generators"

# Automation framework ids only (not test_type ``cucumber`` / Gherkin).
FRAMEWORK_NAME_LITERALS = frozenset(
    {
        "robot_framework",
        "playwright",
        "pytest",
        "pytest_bdd",
        "cypress",
        "selenium",
        "junit",
        "testng",
        "appium",
    }
)


def _modules_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value.strip()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_test_design_does_not_import_detectors_or_intake() -> None:
    forbidden = {
        "packs.software_delivery.project_profile.detectors",
        "packs.software_delivery.project_profile.intake",
        "packs.software_delivery.project_profile.extractors",
    }
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): sorted(
            find_forbidden_module_prefixes(path, forbidden)
        )
        for path in _modules_under(TEST_DESIGN_ROOT)
        if find_forbidden_module_prefixes(path, forbidden)
    }
    assert offenders == {}


def test_project_profile_still_does_not_import_test_design() -> None:
    profile_root = REPO_ROOT / "packs" / "software_delivery" / "project_profile"
    forbidden = {"packs.software_delivery.test_design"}
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): sorted(
            find_forbidden_module_prefixes(path, forbidden)
        )
        for path in _modules_under(profile_root)
        if find_forbidden_module_prefixes(path, forbidden)
    }
    assert offenders == {}


def test_mcp_and_facade_have_no_framework_name_branches() -> None:
    """Framework ids may appear as data/docs, but not as if/elif branches."""
    for path in (MCP_TEST_DESIGN, FACADE):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for comparator in node.comparators:
                    if (
                        isinstance(comparator, ast.Constant)
                        and isinstance(comparator.value, str)
                        and comparator.value in FRAMEWORK_NAME_LITERALS
                    ):
                        raise AssertionError(
                            f"{path.relative_to(REPO_ROOT)} compares to "
                            f"framework id {comparator.value!r}"
                        )


def test_generator_modules_may_name_mvp_framework() -> None:
    assert (GENERATOR_ROOT / "robot.py").is_file()
    constants = _string_constants(GENERATOR_ROOT / "robot.py")
    assert "robot_framework" in constants
