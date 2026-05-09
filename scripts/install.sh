#!/usr/bin/env bash
# SafeClaw — one-line installer (Option C)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Vasanth19/safeclaw/main/scripts/install.sh | bash
#
# What it does:
#   1. Clones the repo to ~/safeclaw/
#   2. Copies .env.example → .env
#   3. Generates secrets (DB passwords, JWT, agent JWT)
#   4. Prints next steps (fill in .env, start the stack)

set -euo pipefail

INSTALL_DIR="${SAFECLAW_INSTALL_DIR:-$HOME/safeclaw}"
REPO_URL="https://github.com/Vasanth19/safeclaw.git"

echo "========================================"
echo "  SafeClaw AI Assistant Installer"
echo "========================================"
echo

# ── 1. Clone the repo ─────────────────────────────────────────────────────
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    echo "SafeClaw already installed at ${INSTALL_DIR}"
    echo "  Run 'cd ${INSTALL_DIR}' and 'git pull' to update."
    exit 0
fi

echo "[1/4] Cloning SafeClaw into ${INSTALL_DIR}..."
git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
cd "${INSTALL_DIR}"

# ── 2. Seed .env ──────────────────────────────────────────────────────────
echo "[2/4] Setting up environment..."
cp .env.example .env

# ── 3. Generate secrets ───────────────────────────────────────────────────
echo "[3/4] Generating secrets..."
bash scripts/init-secrets.sh

# ── 4. Done ────────────────────────────────────────────────────────────────
echo "[4/4] Done!"
echo
echo "Next steps:"
echo "  1. cd ${INSTALL_DIR}"
echo "  2. Edit .env — fill in every __FILL_IN__ value:"
echo "       - Composio API key + connected account IDs"
echo "       - Slack bot token + app token"
echo "       - Telegram bot token (optional, v1 only)"
echo "       - Firecrawl API key (optional, for web search)"
echo "  3. docker compose up -d"
echo "  4. bash scripts/verify-stack.sh --phase 0"
echo "  5. bash scripts/bootstrap-brain.sh"
echo
echo "For the full walkthrough:  https://github.com/Vasanth19/safeclaw/blob/main/FIRST-RUN.md"
echo "For day-2 operations:       https://github.com/Vasanth19/safeclaw/blob/main/DEPLOY-RUNBOOK.md"
echo
