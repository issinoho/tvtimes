# Contributing to tvtimes

Thanks for taking the time. tvtimes is a self-hosted TV-guide app — a Python
(FastAPI) backend, a React SPA, and a small standalone connector agent.

## Ground rules

- Be civil. See the [Code of Conduct](CODE_OF_CONDUCT.md).
- One focused change per pull request.
- Discuss anything large in an issue first — it saves everyone rework.
- By contributing you agree your work is licensed under the [MIT License](LICENSE).

## Development setup

```sh
# full stack (Postgres + Redis + hot-reload API + Vite HMR)
docker compose -f docker-compose.dev.yml up --build
#   API + docs  http://localhost:8000/docs
#   web app     http://localhost:5173

# backend only (SQLite, no worker)
cd backend && uv sync && uv run uvicorn app.main:app --reload
```

You need [Docker](https://docs.docker.com/) with Compose,
[uv](https://docs.astral.sh/uv/), and Node 22+.

## Before you open a PR — everything must pass

```sh
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -q
uv run alembic upgrade head          # if you added a migration

cd ../frontend
npm run lint && npm run typecheck && npm test && npm run build
npm run gen:api                      # if you changed an API schema; commit schema.d.ts
```

`npm run test:browser` runs the layout suite (`*.browser.test.tsx`) in a real
Chromium via Vitest browser mode — overlap, scroll position and contrast, none
of which jsdom can see. It needs `npx playwright install chromium` once. CI runs
it as its own step; `npm test` stays jsdom-only and needs no browser.


CI runs the same four jobs (backend / connector / frontend / image) and pins a
newer ruff/mypy than an old local install may resolve — if `ruff format --check`
passes locally but fails CI, run `uvx ruff@<ci-version> format .` (the version
is in the failed job log).

## Conventions

- **Python** 3.12, `from __future__ import annotations`, fully typed
  (`mypy` strict). Structured logging via `app.logging`, never bare `print`.
- **Frontend**: `@/` alias for `src/`; typed API client generated from the
  OpenAPI schema; component `<Routes>`, not the data router.
- Match the surrounding style; keep comment density and naming consistent.
- Tests live beside the suite they extend (`backend/tests/`,
  `frontend/src/**/*.test.tsx`). New behaviour needs a test.
- Repo-specific invariants (same-origin SPA, cookie scoping, guide timezone,
  in-place channel refresh, EPG fan-out, session listing) are documented in
  [`CLAUDE.md`](CLAUDE.md) — read it before touching auth, the guide, or ingest.

## Workflow

1. Branch from `main`.
2. Commit in logical steps; keep messages descriptive.
3. Open a PR; fill in the template. Squash-merge is the norm.
4. Migrations: hand-check anything `alembic revision --autogenerate` produced.

## Reporting bugs / requesting features

Use the [issue templates](https://github.com/issinoho/tvtimes/issues/new/choose).
For security issues, follow [SECURITY.md](SECURITY.md) instead of a public issue.
