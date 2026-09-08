"""Shared pack-local validators for Software Delivery tool adapters."""

from __future__ import annotations


def require_nonblank_str(
    value: object, field_name: str, error: type[Exception]
) -> str:
    """Reject anything that is not a non-blank string.

    The type check runs before the blankness check so a wrong type is reported
    as a wrong type. Fusing the two would report every rejection as
    "must be a non-blank string", which is false for an ``int`` and hides
    what actually arrived.

    Args:
        value (object): Candidate field value.
        field_name (str): Name used in the error message.
        error (type[Exception]): Exception type raised on rejection.

    Returns:
        str: The validated string.

    Raises:
        Exception: ``error`` if ``value`` is blank or not a string.
    """
    if not isinstance(value, str):
        raise error(
            f"{field_name} must be a non-blank string, got {type(value).__name__}"
        )
    if not value.strip():
        raise error(f"{field_name} must be a non-blank string")
    return value
