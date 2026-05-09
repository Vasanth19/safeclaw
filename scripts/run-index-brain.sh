#!/usr/bin/env bash
# Run the brain indexer via docker compose (one-shot, no cron).
# Usage: bash scripts/run-index-brain.sh [--verbose] [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

set -o allexport
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env"
set +o allexport

INTERNAL_DB_URL="postgresql://${POSTGRES_OBS_USER}:${POSTGRES_OBS_PASSWORD}@postgres-obs:5432/${POSTGRES_OBS_DB}"

docker compose -f "${REPO_ROOT}/docker-compose.yml" run --rm \
  --no-deps \
  --entrypoint "" \
  -T \
  -e BRAIN_OBS_DATABASE_URL="${INTERNAL_DB_URL}" \
  -e BRAIN_USER_KEY="${BRAIN_USER_KEY:-primary}" \
  -v "${REPO_ROOT}:/repo:rw" \
  -v "${REPO_ROOT}/../evolving-brain:/repo/brain:rw" \
  embedder \
  python /repo/scripts/index-brain.py --brain-dir /repo/brain "$@"
