#!/usr/bin/env bash
# install-local-hermes.sh — one-time setup to run Hermes natively on macOS.
# Run from anywhere; uses the repo root relative to this script.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL="$HOME/.safeclaw"
MCP="$LOCAL/mcp-tools"
VENV="$LOCAL/hermes-venv"

echo "==> Creating local directory tree"
mkdir -p "$LOCAL"/{reader-home,actor-home}
mkdir -p "$LOCAL"/mcp-tools
mkdir -p "$LOCAL"/attachments/{staging,processed}

echo "==> Installing Hermes venv at $VENV"
uv venv "$VENV" --python 3.13
uv pip install --python "$VENV/bin/python" --no-cache-dir \
  -e "$REPO/vendor/hermes-agent[all]"

echo "==> Installing Playwright Chromium"
"$VENV/bin/playwright" install chromium

echo "==> Building slack-api MCP"
rsync -a --delete "$REPO/mcp-tools/slack-api/" "$MCP/slack-api/"
(cd "$MCP/slack-api" && npm install --no-audit --prefer-offline && npm run build && npm prune --omit=dev)

echo "==> Building tasks-api MCP"
rsync -a --delete "$REPO/mcp-tools/tasks-api/" "$MCP/tasks-api/"
(cd "$MCP/tasks-api" && npm install --no-audit --prefer-offline && npm run build && npm prune --omit=dev)

echo "==> Installing drive-api MCP"
rsync -a --delete "$REPO/mcp-tools/drive-api/" "$MCP/drive-api/"
uv venv "$MCP/drive-api/.venv" --python 3.13
uv pip install --python "$MCP/drive-api/.venv/bin/python" --no-cache-dir \
  -r "$MCP/drive-api/requirements.txt"

echo "==> Seeding reader HERMES_HOME"
READER_HOME="$LOCAL/reader-home"
mkdir -p "$READER_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}
cp "$REPO/config/reader-hermes-local.yaml" "$READER_HOME/config.yaml"

echo "==> Seeding actor HERMES_HOME"
ACTOR_HOME="$LOCAL/actor-home"
mkdir -p "$ACTOR_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}
cp "$REPO/config/actor-hermes-local.yaml" "$ACTOR_HOME/config.yaml"

echo "==> Syncing bundled Hermes skills"
HERMES_SRC="$REPO/vendor/hermes-agent"
HERMES_HOME="$READER_HOME" "$VENV/bin/python" "$HERMES_SRC/tools/skills_sync.py"
HERMES_HOME="$ACTOR_HOME"  "$VENV/bin/python" "$HERMES_SRC/tools/skills_sync.py"

echo ""
echo "Done. Next:"
echo "  ./scripts/install-launchd.sh   # register + start the daemons"
echo "  docker compose stop hermes-reader hermes-actor   # retire Docker versions"
echo ""
echo "hermes-chat alias will point to the local actor automatically."
