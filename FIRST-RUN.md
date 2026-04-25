# SafeClaw — First-Run Guide

You're reading this because the infrastructure tier has been deployed and is
running on this machine. The "brain" (Hermes) is built but not yet started —
it needs a couple of API keys and OAuth connections before it can work.

This guide walks you through the remaining steps to get from "infrastructure
running" → "assistant actively helping you".

---

## Current state (what's already running)

As of the automated setup, the following services are up on OrbStack:

| Service | Status | Endpoint |
|---|---|---|
| `postgres-obs` (pgvector) | healthy | internal only |
| `postgres-tasks` | healthy | internal only |
| `postgrest` (Task REST API) | healthy | `http://localhost:3001` |
| `nango` (OAuth vault) | healthy | `http://localhost:3003` |
| `embedder` (semantic memory) | healthy | `http://localhost:8000` |
| `tasks-api-mcp` | idle, ready | stdio via `docker exec` |
| `brain-api-mcp` | idle, ready | stdio via `docker exec` |

Databases: 17 tables in `safeclaw_obs` (event log + Brain layer),
3 tables in `safeclaw_tasks` (tasks + comments + transitions).
Vector extension `vector 0.8.2` + trigram `pg_trgm 1.6` installed.

**What is NOT running yet:**
- `hermes-reader` — the intake agent (needs LLM API key)
- `hermes-actor` — the write/action agent (needs LLM API key + Phase 2 flag)
- `reflector` — the weekly soul-update worker (needs LLM API key)

All three are waiting on `HERMES_LLM_API_KEY` in `.env`.

---

## Step 1 — Add your LLM API key

Edit `/Users/vasanth/Clients/rspur/ai-assistant/.env` and set:

```bash
HERMES_LLM_API_KEY=sk-ant-...           # your Anthropic key (recommended)
HERMES_LLM_BASE_URL=https://api.anthropic.com/v1
HERMES_MODEL=claude-sonnet-4-6
```

Get an Anthropic key at https://console.anthropic.com/settings/keys — pick a
project-scoped key, not the admin key.

Alternatives: OpenAI (`https://api.openai.com/v1`, `gpt-4o`) or a local
Ollama instance (`http://host.docker.internal:11434/v1`, `hermes3:latest`).

---

## Step 2 — Create a Google Cloud OAuth client

The assistant connects to Gmail, Drive, and eventually Calendar via a single
Google OAuth 2.0 client you own. You only do this once.

1. Go to https://console.cloud.google.com/
2. Create a new project called `safeclaw-<yourname>` (or reuse an existing one).
3. In the left nav: **APIs & Services → Library**. Enable:
   - Gmail API
   - Google Drive API
   - (optional) Google Calendar API
