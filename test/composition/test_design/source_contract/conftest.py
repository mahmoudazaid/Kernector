"""Register Test Design source harnesses; every contract test runs per provider."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from test.composition.test_design.source_contract.github_harness import (
    GitHubContractHarness,
)
from test.composition.test_design.source_contract.harness import SourceContractHarness
from test.composition.test_design.source_contract.jira_data_center_harness import (
    JiraDataCenterContractHarness,
)

CONTRACT_HARNESSES = (GitHubContractHarness, JiraDataCenterContractHarness)


def _refuse_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("contract tests must not open network connections")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _refuse_network)
    monkeypatch.setattr(socket, "create_connection", _refuse_network)


@pytest.fixture(params=CONTRACT_HARNESSES, ids=lambda cls: cls.provider)
def harness(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> SourceContractHarness:
    return request.param(tmp_path, monkeypatch)
