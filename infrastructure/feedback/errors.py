"""Errors for the response feedback SQLite adapter."""

from __future__ import annotations


class FeedbackStoreError(Exception):
    """SQLite access or schema failure for response feedback storage."""
