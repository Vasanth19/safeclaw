# SafeClaw — Installation & Deployment Guide

This is the **single canonical install reference** — captures the full flow,
the gotchas, and the operations a maintainer needs after the install is live.

If you're an operator just trying to get running, also see `FIRST-RUN.md`
(the short version). This doc is more comprehensive — read it once, refer back
when something breaks.

---

## What you're installing

SafeClaw is a self-hosted AI assistant deployed as a Docker Compose stack.
After install, the operator chats with it via Telegram and the assistant:

- Reads inbound Gmail through a hosted MCP broker (Composio)
- Writes structured observations + a "Brain" of People/Companies/Style to local Postgres
- Drafts replies in the operator's voice (using `style_samples` learned from sent mail)
- Stages every send as a Gmail draft for the operator to approve

The architecture defense (see `ARCHITECTURE.md` §5) splits "read" and "write"
into two Hermes Agent instances with different tool allowlists. This is the
load-bearing part — don't merge them.

---

## Prerequisites

| Tool | Why | Install |
|------|-----|---------|
| **OrbStack** (macOS) or Docker Engine 24+ (Linux) | Container runtime + a real Linux VM on Mac (lets host iptables egress rules apply to containers). | https://orbstack.dev |
| `docker compose` v2 | Compose plugin. Verify: `docker compose version` shows `v2.x`. | Bundled with OrbStack/Docker Desktop. |
| `git`, `bash`, `openssl`, `node` | Used by helper scripts. `node` only used to sign the agent JWT. | Usually preinstalled. |
| **Composio account** | Holds OAuth tokens off-box and exposes per-toolkit MCP URLs. Free tier covers a single-user install (5,000 actions/mo). | https://app.composio.dev |
| **Telegram account** | v1 control surface. Operator DMs the bot to read/draft. | App on phone or desktop. |
| **LLM endpoint** | OpenAI-compatible. Default: Ollama Cloud via local daemon ($20/mo). Alternative: Anthropic, OpenAI, vLLM, etc. | https://ollama.com (then `ollama signin`) |

### Hardware

| Resource | Minimum | Notes |
|---|---|---|
| RAM (free) | 4 GB | Hermes context windows are large |
| Disk | 20 GB | Postgres data + Hermes build cache + brain folder |
| CPU | 4 cores | Most heat is in Hermes inference (offloaded to your LLM endpoint) |

---

## Install — full step-by-step

### Step 1 — Clone the repo

```bash
git clone <safeclaw-repo-url> safeclaw
cd safeclaw
```

All paths below are relative to the repo root.

### Step 2 — Copy `.env.example` to `.env` and paste credentials

```bash
cp .env.example .env
```

Open `.env` in your editor. Two kinds of placeholders:

- `__FILL_IN__` — you paste a real value (Composio key, Telegram token, etc.)
- `__GENERATE__` — `scripts/init-secrets.sh` will fill these in Step 3. Leave them.

Values to paste yourself:

| Variable | Where to get it |
|---|---|
| `COMPOSIO_API_KEY` | After Step 4 (Composio dashboard → project API key, looks like `ak_...`) |
| `COMPOSIO_USER_ID` | After Step 4 (`pg-test-...` for the default project, or your own user_id) |
| `COMPOSIO_READER_MCP_URL` | After Step 4 (Reader MCP server URL — read-only allowlist) |
| `COMPOSIO_ACTOR_MCP_URL` | After Step 4 (Actor MCP server URL — draft/send allowlist) |
| `TELEGRAM_BOT_TOKEN` | After Step 5 (`@BotFather` → `/newbot` → token like `123456:ABC-...`) |
| `TELEGRAM_ALLOWED_USERS` | After Step 5 (`@userinfobot` → comma-separated numeric user IDs) |

You can come back to fill these after Steps 4 + 5. For now move on.

### Step 3 — Generate the random secrets

```bash
bash scripts/init-secrets.sh
```

What this does:
- Replaces every `__GENERATE__` line with a fresh secret:
  - 4 Postgres passwords (`openssl rand -hex 16` each)
  - `JWT_SECRET` (`openssl rand -hex 32`)
  - `TASKS_AGENT_JWT` (HS256 signature over `{"role":"tasks_agent"}` using `JWT_SECRET`)
- Sets `chmod 600 .env`
- Idempotent — safe to re-run; only touches lines that still have `__GENERATE__`

