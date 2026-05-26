#!/bin/sh
# Pre-start init for hermes containers.
# Runs as root before tini drops privileges to the hermes user.
# chmod 666 opens the docker socket so hermes (uid 10000) can run
# `docker exec` for stdio MCP servers (slack_native, brain_api, tasks_api).
chmod 666 /var/run/docker.sock 2>/dev/null || true
chown -R 10000:10000 /opt/data/ 2>/dev/null || true

# Translate the config's `schedules:` block into real Hermes cron jobs.
# This Hermes version's gateway config loader ignores `schedules:`, so without
# this step the ingestion cron never registers and the brain stays empty.
# Run as the hermes user (uid 10000) so $HERMES_HOME/cron/jobs.json is owned
# correctly, with HERMES_HOME pinned to the gateway's data dir. Best-effort:
# a failure here must never block the agent from booting (the script itself
# exits 0 on error, and the `||` guard catches an interpreter/gosu failure).
CRON_SYNC=/safeclaw/cron-sync.py
CRON_CONFIG=/safeclaw/config-template/config.yaml
if [ -f "$CRON_SYNC" ] && [ -f "$CRON_CONFIG" ]; then
    echo "[hermes-init] syncing config schedules: -> Hermes cron jobs"
    HERMES_HOME=/opt/data gosu hermes /opt/hermes/.venv/bin/python "$CRON_SYNC" "$CRON_CONFIG" \
        || echo "[hermes-init] cron-sync failed (non-fatal) — scheduled ingestion may not run"
fi

exec /usr/bin/tini -g -- /opt/hermes/docker/safeclaw-entrypoint.sh "$@"
