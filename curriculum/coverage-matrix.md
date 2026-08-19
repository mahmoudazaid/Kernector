# Coverage matrix

Construct-to-topic evidence is folded into this file. Statuses are progressive: workshop use can establish `practiced` later, never `taught` by itself. `assessed` requires an independent check.

Last audited commit: `162c666`. All rows are **planned** (placement approved, content unwritten).

| Topic | Category | Required by | Theory unit | Guided practice | Workshop | Assessment | Status | Construct / Merge | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| Tooling / dependency resolution | eng | all runs | L01 | GP01 | W01 | A01 | planned | `uv`, `pyproject.toml`, `uv.lock`, `.python-version` / `1676cf6` | high |
| Functions, types, dicts | py | W01+ | L02 | GP02 | W01 | A02 | planned | `ask() -> dict`; list/dict contracts / PR #47 | high |
| Path + files | py | W02, W09 | L03 | GP03 | W02 | A03 | planned | `Path.read_text` / write JSON / PR #45, #63 | high |
| Secrets / env | eng | W01 | L04 | GP04 | W01 | A04 | planned | `load_dotenv`, `.env` gitignored / PR #13, `.gitignore` | high |
| Exceptions / timeouts | py | W01, W06 | L05 | GP05 | W01 | A05 | planned | `requests.exceptions.RequestException`, `timeout=` / `llm.py` | high |
| HTTP + JSON + requests | eng | W01 | L06 | GP06 | W01 (CLI) | A06, A07 | planned | POST `/chat/completions`; JSON messages / PR #13 | high |
| Prompt techniques | app | W02 | L07 | GP07 | W02 | A08 | planned | five `prompts/*.md`; `PROMPT_COMPARISON.md` / `e1ad222` | medium |
| Prompt files / loader | app | W02 | L08 | GP08 | W02 | A09 | planned | `parse_prompt_file`, `PROMPTS` / PR #45 | high |
| Streamlit UI | fw | W03 | L09 | GP09 | W03 | A10, A11 | planned | sidebar, `selectbox`, `chat_input`, `st.markdown` / PR #13 | high |
| Validation + result dict | app | W04 | L10 | GP10 | W04 | A12 | planned | `validate_input`, `is_not_interview_prep` / PR #46 | high |
| Latency / usage / export | app | W04 | L11 | GP11 | W04 | A13 | planned | `time.perf_counter`, usage dict, `st.download_button` / PR #47 | high |
| session_state | fw | W04–W08 | L12 | GP12 | W04, W08 | A14 | planned | `last_*` then `messages` / `c578aec`, PR #62 | high |
| Thread pool I/O | py | W05 | L13 | GP13 | W05 | A15, A16 | planned | `ThreadPoolExecutor`, `as_completed` / `c578aec`; removed PR #62 | high |
| Providers / Ollama | app | W06 | L14 | GP14 | W06 | A17 | planned | Ollama `/v1/chat/completions`, `/api/tags`, `@st.cache_data` / PR #48 | high |
| LangChain chat | fw | W07 | L15 | GP15 | W07 | A18 | planned | `ChatPromptTemplate \| ChatOpenAI`, `invoke` / PR #54 | high |
| Sampling settings | app | W07 | L16 | GP16 | W07 | A19 | planned | `Setting` dataclass, sliders, `**applied` / PR #55 | high |
| Chat history | app | W08 | L17 | GP17 | W08 | A20 | planned | `MessagesPlaceholder`, `to_provider_messages` / PR #62 | high |
| Embeddings + cosine | app | W09 | L18 | GP18 | W09 | A21 | planned | `OpenAIEmbeddings`, numpy cosine, `save_records` / PR #63 | high |
| PCA + plot | app | W10 | L19 | GP19 | W10 | A22 | planned | `sklearn.decomposition.PCA`, matplotlib / PR #64 | high |
| BM25 vs vector | app | W11 | L20 | GP20 | W11 | A23 | planned | `rank_bm25.BM25Okapi`, `tokenize`, `search_vector` / PR #65 | high |
| Hit@k, MRR | app | W11 | L21 | GP21 | W11 | A24 | planned | `evaluate.py` ranks, CSV / PR #65 | high |
| Hybrid fuse | app | W12 | L22 | GP22 | W12 | A25 | planned | `normalize_scores`, `search_hybrid`, `--alpha` / PR #66 | high |
| Script checks | eng | W09, W11 | L18, L21 (subsection) | — | W09, W11 | A21, A24 | planned | `test_similarity.py`, `test_retrieval.py` | high |
| argparse | py | W11–W12 | L20 (subsection) | — | W11, W12 | A23, A25 | planned | `retrieval.py` CLI | high |
| lru_cache | py | W11 | L20 (subsection) | — | W11 | A23 | planned | KB / BM25 / vectors cache / PR #65 | high |
| csv module | py | W11 | L21 (subsection) | — | W11 | A24 | planned | `csv.DictWriter` / PR #65 | high |
| pandas | — | unused | — | — | — | — | ignore | `pyproject.toml` only | high |
| watchdog | — | unused | — | — | — | — | ignore | `pyproject.toml` only | high |

## Notes folded from construct evidence

- Group by learning outcome, not by import or commit.
- W01 omits Streamlit even though PR #13 combined UI and HTTP.
- HEAD `search_hybrid` alpha weights **BM25** (1 = BM25 only); document that vs the common dense-alpha convention.
- `evaluate.py` at `162c666` still compares BM25 vs vector only.
- Guard substring in code is `## Not Interview Pre` (truncated); treat as a brittle output contract.
