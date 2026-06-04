# SafeClaw on orgo — External Installation Agent Hand-off

**One document to hand an external "installation agent" so it can deploy a new
SafeClaw client box end-to-end.** It is intentionally thin: it tells the agent
*what to do, in what order, with which inputs* and points at the detailed runbook
for each step. Do not duplicate the runbook here — the source of truth for step
detail is [`ORGO-CLIENT-TEMPLATE.md`](./ORGO-CLIENT-TEMPLATE.md).

> **What "deploy" produces:** a per-client orgo box running Hermes (reader/actor
> trust split) + GBrain, reachable at two Cloudflare URLs, with Telegram + Gmail
> (trust-split) + optional Slack, a nightly dreaming brain, and a dashboard whose
> **Connections** tab lets the customer self-connect accounts and whose
> **Settings** tab shows status + the client handoff URL.

---

## 0. What to give the agent

1. **Repo access** — `github.com/Vasanth19/safeclaw`, branch **`develop`** (has the
   Connections/Settings plugins + `provision-composio.py`). The agent clones this
   onto the box at `/opt/safeclaw`.
2. **The per-client `.env`** — a `<client>.env` file (format in §2). Hold it on the
   operator machine; the agent transfers it to the box (§3).
3. **Box coordinates** — the orgo **workspace API key** + the **computer id (CID)**
   for this client (from the `orgo-jake-workspace` record).
4. **This document** + `ORGO-CLIENT-TEMPLATE.md` + `INSTALL-CHECKLIST.md`.

That's it. Everything else is derived on the box.

---

## 1. Prerequisites (gather before starting)

| Need | Notes |
|------|-------|
| orgo **PAID** workspace key + CID | box must be always-on (`auto_stop_minutes:0, configurable:true`) |
| **Composio** project key (`ak_…`) | per-client project; **org key stays operator-side**, never on box |
| Composio **Gmail OAuth done** by the customer | gives an ACTIVE `connected_account_id` + `user_id` |
| **Ollama Cloud** key(s) | LLM (`glm-4.7`); ≥2 keys for the failover pool |
| **OpenRouter** key | embeddings (`openrouter:openai/text-embedding-3-small`) + dream LLM phases |
| **Telegram** bot token + numeric user id | one dedicated bot per box (via @BotFather) |
| **Slack** (Phase 1, optional) | customer builds their own app → `xoxb`/`xapp`/`T…`/`U…` (Step 12) |
| **Cloudflare** zone (e.g. `growthsystems.ai`) | on the operator Mac's cloudflared cert; no new token |

---

## 2. The per-client env file (`<client>.env`)

Operator fills this; gitignored; `chmod 600`. Variable names match the working
boxes (mark-agent/elise). For a Composio project where the customer already
OAuth'd, fetch `READER_MCP_BASE_URL`/`ACTOR_MCP_BASE_URL` by creating the two MCP
servers (see §4 Step 11) — or run `scripts/provision-composio.py` for a brand-new
project.

```env
CLIENT=acme
CID=<orgo computer id>
HERMES_DEFAULT_MODEL=glm-4.7
# Composio (per-client PROJECT key — never the org key)
COMPOSIO_API_KEY=ak_…
COMPOSIO_USER_ID=client:acme:gmail
CONNECTED_ACCOUNT_ID=ca_…
READER_MCP_BASE_URL=https://backend.composio.dev/v3/mcp/<reader-server-id>
ACTOR_MCP_BASE_URL=https://backend.composio.dev/v3/mcp/<actor-server-id>
# Telegram (dedicated bot)
TELEGRAM_BOT_TOKEN=…
TELEGRAM_ALLOWED_USERS=<numeric id>
# UI / dashboard basic-auth
SAFECLAW_UI_USER=acme
UI_PASSWORD=<generated>
# Slack (Phase 1 — fill when the customer builds their app)
SLACK_BOT_TOKEN=__FILL_IN__
SLACK_APP_TOKEN=__FILL_IN__
SLACK_USER_ID=__FILL_IN__
SLACK_WORKSPACE_ID=__FILL_IN__
# shared infra
ORGO_API_KEY=sk_live_…
ORGO_WORKSPACE_ID=…
OLLAMA_API_KEY=…
OLLAMA_FALLBACK_KEY=…
OPENROUTER_API_KEY=sk-or-…
FIRECRAWL_API_KEY=…            # optional
```

---

## 3. Execution model — how the agent runs commands on the box

orgo boxes have **no SSH and no public ports**; you run shell via the orgo
`/bash` API. Use the bundled helper:

```bash
ORGO_API_KEY=<key> CID=<cid> python3 orgo/orgo_bash.py "<command>"
```

Hard rules (orgo-specific, learned the hard way):
- **Long installs must run in `tmux`** (gbrain/hermes builds) — orgo reaps
  backgrounded `nohup`/`setsid` jobs and the `/bash` call times out at ~180s.
  Launch in a tmux session, then poll a logfile for a sentinel like `EXIT=`.
- **Never pipe an installer to `| tail`** — it masks the exit code. Run bare,
  capture `$?`, read the log separately.
- **Transfer the env without printing secrets:** base64 it locally and decode on
  the box → `echo <base64> | base64 -d > /opt/safeclaw/client.env; chmod 600`.
- orgo throws 502/503/504 bursts for 30–60s — `orgo_bash.py` already retries 6×.

