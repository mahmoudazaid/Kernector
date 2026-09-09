"""Constant vectors used only to construct EmbeddedChunk for BM25 ingest."""

from __future__ import annotations

EVAL_VECTOR: tuple[float, ...] = (1.0, 0.0, 0.0, 1.0)


class ConstantVectorAdapter:
    """Tiny adapter that ignores text and returns ``EVAL_VECTOR``.

    BM25 indexes chunk text, not this vector. The value exists only because
    ``EmbeddedChunk`` requires a non-empty numeric vector.
    """

    def vector_for(self, text: str) -> tuple[float, ...]:
        """Return the constant eval vector.

        Args:
            text (str): Ignored chunk or query text.

        Returns:
            tuple[float, ...]: ``EVAL_VECTOR``.
        """
        del text
        return EVAL_VECTOR
