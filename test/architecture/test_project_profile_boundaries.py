"""Architecture guards for project_profile (#387 Phase A)."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

from test.architecture.import_scan import find_forbidden_module_prefixes

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_ROOT = REPO_ROOT / "packs" / "software_delivery" / "project_profile"
DETECTOR_ROOT = PROFILE_ROOT / "detectors"

TEAM_ROLE_LITERALS = frozenset(
    {
        "qa",
        "developer",
        "pm",
        "architect",
        "devops",
        "sdet",
        "product_manager",
        "business_analyst",
        "engineering_lead",
    }
)

FRAMEWORK_NAME_LITERALS = frozenset(
    {
        "robot_framework",
        "playwright",
        "pytest",
        "pytest_bdd",
        "cucumber",
        "cypress",
        "selenium",
        "junit",
        "testng",
        "appium",
        "next",
        "react",
        "typescript",
    }
)


def _profile_modules() -> list[Path]:
    return sorted(PROFILE_ROOT.rglob("*.py"))


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value.strip().casefold()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_project_profile_does_not_import_test_design() -> None:
    forbidden = {"packs.software_delivery.test_design"}
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): sorted(
            find_forbidden_module_prefixes(path, forbidden)
        )
        for path in _profile_modules()
        if find_forbidden_module_prefixes(path, forbidden)
    }
    assert offenders == {}


def test_project_profile_has_no_team_role_literals() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _profile_modules():
        hits = _string_constants(path) & TEAM_ROLE_LITERALS
        # Allow documentation that mentions roles only outside contracts — none allowed.
        if hits:
            offenders[path.relative_to(REPO_ROOT).as_posix()] = hits
    assert offenders == {}


def test_framework_name_branches_only_inside_detectors() -> None:
    non_detector = [
        path
        for path in _profile_modules()
        if "detectors" not in path.parts and path.name != "__init__.py"
    ]
    offenders: dict[str, set[str]] = {}
    for path in non_detector:
        # reusable.py may mention robot_framework as data on extracted items —
        # framework *branching* is the concern. Scan Compare/If on constants.
        tree = ast.parse(path.read_text(encoding="utf-8"))
        branched: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for comparator in node.comparators:
                    if (
                        isinstance(comparator, ast.Constant)
                        and isinstance(comparator.value, str)
                        and comparator.value.casefold() in FRAMEWORK_NAME_LITERALS
                    ):
                        branched.add(comparator.value.casefold())
        # Framework Compare branches are allowed in detectors/ and extractors/.
        if "extractors" in path.parts:
            continue
        if branched and path.name not in {"reusable.py", "service.py"}:
            offenders[path.relative_to(REPO_ROOT).as_posix()] = branched
    assert offenders == {}


def test_core_layers_do_not_import_project_profile() -> None:
    forbidden = {"packs.software_delivery.project_profile"}
    roots = (
        REPO_ROOT / "domain",
        REPO_ROOT / "application",
        REPO_ROOT / "infrastructure",
    )
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): sorted(
            find_forbidden_module_prefixes(path, forbidden)
        )
        for root in roots
        for path in root.rglob("*.py")
        if find_forbidden_module_prefixes(path, forbidden)
    }
    assert offenders == {}


def test_adding_detector_needs_no_schema_change() -> None:
    from packs.software_delivery.project_profile.intake import ingest_profile_evidence
    from packs.software_delivery.project_profile.models import ProfileFact, LineRange, EvidenceRef
    from packs.software_delivery.project_profile.registry import (
        DetectorEmission,
        TechnologyDetectorRegistry,
        aggregate_profile,
    )
    class ExtraDetector:
        detector_id = "extra_fake"
        version = "1"
        facets = frozenset({"languages"})

        def detect(self, component_label: str, files: tuple):
            if not files:
                return []
            file = files[0]
            return [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="languages",
                        value="ExtraLang",
                        language="ExtraLang",
                        confidence="low",
                        evidence_refs=(
                            EvidenceRef(
                                component=component_label,
                                path=file.path,
                                content_hash=file.content_hash,
                                line_range=LineRange(1, 1),
                            ),
                        ),
                    )
                )
            ]

    evidence = ingest_profile_evidence(
        [{"files": [{"path": "notes.txt", "content": "x\n"}]}]
    )
    profile = aggregate_profile(
        evidence, TechnologyDetectorRegistry((ExtraDetector(),))
    )
    assert any(f.value == "ExtraLang" for f in profile.facts)


def test_disabled_mcp_registry_does_not_import_project_profile() -> None:
    code = r"""
import sys
from dataclasses import replace

import infrastructure.config as config

config.load_dotenv = lambda *a, **k: False

from application.contracts import RetrieveRequest, RetrieveResponse
from composition.mcp.wiring import build_mcp_tool_registry
from infrastructure.config import DomainToolSettings, load_settings


class _Stub:
    def execute(self, request: RetrieveRequest) -> RetrieveResponse:
        return RetrieveResponse(hits=())


settings = replace(load_settings(), domain_tools=DomainToolSettings(enabled_packs=()))
build_mcp_tool_registry(settings, retrieve=_Stub())
assert not any(
    name == "packs.software_delivery"
    or name.startswith("packs.software_delivery.")
    for name in sys.modules
)
print("ok", flush=True)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout
