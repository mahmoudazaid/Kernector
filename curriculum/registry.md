# Learning-path registry

Phase 1 planning ledger. No lesson, workshop, or assessment prose lives here.

- **Course context:** Kernector (Streamlit interview-prep chatbot + embedding/retrieval labs)
- **Primary branch:** `main`
- **Last audited commit:** `162c666` (2026-08-19, PR #66)
- **Audited range:** `57b9429` … `162c666` (first-parent)
- **ID convention:** `Lxx` theory, `Wxx` workshops, `Axx` assessments, `GPxx` guided practice
- **Ledger rule:** additive only (`unchanged` / `extended` / `inserted` / `corrected`); do not renumber approved IDs

## Status key

`planned` — placement approved, content not written. Nothing is `taught`, `practiced`, or `assessed` yet.

## Theory units

| ID | Title | Depth | First workshop | Assessment |
|---|---|---|---|---|
| L01 | Project tooling (`uv`, `pyproject.toml`, lockfile, Python ≥3.13) | apply | W01 | A01 |
| L02 | Functions, annotations, collections, return contracts | apply | W01 | A02 |
| L03 | Files, `Path`, UTF-8 text | apply | W02 | A03 |
| L04 | Configuration and secrets (`.env`, dotenv, gitignore) | apply | W01 | A04 |
| L05 | Exceptions and timeouts at process boundaries | apply | W01 | A05 |
| L06 | HTTP JSON APIs with `requests` (not stdlib) | apply | W01 | A06 |
| L07 | Chat prompt techniques (zero-shot, few-shot, CoT, structured, critique) | explain | W02 | A08 |
| L08 | Externalizing prompts (markdown + frontmatter loader) | apply | W02 | A09 |
| L09 | Streamlit UI model (script rerun, widgets, layout, `chat_input`) | apply | W03 | A10 |
| L10 | Input validation and structured model results | apply | W04 | A12 |
| L11 | Measuring model calls (latency, tokens, cost, export) | apply | W04 | A13 |
| L12 | `st.session_state` and rerun persistence | apply | W04 / W08 | A14 |
| L13 | I/O-bound concurrency (`ThreadPoolExecutor`, `Future`, `as_completed`) | apply | W05 | A15 |
| L14 | Hosted vs local OpenAI-compatible providers | apply | W06 | A17 |
| L15 | LangChain chat composition (`ChatPromptTemplate`, `\|`, `invoke`) | apply | W07 | A18 |
| L16 | Generation hyperparameters and dataclass settings tables | apply | W07 | A19 |
| L17 | Multi-turn message lists and history placeholders | apply | W08 | A20 |
| L18 | Embeddings, numpy vectors, cosine similarity, JSON persistence | apply | W09 | A21 |
| L19 | Embedding-space visualization (PCA as lossy 2D, plotting) | explain | W10 | A22 |
| L20 | Lexical vs dense retrieval (tokenize, BM25, vector top-k) | apply | W11 | A23 |
| L21 | Ranked evaluation (hit@k, MRR, gold labels, documented misses) | apply | W11 | A24 |
| L22 | Hybrid score fusion (min-max normalize, alpha) | apply | W12 | A25 |

Subsections (not standalone units): `argparse`, `functools.lru_cache`, `csv`, script-style `check()` tests.

## Workshops

Cumulative chain. W01 is CLI/API-only even though PR #13 shipped Streamlit with `requests`. W05 is a historical stage (compare + threads) later removed in W08 to match HEAD.

| ID | Title | Assessment |
|---|---|---|
| W01 | CLI OpenRouter chat via `requests` + result dict | A07 |
| W02 | File-based prompt variants and loader | A09 |
| W03 | Streamlit single-mode analysis UI | A11 |
| W04 | Validation, run metadata, export, session persistence | A12–A14 |
| W05 | Compare-all-prompts with parallel HTTP | A16 |
| W06 | Ollama provider + reachability probe | A17 |
| W07 | LangChain OpenRouter path + tunable settings | A18–A19 |
| W08 | Multi-turn chatbot; drop compare/concurrency | A20 |
| W09 | Shared embedding client + similarity checks | A21 |
| W10 | Embed corpus, pair scores, PCA plot | A22 |
| W11 | BM25 vs vector retrieval + evaluation CSV | A23–A24 |
| W12 | Optional hybrid search (`alpha` weights BM25 in HEAD) | A25 |

## Assessments

One independent check per course-worthy unit (theory and workshop). Criteria to be written in a later phase.

| ID | Unit | Checks |
|---|---|---|
| A01 | L01 | Recreate env from lockfile; explain why lockfile exists |
| A02 | L02 | Write a typed function returning a result dict |
| A03 | L03 | Read/write UTF-8 files with `Path` |
| A04 | L04 | Load a secret from env; keep it out of source |
| A05 | L05 | Map timeout / HTTP / parse failures to caller-safe outcomes |
| A06 | L06 | Identify request shape (URL, headers, JSON) without Streamlit |
| A07 | W01 | CLI call to chat completions; parse `choices[0].message.content` |
| A08 | L07 | Match a prompt file to a named technique and its trade-off |
| A09 | W02 / L08 | Parse frontmatter; reject missing default / duplicate keys |
| A10 | L09 | Explain one widget interaction as a full script rerun |
| A11 | W03 | Single-mode Streamlit ask using a loaded prompt |
| A12 | L10 / W04 | Empty/overlong input; guard-string handling |
| A13 | L11 / W04 | Report latency/usage when present; export markdown |
| A14 | L12 | Persist output across a rerun via `session_state` |
| A15 | L13 | Explain completion order vs submit order; no UI mutation in workers |
| A16 | W05 | Parallel compare of independent prompt runs |
| A17 | L14 / W06 | Switch provider; probe vs generate timeout |
| A18 | L15 / W07 | Compose `prompt \| model` for OpenRouter only |
| A19 | L16 / W07 | Pass allowed sampling keys; ignore unknown keys |
| A20 | L17 / W08 | Multi-turn history without sending UI meta as content |
| A21 | L18 / W09 | Cosine edge cases; fail-fast missing API key; JSON round-trip |
| A22 | L19 / W10 | Interpret clusters without treating 2D as full truth |
| A23 | L20 / W11 | Exact-id BM25 vs paraphrase vector on the same corpus |
| A24 | L21 / W11 | Hit@k / MRR with misses in the denominator |
| A25 | L22 / W12 | Fuse scores; state HEAD alpha convention (BM25 weight) |

## Implementation timeline (evidence, not lesson list)

| Merge / commit | Upgrade |
|---|---|
| `1676cf6` | `uv` project scaffold |
| PR #13 | Streamlit + `requests` OpenRouter + Single/Compare |
| PR #45 | Markdown prompts + loader |
| PR #46 | Input validation + not-interview-prep guard |
| PR #47 | Latency, usage, export |
| `c578aec` | Thread pool compare + `session_state` last results |
| `e1ad222` | Interview-prep prompt set |
| PR #48 | Ollama |
| PR #54 | `config` / `llm`; LangChain OpenRouter |
| PR #55 | Tunable settings |
| PR #62 | Chat history; remove compare/concurrency |
| PR #63 | `embeddings.py` + `test_similarity.py` |
| PR #64 | lab01 embed + explore |
| PR #65 | lab02 BM25/vector + evaluate |
| PR #66 | Hybrid CLI (`search_hybrid`); eval still BM25 vs vector |

## Deferred / ignore

| Item | Treatment |
|---|---|
| pandas, watchdog (unused) | ignore |
| `115.md` | ignore |
| Streamlit skill trees under `.agents` / `.claude` | ignore |
| pytest / CI | deferred |
| Hybrid columns in `evaluate.py` | deferred |
| Duplicate `search_bm25` / `search_vector` after #66 | reference-only |
| RAG inside the Streamlit app | deferred |
| Ollama embeddings | deferred |

## Additive ledger

| Action | What |
|---|---|
| inserted | First curriculum plan (this registry + schedule + matrix) |
