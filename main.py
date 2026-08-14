from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time
import streamlit as st
import requests
from dotenv import load_dotenv
from prompts_loader import DEFAULT_PROMPT, PROMPTS
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
load_dotenv(override=True)
MAX_INPUT_LENGTH = 10000

def validate_input(input: str) -> str | None:
    if not input.strip():
        return "Please paste the interview prep for analyzing."
    if len(input) > MAX_INPUT_LENGTH:
        return f"Input is too long (max {MAX_INPUT_LENGTH} characters)."
    return None

def is_not_interview_prep(reply: str) -> bool:
    return "## Not Interview Pre" in reply

def render_reply(reply: str) -> None:
    if is_not_interview_prep(reply):
        st.warning("This input does not look like a Job Posting.")
    st.markdown(reply)

def make_openrouter_chat_model(model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or os.getenv("OPENROUTER_MODEL"),
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        timeout=30,
    )

def make_ask_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system", "{system}"),
        ("human", "{user_text}"),
    ])

def ask(
    system: str,
    user_text: str,
    provider: str | None = None,
    model: str | None = None,
    ollama_base_url: str | None = None,
) -> dict:
    provider = (provider or os.getenv("LLM_PROVIDER", "openrouter")).lower()

    if provider == "ollama":
        base = (ollama_base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        url = f"{base}/v1/chat/completions"
        model = model or os.getenv("OLLAMA_MODEL", "llama3.2")
        headers = {"Content-Type": "application/json"}
        timeout = 120
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
                timeout=timeout,
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

def render_run_meta(result: dict) -> None:
    bits = []
    usage = result.get("usage") or {}

    if result.get("model"):
        bits.append(f"Model: {result['model']}")

    if result.get("latency_ms") is not None:
        bits.append(f"Latency: {result['latency_ms']}ms")

    total_tokens = usage.get("total_tokens")
    if total_tokens is not None:
        bits.append(f"Tokens: {total_tokens}")
    else:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if prompt_tokens is not None and completion_tokens is not None:
            bits.append(f"Tokens: {prompt_tokens} in / {completion_tokens} out")

    cost = usage.get("cost")
    if cost is not None:
        bits.append(f"Cost: ${cost}")

    if bits:
        st.caption(" | ".join(bits))

def render_export_actions(result: dict, filename_prefix: str) -> None:
    st.download_button(
        "Download output",
        data=result["content"],
        file_name=f"{filename_prefix}.md",
        mime="text/markdown",
        key=f"download_{filename_prefix}",
    )

@st.cache_data(ttl=30)
def probe_ollama(base_url: str) -> dict:
    """Return {reachable: bool, models: list[str]} for an Ollama base URL."""
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        response.raise_for_status()
        models = [m["name"] for m in response.json().get("models", [])]
        return {"reachable": True, "models": models}
    except requests.exceptions.RequestException:
        return {"reachable": False, "models": []}

st.session_state.setdefault("last_user_input", None)
st.session_state.setdefault("last_mode", None)
st.session_state.setdefault("last_selected_key", None)
st.session_state.setdefault("last_results", None)

st.title("Kernector - Interview Analysis")

with st.sidebar:
    provider = st.radio(
        "Provider",
        ["openrouter", "ollama"],
        format_func=lambda p: "OpenRouter" if p == "openrouter" else "Ollama",
        index=0 if os.getenv("LLM_PROVIDER", "openrouter").lower() == "openrouter" else 1,
    )

    selected_model = os.getenv("OPENROUTER_MODEL")
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    if provider == "ollama":
        ollama_base_url = st.text_input("Ollama base URL", value=ollama_base_url)
        status = probe_ollama(ollama_base_url)
        models = status["models"]

        if not status["reachable"]:
            st.error("Ollama is not reachable.")
            st.markdown(
                "1. Install Ollama from [ollama.com/download](https://ollama.com/download)\n"
                "2. Open the Ollama app (starts the local server)\n"
                "3. In a terminal, run: `ollama pull llama3.2`\n"
                "4. Refresh this page"
            )
            st.caption(
                "`ollama pull` only works after Ollama is installed. "
                "If you see `command not found`, finish step 1 first."
            )
            selected_model = st.text_input(
                "Ollama model",
                value=os.getenv("OLLAMA_MODEL", "llama3.2"),
            )
        elif not models:
            st.warning("Ollama is running, but no models are installed yet.")
            st.markdown("In a terminal, run: `ollama pull llama3.2`, then refresh.")
            selected_model = st.text_input(
                "Ollama model",
                value=os.getenv("OLLAMA_MODEL", "llama3.2"),
            )
        else:
            default_model = os.getenv("OLLAMA_MODEL", models[0])
            index = models.index(default_model) if default_model in models else 0
            selected_model = st.selectbox("Ollama model", options=models, index=index)
            st.caption("Ollama connected · local, slower, no API cost.")
    else:
        st.caption(f"OpenRouter model: {selected_model}")


    mode = st.radio("Mode", ["Single", "Compare"])
    selected_key = DEFAULT_PROMPT
    if mode == "Single":
        selected_key = st.selectbox(
            "Prompt variant",
            options=list(PROMPTS.keys()),
            format_func=lambda key: PROMPTS[key]["name"],
            index=list(PROMPTS.keys()).index(DEFAULT_PROMPT),
        )
        st.caption(PROMPTS[selected_key]["description"])
    elif provider == "ollama":
        st.caption(f"Compare will run {len(PROMPTS)} local calls and may be slow.")

user_input = st.chat_input("Paste a Job Posting to analyze")
if user_input:
    error = validate_input(user_input)
    if error:
        st.error(error)
    else:
        st.session_state.last_user_input = user_input
        st.session_state.last_mode = mode
        st.session_state.last_selected_key = selected_key

        if mode == "Single":
            prompt = PROMPTS[selected_key]
            with st.spinner(f"Analyzing with {prompt['name']}..."):
                result = ask(
                    prompt["system"],
                    user_input,
                    provider=provider,
                    model=selected_model,
                    ollama_base_url=ollama_base_url,
                )
            st.session_state.last_results = {selected_key: result}
        else:
            results = {}
            total = len(PROMPTS)
            progress_bar = st.progress(0.0)
            status = st.empty()
            status.write(f"Starting {total} compare runs...")
            with ThreadPoolExecutor() as executor:
                future_to_key = {
                    executor.submit(
                        ask,
                        prompt["system"],
                        user_input,
                        provider,
                        selected_model,
                        ollama_base_url,
                    ): key
                    for key, prompt in PROMPTS.items()
                }
                for index, future in enumerate(as_completed(future_to_key), start=1):
                    key = future_to_key[future]
                    results[key] = future.result()
                    progress_bar.progress(index / total)
                    status.write(f"{index} of {total} variants complete")
                status.write("Compare run complete")

            st.session_state.last_results = results

if st.session_state.last_results and st.session_state.last_user_input:
    st.chat_message("user").write(st.session_state.last_user_input)

    if st.session_state.last_mode == "Single":
        key = st.session_state.last_selected_key
        result = st.session_state.last_results[key]
        with st.chat_message("assistant"):
            render_run_meta(result)
            render_reply(result["content"])
            render_export_actions(result, key)
    else:
        for key, prompt in PROMPTS.items():
            result = st.session_state.last_results[key]
            with st.expander(prompt["name"], expanded=True):
                st.caption(prompt["description"])
                render_run_meta(result)
                render_reply(result["content"])
                render_export_actions(result, key)
