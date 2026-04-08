# Frontend CI/CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the `apps/web` React/Vite frontend into CI/CD so it builds a Docker image, pushes to Harbor, and deploys to the Kubernetes cluster via GitOps — matching the existing backend pipeline pattern.

**Architecture:** Extend the existing `ci.yaml` workflow with path-filtered frontend jobs (lint-web, test-web, build-web) that run in parallel with backend jobs. The frontend builds into an Nginx alpine container serving static files. Deploy step updates the `cortech-infra` Kustomize overlay with both backend and frontend image tags.

**Tech Stack:** Docker (multi-stage: node:22-alpine build, nginx:1.27-alpine runtime), GitHub Actions, Kustomize, Harbor registry, ArgoCD

**Spec:** `docs/superpowers/specs/2026-04-07-frontend-cicd-design.md`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `apps/web/Dockerfile` | Multi-stage build: Node build → Nginx runtime |
| Create | `apps/web/nginx.conf` | SPA routing, gzip, cache headers, health check |
| Create | `apps/web/.dockerignore` | Keep build context small |
| Modify | `.github/workflows/ci.yaml` | Add path filters, lint-web, test-web, build-web jobs; extend scan + deploy |
| Create | `deploy/k8s/web/deployment.yaml` | Kubernetes Deployment for osint-web |
| Create | `deploy/k8s/web/service.yaml` | ClusterIP Service for osint-web |
| Modify | `Makefile` | Add web-lint, web-build-image, web-check targets |
| Modify | `AGENTS.md` | Document frontend CI and new make targets |

---

### Task 1: Nginx Configuration

**Files:**
- Create: `apps/web/nginx.conf`

- [ ] **Step 1: Create nginx.conf**

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA: all routes fall back to index.html
    location / {
        try_files $uri $uri/ /index.html;
        # index.html must never be cached so deploys take effect immediately
        add_header Cache-Control "no-cache";
    }

    # Vite hashed assets — cache forever
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    # Health check for Kubernetes probes
    location = /healthz {
        access_log off;
        return 200 "ok";
        add_header Content-Type text/plain;
    }

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;
    gzip_min_length 256;
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/nginx.conf
git commit -m "ci: add nginx config for frontend container"
```

---

### Task 2: Dockerfile and .dockerignore

**Files:**
- Create: `apps/web/Dockerfile`
- Create: `apps/web/.dockerignore`

- [ ] **Step 1: Create .dockerignore**

```
node_modules/
dist/
.env*
*.md
.vite/
coverage/
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
# ── Stage 1: Build ───────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

- [ ] **Step 3: Verify the image builds locally**

Run:
```bash
cd apps/web && docker build -t osint-web:local .
```

Expected: Build completes successfully. The `npm run build` step runs `tsc -b && vite build` and produces the `dist/` directory.

- [ ] **Step 4: Verify the container serves the app**

Run:
```bash
docker run --rm -d -p 8080:80 --name osint-web-test osint-web:local
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/healthz
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
docker stop osint-web-test
```

Expected: Both curl commands return `200`.

- [ ] **Step 5: Commit**

```bash
git add apps/web/Dockerfile apps/web/.dockerignore
git commit -m "ci: add Dockerfile and dockerignore for frontend"
```

---

### Task 3: Kubernetes Manifests

**Files:**
- Create: `deploy/k8s/web/deployment.yaml`
- Create: `deploy/k8s/web/service.yaml`

- [ ] **Step 1: Create deployment.yaml**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: osint-web
  namespace: osint
  labels:
    app: osint-web
    component: frontend
spec:
  replicas: 1
  selector:
    matchLabels:
      app: osint-web
  template:
    metadata:
      labels:
        app: osint-web
        component: frontend
    spec:
      containers:
        - name: web
          image: harbor.corbello.io/osint/osint-web:latest  # overridden by kustomize
          ports:
            - containerPort: 80
          livenessProbe:
            httpGet:
              path: /healthz
              port: 80
            periodSeconds: 15
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /healthz
              port: 80
            periodSeconds: 5
            failureThreshold: 2
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
```

- [ ] **Step 2: Create service.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: osint-web
  namespace: osint
  labels:
    app: osint-web
    component: frontend
spec:
  type: ClusterIP
  selector:
    app: osint-web
  ports:
    - port: 80
      targetPort: 80
      protocol: TCP
```

