# Kernector

## Run the Streamlit app

```bash
uv run streamlit run main.py
```

## Upload and manage documents

1. Start the app with the command above.
2. Under **Upload new document**, choose one supported file: `.txt`, `.md`, `.markdown`, or `.pdf`.
3. Submit **Upload new**. The app assigns a system-managed UUID source ID (never derived from the file name). Matching filenames create separate documents.
4. Under **Uploaded documents**, select a row to inspect status, chunk count, and the diagnostic source ID.
5. To overwrite content for a selected document, choose a replacement file and submit **Replace** (same source ID; old chunks are replaced). Filenames never trigger replacement by themselves.
6. To remove a document, confirm and click **Delete** (vector chunks first, then the catalog row).

Upload catalog metadata is stored at `data/catalog/uploads.json` by default (`DOCUMENT_CATALOG_PATH`). Seed-corpus documents remain separate and do not appear in this list.

While a create/replace/delete is running, action buttons stay disabled so a repeated click in the same session is rejected before another run starts.

If ingest fails because the store expects a different embedding size, remove the local Chroma directory and try again:

```bash
rm -rf data/chroma
```
