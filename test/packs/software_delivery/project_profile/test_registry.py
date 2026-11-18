"""Detector registry and aggregation semantics (#387 slice 3)."""

from __future__ import annotations

from packs.software_delivery.project_profile.intake import ingest_profile_evidence
from packs.software_delivery.project_profile.models import (
    Convention,
    EvidenceRef,
    LineRange,
    ProfileFact,
)
from packs.software_delivery.project_profile.registry import (
    DetectorEmission,
    TechnologyDetector,
    TechnologyDetectorRegistry,
    aggregate_profile,
)


class _FakeDetector:
    detector_id = "fake"
    version = "1"
    facets = frozenset({"test_frameworks", "languages"})

    def __init__(self, emissions: dict[str, list[DetectorEmission]]) -> None:
        self._emissions = emissions

    def detect(self, component_label: str, files: tuple) -> list[DetectorEmission]:
        return list(self._emissions.get(component_label, []))


def _file_ref(component: str, path: str, content: str, start: int = 1, end: int = 1) -> EvidenceRef:
    from packs.software_delivery.project_profile.intake import content_hash

    return EvidenceRef(
        component=component,
        path=path,
        content_hash=content_hash(content),
        line_range=LineRange(start, end),
    )


def test_detected_status_for_single_framework() -> None:
    content = "robotframework==7\n"
    evidence = ingest_profile_evidence(
        [
            {
                "component": "oie-tests",
                "files": [{"path": "requirements.txt", "content": content}],
            }
        ]
    )
    ref = _file_ref("oie-tests", "requirements.txt", content)
    detector = _FakeDetector(
        {
            "oie-tests": [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="robot_framework",
                        framework_id="robot_framework",
                        confidence="high",
                        evidence_refs=(ref,),
                    )
                )
            ]
        }
    )
    registry = TechnologyDetectorRegistry((detector,))
    profile = aggregate_profile(evidence, registry)
    component = profile.components[0]
    assert component.facet_status["test_frameworks"] == "detected"
    assert profile.facet_status.get("test_frameworks") != "ambiguous"


def test_ambiguous_within_component_lists_both_frameworks() -> None:
    content = "robotframework\npytest-bdd\n"
    evidence = ingest_profile_evidence(
        [
            {
                "component": "mixed",
                "files": [{"path": "requirements.txt", "content": content}],
            }
        ]
    )
    ref = _file_ref("mixed", "requirements.txt", content)
    detector = _FakeDetector(
        {
            "mixed": [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="robot_framework",
                        framework_id="robot_framework",
                        confidence="high",
                        evidence_refs=(ref,),
                    )
                ),
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="pytest_bdd",
                        framework_id="pytest_bdd",
                        confidence="high",
                        evidence_refs=(ref,),
                    )
                ),
            ]
        }
    )
    profile = aggregate_profile(evidence, TechnologyDetectorRegistry((detector,)))
    assert profile.components[0].facet_status["test_frameworks"] == "ambiguous"
    values = {f.value for f in profile.components[0].facts if f.facet == "test_frameworks"}
    assert values == {"robot_framework", "pytest_bdd"}


def test_cross_component_frameworks_are_not_project_ambiguous() -> None:
    robot = "robotframework==7\n"
    playwright = '{"devDependencies":{"@playwright/test":"1"}}\n'
    evidence = ingest_profile_evidence(
        [
            {
                "component": "oie-tests",
                "files": [{"path": "requirements.txt", "content": robot}],
            },
            {
                "component": "oie-e2e",
                "files": [{"path": "package.json", "content": playwright}],
            },
        ]
    )
    detector = _FakeDetector(
        {
            "oie-tests": [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="robot_framework",
                        framework_id="robot_framework",
                        confidence="high",
                        evidence_refs=(_file_ref("oie-tests", "requirements.txt", robot),),
                    )
                )
            ],
            "oie-e2e": [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="playwright",
                        framework_id="playwright",
                        confidence="high",
                        evidence_refs=(_file_ref("oie-e2e", "package.json", playwright),),
                    )
                )
            ],
        }
    )
    profile = aggregate_profile(evidence, TechnologyDetectorRegistry((detector,)))
    by_label = {c.label: c for c in profile.components}
    assert by_label["oie-tests"].facet_status["test_frameworks"] == "detected"
    assert by_label["oie-e2e"].facet_status["test_frameworks"] == "detected"
    assert profile.facet_status.get("test_frameworks") != "ambiguous"


