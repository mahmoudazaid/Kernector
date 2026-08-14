import os
from dotenv import load_dotenv
load_dotenv(override=True)

# Provider selection
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter").lower()

# OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL")
OPENROUTER_MODELS = [
    m.strip() for m in os.getenv("OPENROUTER_MODELS", "").split(",") if m.strip()
]
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL")
OPENROUTER_TIMEOUT = float(os.getenv("OPENROUTER_TIMEOUT", "120"))

# Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_PROBE_TIMEOUT = float(os.getenv("OLLAMA_PROBE_TIMEOUT", "5"))

# Input limits
MAX_INPUT_LENGTH = 10000