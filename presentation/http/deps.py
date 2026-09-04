"""FastAPI dependencies for the HTTP presentation adapter."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from composition import Settings, load_runtime_settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Resolve runtime settings once per process through composition.

    Mirrors Streamlit's ``@st.cache_resource`` settings load: avoids re-running
    ``configure_logging`` / ``load_dotenv(override=True)`` on every request.
    """
    return load_runtime_settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
