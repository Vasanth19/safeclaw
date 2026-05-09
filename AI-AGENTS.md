# SafeClaw — Setup Guide for AI Agents

> If you are an AI agent (Claude, Cursor, etc.) assisting a human with installing SafeClaw, follow this guide. It checks prerequisites, attempts auto-installation, and walks through the full setup.

---

## Step 0 — Detect the Platform

Run this command to identify the OS:

```bash
uname -s
```

| Output | Platform |
|--------|----------|
| `Darwin` | macOS |
| `Linux` | Linux (VPS, VM, or native) |

Also check if this is an Apple Silicon Mac:

```bash
uname -m
```

| Output | Architecture |
|--------|-------------|
| `arm64` | Apple Silicon (M1/M2/M3/M4) |
| `x86_64` | Intel Mac or x86 Linux |

---

## Step 1 — Check Prerequisites

Run each check. If something is missing, attempt auto-installation first (see below), then prompt the user only if auto-install fails.

### 1.1 Docker + Docker Compose

```bash
docker --version && docker compose version
```

**Expected:** Docker Engine 24+ and Compose v2.x.

**If missing — macOS:**
```bash
# Try to install OrbStack (preferred — gives real Linux VM + iptables support)
if ! command -v docker &>/dev/null; then
  if command -v brew &>/dev/null; then
    brew install --cask orbstack
    echo "OrbStack installed. The user may need to open the app once to complete setup."
  else
    echo "Homebrew not found. Prompt the user to install OrbStack from https://orbstack.dev"
  fi
fi
```

**If missing — Linux:**
```bash
# Try the official Docker install script
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER
  echo "Docker installed. The user must log out and back in (or run 'newgrp docker') for group changes to take effect."
fi
```

**If missing — Windows/WSL2:**
```bash
echo "Windows/WSL2 detected. Prompt the user to install Docker Desktop from https://docs.docker.com/desktop/setup/install/windows-install/ and ensure WSL2 integration is enabled."
```

### 1.2 Git

```bash
git --version
```

**If missing — macOS:**
```bash
xcode-select --install  # or: brew install git
```

**If missing — Linux:**
```bash
sudo apt-get update && sudo apt-get install -y git
```

### 1.3 Bash

```bash
bash --version
```

**Note:** macOS ships with an old Bash 3.2. SafeClaw scripts require Bash 4+. Check version:

```bash
bash --version | head -1
```

**If Bash < 4 — macOS:**
```bash
brew install bash
# After install, the new bash is at /opt/homebrew/bin/bash (Apple Silicon) or /usr/local/bin/bash (Intel)
```

### 1.4 OpenSSL

```bash
openssl version
```

**If missing — macOS:** `brew install openssl`
**If missing — Linux:** `sudo apt-get install -y openssl`

### 1.5 Node.js (for JWT signing)

```bash
node --version
```

**Expected:** Node 18+.

**If missing — macOS/Linux:**
```bash
# Try nvm first
if ! command -v node &>/dev/null; then
  if ! command -v nvm &>/dev/null; then
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
  fi
  nvm install 20
  nvm use 20
fi
```

**If missing — general fallback:**
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

### 1.6 Ollama (default inference backend)

```bash
ollama --version
```

**If missing — macOS:**
```bash
brew install ollama
# Or download from https://ollama.com/download/mac
```

**If missing — Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**After install, run once:**
```bash
ollama signin
```

**Note:** If the user wants a different LLM provider (Anthropic, OpenAI, vLLM), skip Ollama and note that they will override `HERMES_*` values in `.env` later.

### 1.7 GitHub CLI (optional, for release downloads)

```bash
gh --version
```

**If missing — macOS:** `brew install gh`
**If missing — Linux:** `sudo apt-get install -y gh` or download from GitHub releases.

---

## Step 2 — Install SafeClaw