- [ ] **Step 3: Validate manifests**

Run:
```bash
kubectl apply --dry-run=client -f deploy/k8s/web/deployment.yaml
kubectl apply --dry-run=client -f deploy/k8s/web/service.yaml
```

Expected: Both output `deployment.apps/osint-web configured (dry run)` and `service/osint-web configured (dry run)` respectively (or `created` — either is fine).

- [ ] **Step 4: Commit**

```bash
git add deploy/k8s/web/
git commit -m "ci: add Kubernetes manifests for frontend deployment"
```

---

### Task 4: CI Workflow — Path Filter and Frontend Jobs

This is the largest task. We modify `.github/workflows/ci.yaml` to add a path-detection job and three frontend jobs.

**Files:**
- Modify: `.github/workflows/ci.yaml`

- [ ] **Step 1: Add `IMAGE_WEB` and `IMAGE_WEB_CACHE` env vars**

Add to the top-level `env:` block (after the existing `IMAGE_CACHE` line):

```yaml
env:
  IMAGE: harbor.corbello.io/osint/osint-core
  IMAGE_WORKER: harbor.corbello.io/osint/osint-core-worker
  IMAGE_BEAT: harbor.corbello.io/osint/osint-core-beat
  IMAGE_CACHE: harbor.corbello.io/osint/osint-core-cache
  IMAGE_WEB: harbor.corbello.io/osint/osint-web
  IMAGE_WEB_CACHE: harbor.corbello.io/osint/osint-web-cache
```

- [ ] **Step 2: Add `changes` job for path detection**

Insert a new job before the existing `lint` job. This job detects which parts of the repo changed and exposes outputs that other jobs use in their `if:` conditions.

```yaml
  # ── Stage 0: Detect changed paths ─────────────────────────────
  changes:
    if: ${{ !inputs.run_migrations }}
    runs-on: osint-core-runner
    outputs:
      backend: ${{ steps.filter.outputs.backend }}
      frontend: ${{ steps.filter.outputs.frontend }}
    steps:
      - uses: actions/checkout@v4

      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            backend:
              - 'src/**'
              - 'tests/**'
              - 'migrations/**'
              - 'Dockerfile'
              - 'pyproject.toml'
              - 'alembic.ini'
              - '.github/workflows/ci.yaml'
              - 'Makefile'
            frontend:
              - 'apps/web/**'
              - '.github/workflows/ci.yaml'
              - 'Makefile'
```

- [ ] **Step 3: Add path filter conditions to existing backend jobs**

Update the `lint` job `if:` to:

```yaml
  lint:
    needs: changes
    if: ${{ !inputs.run_migrations && needs.changes.outputs.backend == 'true' }}
    runs-on: osint-core-runner
```

Update the `test` job `if:` to:

```yaml
  test:
    needs: changes
    if: ${{ !inputs.run_migrations && needs.changes.outputs.backend == 'true' }}
    runs-on: osint-core-runner
```

Update the `build` job `needs:` and `if:` to:

```yaml
  build:
    runs-on: osint-core-runner
    needs: [changes, lint, test]
    if: >-
      github.ref == 'refs/heads/main'
      && !inputs.run_migrations
      && needs.changes.outputs.backend == 'true'
```

Update the `scan` job `if:` to check `needs.build.result`:

```yaml
  scan:
    runs-on: osint-core-runner
    needs: [build]
    continue-on-error: true
    strategy:
      fail-fast: false
      matrix:
        target: [api, worker, beat]
    if: >-
      github.ref == 'refs/heads/main'
      && needs.build.result == 'success'
      && !inputs.run_migrations
```

(The `scan` job is unchanged from existing, just confirming it stays the same.)

Update the `migrate` job `needs:` to include `changes`:

