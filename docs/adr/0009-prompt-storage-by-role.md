# ADR 0009: Store prompts by role

## Status

Accepted

## Context

Kernector has three kinds of prompt text, and until now they were stored
inconsistently:

- **Platform policy** that forms a security boundary: `GROUNDED_RAG_SYSTEM`,
  `AGENT_GROUNDED_RETRIEVE_POLICY`, `GENERAL_ANSWER_SYSTEM`,
  `agent_tool_system_prompt()`, and `REWRITE_SYSTEM`. These embed shared
  constants such as the retrieved-context delimiters, and
  `application/grounded_rag_policy.py` keeps its policy a module constant so
  `PROMPT_PACKS` cannot hide it or offer it as a selectable Mode.
- **Short fixed presets**: the response-style instructions and the RAG judge
  metric prompts, each a few lines.
- **Long domain prompts**: `GENERATE_CASES_SYSTEM` and
  `TEST_CANDIDATE_SUGGESTION_SYSTEM` in `packs/software_delivery/test_design/`.
  These hold dozens of business rules, change often, and were Python f-strings
  full of `\` line continuations and escaped quotes, which made them hard to
  read, review, and edit.

Separately, `prompts/packs/` held user-selectable task prompts loaded by
`MarkdownPromptRepository` through `PROMPT_PACKS`. The Story Intelligence and
core packs there no longer matched the product and were removed, so
`PROMPT_PACKS` now defaults to empty.

## Decision

1. **Platform policy stays in Python.** Prompts that state trust rules or
   embed delimiters other code depends on remain module constants in the use
   case that owns them. They are never loaded from configurable paths.
2. **Short presets stay in Python.** A separate file per few-line string adds
   more indirection than it saves.
3. **Long domain prompts live in Markdown next to their use case.** Each pack
   feature keeps its templates in a `prompts/` package beside the code that
   sends them, for example
   `packs/software_delivery/test_design/prompts/generate_cases.md`. The owning
   module renders the template once at import into the same module constant
   it exposed before, so callers and tests do not change.
4. **Rendering is strict.** Templates use `string.Template` `$NAME`
   placeholders. `load_prompt` loads the file through `importlib.resources`
   and fails at import when a file is missing, a placeholder has no value, or
   a supplied value has no placeholder. A renamed placeholder can never reach
   the model as literal text.
5. **One rule per line.** A Markdown template writes each rule as one line so
   the rendered text matches the former Python string exactly and substring
   assertions in tests keep working.
6. **`prompts/packs/` is only for user-selectable modes.** It stays the home
   for optional task prompts chosen through `PROMPT_PACKS`. Mandatory prompts
   do not go there. None ship by default.

## Consequences

- Domain prompt changes are plain Markdown diffs that non-Python contributors
  can review and edit.
- Loading uses only the standard library, so packs keep their
  domain-plus-stdlib import rule.
- `test/packs/software_delivery/test_design/test_prompts.py` checks that every
  template is rendered by a use case, carries the context delimiters, leaves no
  unresolved placeholder, and that the loader rejects missing or unused
  values.
- The loader is local to `test_design`. If another pack needs Markdown
  prompts, move the loader into a shared package at that point rather than
  copying it.
- Prompt text is now split between Python and Markdown. Choose by role using
  the rules above, not by length alone.

## Related docs

- [ADR 0001 (domain-agnostic knowledge foundation)](0001-domain-agnostic-knowledge-foundation.md)
- [ADR 0008 (group modules by concern)](0008-group-modules-by-concern.md)
- [ARCHITECTURE.md](../../ARCHITECTURE.md)
