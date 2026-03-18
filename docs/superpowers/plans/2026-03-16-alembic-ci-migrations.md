# Alembic CI Migrations Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an automated `alembic upgrade head` step to the CI/CD pipeline so migrations run before every deploy, blocking the deploy on failure.

**Architecture:** A new `migrate` job in `ci.yaml` runs between `scan` and `deploy`. It installs the app on the self-hosted runner (which has network access to PostgreSQL), runs `alembic upgrade head`, and verifies with `alembic current`. A `workflow_dispatch` input allows manual migration runs. Rollback procedures are documented in `docs/runbook.md`.

**Tech Stack:** GitHub Actions, Alembic, Python 3.12, PostgreSQL (asyncpg)

**Spec:** `docs/superpowers/specs/2026-03-16-alembic-ci-migrations-design.md`

---

## Chunk 1: CI Workflow and Runbook

### File Map

- **Modify:** `.github/workflows/ci.yaml` — add `workflow_dispatch` trigger, `migrate` job, update `deploy` conditions
- **Create:** `docs/runbook.md` — migration rollback documentation

---

### Task 1: Add `workflow_dispatch` trigger to `ci.yaml`

**Files:**
- Modify: `.github/workflows/ci.yaml:3-11`

- [ ] **Step 1: Add `workflow_dispatch` trigger with `run_migrations` input**

In `.github/workflows/ci.yaml`, replace the `on:` block (lines 3–11) with:

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
    paths-ignore:
      - "**/*.md"
      - "docs/**"
      - "LICENSE"
  workflow_dispatch:
    inputs:
      run_migrations:
        description: "Run only the migrate job (skip build/scan/deploy)"
        type: boolean
        default: false
```

- [ ] **Step 2: Guard `build` job with `!inputs.run_migrations`**

In `.github/workflows/ci.yaml`, update the `build` job's `if:` (line 71) from:

```yaml
    if: github.ref == 'refs/heads/main'
```

to:

```yaml
    if: github.ref == 'refs/heads/main' && !inputs.run_migrations
```

- [ ] **Step 3: Guard `scan` job with `!inputs.run_migrations`**

In `.github/workflows/ci.yaml`, update the `scan` job's `if:` (line 153) from:

```yaml
    if: github.ref == 'refs/heads/main' && needs.build.result == 'success'
```

to:

```yaml
    if: github.ref == 'refs/heads/main' && needs.build.result == 'success' && !inputs.run_migrations
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "ci: add workflow_dispatch trigger with run_migrations input"
```

---

### Task 2: Add `migrate` job to `ci.yaml`

**Files:**
- Modify: `.github/workflows/ci.yaml` (insert new job between `scan` and `deploy`)

- [ ] **Step 1: Add the `migrate` job**

Insert the following job after the `scan` job block and before the `deploy` job comment. (Line numbers below reference the *original* file — after Task 1 adds the `workflow_dispatch` block, all line numbers shift by ~5 lines. Use the job names/comments as landmarks instead.)

```yaml
  # ── Stage 3.5: Run database migrations (main only) ──────────────
  migrate:
    runs-on: [self-hosted, linux, osint-deploy]
    needs: [build, scan]
    if: >-
      always()
      && github.ref == 'refs/heads/main'
      && (needs.scan.result == 'success' || inputs.run_migrations)
    timeout-minutes: 5
    concurrency:
      group: osint-infra-deploy
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: pip-migrate-${{ hashFiles('pyproject.toml') }}
          restore-keys: pip-migrate-

      - name: Install app (no dev deps)
        run: pip install -e "."

      - name: Run Alembic migrations
        env:
          OSINT_DATABASE_URL: ${{ secrets.OSINT_DATABASE_URL }}
        run: python -m alembic upgrade head --verbose

      - name: Verify migration state
        env:
          OSINT_DATABASE_URL: ${{ secrets.OSINT_DATABASE_URL }}
        run: python -m alembic current
```

**Key details:**
- The `if:` condition starts with `always()` — this is required because when `run_migrations: true`, the `build` and `scan` jobs are skipped, and GitHub Actions will skip any job whose `needs` are all skipped before evaluating the `if:` condition. `always()` forces condition evaluation. The `||` then allows the job to run either on a normal deploy (after scan succeeds) or on a manual `workflow_dispatch` (where scan is skipped).
- `timeout-minutes: 5` prevents hung migrations from blocking the pipeline.
- `concurrency` group matches `deploy` to prevent concurrent migration + deploy races.
- Uses `python -m alembic` (not bare `alembic`) to ensure it picks up the installed package.
- `pip install -e "."` — intentionally no `[dev]` extras. Only alembic + app models are needed.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "ci: add migrate job to run alembic upgrade head before deploy"
```

