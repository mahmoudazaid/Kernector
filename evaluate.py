"""Evaluate BM25 against vector retrieval on data/eval_queries.json.

Run: uv run python evaluate.py

Writes output/eval_results.csv, prints a summary, and prints every failure.

Both metrics are rank based, because BM25 scores are unnormalized sums over
query terms and are not comparable across queries:
  Hit Rate at K  fraction of queries with at least one relevant doc in the top K
  MRR            mean of 1/rank of the first relevant doc, counting a miss as 0
"""

import csv
from pathlib import Path

from embeddings import load_records
from retrieval import search_bm25, search_vector

QUERIES_PATH = "data/eval_queries.json"
RESULTS_PATH = "output/eval_results.csv"
TOP_K = 3

METHODS = {"bm25": search_bm25, "vector": search_vector}

def first_relevant_rank(hits: list[dict], relevant_ids: list[str]) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if hit["doc_id"] in relevant_ids:
            return rank
    return None

def hit_rate(ranks: list[int | None]) -> float:
    return sum(1 for rank in ranks if rank is not None) / len(ranks)

def mean_reciprocal_rank(ranks: list[int | None]) -> float:
    return sum(1 / rank for rank in ranks if rank is not None) / len(ranks)

def actual_winner(ranks: dict[str, int | None]) -> str:
    bm25, vector = ranks["bm25"], ranks["vector"]
    if bm25 is None and vector is None:
        return "neither"
    if bm25 is None:
        return "vector"
    if vector is None:
        return "bm25"
    if bm25 == vector:
        return "tie"
    return "bm25" if bm25 < vector else "vector"

def run_evaluation() -> tuple[list[dict], dict[str, dict]]:
    queries = load_records(QUERIES_PATH)
    rows, hits_by_query = [], {}

    for query in queries:
        row = {
            "query_id": query["id"],
            "query": query["query"],
            "kind": query["kind"],
            "relevant_ids": " ".join(query["relevant_ids"]),
            "expected_winner": query["expected_winner"],
        }
        ranks, hits_by_method = {}, {}

        for name, search in METHODS.items():
            hits = search(query["query"], top_k=TOP_K)
            hits_by_method[name] = hits
            rank = first_relevant_rank(hits, query["relevant_ids"])
            ranks[name] = rank
            row[f"{name}_rank"] = rank
            row[f"{name}_hit"] = int(rank is not None)
            row[f"{name}_reciprocal_rank"] = round(1 / rank, 4) if rank else 0.0
            row[f"{name}_top1"] = hits[0]["doc_id"]

        row["actual_winner"] = actual_winner(ranks)
        rows.append(row)
        hits_by_query[query["id"]] = hits_by_method

    return rows, hits_by_query

def report_summary(rows: list[dict]) -> None:
    print(f"-- summary over {len(rows)} queries at top_k {TOP_K} --")
    print(f"  {'method':8s} {'hit_rate':>9s} {'mrr':>7s}")
    for name in METHODS:
        ranks = [row[f"{name}_rank"] for row in rows]
        print(f"  {name:8s} {hit_rate(ranks):9.3f} {mean_reciprocal_rank(ranks):7.3f}")

def report_predictions(rows: list[dict]) -> None:
    print("-- predicted winner vs actual --")
    for row in rows:
        mark = "ok  " if row["expected_winner"] == row["actual_winner"] else "MISS"
        print(
            f"  {mark} {row['query_id']}  {row['kind']:17s}"
            f" expected {row['expected_winner']:8s} actual {row['actual_winner']}"
        )
    held = sum(1 for row in rows if row["expected_winner"] == row["actual_winner"])
    print(f"  {held}/{len(rows)} predictions held")

def report_failures(rows: list[dict], hits_by_query: dict[str, dict]) -> None:
    print("-- failures, nothing hidden --")
    failed = False
    for row in rows:
        missed_by = [name for name in METHODS if not row[f"{name}_hit"]]
        if not missed_by:
            continue
        failed = True
        print(f"  {row['query_id']} {row['query']!r}")
        print(f"    expected {row['relevant_ids']}, missed by {', '.join(missed_by)}")
        for name in missed_by:
            for rank, hit in enumerate(hits_by_query[row["query_id"]][name], start=1):
                print(f"      {name:6s} {rank}. {hit['score']:8.4f}  {hit['doc_id']}  {hit['text'][:55]}")
    if not failed:
        print("  none")

def write_csv(rows: list[dict], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {path}")

def main() -> None:
    rows, hits_by_query = run_evaluation()
    report_summary(rows)
    report_predictions(rows)
    report_failures(rows, hits_by_query)
    write_csv(rows, RESULTS_PATH)

if __name__ == "__main__":
    main()