Sample output:
```
init-secrets: filled 6 placeholder(s):
  - POSTGRES_OBS_PASSWORD
  - POSTGRES_TASKS_PASSWORD
  - TASKS_AGENT_PASSWORD
  - TASKS_HUMAN_PASSWORD
  - JWT_SECRET
  - TASKS_AGENT_JWT
init-secrets: .env permissions are now 600.
```

### Step 4 — Set up Composio (one-time, ~5 min)

Composio handles all OAuth and integration plumbing — no Google Cloud Console
work needed.

1. **Create an account** at https://app.composio.dev (free tier is fine).
2. **Initialize a project** (one per SafeClaw install):
   ```bash
   composio dev init
   ```
   This creates `.composio/.env.local` with a project API key. Paste the
   key into `.env` as `COMPOSIO_API_KEY`. The `COMPOSIO_USER_ID` lives
   alongside it (`pg-test-...`).
3. **Connect the toolkits the assistant needs.** In the Composio dashboard:
   - Click **+ Add Connection** → search "Gmail" → click Connect → walk
     through Google OAuth (Composio uses its own verified OAuth client, so
     no "unverified app" warning, no Google Cloud Console required).
   - Repeat for Drive (`drive.file` scope is enough).
   - Slack and Calendar are optional for v1.
4. **Create two MCP servers** in the Composio dashboard:
   - **Reader** — read-only allowlist:
     - `GMAIL_FETCH_EMAILS`
     - `GMAIL_LIST_THREADS`
     - `GMAIL_GET_PROFILE`
     - `SLACK_FETCH_CONVERSATION_HISTORY` (optional)
   - **Actor** — draft/send allowlist:
     - `GMAIL_CREATE_EMAIL_DRAFT`
     - `GMAIL_REPLY_TO_THREAD`
     - `SLACK_SEND_MESSAGE` (optional)
     - `GOOGLEDRIVE_FIND_FILE`
     - `GOOGLEDRIVE_MOVE_FILE`
     - `GOOGLEDRIVE_UPLOAD_FILE`
     - `GOOGLEDRIVE_CREATE_FOLDER`
   - **Important:** the URLs Composio shows you in the dashboard (form
     `https://backend.composio.dev/v3/mcp/<id>`) are **base URLs**. Append
     `/mcp?user_id=<your_user_id>` when pasting into `.env`. The full URL
     looks like:
     ```
     https://backend.composio.dev/v3/mcp/<id>/mcp?user_id=<your_user_id>
     ```
     Without that suffix Hermes will get HTTP 307 → 406 (gateway noise, no
     tools). This is the gotcha that cost us most cycles during build.
5. Paste both MCP URLs into `.env` as `COMPOSIO_READER_MCP_URL` and
   `COMPOSIO_ACTOR_MCP_URL`.

### Step 5 — Create the Telegram bot (one-time, ~3 min)

1. **Create the bot** via `@BotFather`:
   - Telegram → search `@BotFather` → DM `/newbot`
   - Pick a display name (e.g. "Jarvis Assistant")
   - Pick a username — must end in `bot` (e.g. `myname_assistant_bot`)
   - BotFather replies with the API token (`123456789:AAH...`)
   - Paste into `.env` as `TELEGRAM_BOT_TOKEN`
2. **Get your numeric user ID** via `@userinfobot`:
   - Telegram → search `@userinfobot` → `/start`
   - Reply contains your numeric ID (e.g. `407407692806619136`)
   - Paste into `.env` as `TELEGRAM_ALLOWED_USERS` (comma-separated if multiple)
3. **Optional** — give the bot a profile picture, description, and commands
   (`/setdescription`, `/setuserpic`, `/setcommands`) via BotFather.

### Step 6 — Boot the stack

```bash
docker compose up -d
```

The first build is slow (~8-15 min) because Hermes is built from source
(Python + `uv` + Playwright browsers). Subsequent restarts are fast.

Watch progress:
```bash
docker compose ps
docker compose logs -f hermes-actor
```

Wait for `hermes-actor` to print:
```
⚕ Hermes Gateway Starting...
Messaging platforms + cron scheduler
```

That means the gateway booted and is now polling Telegram. If it's silent
after that, that's normal — Hermes only logs when there's traffic.

### Step 7 — Bootstrap the brain

```bash
bash scripts/bootstrap-brain.sh
```

