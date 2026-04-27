#!/usr/bin/env bash
# SafeClaw — Hostinger VPS bootstrap script.
#
# Bootstraps a fresh Ubuntu 22.04+ host into a working SafeClaw deployment.
# Idempotent: re-running the script is safe — already-applied steps are
# detected and skipped.
#
# What it does (in order):
#   1. apt update + base packages (curl, git, gnupg, ufw, caddy, ...)
#   2. Install Docker Engine + Compose plugin from get.docker.com
#   3. Lock down firewall to ports 22, 80, 443
#   4. Clone the SafeClaw repo to /opt/safeclaw (or fast-forward if present)
#   5. Pull pre-built images from GHCR (docker compose pull)
#   6. Write /etc/caddy/Caddyfile that reverse-proxies the chosen domain
#      to localhost:8080 and lets Caddy fetch a Let's Encrypt cert
#   7. Install the Ollama daemon on the host (so containers can route
#      :cloud models through host.docker.internal:11434)
#   8. Start ONLY the onboarding webapp (other services boot when the
#      customer submits the setup form — they need customer credentials)
#   9. Print the URL to send to the customer + an SSH cheat-sheet
#  10. Health-check https://<DOMAIN>/health
#
# The customer brings their own Composio API key, user_id, and the two
# MCP server URLs through the onboarding form (Step 2). Composio is the
# customer's account — they connected Gmail / Drive / Slack to it.
# The operator does NOT preload Composio creds anymore.
#
# Usage:
#   bash scripts/provision-vps.sh customer1.safeclaw.com hello@example.com
#
# Args:
#   $1  Domain name. A record must already point at this VPS.
#   $2  Admin email — used as the ACME contact for Let's Encrypt.
#
# Run as root (this is the standard Hostinger SSH context).

set -euo pipefail

# ─── Args + sanity ─────────────────────────────────────────────────────────
DOMAIN="${1:-}"
ADMIN_EMAIL="${2:-}"

usage() {
  cat <<USAGE >&2
Usage:
  bash scripts/provision-vps.sh <domain> <admin-email>

Example:
  bash scripts/provision-vps.sh customer1.safeclaw.com hello@example.com

Required positional args:
  <domain>       fully qualified domain (A record must already point at this VPS)
  <admin-email>  ACME contact for Let's Encrypt

Composio setup is customer-side: the customer enters their own
COMPOSIO_API_KEY, COMPOSIO_USER_ID, and the two MCP URLs via Step 2 of
the /setup form. The operator does not need to preload anything.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -z "${DOMAIN}" || -z "${ADMIN_EMAIL}" ]]; then
  usage
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: provision-vps.sh must run as root. Try:  sudo bash $0 $* " >&2
  exit 1
fi

REPO_URL="https://github.com/Vasanth19/safeclaw.git"
INSTALL_DIR="/opt/safeclaw"
TOTAL_STEPS=10
STEP=0

step() {
  STEP=$((STEP + 1))
  echo
  echo "[${STEP}/${TOTAL_STEPS}] $*"
  echo "─────────────────────────────────────────────────────────────"
}

fail() {
  local what="$1"
  local hint="${2:-Re-run the script after fixing the issue. provision-vps.sh is idempotent.}"
  cat <<FAIL >&2

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PROVISIONING FAILED at step ${STEP}/${TOTAL_STEPS}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  What broke:
    ${what}

  What to try:
    ${hint}

  After fixing, re-run:
    bash scripts/provision-vps.sh ${DOMAIN} ${ADMIN_EMAIL}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FAIL
  exit 1
}

trap 'fail "Unexpected error on line ${LINENO}." "Check the output above for the failing command."' ERR

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  SafeClaw VPS provisioning"
echo "  Domain : ${DOMAIN}"
echo "  Email  : ${ADMIN_EMAIL}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ─── 1. System setup ───────────────────────────────────────────────────────
step "Updating apt and installing base packages"
export DEBIAN_FRONTEND=noninteractive

apt-get update -y \
  || fail "apt-get update failed." "Check the VPS has network access and try again."

apt-get upgrade -y \
  || fail "apt-get upgrade failed." "Free up disk space if /var or / is full, then re-run."

# Caddy lives in a separate apt repo; add it once.
if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https \
    || fail "Could not install Caddy prerequisites."
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
fi

apt-get install -y \
  curl git gnupg lsb-release ca-certificates ufw caddy jq python3 \
  || fail "Base package install failed." "Inspect 'apt-get install' output above for the offending package."

# ─── 2. Docker Engine + Compose v2 ─────────────────────────────────────────
step "Installing Docker Engine + Compose v2"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh \
    || fail "Could not download get.docker.com installer."
  sh /tmp/get-docker.sh \
    || fail "Docker installer failed." "Check /tmp/get-docker.sh output. Your kernel must be >= 5.4."
  rm -f /tmp/get-docker.sh
else
  echo "Docker already installed: $(docker --version)"
fi

systemctl enable --now docker

# Verify compose v2 is present (get.docker.com installs the plugin).
if ! docker compose version 2>/dev/null | grep -qE 'v?2\.'; then
  fail "Docker Compose v2 plugin missing." \
       "Run: apt-get install -y docker-compose-plugin && docker compose version"
fi
echo "Compose: $(docker compose version)"

# ─── 3. Firewall ───────────────────────────────────────────────────────────
step "Configuring ufw firewall (allow 22, 80, 443)"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP (Caddy ACME challenge + redirect)'
ufw allow 443/tcp comment 'HTTPS (Caddy)'
ufw --force enable
ufw status verbose

