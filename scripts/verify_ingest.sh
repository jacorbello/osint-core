#!/usr/bin/env bash
# verify_ingest.sh — End-to-end ingest pipeline verification.
#
# Triggers a manual ingest for a source, then checks that:
#   1. The ingest task was dispatched successfully
#   2. A job record was created with status = succeeded
#   3. Events were written to the database
#   4. Indicators were extracted from ingested events
#
# Usage:
#   ./scripts/verify_ingest.sh [SOURCE_ID] [PLAN_ID]
#
# Defaults:
#   SOURCE_ID = cisa_kev
#   PLAN_ID   = libertycenter-osint
#
# Environment:
#   API_BASE_URL  — API base URL (default: http://localhost:8000)
#   API_TOKEN     — Bearer token for authenticated deployments (omit when auth_disabled=true)
#   CURL_TIMEOUT  — Max seconds per curl request (default: 30)
#   POLL_INTERVAL — Seconds between status polls (default: 5)
#   POLL_TIMEOUT  — Max seconds to wait for task completion (default: 120)

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
SOURCE_ID="${1:-cisa_kev}"
PLAN_ID="${2:-libertycenter-osint}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
POLL_TIMEOUT="${POLL_TIMEOUT:-120}"
API_TOKEN="${API_TOKEN:-}"
CURL_TIMEOUT="${CURL_TIMEOUT:-30}"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

check_pass() { PASS=$((PASS + 1)); green "  ✓ $1"; }
check_fail() { FAIL=$((FAIL + 1)); red   "  ✗ $1"; }

require_cmd() {
    if ! command -v "$1" &>/dev/null; then
        red "ERROR: '$1' is required but not installed."
        exit 1
    fi
}

