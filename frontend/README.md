# Utechia Internship — frontend

Next.js (App Router) + Mantine UI. Two surfaces: `/apply` (applicant form) and
`/manager` (operational dashboard). `/` redirects to `/apply`.

## Dev commands

```bash
npm install
npm run dev      # http://localhost:3000
npm run lint
npm run build    # production build, standalone output in .next/standalone
npm run start    # serve the production build
```

## Environment variables

The backend API base URL is resolved at **request time** in the root layout
(`src/app/layout.tsx`), not inlined at build time, so the same built image can
point at different backends in different environments (e.g. Docker/ECS).

- `API_BASE_URL` — preferred. Read on the server per-request.
- `NEXT_PUBLIC_API_BASE_URL` — optional build-time fallback, used only if
  `API_BASE_URL` is unset. Because `NEXT_PUBLIC_` variables are inlined at
  build time, prefer `API_BASE_URL` for anything that needs to change without
  a rebuild.
- If neither is set, falls back to `http://localhost:8000`.

Copy `.env.example` to `.env.local` for local development:

```bash
cp .env.example .env.local
```

## Structure

- `src/lib/types.ts` — TypeScript mirror of the backend's Pydantic response
  models (`src/backend/api/schemas.py`).
- `src/lib/api.ts` — typed fetch client (`ApiError`, `BackendUnavailableError`).
- `src/lib/api-context.tsx` — React context that carries the runtime API base
  URL to client components; `useApi()` returns a client bound to it.
- `src/app/apply/` — applicant-facing form.
- `src/app/manager/` — manager dashboard (AppShell with navbar: Applicants,
  Projects, Assignments).
