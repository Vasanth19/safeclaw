#!/bin/sh
# gbrain-entrypoint.sh — pre-flight checks before starting gbrain serve
#
# PGLite mode: clear stale lock (container PID 1 looks alive via host launchd).
# Postgres mode: no lock file — connect directly.

set -e

GBRAIN_HOME="${GBRAIN_HOME:-/root}"
LOCK_DIR="${GBRAIN_HOME}/.gbrain/brain.pglite/.gbrain-lock"

if [ -f "${LOCK_DIR}/lock" ]; then
  echo "[gbrain-entrypoint] Removing stale PGLite lock: ${LOCK_DIR}/lock"
  rm -rf "${LOCK_DIR}"
fi

exec bun run /app/src/cli.ts "$@"
