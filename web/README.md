# Kernector web (Next.js)

App Router shell for the future presentation layer. Talks to Kernector only over HTTP (see [ADR 0002](../docs/adr/0002-nextjs-presentation-migration.md)). This ticket ships a foundation shell only — no API client, auth, or feature pages.

## Requirements

- Node.js **22+** (`web/.nvmrc`)
- npm (lockfile committed; use `npm ci`)

## Setup

```bash
cd web
npm ci
```

Copy `.env.example` to `.env.local` if you need to override public vars. Only `NEXT_PUBLIC_*` values are allowed for browser-exposed config; secrets must never appear here.

## Scripts

| Command                | Purpose                             |
| ---------------------- | ----------------------------------- |
| `npm run dev`          | Local App Router server (Turbopack) |
| `npm run build`        | Production build                    |
| `npm start`            | Serve the production build          |
| `npm run lint`         | ESLint                              |
| `npm run typecheck`    | TypeScript (`tsc --noEmit`)         |
| `npm test`             | Vitest unit/component tests         |
| `npm run format`       | Prettier write                      |
| `npm run format:check` | Prettier check                      |

## Routes

Placeholder destinations (no invented product behavior):

- `/` — Dashboard
- `/documents` — Documents
- `/chat` — Chat
- `/settings` — Settings

Global UI states: `loading.tsx`, `error.tsx`, `global-error.tsx` (root layout failures), `not-found.tsx`, plus reusable empty/unavailable components under `components/states/`.

## Visual direction

**Instrument panel** — a cool, professional AI knowledge workspace identity (not a wireframe, not a marketing landing page).

| Token role         | Choice                                                                                              |
| ------------------ | --------------------------------------------------------------------------------------------------- |
| Neutrals           | Cool slate surfaces (`--kern-bg` / `--kern-surface` / `--kern-surface-2`)                           |
| Accent             | Restrained teal (`--kern-accent`, `--kern-accent-soft`) for active nav, brand mark, and status cues |
| Focus              | Matching teal outline (`--kern-focus`) — never rely on color alone                                  |
| Type               | IBM Plex Sans + IBM Plex Mono with `--kern-text-xs`…`--kern-text-xl`                                |
| Radius / elevation | 6–8px radii; soft `--kern-shadow-1` / `--kern-shadow-2`                                             |
| Motion             | `--kern-duration` + `--kern-ease` CSS transitions only; disabled under `prefers-reduced-motion`     |

Semantic tokens live in `styles/tokens.css` and are consumed by `app/globals.css`. Light and dark themes are designed as paired surfaces (not a flat invert). Keep the shell domain-neutral; pack-specific branding stays gated.

## Responsive shell

The compact-shell breakpoint is **680px** (`max-width` in `app/globals.css`). Below that width the sidebar collapses behind the header menu button. The value is kept as a literal media-query threshold (CSS custom properties are not portable across `@media` queries here).