---

### Task 3: Update `deploy` job to depend on `migrate`

**Files:**
- Modify: `.github/workflows/ci.yaml:200-203`

- [ ] **Step 1: Update `deploy` job's `needs` and `if`**

Update the `deploy` job (currently at line ~200 area, after the new migrate job) from:

```yaml
  deploy:
    runs-on: [self-hosted, linux, osint-deploy]
    needs: [build, scan]
    if: github.ref == 'refs/heads/main' && needs.scan.result == 'success'
```

to:

```yaml
  deploy:
    runs-on: [self-hosted, linux, osint-deploy]
    needs: [build, scan, migrate]
    if: >-
      github.ref == 'refs/heads/main'
      && needs.scan.result == 'success'
      && needs.migrate.result == 'success'
      && !inputs.run_migrations
```

**Key details:**
- `needs` now includes `migrate` — deploy waits for migrations.
- `needs.migrate.result == 'success'` — deploy is blocked if migration fails.
- `!inputs.run_migrations` — deploy is skipped on manual migration-only runs.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "ci: gate deploy on successful migrate job"
```

---

### Task 4: Validate the complete workflow YAML

- [ ] **Step 1: Lint the workflow file**

```bash
# Validate YAML syntax (python is available on the runner)
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yaml'))"
```

Expected: no output (valid YAML).

- [ ] **Step 2: Verify job dependency chain**

Manually review the final `ci.yaml` and confirm the pipeline DAG is:

```
lint ─┐
      ├─► build ─► scan ─► migrate ─► deploy
test ─┘
```

Check:
- `build.needs: [lint, test]`
- `scan.needs: build`
- `migrate.needs: [build, scan]`
- `deploy.needs: [build, scan, migrate]`

- [ ] **Step 3: Verify `workflow_dispatch` guards**

Confirm the following jobs have `&& !inputs.run_migrations` in their `if:`:
- `build`
- `scan`
- `deploy`

And that `migrate` has `|| inputs.run_migrations` so it runs on manual dispatch.

---

### Task 5: Create `docs/runbook.md`

**Files:**
- Create: `docs/runbook.md`

- [ ] **Step 1: Write the runbook**

Create `docs/runbook.md` with the following content:

```markdown
# Operations Runbook

## Database Migrations

### How migrations run

Alembic migrations run automatically on every push to `main` as part of the CI/CD pipeline.
The `migrate` job runs `alembic upgrade head` on the self-hosted runner before the deploy
job proceeds. If the migration fails, the deploy is blocked.

### Manual migration run

Trigger via GitHub Actions:

1. Go to **Actions** > **CI** workflow
2. Click **Run workflow**
3. Set **Run only the migrate job** to `true`
4. Click **Run workflow**

This runs only the `migrate` job (build/scan/deploy are skipped).

### Rolling back a migration

**On the self-hosted runner:**

```bash
# SSH into the runner, navigate to a checkout of osint-core
export OSINT_DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/osint"
pip install -e "."
python -m alembic downgrade -1
```

**Important:** This only works if the migration file has a working `downgrade()` function.
Always verify downgrade functions exist before relying on this.

### When to roll back

- Migration was applied but the subsequent deploy failed, and the new code depends on the
  old schema.
- Migration introduced a breaking schema change that needs reverting before a code fix is
  ready.

### Future enhancements

- **Pre-migration database backup:** Not yet implemented. Will be added once the backup
  strategy is decided.
- **`workflow_dispatch` downgrade:** A future `migration_command` input will allow running
  `alembic downgrade -1` via the Actions UI without SSH access.
```

- [ ] **Step 2: Commit**

```bash
git add docs/runbook.md
git commit -m "docs: add operations runbook with migration rollback procedures"
```

---

### Task 6: Prerequisites checklist (manual, pre-merge)

These are not code steps — they are manual actions the operator must complete before merging this PR:

- [ ] **Add `OSINT_DATABASE_URL` secret** to the GitHub repo: Settings > Secrets and variables > Actions > New repository secret. Value: the PostgreSQL connection string reachable from the runner (e.g., `postgresql+asyncpg://osint:password@db-host:5432/osint`).
- [ ] **Verify runner connectivity:** Confirm the self-hosted runner can reach the database host on port 5432. A quick test: `python -c "import asyncio, asyncpg; asyncio.run(asyncpg.connect('postgresql://...'))"` from the runner.
