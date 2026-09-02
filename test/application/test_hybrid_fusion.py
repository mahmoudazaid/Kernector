"""Behavior of min-max normalize and alpha-weighted hybrid fusion."""

import pytest

from application.hybrid_fusion import fuse_hybrid_scores, normalize_scores


def test_normalize_scores_minmax_maps_extremes_to_zero_and_one() -> None:
    assert normalize_scores([2.0, 5.0, 8.0]) == (0.0, 0.5, 1.0)


def test_normalize_scores_flat_span_yields_all_zeros() -> None:
    assert normalize_scores([3.0, 3.0, 3.0]) == (0.0, 0.0, 0.0)


def test_normalize_scores_empty_yields_empty() -> None:
    assert normalize_scores([]) == ()


def test_normalize_scores_single_value_is_zero() -> None:
    assert normalize_scores([7.0]) == (0.0,)


def test_fuse_hybrid_scores_alpha_one_is_bm25_only() -> None:
    assert fuse_hybrid_scores(
        bm25_scores=[0.0, 10.0],
        vector_scores=[100.0, 0.0],
        alpha=1.0,
    ) == (0.0, 1.0)


def test_fuse_hybrid_scores_alpha_zero_is_vector_only() -> None:
    assert fuse_hybrid_scores(
        bm25_scores=[0.0, 10.0],
        vector_scores=[0.0, 4.0],
        alpha=0.0,
    ) == (0.0, 1.0)


def test_fuse_hybrid_scores_equal_alpha_averages_norms() -> None:
    assert fuse_hybrid_scores(
        bm25_scores=[0.0, 10.0],
        vector_scores=[0.0, 4.0],
        alpha=0.5,
    ) == (0.0, 1.0)


def test_fuse_hybrid_scores_blends_disagreeing_modalities() -> None:
    assert fuse_hybrid_scores(
        bm25_scores=[10.0, 0.0],
        vector_scores=[0.0, 4.0],
        alpha=0.5,
    ) == (0.5, 0.5)


def test_fuse_hybrid_scores_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        fuse_hybrid_scores(bm25_scores=[1.0], vector_scores=[1.0, 2.0], alpha=0.5)


def test_fuse_hybrid_scores_rejects_alpha_outside_unit_interval() -> None:
    with pytest.raises(ValueError, match="alpha"):
        fuse_hybrid_scores(bm25_scores=[1.0], vector_scores=[1.0], alpha=1.5)
