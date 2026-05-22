#!/bin/sh
# Pre-start init for hermes containers.
# Runs as root before tini drops privileges to the hermes user.
# chmod 666 opens the docker socket so hermes (uid 10000) can run
# `docker exec` for stdio MCP servers (slack_native, brain_api, tasks_api).
chmod 666 /var/run/docker.sock 2>/dev/null || true
chown -R 10000:10000 /opt/data/ 2>/dev/null || true
exec /usr/bin/tini -g -- /opt/hermes/docker/safeclaw-entrypoint.sh "$@"
