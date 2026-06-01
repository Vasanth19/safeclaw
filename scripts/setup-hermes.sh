#!/usr/bin/env bash
# setup-hermes.sh — install Hermes (Nous Research agent) natively into /opt/hermes
# on a fresh orgo box, plus the cron dependency (croniter) and an optional
# pre-build of the dashboard web bundle for Hermes 0.11.
#
# This is the single load-bearing install of Hermes itself for the orgo native
# (no-Docker) stack. Run it from Step 1 of ORGO-CLIENT-TEMPLATE.md. Everything
# downstream (profiles, gateway, dashboard, dream cron, Console /api/chat)
# depends on `which hermes` resolving after this script completes.
#
# Usage:
#   bash /opt/safeclaw/scripts/setup-hermes.sh
#
# Env knobs:
#   HERMES_VERSION   pin the Hermes version (default: 0.15.1). 0.11 is the FLOOR
#                    (first version with the in-process cron scheduler we need
#                    for nightly dreaming). 0.15+ adds dashboard `--skip-build`.
#   HERMES_PREBUILD_WEB=1  force the `/opt/hermes/web` vite pre-build even on
#                    0.15+ (on <0.15 the pre-build runs automatically because
#                    `--skip-build` is unavailable there).

set -euo pipefail

HERMES_VERSION="${HERMES_VERSION:-0.15.1}"

echo "[setup-hermes] installing Hermes ${HERMES_VERSION} ..."

# Node 20 must already be on PATH (Step 1 installs the static tarball + symlinks);
# the dashboard web bundle needs Node 20+ (vite 7).
command -v node >/dev/null 2>&1 || { echo "FATAL: node not on PATH — run the Node 20 install in Step 1 first"; exit 1; }

# ── 1. Hermes itself (official installer, pinned version) ──────────────────
# Reference: legacy orgo/ORGO-DEPLOY.md — `curl … hermes-agent.nousresearch.com/install.sh | bash`.
# We pass the version through to pin it rather than tracking latest.
export HERMES_INSTALL_DIR="${HERMES_INSTALL_DIR:-/opt/hermes}"
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | HERMES_VERSION="${HERMES_VERSION}" bash

# Make hermes globally resolvable in every fresh shell (orgo /bash spawns a new
# shell per call — do NOT rely on a PATH export persisting).
#
# ⚠️ SYMLINK PATH FIX (live-install issue 3): the Nous installer puts the binary at
#   /opt/hermes/venv/bin/hermes   (and ~/.local/bin/hermes)
# NOT at /opt/hermes/bin/hermes. Probe the real locations in priority order.
HERMES_BIN=""
for cand in \
  "${HERMES_INSTALL_DIR}/venv/bin/hermes" \
  "${HOME}/.local/bin/hermes" \
  "${HERMES_INSTALL_DIR}/bin/hermes"; do
  if [ -x "$cand" ]; then HERMES_BIN="$cand"; break; fi
done
if [ -n "$HERMES_BIN" ]; then
  ln -sf "$HERMES_BIN" /usr/local/bin/hermes
else
  echo "FATAL: could not find the hermes binary in venv/bin, ~/.local/bin, or bin/"; exit 1
fi

command -v hermes >/dev/null 2>&1 || { echo "FATAL: hermes not on PATH after install"; exit 1; }
echo "[setup-hermes] hermes resolved at: $(command -v hermes) -> $HERMES_BIN"
hermes --version

# ── 2. Cron dependency — the in-process scheduler needs croniter ───────────
# Step 4 (gbrain dream nightly cron) will not fire without this.
pip3 install --break-system-packages croniter

# ── 2b. base_url fix (live-install issues 15 + 20) ─────────────────────────
# Hermes 0.15.1's installer ships `model.base_url: https://openrouter.ai/api/v1`
# in the DEFAULT config. Setting model.provider=ollama does NOT change it, and the
# provider resolver then demands an OPENROUTER_API_KEY for chat. Repoint the
# DEFAULT profile's base_url at Ollama Cloud here so the default --tui gateway
# works; reader/actor profiles are repointed in Step 3 (they copy from default,
# but we set them explicitly there too). Best-effort — never abort the install.
HERMES_HOME="${HERMES_HOME:-/root/.hermes}" hermes config set model.base_url https://ollama.com/v1 2>/dev/null \
  && echo "[setup-hermes] default model.base_url -> https://ollama.com/v1" \
  || echo "[setup-hermes] WARN: could not preset model.base_url (set it in Step 1/3)"

# ── 3. Hermes 0.11 dashboard web bundle pre-build (no --skip-build there) ──
HERMES_MAJMIN="$(hermes --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)"
NEEDS_PREBUILD=0
case "${HERMES_MAJMIN}" in
  0.11|0.12|0.13|0.14) NEEDS_PREBUILD=1 ;;
esac
[ "${HERMES_PREBUILD_WEB:-0}" = "1" ] && NEEDS_PREBUILD=1

if [ "${NEEDS_PREBUILD}" = "1" ] && [ -d "${HERMES_INSTALL_DIR}/web" ]; then
  echo "[setup-hermes] Hermes ${HERMES_MAJMIN} has no --skip-build — pre-building /opt/hermes/web once ..."
  ( cd "${HERMES_INSTALL_DIR}/web" && npm install && npm run build )
fi

echo "[setup-hermes] DONE — hermes $(hermes --version), croniter installed."
