# Architecture

Kernector is organised into four layers so that UI frameworks cannot own
business logic and the UI stays replaceable.

## Layers

| Layer | Holds | May import |
|---|---|---|
| `domain/` | Business rules, entities, port protocols | Standard library only |
| `application/` | Use-case orchestration | `domain` |
| `infrastructure/` | LLM clients, config, prompt loading, embeddings | `domain` + third-party libs |
| `presentation/` | Streamlit UI, composition root | `application`, `domain`, and `infrastructure` (for wiring only) |

## Allowed dependency directions

    presentation ──> application ──> domain
           │                            ▲
           └──────> infrastructure ─────┘

Everything points inward toward `domain`. Nothing points outward.

## Rules

- `domain` imports nothing but the standard library. No LangChain, no
  OpenRouter, no Chroma, no Streamlit, no `requests`, no `config`.
- `application` imports `domain` only. It never imports Streamlit, LangChain,
  or anything that performs I/O; it talks to the outside world through the
  port protocols in `domain/ports.py`.
- `infrastructure` implements those ports. It may import any third-party
  library, but never `application` or `presentation`.
- `presentation` is the only layer allowed to import Streamlit, and the only
  layer allowed to construct `infrastructure` objects.

## Composition root

`presentation/streamlit/app.py` wires concrete infrastructure implementations
into application services. It is the single place where the layers are joined.