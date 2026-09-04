"""FastAPI dependencies for the HTTP presentation adapter."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from application.runtime_settings import GetRuntimeSettings, ProbeOllamaStatus
from composition import Settings, build_probe_ollama_status, build_runtime_settings, load_runtime_settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Resolve runtime settings once per process through composition.

    Mirrors Streamlit's ``@st.cache_resource`` settings load: avoids re-running
    ``configure_logging`` / ``load_dotenv(override=True)`` on every request.
    """
    return load_runtime_settings()


def get_runtime_settings(
    settings: Annotated[Settings, Depends(get_settings)],
) -> GetRuntimeSettings:
    """Build the runtime settings catalog use case for this request."""
    return build_runtime_settings(settings)


def get_probe_ollama_status(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProbeOllamaStatus:
    """Build the Ollama probe use case for this request."""
    return build_probe_ollama_status(settings)


SettingsDep = Annotated[Settings, Depends(get_settings)]
RuntimeSettingsDep = Annotated[GetRuntimeSettings, Depends(get_runtime_settings)]
ProbeOllamaStatusDep = Annotated[ProbeOllamaStatus, Depends(get_probe_ollama_status)]