```yaml
  migrate:
    runs-on: osint-core-runner
    needs: [changes, build, scan]
    if: >-
      always()
      && github.ref == 'refs/heads/main'
      && needs.build.result == 'success'
```

(Migrate only runs when backend build succeeded, which already implies backend changes. No further change needed.)

- [ ] **Step 4: Add lint-web job**

Insert after the `test` job:

```yaml
  # ── Stage 1: Lint frontend (parallel with backend) ────────────
  lint-web:
    needs: changes
    if: ${{ !inputs.run_migrations && needs.changes.outputs.frontend == 'true' }}
    runs-on: osint-core-runner
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: apps/web/package-lock.json

      - name: Install dependencies
        run: npm ci
        working-directory: apps/web

      - name: Lint (eslint)
        run: npm run lint
        working-directory: apps/web
```

- [ ] **Step 5: Add test-web job**

Insert after `lint-web`:

```yaml
  # ── Stage 1: Test frontend (parallel with backend) ────────────
  test-web:
    needs: changes
    if: ${{ !inputs.run_migrations && needs.changes.outputs.frontend == 'true' }}
    runs-on: osint-core-runner
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: apps/web/package-lock.json

      - name: Install dependencies
        run: npm ci
        working-directory: apps/web

      - name: Test (vitest)
        run: npm run test
        working-directory: apps/web
```

- [ ] **Step 6: Add build-web job**

Insert after `test-web`:

```yaml
  # ── Stage 2: Build + push frontend Docker image (main only) ───
  build-web:
    runs-on: osint-core-runner
    needs: [changes, lint-web, test-web]
    if: >-
      github.ref == 'refs/heads/main'
      && !inputs.run_migrations
      && needs.changes.outputs.frontend == 'true'
    outputs:
      digest: ${{ steps.build.outputs.digest }}
      short_sha: ${{ steps.vars.outputs.short_sha }}
    steps:
      - uses: actions/checkout@v4

      - name: Set variables
        id: vars
        run: echo "short_sha=${GITHUB_SHA::7}" >> "$GITHUB_OUTPUT"

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Harbor
        uses: docker/login-action@v3
        with:
          registry: harbor.corbello.io
          username: ${{ secrets.HARBOR_USERNAME }}
          password: ${{ secrets.HARBOR_PASSWORD }}

      - name: Build and push web
        id: build
        uses: docker/build-push-action@v6
        with:
          context: apps/web
          push: true
          tags: |
            ${{ env.IMAGE_WEB }}:${{ github.sha }}
            ${{ env.IMAGE_WEB }}:${{ steps.vars.outputs.short_sha }}
            ${{ env.IMAGE_WEB }}:latest
          cache-from: type=registry,ref=${{ env.IMAGE_WEB_CACHE }}
          cache-to: type=registry,ref=${{ env.IMAGE_WEB_CACHE }},mode=max
```

- [ ] **Step 7: Add scan-web job**

Insert after `build-web` (or extend the existing scan matrix — but a separate job is simpler since the web image has no ML skip-dirs and no .trivyignore concerns):

```yaml
  # ── Stage 3: Security scan frontend (main only, non-blocking) ─
  scan-web:
    runs-on: osint-core-runner
    needs: build-web
    continue-on-error: true
    if: >-
      github.ref == 'refs/heads/main'
      && needs.build-web.result == 'success'
      && !inputs.run_migrations
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v4

      - name: Pull image
        run: docker pull "${{ env.IMAGE_WEB }}@${{ needs.build-web.outputs.digest }}"

      - name: Run Trivy vulnerability scanner
        env:
          TRIVY_DB_REPOSITORY: "ghcr.io/aquasecurity/trivy-db"
        run: |
          docker run --rm \
            -e TRIVY_DB_REPOSITORY \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v "$PWD:/workspace" \
            aquasec/trivy:0.56.1 image \
              --timeout 5m0s \
              --format sarif \
              --output /workspace/trivy-results-web.sarif \
              --severity HIGH,CRITICAL \
              --ignore-unfixed \
              --exit-code 1 \
              "${{ env.IMAGE_WEB }}@${{ needs.build-web.outputs.digest }}"

      - name: Upload Trivy scan to GitHub Security tab
        uses: github/codeql-action/upload-sarif@v3
        if: always() && hashFiles('trivy-results-web.sarif') != ''
        with:
          sarif_file: trivy-results-web.sarif
          category: trivy-web
```

