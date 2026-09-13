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
     row actions, confirm dialogs, **connector cards and browse pickers**
     (decision 12)
   - Waits: brand `Loader` (`web/components/ui/Loader.tsx`) on every
     screen-level load
   - Dialogs: `DialogFrame` (`.kern-dialog`) for every overlay; `ConfirmDialog`
     for destructive or irreversible confirms
   - Timestamps: `formatTimestamp` (`09 Sep 2026, 09:35 AM`)

   New routes must match before merge. Prefer shared classes
   (`.kern-settings-fieldset`, `.kern-settings-input`, `.kern-btn`, …) over
   page-local visual systems.

6. **Native controls and system chrome** — Do not ship unstyled browser chrome
   for product UI. File inputs, checkboxes, radios, and range thumbs need the
   emboss recipe (or SoftSelect for listboxes). Custom listboxes use
   `web/components/ui/SoftSelect.tsx` rather than a second select pattern.
   **Do not use `window.confirm`, `window.alert`, or `window.prompt`** for
   product flows — they break Instrument panel identity. Use
   `web/components/ui/ConfirmDialog.tsx` or `DialogFrame` (soft-glass panel,
   overlay fade + panel scale, embossed actions, Escape / backdrop dismiss).
   Destructive confirms use the danger button variant (`.kern-btn-danger`).