---

## 4. The deploy sequence (follow ORGO-CLIENT-TEMPLATE.md for full detail)

Each step = a `[BOX]`, `[MAC]`, or customer action. The template has the exact
commands + the gotcha notes; this is the spine + the **live-validated specifics**
from the matt-hoover run.

| Step | What | Live-validated notes (2026-06-04) |
|------|------|-----------------------------------|
| **0** | Verify always-on | `GET /computers/$CID/auto-stop` → `{auto_stop_minutes:0, configurable:true}` |
| **1** | Base install | `git clone -b develop … /opt/safeclaw`; `apt install unzip`; **Node 20 tarball** to `/tmp` (the **Hermes installer auto-pulls its own Node 22** for the desktop build — let it); bun (`bun.sh/install`, symlink `/usr/local/bin/bun`); gbrain `git clone garrytan/gbrain` + `bun install` + `bun link` → symlink `/usr/local/bin/gbrain` (HEAD = **0.42.23.0**, good); Hermes via `scripts/setup-hermes.sh` (**0.15.1**, it passes `--skip-setup` itself) — run in tmux, poll for `SETUP_EXIT=0`; symlink hermes from `/opt/hermes/venv/bin/hermes`; `pip install croniter`. **Default profile:** `hermes config set model.provider ollama` + `model.default glm-4.7` (base_url already `https://ollama.com/v1`). **Pool:** `hermes auth add ollama-cloud --type api-key --api-key "$OLLAMA_API_KEY" --label primary` (and `--label fallback` for the 2nd key). |
| **2** | GBrain init + embeddings + HTTP server + seed | `OPENROUTER_API_KEY` exported → `gbrain init --pglite --embedding-model openrouter:openai/text-embedding-3-small`; set `sync.repo_path`; ONE `gbrain serve --http --port 3131` in tmux `brain` + `gbrain auth create --name hermes` token; seed `people/<client>` + first git commit. |
| **3–5** | Profiles + crons | reader+actor profiles (`glm-4.7`, base_url override, gbrain **URL** MCP, separate primary keys); nightly `gbrain dream` Hermes cron; hourly `email-ingest` (set `cron.script_timeout_seconds: 1800`). |
| **6–7b** | Console + dashboard + plugins | Flask Console (tmux `sui`, basic-auth); dashboard `--tui` (tmux `hd`) + actor gateway (tmux `gw`); **Step 7b:** run each plugin's `build.sh` + symlink into `~/.hermes/plugins` → recycle `hd` → tabs **Memory · Personas · Connections · Settings**. |
| **8–9** | Tunnel + watchdog | `[MAC]` cloudflared named tunnel; route DNS **by UUID** for `safeclaw-<client>` + `hermes-<client>.<zone>`; `[BOX]` config.yaml (hermes ingress needs `httpHostHeader: localhost`), tmux `cf`; watchdog tmux `wd` (8899/9119/3131/cf/gw + 4am gateway recycle). |
| **10** | Telegram | bot token + allowed id in **actor `.env` ONLY**; recycle `gw`. |
| **11** | Gmail trust split | If the customer already OAuth'd: create reader + actor **MCP servers** (`POST /api/v3/mcp/servers` with the read-only / draft allowlists, **no `GMAIL_SEND_EMAIL`**), then write each into the matching profile `config.yaml` as a URL MCP `…/mcp?user_id=<uid>&connected_account_id=<ca>` + header `x-api-key`. (`provision-composio.py` does the create for a fresh project.) |
| **12** | Slack (Phase 1) | customer builds their app → paste `xoxb`/`xapp`; wire `slack_native` MCP (reader read-only, actor post) + Socket Mode on actor. **Deferrable** — box is fully usable without it. |
| **13 / 13b** | Verify + hand off | both URLs right codes; `tmux ls` = 6 (`brain cf gw hd sui wd`); brain answers about the client; dream proven. **13b:** Settings tab → copy the credential-embedded handoff URL → customer opens it → clicks each connector on the Connections tab. |
| **14** | Golden snapshot | `POST /computers/{id}/clone` once validated. |

---

## 5. Definition of done

- `https://safeclaw-<client>.<zone>` → 401 no-auth / 200 with auth
- `https://hermes-<client>.<zone>` → 200, tabs Memory·Personas·Connections·Settings
- `tmux ls` → `brain cf gw hd sui wd`
- brain answers a `<client>` question (not "I don't know"); `dream.log` shows 11 phases
- Telegram round-trip; Gmail drafts-only (never sends); (Slack if wired)
- Settings checklist green; customer has the handoff URL

## 6. Reference docs (in the repo)
- **`orgo/ORGO-CLIENT-TEMPLATE.md`** — full step detail + every gotcha (READ THIS PER STEP)
- `orgo/INSTALL-CHECKLIST.md` — one-page checkbox version
- `orgo/client.env.example` — env template
- `orgo/access/` — Caddyfile + cloudflared examples
- `scripts/provision-composio.py` — operator-side Composio project provisioning
- `dashboard-plugins/*/README.md` — per-plugin detail

> **Honest note:** this is a *guided runbook with verification gates*, not a
> one-command installer. The gates exist because orgo `/bash` is flaky and a few
> steps need judgment. If a fully scripted installer is wanted, it is a separate
> build on top of this spine.
