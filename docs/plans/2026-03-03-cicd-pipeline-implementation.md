# CI/CD Pipeline Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single-job CI pipeline with a parallel lint/test + build + scan + deploy pipeline, add a Makefile for local dev parity, and automate GitOps deployments to the K8s cluster via cortech-infra.

**Architecture:** GitHub Actions with 4 stages (lint/test, build, scan, deploy). Build pushes a SHA-tagged image to Harbor. Deploy job updates the Kustomize overlay in `cortech-infra` repo. ArgoCD auto-syncs. Makefile mirrors CI commands locally.

**Tech Stack:** GitHub Actions, Docker, Trivy, Kustomize, ArgoCD, Make

**Design doc:** `docs/plans/2026-03-03-cicd-pipeline-design.md`

---

### Task 1: Create Makefile

> **Note:** The Makefile below reflects the initial plan. During implementation, code review
> refined two things: (1) `check` no longer includes `format` (it's read-only: lint + typecheck + test),
> and (2) `scan` includes `--ignorefile .trivyignore` for CI parity. See the actual `Makefile` for
> the current version.

**Files:**
- Create: `Makefile`

**Step 1: Write the Makefile**

```makefile
.DEFAULT_GOAL := help

IMAGE := harbor.corbello.io/osint/osint-core
SHA   := $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")

.PHONY: help format lint typecheck test check check-full build push scan dev dev-down dev-down-clean logs precommit clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

format: ## Auto-fix lint issues and format code
	ruff check --fix src/ tests/
	ruff format src/ tests/

lint: ## Run ruff linter
	ruff check src/ tests/

typecheck: ## Run mypy strict type checking
	mypy src/osint_core/

test: ## Run pytest with coverage
	pytest --cov=osint_core --cov-report=term-missing -v

check: format lint typecheck test ## Run all checks (fast, mirrors CI)

check-full: check scan ## Run all checks including container scan

build: ## Build Docker image tagged with git SHA
	docker build --target api -t $(IMAGE):$(SHA) -t $(IMAGE):local .

push: ## Push SHA-tagged image to Harbor
	docker push $(IMAGE):$(SHA)

scan: ## Trivy scan (mirrors CI flags)
	trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 $(IMAGE):local

dev: ## Start local dev stack
	docker compose -f docker-compose.dev.yaml up --build

dev-down: ## Stop local dev stack
	docker compose -f docker-compose.dev.yaml down

dev-down-clean: ## Stop local dev stack and remove volumes
	docker compose -f docker-compose.dev.yaml down -v

logs: ## Tail local dev stack logs
	docker compose -f docker-compose.dev.yaml logs -f

precommit: format check ## Format and run all checks

clean: ## Remove Python cache artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
```

**Step 2: Verify Makefile works**

Run: `make help`
Expected: formatted table of all targets with descriptions.

Run: `make lint`
Expected: ruff passes (exit 0).

Run: `make typecheck`
Expected: mypy passes (exit 0).

Run: `make test`
Expected: pytest passes with coverage output.

**Step 3: Commit**

```bash
git add Makefile
git commit -m "build: add Makefile for local dev parity with CI"
```

---

### Task 2: Create .trivyignore

**Files:**
- Create: `.trivyignore`

**Step 1: Write the .trivyignore file**

```
# Trivy ignore list for osint-core container image.
# Base image (python-base:ml) includes PyTorch/numpy which trigger known CVEs.
#
# Format: one CVE per line
#   owner: <name> | date: YYYY-MM-DD | reason: <why>
#
# Maintenance: prune entries older than 90 days.
# No entries yet — add as needed after first scan.
```

**Step 2: Commit**

```bash
git add .trivyignore
git commit -m "ci: add .trivyignore for base-image CVE exceptions"
```

---

### Task 3: Rewrite ci.yaml — lint and test jobs

**Files:**
- Modify: `.github/workflows/ci.yaml` (full replacement)

**Step 1: Replace ci.yaml with lint + test jobs (build/scan/deploy added in subsequent tasks)**

Write the complete new `ci.yaml`. This step adds the `lint` and `test` jobs only. The `build`, `scan`, and `deploy` jobs will be added in Tasks 4-6 but we write the full file in one shot here for efficiency.

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
    paths-ignore:
      - "*.md"
      - "docs/**"
      - "LICENSE"

env:
  IMAGE: harbor.corbello.io/osint/osint-core

jobs:
  # ── Stage 1: Lint (parallel with test) ──────────────────────────
  lint:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: pip-lint-${{ hashFiles('pyproject.toml') }}
          restore-keys: pip-lint-

      - name: Install dev dependencies
        run: pip install -e ".[dev]"

      - name: Lint (ruff)
        run: ruff check src/ tests/

      - name: Type check (mypy)
        run: mypy src/osint_core/

  # ── Stage 1: Test (parallel with lint) ──────────────────────────
  test:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: pip-test-${{ hashFiles('pyproject.toml') }}
          restore-keys: pip-test-

      - name: Install dev dependencies
        run: pip install -e ".[dev]"

      - name: Test
        run: pytest --cov=osint_core --cov-report=term-missing -v

  # ── Stage 2: Build + push Docker image (main only) ─────────────
  build:
    runs-on: self-hosted
    needs: [lint, test]
    if: github.ref == 'refs/heads/main'
    outputs:
      digest: ${{ steps.push.outputs.digest }}
      short_sha: ${{ steps.vars.outputs.short_sha }}
    steps:
      - uses: actions/checkout@v4

      - name: Set variables
        id: vars
        run: echo "short_sha=${GITHUB_SHA::7}" >> "$GITHUB_OUTPUT"

      - name: Log in to Harbor
        run: echo "${{ secrets.HARBOR_PASSWORD }}" | docker login harbor.corbello.io -u "${{ secrets.HARBOR_USERNAME }}" --password-stdin

      - name: Build image
        run: |
          docker build --target api \
            -t ${{ env.IMAGE }}:${{ github.sha }} \
            -t ${{ env.IMAGE }}:${{ steps.vars.outputs.short_sha }} \
            -t ${{ env.IMAGE }}:latest \
            .

      - name: Push image and capture digest
        id: push
        run: |
          docker push ${{ env.IMAGE }}:${{ github.sha }}
          docker push ${{ env.IMAGE }}:${{ steps.vars.outputs.short_sha }}
          docker push ${{ env.IMAGE }}:latest
          DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' ${{ env.IMAGE }}:${{ github.sha }} | cut -d@ -f2)
          echo "digest=${DIGEST}" >> "$GITHUB_OUTPUT"
          echo "::notice::Image digest: ${DIGEST}"

  # ── Stage 3: Security scan (main only) ─────────────────────────
  scan:
    runs-on: self-hosted
    needs: build
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: "${{ env.IMAGE }}@${{ needs.build.outputs.digest }}"
          format: "sarif"
          output: "trivy-results.sarif"
          severity: "HIGH,CRITICAL"
          ignore-unfixed: true
          exit-code: "1"
          trivyignores: ".trivyignore"
        env:
          TRIVY_DB_REPOSITORY: "ghcr.io/aquasecurity/trivy-db"

      - name: Upload Trivy scan to GitHub Security tab
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: "trivy-results.sarif"

  # ── Stage 4: Deploy to K8s via GitOps (main only) ──────────────
  deploy:
    runs-on: self-hosted
    needs: [build, scan]
    if: github.ref == 'refs/heads/main'
    concurrency:
      group: osint-infra-deploy
      cancel-in-progress: false
    steps:
      - name: Set up SSH for cortech-infra
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.DEPLOY_KEY_INFRA }}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null
          cat >> ~/.ssh/config <<EOF
          Host github.com
            IdentityFile ~/.ssh/deploy_key
            StrictHostKeyChecking yes
          EOF

      - name: Install kustomize
        uses: imranismail/setup-kustomize@v2

      - name: Clone cortech-infra and update image tag
        env:
          SHORT_SHA: ${{ needs.build.outputs.short_sha }}
          FULL_SHA: ${{ github.sha }}
          DIGEST: ${{ needs.build.outputs.digest }}
          RUN_ID: ${{ github.run_id }}
        run: |
          git clone git@github.com:jacorbello/cortech-infra.git /tmp/cortech-infra
          cd /tmp/cortech-infra/apps/osint/overlays/production

          kustomize edit set image ${{ env.IMAGE }}:${SHORT_SHA}

          # No-op if image tag is already current
          if git diff --quiet; then
            echo "::notice::Image tag already up to date — no deploy needed."
            exit 0
          fi

          # Assert only the expected file changed
          CHANGED=$(git diff --name-only)
          if [ "$CHANGED" != "apps/osint/overlays/production/kustomization.yaml" ]; then
            echo "::error::Unexpected files changed: ${CHANGED}"
            exit 1
          fi

          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          git add apps/osint/overlays/production/kustomization.yaml
          git commit -m "deploy(osint): update osint-core to ${SHORT_SHA}

          Source: jacorbello/osint-core@${FULL_SHA}
          Workflow: https://github.com/jacorbello/osint-core/actions/runs/${RUN_ID}
          ArgoCD: osint-platform (apps/osint/overlays/production)
          Digest: ${DIGEST}"

          # Push with one retry on conflict
          if ! git push origin main; then
            echo "::warning::Push conflict — retrying with pull-rebase"
            git pull --rebase origin main
            git push origin main
          fi

      - name: Cleanup SSH key
        if: always()
        run: rm -f ~/.ssh/deploy_key
