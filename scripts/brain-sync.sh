#!/usr/bin/env bash
# SafeClaw — periodic brain sync
#
# Wrapper around scripts/bootstrap-brain.sh meant for cron. Adds:
#   - flock so two cron firings can't run concurrently (Composio MCP rate limits
#     are gentle but a stuck run + an overlapping run is messy state).
#   - timestamped logs to logs/brain-sync.log so failures are diagnosable.
#   - a small days-back window (1) since the bootstrap script's watermark in
#     brain/.bootstrap-state.json already filters to only-newer-than-last-run.
#
# The script bootstrap-brain.sh itself handles:
#   - Composio MCP fetch with the SSE-parser fix
#   - Incremental: messages with received_at <= last watermark are skipped
#   - Upsert into brain/People/, brain/Companies/, postgres-obs.entities
#
# Suggested cron line (every 30 min):
#   */30 * * * * /Users/vasanth/Clients/rspur/ai-assistant/scripts/brain-sync.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${REPO_ROOT}/logs"
LOG_FILE="${LOG_DIR}/brain-sync.log"
LOCK_DIR="${REPO_ROOT}/.brain-sync.lock"

mkdir -p "${LOG_DIR}"

# Portable lock: mkdir is atomic on POSIX filesystems (works on both macOS
# and Linux without needing flock, which macOS doesn't ship). If the lock
# directory exists, a previous run is still active — exit silently and let
# the next cron firing try again. Stale locks older than 1h are cleared so
# a crashed run doesn't deadlock the schedule forever.
if [ -d "${LOCK_DIR}" ]; then
    # Stale-lock recovery: lock dirs older than 1h are presumed dead.
    if [ -n "$(find "${LOCK_DIR}" -maxdepth 0 -mmin +60 2>/dev/null)" ]; then
        rmdir "${LOCK_DIR}" 2>/dev/null || true
    else
        printf '%s [skip] previous sync still running\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${LOG_FILE}"
        exit 0
    fi
fi
if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    printf '%s [skip] could not acquire lock\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${LOG_FILE}"
    exit 0
fi
trap 'rmdir "${LOCK_DIR}" 2>/dev/null || true' EXIT

{
    printf '\n──── %s ── brain-sync start\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    cd "${REPO_ROOT}"
    # --days 1 keeps the window narrow; the watermark in bootstrap-state.json
    # is what actually controls "only fetch newer than last successful run".
    bash scripts/bootstrap-brain.sh --days 1
    printf '──── %s ── brain-sync done (rc=%s)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$?"
} >> "${LOG_FILE}" 2>&1
