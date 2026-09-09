"""Catalog adapter errors shared across JSON and SQL implementations."""


class CatalogError(RuntimeError):
    """Base error raised by document catalog adapters."""