What this does:
1. Seeds the PARA-style markdown brain folder into `./brain/` if not already
   present. Creates the standard vault layout (Identity, Aspirations, Live Logs,
   Daily Journal, Meetings, Projects, Areas, Resources, Operations, People, Companies).
2. Pulls Gmail history for the last 90 days through the Composio Reader MCP.
3. Extracts unique senders → upserts into `brain/People/<slug>.md` and the
   `entities` table in postgres-obs.
4. Extracts sender domains → `brain/Companies/<domain>.md` + `entities`.
5. Pulls sent-mail bodies → `style_samples` table (used as few-shot when
   the Actor drafts replies in your voice).
6. Writes a summary to `brain/2 - Live Logs/bootstrap-<timestamp>.md`.

Useful flags:

| Flag | Effect |
|---|---|
| `--days N` | Override `BOOTSTRAP_DAYS` for this run (default 90) |
| `--dry-run` | Parse + print what would happen, no DB writes |
| `--reset` | Clear the watermark, reprocess everything from scratch |
| `--help` | Print usage |

After it finishes, `brain/People/` and `brain/Companies/` will have one
markdown file per unique correspondent / domain. The Actor uses these +
the `entities` table to recognize who you talk about.

### Step 8 — First conversation

Open Telegram, find your bot, send `Hi`.

The bot should respond with a real LLM-generated reply (powered by your
configured `HERMES_DEFAULT_MODEL` via the configured endpoint). Try:

- `What can you do?` — exercises tool listing
- `Fetch my last 3 emails` — exercises the Composio MCP path
- `Draft a reply to <person> about <topic>` — exercises Actor + brain recall

Every send the Actor proposes is a **draft in your Gmail drafts folder**
until you `AUTO_SEND_ENABLED=true` — which should not happen until 30 days
of clean operation (see `IMPLEMENTATION-PLAN.md` §Phase 4).

---

## Customizing the LLM endpoint

Default is **Ollama Cloud via local Ollama daemon** — `glm-5.1:cloud`. The
local daemon proxies `:cloud` model calls to ollama.com using the SSH key
written by `ollama signin`. No API key is sent in env.

To switch to a different OpenAI-compatible endpoint, edit `.env`:

```bash
# Anthropic Claude
HERMES_INFERENCE_PROVIDER=custom
OLLAMA_BASE_URL=https://api.anthropic.com/v1
OLLAMA_API_KEY=sk-ant-...
HERMES_DEFAULT_MODEL=claude-sonnet-4-6

# OpenAI
HERMES_INFERENCE_PROVIDER=custom
OLLAMA_BASE_URL=https://api.openai.com/v1
OLLAMA_API_KEY=sk-proj-...
HERMES_DEFAULT_MODEL=gpt-4o

# Local Ollama (no cloud)
HERMES_INFERENCE_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
OLLAMA_API_KEY=ollama-local
HERMES_DEFAULT_MODEL=llama3.1:8b
```

(The variable names are `OLLAMA_*` for legacy reasons — they apply to any
OpenAI-compatible endpoint when `HERMES_INFERENCE_PROVIDER=custom`.)

After changing, `docker compose restart hermes-reader hermes-actor`.

---

## Daily operator commands

| What you want | Command |
|---|---|
| All services status | `docker compose ps` |
| Tail reader logs | `docker compose logs -f hermes-reader` |
| Tail actor logs | `docker compose logs -f hermes-actor` |
| Recent observations | `docker compose exec postgres-obs psql -U "$POSTGRES_OBS_USER" -d safeclaw_obs -c 'SELECT sender, subject, is_critical, processed_at FROM observations ORDER BY processed_at DESC LIMIT 20;'` |
| Show all People in brain | `ls brain/People/` |
| Re-bootstrap (incremental, only new mail) | `bash scripts/bootstrap-brain.sh` |
| Re-bootstrap (full reset) | `bash scripts/bootstrap-brain.sh --reset` |
| Stop everything | `docker compose down` |
| Start again | `docker compose up -d` |
| Re-seed brain folder | `bash scripts/bootstrap-brain.sh --reset` (backs up existing brain/ to brain-backup-{timestamp}) |

---

## Troubleshooting — gotchas captured during the buildout

These are the real walls we hit. Documenting so future installs don't.

### "No LLM provider configured" on first DM

**Symptom:** Bot replies with `Sorry, I encountered an error (RuntimeError). No
LLM provider configured. Run hermes model to select a provider.`

