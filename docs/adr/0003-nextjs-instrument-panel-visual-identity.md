# ADR 0003: Next.js Instrument panel visual identity

## Status

Accepted

## Context

The Next.js shell under `web/` is the long-term interactive presentation
surface (see [ADR 0002](0002-nextjs-presentation-migration.md)). Early pages
shipped with workable layout but inconsistent control chrome: native file
pickers, stock selects, flat filled buttons, and per-screen one-offs. That
drift reads as a wireframe collection rather than one product.

Product direction for `web/` is an **Instrument panel**: a cool, professional
AI knowledge workspace — not a marketing landing page and not a generic
dashboard kit. Contributors repeatedly reintroduced mismatched controls when
adding Chat, Settings, and Knowledge Hub UI. This ADR records the visual
system so future screens reuse the same tokens and recipes instead of
inventing a local look.

## Decision

1. **Identity name** — **Instrument panel**. Cool slate neutrals, restrained
   teal accent, IBM Plex Sans / Mono, soft elevation. Domain / pack branding
   stays gated; the shell itself remains product-neutral.

2. **Token source of truth** — Semantic CSS custom properties live only in
   [`web/styles/tokens.css`](../../web/styles/tokens.css). Feature CSS in
   `web/app/globals.css` (and component modules) **consumes** those tokens; it
   must not hard-code competing palettes, sheens, or emboss shadows for
   interactive chrome. Light and dark are **paired surfaces** via
   `light-dark()` on `:root` plus explicit `:root[data-theme="light|dark"]`
   overrides — not a flat invert of light mode.

3. **Soft glass emboss (required control recipe)** — Interactive faces share:

   | Token | Role |
   | --- | --- |
   | `--kern-control-highlight` / `--kern-control-shade` | Inset highlight and shade |
   | `--kern-control-sheen` | Gloss gradient on surface / secondary controls |
   | `--kern-control-sheen-fill` | Weaker gloss on **accent-filled** controls so label contrast stays WCAG AA |
   | `--kern-control-emboss` | Resting depth |
   | `--kern-control-emboss-press` | Pressed / hover-in depth |

   Typical resting face:

   ```css
   background: var(--kern-control-sheen), var(--kern-surface);
   box-shadow: var(--kern-control-emboss);
   ```

   Accent-filled primary actions use `--kern-control-sheen-fill` over
   `--kern-accent` (or equivalent) with light text that remains AA. Do not
   apply the strong surface sheen on filled primaries — it washes out labels
   in light theme.

4. **Main pane fill (workspace layout)** — Product workspace screens occupy
   the full width of `.kern-main` (`width: 100%`; no decorative content
   `max-width` that leaves empty side gutters). This includes Knowledge Hub
   (catalog / table / upload), Chat, and Dashboard. Lead copy may keep a
   readable measure (for example `max-width` on `.kern-documents-lead` only).
   **Exception:** dense preference forms such as Settings may keep a
   constrained column (`~40rem`) for readability. Do not reintroduce a
   page-level max-width on table or catalog surfaces.

5. **App-wide scope** — The emboss recipe applies to **every** Next.js
   product surface that shows controls or chrome, including at least:

   - Shell: sidebar nav pills, brand mark, theme / menu triggers
   - Buttons: `.kern-btn`, secondary / ghost / danger variants
   - Chat: bubbles, composer, **circular** send control
   - Settings: fieldsets, radios, range thumbs, SoftSelect
   - Knowledge Hub: fieldsets, file inputs (`::file-selector-button`),
     row actions, confirm dialogs
   - Dialogs: `ConfirmDialog` (`.kern-dialog`) for destructive or
     irreversible confirms

   New routes must match before merge. Prefer shared classes
   (`.kern-settings-fieldset`, `.kern-settings-input`, `.kern-btn`, …) over
   page-local visual systems.

6. **Native controls and system chrome** — Do not ship unstyled browser chrome
   for product UI. File inputs, checkboxes, radios, and range thumbs need the
   emboss recipe (or SoftSelect for listboxes). Custom listboxes use
   `web/components/ui/SoftSelect.tsx` rather than a second select pattern.
   **Do not use `window.confirm`, `window.alert`, or `window.prompt`** for
   product flows — they break Instrument panel identity. Use
   `web/components/ui/ConfirmDialog.tsx` (soft-glass panel, embossed actions,
   Escape / backdrop dismiss) or an equivalent token-backed dialog. Destructive
   confirms use the danger button variant (`.kern-btn-danger`).

7. **Geometry and motion** — Pill radii for many controls
   (`--kern-radius-pill`); chat send stays a **circle** (`border-radius: 50%`),
   not a rounded rectangle. Motion uses `--kern-duration` /
   `--kern-duration-emphasis` and `--kern-ease` / `--kern-ease-out`. Prefer a
   light press-in (`emboss-press` + slight scale) over heavy glow stacks.

8. **Explicit non-goals (do not regress to)** — Do not replace this identity
   with: purple / indigo gradient kits; warm cream + terracotta serif
   marketing looks; broadsheet / newspaper dense columns; dark-mode-only
   defaults; multi-layer neon glow; emoji decoration as chrome; per-page
   accent colors; narrow “card column” layouts on workspace pages that waste
   the main pane; native system dialogs for confirms; or copied third-party
   widget markup that bypasses tokens.

9. **Guardrail tests** — `web/__tests__/design-tokens.test.ts` asserts the
   required token names on `:root` and theme overrides (including control
   sheen / emboss tokens). Keep that contract in sync when adding tokens.
   Visual regressions on a screen are fixed by applying shared recipes, not
   by forking tokens under a new name for one page.

## Consequences

- PRs that add or restyle `web/` UI are incomplete if controls look native or
  flat relative to Settings / Chat / Knowledge Hub under the same theme, if
  workspace pages leave unused side gutters from an artificial content
  `max-width`, or if confirms use browser system dialogs.
- Changing the identity (palette, emboss model, type, main-pane fill, or
  dialog recipe) requires updating this ADR (or a superseding ADR),
  `tokens.css`, `web/README.md` Visual direction, and the design-token tests
  together — not a silent CSS drift on one route.
- Accessibility for filled controls is part of the identity: prefer
  `--kern-control-sheen-fill` and verified contrast over stronger gloss.
- Streamlit presentation is out of scope for this ADR; it is not required to
  mirror Instrument panel chrome.

## Related docs

- [web/README.md](../../web/README.md) — Visual direction summary for
  contributors
- [web/styles/tokens.css](../../web/styles/tokens.css) — token definitions
- [web/components/ui/ConfirmDialog.tsx](../../web/components/ui/ConfirmDialog.tsx)
  — shared soft-glass confirm dialog
- [ADR 0002](0002-nextjs-presentation-migration.md) — Next.js / HTTP ownership
  of `web/`
