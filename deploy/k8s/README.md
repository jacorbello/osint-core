# Kubernetes Deployment Notes

The live deployment manifests live in the `cortech-infra` repository under
`apps/osint/overlays/production`.  The CI pipeline in this repo clones
`cortech-infra` and updates the image tag via `kustomize edit set image`
on every merge to `main`.

## Running migrations

`migration-job.yaml` defines a Kubernetes Job that runs `alembic upgrade head`.
It should be applied (or triggered via ArgoCD PreSync hook) before each
deployment that introduces schema changes.

### Manual rollout

```bash
# Tag must match the image being deployed
kubectl -n osint set image job/osint-migrate \
  migrate=harbor.corbello.io/osint/osint-core-api:<SHA>

kubectl -n osint apply -f migration-job.yaml
kubectl -n osint wait --for=condition=complete --timeout=120s job/osint-migrate
```

### ArgoCD PreSync hook (recommended)

Uncomment the `argocd.argoproj.io/hook: PreSync` annotations in
`migration-job.yaml`, copy the file to
`apps/osint/overlays/production/` in `cortech-infra`, and add it to the
overlay's `kustomization.yaml`.  ArgoCD will then run the Job before
syncing the Deployment, ensuring the database is always migrated before
the new pods start.
