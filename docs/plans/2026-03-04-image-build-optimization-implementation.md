# Image Build Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate CI image builds to Buildx + Harbor registry cache, build all three targets (api/worker/beat), and matrix-scan each with Trivy.

**Architecture:** Three sequential `docker/build-push-action@v6` calls share a single Harbor registry cache (`mode=max`), eliminating the need for manual prune steps. The scan job becomes a matrix over all three images. A BuildKit pip cache mount in the Dockerfile prevents redundant pip downloads on code-only changes.

**Tech Stack:** GitHub Actions, Docker Buildx, `docker/build-push-action@v6`, `docker/setup-buildx-action@v3`, `docker/login-action@v3`, Harbor registry cache, Trivy (containerised)

**Design doc:** `docs/plans/2026-03-04-image-build-optimization-design.md`

---

## Validation Commands

These are the "tests" for CI config changes — run after each task:

```bash
# YAML syntax check
python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yaml')); print('OK')"

# Dockerfile syntax check (requires docker)
docker build --check .
```

There are no unit tests for pipeline config. The integration test is opening a PR and watching CI run. The plan notes where a CI run should be triggered.

---

### Task 1: Dockerfile — add BuildKit pip cache mount

**Files:**
- Modify: `Dockerfile`

**Step 1: Edit the pip install in the `base` stage**

Change this line in `Dockerfile` (line 10):
```dockerfile
RUN pip install --no-cache-dir "."
```
To:
```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir "."
```

The `--mount=type=cache` is a BuildKit directive that mounts a persistent cache directory during the build step. It does not add the cache to the image layer — it only speeds up the build by reusing previously downloaded wheels.

**Step 2: Validate Dockerfile syntax**

```bash
docker build --check .
```
Expected: no errors. If docker is unavailable on your machine, skip — the build job will catch it.

**Step 3: Commit**

```bash
git add Dockerfile
git commit -m "perf(docker): add BuildKit pip cache mount to base stage"
```

---

### Task 2: Add IMAGE_WORKER and IMAGE_BEAT env vars

**Files:**
- Modify: `.github/workflows/ci.yaml`

**Step 1: Extend the top-level `env` block**

Current `env` block (lines 13–15):
```yaml
env:
  IMAGE: harbor.corbello.io/osint/osint-core
```

Replace with:
```yaml
env:
  IMAGE: harbor.corbello.io/osint/osint-core
  IMAGE_WORKER: harbor.corbello.io/osint/osint-core-worker
  IMAGE_BEAT: harbor.corbello.io/osint/osint-core-beat
  IMAGE_CACHE: harbor.corbello.io/osint/osint-core-cache
```

`IMAGE_CACHE` is a dedicated Harbor repository used solely as a BuildKit layer cache store. It holds no runnable image — only BuildKit cache manifests.

**Step 2: Validate YAML syntax**

```bash
python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yaml')); print('OK')"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "ci: add IMAGE_WORKER, IMAGE_BEAT, IMAGE_CACHE env vars"
```

---

### Task 3: Update build job — Buildx setup and login-action

**Files:**
- Modify: `.github/workflows/ci.yaml` — `build` job steps

**Step 1: Remove the pre-build prune step**

Delete this entire step from the build job (currently after the `actions/checkout@v4` step):
```yaml
      - name: Pre-build Docker cleanup
        run: |
          docker system prune -af --volumes || true
          docker builder prune -af || true
```

BuildKit tracks its own cache and does not leave dangling layers. This step is no longer needed.

**Step 2: Remove the post-build prune step**

Delete this entire step:
```yaml
      - name: Post-build Docker cleanup
        if: always()
        run: |
          docker image prune -af || true
          docker builder prune -af || true
          docker system df || true
```

**Step 3: Replace the manual docker login step**

Delete:
```yaml
      - name: Log in to Harbor
        run: echo "${{ secrets.HARBOR_PASSWORD }}" | docker login harbor.corbello.io -u "${{ secrets.HARBOR_USERNAME }}" --password-stdin
```