```

**Step 2: Validate YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yaml'))"`
Expected: no error (exit 0). If `pyyaml` is already installed (it's in project deps).

**Step 3: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "ci: rewrite pipeline with parallel lint/test, scan, and GitOps deploy"
```

---

### Task 4: Validate locally

**Step 1: Run make check to verify local parity**

Run: `make check`
Expected: format, lint, typecheck, and test all pass.

**Step 2: Run make help to verify all targets listed**

Run: `make help`
Expected: all 15 targets listed with descriptions.

**Step 3: Validate workflow YAML parses correctly**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yaml')); print('YAML OK')"`
Expected: `YAML OK`

---

### Task 5: Final commit and summary

**Step 1: Verify git status is clean**

Run: `git status`
Expected: nothing to commit, working tree clean (all changes committed in prior tasks).

**Step 2: Review commit log**

Run: `git log --oneline -5`
Expected: 3 new commits on top of the design doc commit:
1. `build: add Makefile for local dev parity with CI`
2. `ci: add .trivyignore for base-image CVE exceptions`
3. `ci: rewrite pipeline with parallel lint/test, scan, and GitOps deploy`

---

## Prerequisites (manual, before first pipeline run)

These must be done by the user outside of this plan:

1. Generate SSH deploy key pair: `ssh-keygen -t ed25519 -f osint-deploy-key -N ""`
2. Add the **public key** to `cortech-infra` repo → Settings → Deploy keys (enable write access)
3. Add the **private key** as `DEPLOY_KEY_INFRA` secret in `osint-core` repo → Settings → Secrets
4. Verify branch protection on `cortech-infra/main` allows the deploy key push path

---

## Files Changed Summary

| File | Action | Description |
|------|--------|-------------|
| `Makefile` | Create | Local task runner with 15 targets |
| `.trivyignore` | Create | CVE exception list (empty initially) |
| `.github/workflows/ci.yaml` | Replace | Full pipeline: lint, test, build, scan, deploy |
