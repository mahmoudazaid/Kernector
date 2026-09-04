"""FastAPI dependencies for the HTTP presentation adapter."""

from composition import Settings, load_runtime_settings


def get_settings() -> Settings:
    """Resolve runtime settings through composition (never infrastructure)."""
    return load_runtime_settings()
