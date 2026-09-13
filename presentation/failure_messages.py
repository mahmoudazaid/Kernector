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
PROVIDER_AUTH_FAILURE_MESSAGE = (
    "Authentication with the model provider failed. Check the API key configuration."
)
PROVIDER_CREDITS_FAILURE_MESSAGE = (
    "The model provider has no remaining credits. Add credits or choose another provider."
)
PROVIDER_MODEL_UNAVAILABLE_FAILURE_MESSAGE = (
    "The selected model is unavailable. Choose a different model or check provider status."
)
PROVIDER_RATE_LIMIT_FAILURE_MESSAGE = (
    "The model provider rate-limited the request. Wait briefly and try again."
)
PROVIDER_TIMEOUT_FAILURE_MESSAGE = (
    "The model provider timed out. Try again or increase the request timeout."
)
PROVIDER_NETWORK_FAILURE_MESSAGE = (
    "The model provider could not be reached. Check network connectivity and try again."
)
TOOL_FAILURE_MESSAGE = "A tool failed while processing your request."
OPERATIONAL_FAILURE_MESSAGE = "Something went wrong while processing your request."
