"""Min-max normalization and alpha-weighted BM25 + vector score fusion."""

from collections.abc import Sequence


def normalize_scores(scores: Sequence[float]) -> tuple[float, ...]:
    """Min-max normalize ``scores`` into ``[0, 1]``.

    An empty input yields ``()``. A single present score or a flat span of equal
    scores yields ``1.0`` for each entry so channel evidence is preserved (missing
    candidates stay ``0.0`` only via sparse fusion, not via flat collapse).
    """
    if not scores:
        return ()
    low = min(scores)
    high = max(scores)
    span = high - low
    if span == 0:
        return tuple(1.0 for _ in scores)
    return tuple((value - low) / span for value in scores)


def _normalize_sparse(scores: Sequence[float | None]) -> tuple[float, ...]:
    """Min-max only genuine channel scores; absent entries contribute ``0.0``."""
    present = [score for score in scores if score is not None]
    if not present:
        return tuple(0.0 for _ in scores)
    norms = normalize_scores(present)
    iterator = iter(norms)
    return tuple(
        next(iterator) if score is not None else 0.0 for score in scores
    )


def fuse_hybrid_scores(
    *,
    bm25_scores: Sequence[float | None],
    vector_scores: Sequence[float | None],
    alpha: float,
) -> tuple[float, ...]:
    """Fuse aligned BM25 and vector scores.

    Formula: ``alpha * norm(BM25) + (1 - alpha) * norm(vector)``.
    ``alpha`` weights BM25 (``1`` = BM25 only, ``0`` = vector only).

    ``None`` means the candidate was absent from that channel. Only genuine
    scores participate in min-max normalization; absent slots get normalized
    contribution ``0.0`` afterward (never a raw ``0.0`` inserted before norm).
    Flat or single-score channels normalize to ``1.0`` so evidence is kept.
    """
    if not isinstance(alpha, (int, float)) or isinstance(alpha, bool):
        raise ValueError(f"alpha must be a number in [0, 1], got {alpha!r}")
    if alpha < 0 or alpha > 1:
        raise ValueError(f"alpha must be in [0, 1], got {alpha!r}")
    if len(bm25_scores) != len(vector_scores):
        raise ValueError(
            "bm25_scores and vector_scores must have the same length, "
            f"got {len(bm25_scores)} and {len(vector_scores)}"
        )
    for index, (bm25, vector) in enumerate(
        zip(bm25_scores, vector_scores, strict=True)
    ):
        if bm25 is None and vector is None:
            raise ValueError(
                f"candidate at index {index} is absent from both channels"
            )
    bm25_norm = _normalize_sparse(bm25_scores)
    vector_norm = _normalize_sparse(vector_scores)
    return tuple(
        alpha * bm25 + (1.0 - alpha) * vector
        for bm25, vector in zip(bm25_norm, vector_norm, strict=True)
    )
