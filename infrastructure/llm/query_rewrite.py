"""OpenRouter LangChain adapter for retrieval query rewriting."""

from collections.abc import Callable
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from domain.errors import QueryRewriterError
from infrastructure.config import OpenRouterSettings

# Domain-agnostic rewrite instruction. Kept as a module constant (not a user-
# facing prompt pack) so PROMPT_PACKS cannot hide it and the sidebar cannot
# offer it as a chat persona.
REWRITE_SYSTEM = """\
You rewrite natural-language knowledge questions into retrieval-oriented search \
queries over a generic document corpus.

Rules:
- Output only the rewritten query text. No labels, quotes, or explanation.
- Prefer concrete nouns, entities, and actions that might appear in documents.
- Stay domain-agnostic: do not invent product names, issue trackers, or \
workflow jargon the user did not supply.
- If the input is already specific, return a lightly cleaned version of it.
"""


class QueryRewriteConfigError(RuntimeError):
    """Rewrite credentials or model are missing or unusable.

    Named so the composition root can catch this specific failure narrowly and
    map it to a typed ``ConfigurationError``. Raised only from construction,
    never from ``rewrite()``.
    """


class _InvocableModel(Protocol):
    def invoke(self, messages: object, **kwargs: object) -> Any: ...


class OpenRouterQueryRewriter:
    """``QueryRewriter`` backed by LangChain ``ChatOpenAI`` on OpenRouter.

    Accepts an optional injected ``model`` (or ``model_factory``) so tests
    exercise the public ``rewrite()`` seam without calling the network.
    """

    def __init__(
        self,
        config: OpenRouterSettings,
        *,
        model: _InvocableModel | None = None,
        model_factory: Callable[[], _InvocableModel] | None = None,
    ) -> None:
        _require_rewrite_config(config)
        self._system = REWRITE_SYSTEM
        if model is not None:
            self._model = model
        elif model_factory is not None:
            self._model = model_factory()
        else:
            self._model = ChatOpenAI(
                model=config.rewrite_model,
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout,
            )

    def rewrite(self, query: str) -> str:
        """Return a non-blank retrieval-oriented rewrite of ``query``.

        Raises:
            QueryRewriterError: Invocation failed or content was blank after
                normalization.
        """
        messages = [
            SystemMessage(content=self._system),
            HumanMessage(content=query),
        ]
        try:
            result = self._model.invoke(messages)
        except Exception as error:
            raise QueryRewriterError(str(error)) from error

        content = getattr(result, "content", result)
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        normalized = content.strip()
        if not normalized:
            raise QueryRewriterError(
                "Query rewrite returned a blank retrieval query"
            )
        return normalized


def _require_rewrite_config(config: OpenRouterSettings) -> None:
    """Fail fast when rewrite credentials or model are absent."""
    if not config.api_key:
        raise QueryRewriteConfigError(
            "Missing OPENROUTER_API_KEY. Add it to .env before rewriting queries."
        )
    if not config.base_url:
        raise QueryRewriteConfigError(
            "Missing OPENROUTER_BASE_URL. Add it to .env before rewriting queries."
        )
    if not config.rewrite_model:
        raise QueryRewriteConfigError(
            "Missing OPENROUTER_REWRITE_MODEL or OPENROUTER_MODEL. "
            "Add one to .env before rewriting queries."
        )