Replace with:
```yaml
      - name: Log in to Harbor
        uses: docker/login-action@v3
        with:
          registry: harbor.corbello.io
          username: ${{ secrets.HARBOR_USERNAME }}
          password: ${{ secrets.HARBOR_PASSWORD }}
```

**Step 4: Add Buildx setup step immediately before the login step**

Insert before the login step:
```yaml
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
```

**Step 5: Validate YAML syntax**

```bash
python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yaml')); print('OK')"
```
Expected: `OK`

**Step 6: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "ci(build): add Buildx setup, use login-action, remove disk prune steps"
```

---

### Task 4: Update build job — replace docker build/push with build-push-action × 3

**Files:**
- Modify: `.github/workflows/ci.yaml` — `build` job steps and outputs

**Step 1: Update the job `outputs` block**

Current:
```yaml
    outputs:
      digest: ${{ steps.push.outputs.digest }}
      short_sha: ${{ steps.vars.outputs.short_sha }}
```

Replace with:
```yaml
    outputs:
      digest_api: ${{ steps.build_api.outputs.digest }}
      digest_worker: ${{ steps.build_worker.outputs.digest }}
      digest_beat: ${{ steps.build_beat.outputs.digest }}
      short_sha: ${{ steps.vars.outputs.short_sha }}
```

**Step 2: Delete the old `Build image` step**

Delete:
```yaml
      - name: Build image
        run: |
          docker build --target api \
            -t ${{ env.IMAGE }}:${{ github.sha }} \
            -t ${{ env.IMAGE }}:${{ steps.vars.outputs.short_sha }} \
            -t ${{ env.IMAGE }}:latest \
            .
```

**Step 3: Delete the old `Push image and capture digest` step**

Delete the entire step with `id: push` (the one that runs `docker push` three times and parses the digest with `awk`).

**Step 4: Add the three build-push-action steps**

Add after the `Set variables` step:

```yaml
      - name: Build and push api
        id: build_api
        uses: docker/build-push-action@v6
        with:
          context: .
          target: api
          push: true
          tags: |
            ${{ env.IMAGE }}:${{ github.sha }}
            ${{ env.IMAGE }}:${{ steps.vars.outputs.short_sha }}
            ${{ env.IMAGE }}:latest
          cache-from: type=registry,ref=${{ env.IMAGE_CACHE }}
          cache-to: type=registry,ref=${{ env.IMAGE_CACHE }},mode=max

      - name: Build and push worker
        id: build_worker
        uses: docker/build-push-action@v6
        with:
          context: .
          target: worker
          push: true
          tags: |
            ${{ env.IMAGE_WORKER }}:${{ github.sha }}
            ${{ env.IMAGE_WORKER }}:${{ steps.vars.outputs.short_sha }}
            ${{ env.IMAGE_WORKER }}:latest
          cache-from: type=registry,ref=${{ env.IMAGE_CACHE }}
          cache-to: type=registry,ref=${{ env.IMAGE_CACHE }},mode=max

      - name: Build and push beat
        id: build_beat
        uses: docker/build-push-action@v6
        with:
          context: .
          target: beat
          push: true
          tags: |
            ${{ env.IMAGE_BEAT }}:${{ github.sha }}
            ${{ env.IMAGE_BEAT }}:${{ steps.vars.outputs.short_sha }}
            ${{ env.IMAGE_BEAT }}:latest
          cache-from: type=registry,ref=${{ env.IMAGE_CACHE }}
          cache-to: type=registry,ref=${{ env.IMAGE_CACHE }},mode=max
```

Note: `cache-to` is on all three steps. BuildKit deduplicates — the `base` layer is written to the cache by the first build and read from it by the second and third.

**Step 5: Validate YAML syntax**

```bash
python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yaml')); print('OK')"
```
Expected: `OK`

**Step 6: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "ci(build): replace docker build/push with build-push-action for all three targets"
```

---

### Task 5: Update scan job — matrix over api, worker, beat

**Files:**
- Modify: `.github/workflows/ci.yaml` — `scan` job

