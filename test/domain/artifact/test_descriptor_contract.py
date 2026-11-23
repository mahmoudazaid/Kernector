"""ArtifactDescriptor contract validation (#373, ADR 0011)."""

from __future__ import annotations

import pytest

from domain.errors import DomainValidationError
from domain.knowledge import SourceReference

from domain.artifact.errors import ArtifactInputError
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import (
    ArtifactDescriptor,
    ArtifactPart,
    ArtifactRef,
    ContextAssignment,
)


def _reference() -> SourceReference:
    return SourceReference("acme/proj-orders:orders/cancel.py", "github")


def _descriptor(**overrides: object) -> ArtifactDescriptor:
    values: dict[str, object] = {
        "reference": _reference(),
        "revision": "abc123",
        "kind": ArtifactKind.CODE_FILE,
        "contexts": (ContextAssignment("backend", "role_default"),),
        "component_ids": ("cmp_orders",),
        "external_keys": (),
        "parts": (),
        "title": "orders/cancel.py",
        "url": "https://github.com/acme/proj-orders/blob/main/orders/cancel.py",
    }
    values.update(overrides)
    return ArtifactDescriptor(**values)  # type: ignore[arg-type]


def test_descriptor_accepts_valid_contract() -> None:
    descriptor = _descriptor()

    assert descriptor.kind == "code_file"
    assert descriptor.contexts[0].context == "backend"
    assert descriptor.component_ids == ("cmp_orders",)


def test_artifact_ref_addresses_whole_artifact_or_part() -> None:
    whole = ArtifactRef(_reference())
    part = ArtifactRef(_reference(), part_key="POST /orders/{orderId}/cancel")

    assert whole.part_key is None
    assert part.part_key == "POST /orders/{orderId}/cancel"


def test_artifact_part_carries_operation_fields() -> None:
    part = ArtifactPart(
        kind="api_operation",
        part_key="POST /orders/{orderId}/cancel",
        operation_id="cancelOrder",
        summary="Cancel an unpaid order",
        response_codes=("200", "409"),
    )

    assert part.operation_id == "cancelOrder"
    assert part.response_codes == ("200", "409")


@pytest.mark.parametrize("kind", ["", "Code_File", "code-file", "1code", "x" * 65])
def test_descriptor_rejects_invalid_kind_token(kind: str) -> None:
    with pytest.raises(ArtifactInputError):
        _descriptor(kind=kind)


@pytest.mark.parametrize(
    "context", ["", "Backend", "api-contract", "1ctx", "x" * 65]
)
def test_context_assignment_rejects_invalid_context_token(context: str) -> None:
    with pytest.raises(ArtifactInputError):
        ContextAssignment(context, "role_default")


def test_descriptor_rejects_blank_revision() -> None:
    with pytest.raises(ArtifactInputError):
        _descriptor(revision="   ")


def test_descriptor_rejects_non_source_reference() -> None:
    with pytest.raises(ArtifactInputError):
        _descriptor(reference="not-a-ref")


def test_descriptor_rejects_duplicate_external_keys() -> None:
    with pytest.raises(ArtifactInputError):
        _descriptor(external_keys=("PROJ-123", "PROJ-123"))


def test_descriptor_rejects_duplicate_component_ids() -> None:
    with pytest.raises(ArtifactInputError):
        _descriptor(component_ids=("cmp_a", "cmp_a"))


def test_artifact_input_errors_are_domain_validation_errors() -> None:
    with pytest.raises(DomainValidationError):
        _descriptor(kind="")


def test_well_known_kind_constants_are_documented_tokens() -> None:
    assert ArtifactKind.STORY == "story"
    assert ArtifactKind.BUG == "bug"
    assert ArtifactKind.TEST_CASE == "test_case"
    assert ArtifactKind.CODE_FILE == "code_file"
    assert ArtifactKind.AUTOMATED_TEST == "automated_test"
    assert ArtifactKind.TEST_SUPPORT == "test_support"
    assert ArtifactKind.DOCUMENT == "document"
    assert ArtifactKind.WORK_ITEM == "work_item"
    assert ArtifactKind.API_SPEC == "api_spec"
    assert ArtifactKind.API_OPERATION == "api_operation"
