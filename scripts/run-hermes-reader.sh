#!/usr/bin/env bash
# run-hermes-reader.sh — launchd wrapper for the local Hermes reader process.
# Sources .env from the repo, sets HERMES_HOME, then execs hermes.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/.safeclaw/hermes-venv"
export HERMES_HOME="$HOME/.safeclaw/reader-home"

# launchd has a minimal PATH — extend it to include all required runtimes.
export PATH="/opt/homebrew/bin:/Users/vasanth/.local/bin:/Users/vasanth/.bun/bin:/usr/local/bin:$PATH"

# Load all env vars from repo .env
set -a
# shellcheck source=/dev/null
source "$REPO/.env"
set +a

# Save the real bot token before blanking — the slack_native MCP needs it
# via SLACK_MCP_BOT_TOKEN (matches reader-hermes-local.yaml mcp_servers config).
export SLACK_MCP_BOT_TOKEN="${SLACK_BOT_TOKEN}"

# Reader is a background ingest agent — it must NOT open a second platform
# socket (Slack Socket Mode, Telegram long-poll). Blank the tokens so Hermes
# skips platform adapter startup.
export TELEGRAM_BOT_TOKEN=""
export SLACK_BOT_TOKEN=""
export SLACK_APP_TOKEN=""

# Model / inference overrides (same as Docker env block)
export HERMES_INFERENCE_PROVIDER=ollama-cloud
export OLLAMA_BASE_URL=http://localhost:11435/v1
export HERMES_DEFAULT_MODEL=glm-5.1:cloud

exec "$VENV/bin/hermes" gateway run --accept-hooks
