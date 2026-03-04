# Image Build Optimization Design

**Date:** 2026-03-04
**Status:** Approved

## Problem

The current CI build job uses plain `docker build` with no BuildKit, no layer caching, and three
separate `docker push` commands. It only builds the `api` target, leaving `worker` and `beat`
unbuilt and unscanned. Disk pressure is severe enough to require aggressive pre/post
`docker system prune -af --volumes` and a 12 GB free-space guard.

## Goals

- Build and push all three targets (`api`, `worker`, `beat`) in CI
- Eliminate redundant disk cleanup via BuildKit's efficient layer handling
- Cache image layers in Harbor for fast incremental builds
- Scan all three images with Trivy
- Follow industry-standard separate-repository-per-component naming

## Non-Goals

- Changes to `build-base-images.yml` (already uses Buildx + GHA cache correctly)
- Changes to the deploy job (continues to use the `api` digest/sha via GitOps)
- Multi-platform builds

---

## Design

### 1. Build Job

Add `docker/setup-buildx-action@v3` and replace manual `docker login` with
`docker/login-action@v3` for consistency with `build-base-images.yml`.

Replace the single `docker build` + three `docker push` shell commands with three sequential
`docker/build-push-action@v6` calls — one per target. Each call:

- `context: .`
- `target: <api|worker|beat>`
- `push: true`
- Tags: `IMAGE:${{ github.sha }}`, `IMAGE:${{ short_sha }}`, `IMAGE:latest`
- `cache-from: type=registry,ref=harbor.corbello.io/osint/osint-core-cache`
- `cache-to: type=registry,ref=harbor.corbello.io/osint/osint-core-cache,mode=max`

`mode=max` exports all intermediate layers (including `base`). On a code-only change with no
dependency changes, BuildKit resolves the `base` stage entirely from the registry cache and skips
`pip install` altogether. The three sequential builds share this cache, so `base` is only
materialised once per run.

Build job outputs are extended from a single `digest` to `digest_api`, `digest_worker`, and
`digest_beat`, each captured from the respective action's `outputs.digest`.

The pre/post `docker system prune` steps are removed — BuildKit does not accumulate dangling
layers the way classic builder does. The disk guard check stays as a conservative safety net.

### 2. Image Naming

Separate Harbor repositories per component (industry standard):

| Target | Repository |
|--------|-----------|
| `api` | `harbor.corbello.io/osint/osint-core` (existing, unchanged) |
| `worker` | `harbor.corbello.io/osint/osint-core-worker` (new) |
| `beat` | `harbor.corbello.io/osint/osint-core-beat` (new) |

Add `IMAGE_WORKER` and `IMAGE_BEAT` top-level env vars alongside the existing `IMAGE`.

### 3. Dockerfile — pip Cache Mount

Add a BuildKit cache mount to the `pip install` step in the `base` stage:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "."
```

The `--mount=type=cache` persists the pip download cache between builds on the same runner
without including it in the image layer. `--no-cache-dir` is omitted — it would instruct pip
to bypass the cache entirely, directly cancelling the mount's effect. Combined with registry
layer caching, a code-only change skips both pip download and pip install entirely.

### 4. Scan Job

Convert from a single scan to a matrix over `[api, worker, beat]`. Each leg:

- Scans `IMAGE:digest_<target>` via Trivy (containerised, existing flags unchanged)
- Outputs `trivy-results-${{ matrix.target }}.sarif`
- Uploads its SARIF to the GitHub Security tab

All three matrix legs must succeed for the deploy job to proceed.

### 5. Deploy Job

Unchanged. Continues to use `needs.build.outputs.digest_api` and `short_sha` for the GitOps
kustomize image tag update.

---

## Trade-offs Considered

| Option | Verdict |
|--------|---------|
| `docker buildx bake` | Overkill for 3 targets; bake config is extra maintenance surface |
| GHA cache for build layers | GHA cache has 10 GB cap and 7-day eviction; Harbor is co-located on same network and has no size limit |
| Single repo with tag prefixes | Less standard than separate repos; complicates pull policies and per-image scanning in Harbor |