# ─── 4. Clone or update the SafeClaw repo ──────────────────────────────────
step "Fetching SafeClaw source to ${INSTALL_DIR}"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
  echo "Repo already present — fast-forwarding to latest main."
  git -C "${INSTALL_DIR}" fetch --all --prune \
    || fail "git fetch failed in ${INSTALL_DIR}." "Check connectivity to github.com."
  git -C "${INSTALL_DIR}" reset --hard origin/main \
    || fail "git reset --hard failed." "Inspect the working tree at ${INSTALL_DIR}."
else
  mkdir -p /opt
  git clone "${REPO_URL}" "${INSTALL_DIR}" \
    || fail "git clone ${REPO_URL} failed." "Check the repo is reachable from this VPS."
fi

cd "${INSTALL_DIR}"

# ─── 5. Pull pre-built images ──────────────────────────────────────────────
step "Pulling pre-built container images from GHCR"
docker compose pull \
  || fail "docker compose pull failed." \
          "Check the image tags in docker-compose.yml exist on GHCR and that this VPS has network access."

# ─── 6. Caddy configuration ────────────────────────────────────────────────
step "Writing /etc/caddy/Caddyfile and reloading Caddy"
mkdir -p /var/log/caddy
chown -R caddy:caddy /var/log/caddy

cat > /etc/caddy/Caddyfile <<EOF
# Managed by scripts/provision-vps.sh — overwritten on every run.
# ACME contact for Let's Encrypt:
{
    email ${ADMIN_EMAIL}
}

${DOMAIN} {
    reverse_proxy localhost:8080
    log {
        output file /var/log/caddy/access.log {
            roll_size 10mb
            roll_keep 5
        }
    }
}
EOF

caddy validate --config /etc/caddy/Caddyfile \
  || fail "Caddyfile failed validation." "Inspect /etc/caddy/Caddyfile."

systemctl enable caddy >/dev/null 2>&1 || true
systemctl reload caddy 2>/dev/null \
  || systemctl restart caddy \
  || fail "Caddy reload/restart failed." "Run 'journalctl -u caddy -n 50' to see why."

# ─── 7. Install Ollama daemon on host ──────────────────────────────────────
# Hermes containers route :cloud models through a host-side Ollama daemon
# at host.docker.internal:11434. On Linux Docker that resolves via the
# extra_hosts shim in docker-compose.yml; this step makes sure the daemon
# is actually listening on :11434.
step "Installing Ollama daemon on host"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh \
    || fail "Ollama install failed." "Check connectivity to ollama.com and re-run."
  systemctl enable ollama >/dev/null 2>&1 || true
  systemctl start ollama \
    || fail "Could not start the ollama systemd service." "Run 'journalctl -u ollama -n 50'."
  echo "  ✓ Ollama installed + started on :11434"
else
  echo "  ✓ Ollama already installed; ensuring daemon is up"
  systemctl enable ollama >/dev/null 2>&1 || true
  systemctl restart ollama \
    || fail "Could not restart the ollama systemd service." "Run 'journalctl -u ollama -n 50'."
fi

# Verify the daemon is reachable. /api/tags is the cheapest endpoint.
sleep 3
curl -fsS http://localhost:11434/api/tags >/dev/null \
  || fail "Ollama daemon not responding on :11434." \
          "Check 'systemctl status ollama' and 'journalctl -u ollama -n 100'."

# ─── 8. Boot the onboarding webapp ─────────────────────────────────────────
step "Starting the onboarding webapp (other services boot at customer Submit)"
docker compose up -d onboarding \
  || fail "docker compose up -d onboarding failed." \
          "Check 'docker compose logs onboarding' for the error."

# Wait for the onboarding container to report healthy on localhost:8080.
echo "Waiting up to 90s for onboarding webapp to come up on :8080 ..."
ATTEMPTS=30
until curl -fsS http://localhost:8080/health >/dev/null 2>&1; do
  ATTEMPTS=$((ATTEMPTS - 1))
  if [[ ${ATTEMPTS} -le 0 ]]; then
    fail "Onboarding webapp never responded on http://localhost:8080/health within 90s." \
         "Inspect 'docker compose logs onboarding' and 'docker compose ps'."
  fi
  sleep 3
done
echo "Onboarding webapp is up."

# ─── 9. Customer URL + cheat sheet ─────────────────────────────────────────
step "Printing customer URL"
cat <<BANNER

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SafeClaw VPS provisioned for ${DOMAIN}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Send this URL to the customer:
    https://${DOMAIN}/setup

  Webapp is live. Other services boot when customer clicks Submit.

  SSH back here anytime via:
    ssh root@${DOMAIN}
    cd ${INSTALL_DIR} && docker compose ps

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BANNER

# ─── 10. Public health check ───────────────────────────────────────────────
step "Health-checking https://${DOMAIN}/health"

# Caddy needs a beat to negotiate the cert on first request.
echo "First HTTPS request can take ~30s while Let's Encrypt issues the cert ..."
ATTEMPTS=20
until curl -sf "https://${DOMAIN}/health" >/dev/null 2>&1; do
  ATTEMPTS=$((ATTEMPTS - 1))
  if [[ ${ATTEMPTS} -le 0 ]]; then
    fail "https://${DOMAIN}/health never returned 200." \
         "Confirm the A record for ${DOMAIN} resolves to this VPS, then run 'journalctl -u caddy -n 100'."
  fi
  sleep 5
done

echo
echo "OK  https://${DOMAIN}/health is reachable and returns 200."
echo "Provisioning complete."
exit 0
