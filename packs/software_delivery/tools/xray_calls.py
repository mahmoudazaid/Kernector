"""Map Xray connector failures onto the tool error taxonomy (#199, #397)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from domain.errors import ConnectorAuthError, ConnectorUnavailableError, ToolFailureError
from domain.test_management.xray import XrayRequiredFieldsError

MSG_XRAY_UNAVAILABLE = "Xray is temporarily unavailable"
MSG_XRAY_FAILED = "Creating Xray tests failed"
MSG_REQUIRED_FIELDS = (
    "The Xray project requires Jira fields Kernector could not fill from the "
    "source issue or allowed values; nothing was created"
)
MAX_FIELD_NAMES = 10

_T = TypeVar("_T")


def call_xray(call: Callable[[], _T]) -> _T:
    """Run ``call``; auth errors propagate, everything else becomes ``ToolFailureError``."""
    try:
        return call()
    except ConnectorAuthError:
        raise
    except XrayRequiredFieldsError as exc:
        names = ", ".join(exc.field_names[:MAX_FIELD_NAMES])
        raise ToolFailureError(f"{MSG_REQUIRED_FIELDS}: {names}") from exc
    except ConnectorUnavailableError as exc:
        raise ToolFailureError(MSG_XRAY_UNAVAILABLE) from exc
    except Exception as exc:  # noqa: BLE001 - map connector and unexpected failures
        raise ToolFailureError(MSG_XRAY_FAILED) from exc