### Option A: One-line installer (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Vasanth19/safeclaw/main/scripts/install.sh | bash
```

This clones to `~/safeclaw`, seeds `.env`, and generates secrets.

### Option B: Manual clone

```bash
git clone https://github.com/Vasanth19/safeclaw.git ~/safeclaw
cd ~/safeclaw
cp .env.example .env
bash scripts/init-secrets.sh
```

---

## Step 3 — Configure `.env`

**CRITICAL:** The human must provide real values for every `__FILL_IN__` placeholder.

**Do NOT guess or hallucinate these values.** Prompt the user for each:

| Variable | What to ask the user | Where to get it |
|----------|---------------------|-----------------|
| `COMPOSIO_API_KEY` | "What is your Composio API key?" | https://app.composio.dev → Settings → API Keys |
| `COMPOSIO_USER_ID` | "What is your Composio user ID?" | Same page as API key |
| `COMPOSIO_READER_MCP_URL` | "What is your Composio Reader MCP URL?" | Composio dashboard, connected accounts |
| `SLACK_BOT_TOKEN` | "What is your Slack Bot User OAuth Token?" | https://api.slack.com/apps → OAuth & Permissions |
| `SLACK_APP_TOKEN` | "What is your Slack App-Level Token?" | Same app → Basic Info → App-Level Tokens |
| `TELEGRAM_BOT_TOKEN` | "What is your Telegram bot token?" (optional for v1) | @BotFather on Telegram |
| `FIRECRAWL_API_KEY` | "What is your Firecrawl API key?" (optional) | https://firecrawl.dev → Dashboard |

**How to edit `.env`:**
```bash
cd ~/safeclaw
# Open in the user's preferred editor
# VS Code: code .env
# Vim: vim .env
# Nano: nano .env
```

**Validation rule:** After the user fills in `.env`, grep for any remaining `__FILL_IN__`:

```bash
grep "__FILL_IN__" .env
```

If any remain, the stack will fail to start. Prompt the user to complete them.

---

## Step 4 — Start the Stack

```bash
cd ~/safeclaw
docker compose up -d
```

**Wait for health checks.** Run this until all show `healthy` or `running`:

```bash
docker compose ps
```

Services to verify:
- `safeclaw-hermes-reader` (running)
- `safeclaw-hermes-actor` (running, if `ACTOR_ENABLED=true`)
- `safeclaw-postgres-obs` (healthy)
- `safeclaw-postgres-tasks` (healthy)
- `safeclaw-postgrest` (running)
- `safeclaw-embedder` (healthy)
- `safeclaw-reflector` (running)
- `safeclaw-onboarding` (healthy)

---

## Step 5 — Verify Phase 0

```bash
bash scripts/verify-stack.sh --phase 0
```

Expected output: all checks PASS. If any FAIL, fix before proceeding.

---

## Step 6 — Bootstrap the Brain

```bash
bash scripts/bootstrap-brain.sh
```

This seeds the `brain/` folder and pulls 90 days of Gmail history.

**Takes 5–15 minutes** depending on inbox volume.

---

## Step 7 — Open the Control Surfaces

After the stack is running, open these URLs in the user's browser:

| URL | What it is | When to use |
|-----|-----------|-------------|
| `http://localhost:8080/dashboard` | **SafeClaw Dashboard** — live service status, log streams, container health | Day-to-day monitoring |
| `http://localhost:9119` | **Hermes Mission Control** — agent configuration, schedules, feature flags, chat history | Admin / debugging |

**Auto-open command (macOS):**
```bash
open http://localhost:8080/dashboard
open http://localhost:9119
```

**Auto-open command (Linux):**
```bash
xdg-open http://localhost:8080/dashboard
xdg-open http://localhost:9119
```

**If the user is on a remote VPS/VM**, tell them to use SSH port forwarding instead:
```bash
ssh -L 8080:localhost:8080 -L 9119:localhost:9119 user@vps-host
```
Then open `http://localhost:8080/dashboard` and `http://localhost:9119` locally.

---

## Step 8 — Connect Chat Surfaces

### Telegram (v1)
1. The user DMs the bot they created with @BotFather.
2. The bot token was set in `.env` as `TELEGRAM_BOT_TOKEN`.
3. Start the conversation with `/start`.

### Slack (v2)
1. The user @mentions SafeClaw in the home channel configured in `actor-hermes.yaml`.
2. Or DM the bot directly.

---

## Troubleshooting

### Docker permission denied
```bash
# Linux: add user to docker group, then re-login
sudo usermod -aG docker $USER
# Log out and back in (or: newgrp docker)
```

### Port already in use
```bash
# Find what's on 8080 or 9119
lsof -i :8080
lsof -i :9119
# Kill the process or change the port mapping in docker-compose.yml
```

### `.env` values not loading
```bash
# Ensure .env is in the repo root and not overridden by shell env
set -a; source .env; set +a
# Or use docker compose's env_file: directive (already configured)
```

### Ollama not reachable
```bash
# Verify Ollama daemon is running
ollama list
# If empty, models aren't pulled yet. SafeClaw uses glm-5.1:cloud by default
# which routes through Ollama Cloud (no local model needed).
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Check all services | `docker compose ps` |
| View logs | `docker compose logs -f <service>` |
| Restart one service | `docker compose restart <service>` |
| Full restart | `docker compose down && docker compose up -d` |
| Re-bootstrap brain | `bash scripts/bootstrap-brain.sh --reset` |
| Update to latest | `git pull origin main && docker compose up -d --build` |
| Open dashboard | `open http://localhost:8080/dashboard` (macOS) |
| Open Mission Control | `open http://localhost:9119` (macOS) |

---

## Agent Checklist

Before declaring setup complete, verify:

- [ ] All prerequisite tools installed (Docker, git, bash, openssl, node)
- [ ] `.env` has zero `__FILL_IN__` placeholders remaining
- [ ] `docker compose up -d` started without errors
- [ ] `docker compose ps` shows all expected services
- [ ] `bash scripts/verify-stack.sh --phase 0` reports all PASS
- [ ] `bash scripts/bootstrap-brain.sh` completed without errors
- [ ] Dashboard at `http://localhost:8080/dashboard` loads
- [ ] Mission Control at `http://localhost:9119` loads
- [ ] User knows how to chat with the assistant (Telegram DM or Slack @mention)
