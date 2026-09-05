"""Ollama chat adapter and reachability probe."""

import time
from collections.abc import Mapping, Sequence
from typing import Protocol

import requests

from domain.errors import ProviderError
from domain.models import AskResult, Message, Usage
from infrastructure.config import OllamaSettings


class OllamaConfigError(RuntimeError):
    """The Ollama base URL is missing or unusable.

    Named so the composition root can catch this specific failure narrowly and
    map it to a typed ``ConfigurationError``. Raised only from construction,
    never from ``complete()``.
    """


class _HttpPost(Protocol):
    def __call__(self, url: str, **kwargs: object) -> object: ...


class OllamaChat:
    """ChatModel backed by a local Ollama server."""

    def __init__(
        self,
        config: OllamaSettings,
        *,
        post: _HttpPost | None = None,
    ) -> None:
        if not config.base_url:
            raise OllamaConfigError(
                "Missing OLLAMA_BASE_URL. Add it to .env before using Ollama."
            )
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._post = post or requests.post

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        payload = {
            "model": self._config.model,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
            **settings,
        }
        start_time = time.perf_counter()
        try:
            response = self._post(
                f"{self._base_url}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self._config.timeout,
            )
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as exc:
            raise ProviderError(
                "The Ollama chat provider could not be reached."
            ) from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(
                "The Ollama chat response could not be parsed."
            ) from exc

        return AskResult(
            content=content,
            model=data.get("model", self._config.model),
            latency_ms=latency_ms,
            usage=_to_usage(data.get("usage")),
            settings=dict(settings),
        )


def _to_usage(usage: Mapping[str, object] | None) -> Usage | None:
    if not usage:
        return None
    return Usage(
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        cost=usage.get("cost"),
    )


def probe_ollama(base_url: str, timeout: float) -> dict:
    """Return {reachable: bool, models: list[str]} for an Ollama base URL."""
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/api/tags",
            timeout=timeout,
            allow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
        raw_models = payload.get("models", []) if isinstance(payload, dict) else []
        models: list[str] = []
        if isinstance(raw_models, list):
            for entry in raw_models:
                if isinstance(entry, dict):
                    name = entry.get("name")
                    if isinstance(name, str) and name:
                        models.append(name)
        return {"reachable": True, "models": models}
    except (requests.exceptions.RequestException, ValueError, TypeError):
        return {"reachable": False, "models": []}
