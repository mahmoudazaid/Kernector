"""Keyword (BM25) and vector retrieval over data/knowledge_base.json.

Try a query against both methods:
    uv run python retrieval.py "ERR-4021"

Vector search needs OPENROUTER_API_KEY (see embeddings.py) and caches the
knowledge-base vectors in output/kb_embeddings.json so repeat runs cost nothing.
Tokenization is lowercase with punctuation stripped and no stemming, so "keys"
does not match "key".
"""

import re
import sys
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi

from embeddings import cosine_similarity, embed_texts, load_records, save_records

KNOWLEDGE_BASE_PATH = "data/knowledge_base.json"
CACHE_PATH = "output/kb_embeddings.json"

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

def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit('Usage: uv run python retrieval.py "your query"')

    query = " ".join(sys.argv[1:])
    print(f"query:  {query!r}")
    print(f"tokens: {tokenize(query)}")

    for label, results in (("bm25", search_bm25(query)), ("vector", search_vector(query))):
        print(f"-- {label} --")
        for rank, hit in enumerate(results, start=1):
            print(f"  {rank}. {hit['score']:8.4f}  {hit['doc_id']}  {hit['text'][:70]}")

if __name__ == "__main__":
    main()
