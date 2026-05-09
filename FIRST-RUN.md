# SafeClaw — First-Run Guide

This is the runbook a new operator follows on a fresh machine to go from
`git clone` → "the assistant is helping me." Every step assumes you're sitting
at the install host.

The summary is short, because Composio handles the OAuth dance for you and the
bootstrap script handles the brain seed:

1. Clone the repo
2. Install OrbStack
3. Copy `.env.example` to `.env` and fill the `__FILL_IN__` values
4. Generate secrets (`bash scripts/init-secrets.sh`)
5. Start the stack (`docker compose up -d`)
6. Bootstrap the brain (`bash scripts/bootstrap-brain.sh`)
7. DM your Telegram bot

---

## Prerequisites

| Tool | Why | Install |
|------|-----|---------|
| **OrbStack** (macOS) or Docker Engine 24+ (Linux) | Container runtime. OrbStack on macOS gives you a real Linux VM, which is the only way the egress iptables story works on a Mac. | https://orbstack.dev |
| `docker compose` v2 | Compose plugin (verify: `docker compose version` shows v2.x). | Bundled with OrbStack / Docker Desktop. |
| `git`, `bash`, `openssl`, `node` | Used by the helper scripts. `node` is only used to sign the agent JWT. | Usually preinstalled. |
| **Composio account** | Holds OAuth tokens off-box and exposes per-toolkit MCP URLs. | https://app.composio.dev |
| **Telegram account** | v1 control surface. You DM your bot to approve drafts. | Telegram on phone or desktop. |