**Cause:** Hermes has TWO concepts that both must be configured:
1. The YAML `model:` block in `config/{reader,actor}-hermes.yaml`
2. The `HERMES_INFERENCE_PROVIDER` env var + corresponding `OLLAMA_API_KEY`
   (or whatever provider's API key var)

If only one is set, the agent's startup check fails.

**Fix:** ensure `.env` has all of:
- `HERMES_INFERENCE_PROVIDER=ollama-cloud` (or `custom`, `ollama`, etc.)
- `OLLAMA_BASE_URL=...`
- `OLLAMA_API_KEY=...`
- `HERMES_DEFAULT_MODEL=...`

And the YAML `model:` block in `config/actor-hermes.yaml` has matching
values. Both are needed.

### Composio MCP returns 307 → 406

**Symptom:** Hermes logs `HTTP 406` or no MCP tools registered.

**Cause:** the URL Composio's dashboard shows you (`/v3/mcp/<id>`) is the
**base** — it 307-redirects to `/sse` which expects SSE Accept headers.

**Fix:** append `/mcp?user_id=<your_user_id>` to the URL when pasting into
`.env`. Final shape:
```
COMPOSIO_READER_MCP_URL=https://backend.composio.dev/v3/mcp/<id>/mcp?user_id=<uid>
```

### Slack platform crashes the actor

**Symptom:** `slack_sdk.errors.SlackApiError: invalid_auth` repeats in actor
logs every few seconds.

**Cause:** `.env` has placeholder Slack tokens (`xoxb-__FILL_IN__`) — Hermes
sees them as valid-looking and tries to authenticate.

**Fix:** if you're not using Slack in v1, leave Slack vars **completely
empty** in `.env`:
```
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_REVIEW_CHANNEL_ID=
```
Don't use placeholder strings. The current `.env.example` doesn't include
Slack at all in v1 — those vars only appear if you copy from an older `.env`.

### Wrong Hermes binary called

**Symptom:** Container loops printing
`AI Agent initialized with model: ⚠️ API key appears invalid` then exits.

**Cause:** `hermes-agent` is the legacy demo binary that always tries a
hardcoded test query. The real CLI is `hermes` (no suffix).

**Fix:** in `docker-compose.yml`, the `command:` line for hermes-actor
must call `hermes` not `hermes-agent`:
```yaml
command: >
  sh -c '
    if [ "${ACTOR_ENABLED:-false}" != "true" ]; then exit 0; fi
    exec /opt/hermes/.venv/bin/hermes gateway run --accept-hooks
  '
```
This is the way the shipped compose is configured already — don't change it.

### Shell env overrides `.env`

**Symptom:** `docker compose exec hermes-actor env | grep COMPOSIO_API_KEY`
returns a different value than what's in `.env`.

**Cause:** Docker Compose's variable interpolation prefers the **shell env
of the user running `docker compose`** over the `.env` file. If your `~/.zshrc`
exports `COMPOSIO_API_KEY=uak_...` (a different key from your project's
`ak_...`), shell wins.

**Fix:** the shipped `docker-compose.yml` uses `env_file: .env` for the
Hermes services, which loads `.env` directly into the container, bypassing
interpolation. Keep that directive intact.

### Gateway logs say "No messaging platforms enabled"

**Cause:** Hermes gateway exits early if no `TELEGRAM_BOT_TOKEN` (or other
platform token) is detected. The agent's MCP servers also don't get
registered without a platform.

**Fix:** ensure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS` are both
set in `.env` and propagated to the actor (the shipped `env_file:` setup
handles this).

### Hermes config write fails with "Device or resource busy"

**Symptom:** `hermes config set <key> <value>` returns
`OSError: [Errno 16] Device or resource busy`.

**Cause:** the compose file bind-mounts `./config/actor-hermes.yaml` to
`/opt/data/config.yaml` inside the container. `hermes config set` does an
atomic rename, which fails on a bind-mounted file.

**Fix:** edit `config/actor-hermes.yaml` on the **host** instead, then
`docker compose restart hermes-actor`.

### Bot answers but says "/sethome"

**Cause:** Hermes wants to know which Telegram chat to use for cron-driven
output (daily briefings, weekly reflections, critical alerts). It defaults
to asking on first message.

**Fix:** in your DM with the bot, send `/sethome`. The bot will confirm and
all future cron output lands in this DM.

### Bootstrap script can't reach Composio

**Symptom:** `bash scripts/bootstrap-brain.sh --dry-run` fails with
"connection refused" or "401 unauthorized".

**Cause:** either the stack isn't up (`docker compose ps` missing services),
or `.env` still has `__FILL_IN__` for Composio fields.

**Fix:** ensure Steps 4 and 6 are complete before running Step 7.

---

## Operations

### Updating to a newer SafeClaw version

```bash
cd <safeclaw_install>
git pull
docker compose build --pull        # rebuild custom images (Hermes, brain-api, etc.)
docker compose up -d                # restart with new images
```

Migrations are forward-compatible — no manual SQL needed.

### Updating the brain template

The `brain/` folder is a copy of the upstream template at clone time, with
its `.git` stripped. To re-seed from the bootstrap script:

```bash
bash scripts/bootstrap-brain.sh --reset
# review the output — your populated People/Companies stay untouched
```

Or — easier — let new SafeClaw versions ship with an updated bootstrap
script that handles the merge for you.

### Backups

The data that matters:

- `postgres-obs` Docker volume → contains the brain (entities, observations,
  embeddings, style samples). Back up via:
  ```bash
  docker compose exec postgres-obs pg_dump -U "$POSTGRES_OBS_USER" safeclaw_obs > obs-$(date +%F).sql
  ```
- `postgres-tasks` volume → similar:
  ```bash
  docker compose exec postgres-tasks pg_dump -U "$POSTGRES_TASKS_USER" safeclaw_tasks > tasks-$(date +%F).sql
  ```
- `./brain/` folder → human-readable backup is just a `cp -r` or `tar`.
- `.env` → contains the only secrets. Back up to a password manager or KMS.

The `vendor/`, `composio/`, `node_modules/`, and Docker volumes other than
the two Postgres ones are reproducible from the repo + `.env`.

---

## Multi-customer deployment

This repo is designed for one SafeClaw install per customer. To deploy to N
customers:

1. **Each customer gets their own clone** of the repo (or fork — same effect)
2. **Each customer creates their own:**
   - Composio account (or sub-project under your master account; per-customer
     project keys keep their data isolated)
   - Telegram bot (each gets a unique `@something_bot` username)
   - LLM API key or Ollama subscription
   - Postgres data lives only on their machine
3. **You can ship the install as:**
   - A `make install` script that runs Steps 1-7 with prompts
   - A pre-baked Docker volume (less portable)
   - A managed service where you run the stack on a VPS per customer (each gets a different domain)

The codebase has zero per-customer assumptions. The `.env` is the only
customer-specific surface, and `.env.example` documents every field.

### Cost per customer at typical volume

| Component | Cost (v1) |
|---|---|
| Composio (Free tier, 5k actions/mo) | $0 — covers single user easily |
| Composio (Hobby tier, if needed) | ~$9/mo |
| Ollama Cloud subscription | $20/mo per customer (or ~$30/mo for Anthropic Claude alternatively) |
| VPS or local hardware | $0 (their machine) to ~$20/mo (small VPS) |
| **Floor cost per customer** | **$20/mo** (Ollama Cloud only, everything else self-hosted) |

---

## Known limits / what's NOT in v1

These exist as scaffolding but are not yet wired:

- **Slack platform** — config exists; no end-to-end testing in v1 (Telegram is
  the v1 chat surface). v2 will enable the `#safeclaw-review` approval
  channel pattern.
- **Drive mirror** (`rclone-sync` service) — runs but the OAuth token isn't
  auto-provisioned through Composio yet. v2 closes this loop.
- **Auto-send** (`AUTO_SEND_ENABLED=true`) — gated behind 30-day clean run
  (see `IMPLEMENTATION-PLAN.md` §Phase 4). Don't enable in v1.
- **Reflector** (weekly Soul revisions) — service is in compose but not
  scheduled to run; `soul_revisions` table stays empty. Wire in v2.
- **Reader cron** — currently the Reader observes only when the Actor
  triggers it (via Telegram conversation). Continuous Gmail Pub/Sub push or
  a cron poller is v2 work. Until then, "fetch latest" via Telegram is the
  way to refresh observations.

---

## Acceptance test (validate a fresh install)

After Step 7, run this checklist:

```bash
# All services healthy
docker compose ps
# → expect: postgres-obs, postgres-tasks, postgrest, embedder healthy;
#    hermes-reader, hermes-actor, brain-api-mcp, tasks-api-mcp running

# Brain populated
ls brain/People/ | wc -l
# → expect: > 0 (one file per unique sender from last 90 days)

# Postgres has style samples
docker compose exec postgres-obs psql -U "$POSTGRES_OBS_USER" -d safeclaw_obs \
  -c "SELECT count(*) FROM style_samples;"
# → expect: > 0

# Composio MCP reachable
docker compose exec hermes-actor python3 -c "
import urllib.request, json, os
url = os.environ['COMPOSIO_READER_MCP_URL']
req = urllib.request.Request(url,
  data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'}).encode(),
  headers={'x-api-key': os.environ['COMPOSIO_API_KEY'],
           'Accept':'application/json, text/event-stream',
           'Content-Type':'application/json'})
r = urllib.request.urlopen(req, timeout=10)
print('HTTP', r.status, '— MCP reachable')
"

# Telegram bot reachable
curl -sf "https://api.telegram.org/bot$(grep ^TELEGRAM_BOT_TOKEN .env | cut -d= -f2)/getMe"
# → expect: {"ok":true,"result":{"username":"<your_bot>",...}}
```

If all four pass, the install is shippable.

---

## Where things live (file map)

```
<safeclaw_install>/
├── .env                          ← per-customer secrets (gitignored, chmod 600)
├── .env.example                  ← template with __FILL_IN__ + __GENERATE__
├── INSTALL.md                    ← this file
├── FIRST-RUN.md                  ← short version of the install
├── ARCHITECTURE.md               ← full architecture reference
├── DEPLOY-RUNBOOK.md             ← detailed env vars + ops
├── IMPLEMENTATION-PLAN.md        ← five-phase rollout plan
├── README.md                     ← repo overview
├── docker-compose.yml            ← 11-service stack definition
│
├── config/
│   ├── reader-hermes.yaml        ← Reader Hermes config (read-only MCP allowlist)
│   ├── actor-hermes.yaml         ← Actor Hermes config (write/draft tools)
│   └── postgrest.conf
│
├── db/
│   ├── 001_obs_schema.sql        ← observation event log + critical alerts
│   ├── 002_task_schema.sql       ← tasks + RLS roles
│   └── 003_brain_schema.sql      ← brain layer (entities, facts, embeddings)
│
├── services/
│   ├── embedder/                 ← Python: sentence-transformers, polls + /embed HTTP
│   └── reflector/                ← Python: weekly Soul updater (v2)
│
├── mcp-tools/
│   ├── tasks-api/                ← Node MCP server: create_task, add_comment, ...
│   └── brain-api/                ← Node MCP server: brain_recall, brain_write, ...
│
├── scripts/
│   ├── init-secrets.sh           ← generate per-install random secrets in .env
│   ├── bootstrap-brain.sh        ← clone Evolving Brain Template + scrape 90d Gmail
│   ├── lib/bootstrap_brain.py    ← the actual brain-population logic
│   └── verify-stack.sh           ← phase-gated PASS/FAIL acceptance checks
│
├── brain/                        ← seeded at install (gitignored), PARA-style markdown vault
│   ├── 0 - Identity/             ← who the operator is
│   ├── 1 - Aspirations/
│   ├── 2 - Live Logs/            ← bootstrap reports + daily logs
│   ├── 3 - Daily Journal/
│   ├── 4 - Meetings/
│   ├── 5 - Projects/
│   ├── 6 - Areas/
│   ├── 7 - Resources/
│   ├── 8 - North Star/
│   ├── 9 - Operations/
│   ├── People/                   ← auto-populated by bootstrap, then maintained by Actor
│   └── Companies/                ← auto-populated by bootstrap, then maintained by Actor
│
└── vendor/                       ← cloned at first build (gitignored)
    └── hermes-agent/             ← NousResearch/hermes-agent vendored for local build
```

---

## Credits

- **Hermes Agent runtime** — NousResearch (https://github.com/NousResearch/hermes-agent)
- **PARA-style markdown vault layout** — inspired by Tiago Forte's PARA method
- **Composio** — OAuth + MCP integration platform (https://composio.dev)
- **Ollama Cloud** — `:cloud` model routing (https://ollama.com)
- **pgvector** — Postgres vector extension
- **PostgREST** — auto-generated REST API on the task DB
