#!/usr/bin/env bash
# SafeClaw — OAuth Setup Script
# Walks the operator through authorizing all OAuth connections in Nango.
# Run AFTER `docker compose up -d` and the stack is healthy.
#
# Usage: bash scripts/setup-oauth.sh

set -euo pipefail

# ── Required tools ────────────────────────────────────────────────────────────
for cmd in docker curl jq; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: '$cmd' is required but not found. Please install it and re-run." >&2
    exit 1
  fi
done

# ── Color helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
step()    { echo -e "\n${BOLD}── Step $* ─────────────────────────────────────────────────${NC}"; }

pause() {
  echo ""
  read -rp "Press Enter to continue to the next step..."
}

# ── Verify Nango is running ───────────────────────────────────────────────────
step "0: Verify Nango is healthy"

NANGO_URL="http://localhost:3003"

info "Checking 'docker compose ps' for Nango..."
if ! docker compose ps --format json 2>/dev/null | jq -r '.[].Name' 2>/dev/null | grep -q "nango"; then
  # Fallback for older docker compose versions
  if ! docker compose ps 2>/dev/null | grep -q "nango"; then
    error "Nango container is not running. Run 'docker compose up -d' first."
    exit 1
  fi
fi
success "Nango container found in compose stack."

info "Checking Nango health endpoint..."
MAX_TRIES=12
WAIT=5
for i in $(seq 1 $MAX_TRIES); do
  if curl -sf "${NANGO_URL}/health" -o /dev/null; then
    success "Nango is healthy at ${NANGO_URL}"
    break
  fi
  if [ "$i" -eq "$MAX_TRIES" ]; then
    error "Nango did not respond after $((MAX_TRIES * WAIT))s. Check: docker compose logs nango"
    exit 1
  fi
  info "Waiting for Nango... attempt $i/$MAX_TRIES"
  sleep "$WAIT"
done

echo ""
echo -e "${BOLD}Nango Dashboard:${NC} ${NANGO_URL}"
echo ""
warn "You will need to complete the following OAuth flows in the Nango dashboard."
warn "Keep this terminal open — it will guide you through each integration."
pause

# ── Integration 1: Gmail Readonly ─────────────────────────────────────────────
step "1: Gmail Read-Only (hermes-reader — 3 inboxes)"

cat <<EOF

${BOLD}Integration name to create:${NC} gmail-readonly
${BOLD}Provider:${NC} Google
${BOLD}OAuth scopes:${NC}
  - https://www.googleapis.com/auth/gmail.readonly
  - https://www.googleapis.com/auth/gmail.labels

${BOLD}Steps in Nango Dashboard:${NC}
  1. Go to ${NANGO_URL}
  2. Click "Integrations" → "Add Integration"
  3. Search for "Google" and select it
  4. Integration ID: gmail-readonly
  5. Paste your Google OAuth Client ID and Secret from .env
  6. Set scopes to the two listed above
  7. Click "Save"

${BOLD}Then add 3 connections (one per inbox):${NC}
  Connection 1 ID: jake-rspur        → Authorize jake@rspur.com
  Connection 2 ID: jake-panhandle    → Authorize jake@panhandlehomebuyer.com
  Connection 3 ID: jake-rockingspur  → Authorize jake@rockingspurhomesales.com

${BOLD}For each connection:${NC}
  - Click "Connections" → "Add Connection"
  - Select integration: gmail-readonly
  - Enter the Connection ID above
  - Complete the Google OAuth consent screen
  - Verify the connection shows "Active"

EOF
pause

# ── Integration 2: Gmail Draft ────────────────────────────────────────────────
step "2: Gmail Draft (hermes-actor — same 3 inboxes)"

cat <<EOF

${BOLD}Integration name to create:${NC} gmail-draft
${BOLD}Provider:${NC} Google
${BOLD}OAuth scope:${NC}
  - https://www.googleapis.com/auth/gmail.compose

