"""Ollama chat adapter and reachability probe."""

import time
from collections.abc import Mapping, Sequence

import requests

from domain.models import AskResult, Message, Usage
from infrastructure.config import OllamaSettings


class OllamaChat:
    """ChatModel backed by a local Ollama server."""

    def __init__(self, config: OllamaSettings) -> None:
        if not config.base_url:
            raise RuntimeError(
                "Missing OLLAMA_BASE_URL. Add it to .env before using Ollama."
            )
        self._config = config
        self._base_url = config.base_url.rstrip("/")

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
            response = requests.post(
                f"{self._base_url}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self._config.timeout,
            )
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException:
            return AskResult(
                content="Failed to connect to Ollama",
                model=self._config.model,
                settings=dict(settings),
            )
        except (KeyError, IndexError, ValueError):
            return AskResult(
                content="Failed to parse response from Ollama",
                model=self._config.model,
                settings=dict(settings),
            )

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
        )
        response.raise_for_status()
        models = [m["name"] for m in response.json().get("models", [])]
        return {"reachable": True, "models": models}
    except requests.exceptions.RequestException:
        return {"reachable": False, "models": []}
