import os
import time
import requests
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import config
from model_settings import SETTINGS

def ask(
    system: str,
    user_text: str,
    provider: str | None = None,
    model: str | None = None,
    ollama_base_url: str | None = None,
    model_config: dict | None = None,
    history: list[dict] | None = None,
) -> dict:
    provider = (provider or config.DEFAULT_PROVIDER).lower()
    applied = {
        k: v for k, v in (model_config or {}).items()
        if k in {s.key for s in SETTINGS}
    }
    conversation = to_provider_messages(history or [])+[
        {"role": "user", "content": user_text},
    ]

    if provider == "ollama":
        base = (ollama_base_url or config.OLLAMA_BASE_URL).rstrip("/")
        url = f"{base}/v1/chat/completions"
        model = model or config.OLLAMA_MODEL
        headers = {"Content-Type": "application/json"}
        provider_label = "Ollama"
        try:
            started = time.perf_counter()
            response = requests.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}] + conversation,
                    **applied,
                },
                timeout=config.OLLAMA_TIMEOUT,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            data = response.json()
            return {
                "content": data["choices"][0]["message"]["content"],
                "model": data.get("model", model),
                "latency_ms": latency_ms,
                "usage": data.get("usage"),
                "settings": applied,
            }
        except requests.exceptions.RequestException:
            return {
                "content": f"Failed to connect to {provider_label}",
                "model": model,
                "latency_ms": None,
                "usage": None,
                "settings": applied,
            }
        except (KeyError, IndexError, ValueError):
            return {
                "content": f"Failed to parse response from {provider_label}",
                "model": model,
                "latency_ms": None,
                "usage": None,
                "settings": applied,
            }

    model = model or os.getenv("OPENROUTER_MODEL")
    provider_label = "OpenRouter"
    try:
        started = time.perf_counter()
        chat_model = make_openrouter_chat_model(model, **applied)
        prompt = make_ask_prompt()
        chain = prompt | chat_model
        ai_message = chain.invoke({
            "system": system,
            "history": conversation,
        })
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = None
        meta = getattr(ai_message, "usage_metadata", None) or {}
        if meta:
            usage = {
                "prompt_tokens": meta.get("input_tokens"),
                "completion_tokens": meta.get("output_tokens"),
                "total_tokens": meta.get("total_tokens"),
            }
        return {
            "content": ai_message.content,
            "model": model,
            "latency_ms": latency_ms,
            "usage": usage,
            "settings": applied,
        }
    except Exception:
        return {
            "content": f"Failed to connect to {provider_label}",
            "model": model,
            "latency_ms": None,
            "usage": None,
            "settings": applied,
        }

def make_openrouter_chat_model(model: str | None = None, **params) -> ChatOpenAI:
    return ChatOpenAI(
        model= model or config.OPENROUTER_MODEL,
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        timeout=config.OPENROUTER_TIMEOUT,
        **params,
    )

def make_ask_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system", "{system}"),
        MessagesPlaceholder("history"),
    ])

def to_provider_messages(messages: list[dict]) -> list[dict]:
    return [
        {"role": message["role"], "content": message["content"]}
        for message in messages
    ]

def validate_input(input: str) -> str | None:
    if not input.strip():
        return "Please paste the interview prep for analyzing."
    if len(input) > config.MAX_INPUT_LENGTH:
        return f"Input is too long (max {config.MAX_INPUT_LENGTH} characters)."
    return None

def is_not_interview_prep(reply: str) -> bool:
    return "## Not Interview Pre" in reply
