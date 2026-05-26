#!/usr/bin/env bash
# SafeClaw — GBrain retrieval smoke test
#
# Verifies the safeclaw-brain HTTP MCP service can put a page AND get it back
# from BOTH `search` (keyword/FTS) and `query` (semantic/vector). Run this after
# bringing the brain up to confirm the full write -> index -> retrieve loop works
# before the Reader/Actor/Reflector start depending on it.
#
# ─── GOTCHA THIS SCRIPT GUARDS AGAINST (read before changing the slug) ──────
#
# GBrain's search/query operations apply a HARD-EXCLUDE slug-prefix filter at
# the chunk-rank stage. The defaults (gbrain src: src/core/search/source-boost.ts
# DEFAULT_HARD_EXCLUDES) are:
#
#       test/   archive/   attachments/   .raw/
#
# Any page whose slug starts with one of those prefixes is SILENTLY dropped from
# both `search` (postgres-engine.ts searchKeyword, buildHardExcludeClause) and
# `query` (the vector path applies the same clause) — even though `put_page`
# succeeds, `gbrain stats` counts it as Embedded, `get_page` returns it in full,
# and the row's tsvector/embedding are present and correct in Postgres.
#
# A prior smoke test wrote slug `test/smoke` and saw search + query return `[]`,
# which looked like a broken index or a source-scoping leak. It was NEITHER:
# `test/` is a hard-excluded prefix, so the page was filtered out of retrieval
# by design. The fix is to smoke-test under a NON-EXCLUDED slug — exactly what
# the real bootstrap writes (people/, companies/, style/, logs/, identity/).
# DO NOT change SMOKE_SLUG to a test/ archive/ attachments/ or .raw/ prefix or
# this script will report a false failure. (If you must probe an excluded slug,
# pass `include_slug_prefixes:["test/"]` in the search/query arguments to opt
# back in — see the gbrain types.ts SearchOpts contract.)
#
# Usage:
#   bash scripts/smoke-brain.sh                 # mints a throwaway token, runs the loop
#   SAFECLAW_BRAIN_TOKEN=gbrain_... bash scripts/smoke-brain.sh   # reuse a token
#   bash scripts/smoke-brain.sh --help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

for arg in "$@"; do
  if [[ "${arg}" == "--help" || "${arg}" == "-h" ]]; then
    sed -n '2,37p' "${BASH_SOURCE[0]}"
    exit 0
  fi
done

BRAIN_SVC="safeclaw-brain"
# NON-EXCLUDED slug on purpose (see GOTCHA above). people/ is what bootstrap uses.
# A per-run timestamp suffix guarantees a FRESH page each run: delete_page is a
# SOFT delete (sets pages.deleted_at), and the search/query visibility clause
# hides soft-deleted pages. Re-using a fixed slug would put_page over a
# soft-deleted row WITHOUT clearing deleted_at, so search/query would return []
# on the second run — a false failure. A unique slug per run sidesteps that.
SMOKE_SLUG="people/_smoke-probe-$(date +%s)"
# A unique, self-contained marker so neither search nor query can match any
# other page. The marker is deliberately rare (random-looking) AND the prose is
# the only thing on the brain talking about it, so the semantic query below
# ranks THIS page first regardless of what else is in the brain.
MARKER="zqxwflumber7731"
SMOKE_CONTENT="# GBrain Smoke Probe\\n\\nThis throwaway page verifies GBrain retrieval end to end. Unique retrieval marker: ${MARKER}. The marker token ${MARKER} appears only here so search and query can prove the write-index-retrieve loop works."

# ── Resolve the container name (compose project prefix may vary) ───────────
if ! docker ps --format '{{.Names}}' | grep -qx "${BRAIN_SVC}"; then
  # Fall back to the compose-resolved container id.
  if ! BRAIN_SVC="$(docker compose ps -q safeclaw-brain 2>/dev/null)"; then
    echo "ERROR: safeclaw-brain container is not running. Run 'docker compose up -d safeclaw-brain' first." >&2
    exit 1
  fi
  [[ -n "${BRAIN_SVC}" ]] || { echo "ERROR: could not resolve the safeclaw-brain container." >&2; exit 1; }