**Step 1: Add matrix strategy to the scan job**

The current scan job has no `strategy`. Add it directly under the `scan:` key, before `runs-on`:

```yaml
    strategy:
      fail-fast: false
      matrix:
        target: [api, worker, beat]
```

`fail-fast: false` ensures all three scans run even if one finds vulnerabilities — you get the full picture.

**Step 2: Update the job `if` condition and `needs`**

Current:
```yaml
    if: github.ref == 'refs/heads/main' && needs.build.result == 'success'
```

No change needed here — the condition already works with a matrix job.

**Step 3: Replace the hardcoded Trivy image reference**

The current Trivy step uses `${{ env.IMAGE }}@${{ needs.build.outputs.digest }}`.

First, add a step before the Trivy run to resolve the correct image and digest for the current matrix target:

```yaml
      - name: Resolve image for this target
        id: img
        run: |
          case "${{ matrix.target }}" in
            api)    echo "ref=${{ env.IMAGE }}@${{ needs.build.outputs.digest_api }}" >> "$GITHUB_OUTPUT" ;;
            worker) echo "ref=${{ env.IMAGE_WORKER }}@${{ needs.build.outputs.digest_worker }}" >> "$GITHUB_OUTPUT" ;;
            beat)   echo "ref=${{ env.IMAGE_BEAT }}@${{ needs.build.outputs.digest_beat }}" >> "$GITHUB_OUTPUT" ;;
          esac
```

**Step 4: Update the Trivy run step**

In the Trivy `docker run` command, replace the final positional argument:

Old:
```
"${{ env.IMAGE }}@${{ needs.build.outputs.digest }}"
```

New:
```
"${{ steps.img.outputs.ref }}"
```

Also update the `--output` flag to include the target name:

Old:
```
--output /workspace/trivy-results.sarif
```

New:
```
--output /workspace/trivy-results-${{ matrix.target }}.sarif
```

**Step 5: Update the SARIF upload step**

Old:
```yaml
        with:
          sarif_file: "trivy-results.sarif"
```

New:
```yaml
        with:
          sarif_file: "trivy-results-${{ matrix.target }}.sarif"
```

Also update the `hashFiles` guard:

Old:
```yaml
        if: always() && hashFiles('trivy-results.sarif') != ''
```

New:
```yaml
        if: always() && hashFiles('trivy-results-${{ matrix.target }}.sarif') != ''
```

**Step 6: Update deploy job to use digest_api**

The deploy job references `needs.build.outputs.digest`. Update to `needs.build.outputs.digest_api`:

```yaml
          DIGEST: ${{ needs.build.outputs.digest_api }}
```

**Step 7: Validate YAML syntax**

```bash
python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yaml')); print('OK')"
```
Expected: `OK`

**Step 8: Commit**

```bash
git add .github/workflows/ci.yaml
git commit -m "ci(scan): matrix scan over api, worker, beat; update deploy to use digest_api"
```

---

### Task 6: Integration test — open a PR and verify CI

**Step 1: Push your branch**

```bash
git push -u origin feat/image-build-optimization
```

**Step 2: Open a PR against main**

The `lint` and `test` jobs will run (they don't involve Docker). Verify they pass.

**Step 3: Merge to main and watch the full pipeline**

The build job runs `lint` + `test` → `build` → `scan` (matrix × 3) → `deploy`.

**Expected outcomes:**
- Build job: three images pushed to Harbor, no prune steps needed, disk usage stays well below the 12 GB guard
- Cache: second CI run is meaningfully faster (base layer resolved from Harbor cache)
- Scan job: three parallel Trivy scans, three SARIF files uploaded to GitHub Security tab
- Deploy job: updates kustomization with `osint-core:short_sha` as before

**If the cache repo doesn't exist in Harbor yet:**

Create it manually in the Harbor UI: `osint/osint-core-cache`. Set it as a private repository. No special configuration is required — BuildKit creates the cache manifest on first push.

Similarly, create `osint/osint-core-worker` and `osint/osint-core-beat` if they don't exist.