- [ ] **Step 8: Update deploy job to handle both backend and frontend**

Replace the existing `deploy` job with:

```yaml
  # ── Stage 4: Deploy to K8s via GitOps (main only) ──────────────
  deploy:
    runs-on: osint-core-runner
    needs: [changes, build, scan, migrate, build-web, scan-web]
    if: >-
      always()
      && github.ref == 'refs/heads/main'
      && !inputs.run_migrations
      && (needs.build.result == 'success' || needs.build-web.result == 'success')
      && (needs.build.result != 'success' || needs.migrate.result == 'success')
    concurrency:
      group: osint-infra-deploy
      cancel-in-progress: false
    steps:
      - name: Set up runner
        run: |
          which ssh || (sudo apt-get update -qq && sudo apt-get install -y -qq openssh-client)

      - name: Set up SSH for cortech-infra
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.DEPLOY_KEY_INFRA }}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          cat > /tmp/github_known_hosts <<'KEYS'
          github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
          github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
          github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
          KEYS

      - name: Install kustomize
        uses: imranismail/setup-kustomize@v2.1.0

      - name: Clone cortech-infra and update image tags
        env:
          GIT_SSH_COMMAND: "ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/tmp/github_known_hosts"
          SHORT_SHA: ${{ needs.build.outputs.short_sha || needs.build-web.outputs.short_sha }}
          FULL_SHA: ${{ github.sha }}
          DIGEST_API: ${{ needs.build.outputs.digest_api }}
          DIGEST_WEB: ${{ needs.build-web.outputs.digest }}
          BACKEND_CHANGED: ${{ needs.build.result == 'success' }}
          FRONTEND_CHANGED: ${{ needs.build-web.result == 'success' }}
          RUN_ID: ${{ github.run_id }}
        run: |
          rm -rf /tmp/cortech-infra
          git clone git@github.com:jacorbello/cortech-infra.git /tmp/cortech-infra
          cd /tmp/cortech-infra

          OVERLAY="apps/osint/overlays/production"

          # Update backend image if backend was built
          if [ "$BACKEND_CHANGED" = "true" ]; then
            (cd "$OVERLAY" && kustomize edit set image harbor.corbello.io/osint/osint-core:${SHORT_SHA})
          fi

          # Update frontend image if frontend was built
          if [ "$FRONTEND_CHANGED" = "true" ]; then
            (cd "$OVERLAY" && kustomize edit set image harbor.corbello.io/osint/osint-web:${SHORT_SHA})
          fi

          # No-op if image tags are already current
          if git diff --quiet; then
            echo "::notice::Image tags already up to date — no deploy needed."
            exit 0
          fi

          # Assert only the expected file changed
          CHANGED=$(git diff --name-only)
          if [ "$CHANGED" != "${OVERLAY}/kustomization.yaml" ]; then
            echo "::error::Unexpected files changed: ${CHANGED}"
            exit 1
          fi

          # Build commit message
          MSG="deploy(osint): update"
          if [ "$BACKEND_CHANGED" = "true" ]; then
            MSG="$MSG osint-core"
          fi
          if [ "$FRONTEND_CHANGED" = "true" ]; then
            [ "$BACKEND_CHANGED" = "true" ] && MSG="$MSG +" || true
            MSG="$MSG osint-web"
          fi
          MSG="$MSG to ${SHORT_SHA}"

          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          git add "${OVERLAY}/kustomization.yaml"
          git commit -m "$MSG

          Source: jacorbello/osint-core@${FULL_SHA}
          Workflow: https://github.com/jacorbello/osint-core/actions/runs/${RUN_ID}
          ArgoCD: osint-platform (${OVERLAY})
          Backend digest: ${DIGEST_API:-skipped}
          Frontend digest: ${DIGEST_WEB:-skipped}"

          # Push with one retry on conflict
          if ! git push origin main; then
            echo "::warning::Push conflict — retrying with pull-rebase"
            git pull --rebase origin main
            git push origin main
          fi

      - name: Cleanup credentials
        if: always()
        run: |
          rm -f ~/.ssh/deploy_key
          rm -f /tmp/github_known_hosts
          rm -rf /tmp/cortech-infra
```

