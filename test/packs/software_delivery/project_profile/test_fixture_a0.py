"""Part A0 profile-evidence fixture smoke tests (#371 / #387 slice 0)."""

from __future__ import annotations

from test.fixtures.project_intelligence.loader import (
    COMPONENT_LABELS,
    gold_lists_schema_fields,
    gold_text,
    iter_required_paths,
    read_text,
    secret_env_value,
)


def test_part_a0_required_paths_exist() -> None:
    missing = [path for path in iter_required_paths() if not path.is_file()]
    assert missing == [], f"missing fixture files: {missing}"


def test_gold_lists_technology_profile_schema_fields() -> None:
    assert gold_lists_schema_fields()


def test_gold_declares_client_component_labels() -> None:
    text = gold_text()
    for label in COMPONENT_LABELS:
        assert f"label: {label}" in text


def test_env_secret_present_for_intake_drop_tests() -> None:
    secret = secret_env_value()
    assert secret
    assert "never" in secret or "secret" in secret.lower()
    assert "SECRET_DATABASE_PASSWORD=" in read_text("acme/proj-orders/.env")


def test_frontend_evidence_covers_detector_and_extractor_paths() -> None:
    package = read_text("acme/proj-web/package.json")
    assert "typescript" in package
    assert "next" in package
    assert "react" in package
    assert "CancelOrderButton" in read_text(
        "acme/proj-web/components/CancelOrderButton.tsx"
    )
    assert "cancelOrder" in read_text("acme/proj-web/lib/api/orders.ts")
    assert "Order detail" in read_text("acme/proj-web/app/orders/[id]/page.tsx")


def test_robot_keywords_have_stable_line_ranges() -> None:
    resource = read_text("acme/proj-tests/resources/orders.resource").splitlines()
    assert resource[1] == "Create Unpaid Order"
    assert resource[5] == "Create Paid Order"
    assert resource[9] == "Cancel Order"
