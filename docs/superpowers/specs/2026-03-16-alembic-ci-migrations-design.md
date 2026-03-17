# Automated Alembic Migrations in CI/CD Pipeline

**Issue:** [#40 — Add automated Alembic migrations to CI/CD pipeline](https://github.com/jacorbello/osint-core/issues/40)
**Date:** 2026-03-16

## Problem

The current deploy pipeline is pure GitOps with no `alembic upgrade` step. ORM model changes that lack a corresponding migration silently drift the schema, requiring manual `ALTER TABLE` fixes (see PR #37 incident).

## Decision: Direct Runner Migration

Run `alembic upgrade head` directly on the self-hosted runner, which already has Python 3.12, installs the package during CI, and has network access to the PostgreSQL database. This avoids k8s Job manifests and Docker networking complexity for a marginal environment-purity win.

## Design

### New GitHub Actions Secret

- **`OSINT_DATABASE_URL`**: PostgreSQL connection string (e.g., `postgresql+asyncpg://user:pass@host:5432/osint`). Must be added to the repo's Actions secrets before this workflow change is deployed.

**Why this name:** The app's `Settings` class uses `env_prefix = "OSINT_"` (`src/osint_core/config.py`), so the `database_url` field reads from `OSINT_DATABASE_URL`. Alembic's `env.py` gets the URL via `settings.database_url`. Using a different env var name would silently fall back to the hardcoded default (the in-cluster `postgres:5432` hostname), which would either fail to resolve or connect to the wrong database.

### New `migrate` Job in `ci.yaml`

Inserted between `scan` and `deploy` in the pipeline:

```
lint ─┐
      ├─► build ─► scan ─► migrate ─► deploy
test ─┘
```

**Configuration:**
- **Runs on:** `[self-hosted, linux, osint-deploy]`
- **Needs:** `[build, scan]`
- **Condition:** `github.ref == 'refs/heads/main' && needs.scan.result == 'success'`
- **No path filtering** — runs unconditionally on every deploy. This is intentional: if someone changes an ORM model without adding a migration, `alembic upgrade head` is a no-op when the schema is current, but the deploy proceeds. The real protection is that the schema stays in sync — if a migration is missing, the mismatch surfaces at the application level rather than silently drifting.
- **Note:** The existing `push` trigger has `paths-ignore` for `docs/**` and `**/*.md`, so doc-only pushes skip the entire workflow (including `migrate`). This is acceptable since doc-only changes never include schema modifications.
- **Timeout:** `timeout-minutes: 5` on the job to prevent hung migrations (e.g., waiting on a database lock) from blocking the pipeline indefinitely.
- **Concurrency:** Uses the same `concurrency` group as `deploy` (`osint-infra-deploy`) to prevent concurrent migration runs against the same database. While Alembic acquires an advisory lock on `alembic_version`, running two migrations simultaneously would produce confusing logs and potential lock-timeout failures.

**Steps:**
1. `actions/checkout@v4`
2. `actions/setup-python@v5` (Python 3.12, with pip cache)
3. `pip install -e "."` (installs alembic + app models)
4. `alembic upgrade head` with `OSINT_DATABASE_URL` from secrets
5. `alembic current` — post-migration verification step (prints current revision for audit logs)

### Updated `deploy` Job

- **Needs:** changed from `[build, scan]` to `[build, scan, migrate]`
- **Condition:** updated to include `needs.migrate.result == 'success'`
- Deploy is blocked if migration fails.

### `workflow_dispatch` Input

The existing `on:` block gains a `workflow_dispatch` trigger with a `run_migrations` boolean input (default: `false`). When triggered manually with `run_migrations: true`:
- Only the `migrate` job runs. The `build`, `scan`, and `deploy` jobs add `&& !inputs.run_migrations` to their existing `if:` conditions so they are skipped.
- Enables manual migration runs independent of a code push (e.g., applying a migration that was merged but failed to run, or running migrations against a restored database).

**Note on `pip install`:** The migrate job uses `pip install -e "."` (not `".[dev]"`). Dev dependencies (ruff, mypy, pytest) are not needed for running migrations. This is intentional — do not "correct" it to match lint/test jobs.

### Rollback Documentation (`docs/runbook.md`)

A new runbook file covering:
1. **Normal rollback:** `alembic downgrade -1` on the runner.
2. **Emergency rollback via `workflow_dispatch`:** Future enhancement — add a `migration_command` string input so operators can dispatch `downgrade -1` without SSH access.
3. **When to rollback:** Migration applied but deploy failed, or migration introduced a breaking schema change.
4. **Caveat:** Downgrade requires working `downgrade()` functions in every migration file.

### What This Does NOT Include (Deferred)

- **Pre-migration database backup:** Will be added in a follow-up once the backup strategy is decided (k8s CronJob, managed service snapshot, or `pg_dump` on the runner).
- **Automatic downgrade via `workflow_dispatch`:** The dispatch currently only runs `upgrade head`. A `migration_command` input is a future enhancement.

## Acceptance Criteria Mapping

| Criteria | How It's Met |
|----------|-------------|
| Migrations run automatically on every deploy | `migrate` job runs unconditionally after scan |
| Deploy blocked if migrations fail | `deploy.needs` includes `migrate` |
| Pre-migration database backup | Deferred (documented as future work) |
| `workflow_dispatch` for manual migration runs | `run_migrations` boolean input |
| Rollback strategy documented | `docs/runbook.md` |
| No more manual `ALTER TABLE` | Alembic manages all schema changes |

## Files Changed

1. **`.github/workflows/ci.yaml`** — Add `migrate` job, `workflow_dispatch` input, update `deploy` dependencies
2. **`docs/runbook.md`** — New file with rollback documentation
