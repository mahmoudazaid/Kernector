# Kernector

## Run the Streamlit app

```bash
uv run streamlit run main.py
```

## Upload a document into the knowledge base

1. Start the app with the command above.
2. Choose one supported file: `.txt`, `.md`, `.markdown`, or `.pdf`.
3. Enter a stable, unique source ID (identity is never taken from the file name).
4. Submit **Ingest** and read the accepted-document and chunk counts.
5. Re-uploading with the same source ID replaces that source's chunks; a new source ID keeps a separate source even when the file names match.

While ingestion is running, the Ingest button stays disabled so a repeated click in the same session is rejected before another run starts.

If ingest fails because the store expects a different embedding size, remove the local Chroma directory and try again:

```bash
rm -rf data/chroma
```
