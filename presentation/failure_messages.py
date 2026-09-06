"""Fixed category sentences shared by presentation adapters.

Presentation never renders ``str(error)`` for provider/tool/store failures.
The exception type selects the sentence; type alone is never treated as proof
that the exception text is safe.

Adapters own their own exception-type dispatch — only the wording is shared.
This module has no layer dependencies by design: shared presentation text lives
at the package root so HTTP (and any future adapter) can reuse it without
cross-importing peer packages.
"""

from __future__ import annotations

PROVIDER_FAILURE_MESSAGE = "The model provider could not complete the request."
TOOL_FAILURE_MESSAGE = "A tool failed while processing your request."
OPERATIONAL_FAILURE_MESSAGE = "Something went wrong while processing your request."
