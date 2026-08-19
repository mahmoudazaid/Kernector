"""Keyword (BM25) and vector retrieval over labs/lab02/data/knowledge_base.json.

Try a query against both methods:
    uv run python -m labs.lab02.retrieval "ERR-4021"

Vector search needs OPENROUTER_API_KEY (see embeddings.py) and caches the
knowledge-base vectors in labs/lab02/output/kb_embeddings.json so repeat runs cost nothing.
Tokenization is lowercase with punctuation stripped and no stemming, so "keys"
does not match "key".
"""

import argparse
import re
import sys
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi

from embeddings import cosine_similarity, embed_texts, load_records, save_records

KNOWLEDGE_BASE_PATH = "labs/lab02/data/knowledge_base.json"
CACHE_PATH = "labs/lab02/output/kb_embeddings.json"

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())

@lru_cache(maxsize=1)
def knowledge_base() -> list[dict]:
    return load_records(KNOWLEDGE_BASE_PATH)

@lru_cache(maxsize=1)
def bm25_index() -> BM25Okapi:
    return BM25Okapi([tokenize(document["text"]) for document in knowledge_base()])

@lru_cache(maxsize=1)
def knowledge_base_vectors() -> list[list[float]]:
    documents = knowledge_base()
    if Path(CACHE_PATH).exists():
        cached = load_records(CACHE_PATH)
        if [(item["id"], item["text"]) for item in cached] == [
            (document["id"], document["text"]) for document in documents
        ]:
            return [item["embedding"] for item in cached]
        print(f"  {CACHE_PATH} is stale, re-embedding the knowledge base")

    vectors = embed_texts([document["text"] for document in documents])
    save_records(
        [{**document, "embedding": vector} for document, vector in zip(documents, vectors)],
        CACHE_PATH,
    )
    return vectors

def search_bm25(query: str, top_k: int = 5) -> list[dict]:
    documents = knowledge_base()
    scores = bm25_index().get_scores(tokenize(query))
    ranked = sorted(zip(scores, documents), key=lambda pair: pair[0], reverse=True)
    return [
        {"doc_id": document["id"], "score": float(score), "text": document["text"]}
        for score, document in ranked[:top_k]
    ]

def search_vector(query: str, top_k: int = 5) -> list[dict]:
    documents = knowledge_base()
    query_vector = embed_texts([query])[0]
    ranked = sorted(
        (
            (cosine_similarity(query_vector, vector), document)
            for vector, document in zip(knowledge_base_vectors(), documents)
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return [
        {"doc_id": document["id"], "score": float(score), "text": document["text"]}
        for score, document in ranked[:top_k]
    ]

def normalize_scores(scores: list[float]) -> list[float]:
    lowest, highest = min(scores), max(scores)
    span = highest - lowest
    if span == 0.0:
        return [0.0] * len(scores)
    return [(score - lowest) / span for score in scores]

def search_hybrid(query: str, top_k: int = 5, alpha: float = 0.5) -> list[dict]:
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be between 0 and 1, got {alpha}")
    bm25 = normalize_scores(bm25_scores(query))
    vector = normalize_scores(vector_scores(query))
    # alpha weights BM25, so alpha=1 is BM25 only and alpha=0 is vector only.
    # Note this is inverted from the common convention where alpha weights the dense side.
    fused = [alpha * keyword + (1.0 - alpha) * dense for keyword, dense in zip(bm25, vector)]
    return rank_hits(fused, top_k)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the knowledge base with BM25, vector, and hybrid retrieval.")
    parser.add_argument("query", nargs="+", help="the search query")
    parser.add_argument("--alpha", type=float, default=0.5, help="hybrid BM25 weight, 0 is vector only and 1 is BM25 only")
    parser.add_argument("--top-k", type=int, default=5, help="how many hits to show per method")
    arguments = parser.parse_args()

    query = " ".join(arguments.query)
    print(f"query:  {query!r}")
    print(f"tokens: {tokenize(query)}")

    results = (
        ("bm25", search_bm25(query, arguments.top_k)),
        ("vector", search_vector(query, arguments.top_k)),
        (f"hybrid alpha={arguments.alpha}", search_hybrid(query, arguments.top_k, arguments.alpha)),
    )
    for label, hits in results:
        print(f"-- {label} --")
        for rank, hit in enumerate(hits, start=1):
            print(f"  {rank}. {hit['score']:8.4f}  {hit['doc_id']}  {hit['text'][:70]}")

def bm25_scores(query: str) -> list[float]:
    return [float(score) for score in bm25_index().get_scores(tokenize(query))]

def vector_scores(query: str) -> list[float]:
    query_vector = embed_texts([query])[0]
    return [cosine_similarity(query_vector, vector) for vector in knowledge_base_vectors()]

def rank_hits(scores: list[float], top_k: int) -> list[dict]:
    documents = knowledge_base()
    ranked = sorted(zip(scores, documents), key=lambda pair: pair[0], reverse=True)
    return [
        {"doc_id": document["id"], "score": float(score), "text": document["text"]}
        for score, document in ranked[:top_k]
    ]

def search_bm25(query: str, top_k: int = 5) -> list[dict]:
    return rank_hits(bm25_scores(query), top_k)

def search_vector(query: str, top_k: int = 5) -> list[dict]:
    return rank_hits(vector_scores(query), top_k)

if __name__ == "__main__":
    main()