def test_compatible_multi_value_stays_detected() -> None:
    content = '{"dependencies":{"next":"14","react":"18","typescript":"5"}}\n'
    evidence = ingest_profile_evidence(
        [{"component": "oie-web", "files": [{"path": "package.json", "content": content}]}]
    )
    ref = _file_ref("oie-web", "package.json", content)
    detector = _FakeDetector(
        {
            "oie-web": [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="languages",
                        value="TypeScript",
                        language="TypeScript",
                        confidence="high",
                        evidence_refs=(ref,),
                    )
                ),
                DetectorEmission(
                    fact=ProfileFact(
                        facet="application_frameworks",
                        value="next",
                        framework_id="next",
                        confidence="high",
                        evidence_refs=(ref,),
                    )
                ),
                DetectorEmission(
                    fact=ProfileFact(
                        facet="application_frameworks",
                        value="react",
                        framework_id="react",
                        confidence="high",
                        evidence_refs=(ref,),
                    )
                ),
            ]
        }
    )
    # widen facets on fake
    detector.facets = frozenset({"languages", "application_frameworks", "test_frameworks"})
    profile = aggregate_profile(evidence, TechnologyDetectorRegistry((detector,)))
    status = profile.components[0].facet_status
    assert status["languages"] == "detected"
    assert status["application_frameworks"] == "detected"
    assert len([f for f in profile.components[0].facts if f.facet == "application_frameworks"]) == 2


def test_insufficient_context_when_no_emissions_for_declared_facet() -> None:
    evidence = ingest_profile_evidence(
        [{"component": "thin", "files": [{"path": "README.md", "content": "hi\n"}]}]
    )

    class Empty(TechnologyDetector):
        detector_id = "empty"
        version = "1"
        facets = frozenset({"languages"})
        evidence_recommendations = {
            "languages": ("pyproject.toml", "package.json"),
        }

        def detect(self, component_label: str, files: tuple) -> list[DetectorEmission]:
            return []

    profile = aggregate_profile(evidence, TechnologyDetectorRegistry((Empty(),)))
    assert profile.components[0].facet_status["languages"] == "insufficient_context"
    assert any("pyproject.toml" in d or "package.json" in d for d in profile.diagnostics)


def test_unrecognized_when_evidence_present_but_no_match() -> None:
    content = "framework: totally-unknown\n"
    evidence = ingest_profile_evidence(
        [{"component": "x", "files": [{"path": "manifest.weird", "content": content}]}]
    )

    class Unrec(TechnologyDetector):
        detector_id = "unrec"
        version = "1"
        facets = frozenset({"test_frameworks"})

        def detect(self, component_label: str, files: tuple) -> list[DetectorEmission]:
            return [
                DetectorEmission(
                    unrecognized_facet="test_frameworks",
                    diagnostic="unrecognized test framework evidence",
                )
            ]

    profile = aggregate_profile(evidence, TechnologyDetectorRegistry((Unrec(),)))
    assert profile.components[0].facet_status["test_frameworks"] == "unrecognized"


def test_fabricated_evidence_refs_are_dropped() -> None:
    content = "robotframework==7\n"
    evidence = ingest_profile_evidence(
        [
            {
                "component": "oie-tests",
                "files": [{"path": "requirements.txt", "content": content}],
            }
        ]
    )
    bad_ref = EvidenceRef(
        component="oie-tests",
        path="requirements.txt",
        content_hash="deadbeef",
        line_range=LineRange(1, 1),
    )
    detector = _FakeDetector(
        {
            "oie-tests": [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="robot_framework",
                        framework_id="robot_framework",
                        confidence="high",
                        evidence_refs=(bad_ref,),
                    )
                )
            ]
        }
    )
    profile = aggregate_profile(evidence, TechnologyDetectorRegistry((detector,)))
    assert profile.components[0].facts == ()
    assert any("fabricated" in d.lower() or "invalid evidence" in d.lower() for d in profile.diagnostics)


def test_wrong_component_ref_dropped() -> None:
    content = "x\n"
    evidence = ingest_profile_evidence(
        [
            {"component": "a", "files": [{"path": "package.json", "content": content}]},
            {"component": "b", "files": [{"path": "package.json", "content": content}]},
        ]
    )
    stolen = _file_ref("b", "package.json", content)
    detector = _FakeDetector(
        {
            "a": [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="languages",
                        value="TypeScript",
                        language="TypeScript",
                        confidence="high",
                        evidence_refs=(stolen,),
                    )
                )
            ]
        }
    )
    detector.facets = frozenset({"languages", "test_frameworks"})
    profile = aggregate_profile(evidence, TechnologyDetectorRegistry((detector,)))
    by_label = {c.label: c for c in profile.components}
    assert by_label["a"].facts == ()


def test_fingerprint_included_and_stable() -> None:
    content = "robotframework==7\n"
    groups = [
        {
            "component": "oie-tests",
            "files": [{"path": "requirements.txt", "content": content}],
        }
    ]
    evidence = ingest_profile_evidence(groups)
    ref = _file_ref("oie-tests", "requirements.txt", content)
    detector = _FakeDetector(
        {
            "oie-tests": [
                DetectorEmission(
                    fact=ProfileFact(
                        facet="test_frameworks",
                        value="robot_framework",
                        framework_id="robot_framework",
                        confidence="high",
                        evidence_refs=(ref,),
                    )
                )
            ]
        }
    )
    registry = TechnologyDetectorRegistry((detector,))
    a = aggregate_profile(evidence, registry)
    b = aggregate_profile(ingest_profile_evidence(list(reversed(groups))), registry)
    assert a.profile_fingerprint == b.profile_fingerprint
    assert a.profile_fingerprint
