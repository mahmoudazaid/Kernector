"""Checks for retrieval.py and evaluate.py. Run: uv run python -m labs.lab02.test_retrieval

No network access. BM25 and the metrics are pure functions over committed data,
and the vector checks read labs/lab02/output/kb_embeddings.json, skipping if it is absent.
"""

from pathlib import Path

from embeddings import cosine_similarity
from labs.lab02.evaluate import (
    actual_winner,
    first_relevant_rank,
    hit_rate,
    mean_reciprocal_rank,
)
from labs.lab02.retrieval import CACHE_PATH, knowledge_base, knowledge_base_vectors, search_bm25, tokenize

failures = []

def check(label: str, passed: bool) -> None:
    print(f"{'PASS' if passed else 'FAIL'}  {label}")
    if not passed:
        failures.append(label)

print("-- tokenizer --")
check("error codes stay one token", tokenize("ERR-4021") == ["err-4021"])
check("punctuation is stripped", tokenize("What does ERR-4210 mean?") == ["what", "does", "err-4210", "mean"])
check("no stemming, so keys does not match key", tokenize("keys") != tokenize("key"))

print("-- bm25 exact identifiers, no api --")
for query, expected in [("ERR-4021", "kb-01"), ("ERR-4210", "kb-02"), ("ERR-5003", "kb-03")]:
    hits = search_bm25(query, top_k=3)
    check(f"{query} ranks {expected} first", hits[0]["doc_id"] == expected)
    check(f"{query} rank 1 has a positive score", hits[0]["score"] > 0)
    check(f"{query} rank 2 scores exactly zero", hits[1]["score"] == 0.0)

hits = search_bm25("ERR-4021", top_k=3)
check("hits carry doc_id, score and text", all({"doc_id", "score", "text"} <= set(hit) for hit in hits))
check("top_k is respected", len(search_bm25("ERR-4021", top_k=2)) == 2)
check(
    "ERR-4210 does not retrieve the transposed code kb-01",
    search_bm25("ERR-4210", top_k=1)[0]["doc_id"] != "kb-01",
)

print("-- metrics on synthetic data --")
ranks = [1, 2, None, 4]
check("hit rate keeps misses in the denominator, 3 of 4", hit_rate(ranks) == 0.75)
check("mrr of [1, 2, miss, 4] is 0.4375", abs(mean_reciprocal_rank(ranks) - 0.4375) < 1e-9)
check("all rank 1 gives mrr 1.0", mean_reciprocal_rank([1, 1, 1]) == 1.0)
check("all misses give mrr 0.0", mean_reciprocal_rank([None, None]) == 0.0)
check("all misses give hit rate 0.0", hit_rate([None, None]) == 0.0)

ordered = [{"doc_id": "kb-09"}, {"doc_id": "kb-05"}, {"doc_id": "kb-01"}]
check("first relevant rank is positional, not best", first_relevant_rank(ordered, ["kb-01", "kb-05"]) == 2)
check("first relevant rank is None when nothing matches", first_relevant_rank(ordered, ["kb-16"]) is None)

check("lower rank wins", actual_winner({"bm25": 1, "vector": 3}) == "bm25")
check("a miss loses to a hit", actual_winner({"bm25": None, "vector": 3}) == "vector")
check("equal ranks tie", actual_winner({"bm25": 2, "vector": 2}) == "tie")
check("two misses is neither", actual_winner({"bm25": None, "vector": None}) == "neither")

print("-- vector cache, no api --")
if not Path(CACHE_PATH).exists():
    print(f"SKIP  {CACHE_PATH} missing, run: uv run python -m labs.lab02.evaluate")
else:
    documents = knowledge_base()
    vectors = knowledge_base_vectors()
    check("one cached vector per document", len(vectors) == len(documents))
    check(
        "vectors share one non-zero length",
        len({len(vector) for vector in vectors}) == 1 and len(vectors[0]) > 0,
    )
    index = {document["id"]: vector for document, vector in zip(documents, vectors)}
    related = cosine_similarity(index["kb-07"], index["kb-08"])
    unrelated = cosine_similarity(index["kb-07"], index["kb-14"])
    print(f"      kb-07/kb-08 {related:.4f} vs kb-07/kb-14 {unrelated:.4f}")
    check("the two password docs beat an unrelated invoices doc", related > unrelated)

print()
if failures:
    print(f"{len(failures)} check(s) failed:")
    for label in failures:
        print(f"  - {label}")
    raise SystemExit(1)
print("all checks passed")