The key logic in the `if:` condition:
- At least one of `build` or `build-web` must have succeeded (something to deploy)
- If backend was built, migrate must have succeeded (don't deploy broken schema)
- If only frontend was built, migrate is irrelevant (skipped jobs have result `skipped`, not `success`)

- [ ] **Step 9: Validate the full workflow YAML**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yaml'))" && echo "YAML valid"
```

Expected: `YAML valid`

- [ ] **Step 10: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "ci: add frontend lint/test/build jobs with path filtering"
```

---

### Task 5: Makefile Additions

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add new targets**

Add after the existing `web-preview` target and before the `precommit` target. Also update the `.PHONY` line to include the new targets.

Add to `.PHONY`:

```makefile
.PHONY: help format lint typecheck test check check-full build push scan dev dev-down dev-down-clean logs precommit clean web-dev web-build web-test web-test-watch web-test-coverage web-preview web-lint web-build-image web-check
```

Add the new targets:

```makefile
web-lint: ## Lint frontend (mirrors CI)
	cd apps/web && npm run lint

web-build-image: ## Build frontend Docker image tagged with git SHA
	docker build -f apps/web/Dockerfile -t $(IMAGE)-web:$(SHA) -t $(IMAGE)-web:local apps/web

web-check: web-lint web-test ## Run all frontend checks (mirrors CI)
```

- [ ] **Step 2: Verify targets work**

Run:
```bash
make web-check
```

Expected: ESLint lint passes, Vitest tests pass.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "ci: add web-lint, web-build-image, web-check make targets"
```

---

### Task 6: AGENTS.md Update

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Add frontend to project structure**

In the first paragraph of "Project Structure & Module Organization", after the sentence about `docs/`, add:

```
Frontend code lives in `apps/web/` (React + Vite + TypeScript). Deployment manifests for the frontend are in `deploy/k8s/web/`.
```

- [ ] **Step 2: Add frontend CI info to build/test section**

In "Build, Test, and Development Commands", after the `make check` bullet, add:

```markdown
- `make web-lint`: run ESLint on `apps/web/`.
- `make web-check`: run frontend lint and tests in the same sequence as CI.
```

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: add frontend CI targets and project structure to AGENTS.md"
```

---

### Task 7: End-to-End Verification

- [ ] **Step 1: Run full backend check**

Run:
```bash
make check
```

Expected: All lint, typecheck, and tests pass. Nothing broken by our changes (we only touched CI/infra files, not backend code).

- [ ] **Step 2: Run full frontend check**

Run:
```bash
make web-check
```

Expected: Lint and tests pass.

- [ ] **Step 3: Verify Docker image builds**

Run:
```bash
make web-build-image
```

Expected: Docker build succeeds, image tagged with current SHA.

- [ ] **Step 4: Verify YAML validity of all changed files**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yaml'))" && echo "ci.yaml valid"
python -c "import yaml; yaml.safe_load(open('deploy/k8s/web/deployment.yaml'))" && echo "deployment.yaml valid"
python -c "import yaml; yaml.safe_load(open('deploy/k8s/web/service.yaml'))" && echo "service.yaml valid"
```

Expected: All three print `valid`.

- [ ] **Step 5: Verify Kubernetes manifests**

Run:
```bash
kubectl apply --dry-run=client -f deploy/k8s/web/
```

Expected: Both deployment and service validate successfully.

- [ ] **Step 6: Review git log**

Run:
```bash
git log --oneline -10
```

Expected: 6 new commits (one per task 1-6), all with `ci:` or `docs:` conventional prefixes.
