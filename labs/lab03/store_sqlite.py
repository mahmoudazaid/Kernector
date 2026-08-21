import sqlite3
from pathlib import Path

import numpy as np

from embeddings import embed_texts

DB_PATH = "labs/lab03/output/embeddings.db"


def save_embeddings_to_db(embeddings, db_path=DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create table if it doesn't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            embedding BLOB
        )
    ''')

    for text, embedding in embeddings.items():
        # Convert the NumPy array to a bytes object
        embedding_bytes = embedding.tobytes()
        cursor.execute("INSERT INTO embeddings (text, embedding) VALUES (?, ?)", (text, embedding_bytes))

    conn.commit()
    conn.close()

texts = [
    "The food was delicious and the waiter...",
    "The movie was amazing, the acting was superb.",
    "I had a terrible experience at the hotel."
]
embeddings_dict = {
    text: np.asarray(vector, dtype=np.float32)
    for text, vector in zip(texts, embed_texts(texts))
}

save_embeddings_to_db(embeddings_dict)

def read_embeddings_from_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT text, embedding FROM embeddings")
    rows = cursor.fetchall()

    embeddings = {}
    for row in rows:
        text = row[0]
        # Convert the bytes object back to a NumPy array
        embedding_bytes = row[1]
        embedding = np.frombuffer(embedding_bytes, dtype=np.float32)  # Assuming float32
        embeddings[text] = embedding

    conn.close()
    return embeddings

# Example usage:
retrieved_embeddings = read_embeddings_from_db()
print(retrieved_embeddings)

for text, embedding in retrieved_embeddings.items():
    print(f"Text: {text}")
    print(f"Embedding: {embedding}")