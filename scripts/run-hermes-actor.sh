#!/usr/bin/env bash
# run-hermes-actor.sh — launchd wrapper for the local Hermes actor process.
# Sources .env from the repo, sets HERMES_HOME, then execs hermes.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/.safeclaw/hermes-venv"
export HERMES_HOME="$HOME/.safeclaw/actor-home"

# launchd has a minimal PATH — extend it to include all required runtimes.
export PATH="/opt/homebrew/bin:/Users/vasanth/.local/bin:/Users/vasanth/.bun/bin:/usr/local/bin:$PATH"

# Load all env vars from repo .env
set -a
# shellcheck source=/dev/null
source "$REPO/.env"
set +a

# Model / inference overrides (same as Docker env block)
export HERMES_INFERENCE_PROVIDER=ollama-cloud
export OLLAMA_BASE_URL=http://localhost:11435/v1
export HERMES_DEFAULT_MODEL=glm-5.1:cloud

exec "$VENV/bin/hermes" gateway run --accept-hooks
