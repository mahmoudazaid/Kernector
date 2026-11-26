"""CLI create_user (#182)."""

from __future__ import annotations

from dataclasses import dataclass

from application.errors import ConfigurationError
from presentation.cli import create_user as create_user_cli


@dataclass(frozen=True)
class _FakeUser:
    user_id: str
    username: str


def test_create_user_prompts_for_password_and_creates(
    capsys,
) -> None:
    prompts: list[str] = []

    def fake_getpass(prompt: str = "") -> str:
        prompts.append(prompt)
        return "secret-password"

    def fake_create(username: str, password: str) -> _FakeUser:
        assert username == "alice"
        assert password == "secret-password"
        return _FakeUser(user_id="usr_abc", username=username)

    code = create_user_cli.main(
        ["--username", "alice"],
        prompt_password=fake_getpass,
        create_user=fake_create,
    )
    assert code == 0
    assert prompts == ["Password: ", "Confirm password: "]
    out = capsys.readouterr().out
    assert "alice" in out
    assert "usr_abc" in out
    assert "secret-password" not in out


def test_create_user_rejects_password_flag(capsys) -> None:
    code = create_user_cli.main(
        ["--username", "alice", "--password", "nope"],
        prompt_password=lambda _p: "x",
        create_user=lambda *_a: (_ for _ in ()).throw(AssertionError("no create")),
    )
    assert code == 2
    assert "--password" in capsys.readouterr().err


def test_create_user_rejects_mismatched_passwords(capsys) -> None:
    values = iter(["one", "two"])
    code = create_user_cli.main(
        ["--username", "alice"],
        prompt_password=lambda _p: next(values),
        create_user=lambda *_a: (_ for _ in ()).throw(AssertionError("no create")),
    )
    assert code == 2
    assert "do not match" in capsys.readouterr().err


def test_create_user_surfaces_configuration_error(capsys) -> None:
    def boom(_username: str, _password: str) -> _FakeUser:
        raise ConfigurationError("username 'alice' already exists")

    code = create_user_cli.main(
        ["--username", "alice"],
        prompt_password=lambda _p: "same",
        create_user=boom,
    )
    assert code == 2
    assert "already exists" in capsys.readouterr().err
