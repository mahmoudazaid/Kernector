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

| Command | Purpose |
| --- | --- |
| `npm run dev` | Local App Router server (Turbopack) |
| `npm run build` | Production build |
| `npm start` | Serve the production build |
| `npm run lint` | ESLint |
| `npm run typecheck` | TypeScript (`tsc --noEmit`) |
| `npm test` | Vitest unit/component tests |
| `npm run format` | Prettier write |
| `npm run format:check` | Prettier check |

## Routes

Placeholder destinations (no invented product behavior):

- `/` — Dashboard
- `/documents` — Documents
- `/chat` — Chat
- `/settings` — Settings

Global UI states: `loading.tsx`, `error.tsx`, `not-found.tsx`, plus reusable empty/unavailable components under `components/states/`.
