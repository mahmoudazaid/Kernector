"""Embed documents into a local Milvus Lite collection and search it.

Run: uv run python -m labs.lab03.store_milvus

Milvus Lite is embedded and file backed, so there is no server to start. The
collection is dropped and recreated on every run, which keeps reruns idempotent.
Unlike the sqlite store, the search happens inside the database rather than as a
cosine loop in Python.
"""

from pathlib import Path

from pymilvus import MilvusClient

from embeddings import embed_texts

DB_PATH = "labs/lab03/output/milvus_demo.db"
COLLECTION_NAME = "demo_collection"
TOP_K = 2

DOCUMENTS = [
    "Artificial intelligence was founded as an academic discipline in 1956.",
    "Alan Turing was the first person to conduct substantial research in AI.",
    "Born in Maida Vale, London, Turing was raised in southern England.",
]
QUERY = "Who is Alan Turing?"

def make_client(db_path: str = DB_PATH) -> MilvusClient:
    # Milvus Lite refuses to open a path whose parent directory is missing.
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return MilvusClient(db_path)

def build_collection(client: MilvusClient, documents: list[str], subject: str) -> list[dict]:
    vectors = embed_texts(documents)

    if client.has_collection(collection_name=COLLECTION_NAME):
        client.drop_collection(collection_name=COLLECTION_NAME)
    # Derive the dimension from the vectors so a model swap cannot desync the schema.
    client.create_collection(collection_name=COLLECTION_NAME, dimension=len(vectors[0]))

    return [
        {"id": index, "vector": vector, "text": text, "subject": subject}
        for index, (text, vector) in enumerate(zip(documents, vectors))
    ]

def search(client: MilvusClient, query: str, top_k: int = TOP_K) -> list[dict]:
    query_vector = embed_texts([query])[0]
    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_vector],
        limit=top_k,
        output_fields=["text", "subject"],
    )
    return results[0]

def main() -> None:
    client = make_client()

    rows = build_collection(client, DOCUMENTS, subject="history")
    inserted = client.insert(collection_name=COLLECTION_NAME, data=rows)
    print(f"inserted {inserted['insert_count']} rows into {COLLECTION_NAME} ({DB_PATH})")
    print(f"dimension: {len(rows[0]['vector'])}")

    print(f"query: {QUERY!r}")
    for rank, hit in enumerate(search(client, QUERY), start=1):
        print(f"  {rank}. {hit['distance']:8.4f}  {hit['entity']['text']}")

if __name__ == "__main__":
    main()
