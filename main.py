import json
import os
import streamlit as st
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

st.title("Kernecktor - Interview prepration")
user_input = st.chat_input("Enter your question")
if user_input:
    st.chat_message('user').write(user_input)
    r=requests.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json",
        },
        json={
            "model": os.getenv('OPENROUTER_MODEL'),
            "messages": [
                {"role": "system", "content": "You are an interview coach."},
                {"role": "user", "content": user_input},
            ],
        },
    )
    data = r.json()
    st.write(data)
    reply = r.json()["choices"][0]["message"]["content"]
    st.chat_message('assistant').write(reply)