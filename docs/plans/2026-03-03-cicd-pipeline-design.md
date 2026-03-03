# CI/CD Pipeline Redesign

**Date:** 2026-03-03
**Status:** Approved
**Approach:** Incremental fix (Approach A) + Makefile

## Context

The osint-core project has a minimal CI pipeline (`ci.yaml`) that runs lint+test sequentially, then builds and pushes only the `api` Docker image to Harbor. There is no continuous deployment — after an image is pushed, a manual rollout kick is required.

**Infrastructure:**
- Self-hosted GitHub Actions runners
- Harbor registry at `harbor.corbello.io`
- Kubernetes cluster (homelab) with ArgoCD (`osint-platform` app, auto-sync enabled)
- GitOps manifests in `cortech-infra` repo at `apps/osint/overlays/production`
- Kustomize base/overlay structure; all three deployments (osint-core, osint-worker, osint-beat) share one image with command overrides

**Pain points:** slow builds, no automated deployment after build, incomplete pipeline stages.

## Pipeline Architecture

```
         ┌── lint (ruff + mypy) ──┐
PR/push: │                        ├──► build ──► scan ──► deploy
         └── test (pytest + cov) ─┘         (main only)
```

| Stage | Trigger | Runner | Purpose |
|-------|---------|--------|---------|
| `lint` | PR + push to main | self-hosted | ruff check + mypy — parallel with test |
| `test` | PR + push to main | self-hosted | pytest with coverage — parallel with lint |
| `build` | After lint+test, main only | self-hosted | Build + push Docker image to Harbor |
| `scan` | After build, main only | self-hosted | Trivy container vulnerability scan |
| `deploy` | After scan, main only | self-hosted | Update image tag in cortech-infra, ArgoCD auto-syncs |

On PRs, only `lint` and `test` run (fast feedback). On main, all stages run.

## CI Improvements

### Parallel lint + test

Split the current sequential `lint-test` job into two parallel jobs. Lint (ruff + mypy) takes ~10s and should not block pytest.

### Pip caching

Use `actions/cache` on `~/.cache/pip` for both lint and test jobs to avoid re-downloading dev dependencies on every run.

### Paths-ignore

Skip build/scan/deploy when only docs or non-code files change.

## Docker Build & Image Tagging

### Build target

Build the `api` target only (unchanged). All three K8s deployments use the same image with different command overrides, so one image is correct.

### Tagging strategy

Every build produces three tags:
- `harbor.corbello.io/osint/osint-core:<full-sha>` — immutable audit trail
- `harbor.corbello.io/osint/osint-core:<short-sha>` — human-readable
- `harbor.corbello.io/osint/osint-core:latest` — local dev convenience only

### Digest output

The build job outputs the image digest (`@sha256:...`) for use by downstream scan and deploy jobs. This avoids tag race/mutation issues and provides traceability.

## Security Scanning

### Tool: Trivy

- Scan by **digest** (not tag) from build output
- Severity gate: `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`
- Output: SARIF uploaded to GitHub Security tab via `github/codeql-action/upload-sarif`
- Cache Trivy DB on self-hosted runner between runs
- `.trivyignore` for accepted base-image CVEs with owner, date, and rationale comments

### .trivyignore format

```
# owner: <name> | date: YYYY-MM-DD | reason: <why>
# review: prune entries older than 90 days
CVE-XXXX-XXXXX
```

## CD / Deploy Job

### Mechanism

After build + scan pass on main:

1. Set up SSH with deploy key (`DEPLOY_KEY_INFRA` secret) and pin `github.com` in `known_hosts` via `ssh-keyscan`
2. Clone `cortech-infra` repo
3. Set explicit git identity (`github-actions[bot]`)
4. `cd apps/osint/overlays/production`
5. `kustomize edit set image harbor.corbello.io/osint/osint-core:<short-sha>`
6. Check `git diff --quiet` — if no diff, exit cleanly (no-op)
7. Assert diff only touches the expected `kustomization.yaml`
8. Commit with traceability message (see format below)
9. Push to `cortech-infra` main
10. ArgoCD auto-syncs (automated sync + selfHeal enabled)

### Concurrency guard

```yaml
concurrency:
  group: osint-infra-deploy
  cancel-in-progress: false
```

Prevents two CI runs from racing to push overlay commits.

### Commit message format

```
deploy(osint): update osint-core to <short-sha>

Source: jacorbello/osint-core@<full-sha>
Workflow: https://github.com/jacorbello/osint-core/actions/runs/<run-id>
ArgoCD: osint-platform (apps/osint/overlays/production)
Digest: sha256:<digest>
```

### Failure handling

If push fails (concurrent conflict), retry once with pull-rebase. If it fails again, the job fails and GitHub Actions sends a notification.

### Authentication

- **Deploy key** (SSH) stored as `DEPLOY_KEY_INFRA` secret — repo-scoped to `cortech-infra` only, least privilege
- `known_hosts` pinned for `github.com` via `ssh-keyscan` in workflow setup

## Makefile

Local task runner mirroring CI. Default target is `help`.

### Targets

| Target | Description |
|--------|-------------|
| `help` | Auto-list targets from `##` comments (default) |
| `format` | `ruff check --fix` + `ruff format` |
| `lint` | `ruff check src/ tests/` |
| `typecheck` | `mypy src/osint_core/` |
| `test` | `pytest --cov=osint_core --cov-report=term-missing -v` |
| `check` | lint + typecheck + test (read-only, mirrors CI) |
| `check-full` | check + scan |
| `build` | Docker build with SHA tag + `:local` |
| `push` | Push to Harbor |
| `scan` | Trivy with CI-matching flags (`--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`) |
| `dev` | `docker compose -f docker-compose.dev.yaml up --build` |
| `dev-down` | Stop dev stack |
| `dev-down-clean` | Stop dev stack + remove volumes |
| `logs` | `docker compose logs -f` |
| `precommit` | format + check |
| `clean` | Remove `__pycache__`, `.mypy_cache`, `.pytest_cache` |

## New Files

| File | Repo | Purpose |
|------|------|---------|
| `.github/workflows/ci.yaml` | osint-core | Rewritten pipeline (replaces current) |
| `Makefile` | osint-core | Local task runner |
| `.trivyignore` | osint-core | Accepted base-image CVEs |

## Secrets Required

| Secret | Repo | Purpose |
|--------|------|---------|
| `DEPLOY_KEY_INFRA` | osint-core | SSH deploy key with push access to cortech-infra |
| `HARBOR_USERNAME` | osint-core | Already exists |
| `HARBOR_PASSWORD` | osint-core | Already exists |

## Prerequisites

- [ ] Generate SSH deploy key pair and add public key to `cortech-infra` repo (Settings > Deploy keys, allow write access)
- [ ] Add private key as `DEPLOY_KEY_INFRA` secret in `osint-core` repo
- [ ] Verify branch protection on `cortech-infra/main` allows the deploy key push path

## Out of Scope (YAGNI)

- Reusable workflows (single repo)
- SAST / dependency audit / secret scanning
- Integration test stage
- `.pre-commit-config.yaml` (Makefile `precommit` covers this)
- Changes to Dockerfile or docker-compose
- Changes to base image workflow