You also need somewhere to point Hermes for inference. The shipped default is
**Ollama Cloud via the local Ollama daemon** — install Ollama
(https://ollama.com), then `ollama signin` once so the daemon can proxy
`:cloud` model calls. Other OpenAI-compatible endpoints (Anthropic, OpenAI,
self-hosted vLLM) work too — just override the `HERMES_*` values in `.env`.

---

## Step 1 — Clone

```bash
git clone <repo-url> safeclaw
cd safeclaw
```

All paths below are relative to the repo root.

---

## Step 2 — Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in every line that says `__FILL_IN__`. Leave the
`__GENERATE__` lines alone — `scripts/init-secrets.sh` will populate those in
the next step.

The values you need to paste yourself:

| Variable | Where to get it |
|----------|-----------------|
| `COMPOSIO_API_KEY` | Composio dashboard → project API key (`ak_...`) |
| `COMPOSIO_USER_ID` | Composio dashboard → your connection actor (`pg-test-...` or your real `user_id`) |
| `COMPOSIO_READER_MCP_URL` | Composio dashboard → MCP servers → Reader → URL |
| `COMPOSIO_ACTOR_MCP_URL` | Composio dashboard → MCP servers → Actor → URL |
| `TELEGRAM_BOT_TOKEN` | DM `@BotFather` on Telegram → `/newbot` → copy the `123:ABC` token |
| `TELEGRAM_ALLOWED_USERS` | DM `@userinfobot` on Telegram → it returns your numeric ID. Comma-separate if more than one. |

If you want to override the LLM backend, edit the `HERMES_*` and `OLLAMA_*`
lines too.

---

## Step 3 — Generate secrets

```bash
bash scripts/init-secrets.sh
```

This walks through `.env`, replaces every `__GENERATE__` placeholder with a
fresh random secret (database passwords, `JWT_SECRET`, the agent JWT signed
with that secret), atomic-writes the file, and `chmod 600 .env`.

The script is idempotent — safe to re-run if you add new `__GENERATE__` lines
later. It only touches lines that still have the placeholder, so previously
generated secrets are preserved.

---

## Step 4 — Compose the Composio MCP servers

In the Composio dashboard:

1. Connect the Gmail account(s) the assistant should monitor. Suggested
   connection IDs: `primary-inbox`, `secondary-inbox`, `tertiary-inbox`.
2. Connect the Drive account. Suggested connection ID: `primary-drive`.
3. Create the **Reader** MCP server. Toolkit allowlist (read-only):
   - `GMAIL_FETCH_EMAILS`
   - `GMAIL_LIST_THREADS`
   - `GOOGLEDRIVE_FIND_FILE` (read-only Drive lookup, optional)
4. Create the **Actor** MCP server. Toolkit allowlist (compose / send):
   - `GMAIL_CREATE_DRAFT`
   - `GMAIL_SEND_EMAIL`
   - `GMAIL_REPLY_TO_THREAD`
   - `TELEGRAM_SEND_MESSAGE`
   - `GOOGLEDRIVE_MOVE_FILE` (optional)
5. Copy both MCP URLs and the project API key into `.env`.

The toolkit allowlist on each MCP server is the load-bearing security boundary
— see ARCHITECTURE.md §5.

---

## Step 5 — Start the stack

```bash
docker compose up -d
```

Watch the services come up:

```bash
docker compose ps
docker compose logs -f
```

The first build is slow (Hermes is built from source — Python + `uv` +
Playwright browsers; allow 8–15 min). Subsequent restarts are fast.

When all services show `healthy` or `running`, run the foundation check:

```bash
bash scripts/verify-stack.sh --phase 0
```

---

## Step 6 — Bootstrap the brain

The brain folder is empty by design. The bootstrap script:

1. Seeds the PARA-style markdown brain folder into `./brain/`.
2. Pulls 90 days of Gmail history through the Composio Reader MCP, extracts
   unique senders into `brain/People/`, sender domains into
   `brain/Companies/`, and sent-mail bodies into `postgres-obs.style_samples`.
3. Writes a summary report to `brain/2 - Live Logs/bootstrap-{timestamp}.md`.

Run it:

```bash
bash scripts/bootstrap-brain.sh
```

Useful flags:

| Flag | Effect |
|------|--------|
| `--days N` | Override `BOOTSTRAP_DAYS` for this run. |
| `--dry-run` | Parse + print what would happen, no DB writes. |
| `--reset` | Clear the watermark and reprocess everything from scratch. |
| `--help` | Print usage. |

After it finishes you should see:

- `brain/People/<slug>.md` files for each unique correspondent
- `brain/Companies/<domain>.md` files for each unique sender domain
- Rows in `postgres-obs.style_samples` with your sent-mail bodies
- A summary log at `brain/2 - Live Logs/bootstrap-<timestamp>.md`

---

## Step 7 — Talk to your bot

Open Telegram, find the bot you created with `@BotFather`, and DM it. Once the
Actor sees you in `TELEGRAM_ALLOWED_USERS` it'll respond and start posting
approval cards as new email arrives in the Reader's inbox.

Any draft the Actor proposes will be staged in your Gmail drafts folder
(thanks to `GMAIL_CREATE_DRAFT`) and surfaced for approval in Telegram. Auto-
send stays off until you've completed the 30-day clean run described in
IMPLEMENTATION-PLAN.md §Phase 4.

---

## Daily operator commands

| What you want | Command |
|---|---|
| See all services | `docker compose ps` |
| Tail reader logs | `docker compose logs -f hermes-reader` |
| Tail actor logs | `docker compose logs -f hermes-actor` |
| See recent observations | `docker compose exec postgres-obs psql -U obs_user -d safeclaw_obs -c 'SELECT sender, subject, is_critical, processed_at FROM observations ORDER BY processed_at DESC LIMIT 20;'` |
| See pending approvals | Check Telegram (v1) — the Actor DMs you the cards. |
| Re-bootstrap (incremental) | `bash scripts/bootstrap-brain.sh` |
| Re-bootstrap (full reset) | `bash scripts/bootstrap-brain.sh --reset` |
| Shut everything down | `docker compose down` |
| Start again | `docker compose up -d` |

---

## How the assistant actually helps you (day to day)

1. **Email arrives** → Reader sees it via the Composio Reader MCP, classifies
   intent, extracts entities, writes a structured observation to
   `postgres-obs`. If the email matches critical rules, the Actor sends you a
   Telegram card.

2. **You DM the bot** (`draft a reply to alice@example.com about the closing`)
   → Actor looks up Alice in the brain, pulls 3–5 of your past emails to her
   as style samples, drafts a reply in your voice, and creates a Gmail draft.
   It DMs you a preview card.

3. **You tap Approve** → the draft stays in your Gmail drafts folder for you
   to review and send (Phase 1). After the 30-day clean run, you can flip
   `AUTO_SEND_ENABLED=true` and the assistant will send on your behalf for
   whitelisted recipients.

4. **Reflector runs weekly** (Mondays 06:00 UTC) → reads your last 7 days of
   approve / reject decisions and proposes Soul + preference updates. You
   confirm each proposed rule via the chat surface.

---

## Gotchas

- **First Hermes build is slow** — 8-15 min. Subsequent restarts are fast.

- **Gmail Pub/Sub `historyId` gaps** — Gmail's `watch()` expires after 7 days.
  The actor's `gmail_rearm` schedule (midnight daily) re-arms it and
  reconciles missed history. If this fails silently, the reader stops seeing
  new mail. Check: `docker compose logs hermes-actor | grep gmail_rearm`.

- **Composio token expiry** — if the Composio MCP returns "auth required" or
  "invalid connection", re-authorize the connection in the Composio
  dashboard. SafeClaw never sees the refresh token.

- **`drive.file` scope** — the assistant can only touch Drive files it
  created or that you explicitly opened with its Drive integration. By
  design.

- **Soul file vs DB** — `brain/0 - Identity/soul.md` is human-readable and
  intended for you to edit. Changes you make there sync to `user_profile`
  on the next reflector run. The DB version is what the agent reads.

---

## Where things live on disk

```
<safeclaw_install>/
├── .env                    ← secrets (chmod 600, NEVER commit)
├── docker-compose.yml      ← the stack definition
├── config/                 ← Hermes reader/actor YAML
├── db/                     ← SQL migrations
├── brain/                  ← human-editable second brain (gitignored;
│                             cloned from the Evolving Brain Template at
│                             install time)
├── mcp-tools/              ← tasks-api + brain-api MCP servers (TypeScript)
├── services/               ← embedder + reflector (Python)
├── scripts/                ← init-secrets.sh, bootstrap-brain.sh, verify-stack.sh
├── vendor/hermes-agent/    ← cloned from upstream (gitignored)
└── drive-mirror/           ← rclone'd Drive folder (created on first sync)
```

---

## When something breaks

1. `docker compose ps` — which service is not healthy?
2. `docker compose logs <service> --tail 50` — what's the error?
3. For agent errors: check the `observations` table for the most recent row;
   the `raw_tags` column shows exactly what input the agent got.
4. Hard reset (nuclear): `docker compose down -v && docker compose up -d`
   — **this wipes the databases**. Back up first:
   `docker compose exec postgres-obs pg_dump -U obs_user safeclaw_obs > obs-backup.sql`.
