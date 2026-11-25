"""Provision a local auth user via an interactive password prompt (#182).

Run with::

    uv run python -m presentation.cli.create_user --username alice

There is no ``--password`` flag. The password is read with ``getpass``.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence
from typing import Protocol

from application.errors import ConfigurationError
from composition.auth import create_local_user


class CreatedUser(Protocol):
    user_id: str
    username: str


def main(
    argv: Sequence[str] | None = None,
    *,
    prompt_password: Callable[[str], str] = getpass.getpass,
    create_user: Callable[[str, str], CreatedUser] = create_local_user,
) -> int:
    """Create a local user and print the new ``user_id``.

    Returns:
        int: ``0`` on success, ``2`` for argv/config/validation failure.
    """
    raw = list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--password" or arg.startswith("--password=") for arg in raw):
        print(
            "Refusing --password; use the interactive prompt only.",
            file=sys.stderr,
        )
        return 2

    parser = argparse.ArgumentParser(
        prog="python -m presentation.cli.create_user",
        description=(
            "Create a local Kernector user "
            "(password prompted, never via flag)."
        ),
    )
    parser.add_argument("--username", required=True, help="Unique local username")
    try:
        args = parser.parse_args(raw)
    except SystemExit as error:
        if error.code in (0, None):
            return 0
        return 2

    try:
        password = prompt_password("Password: ")
        confirm = prompt_password("Confirm password: ")
    except (EOFError, KeyboardInterrupt):
        print("Password prompt cancelled.", file=sys.stderr)
        return 2

    if not password:
        print("Password is required.", file=sys.stderr)
        return 2
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 2

    try:
        user = create_user(args.username, password)
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2

    print(f"Created user {user.username!r} ({user.user_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
