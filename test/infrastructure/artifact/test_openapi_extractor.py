"""OpenAPI / Swagger operation extraction (#373)."""

from __future__ import annotations

from domain.artifact.kinds import ArtifactKind
from domain.knowledge import SourceDocument, SourceMetadata, SourceReference, SourceType
from infrastructure.artifact.openapi import extract_openapi_parts


VALID_SPEC = """
openapi: 3.0.3
info:
  title: Orders
  version: 1.0.0
paths:
  /orders/{orderId}/cancel:
    post:
      operationId: cancelOrder
      summary: Cancel an unpaid order
      responses:
        "200":
          description: cancelled
        "409":
          description: conflict
"""

UNSUPPORTED_SPEC = """
openapi: "1.2"
info:
  title: Legacy
  version: 0.1.0
paths: {}
"""

MALFORMED_SPEC = "{ not: valid yaml ["


def _document(content: str, path: str = "api/openapi.yaml") -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference(f"acme/proj-orders:{path}", SourceType.GITHUB),
            title=path,
            extra={
                "github_path": path,
                "github_blob_sha": "sha-spec",
                "file_name": path.rsplit("/", 1)[-1],
            },
        ),
        content,
    )


def test_valid_spec_yields_operation_parts_and_keys() -> None:
    result = extract_openapi_parts(_document(VALID_SPEC))

    assert result.kind == ArtifactKind.API_SPEC
    assert result.diagnostic is None
    assert len(result.parts) == 1
    part = result.parts[0]
    assert part.kind == ArtifactKind.API_OPERATION
    assert part.operation_id == "cancelOrder"
    assert part.part_key == "POST /orders/{orderId}/cancel"
    assert "200" in part.response_codes
    assert set(result.external_keys) == {
        "cancelOrder",
        "POST /orders/{orderId}/cancel",
    }


def test_multiline_summary_is_normalized_not_rejected() -> None:
    spec = """
openapi: 3.0.3
info:
  title: Orders
  version: 1.0.0
paths:
  /orders:
    get:
      operationId: listOrders
      summary: |
        List orders.
        Supports cursor pagination.
      responses:
        "200":
          description: ok
"""
    result = extract_openapi_parts(_document(spec))

    assert result.diagnostic is None
    assert len(result.parts) == 1
    assert result.parts[0].summary == "List orders. Supports cursor pagination."
    assert "listOrders" in result.external_keys


def test_operation_id_and_method_path_are_same_operation() -> None:
    result = extract_openapi_parts(_document(VALID_SPEC))
    by_id = {key: result.parts[0] for key in result.external_keys}
    assert by_id["cancelOrder"] is by_id["POST /orders/{orderId}/cancel"]


def test_unsupported_version_keeps_api_spec_with_diagnostic_and_zero_ops() -> None:
    result = extract_openapi_parts(_document(UNSUPPORTED_SPEC))

    assert result.kind == ArtifactKind.API_SPEC
    assert result.diagnostic == "unsupported"
    assert result.parts == ()
    assert result.external_keys == ()


def test_malformed_spec_keeps_api_spec_with_diagnostic_and_zero_ops() -> None:
    result = extract_openapi_parts(_document(MALFORMED_SPEC))

    assert result.kind == ArtifactKind.API_SPEC
    assert result.diagnostic == "unsupported"
    assert result.parts == ()


def test_size_limit_rejects_oversized_spec() -> None:
    huge = "openapi: 3.0.0\n" + ("x: " + ("a" * 100) + "\n") * 20_000
    result = extract_openapi_parts(_document(huge), max_bytes=1024)

    assert result.diagnostic == "unsupported"
    assert result.parts == ()
