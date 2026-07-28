import os
import time
import streamlit as st
import requests
from dotenv import load_dotenv
from prompts_loader import DEFAULT_PROMPT, PROMPTS

load_dotenv(override=True)
MAX_STORY_LENGTH = 1000

def validate_story(story: str) -> str | None:
    if not story.strip():
        return "Please paste a user story before analyzing."
    if len(story) > MAX_STORY_LENGTH:
        return f"User story is too long (max {MAX_STORY_LENGTH} characters)."
    return None

def is_not_a_user_story(reply: str) -> bool:
    return "## Not a User Story" in reply

def render_reply(reply: str) -> None:
    if is_not_a_user_story(reply):
        st.warning("This input does not look like a user story.")
    st.markdown(reply)

def ask(system: str, user_text: str) -> dict:
    model = os.getenv("OPENROUTER_MODEL")
    try:
        started = time.perf_counter()
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
            },
            timeout=30,
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
            "content": "Failed to connect to OpenRouter",
            "model": model,
            "latency_ms": None,
            "usage": None,
        }
    except (KeyError, IndexError, ValueError):
        return {
            "content": "Failed to parse response from OpenRouter",
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

st.session_state.setdefault("last_user_input", None)
st.session_state.setdefault("last_mode", None)
st.session_state.setdefault("last_selected_key", None)
st.session_state.setdefault("last_results", None)

st.title("Kernector - Story Analysis")

with st.sidebar:
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

user_input = st.chat_input("Paste a user story to analyze")
if user_input:
    error = validate_story(user_input)
    if error:
        st.error(error)
    else:
        st.session_state.last_user_input = user_input
        st.session_state.last_mode = mode
        st.session_state.last_selected_key = selected_key

        if mode == "Single":
            prompt = PROMPTS[selected_key]
            with st.spinner(f"Analyzing with {prompt['name']}..."):
                result = ask(prompt["system"], user_input)
            st.session_state.last_results = {selected_key: result}
        else:
            results = {}
            for key, prompt in PROMPTS.items():
                with st.spinner(f"Running {prompt['name']}..."):
                    results[key] = ask(prompt["system"], user_input)
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
            with st.expander(prompt["name"], expanded=False):
                st.caption(prompt["description"])
                render_run_meta(result)
                render_reply(result["content"])
                render_export_actions(result, key)