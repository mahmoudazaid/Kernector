"""Embed data/documents.json and write output/embeddings.json.

Run: uv run python -m labs.lab01.embed_and_store
"""

from embeddings import embed_texts, load_records, save_records

DOCUMENTS_PATH = "labs/lab01/data/documents.json"
EMBEDDINGS_PATH = "labs/lab01/output/embeddings.json"

def main() -> None:
    documents = load_records(DOCUMENTS_PATH)
    print(f"Loaded {len(documents)} documents from {DOCUMENTS_PATH}")

    vectors = embed_texts([document["text"] for document in documents])
    if len(vectors) != len(documents):
        raise RuntimeError(f"Expected {len(documents)} vectors, got {len(vectors)}")

    records = [{**document, "embedding": vector} for document, vector in zip(documents, vectors)]
    save_records(records, EMBEDDINGS_PATH)

    print(f"Wrote {len(records)} records to {EMBEDDINGS_PATH}")
    print(f"Vector dimensions: {len(records[0]['embedding'])}")

if __name__ == "__main__":
    main()
