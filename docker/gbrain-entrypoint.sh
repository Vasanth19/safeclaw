#!/bin/sh
# gbrain-entrypoint.sh — clear stale PGLite lock before starting
# The lock uses the PID of the process that acquired it. In a container,
# that PID is always 1. On the host (bind-mount), PID 1 (launchd/init)
# is always alive, so gbrain's stale-lock detector never fires. We clear
# it explicitly on container startup to avoid "Timed out waiting for PGLite lock."

set -e

# Resolve the brain data dir from GBRAIN_HOME (default: /root/.gbrain)
GBRAIN_HOME="${GBRAIN_HOME:-/root}"
LOCK_DIR="${GBRAIN_HOME}/.gbrain/brain.pglite/.gbrain-lock"

if [ -f "${LOCK_DIR}/lock" ]; then
  echo "[gbrain-entrypoint] Removing stale PGLite lock: ${LOCK_DIR}/lock"
  rm -rf "${LOCK_DIR}"
fi

exec bun run /app/src/cli.ts "$@"
