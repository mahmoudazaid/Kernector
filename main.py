import os
import streamlit as st
import requests
from dotenv import load_dotenv
from prompts import DEFAULT_PROMPT, PROMPTS

load_dotenv(override=True)


def ask(system: str, user_text: str) -> str:
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("OPENROUTER_MODEL"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException:
        return "Failed to connect to OpenRouter"
    except (KeyError, IndexError, ValueError):
        return "Failed to parse response from OpenRouter"

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

if mode == "Single":
    st.caption(f"Using: {PROMPTS[selected_key]['name']}")
else:
    st.caption("Comparing all prompt variants")

user_input = st.chat_input("Paste a user story to analyze")
if user_input:
    st.chat_message("user").write(user_input)

    if mode == "Single":
        prompt = PROMPTS[selected_key]
        with st.spinner(f"Analyzing with {prompt['name']}..."):
            reply = ask(prompt["system"], user_input)
        st.chat_message("assistant").write(reply)
    else:
        for key, prompt in PROMPTS.items():
            with st.expander(prompt["name"], expanded=False):
                st.caption(prompt["description"])
                with st.spinner(f"Running {prompt['name']}..."):
                    reply = ask(prompt["system"], user_input)
                st.markdown(reply)
