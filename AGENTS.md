# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/osint_core/`. Keep HTTP routes in `src/osint_core/api/routes/`, domain logic in `src/osint_core/services/`, persistence models in `src/osint_core/models/`, connector adapters in `src/osint_core/connectors/`, and Celery tasks in `src/osint_core/workers/`. Tests mirror that layout under `tests/`, with extra suites in `tests/api/`, `tests/connectors/`, `tests/services/`, `tests/workers/`, and `tests/integration/`. Database migrations are in `migrations/`, plan YAMLs in `plans/`, deployment manifests in `deploy/`, and operational docs in `docs/`. Frontend code lives in `apps/web/` (React + Vite + TypeScript). Deployment manifests for the frontend are in `deploy/k8s/web/`.

## Build, Test, and Development Commands
Use Python 3.12. Install dependencies with `pip install -e ".[dev]"` or your existing `uv` workflow if you use `uv.lock`.

- `make format`: run `ruff check --fix` and `ruff format` on `src/` and `tests/`.
- `make lint`: run Ruff lint checks.
- `make typecheck`: run strict `mypy` on `src/osint_core/`.
- `make test`: run `pytest --cov=osint_core --cov-report=term-missing -v`.
- `make check`: run lint, type checks, and tests in the same sequence as CI.
- `make web-lint`: run ESLint on `apps/web/`.
- `make web-check`: run frontend lint and tests in the same sequence as CI.

Local linting, type checks, and `pytest` runs are fine. Do not run the full stack locally on this repository's primary development laptop; `make dev` and local Docker Compose are intentionally avoided because the system is too heavy. Any stack-dependent verification should target the deployed environment at `https://osint.corbello.io`, for example: `API_BASE_URL=https://osint.corbello.io ./scripts/verify_ingest.sh cisa_kev cyber-threat-intel`.

## Coding Style & Naming Conventions
Follow Ruff defaults with a 100-character line limit and Python 3.12 syntax. The codebase uses 4-space indentation, snake_case for modules/functions, PascalCase for classes, and explicit typing throughout. `mypy` runs in strict mode, so new code should avoid implicit `Any` and keep Pydantic/SQLAlchemy types precise.

## Testing Guidelines
Write tests with `pytest` and place them next to the area they cover, using `test_*.py` naming. Prefer focused unit tests first, then add integration coverage for queue, database, or end-to-end ingest behavior. Run local tests normally, but configure any environment-backed checks to point at `osint.corbello.io` instead of local Docker services. Keep coverage stable for touched code; `make test` is the minimum pre-PR check.

For frontend code in `apps/web`, follow a strict TDD-first workflow with Vitest:
- write or update a failing unit test before implementing behavior changes
- keep tests colocated with the unit under test (e.g., `*.test.tsx` next to components/features)
- use Testing Library for interaction/state assertions over implementation details
- run `npm run web:test` (or `make web-test`) before finalizing changes

## Commit & Pull Request Guidelines
Recent history follows conventional prefixes such as `fix:`, `feat:`, `docs:`, and `ci:`. Keep commit subjects imperative and specific, for example `fix: correct migration revision ID`. PRs should describe behavior changes, note schema or config impacts, link the relevant issue when applicable, and include sample requests/responses or screenshots only when UI or API output changed. Confirm `make check` passes before opening the PR.
