#!/usr/bin/env bash
# SafeClaw — bootstrap brain
#
# Seeds the Brain layer by scraping the last 90 days of sent mail, extracting
# entities + style samples, and populating user_profile from brain/user.soul.md.
#
# PREREQ: Gmail OAuth (Phase H of DEPLOY-RUNBOOK) must be complete. This script
# will fail fast if the OAuth credentials aren't present.
#
# Usage:
#   scripts/bootstrap-brain.sh [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo "SafeClaw Brain bootstrap"
echo "========================"
echo
echo "This will:"
echo "  1. Load brain/user.soul.md into user_profile.soul_md on postgres-obs."
echo "  2. Scrape the last 90 days of sent mail from the configured Gmail account."
echo "  3. Extract entities, facts, and style samples via the configured LLM."
echo "  4. Let the embedder pick up new rows on its next poll cycle."
echo
echo "Prerequisites:"
echo "  - docker compose stack is UP"
echo "  - Nango Gmail OAuth is complete (Phase H of DEPLOY-RUNBOOK.md)"
echo "  - brain/user.soul.md exists (copy from user.soul.md.template)"
echo

# ── Guard: Gmail OAuth must be configured before running ─────────────────────
if ! grep -qE '^GOOGLE_CLIENT_ID=[^_]' "${REPO_ROOT}/.env" 2>/dev/null; then
  echo "ERROR: GOOGLE_CLIENT_ID in .env still looks like a placeholder."
  echo "       Complete Phase H (OAuth setup) before running bootstrap."
  exit 2
fi

if [[ ! -f "${REPO_ROOT}/brain/user.soul.md" ]]; then
  echo "ERROR: brain/user.soul.md not found."
  echo "       cp brain/user.soul.md.template brain/user.soul.md   # then edit it"
  exit 2
fi

# ── The actual bootstrap (Node script) ───────────────────────────────────────
# TODO(bootstrap-brain.ts): implement Gmail sent-mail scrape + entity extraction.
# Once implemented, invoke via:
#   node "${REPO_ROOT}/scripts/bootstrap-brain.ts"
# or equivalent tsx/ts-node invocation.

echo "NOTE: scripts/bootstrap-brain.ts is not yet implemented."
echo "      This script has verified prerequisites are in place."
echo "      Re-run after the Node implementation lands."
echo
echo "Exiting 0 — prerequisites look good; nothing else to do yet."
exit 0