api_get() {
    if [[ -n "${API_TOKEN}" ]]; then
        curl -sf --max-time "${CURL_TIMEOUT}" \
            -H "Authorization: Bearer ${API_TOKEN}" \
            "${API_BASE_URL}$1"
    else
        curl -sf --max-time "${CURL_TIMEOUT}" "${API_BASE_URL}$1"
    fi
}
api_post() {
    if [[ -n "${API_TOKEN}" ]]; then
        curl -sf --max-time "${CURL_TIMEOUT}" -X POST \
            -H "Authorization: Bearer ${API_TOKEN}" \
            "${API_BASE_URL}$1"
    else
        curl -sf --max-time "${CURL_TIMEOUT}" -X POST "${API_BASE_URL}$1"
    fi
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
require_cmd curl
require_cmd jq

bold "============================================================"
bold " OSINT-Core End-to-End Ingest Verification"
bold "============================================================"
echo ""
echo "  API:      ${API_BASE_URL}"
echo "  Source:   ${SOURCE_ID}"
echo "  Plan:     ${PLAN_ID}"
echo "  Timeout:  ${POLL_TIMEOUT}s"
echo ""

# ---------------------------------------------------------------------------
# Step 0: Health check
# ---------------------------------------------------------------------------
bold "Step 0: API health check"
if api_get "/healthz" > /dev/null 2>&1; then
    check_pass "API is reachable at ${API_BASE_URL}/healthz"
else
    check_fail "API is not reachable at ${API_BASE_URL}/healthz"
    red "Aborting — ensure the stack is running (docker compose -f docker-compose.dev.yaml up -d)"
    exit 1
fi
echo ""

# ---------------------------------------------------------------------------
# Step 1: Trigger ingest
# ---------------------------------------------------------------------------
bold "Step 1: Trigger manual ingest"

DISPATCH_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

DISPATCH_RESPONSE=$(api_post "/api/v1/ingest/source/${SOURCE_ID}/run?plan_id=${PLAN_ID}" 2>&1) || {
    check_fail "POST /api/v1/ingest/source/${SOURCE_ID}/run returned an error"
    echo "  Response: ${DISPATCH_RESPONSE}"
    exit 1
}

TASK_ID=$(echo "${DISPATCH_RESPONSE}" | jq -r '.task_id // empty')
DISPATCH_STATUS=$(echo "${DISPATCH_RESPONSE}" | jq -r '.status // empty')

if [[ -n "${TASK_ID}" && "${DISPATCH_STATUS}" == "dispatched" ]]; then
    check_pass "Ingest task dispatched (task_id=${TASK_ID})"
else
    check_fail "Unexpected dispatch response: ${DISPATCH_RESPONSE}"
    exit 1
fi
echo ""

# ---------------------------------------------------------------------------
# Step 2: Poll for job completion
# ---------------------------------------------------------------------------
bold "Step 2: Wait for job to complete"

ELAPSED=0
JOB_STATUS=""
JOB_ID=""

while [[ ${ELAPSED} -lt ${POLL_TIMEOUT} ]]; do
    JOBS_RESPONSE=$(api_get "/api/v1/jobs?limit=100" 2>/dev/null) || true

    if [[ -n "${JOBS_RESPONSE}" ]]; then
        # Match job by celery_task_id (== TASK_ID from dispatch response),
        # falling back to source_id + dispatch time for older records without it
        JOB_MATCH=$(echo "${JOBS_RESPONSE}" | jq -r --arg tid "${TASK_ID}" \
            '[.items[] | select(.celery_task_id == $tid)] | first // empty')

        if [[ -z "${JOB_MATCH}" || "${JOB_MATCH}" == "null" ]]; then
            JOB_MATCH=$(echo "${JOBS_RESPONSE}" | jq -r --arg sid "${SOURCE_ID}" --arg dt "${DISPATCH_TIME}" \
                '[.items[] | select(.input.source_id == $sid and .submitted_at >= $dt)] | sort_by(.submitted_at) | last // empty')
        fi

        if [[ -n "${JOB_MATCH}" && "${JOB_MATCH}" != "null" ]]; then
            JOB_STATUS=$(echo "${JOB_MATCH}" | jq -r '.status')
            JOB_ID=$(echo "${JOB_MATCH}" | jq -r '.id')

            if [[ "${JOB_STATUS}" == "succeeded" || "${JOB_STATUS}" == "partial_success" ]]; then
                break
            elif [[ "${JOB_STATUS}" == "failed" || "${JOB_STATUS}" == "dead_letter" ]]; then
                break
            fi
        fi
    fi

    printf "  Waiting... (%ds / %ds) [status=%s]\r" "${ELAPSED}" "${POLL_TIMEOUT}" "${JOB_STATUS:-pending}"
    sleep "${POLL_INTERVAL}"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

echo ""  # clear the \r line

if [[ "${JOB_STATUS}" == "succeeded" ]]; then
    check_pass "Job completed with status=succeeded (job_id=${JOB_ID})"
elif [[ "${JOB_STATUS}" == "partial_success" ]]; then
    check_pass "Job completed with status=partial_success (job_id=${JOB_ID})"
    yellow "  ⚠ Some items may have failed — check job output for details"
elif [[ "${JOB_STATUS}" == "failed" || "${JOB_STATUS}" == "dead_letter" ]]; then
    check_fail "Job ended with status=${JOB_STATUS} (job_id=${JOB_ID})"
    JOB_ERROR=$(echo "${JOB_MATCH}" | jq -r '.error // "no error message"')
    red "  Error: ${JOB_ERROR}"
else
    check_fail "Job did not complete within ${POLL_TIMEOUT}s (last status=${JOB_STATUS:-unknown})"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 3: Check events in DB
# ---------------------------------------------------------------------------
bold "Step 3: Verify events were created"

EVENTS_RESPONSE=$(api_get "/api/v1/events?source_id=${SOURCE_ID}&limit=5&date_from=${DISPATCH_TIME}" 2>/dev/null) || true

if [[ -n "${EVENTS_RESPONSE}" ]]; then
    EVENT_COUNT=$(echo "${EVENTS_RESPONSE}" | jq -r '.page.total // 0')
    if [[ "${EVENT_COUNT}" -gt 0 ]]; then
        check_pass "Found ${EVENT_COUNT} event(s) for source_id=${SOURCE_ID}"
        # Show a sample event title
        SAMPLE_TITLE=$(echo "${EVENTS_RESPONSE}" | jq -r '.items[0].title // "N/A"')
        echo "  Sample: ${SAMPLE_TITLE}"
    else
        check_fail "No events found for source_id=${SOURCE_ID}"
    fi
else
    check_fail "Could not query events API"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 4: Check indicators were extracted
# ---------------------------------------------------------------------------
bold "Step 4: Verify indicators were extracted"

INDICATORS_RESPONSE=$(api_get "/api/v1/indicators?source_id=${SOURCE_ID}&limit=10" 2>/dev/null) || true

if [[ -n "${INDICATORS_RESPONSE}" ]]; then
    # Filter to indicators linked to our source and seen after dispatch
    MATCHING_INDICATORS=$(echo "${INDICATORS_RESPONSE}" | jq --arg sid "${SOURCE_ID}" --arg dt "${DISPATCH_TIME}" \
        '[.items[] | select((.sources // [] | any(. == $sid)) and .last_seen >= $dt)]')
    INDICATOR_COUNT=$(echo "${MATCHING_INDICATORS}" | jq 'length')
    if [[ "${INDICATOR_COUNT}" -gt 0 ]]; then
        check_pass "Found ${INDICATOR_COUNT} indicator(s) for source_id=${SOURCE_ID} since dispatch"
        # Show breakdown by type
        echo "${MATCHING_INDICATORS}" | jq -r 'group_by(.indicator_type) | .[] |
            "  Type: \(.[0].indicator_type) — count: \(length)"' 2>/dev/null || true
    else
        check_fail "No indicators found for source_id=${SOURCE_ID} since dispatch"
    fi
else
    check_fail "Could not query indicators API"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 5: Check job output details
# ---------------------------------------------------------------------------
bold "Step 5: Verify job output details"

if [[ -n "${JOB_ID}" && "${JOB_ID}" != "null" ]]; then
    JOB_DETAIL=$(api_get "/api/v1/jobs/${JOB_ID}" 2>/dev/null) || true

    if [[ -n "${JOB_DETAIL}" ]]; then
        INGESTED=$(echo "${JOB_DETAIL}" | jq -r '.result.ingested // 0')
        SKIPPED=$(echo "${JOB_DETAIL}" | jq -r '.result.skipped // 0')
        ERRORS=$(echo "${JOB_DETAIL}" | jq -r '.result.errors // 0')

        echo "  Ingested: ${INGESTED}  |  Skipped: ${SKIPPED}  |  Errors: ${ERRORS}"

        if [[ "${INGESTED}" -gt 0 ]]; then
            check_pass "Job ingested ${INGESTED} item(s)"
        else
            check_fail "Job ingested 0 items"
        fi
    else
        check_fail "Could not fetch job detail for ${JOB_ID}"
    fi
else
    check_fail "No job ID available to inspect"
fi
echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
bold "============================================================"
bold " Summary"
bold "============================================================"
echo ""
green "  Passed: ${PASS}"
if [[ ${FAIL} -gt 0 ]]; then
    red   "  Failed: ${FAIL}"
else
    green "  Failed: ${FAIL}"
fi
echo ""

if [[ ${FAIL} -gt 0 ]]; then
    red "VERIFICATION FAILED — see failures above."
    exit 1
else
    green "ALL CHECKS PASSED — ingest pipeline is working end-to-end."
    exit 0
fi