${BOLD}Steps:${NC}
  1. Click "Integrations" → "Add Integration"
  2. Integration ID: gmail-draft
  3. Same Google OAuth Client ID and Secret
  4. Scope: gmail.compose ONLY — do NOT add gmail.send
  5. Save

${BOLD}Add 3 connections with the same IDs:${NC}
  jake-rspur / jake-panhandle / jake-rockingspur
  (Same accounts as gmail-readonly — re-authorize for the compose scope)

EOF
pause

# ── Integration 3: Google Drive ───────────────────────────────────────────────
step "3: Google Drive File (hermes-actor)"

cat <<EOF

${BOLD}Integration name to create:${NC} google-drive-file
${BOLD}Provider:${NC} Google
${BOLD}OAuth scope:${NC}
  - https://www.googleapis.com/auth/drive.file

${BOLD}IMPORTANT:${NC} drive.file scope grants access ONLY to files created by or explicitly
opened with this OAuth client. It cannot read Jake's entire Drive — only the
app-owned folder. This is intentional and must NOT be changed to drive or drive.readonly.

${BOLD}Steps:${NC}
  1. Click "Integrations" → "Add Integration"
  2. Integration ID: google-drive-file
  3. Same Google OAuth Client ID and Secret
  4. Scope: drive.file ONLY
  5. Save

${BOLD}Add 1 connection:${NC}
  Connection ID: jake-drive
  Authorize as: the primary Jake McKinney Google account

EOF
pause

# ── Integration 4: Slack Bot ──────────────────────────────────────────────────
step "4: Slack Bot (hermes-reader + hermes-actor)"

cat <<EOF

${BOLD}Integration name to create:${NC} slack-bot
${BOLD}Provider:${NC} Slack
${BOLD}Bot Token Scopes:${NC}
  - channels:read
  - channels:history
  - chat:write
  - chat:write.public

${BOLD}Prerequisites (do this in Slack App Dashboard first):${NC}
  1. Go to https://api.slack.com/apps → Create New App → From Scratch
  2. App name: SafeClaw
  3. Workspace: Rocking Spur Homes Slack workspace
  4. Under "OAuth & Permissions" → add the 4 bot token scopes above
  5. Under "Socket Mode" → Enable Socket Mode → generate App-Level Token
     - Token name: safeclaw-socket
     - Scope: connections:write
     - Copy the xapp-... token → paste into .env as SLACK_APP_TOKEN
  6. Install app to workspace → copy Bot User OAuth Token (xoxb-...) → paste into .env as SLACK_BOT_TOKEN
  7. Invite SafeClaw bot to #safeclaw-review channel: /invite @SafeClaw

${BOLD}Then in Nango Dashboard:${NC}
  1. Click "Integrations" → "Add Integration"
  2. Integration ID: slack-bot
  3. Paste Slack Client ID and Secret (from Slack App Dashboard → App Credentials)
  4. Scopes: channels:read channels:history chat:write chat:write.public
  5. Save

${BOLD}Add 1 connection:${NC}
  Connection ID: rspur-slack
  Authorize as: Rocking Spur Homes workspace admin

EOF
pause

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
success "OAuth setup walkthrough complete."
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo "  1. Verify all connections show 'Active' in the Nango dashboard."
echo "  2. Update .env with SLACK_BOT_TOKEN, SLACK_APP_TOKEN, and SLACK_REVIEW_CHANNEL_ID."
echo "  3. Run database migrations:"
echo "     docker compose exec postgres-obs psql -U \$POSTGRES_OBS_USER -d safeclaw_obs -f /migrations/001_obs_schema.sql"
echo "     docker compose exec postgres-tasks psql -U \$POSTGRES_TASKS_USER -d safeclaw_tasks -f /migrations/002_task_schema.sql"
echo "  4. Run Phase 1 verification:"
echo "     bash scripts/verify-stack.sh --phase 1"
echo ""
