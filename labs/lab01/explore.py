"""Explore labs/lab01/output/embeddings.json: similarity comparisons, PCA projection, and a plot.

Run: uv run python -m labs.lab01.explore
Requires labs/lab01/output/embeddings.json, produced by: uv run python -m labs.lab01.embed_and_store
"""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from sklearn.decomposition import PCA
from itertools import combinations

from embeddings import cosine_similarity, embed_texts, load_records

EMBEDDINGS_PATH = "labs/lab01/output/embeddings.json"
PLOT_PATH = "labs/lab01/output/embedding_plot.png"

CATEGORY_COLORS = {
    "billing": "#1f77b4",
    "auth": "#d62728",
    "deployment": "#2ca02c",
}


QUERY = "I cannot sign in to my account"

SAME_CATEGORY_PAIRS = [
    ("billing-01", "billing-02"),
    ("auth-01", "auth-02"),
    ("deployment-02", "deployment-06"),
]

CROSS_CATEGORY_PAIRS = [
    ("billing-01", "deployment-01"),
    ("auth-03", "deployment-03"),
    ("billing-03", "auth-06"),
]

def report_pairs(title: str, pairs: list[tuple[str, str]], index: dict) -> list[float]:
    print(f"-- {title} --")
    scores = []
    for left, right in pairs:
        score = cosine_similarity(index[left]["embedding"], index[right]["embedding"])
        scores.append(score)
        print(f"  {score:.4f}  {left} <-> {right}")
    return scores

def check_separation(same_scores: list[float], cross_scores: list[float]) -> None:
    weakest_same = min(same_scores)
    strongest_cross = max(cross_scores)
    print("-- separation check --")
    print(f"  weakest same-category    {weakest_same:.4f}")
    print(f"  strongest cross-category {strongest_cross:.4f}")
    print(f"  margin                   {weakest_same - strongest_cross:+.4f}")
    if weakest_same <= strongest_cross:
        raise SystemExit(
            f"FAILED: weakest same-category pair {weakest_same:.4f} does not beat "
            f"strongest cross-category pair {strongest_cross:.4f}. "
            "The dataset categories are not semantically distinct enough."
        )
    print("  PASS every same-category pair beats every cross-category pair")

def report_query(query: str, records: list[dict], top_n: int = 5) -> None:
    print(f"-- query to doc: {query!r} --")
    query_vector = embed_texts([query])[0]
    ranked = sorted(
        ((cosine_similarity(query_vector, record["embedding"]), record) for record in records),
        key=lambda scored: scored[0],
        reverse=True,
    )
    for score, record in ranked[:top_n]:
        print(f"  {score:.4f}  {record['id']:15s} {record['category']}")
    weakest_score, weakest_record = ranked[-1]
    print(f"  {weakest_score:.4f}  {weakest_record['id']:15s} {weakest_record['category']}  (weakest)")

def project_to_2d(records: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    vectors = np.array([record["embedding"] for record in records])
    pca = PCA(n_components=2, random_state=0)
    coordinates = pca.fit_transform(vectors)
    explained = pca.explained_variance_ratio_
    print("-- pca --")
    print(f"  reduced {vectors.shape[1]} dimensions to 2")
    print(f"  variance explained: PC1 {explained[0]:.1%}, PC2 {explained[1]:.1%}, total {explained.sum():.1%}")
    return coordinates, explained

def save_plot(records: list[dict], coordinates: np.ndarray, explained: np.ndarray, path: str) -> None:
    figure, axes = plt.subplots(figsize=(11, 8))

    for category, color in CATEGORY_COLORS.items():
        indexes = [i for i, record in enumerate(records) if record["category"] == category]
        axes.scatter(
            coordinates[indexes, 0],
            coordinates[indexes, 1],
            c=color,
            label=category,
            s=90,
            alpha=0.85,
            edgecolors="white",
            linewidths=0.8,
        )

    for record, (x, y) in zip(records, coordinates):
        axes.annotate(record["id"], (x, y), fontsize=7, xytext=(5, 4), textcoords="offset points")

    axes.set_xlabel(f"PC1 ({explained[0]:.1%} of variance)")
    axes.set_ylabel(f"PC2 ({explained[1]:.1%} of variance)")
    axes.set_title(
        f"{len(records)} support documents: "
        f"{len(records[0]['embedding'])} dimensions reduced to 2 by PCA"
    )
    axes.legend(title="category")
    axes.grid(True, linestyle=":", alpha=0.4)
    axes.margins(x=0.14, y=0.08)
    figure.tight_layout()

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150)
    plt.close(figure)
    print(f"  saved {path}")

def category_cohesion(records: list[dict]) -> dict[str, float]:
    cohesion = {}
    for category in CATEGORY_COLORS:
        vectors = [record["embedding"] for record in records if record["category"] == category]
        pairs = [cosine_similarity(left, right) for left, right in combinations(vectors, 2)]
        cohesion[category] = sum(pairs) / len(pairs)
    return cohesion

def centroid_scores(record: dict, records: list[dict]) -> dict[str, float]:
    scores = {}
    for category in CATEGORY_COLORS:
        vectors = [
            other["embedding"]
            for other in records
            if other["category"] == category and other["id"] != record["id"]
        ]
        scores[category] = cosine_similarity(record["embedding"], np.mean(vectors, axis=0).tolist())
    return scores

def report_interpretation(records: list[dict], explained: np.ndarray) -> None:
    print("-- interpretation --")

    cohesion = category_cohesion(records)
    print("  cohesion, mean similarity within each category:")
    for category, score in sorted(cohesion.items(), key=lambda item: item[1], reverse=True):
        print(f"    {category:11s} {score:.4f}")

    print("  documents nearer another category's centroid than their own:")
    misplaced = []
    for record in records:
        scores = centroid_scores(record, records)
        nearest = max(scores, key=scores.get)
        if nearest != record["category"]:
            misplaced.append(record["id"])
            print(
                f"    {record['id']:14s} labeled {record['category']} ({scores[record['category']]:.4f})"
                f" but nearer {nearest} ({scores[nearest]:.4f})"
            )
    if not misplaced:
        print("    none")

    print()
    print("  Answer these from the plot and the numbers above:")
    print("   1. Which categories cluster tightly and which spread out? Check against the cohesion scores,")
    print("      and note that distance between clusters is not the same thing as tightness within one.")
    print("   2. Which documents sit between clusters, and what in their wording pulls them there?")
    print(f"   3. Only {explained.sum():.1%} of the variance survives the reduction to 2D.")
    print("      What structure might the plot be hiding, and which numbers should you trust instead?")
    print("   4. Would keyword matching have scored the near-duplicate pairs as highly as cosine similarity did?")

def main() -> None:
    if not Path(EMBEDDINGS_PATH).exists():
        raise SystemExit(f"{EMBEDDINGS_PATH} not found. Run: uv run python -m labs.lab01.embed_and_store")

    records = load_records(EMBEDDINGS_PATH)
    index = {record["id"]: record for record in records}
    print(f"Loaded {len(records)} records of {len(records[0]['embedding'])} dimensions\n")

    same_scores = report_pairs("same category", SAME_CATEGORY_PAIRS, index)
    cross_scores = report_pairs("cross category", CROSS_CATEGORY_PAIRS, index)
    check_separation(same_scores, cross_scores)
    report_query(QUERY, records)
    coordinates, explained = project_to_2d(records)
    save_plot(records, coordinates, explained, PLOT_PATH)
    report_interpretation(records, explained)


if __name__ == "__main__":
    main()
