"""CLI grant_workspace_access (#446)."""

from __future__ import annotations

from dataclasses import dataclass

from application.errors import ConfigurationError
from presentation.cli import grant_workspace_access as cli


@dataclass(frozen=True)
class _Result:
    username: str
    user_id: str
    workspace_id: str
    project_ids: tuple[str, ...]


def test_requires_project_ids_or_all_existing_flag(capsys) -> None:
    calls: list[object] = []

    def grant(**kwargs: object) -> _Result:
        calls.append(kwargs)
        raise AssertionError("must not grant")

    code = cli.main(["--username", "alice"], grant_access=grant)
    assert code == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "--project-id" in err or "--all-existing-projects" in err


def test_grants_explicit_project_ids(capsys) -> None:
    def grant(
        *,
        username: str,
        project_ids: tuple[str, ...] | None,
        all_existing_projects: bool,
    ) -> _Result:
        assert username == "alice"
        assert project_ids == ("prj_one", "prj_two")
        assert all_existing_projects is False
        return _Result(
            username="alice",
            user_id="usr_alice",
            workspace_id="ws_acme",
            project_ids=("prj_one", "prj_two"),
        )

    code = cli.main(
        [
            "--username",
            "alice",
            "--project-id",
            "prj_one",
            "--project-id",
            "prj_two",
        ],
        grant_access=grant,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "alice" in out
    assert "prj_one" in out
    assert "ws_acme" in out


def test_all_existing_projects_flag(capsys) -> None:
    def grant(
        *,
        username: str,
        project_ids: tuple[str, ...] | None,
        all_existing_projects: bool,
    ) -> _Result:
        assert project_ids is None
        assert all_existing_projects is True
        return _Result(
            username="alice",
            user_id="usr_alice",
            workspace_id="ws_acme",
            project_ids=("prj_a",),
        )

    code = cli.main(
        ["--username", "alice", "--all-existing-projects"],
        grant_access=grant,
    )
    assert code == 0
    assert "prj_a" in capsys.readouterr().out


def test_surfaces_configuration_error_without_partial_claim(capsys) -> None:
    def boom(
        *,
        username: str,
        project_ids: tuple[str, ...] | None,
        all_existing_projects: bool,
    ) -> _Result:
        raise ConfigurationError("unknown project")

    code = cli.main(
        ["--username", "alice", "--project-id", "prj_missing"],
        grant_access=boom,
    )
    assert code == 2
    assert "unknown project" in capsys.readouterr().err
