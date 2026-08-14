import os
import time
import requests
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
import config

def ask(
    system: str,
    user_text: str,
    provider: str | None = None,
    model: str | None = None,
    ollama_base_url: str | None = None,
) -> dict:
    provider = (provider or config.DEFAULT_PROVIDER).lower()

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
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_text},
                    ],
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
            }
        except requests.exceptions.RequestException:
            return {
                "content": f"Failed to connect to {provider_label}",
                "model": model,
                "latency_ms": None,
                "usage": None,
            }
        except (KeyError, IndexError, ValueError):
            return {
                "content": f"Failed to parse response from {provider_label}",
                "model": model,
                "latency_ms": None,
                "usage": None,
            }

    model = model or os.getenv("OPENROUTER_MODEL")
    provider_label = "OpenRouter"
    try:
        started = time.perf_counter()
        chat_model = make_openrouter_chat_model(model)
        prompt = make_ask_prompt()
        chain = prompt | chat_model
        ai_message = chain.invoke({
            "system": system,
            "user_text": user_text,
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
        }
    except Exception:
        return {
            "content": f"Failed to connect to {provider_label}",
            "model": model,
            "latency_ms": None,
            "usage": None,
        }

def make_openrouter_chat_model(model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model= model or config.OPENROUTER_MODEL,
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        timeout=config.OPENROUTER_TIMEOUT,
    )

def make_ask_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system", "{system}"),
        ("human", "{user_text}"),
    ])

def validate_input(input: str) -> str | None:
    if not input.strip():
        return "Please paste the interview prep for analyzing."
    if len(input) > config.MAX_INPUT_LENGTH:
        return f"Input is too long (max {config.MAX_INPUT_LENGTH} characters)."
    return None

def is_not_interview_prep(reply: str) -> bool:
    return "## Not Interview Pre" in reply
