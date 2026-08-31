<!-- A short PR is a happy PR. Delete sections that don't apply. -->

## What & why

<!-- One or two sentences. Link the issue if there is one: Closes #123 -->

## How to test

<!-- Steps a reviewer can follow, or the automated tests that cover it. -->

## Checklist

- [ ] `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest -q`
- [ ] `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`
- [ ] Regenerated `frontend/src/lib/api/schema.d.ts` if an API schema changed
- [ ] Added / updated tests for the change
- [ ] Hand-checked any generated Alembic migration
- [ ] Updated docs (`README.md`, `docs/`, `CLAUDE.md`) if behaviour changed