7. **Geometry and motion** — Pill radii for many controls
   (`--kern-radius-pill`); chat send stays a **circle** (`border-radius: 50%`),
   not a rounded rectangle. Motion uses `--kern-duration` /
   `--kern-duration-emphasis` and `--kern-ease` / `--kern-ease-out`. Prefer a
   light press-in (`emboss-press` + slight scale) over heavy glow stacks.

   **Dialog enter / exit (required overlay recipe)** — Every product dialog
   (delete confirm, upload, connector browse pickers, and future overlays)
   uses [`DialogFrame`](../../web/components/ui/DialogFrame.tsx) with the
   [Motion Base UI dialog](https://motion.dev/examples/react-base-dialog)
   overlay + content pattern: the scrim fades on its own (`opacity` 0→1,
   ~200ms) while the soft-glass panel independently fades and scales
   (`opacity` 0→1, `scale` 0.9→1) on a spring (`duration` 0.5, `bounce`
   0.2). Do not fade the positioning root — that hides the scale. Keep
   Instrument panel chrome (tokens, emboss, type); do not adopt Base UI
   styling. `prefers-reduced-motion` keeps a 200ms opacity fade and drops
   scale. Do not invent a second overlay animation per screen.

8. **Explicit non-goals (do not regress to)** — Do not replace this identity
   with: purple / indigo gradient kits; warm cream + terracotta serif
   marketing looks; broadsheet / newspaper dense columns; dark-mode-only
   defaults; multi-layer neon glow; emoji decoration as chrome; per-page
   accent colors; narrow “card column” layouts on workspace pages that waste
   the main pane; native system dialogs for confirms; or copied third-party
   widget markup that bypasses tokens; skeleton bars or “Loading …” lead
   copy as the wait UI; mixed timestamp formats.

9. **Guardrail tests** — `web/__tests__/design-tokens.test.ts` asserts the
   required token names on `:root` and theme overrides (including control
   sheen / emboss tokens). Keep that contract in sync when adding tokens.
   `web/__tests__/timestamp-guardrail.test.ts` forbids locale-default date
   formatters (`toLocaleString`, `toLocaleDateString`, `toLocaleTimeString`,
   `Intl.DateTimeFormat`) and relative-time copy (“Just now”, “Yesterday”,
   “N min ago”) in `web/lib` and `web/components` except `formatTimestamp`.
   `toLocaleString` also matches number grouping; mark those lines with
   `// allow-locale-number`. Visual regressions on a screen are fixed by
   applying shared recipes, not by forking tokens under a new name for one
   page.

10. **Brand loader (required wait recipe)** — Screen-level and in-panel
    waits use the blinking Kernector mark via
    [`web/components/ui/Loader.tsx`](../../web/components/ui/Loader.tsx)
    (and `LoadingState` for full-pane waits). Status copy is visually
    hidden (`role="status"`). Do not present “Loading …” lead text,
    skeleton bars, or a second spinner as the wait UI. Chat
    turn-in-progress stays `KernectorThinkingMark` — that is a thinking
    cue, not a page loader. Overlay waits (Drive sync, picker browse)
    reuse `Loader` at `sm` / `md`; page waits use `lg`. Honor
    `prefers-reduced-motion` (lids hold closed). New routes must use this
    recipe before merge.

11. **Timestamps** — Every visible clock time in `web/` uses
    [`formatTimestamp`](../../web/lib/format/timestamp.ts):
    **`09 Sep 2026, 09:35 AM`** (local wall clock, `DD Mon YYYY, HH:MM AM/PM`,
    English month abbreviations, 12-hour, no timezone suffix). Do not use
    relative copy (“5 min ago”), locale-default `toLocaleString()`, or
    timezone abbreviations (`EEST`). Machine values stay ISO-8601 on the
    wire and in `datetime` attributes wherever the timestamp is rendered as
    its own element.

12. **Knowledge Hub connectors (required card + browse recipe)** — Every
    OAuth / sync connector on the Connectors surface reuses the Google Drive
    card and picker chrome. Do not invent a second card layout, inline scope
    form, or modal styling per provider.

    **Connected card (`.kern-source-card`)** — Match
    [`GoogleDrivePanel`](../../web/components/documents/GoogleDrivePanel.tsx):

    | Region | Content |
    | --- | --- |
    | Title row | Provider icon, name, short kind line, status pill (`Connected` / reconnect / setup) |
    | Metrics (`.kern-source-metrics`) | Two columns only: **Account** (login or email) \| **Indexed** (document count) |
    | Sync block (`.kern-sync-section`) | **Last synced** via `formatTimestamp` (or `Never`). Providers with a single sync scope (for example one GitHub repository) may add one prior row in the same block (label + value), not extra metric columns |
    | Actions (`.kern-source-actions.is-split`) | Left: primary **Browse**, secondary **Sync**. Right: danger **Disconnect** |

    Disconnected state uses `.kern-available-card` + **Connect** (same pattern
    as Drive). Disconnect confirms through `ConfirmDialog` with
    `tone="danger"`. Do not put repository / folder / project pickers,
    selects, or “Save and sync” controls inside the card body.

    **Browse picker (required overlay)** — **Browse** opens a
    `DialogFrame` with `panelClassName="kern-picker-dialog"` — the same
    recipe as
    [`GoogleDrivePicker`](../../web/components/documents/GoogleDrivePicker.tsx)
    and
    [`GitHubPicker`](../../web/components/documents/GitHubPicker.tsx):

    - Title + short body copy; ghost close control
    - Optional search row (`.kern-picker-search`) when the catalog is large
    - Scrollable list (`.kern-picker-list`) of `.kern-drive-item` rows
      (checkbox or radio as the product model requires; icon + primary name
      + muted meta)
    - Footer (`.kern-picker-foot`): live selection summary + **Cancel** /
      **Save** (or equivalent primary confirm). Keep the primary label
      **Save** while the control is disabled — do not swap it to
      “Saving…”.

    **GitHub sources picker (required)** — GitHub uses one
    **Choose GitHub sources** dialog with two independent panels visible
    together (`.kern-github-sources-panels`): **Repository code** (required,
    exactly one) and **Project issues** (optional, zero or one). Do **not**
    use tabs. Each panel has its own search. Project is not a child of the
    repository. Provide an obvious **Clear project** action. Footer:
    `1 source selected` / `2 sources selected`; primary **Save sources**;
    disable until a repository is selected. Two columns on desktop; stack on
    narrow viewports.

    **Save dismiss + card busy (required)** — On **Save**, close the picker
    immediately (`setPickerOpen(false)` before awaiting persist/sync), then
    run save + initial sync under the connector card busy overlay
    (`cardBusy = busy && !pickerOpen`, `Loader` with a short “Syncing …”
    label). Do not leave the dialog open as the loading surface. Persist
    failures surface on the **card** (`role="alert"` / action error), not
    inside a closed picker. Match
    [`GoogleDrivePanel.onAddSelection`](../../web/components/documents/GoogleDrivePanel.tsx)
    and
    [`GitHubPanel.onSaveSelection`](../../web/components/documents/GitHubPanel.tsx).

    Selection that drives sync lives in that dialog only. After save, the
    card shows the chosen scope as plain values (account metrics + optional
    sync-section row), never as an embedded form. Future connectors (Jira,
    Confluence, and others) must copy this card + picker split; extend shared
    classes rather than forking layout.

    **Stable connector identity** — Each configured GitHub connector instance
    persists an opaque `connector_id` with the grant/config. Catalog rows and
    provenance carry it. Reconciliation and deletion are scoped by
    `workspace_id` (catalog binding) + `connector_id`, never by
    `source_type="github"` alone. Changing the repository or Project keeps the
    same `connector_id`; a new Connect after disconnect mints a new id.

## Consequences

- PRs that add or restyle `web/` UI are incomplete if controls look native or
  flat relative to Settings / Chat / Knowledge Hub under the same theme, if
  workspace pages leave unused side gutters from an artificial content
  `max-width`, if confirms use browser system dialogs, or if a new connector
  ships a divergent card metrics layout or an inline / non-`DialogFrame`
  browse picker.
- Changing the identity (palette, emboss model, type, main-pane fill,
  dialog recipe, or connector card / picker recipe) requires updating this
  ADR (or a superseding ADR), `tokens.css`, `web/README.md` Visual
  direction, and the design-token tests together — not a silent CSS drift on
  one route.
- Accessibility for filled controls is part of the identity: prefer
  `--kern-control-sheen-fill` and verified contrast over stronger gloss.
- Streamlit presentation is out of scope for this ADR; it is not required to
  mirror Instrument panel chrome.

## Related docs

- [web/README.md](../../web/README.md) — Visual direction summary for
  contributors
- [web/styles/tokens.css](../../web/styles/tokens.css) — token definitions
- [web/components/ui/DialogFrame.tsx](../../web/components/ui/DialogFrame.tsx)
  — shared overlay fade + panel scale for every dialog
- [web/components/ui/ConfirmDialog.tsx](../../web/components/ui/ConfirmDialog.tsx)
  — shared soft-glass confirm dialog
- [web/components/ui/Loader.tsx](../../web/components/ui/Loader.tsx) —
  brand wait mark for every screen
- [web/components/states/LoadingState.tsx](../../web/components/states/LoadingState.tsx)
  — full-pane wait wrapping `Loader`
- [web/lib/format/timestamp.ts](../../web/lib/format/timestamp.ts) —
  unified `09 Sep 2026, 09:35 AM` display timestamps
- [web/components/documents/GoogleDrivePanel.tsx](../../web/components/documents/GoogleDrivePanel.tsx)
  / [GoogleDrivePicker.tsx](../../web/components/documents/GoogleDrivePicker.tsx)
  — reference connected card + browse dialog
- [web/components/documents/GitHubPanel.tsx](../../web/components/documents/GitHubPanel.tsx)
  / [GitHubPicker.tsx](../../web/components/documents/GitHubPicker.tsx)
  — second connector following the same recipe
- [ADR 0002](0002-nextjs-presentation-migration.md) — Next.js / HTTP ownership
  of `web/`
