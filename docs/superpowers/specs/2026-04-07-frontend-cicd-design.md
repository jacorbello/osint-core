# Frontend CI/CD and Deployment Design

**Date:** 2026-04-07
**Status:** Approved
**Scope:** Wire the `apps/web` React/Vite frontend into CI/CD and deploy it as a standalone container in the Kubernetes cluster.

## Context

The OSINT platform backend (API, worker, beat) has a mature CI/CD pipeline in `.github/workflows/ci.yaml` that builds Docker images, pushes to Harbor (`harbor.corbello.io/osint/`), and deploys via GitOps (updating Kustomize overlays in the `cortech-infra` repo, synced by ArgoCD).

The `apps/web` frontend (React 18 + Vite + TypeScript + Tailwind) is bootstrapped with a working first screen but has no Dockerfile, no CI jobs, and no Kubernetes manifests. This spec covers wiring it into the existing pipeline.

## Approach

Extend the existing `ci.yaml` workflow with path-filtered frontend jobs rather than creating a separate workflow. This avoids duplicating GitOps deploy logic, prevents race conditions on `cortech-infra` pushes, and enables atomic deploys when both backend and frontend change in the same commit.

## 1. Dockerfile (`apps/web/Dockerfile`)

Multi-stage build:

### Stage 1 — Build

- Base image: `node:22-alpine`
- Working directory: `/app`
- Copy `package.json` and `package-lock.json` (from `apps/web/` context)
- Run `npm ci` for reproducible installs
- Copy remaining source files
- Run `npm run build` producing `dist/` with static assets
- Build context: `apps/web/` (no repo-root files needed)

### Stage 2 — Runtime

- Base image: `nginx:1.27-alpine`
- Copy `dist/` into `/usr/share/nginx/html`
- Copy custom `nginx.conf`
- Expose port 80
- No Node.js runtime in production — Nginx serves static files only

## 2. Nginx Configuration (`apps/web/nginx.conf`)

- `try_files $uri $uri/ /index.html` for SPA client-side routing
- Gzip enabled for JS, CSS, HTML, JSON, SVG
- Hashed assets (`/assets/*`): `Cache-Control: public, max-age=31536000, immutable`
- `index.html`: `Cache-Control: no-cache` so deployments are picked up immediately
- Health check endpoint: `GET /healthz` returns 200
- No `/api` proxy — API routing is handled at cluster ingress level

## 3. CI Workflow Changes (`ci.yaml`)

### Path filtering

Jobs use path-based conditions to skip unnecessary work:

- **Backend jobs** (`lint`, `test`, `typecheck`, `build`, `migrate`): run on changes to `src/`, `tests/`, `migrations/`, `Dockerfile`, `pyproject.toml`, `alembic.ini`
- **Frontend jobs** (`lint-web`, `test-web`, `build-web`): run on changes to `apps/web/`
- **Deploy**: runs when either `build` or `build-web` produced new images
- **Shared files** (`.github/workflows/ci.yaml`, `Makefile`): trigger both pipelines

### New jobs

All run on the `osint-core-runner` runner, parallel to existing backend jobs:

**`lint-web`**
- Node 22 setup
- `npm ci` in `apps/web/`
- `npm run lint`

**`test-web`**
- Node 22 setup
- `npm ci` in `apps/web/`
- `npm run test`

**`build-web`** (main branch only, requires `lint-web` + `test-web`)
- Docker buildx setup
- Build `apps/web/Dockerfile`
- Push to `harbor.corbello.io/osint/osint-web`
- Tags: full SHA, short SHA (7 chars), `latest`
- Registry-level build cache (same pattern as backend)

### Modified jobs

**`scan`**
- Add `osint-web` image as an additional scan target

**`deploy`**
- Requires: `build` (if ran) AND `build-web` (if ran)
- Runs `kustomize edit set image` for each image that was built
- Same SSH setup, cortech-infra clone, push-with-retry logic
- Commit message includes both image references when both changed

## 4. Kubernetes Manifests (`deploy/k8s/web/`)

### Deployment (`deployment.yaml`)

- Namespace: `osint`
- Image: `harbor.corbello.io/osint/osint-web:latest` (overridden by Kustomize)
- Replicas: 1
- Container port: 80
- Liveness probe: `GET /healthz` every 15s, 3 failure threshold
- Readiness probe: `GET /healthz` every 5s, 2 failure threshold
- Resources:
  - Request: 50m CPU, 64Mi memory
  - Limit: 200m CPU, 128Mi memory
- Labels: `app: osint-web`, `component: frontend`

### Service (`service.yaml`)

- Type: ClusterIP
- Port: 80 → container port 80
- Selector: `app: osint-web`

### Ingress

Not included here. The ingress configuration lives in `cortech-infra` alongside existing routing rules. A one-time manual addition is needed to route frontend traffic to the `osint-web` service.

## 5. Makefile Additions

| Target | Command | Purpose |
|--------|---------|---------|
| `web-lint` | `cd apps/web && npm run lint` | Lint frontend (mirrors CI) |
| `web-build-image` | `docker build -f apps/web/Dockerfile -t $(IMAGE)-web:$(SHA) apps/web` | Build Docker image locally |
| `web-check` | `web-lint` + `web-test` | Full frontend CI check locally |

Existing targets (`web-dev`, `web-build`, `web-test`, `web-test-watch`, `web-test-coverage`, `web-preview`) are unchanged.

## 6. `.dockerignore`

An `apps/web/.dockerignore` to keep the build context small:

- `node_modules/`
- `dist/`
- `.env*`
- `*.md`
- `.vite/`

## 7. AGENTS.md Update

- Add `apps/web/` to the project structure section
- Document `make web-check` as the frontend equivalent of `make check`
- Note the frontend CI integration in the build/test section

## Pipeline Flow

```
Push to main
├── changes in src/, tests/, migrations/, etc.
│   ├── lint (parallel)
│   ├── typecheck (parallel)
│   └── test (parallel)
│       └── build → push harbor.corbello.io/osint/osint-core:SHA
│           ├── scan (non-blocking)
│           └── migrate
│
├── changes in apps/web/
│   ├── lint-web (parallel)
│   └── test-web (parallel)
│       └── build-web → push harbor.corbello.io/osint/osint-web:SHA
│           └── scan (non-blocking)
│
└── deploy (after all required builds + migrate complete)
    └── update cortech-infra kustomize overlay(s)
        └── ArgoCD syncs to cluster
```

On PRs, only lint/test jobs run (no build, no deploy).

## Out of Scope

- CDN / edge caching (can be added later in front of the ingress)
- Preview environments for PRs
- Environment-specific build-time configuration (currently proxied at dev time, ingress-routed in production)
- Horizontal pod autoscaling (single replica is sufficient for now)
