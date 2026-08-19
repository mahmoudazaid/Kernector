# Python prerequisite schedule

Schedule every required Python/engineering concept **before** the first lesson or workshop that depends on it. Do not front-load the whole language. Do not introduce a framework for the first time inside a workshop.

Last audited commit: `162c666`.

## Ordering rules

1. Dicts and return contracts before HTTP/JSON/`requests` and before any workshop that builds request or result objects.
2. `requests` is third-party, not the standard library.
3. First API workshop (W01) is CLI-only: no Streamlit, widgets, `session_state`, or rerun.
4. Streamlit theory (L09) before W03. `session_state` (L12) after basic Streamlit, before workshops that persist across reruns.
5. Concurrency (L13) before W05. LangChain (L15) before W07.

## Schedule

| Sequence | Unit | Constructs | Teach as | First dependent use |
|---|---|---|---|---|
| 1 | L01 | `uv`, virtual env, `pyproject.toml`, lockfile, `.python-version`, `requires-python` | standalone | any `uv run` |
| 2 | L02 | functions, annotations, `list`/`dict`/`tuple`, return contracts | standalone | W01 `ask()` result dict; JSON bodies |
| 3 | L03 | `pathlib.Path`, encoding, read/write text | standalone | W02 prompt files; later JSON records |
| 4 | L04 | `os.getenv`, `python-dotenv`, `.env` vs source, `.gitignore` | standalone | W01 API key |
| 5 | L05 | `try/except`, exception types, timeouts | standalone | W01/W06 HTTP |
| 6 | L06 | HTTP verbs, headers, JSON encode/decode, status codes, **`requests`** | standalone | **W01** |
| 7 | L08 | `Path.glob`, split/parse text, dict registry at import | standalone (after L03, L07) | W02 |
| 8 | L09 | Streamlit script-rerun, widgets, sidebar, `st.chat_input` | standalone | **W03** |
| 9 | L12 | `st.session_state` lifetime vs locals | standalone (after L09) | W04 persist, W05 last results, W08 `messages` |
| 10 | L13 | `ThreadPoolExecutor`, `submit`, `Future`, `as_completed`, completion order, no shared UI mutation | standalone | **W05** |
| 11 | L15 | `ChatOpenAI`, `ChatPromptTemplate`, `|`, `invoke` | standalone | **W07** |
| 12 | L16 | `dataclass`, kwargs, filtering unknown keys | standalone | W07 settings |
| 13 | L18 | numpy arrays, `dot`/`norm`, zero-vector guard | standalone | **W09** |
| 14 | L19 | PCA as projection; explained variance; matplotlib `Agg` | standalone | **W10** |
| 15 | L20 | `re` tokenization, ranking, hyphenated tokens | standalone | **W11** |
| 16 | L21 | `None` vs rank, division by corpus size, `csv` | standalone | **W11** |
| 17 | L22 | min-max normalize, weighted sum | standalone | **W12** |

## Subsections (host lesson only)

| Construct | Host | Notes |
|---|---|---|
| `argparse` | L20 / W11 | retrieval CLI |
| `functools.lru_cache` | L20 / W11 | index/vector cache |
| `csv.DictWriter` | L21 | eval results |
| Script-style `check()` tests | L18 / L21 | `test_similarity.py`, `test_retrieval.py` (not pytest) |

## Explicitly not scheduled before W01

Streamlit, `session_state`, LangChain, Ollama, embeddings, BM25, PCA, hybrid fusion, `ThreadPoolExecutor`.

## Unused dependencies (do not schedule)

`pandas`, `watchdog` — declared in `pyproject.toml`, not used in merged product or lab modules at `162c666`.