4. **APIs & Services → OAuth consent screen**:
   - User Type: **External**
   - App name: `SafeClaw Assistant`
   - Support email: your email
   - Developer email: your email
   - Scopes: skip for now (Nango handles scope requests per-connection)
   - Test users: **add every Gmail address you plan to connect** (up to 100)
   - Publishing status: leave as **Testing** for now. (Testing-mode refresh
     tokens expire after 7 days — fine for initial setup; flip to Production
     once you've verified the assistant works. See §Gotchas.)
5. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**
   - Name: `SafeClaw — Nango`
   - Authorized redirect URIs: **`http://localhost:3003/oauth/callback`**
   - Click Create. Copy the **Client ID** and **Client secret**.

6. Paste into `.env`:
   ```
   GOOGLE_CLIENT_ID=<paste>.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=<paste>
   ```

---

## Step 3 — Register integrations in Nango

Nango's dashboard is your OAuth control panel. It lives at
http://localhost:3003 — open it in your browser.

For each of the four integrations below, click **Integrations → Configure New
Integration** and fill these fields:

### (a) gmail-readonly — for Gmail inbox monitoring
| Field | Value |
|---|---|
| Provider | `google` |
| Integration Unique Key | `gmail-readonly` |
| Client ID | *(paste your Google Client ID)* |
| Client Secret | *(paste your Google Client Secret)* |
| Scopes | `https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.labels` |

### (b) gmail-draft — for composing drafts the actor can write
| Field | Value |
|---|---|
| Provider | `google` |
| Integration Unique Key | `gmail-draft` |
| Scopes | `https://www.googleapis.com/auth/gmail.compose` |

### (c) google-drive-file — for the monitored Drive folder
| Field | Value |
|---|---|
| Provider | `google` |
| Integration Unique Key | `google-drive-file` |
| Scopes | `https://www.googleapis.com/auth/drive.file` |

(Same Client ID / Secret as the others.)

### (d) slack-bot — for the control channel
Come back to this after you've done Step 5 (Slack app).

---

## Step 4 — Connect your Gmails

For each Gmail address you want to monitor (up to 3):

1. In Nango → **Connections** → **Add Connection**.
2. Pick integration `gmail-readonly`.
3. Connection ID: use the email address itself (e.g. `vasanth@hyphenlabs.com`).
4. Click **Authenticate**. Google OAuth opens in a new tab → pick the account
   → grant access. You'll be bounced back to Nango with ✓ Connected.
5. Repeat for `gmail-draft` with the **same** Connection ID for each inbox.

Do the same for `google-drive-file` — one connection per Drive account whose
folder you want mirrored.

> The Connection ID is how the assistant refers to each inbox. Use the
> email address — it's stable and readable.

---

## Step 5 — Create the Slack app

The assistant posts approval cards to a channel named `#safeclaw-review`.
Every draft, scheduled send, and flagged alert surfaces there. You click ✅
or ❌ on each card.

1. Go to https://api.slack.com/apps → **Create New App** → From scratch.
   - Name: `SafeClaw`
   - Workspace: pick the one you use daily.

2. **OAuth & Permissions** → **Scopes → Bot Token Scopes**. Add:
   - `channels:read`
   - `channels:history`
   - `chat:write`
   - `im:history` *(optional — only if you want DM context)*
   - `reactions:write`

3. **Socket Mode** → toggle ON → generate an App-level token with scope
   `connections:write`. Copy the `xapp-...` token.

4. **OAuth & Permissions** → **Install to Workspace**. Copy the bot token
   `xoxb-...`.

5. In your Slack workspace, **create a channel `#safeclaw-review`**, then invite
   the bot: type `/invite @SafeClaw` in the channel.

6. Get the channel ID: right-click the channel name → View channel details →
   bottom of the modal shows the Channel ID `C0XXXXXXXX`.

7. Paste into `.env`:
   ```
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   SLACK_REVIEW_CHANNEL_ID=C0XXXXXXXX
   ```

8. Back in Nango: register integration **slack-bot** (provider `slack`), then
   add a connection using these tokens so the actor's Slack MCP tool can read
   via Nango as well.

---

## Step 6 — Start Hermes (the brain)

Now that `.env` has the LLM key and at least one Gmail connected:

```bash
cd /Users/vasanth/Clients/rspur/ai-assistant
docker compose up -d --build hermes-reader
```

The first build takes **8–15 min** — Hermes is built from source (Python,
`uv`, Playwright browsers). Watch progress:

```bash
docker compose logs -f hermes-reader
```

When you see `gateway ready` and `listening on ...`, the reader is live.

To enable the actor (drafts + Slack posts), set `ACTOR_ENABLED=true` in
`.env`, then:

```bash
docker compose up -d hermes-actor
```

---

## Step 7 — Bootstrap the Brain with your history

Once the reader is live and Gmail is connected, seed the Brain with 90 days
of your sent mail:

```bash
bash scripts/bootstrap-brain.sh
```

This scrapes your Sent folder to extract style samples, key contacts, and
relationship graph. Runs once, ~5 min per inbox. Logs into `postgres-obs`
(tables `style_samples`, `entities`, `relationships`).

---

## Daily operator commands

| What you want | Command |
|---|---|
| See all services | `docker compose ps` |
| Tail reader logs | `docker compose logs -f hermes-reader` |
| See recent observations | `docker compose exec postgres-obs psql -U obs_user -d safeclaw_obs -c 'SELECT sender, subject, is_critical, processed_at FROM observations ORDER BY processed_at DESC LIMIT 20;'` |
| See pending approvals | *Look at `#safeclaw-review` in Slack.* |
| Shut everything down | `docker compose down` |
| Start again | `docker compose up -d` |
| Apply schema changes | `docker compose cp db/NEW.sql postgres-obs:/tmp/ && docker compose exec postgres-obs psql -U obs_user -d safeclaw_obs -f /tmp/NEW.sql` |

---

## How the assistant actually helps you (day to day)

1. **Emails arrive** → Reader sees them via Nango → writes a structured
   observation to `postgres-obs`. If the email matches critical rules
   (sender in allowlist AND subject matches financial/legal/urgent patterns),
   a card appears in `#safeclaw-review`.

2. **You mention the bot in Slack** (`@SafeClaw draft a reply to Alice about
   the closing`) → Actor looks up Alice in the Brain, pulls 3-5 of your
   past emails to her as style samples, drafts a reply in **your** voice,
   creates a Gmail draft. Posts a card to `#safeclaw-review` with a preview.

3. **You click ✅** on the card → draft stays in your Gmail drafts folder
   for you to review and send (Phase 1). After 30 days clean you can flip
   `AUTO_SEND_ENABLED=true` and the assistant will send on your behalf for
   whitelisted recipients.

4. **Reflector runs weekly** (Monday 6am) → reads your last 7 days of
   approve/reject decisions → proposes updates to your Soul. You confirm
   each proposed rule in Slack.

---

## Gotchas

- **Testing-mode OAuth** — Google refresh tokens issued in Testing mode
  expire after 7 days. Once everything works, publish your OAuth consent
  screen to Production (you may need to verify scopes, Google reviews this
  in 2-4 weeks). Or just re-authenticate weekly in the meantime.

- **Gmail Pub/Sub `historyId` gaps** — Gmail's `watch()` expires after 7
  days. The actor's `gmail_rearm` cron (midnight daily) re-arms it and
  reconciles any missed history. If this cron fails silently, the reader
  stops seeing new mail. Check: `docker compose logs hermes-actor | grep
  gmail_rearm` should show recent success lines.

- **`drive.file` scope** — The assistant can only touch files it created
  or that you explicitly opened with its Drive integration. It cannot
  scan your whole Drive. By design.

- **Nango platform warning** — `nangohq/nango-server` only publishes
  `linux/amd64` images. On Apple Silicon it runs under emulation with a
  platform warning — that's harmless, just slower startup. For production
  on a Mac mini M-series, fine; on a Linux VPS, native.

- **Hermes first build is slow** — Expect 8-15 min the first time. Subsequent
  `docker compose up -d` restarts are fast.

- **Soul file vs DB** — `brain/user.soul.md` is human-readable and
  intended for you to edit. Changes you make there sync to `user_profile`
  on the next reflector run. The DB version is what the agent reads.

---

## Where things live on disk

```
/Users/vasanth/Clients/rspur/ai-assistant/
├── .env                    ← secrets (chmod 600, NEVER commit)
├── docker-compose.yml      ← the stack definition
├── config/                 ← Hermes reader/actor YAML
├── db/                     ← SQL migrations
├── brain/                  ← human-editable memory
│   ├── user.soul.md.template
│   └── entities/           ← per-entity markdown (populated over time)
├── mcp-tools/              ← tasks-api + brain-api MCP servers (TypeScript)
├── services/               ← embedder + reflector (Python)
├── vendor/hermes-agent/    ← cloned from NousResearch (gitignored)
└── drive-mirror/           ← rclone'd Drive folder (created on first sync)
```

---

## When something breaks

1. `docker compose ps` — which service is not healthy?
2. `docker compose logs <service> --tail 50` — what's the error?
3. For agent errors: check `observations` table for the most recent row;
   the `raw_tags` column shows exactly what input the agent got.
4. Hard reset (nuclear): `docker compose down -v && docker compose up -d`
   — **this wipes the databases**. Back up first:
   `docker compose exec postgres-obs pg_dump -U obs_user safeclaw_obs > obs-backup.sql`.
