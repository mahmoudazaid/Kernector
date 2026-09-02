"""Behavior of min-max normalize and alpha-weighted hybrid fusion."""

import pytest

from application.hybrid_fusion import fuse_hybrid_scores, normalize_scores


def test_normalize_scores_minmax_maps_extremes_to_zero_and_one() -> None:
    assert normalize_scores([2.0, 5.0, 8.0]) == (0.0, 0.5, 1.0)


def test_normalize_scores_flat_span_yields_all_ones() -> None:
    assert normalize_scores([3.0, 3.0, 3.0]) == (1.0, 1.0, 1.0)


def test_normalize_scores_empty_yields_empty() -> None:
    assert normalize_scores([]) == ()


def test_normalize_scores_single_value_is_one() -> None:
    assert normalize_scores([7.0]) == (1.0,)


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


def test_fuse_single_vector_hit_with_alpha_zero_is_one() -> None:
    fused = fuse_hybrid_scores(
        bm25_scores=[None],
        vector_scores=[0.42],
        alpha=0.0,
    )
    assert fused == (1.0,)


def test_fuse_single_lexical_hit_with_alpha_one_is_one() -> None:
    fused = fuse_hybrid_scores(
        bm25_scores=[3.5],
        vector_scores=[None],
        alpha=1.0,
    )
    assert fused == (1.0,)


def test_fuse_equal_present_scores_stay_valid_ones() -> None:
    fused = fuse_hybrid_scores(
        bm25_scores=[2.0, 2.0],
        vector_scores=[None, None],
        alpha=1.0,
    )
    assert fused == (1.0, 1.0)


def test_fuse_sparse_lexical_only_gets_no_artificial_vector_norm_from_raw_zero() -> None:
    """Absent vector scores must not enter min-max as raw 0.0.

    With negatives present, inserting 0.0 for a lexical-only candidate would
    place it mid-range (~0.5) and inflate its fused score.
    """
    fused = fuse_hybrid_scores(
        bm25_scores=[10.0, 0.0, None, None],
        vector_scores=[None, None, -0.8, 0.8],
        alpha=0.5,
    )
    # BM25 [10, 0] → [1, 0]; vector [-0.8, 0.8] → [0, 1]
    # L: 0.5*1 + 0.5*0 = 0.5  (not 0.75 from bogus vector_norm=0.5)
    assert fused[0] == pytest.approx(0.5)
    assert fused[1] == pytest.approx(0.0)
    assert fused[2] == pytest.approx(0.0)
    assert fused[3] == pytest.approx(0.5)


def test_fuse_sparse_vector_only_candidate_gets_zero_bm25_contribution() -> None:
    fused = fuse_hybrid_scores(
        bm25_scores=[None, 2.0, 8.0],
        vector_scores=[0.9, 0.1, None],
        alpha=0.5,
    )
    assert fused == (0.5, 0.0, 0.5)


def test_fuse_sparse_overlapping_and_disjoint_with_multiple_present() -> None:
    fused = fuse_hybrid_scores(
        bm25_scores=[10.0, 0.0, None],
        vector_scores=[0.2, None, -0.2],
        alpha=0.5,
    )
    assert fused == (1.0, 0.0, 0.0)


def test_fuse_sparse_empty_channel_assigns_zero_for_all() -> None:
    fused = fuse_hybrid_scores(
        bm25_scores=[None, None],
        vector_scores=[0.0, 1.0],
        alpha=0.5,
    )
    assert fused == (0.0, 0.5)


def test_fuse_missing_channel_entries_remain_zero() -> None:
    fused = fuse_hybrid_scores(
        bm25_scores=[5.0, None],
        vector_scores=[None, 0.7],
        alpha=0.5,
    )
    # Single present each side → 1.0; missing → 0.0 → fused [0.5, 0.5]
    assert fused == (0.5, 0.5)


def test_fuse_hybrid_scores_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        fuse_hybrid_scores(bm25_scores=[1.0], vector_scores=[1.0, 2.0], alpha=0.5)


def test_fuse_hybrid_scores_rejects_alpha_outside_unit_interval() -> None:
    with pytest.raises(ValueError, match="alpha"):
        fuse_hybrid_scores(bm25_scores=[1.0], vector_scores=[1.0], alpha=1.5)


def test_fuse_requires_at_least_one_score_per_candidate() -> None:
    with pytest.raises(ValueError, match="absent from both"):
        fuse_hybrid_scores(
            bm25_scores=[None, 1.0],
            vector_scores=[None, 1.0],
            alpha=0.5,
        )
