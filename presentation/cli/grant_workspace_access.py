"""Grant workspace membership and explicit project access (#446).

Run with::

    uv run python -m presentation.cli.grant_workspace_access \\
        --username alice --project-id prj_one --project-id prj_two

    uv run python -m presentation.cli.grant_workspace_access \\
        --username alice --all-existing-projects

Omitting both ``--project-id`` and ``--all-existing-projects`` is an error;
it never means access to every project. ``--all-existing-projects`` on an
empty catalog grants membership only.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import Protocol

from application.errors import ConfigurationError
from composition.auth import grant_workspace_access


class GrantResult(Protocol):
    @property
    def username(self) -> str: ...

    @property
    def user_id(self) -> str: ...

    @property
    def workspace_id(self) -> str: ...

    @property
    def project_ids(self) -> tuple[str, ...]: ...


def main(
    argv: Sequence[str] | None = None,
    *,
    grant_access: Callable[..., GrantResult] = grant_workspace_access,
) -> int:
    """Grant membership plus explicit project grants for an existing user.

    Returns:
        int: ``0`` on success, ``2`` for argv/config/validation failure.
    """
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="python -m presentation.cli.grant_workspace_access",
        description=(
            "Grant workspace membership and explicit project grants "
            "for an existing local user (#446)."
        ),
    )
    parser.add_argument("--username", required=True, help="Existing local username")
    parser.add_argument(
        "--project-id",
        action="append",
        dest="project_ids",
        default=None,
        help="Project id to grant (repeatable). Required unless "
        "--all-existing-projects is set.",
    )
    parser.add_argument(
        "--all-existing-projects",
        action="store_true",
        help=(
            "Grant every project present in the bound workspace at run time "
            "(membership only when the catalog has none). "
            "Never implied by omitting --project-id."
        ),
    )
    try:
        args = parser.parse_args(raw)
    except SystemExit as error:
        if error.code in (0, None):
            return 0
        return 2

    project_ids = tuple(args.project_ids) if args.project_ids else None
    if not args.all_existing_projects and not project_ids:
        print(
            "Provide --project-id (repeatable) or --all-existing-projects.",
            file=sys.stderr,
        )
        return 2

    try:
        result = grant_access(
            username=args.username,
            project_ids=project_ids,
            all_existing_projects=args.all_existing_projects,
        )
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2

    print(
        f"Granted {result.username!r} ({result.user_id}) "
        f"workspace {result.workspace_id!r} projects "
        f"{', '.join(result.project_ids)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
