#!/usr/bin/env bash
# scripts/load_plan.sh — Bootstrap: sync plan YAMLs into the DB and activate them.
#
# Usage:
#   ./scripts/load_plan.sh                           # default: http://localhost:8000
#   ./scripts/load_plan.sh http://api:8000           # custom API base URL
#   OSINT_API_TOKEN=<token> ./scripts/load_plan.sh   # with Bearer auth (production)
#
# The script calls POST /api/v1/plan/sync which reads every *.yaml in the
# configured plan_dir (default /app/plans), validates, stores new versions,
# and auto-activates them.  After sync it fetches the active plan to confirm.
set -euo pipefail

API_BASE="${1:-http://localhost:8000}"

# Optional Bearer token for production deployments (auth_disabled=false)
AUTH_HEADER=()
if [[ -n "${OSINT_API_TOKEN:-}" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${OSINT_API_TOKEN}")
fi

echo "==> Syncing plans from disk into the database …"
SYNC_RESP=$(curl -s --fail-with-body -X POST "${API_BASE}/api/v1/plan/sync" \
  -H "Accept: application/json" ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"})

SYNCED=$(echo "$SYNC_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('synced',[])))")
ERRORS=$(echo "$SYNC_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('errors',[])))")

echo "    synced: ${SYNCED}  errors: ${ERRORS}"

if [ "$ERRORS" -gt 0 ]; then
  echo "==> Sync errors:"
  echo "$SYNC_RESP" | python3 -m json.tool
  exit 1
fi

# Verify the cyber-threat-intel plan is active
echo ""
echo "==> Verifying active plan for 'cyber-threat-intel' …"
ACTIVE_RESP=$(curl -s --fail-with-body "${API_BASE}/api/v1/plan/active?plan_id=cyber-threat-intel" \
  -H "Accept: application/json" ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"}) && {
  PLAN_ID=$(echo "$ACTIVE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['plan_id'])")
  VERSION=$(echo "$ACTIVE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])")
  echo "    active plan_id=${PLAN_ID}  version=${VERSION}"
  echo ""
  echo "Bootstrap complete. The plan is active and ingest tasks will succeed."
} || {
  echo "    WARNING: no active plan found — check sync output above."
  exit 1
}