fi

# ── Mint a throwaway token unless one was provided ─────────────────────────
TOKEN="${SAFECLAW_BRAIN_TOKEN:-}"
if [[ -z "${TOKEN}" ]]; then
  # NOTE: --takes-holders is REQUIRED to work around a gbrain v0.37.11.0
  # arg-parsing quirk where `auth create <name>` with no flag drops the
  # positional name and prints usage (mirrors onboarding/lib/provisioner.py).
  CREATE_OUT="$(docker exec "${BRAIN_SVC}" gbrain auth create smoke --takes-holders world,garry,brain 2>&1)" || {
    echo "ERROR: gbrain auth create failed:" >&2; echo "${CREATE_OUT}" >&2; exit 1; }
  TOKEN="$(printf '%s' "${CREATE_OUT}" | grep -oE 'gbrain_[0-9a-f]{64}' | head -n1)"
  [[ -n "${TOKEN}" ]] || { echo "ERROR: could not parse minted token from:" >&2; echo "${CREATE_OUT}" >&2; exit 1; }
fi

# ── Helper: call a GBrain MCP tool, return the unwrapped op result text ─────
mcp_call() {
  # $1 = JSON-RPC body. Strips the SSE `data: ` framing GBrain emits.
  docker exec "${BRAIN_SVC}" curl -s -X POST http://localhost:3131/mcp \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "$1" | sed 's/^data: //; /^event:/d; /^$/d'
}

echo "==> put_page ${SMOKE_SLUG}"
mcp_call "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"put_page\",\"arguments\":{\"slug\":\"${SMOKE_SLUG}\",\"content\":\"${SMOKE_CONTENT}\"}}}" >/dev/null

echo "==> get_page ${SMOKE_SLUG}"
GET_OUT="$(mcp_call "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"get_page\",\"arguments\":{\"slug\":\"${SMOKE_SLUG}\"}}}")"
echo "${GET_OUT}" | grep -q "${SMOKE_SLUG}" || { echo "FAIL: get_page did not return the page." >&2; echo "${GET_OUT}" >&2; exit 1; }

echo "==> search (keyword) for the unique marker"
SEARCH_OUT="$(mcp_call "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"search\",\"arguments\":{\"query\":\"${MARKER}\"}}}")"

echo "==> query (semantic) for the smoke probe"
QUERY_OUT="$(mcp_call "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"query\",\"arguments\":{\"query\":\"GBrain smoke probe unique retrieval marker ${MARKER}\"}}}")"

FAILED=0
if echo "${SEARCH_OUT}" | grep -q "${SMOKE_SLUG}"; then
  echo "  PASS  search returned ${SMOKE_SLUG}"
else
  echo "  FAIL  search returned no match for ${SMOKE_SLUG}" >&2
  echo "        raw: ${SEARCH_OUT}" >&2
  FAILED=1
fi
if echo "${QUERY_OUT}" | grep -q "${SMOKE_SLUG}"; then
  echo "  PASS  query returned ${SMOKE_SLUG}"
else
  echo "  FAIL  query returned no match for ${SMOKE_SLUG}" >&2
  echo "        raw: ${QUERY_OUT}" >&2
  FAILED=1
fi

# ── Cleanup: delete the probe page so it never pollutes real retrieval ──────
mcp_call "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"tools/call\",\"params\":{\"name\":\"delete_page\",\"arguments\":{\"slug\":\"${SMOKE_SLUG}\"}}}" >/dev/null 2>&1 || true

if [[ "${FAILED}" -ne 0 ]]; then
  echo "" >&2
  echo "GBrain retrieval smoke test FAILED. If the slug above starts with a" >&2
  echo "hard-excluded prefix (test/ archive/ attachments/ .raw/) that's the cause" >&2
  echo "— see the GOTCHA banner at the top of this script." >&2
  exit 1
fi

echo ""
echo "GBrain retrieval smoke test PASSED — put -> get -> search -> query all OK."
