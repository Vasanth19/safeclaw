#!/usr/bin/env bash
# ─── safeclaw-brain entrypoint ───────────────────────────────────────────────
# Idempotent bringup for the GBrain engine:
#   1. require DATABASE_URL (Postgres backend — static bearer tokens live in
#      the access_tokens table, which is Postgres-only).
#   2. GBRAIN_HOME=/data/safeclaw-brain → config + brain live under
#      ${GBRAIN_HOME}/.gbrain (gbrain appends `.gbrain` itself).
#   3. first boot only: git init the brain home + `gbrain init ...`.
#   4. every boot: `gbrain apply-migrations --yes` (no-op if already current).
#   5. exec the HTTP server on :3131 (internal docker network only).
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required (Postgres backend for access_tokens)}"

export GBRAIN_HOME="${GBRAIN_HOME:-/data/safeclaw-brain}"

# gbrain resolves its config/brain under ${GBRAIN_HOME}/.gbrain.
BRAIN_DIR="${GBRAIN_HOME}/.gbrain"
CONFIG_FILE="${BRAIN_DIR}/config.json"

mkdir -p "${GBRAIN_HOME}"

if [ -f "${CONFIG_FILE}" ]; then
  echo "[safeclaw-brain] already initialized at ${BRAIN_DIR} — skipping init."
else
  echo "[safeclaw-brain] first boot — initializing brain at ${BRAIN_DIR}"
  mkdir -p "${BRAIN_DIR}"
  # GBrain repos are git-backed: the brain home must be a git working tree.
  if [ ! -d "${BRAIN_DIR}/.git" ]; then
    git init -q "${BRAIN_DIR}"
  fi
  # Local Ollama embeddings: nomic-embed-text (768 dims, no API key). The host
  # must `ollama pull nomic-embed-text`; OLLAMA_BASE_URL points at the host.
  gbrain init \
    --embedding-model ollama:nomic-embed-text \
    --embedding-dimensions 768
fi

echo "[safeclaw-brain] applying migrations..."
gbrain apply-migrations --yes

echo "[safeclaw-brain] starting HTTP server on :3131 (bind 0.0.0.0, internal only)"
exec gbrain serve --http --port 3131 --bind 0.0.0.0
