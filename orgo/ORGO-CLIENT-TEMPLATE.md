# SafeClaw on orgo.ai — Canonical Client Deployment Template

> **What this is.** THE single source of truth for deploying the full SafeClaw
> stack (**Hermes reader/actor + GBrain + nightly dreaming + SafeClaw Console +
> Slack/Telegram/Gmail trust-split integrations**) onto a fresh **orgo.ai**
> always-on workspace box for a new customer. It supersedes the older
> Docker-based `orgo/ORGO-DEPLOY.md` and `provision-client.py` (compose, golden
> snapshot, `render-hermes-config`, Caddy gate — all legacy). The proven stack
> is **NATIVE (no Docker)**.
>
> **Audience:** an operator (or an agent) running it top-to-bottom against a
> fresh orgo computer. Every step has commands + a verification + expected
> output. Steps are labelled **[MAC]** (run on the operator's Mac) or **[BOX]**
> (run on the orgo computer via the `/bash` API).
>
> **Worked example throughout:** `mark-agent` in **Jake McKinney's (paid)
> workspace** — the FIRST real end-to-end install (completed 2026-06-01). Stack:
> **Hermes 0.15.1 + gbrain 0.42.1**, tunnel **`safeclaw-mark-v2`**, **6 tmux
> sessions** (`brain`, `cf`, `gw`, `hd`, `sui`, `wd`). Where you see
> `<CLIENT>=mark` substitute your client's slug. This template folds in the **24
> fixes** found during that live install (each tagged "issue N" inline).
>
> **No secrets in this file.** Placeholders: `<ORGO_API_KEY>`, `<CLIENT>`,
> `<CID>` (computer id), `<WSID>` (workspace id), `<TELEGRAM_BOT_TOKEN>`,
> `<TELEGRAM_NUMERIC_USER_ID>`, `<COMPOSIO_API_KEY>`, `<COMPOSIO_USER_ID>`,
> `<CONNECTED_ACCOUNT_ID>`, `<READER_MCP_BASE_URL>`, `<ACTOR_MCP_BASE_URL>`,
> `<OLLAMA_API_KEY>`, `<OLLAMA_FALLBACK_KEY>`, `<OPENROUTER_API_KEY>`,
> `<OPENAI_API_KEY>`, `<GBRAIN_HTTP_TOKEN>`, `<UI_PASSWORD>`, `<TUNNEL_ID>`,
> `<SLACK_BOT_TOKEN>` (`xoxb-…`), `<SLACK_APP_TOKEN>` (`xapp-…`),
> `<SLACK_WORKSPACE_ID>` (`T…`), `<SLACK_USER_ID>` (`U…`).

---

## 1. Overview — what gets deployed

```
                          Internet
                             │
          ┌──────────────────┴───────────────────┐
          │  Cloudflare (TLS, growthsystems.ai)    │
          └──────────────────┬───────────────────┘
                             │  ONE named tunnel, TWO hostnames
                ┌────────────┴────────────┐
                │                         │
 safeclaw-<CLIENT>.growthsystems.ai   hermes-<CLIENT>.growthsystems.ai
                │                         │  (ingress sets httpHostHeader: localhost)
                ▼                         ▼
  ┌─────────────────── ORGO COMPUTER (native, always-on, 16 GB) ────────────────────────┐
  │                                                                                       │
  │  cloudflared (tmux cf) ──► 127.0.0.1:8899  SafeClaw Console (Flask, tmux sui)         │
  │                       └──► 127.0.0.1:9119  Hermes dashboard (--tui, tmux hd)          │
  │                                                                                       │
  │  GBrain HTTP server (tmux brain): ONE gbrain serve --http --port 3131 (single-writer  │
  │    PGLite lock) — ALL Hermes consumers wire it as a URL MCP, never stdio (see Step 2c)│
  │                                                                                       │
  │  Hermes profiles (isolated HERMES_HOME each):                                         │
  │    • default  → dashboard's embedded --tui gateway (NO telegram token, NO slack app)  │
  │    • reader   → gbrain URL MCP + Gmail READ MCP + slack_native(reader, read-only)     │
  │    • actor    → gbrain URL MCP + Gmail DRAFT MCP + slack_native(actor, post) + Telegram│
  │                 gateway (tmux gw) + Slack Socket Mode (ONLY the actor opens it)        │
  │                                                                                       │
  │  Hermes cron (in the actor gateway):  gbrain dream  nightly @ 03:00                   │
  │    (the dream script STOPS the brain tmux session, runs dream, RESTARTS it)           │
  │  GBrain (PGLite, ONE HTTP server :3131 — 88 tools) wired into BOTH profiles as URL MCP│
  │  Embeddings: OpenRouter text-embedding-3-small (required for dream's embed phase)     │
  │  LLM: Ollama Cloud (glm-4.7) — off-box inference (NOT kimi-k2.5; see Step 1 note)     │
  │                                                                                       │
  │  Watchdog (tmux wd): checks 8899/9119/3131/cf/gw, restarts dead, re-syncs clock /30s, │
  │                      nightly 04:00 restarts actor+reader gateways (slack 8h-stale fix) │
  └───────────────────────────────────────────────────────────────────────────────────────┘
```

**What the client gets:**
- A stable Console URL `https://safeclaw-<CLIENT>.growthsystems.ai` (basic-auth):
  Chat working, plus links to the Hermes dashboard.
- A Hermes dashboard URL `https://hermes-<CLIENT>.growthsystems.ai` (operator/
  technical view: Chat, Sessions, Models, Logs, MCP… + Memory/Personas plugins).
- A **self-serve connect page in the Console**: the operator shares one
  credential-embedded URL
  (`https://user:pass@safeclaw-<CLIENT>…/connect-accounts`); the customer clicks
  each connector and OAuths their own accounts — no Composio console, no tokens,
  no `.env`. Each card mints a fresh Composio OAuth link server-side (Step 6).
- A dedicated Telegram bot (their own, from @BotFather) for interactive chat.
- **Slack** wired with a **trust split** ported from the VPS (the better setup):
  a custom stdio MCP whose tools differ by mode — reader can list/read channels,
  actor can post/upload. Only the actor opens the live Socket Mode connection.
- Gmail wired with a **trust split**: reader can only read; actor can only draft —
  never send. Enforced at the Composio MCP allowlist, not by a prompt (see
  `ARCHITECTURE.md` §2.3).
- A brain that **dreams nightly** (11-phase maintenance), keeping retrieval sharp.

---

## 2. Prerequisites

| Need | Detail |
|------|--------|
| **orgo PAID workspace + API key** | **HARD REQUIREMENT.** Must be a paid (Scale) workspace so boxes are always-on (`auto_stop_minutes: 0`, `configurable: true`). A free/Hacker account forces `auto_stop_minutes: 15` / `configurable: false` and the tunnel dies every nap (530/1033). For Jake: **"Jake McKinney's workspace"** id `9898964f-f0f8-4d05-b08c-20b89a2b401d`, owner `jake@rspur.com`. |
| **Cloudflare zone `growthsystems.ai`** | Already a CF zone on the operator Mac's cloudflared (`~/.cloudflared/cert.pem`). **No new API token needed** — the named tunnel is minted from this existing cert. **⚠️ Zone settings pre-flight (one-time, in the CF dashboard):** **Network → WebSockets = ON** and **Security → Bots → Bot Fight Mode = OFF**. If WebSockets is off (or Bot Fight Mode interferes), Cloudflare strips the WS `Upgrade` header and the Hermes dashboard's terminal chat (`/api/pty`) gets 401 through the tunnel even though Hermes accepts the same handshake locally (verified on Mark, 2026-06-01). |
| **Ollama Cloud API key(s)** | LLM inference (`glm-4.7` — the proven agentic model; **NOT** kimi-k2.5, see Step 1). Off-box; keeps the box light. Bring **at least two keys** so the credential pool can fail over on a 429 (Step 1 "Credential pool"). |
| **GBrain source** | The brain engine is cloned + built from `https://github.com/garrytan/gbrain` (bun). No separate account needed; the box clones it in Step 1. |
| **Embeddings key (OpenRouter or OpenAI)** | **NOW REQUIRED — no longer deferred.** GBrain's nightly `dream` has an `embed` phase; Ollama Cloud has **no** `/v1/embeddings` endpoint, so embeddings must come from OpenRouter/OpenAI (`openrouter:openai/text-embedding-3-small`, 1536 dims). **⚠️ Budget note (issue 7):** gbrain **0.42 auto-sets `chat_model = openrouter:openai/gpt-5.2`**, so dream's LLM phases (synthesize/extract/patterns) **bill the same OpenRouter key** — not just embeddings. Expect real OpenRouter spend on every nightly dream; size the key's budget accordingly. |
| **Composio ORG API key** | **Operator-side only — NEVER goes on the box.** Held on your Mac / admin agent; it can create projects across every client. `scripts/provision-composio.py` uses it to create this client's **isolated project** and writes only the per-client **project key** (`COMPOSIO_API_KEY=ak_…`) + reader/actor MCP URLs into `client.env` (Step 11a). The Gmail trust split (reader read-only, actor draft-only) is enforced at that project's MCP allowlists. |
| **Telegram bot PER CLIENT** | One dedicated bot from **@BotFather** per box. Telegram allows exactly one `getUpdates` consumer — a second poller = permanent conflict. |
| **Slack app PER CLIENT** | One Slack app per workspace (Step 11a). Produces `xoxb-` bot token, `xapp-` app token, `T…` workspace id, `U…` user id. |

### Operator helper — calling the orgo /bash API (PURE-PYTHON, retry-hardened)

> **⚠️ Replaced the old bash+curl helper.** During the Mark live install the
> orgo API threw recurring **503/502/connection-refused bursts that lasted
> 30–60+ seconds** at a time. A thin `curl` wrapper silently returned `exit -1`
> with an empty body and the operator could not tell "command failed to land"
> from "command landed but returned nothing." The proven helper is a **pure-Python
> `urllib` client with 6 retries and exponential backoff (5→30 s)**. **Hard rule:
> every deploy command must be VERIFIED to have landed with a separate read-only
> follow-up command — never assume a mutating call succeeded** (issues 1, 19).

Save this as `orgo_bash.py` on the operator Mac and source the wrapper. Every
**[BOX]** command below assumes `orgo_bash "…"` resolves to it.

```bash
export ORGO_API_KEY="<ORGO_API_KEY>"   # the paid-workspace key, NEVER commit
export CID="<CID>"                      # set after Step 0 creates the computer
```

```python
# orgo_bash.py — pure-Python orgo /bash client. urllib only (no deps).
# Usage: python3 orgo_bash.py "command string"
import json, os, sys, time, urllib.request, urllib.error

API_KEY = os.environ["ORGO_API_KEY"]
CID     = os.environ["CID"]
URL     = f"https://www.orgo.ai/api/computers/{CID}/bash"

def run(cmd, retries=6):
    body = json.dumps({"command": cmd}).encode()
    backoff = 5
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                URL, data=body, method="POST",
                headers={"Authorization": f"Bearer {API_KEY}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read().decode()
        except (urllib.error.HTTPError, urllib.error.URLError, ConnectionError, TimeoutError) as e:
            # orgo throws 503/502/connection-refused bursts that last 30-60s.
            last = e
            code = getattr(e, "code", "conn")
            sys.stderr.write(f"[orgo_bash] attempt {attempt}/{retries} failed ({code}); "
                             f"retrying in {backoff}s\n")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)   # 5,10,20,30,30…
    raise SystemExit(f"[orgo_bash] all {retries} attempts failed: {last}")

if __name__ == "__main__":
    print(run(sys.argv[1]))
```

```bash
# Shell wrapper so every [BOX] step can call orgo_bash "<cmd>".
orgo_bash() { python3 /path/to/orgo_bash.py "$1"; }
```

> **/bash API gotchas (apply to EVERY [BOX] step):**
> - **Failure bursts last 30–60+ seconds** (503/502/connection-refused, or
>   `exit_code: -1` with empty output). The Python helper above retries 6× with
>   5→30 s backoff. **Always verify mutating commands with a follow-up read-only
>   command** — never trust the mutating call's own response (issues 1, 19).
> - **NEVER put `sleep N` inside an orgo /bash command** — a long-running
>   in-call sleep trips the API into timeouts/503s. **Pattern:** launch the work
>   in tmux in one call, then *poll status in separate calls*, doing the waiting
>   on the operator's Mac (e.g. a Python `time.sleep` between `orgo_bash` calls),
>   NOT inside the box command (issue 13). (The few `sleep 3/5/8` in this doc are
>   short, post-`tmux new-session` settles — keep them tiny; never `sleep 30+`.)
> - **The `pkill -f` self-kill trap is worse than it looks.** `pkill -f
>   "<string>"` matches your *own* command's FULL cmdline **including heredoc
>   contents** — so if your command writes a launcher script that contains the
>   text `gbrain serve` and you also `pkill -f "gbrain.*serv[e]"`, you kill your
>   own in-flight command. **Kill by PID (`ps … | … | kill`) or by exact name
>   (`pkill -x <exactname>`) only** — never `pkill -f` on a string that appears
>   anywhere in the command you're sending (issue 23).
> - `nohup`/`setsid` background jobs get **reaped** by orgo. **Only tmux
>   survives.** No systemd, no cron/crontab on orgo boxes. (Hermes has its OWN
>   in-process cron — that's what runs `gbrain dream`, Step 4.)

---

## 3. Naming convention (per client)

| Thing | Pattern | Worked example (`<CLIENT>=mark`) |
|-------|---------|----------------------------------|
| orgo workspace | Jake's paid workspace | `9898964f-f0f8-4d05-b08c-20b89a2b401d` |
| orgo computer | `<CLIENT>-agent` | `mark-agent` (`7136d3d6-dde9-4888-a564-ffecc7ebe763`) |
| Console hostname | `safeclaw-<CLIENT>.growthsystems.ai` | `safeclaw-mark.growthsystems.ai` |
| Hermes dash hostname | `hermes-<CLIENT>.growthsystems.ai` | `hermes-mark.growthsystems.ai` |
| Cloudflare tunnel | `safeclaw-<CLIENT>` | `safeclaw-mark-v2` (the `-v2` is the split-brain re-point — issue 17, Step 8a) |
| Telegram bot | client's own, e.g. `@<CLIENT>_outbound_bot` | `@mark_outbound_bot` |
| Slack app | `<Client> Assistant` | `Mark's Assistant` |

---

## Step 0 — Create workspace + computer, verify ALWAYS-ON  **[MAC]**

> **This is the load-bearing step.** The *old* free-account "Mark" box was
> created under a free account, which forced `auto_stop_minutes: 15` /
> `"configurable": false`. It napped after 15 min idle → the tunnel went down
> with Cloudflare **530 / error 1033** every time, and the VM clock drifted
> ~24 h (breaking TLS / Telegram / Composio auth). The **new** reference box
> `mark-agent` lives in **Jake's paid workspace** and is **always-on**. **Do not
> proceed past this step until always-on is confirmed.**
>
> **⚠️ Two "Mark" boxes existed — use the right one.** There was a retired
> **FREE-account** box (`cd6ec0dc-8d5c-49e5-9bba-0082c95c0b0e`, under
> `mark@rspur.com`, suspends every 15 min) and the current always-on
> **`mark-agent`** (`7136d3d6-dde9-4888-a564-ffecc7ebe763`) in Jake's PAID
> workspace. Always use the paid `mark-agent`. If you land on an older note
> citing the `cd6ec0dc…` id, it's the wrong (free) box — verify with
> `GET /api/me` (account) + `GET …/auto-stop` (`configurable: true`) before
> proceeding.

**0a. Confirm you're on the right (paid) account:**

```bash
curl -s "https://www.orgo.ai/api/me" -H "Authorization: Bearer $ORGO_API_KEY"
```
Expected: JSON whose account is **Jake's paid workspace owner** (`jake@rspur.com`),
NOT a free personal address. If it's the wrong account, STOP — wrong key.

**0b. Create the computer** inside Jake's paid workspace, named `<CLIENT>-agent`
(reference: `mark-agent`, Ubuntu 24.04.4, 4 CPU, 16 GB RAM, 30 GB disk, with
`tmux`/`git`/`python3`/`node` preinstalled). orgo API base is
`https://www.orgo.ai/api`; computers are addressed as `/computers/{id}`.

```bash
# Create the box in Jake's paid workspace and capture its id into $CID.
CID=$(curl -s -X POST "https://www.orgo.ai/api/computers" \
  -H "Authorization: Bearer $ORGO_API_KEY" -H "Content-Type: application/json" \
  -d '{"workspace_id":"9898964f-f0f8-4d05-b08c-20b89a2b401d","name":"<CLIENT>-agent"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
export CID
echo "CID=$CID"   # record this — every [BOX] step needs it
```

> If the POST body shape differs on your orgo plan (image/size keys), inspect an
> existing box's JSON first: `GET /api/computers` and mirror its fields. The only
> hard requirements are `workspace_id` = Jake's paid workspace and a unique
> `name`; size/image default to the paid-plan box (4 CPU / 16 GB / 30 GB).

**0c. Verify + force always-on (the load-bearing check):**

```bash
# Is auto-stop configurable on this plan?
curl -s "https://www.orgo.ai/api/computers/$CID/auto-stop" \
  -H "Authorization: Bearer $ORGO_API_KEY"
# Expected: {"configurable": true, "auto_stop_minutes": <n>}
#  → "configurable": false  ⇒ WRONG ACCOUNT (free/Hacker). STOP.

# Turn always-on ON (0 = never auto-stop):
curl -s -X PATCH "https://www.orgo.ai/api/computers/$CID/auto-stop" \
  -H "Authorization: Bearer $ORGO_API_KEY" -H "Content-Type: application/json" \
  -d '{"auto_stop_minutes": 0}'
# Expected: 200 with auto_stop_minutes: 0.
#  → 403 ⇒ WRONG ACCOUNT (free plan can't PATCH auto-stop). STOP.
```

**Verify:**
```bash
orgo_bash "echo BOX_OK && uname -a && nproc && free -g | awk '/Mem/{print \$2\"GB\"}'"
```
Expected: `BOX_OK` + a Linux uname line + `4` + `~15GB`. (Retry on flaky `-1`.)

> **16 GB note.** The new boxes relax the old 4 GB constraints (you *can* run
> both gateways hot now), but the native no-Docker approach stays — it is the
> proven path. Local Ollama is still off the table (no GPU; embeddings still
> come from OpenRouter, LLM still from Ollama Cloud).

---

## Step 1 — Base software install (native, NO Docker)  **[BOX]**

```bash
orgo_bash 'set -e
# repo (track main — new client deploys follow main, NOT the Suffolk branch)
git clone -b main https://github.com/Vasanth19/safeclaw /opt/safeclaw 2>/dev/null || \
  (cd /opt/safeclaw && git fetch && git reset --hard origin/main)
# python deps for the Console + provisioning.
# NOTE: unzip is REQUIRED — bun s installer unzips its release and fresh
# Ubuntu 24.04 orgo boxes do NOT ship unzip (issue 2). Without it the bun
# install in the next block fails silently and gbrain never builds.
apt-get update -y && apt-get install -y python3-pip unzip
pip3 install --break-system-packages flask pyyaml requests
# Node 20 static tarball — vite (Hermes web) AND the Slack MCP build need Node 20+
cd /tmp && curl -fsSLO https://nodejs.org/dist/v20.18.1/node-v20.18.1-linux-x64.tar.xz \
  && tar xf node-v20.18.1-linux-x64.tar.xz
ln -sf /tmp/node-v20.18.1-linux-x64/bin/node  /usr/local/bin/node
ln -sf /tmp/node-v20.18.1-linux-x64/bin/npm   /usr/local/bin/npm
ln -sf /tmp/node-v20.18.1-linux-x64/bin/npx   /usr/local/bin/npx
# cloudflared MUST be on the BOX (Step 8 runs the tunnel here, Step 9 watchdog
# restarts it). Without this the tunnel never comes up → neither public URL works.
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared
echo BASE_DONE'
```

**Verify the base layer (Node + cloudflared both resolve):**
```bash
orgo_bash 'node --version && cloudflared --version'
```
Expected: `v20.18.1` and a `cloudflared version …` line. If `cloudflared:
command not found`, Step 8's tunnel will never start.

Install **gbrain** and **Hermes**. **Do NOT wire the brain into Hermes here** —
all gbrain MCP wiring now happens **after Step 2** (issue 5: `hermes mcp add
gbrain` validates by spawning `gbrain serve`, which fails/hangs on an
uninitialized brain — and the final wiring is a *URL* MCP to the HTTP server, not
stdio; see Step 2c).

> **Hermes version decision (per hermes_internals notes).** Hermes **0.11**
> already ships the in-process **cron** scheduler we need for dreaming (Step 4),
> so 0.11 is the *floor*. Install **0.15.1** when available — its dashboard
> supports `--skip-build` (lets us skip the heavy vite build at launch). If you
> are pinned to 0.11, the only difference is you cannot pass `--skip-build` and
> must pre-build the web bundle once (`cd /opt/hermes/web && npm run build`).
> Cron is present in both; **the gateway must be running for cron to fire.**

> **⚠️ NEVER pipe the install script through `| tail -N`** (issue 4). A pipe
> masks the script's exit code (`set -o pipefail` is not on by default), so a
> failed Hermes install looks like success. **Run `setup-hermes.sh` bare, check
> its exit status, THEN tail the log** — as the block below does.

```bash
orgo_bash 'set -e
export PATH=/tmp/node-v20.18.1-linux-x64/bin:$PATH
# --- gbrain (bun CLI) — source is github.com/garrytan/gbrain ---
curl -fsSL https://bun.sh/install | bash && export PATH="$HOME/.bun/bin:$PATH"
# 🚨 CRITICAL: gbrain s shebang is `#!/usr/bin/env bun`. Symlink BOTH gbrain AND
# bun globally (issue 21). Without the bun symlink, every NON-interactive spawn
# of gbrain (the HTTP server, the dream cron, the watchdog, the Console) dies with
#   /usr/bin/env: bun: No such file or directory
# even though gbrain resolves on PATH.
ln -sf /root/.bun/bin/bun /usr/local/bin/bun
# NO "|| true" here — a failed clone must abort, not silently leave gbrain absent.
git clone https://github.com/garrytan/gbrain.git /opt/gbrain-src
(cd /opt/gbrain-src && bun install && bun link)
# Make gbrain globally resolvable in EVERY fresh orgo /bash shell (and the dream
# cron + Console /api/chat) — do not rely on a PATH export persisting.
ln -sf "$(command -v gbrain)" /usr/local/bin/gbrain
echo GBRAIN_INSTALLED'

# --- Hermes (>=0.11 for cron; prefer 0.15.1). Run BARE, then check exit. ---
orgo_bash 'set -e
export PATH=/tmp/node-v20.18.1-linux-x64/bin:$PATH
bash /opt/safeclaw/scripts/setup-hermes.sh; echo "SETUP_HERMES_EXIT=$?"'
# Verify SETUP_HERMES_EXIT=0 in the output BEFORE proceeding. If you want the log,
# read it in a SEPARATE call (never `... | tail` the install itself — issue 4):
orgo_bash 'tail -20 /var/log/setup-hermes.log 2>/dev/null || echo "(no log file)"'

# --- default profile: LLM = Ollama Cloud glm-4.7 (NOT kimi-k2.5, see note) ---
orgo_bash 'set -e
export HERMES_HOME=/root/.hermes
hermes config set model.provider ollama
hermes config set model.default glm-4.7
# 🚨 CRITICAL base_url fix (issue 20): Hermes 0.15.1 s installer ships
#   model.base_url: https://openrouter.ai/api/v1
# in the DEFAULT config. Setting model.provider=ollama does NOT change it, and the
# provider resolver then DEMANDS an OPENROUTER_API_KEY for chat. EVERY profile
# (default here; reader/actor in Step 3) MUST repoint base_url at Ollama Cloud:
hermes config set model.base_url https://ollama.com/v1
echo "OLLAMA_API_KEY=<OLLAMA_API_KEY>" >> /root/.hermes/.env
# NOTE: gbrain MCP is NOT added here — it is wired as a URL MCP after Step 2 (Step 2c).
echo STACK_DONE'
```

> **⚠️ Model choice — use `glm-4.7`, NOT `kimi-k2.5`.** kimi-k2.5 is a *reasoning*
> model: it thinks ~3.7 min/step under the real ~78-tool agentic load, so ingest
> never completes and you reproduce a multi-hour hang the team already debugged.
> `glm-4.7` is the proven agentic model (~1.0 s/step, clean tool-calls). See
> `knowledge/gotchas/ollama-cloud-models-and-limits.md` for the full scorecard
> (`glm-5` / `minimax-m2` are acceptable fallbacks; avoid `glm-4.6` parser bug,
> `gpt-oss` empty-content, and the `qwen3` variants).

**Verify Hermes + gbrain + bun all resolve and base_url is repointed:**
```bash
orgo_bash 'export HERMES_HOME=/root/.hermes
which hermes
hermes --version
which gbrain
which bun
gbrain --version
hermes config show | grep -i base_url'
```
Expected: `/usr/local/bin/hermes`, a Hermes version `>= 0.11`,
`/usr/local/bin/gbrain`, `/usr/local/bin/bun`, a gbrain version line (gbrain
**0.42.x**), and `model.base_url: https://ollama.com/v1` (NOT openrouter — issue
20). If `which hermes`, `which gbrain`, or `which bun` is empty, STOP — nothing
downstream will work (the missing `bun` symlink is issue 21; every non-interactive
gbrain spawn fails without it). The gbrain MCP is wired in Step 2c; Hermes
answering from the brain end-to-end is verified in Step 13.

### Step 1 (cont.) — Credential pool (multi-key Ollama failover)  **[BOX]**

A **single** `OLLAMA_API_KEY` means one weekly/session 429 stalls the whole
pipeline. Hermes ships a **credential pool** that auto-rotates between keys per
provider on a 429 — add at least one fallback. Pool entry `#1` is auto-derived
from the env `OLLAMA_API_KEY`; add `#2…` via `hermes auth add`.

```bash
orgo_bash 'export HERMES_HOME=/root/.hermes
# provider id is ollama-cloud (NOT "custom" — that is only the config.yaml wrapper)
hermes auth add ollama-cloud --type api-key --api-key <OLLAMA_FALLBACK_KEY> --label fallback
hermes auth list   # expect: ollama-cloud (2 credentials): env entry + fallback'
```

> **Load-bearing credential-pool gotchas** (from
> `knowledge/patterns/hermes-credential-pool-multi-key.md`):
> 1. **The pool is CACHED at gateway startup.** After any `hermes auth add` you
>    MUST recreate/restart the gateway (`tmux kill-session -t gw` then relaunch,
>    Step 7) or the new key never rotates in — a long-running gateway keeps its
>    cached single-entry pool. (On a fresh box you add the pool *before* Step 7
>    starts the gateway, so this is automatic; mind it on later edits.)
> 2. **A pool entry can be REVOKED (HTTP 401), not just exhausted (429),** and
>    rotation will happily rotate to a dead key. Probe BOTH keys directly with
>    the curl in the gotcha before trusting the pool.
> 3. **`last_status: exhausted` persists in `auth.json` across restarts** — clear
>    it with `hermes auth reset ollama-cloud` once the session/weekly wall lifts.
> 4. Provider id is **`ollama-cloud`**, never `custom`.

This same pool is added to the reader and actor profiles in Step 3.

---

## Step 2 — GBrain init (PGLite) + EMBEDDINGS + sync repo  **[BOX]**

> **🚨 INSTALLED ≠ INITIALIZED.** Step 1 only puts the `gbrain` binary on disk.
> Until `gbrain init` runs **with an embedding provider (the OpenRouter API key)**,
> the brain is **not active at all**: Hermes and the agents **cannot connect to
> it** (the gbrain MCP has nothing to serve), the Console dashboard shows
> **0 brain pages**, `gbrain` CLI says "No brain configured", the dream embed
> phase no-ops, and semantic search is dead. This step is REQUIRED on every box —
> never skip it, never defer it. The OpenRouter key comes from the credential
> staging (`workspace.env` / `~/.gsai/secrets.env`) and goes into BOTH the init
> shell and `/opt/brain/.env`.
> (setup-hermes.sh now prints a guard warning if it detects this state; the
> Console SYSTEM TEST card has an "Embeddings" check that fails on it.)

GBrain initialises as PGLite (serverless, on-box). **Embeddings are now required**
because the nightly `dream` (Step 4) runs an `embed` phase, and Ollama Cloud has
**no** embeddings endpoint.

> **⚠️ gbrain 0.42 changed init — the old file-config hack is OBSOLETE (issue 6).**
> In 0.42 the embedding model is passed **at init time** with
> `--embedding-model`. Plain `gbrain init --pglite` **stalls on an interactive
> provider prompt** (orgo /bash is non-interactive → it hangs forever). The
> earlier Step-2 python edit of `.gbrain/config.json` is **deleted** — do not use
> it. `OPENROUTER_API_KEY` MUST be exported **in the same shell as init**.

```bash
orgo_bash 'set -e
export GBRAIN_HOME=/opt/brain
export PATH=/usr/local/bin:$HOME/.bun/bin:$PATH
export OPENROUTER_API_KEY=<OPENROUTER_API_KEY>   # MUST be in the init shell
# NO "2>/dev/null || true" — if gbrain failed to install in Step 1, init MUST
# fail loudly here. Embedding model is passed AT INIT (0.42; issue 6):
gbrain init --pglite --embedding-model openrouter:openai/text-embedding-3-small
# embedding key in the gbrain env (reused by the HTTP server + dream later)
echo "OPENROUTER_API_KEY=<OPENROUTER_API_KEY>" >> /opt/brain/.env
echo BRAIN_INIT_DONE'
```

> **OpenAI key instead of OpenRouter?** gbrain supports both. With an OpenAI key,
> pass `--embedding-model openai:text-embedding-3-small` (same 1536 dims) and put
> `OPENAI_API_KEY` in `/opt/brain/.env` (and the Step 4 dream cron) in place of
> `OPENROUTER_API_KEY`.

### Step 2 (cont.) — sync repo (so dream's filesystem phases run)  **[BOX]**

> **A DB-only PGLite brain SKIPS dream's filesystem phases** (lint / backlinks /
> sync / synthesize / patterns) (issue 14). dream needs a git working tree to
> sync against. **REQUIRED:** create a git repo and point `sync.repo_path` at it,
> and make **≥1 commit** (the `sync` phase fails with zero commits).

```bash
orgo_bash 'set -e
export GBRAIN_HOME=/opt/brain PATH=/usr/local/bin:$HOME/.bun/bin:$PATH
mkdir -p /opt/brain/repo && cd /opt/brain/repo
git init
git config user.email "brain@safeclaw.local"
git config user.name  "SafeClaw Brain"
gbrain config set sync.repo_path /opt/brain/repo
echo SYNC_REPO_DONE'
```

(The first commit is made in Step 2b, right after the seed page is written.)

**Verify init + embeddings + sync repo:**
```bash
orgo_bash 'export GBRAIN_HOME=/opt/brain PATH=/usr/local/bin:$HOME/.bun/bin:$PATH
gbrain config show 2>/dev/null | grep -iE "embedding_model|repo_path"
export OPENROUTER_API_KEY=<OPENROUTER_API_KEY>; gbrain embed --stale 2>&1 | tail -3'
```
Expected: `embedding_model` = `openrouter:openai/text-embedding-3-small`,
`sync.repo_path` = `/opt/brain/repo`, and an embed run with NO
`ZEROENTROPY_API_KEY` error (0 stale on a fresh brain is fine).

---

## Step 2c — ONE persistent GBrain HTTP server (PGLite single-writer lock)  **[BOX]**

> **🚨 THE most important architecture change from the Mark install (issue 22).**
> **PGLite allows exactly ONE writer process.** If every Hermes consumer (the
> actor gateway + the dashboard `--tui` gateway + every Console chat) spawns its
> **own** `gbrain serve` stdio MCP, they all fight for the single PGLite writer
> lock and all but one fail with **`GBrain: Timed out waiting for PGLite lock`**.
> The old stdio `hermes mcp add gbrain --command gbrain --args serve` pattern
> CANNOT work with multiple consumers — it is **replaced** by ONE shared HTTP
> brain server that every profile reaches as a **URL MCP** (this mirrors the
> original VPS architecture).

**2c-a. Launcher + persistent HTTP server in tmux `brain`.** The launcher exports
`GBRAIN_HOME`, `PATH`, and sources `/opt/brain/.env` so the server has the embed
key:

```bash
orgo_bash 'cat > /opt/launch-brain.sh <<"EOF"
#!/usr/bin/env bash
export GBRAIN_HOME=/opt/brain
export PATH=/usr/local/bin:/root/.bun/bin:$PATH
set -a; [ -f /opt/brain/.env ] && . /opt/brain/.env; set +a
exec gbrain serve --http --port 3131
EOF
chmod +x /opt/launch-brain.sh
tmux kill-session -t brain 2>/dev/null
tmux new-session -d -s brain /opt/launch-brain.sh
echo BRAIN_HTTP_UP'
```

**2c-b. Mint a bearer token for Hermes.**

> **🚨 ORDER FIX (found live on elise-losasso): mint the token BEFORE starting
> the HTTP server (i.e. run 2c-b's `gbrain auth create` first, or stop the
> `brain` tmux session around it).** `gbrain auth create` is a CLI **write** —
> it needs the PGLite writer lock that the just-started `gbrain serve --http`
> already holds. Running it with the server up doesn't error: it **hangs**, the
> orgo /bash call 504s, the retries pile up more hung copies, and the box's
> whole /bash executor wedges for several minutes (every later call 504s until
> the lock timeouts fire). Token first → then start the server.

> **⚠️ `gbrain auth create` needs the `--name` flag** (issue 22b). A *positional*
> name (`gbrain auth create hermes`) just prints usage and creates nothing.

```bash
orgo_bash 'export GBRAIN_HOME=/opt/brain PATH=/usr/local/bin:/root/.bun/bin:$PATH
# Mint, then capture the token into a chmod-600 file the wiring step reads.
gbrain auth create --name hermes | tee /opt/brain/.hermes-token.raw
# Extract just the token (a gbrain_… string) into the final file:
grep -oE "gbrain_[A-Za-z0-9]+" /opt/brain/.hermes-token.raw | head -1 > /opt/brain/.hermes-token
chmod 600 /opt/brain/.hermes-token && rm -f /opt/brain/.hermes-token.raw
test -s /opt/brain/.hermes-token && echo TOKEN_SAVED'
```

**2c-c. Wire gbrain as a URL MCP into EVERY profile** (default + reader + actor)
via PyYAML — same pattern as the Gmail MCP (Step 11). Each profile points at the
one HTTP server with a Bearer header:

```bash
orgo_bash 'TOKEN=$(cat /opt/brain/.hermes-token); export TOKEN
python3 - <<"PY"
import os, yaml, pathlib
token = os.environ["TOKEN"]
for role, home in {
    "default": "/root/.hermes",
    "reader":  "/root/.hermes/profiles/reader",
    "actor":   "/root/.hermes/profiles/actor",
}.items():
    cfg_path = pathlib.Path(home) / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    cfg = cfg or {}
    cfg.setdefault("mcp_servers", {})["gbrain"] = {
        "url": "http://127.0.0.1:3131/mcp",
        "headers": {"Authorization": f"Bearer {token}"},
        "timeout": 120, "connect_timeout": 30,
    }
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    print("wired gbrain URL MCP into", cfg_path)
PY'
```

> **Why a URL MCP, not `hermes mcp add gbrain --command gbrain --args serve`:**
> the stdio form spawns a *new* `gbrain serve` per consumer → PGLite lock fight
> (issue 22). The reader/actor profiles do not exist yet at this point if you run
> 2c before Step 3 — run **Step 3 first**, then 2c-c, OR (proven on Mark) run 2c-a
> and 2c-b here and fold 2c-c in right after Step 3 creates the profiles. Either
> way: **every profile gets the URL MCP; none gets a stdio gbrain.**

**Verify the HTTP brain server is alive (405 on a bare GET = healthy MCP endpoint):**
```bash
orgo_bash 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3131/mcp'
```
Expected: `405` (the MCP endpoint rejects a plain GET — that IS the alive signal;
a connection failure means the `brain` tmux session died — check `tmux ls`).

---

## Step 2b — Seed the brain (identity + client page)  **[BOX]**

A brand-new PGLite brain is **empty** — so the dream `embed` phase has nothing to
embed (its "no ZEROENTROPY error" verify passes trivially but proves nothing) and
Step 13's deliverable (`hermes chat "what do you know about <CLIENT>?"`) returns
nothing. Seed **at least one identity/client page** so embeddings exist on a real
page and the end-to-end chat answer references seeded content.

> **⚠️ `gbrain put-page` does NOT exist in 0.42 (issue 8).** The command is
> `gbrain put <slug>` reading the page body from **stdin**:
> `gbrain put <slug> < file.md`. Also: **0.42 auto-embeds at put time**, so seeing
> `Embedded 0 chunks (0 stale found)` immediately after a put is NORMAL (the chunks
> were already embedded by the put) — it is not an error and not an empty no-op.

```bash
orgo_bash 'set -e
export GBRAIN_HOME=/opt/brain PATH=/usr/local/bin:$HOME/.bun/bin:$PATH OPENROUTER_API_KEY=<OPENROUTER_API_KEY>
# Seed a starter identity/client page via STDIN (0.42 has no put-page). If the
# repo bootstrap fits the client, run scripts/bootstrap-brain.sh instead — but at
# minimum seed one page so retrieval has real content.
gbrain put "people/<CLIENT>" <<"MD"
# <CLIENT>

SafeClaw is the AI email/Slack/Telegram assistant deployed for <CLIENT>.
This is the seed identity page so the brain has content to embed and recall.
Replace/expand with real client context (entities, markets, contacts) as known.
MD
# 0.42 auto-embeds at put time; this confirms (0 stale is fine — already embedded):
gbrain embed --stale 2>&1 | tail -3
echo SEED_DONE'
```

**Make the first sync commit (issue 14)** — the dream `sync` phase fails with zero
commits in the sync repo:
```bash
orgo_bash 'cd /opt/brain/repo && git add -A && git commit -m "initial seed" 2>&1 | tail -2'
```
(If the put did not materialise files into `/opt/brain/repo`, the first `gbrain
dream` `sync` phase will write them — but make at least an empty initial commit so
the repo has history: `git commit --allow-empty -m "initial seed"`.)

**Verify the seed page exists and is embedded:**
```bash
orgo_bash 'export GBRAIN_HOME=/opt/brain PATH=/usr/local/bin:$HOME/.bun/bin:$PATH
gbrain list_pages 2>/dev/null | grep -i "<CLIENT>"
export OPENROUTER_API_KEY=<OPENROUTER_API_KEY>; gbrain query "<CLIENT>" 2>&1 | head -5'
```
Expected: the `people/<CLIENT>` page listed, and the query returns the seeded
content (proves embeddings are real). Step 13's chat deliverable now has something
to answer with.

> If `gbrain put` arg shape differs on the installed gbrain version, check
> `gbrain put --help`; the goal is simply "one real page, embedded, + 1 commit."

---

## Step 3 — Hermes profiles (reader / actor trust split)  **[BOX]**

Each Hermes **profile** is an isolated `HERMES_HOME`
(`/root/.hermes/profiles/<name>/`) with its **own** config / `.env` / MCP
servers / skills. Profiles give the reader and actor **different tools**, not
just a different voice. The trust split:

- **reader** → gbrain URL MCP + Gmail **read-only** MCP + Slack `reader` MCP. No
  send/draft/post tool exists in it.
- **actor** → gbrain URL MCP + Gmail **draft** MCP + Slack `actor` MCP + the
  Telegram gateway + the Slack Socket Mode connection.
- **default** → ONLY the dashboard's embedded `--tui` gateway. **No Telegram
  token, no Slack app token** (critical — see Steps 4, 7, 11/12).

> **⚠️ Hermes 0.15.1 has NO `-p <profile>` flag (issue 9).** Profiles are created
> with **`hermes profile create <name>`** (note: singular **`profile`**, not
> `profiles`) and every per-profile command is run with
> **`HERMES_HOME=/root/.hermes/profiles/<name>`** as an env var — there is no
> `-p`. The loop below is rewritten accordingly.
>
> **⚠️ `hermes profile create` COPIES the default profile (issue 11)** — its
> `config.yaml` (so the base_url, model, token-economy knobs) AND its credential
> pool. So set the default profile's keys/knobs in Step 1 **before** creating
> profiles to inherit them. **Proven concurrency pattern on Mark:** give actor and
> reader **DIFFERENT primary keys** (actor = a dedicated key, reader = the shared
> key), each carrying the *other* as a pool fallback → true concurrency isolation
> (see the concurrency-starvation box below).

```bash
orgo_bash 'set -e
export HERMES_HOME=/root/.hermes
for p in reader actor; do
  # Create the profile (copies default config + cred pool — issue 11).
  hermes profile create $p 2>&1 | tail -1
  D=/root/.hermes/profiles/$p
  mkdir -p $D/logs
  # All per-profile commands use HERMES_HOME=$D (NO -p flag — issue 9).
  HERMES_HOME=$D hermes config set model.provider ollama
  HERMES_HOME=$D hermes config set model.default glm-4.7   # NOT kimi-k2.5 (Step 1)
  HERMES_HOME=$D hermes config set model.base_url https://ollama.com/v1  # issue 20
  # --- TOKEN-ECONOMY KNOBS (the single biggest operational fix) ---
  # Defaults (compression-state-dependent, max_turns=90, retries=3) produced
  # O(n^2) token growth (observed 94-turn runs sending 61,485 tokens in ONE call)
  # that vaporized the weekly Ollama cap in ~1 day. Apply to BOTH profiles.
  HERMES_HOME=$D hermes config set agent.auxiliary.compression.enabled true
  HERMES_HOME=$D hermes config set agent.max_turns 25
  HERMES_HOME=$D hermes config set agent.api_max_retries 2
done
# --- Per-profile PRIMARY keys (different keys = concurrency isolation, issue 11) ---
# actor gets the DEDICATED key as primary; reader gets the SHARED key; each carries
# the other as a pool fallback.
echo "OLLAMA_API_KEY=<OLLAMA_API_KEY>"          >> /root/.hermes/profiles/actor/.env
echo "OLLAMA_API_KEY=<OLLAMA_FALLBACK_KEY>"     >> /root/.hermes/profiles/reader/.env
HERMES_HOME=/root/.hermes/profiles/actor  hermes auth add ollama-cloud --type api-key --api-key <OLLAMA_FALLBACK_KEY> --label fallback
HERMES_HOME=/root/.hermes/profiles/reader hermes auth add ollama-cloud --type api-key --api-key <OLLAMA_API_KEY>      --label fallback
echo PROFILES_DONE'
# NOTE: gbrain is wired into BOTH profiles as a URL MCP in Step 2c-c (NOT a stdio
# `hermes mcp add gbrain` — that fights the PGLite single-writer lock, issue 22).
# Run Step 2c-c now if you have not already.
```

> **Why these three knobs are mandatory** (see
> `knowledge/gotchas/hermes-compression-off-causes-quadratic-tokens.md` +
> `decisions/safeclaw-ingest-working-config.md`):
> - `agent.auxiliary.compression.enabled: true` — without it the agentic loop
>   re-sends the entire growing history every turn → O(n²) total tokens.
> - `agent.max_turns: 25` — Hermes defaults to 90; bound the loop.
> - `agent.api_max_retries: 2` — Hermes defaults to 3; the 3rd retry on a hard
>   429 wall is pure waste.
>
> **Diagnostic signature if you skip them:** grep `agent.log` for `tokens=~N`
> > 20k paired with `msgs=M` > 20 — that's the quadratic blow-up.

> **⚠️ Concurrency starvation (HANG, not a 429).** The reader and actor gateways
> SHARE the Ollama account's concurrency budget. On a 16 GB box you *can* run
> both hot — but if they (or any other consumer) saturate the Pro concurrency
> cap, calls **HANG** at `Auxiliary auto-detect` with 0 progress for up to the
> 1800 s per-call timeout (it looks dead for 30 min) — they do **not** 429.
> Either give reader and actor **separate keys / pool entries**, or keep only the
> actor gateway hot during heavy ingest. **Never run OpenClaw (or any other
> agent) against the same Ollama account** — that is the exact starvation trap.
> A direct probe returns `too many concurrent requests` (NOT a usage-limit
> message). See `knowledge/gotchas/openclaw-ollama-concurrency-conflict.md`.

**Verify (MCP + token-economy knobs applied to both profiles).** Note: **`hermes
config get` does NOT exist (issue 10)** — use `hermes config show | grep <key>`:
```bash
orgo_bash 'for p in reader actor; do echo "== $p =="; \
  HERMES_HOME=/root/.hermes/profiles/$p hermes mcp list; \
  HERMES_HOME=/root/.hermes/profiles/$p hermes config show | grep -iE "max_turns|compression|base_url"; \
  HERMES_HOME=/root/.hermes/profiles/$p hermes auth list; done'
```
Expected: both list `gbrain` (the URL MCP from Step 2c-c); `max_turns: 25`;
`compression.enabled: true`; `base_url: https://ollama.com/v1`; and
`ollama-cloud (2 credentials)`. (Gmail + Slack MCPs are added in Steps 8, 11, 12.)

---

## Step 4 — DREAMING: nightly `gbrain dream` as a Hermes cron job  **[BOX]**

> **This was NEVER installed on the old box** — only `gbrain serve` (the MCP) was
> wired in. There is no systemd/cron on orgo, and `nohup`/`setsid` get reaped.
> The fix is Hermes's **own in-process cron scheduler** (present since 0.11): it
> fires jobs as long as a gateway is running. We register `gbrain dream` to run
> nightly inside the **actor** profile (whose gateway is always up, Step 7).

**What dreaming does** — `gbrain dream` is the 11-phase nightly maintenance pass:
`lint → backlinks → sync → synthesize → extract → patterns →
recompute_emotional_weight → consolidate → embed → orphans → purge`. The `embed`
phase is why the OpenRouter key (Step 2) is mandatory. `purge` hard-deletes
soft-deleted pages after 72 h. Without dreaming the brain accumulates orphans,
stale embeddings, and missing backlinks — retrieval quality degrades over weeks.

> **⚠️ Hermes 0.15.1 cron syntax is COMPLETELY different from the old template
> (issue 12):**
> - the schedule is **POSITIONAL** (first arg), e.g. `"0 3 * * *"` — there is
>   **NO `--schedule` and NO `--command` flag**;
> - the job runs a **script file** that must live at
>   `$HERMES_HOME/scripts/<name>.sh` (passed via `--script <name>.sh`);
> - **`--no-agent`** runs the script directly **without burning any LLM tokens**
>   (the old `--command "hermes chat …"` form spent tokens every night).
>
> Form: `hermes cron create "0 3 * * *" --name gbrain-dream --script gbrain-dream.sh --no-agent`.
> The cron only fires **while a gateway runs** — the actor gateway (Step 7).

> **⚠️ The dream script MUST stop+restart the brain HTTP server (issue 22d).**
> `gbrain dream` runs its own CLI which needs the **PGLite writer lock** — but the
> persistent `gbrain serve --http` (tmux `brain`, Step 2c) already holds it. So the
> script: stops the `brain` tmux session, runs `gbrain dream`, then restarts the
> `brain` session. Otherwise dream deadlocks on the lock the HTTP server holds.

**Write the dream script** at the actor profile's `scripts/` dir:
```bash
orgo_bash 'A=/root/.hermes/profiles/actor; mkdir -p $A/scripts
cat > $A/scripts/gbrain-dream.sh <<"EOF"
#!/usr/bin/env bash
# Nightly gbrain dream. Stops the HTTP brain server (it holds the PGLite writer
# lock), runs dream, restarts it. Logs to /opt/brain/dream.log.
export GBRAIN_HOME=/opt/brain
export PATH=/usr/local/bin:/root/.bun/bin:$PATH
set -a; [ -f /opt/brain/.env ] && . /opt/brain/.env; set +a   # OPENROUTER_API_KEY etc.
{
  echo "=== dream start $(date -u) ==="
  tmux kill-session -t brain 2>/dev/null   # release the PGLite writer lock
  sleep 3
  gbrain dream
  tmux new-session -d -s brain /opt/launch-brain.sh   # restart the HTTP server
  echo "=== dream end $(date -u) ==="
} >> /opt/brain/dream.log 2>&1
EOF
chmod +x $A/scripts/gbrain-dream.sh
echo DREAM_SCRIPT_WRITTEN'
```

**Register the cron** (new 0.15.1 syntax — positional schedule, `--script`,
`--no-agent`):
```bash
orgo_bash 'export HERMES_HOME=/root/.hermes/profiles/actor
hermes cron create "0 3 * * *" --name gbrain-dream --script gbrain-dream.sh --no-agent
# (cron needs croniter; setup-hermes.sh installs it. cron fires only while the
#  actor gateway runs — Step 7.)
echo CRON_DONE'
```

> **gbrain sync/maintenance schedule.** On PGLite (single on-box file) the
> separate `autopilot`/`maintenance` daemons the Mac uses are NOT warranted —
> `dream` already runs `sync` and `consolidate` as phases 3 and 7. One nightly
> `dream` is the complete maintenance story for an orgo box. (Only escalate to a
> standalone `gbrain autopilot --interval 300` loop if you later move the brain
> to Postgres.)

**Verify the cron is registered:**
```bash
orgo_bash 'HERMES_HOME=/root/.hermes/profiles/actor hermes cron list'
```
Expected: a `gbrain-dream` entry, schedule `0 3 * * *`, next-run timestamp set.

**Verify the gbrain pipeline (force one run via the SCRIPT — it stops/restarts the
brain server):**
```bash
# Run the dream script itself (it releases the PGLite lock, dreams, restarts brain):
orgo_bash 'bash /root/.hermes/profiles/actor/scripts/gbrain-dream.sh; tail -20 /opt/brain/dream.log'
# Confirm the brain HTTP server came back up after the dream:
orgo_bash 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3131/mcp'   # 405 = back up
```
Expected: `dream.log` shows all 11 phases completing (look for `lint … sync …
patterns … embed … purge` and a final summary), no `ZEROENTROPY_API_KEY` error in
the embed phase, no `sync` failure (the Step 2b commit prevents that), and the
`brain` HTTP server returns `405` again (restarted by the script).

**Verify the SCHEDULER actually fires the job (not just the gbrain binary).** The
manual run above proves the pipeline but NOT that Hermes' in-process cron triggers
it — and the cron only fires while the actor gateway (Step 7) runs, which is the
exact dependency most likely to break silently. Prove the scheduler wiring:
```bash
# Preferred — force the cron entry to run THROUGH Hermes (if your version has it):
orgo_bash 'HERMES_HOME=/root/.hermes/profiles/actor hermes cron run gbrain-dream 2>&1 | tail -5'
# Fallback — confirm the gateway logged a cron fire (after the gateway is up, Step 7):
orgo_bash 'grep -iE "cron.*gbrain-dream|Running job .gbrain-dream|cron.scheduler" \
  /root/.hermes/profiles/actor/logs/gateway.log | tail -5'
```
Expected: a Hermes-side cron-fire entry for `gbrain-dream` (and a fresh
`dream.log` tail), proving the scheduler→dream wiring — not merely that the dream
binary works. If neither shows anything, the actor gateway isn't running (Step 7)
or the cron didn't register (re-check `hermes cron list`).

---

## Step 5 — Hermes routines / workflows (client registration)  **[BOX]**

Hermes's recurring-work primitive **is** the cron scheduler from Step 4 (there is
no separate "routines" subsystem in 0.11/0.15 — `hermes cron` *is* the routines
feature). Client-specific recurring jobs are registered exactly like the dream
job: a named cron entry in the profile whose gateway runs it.

Typical client routines (register only the ones the client asked for):

> **⚠️ `hermes chat` flag order (0.15.1, hit live on mark-agent):** `-q` is
> `--query` and TAKES the prompt as its argument; `-Q` is the separate quiet
> flag. `hermes chat -q -Q "..."` fails with `error: argument -q/--query:
> expected one argument`. Correct form: `hermes chat -Q -q "<prompt>"`.

```bash
# Morning inbox triage digest at 07:00 weekdays. New 0.15.1 syntax (issue 12):
# schedule is POSITIONAL; a script lives at $HERMES_HOME/scripts/. This routine
# DOES want an LLM (so NOT --no-agent) — it agentically summarizes + DMs.
orgo_bash 'A=/root/.hermes/profiles/actor; mkdir -p $A/scripts
cat > $A/scripts/morning-digest.sh <<"EOF"
#!/usr/bin/env bash
export HERMES_HOME=/root/.hermes/profiles/actor
export PATH=/usr/local/bin:/tmp/node-v20.18.1-linux-x64/bin:$PATH
hermes chat -Q -q "Summarize overnight email + Slack and DM me the top 5 items"
EOF
chmod +x $A/scripts/morning-digest.sh
HERMES_HOME=$A hermes cron create "0 7 * * 1-5" --name morning-digest --script morning-digest.sh'
```

### Routine: hourly Gmail ingestion → brain (deployed on mark-agent 2026-06-02)

The standard "the agent actually knows the inbox" routine. Gmail's own
categorization does the hard filter (`category:primary` excludes Promotions /
Social / Spam); the LLM then keeps only emails worth remembering and writes
summary pages into gbrain under `emails/<date>-<subject>`.

Pattern: the script exports `HERMES_HOME` of the **reader** profile (read-only
Gmail — trust split preserved), but the cron entry registers in the **actor**
scheduler (the only gateway that fires crons). `--no-agent` because the script
itself runs `hermes chat`; its stdout is the run record.

```bash
# Script: fetch category:primary from BOTH inboxes → LLM filter → gbrain put_page
# (full prompt in /root/.hermes/profiles/actor/scripts/email-ingest.sh on mark-agent;
#  key elements: category:primary -in:spam -in:trash newer_than:2h, max 15/inbox,
#  keep real-person + actionable mail, discard newsletters/OTP/notifications,
#  dedup via get_page on slug emails/<YYYY-MM-DD>-<kebab-subject>,
#  final line "INGEST RESULT: N fetched, K ingested, F filtered out, D already known")

# Register: hourly at :15 (off the 03:00 dream + 04:00 recycle windows)
orgo_bash 'HERMES_HOME=/root/.hermes/profiles/actor hermes cron create "15 * * * *" \
  --name email-ingest --script email-ingest.sh --no-agent --deliver local'
```

> Cadence note: glm-4.7 under the full ~90-tool reader load takes minutes per
> step; a single ingest run can take 10–30 min. **Hourly is the floor** — do not
> schedule this every 15/30 min or runs will overlap.

> **Rule:** every client routine is a `hermes cron` entry in the **actor** profile
> (its gateway is the always-running one). The reader profile has no long-running
> gateway, so cron entries placed there will not fire on a schedule — only the
> actor's do. Document each routine you add in the Console's notes panel.

> **Keep routine crons off the 03:00 and 04:00 windows.** 03:00 is the dream cron
> (Step 4); 04:00 is the watchdog's nightly gateway recycle (Slack 8h-stale fix,
> Step 9/12e). A routine scheduled at 04:00 can collide with the gateway restart
> mid-run. Pick odd/quiet hours (e.g. 04:15, 07:00) for client routines.

**Verify:**
```bash
orgo_bash 'HERMES_HOME=/root/.hermes/profiles/actor hermes cron list'
```
Expected: `gbrain-dream` plus any client routines, each with a next-run time.

---

## Step 6 — SafeClaw Console (Flask) + basic-auth  **[BOX]**

The Console is a standalone Flask app (`safeclaw-ui/`, no build step) — Hermes's
own React dashboard wouldn't build reliably on the box, so this is the reliable
in-browser config + chat surface. Panels: Dashboard · Chat (brain-backed) ·
Slack · Telegram · Gmail · GDrive · Zapier/MCP, each with inline how-to help.
Auth is a `before_request` basic-auth gate using `SAFECLAW_UI_USER` /
`SAFECLAW_UI_PASS`. The sidebar's **"Hermes Dashboard" link is client-aware** —
it derives from `SAFECLAW_UI_USER` (the `<CLIENT>` slug) as
`https://hermes-<CLIENT>.growthsystems.ai`, or from an explicit `HERMES_DASH_URL`
env var. Because the Step 6 tmux block sets `SAFECLAW_UI_USER=<CLIENT>`, the link
points at THIS client's dashboard automatically — confirm it in Step 13.

```bash
orgo_bash 'set -e
mkdir -p /opt/safeclaw-ui
cp -r /opt/safeclaw/safeclaw-ui/* /opt/safeclaw-ui/
# basic-auth password (REQUIRED — the Console reads/writes secrets)
echo "<UI_PASSWORD>" > /opt/safeclaw-ui/.uipass && chmod 600 /opt/safeclaw-ui/.uipass
tmux kill-session -t sui 2>/dev/null
tmux new-session -d -s sui "export HERMES_HOME=/root/.hermes \
  SAFECLAW_UI_USER=<CLIENT> SAFECLAW_UI_PASS=$(cat /opt/safeclaw-ui/.uipass) \
  PATH=/tmp/node-v20.18.1-linux-x64/bin:\$PATH PORT=8899 HOST=127.0.0.1; \
  exec python3 /opt/safeclaw-ui/app.py"
echo SUI_UP'
```

**Verify:**
```bash
orgo_bash 'sleep 3; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8899/healthz'
```
Expected: `200` (`/healthz` is unauthenticated; `/` requires basic-auth → `401`
without creds).

> **Use `/api/selftest` + the "SYSTEM TEST" dashboard card as the primary
> end-to-end check.** The Console exposes `POST /api/selftest` (surfaced as the
> "SYSTEM TEST" card on the Dashboard panel) that verifies Hermes, GBrain, both
> profiles, a **real Gmail fetch per inbox**, Telegram, the tunnel, clock drift,
> and the LLM key in one click — the single best verification surface. **Note:**
> hitting it **auto-restarts the actor gateway**, so expect a brief Telegram/Slack
> reconnect after running it. Re-use it again in Step 13.

---

## Step 7 — Hermes dashboard (with the Chat tab)  **[BOX]**

The Hermes dashboard serves on port 9119. **The in-browser Chat tab requires the
`--tui` flag** (or `HERMES_DASHBOARD_TUI=1`) — without it the Chat tab does not
appear. `--tui` embeds a Hermes gateway on the **default** profile; this is safe
**only because the default profile's `.env` has no Telegram token and no Slack
app token** (those live ONLY in the actor — Steps 11/12). If you ever put a
Telegram token in default `.env`, `--tui` creates a second Telegram poller →
conflict.

Launch script `/opt/launch-hermes-dash.sh` (run in tmux `hd`):

```bash
orgo_bash 'cat > /opt/launch-hermes-dash.sh <<"EOF"
#!/usr/bin/env bash
export HERMES_HOME=/root/.hermes
export HERMES_ALLOW_ROOT_GATEWAY=1
export PATH=/tmp/node-v20.18.1-linux-x64/bin:$PATH
# --skip-build is 0.15+ ONLY. On <0.15 it errors ("--skip-build not recognized")
# and the dashboard never serves. Detect the version and drop the flag there
# (setup-hermes.sh has already pre-built /opt/hermes/web for <0.15).
SKIP_BUILD=""
MAJMIN=$(hermes --version 2>/dev/null | grep -oE "[0-9]+\.[0-9]+" | head -1)
case "$MAJMIN" in
  0.11|0.12|0.13|0.14) SKIP_BUILD="" ;;   # pre-built bundle, no flag
  *)                   SKIP_BUILD="--skip-build" ;;
esac
exec hermes dashboard --port 9119 --host 0.0.0.0 --no-open --tui --insecure $SKIP_BUILD
EOF
chmod +x /opt/launch-hermes-dash.sh
tmux kill-session -t hd 2>/dev/null
tmux new-session -d -s hd /opt/launch-hermes-dash.sh
echo HD_UP'
```

> **Pin to 0.15.1 if you can** (`HERMES_VERSION=0.15.1` in setup-hermes.sh) to
> avoid the 0.11 pre-build path entirely. If you stay on 0.11–0.14,
> setup-hermes.sh runs the one-time `cd /opt/hermes/web && npm run build` so the
> dashboard can serve without `--skip-build`.

**Also start the actor gateway now** (it hosts the Telegram poller, the Slack
Socket Mode connection, AND the cron scheduler that fires `gbrain dream`):

```bash
orgo_bash 'A=/root/.hermes/profiles/actor; mkdir -p $A/logs
tmux kill-session -t gw 2>/dev/null
tmux new-session -d -s gw "export HERMES_HOME=$A HERMES_ALLOW_ROOT_GATEWAY=1 \
  PATH=/tmp/node-v20.18.1-linux-x64/bin:\$PATH; \
  exec hermes gateway run > $A/logs/gateway.log 2>&1"
echo GW_UP'
```

### Step 7b — Install the SafeClaw dashboard plugins (Connections + Settings)  **[BOX]**

The dashboard tabs the operator and customer actually use are shipped as
plugins in the repo (`dashboard-plugins/`). Build each bundle (their `dist/` is
gitignored — `build.sh` regenerates it) and symlink it into `~/.hermes/plugins`,
then recycle the dashboard so the tabs appear.

```bash
orgo_bash 'set -e; export PATH=/tmp/node-v20.18.1-linux-x64/bin:$PATH
mkdir -p /root/.hermes/plugins
for p in safeclaw-memory safeclaw-personas; do
  src=/opt/safeclaw/dashboard-plugins/$p
  [ -x "$src/build.sh" ] && bash "$src/build.sh"        # src → dist/index.js
  ln -sfn "$src" /root/.hermes/plugins/$p
done
# NOTE: the customer "connect your accounts" experience is NOT a Hermes plugin —
# it lives in the SafeClaw Console at /connect-accounts (Step 6). Do NOT install
# safeclaw-connections / safeclaw-settings as dashboard plugins.
# recycle the dashboard (tmux hd) so the new tabs register
tmux kill-session -t hd 2>/dev/null; sleep 2
tmux new-session -d -s hd /opt/launch-hermes-dash.sh
echo PLUGINS_LINKED'
```

The dashboard now serves the **Memory** (3D brain) and **Personas** tabs. The
customer-facing **connect-your-accounts** experience is NOT here — it lives in
the **SafeClaw Console** at `/connect-accounts` (Step 6), so the customer never
sees the technical dashboard.

> **Verify:** load `https://hermes-<CLIENT>.growthsystems.ai` → tabs **Memory ·
> Personas** are present.

> **Host-header gotcha:** the dashboard rejects foreign `Host` headers with
> **400 "Invalid Host header"**. The Cloudflare ingress for the hermes hostname
> **MUST** set `originRequest.httpHostHeader: localhost` (Step 8). `--host
> 0.0.0.0` also relaxes `_is_accepted_host` so tunnel Host headers are accepted.

**Verify:**
```bash
orgo_bash 'sleep 5; curl -s -o /dev/null -w "%{http_code}\n" -H "Host: localhost" http://127.0.0.1:9119/'
```
Expected: `200`.

---

## Step 8 — Cloudflare named tunnel (TWO hostnames, ONE tunnel)  **[MAC] then [BOX]**

Use a **named** tunnel (quick `trycloudflare` tunnels were unreliable here),
created from the Mac's existing cloudflared cert. **No new API token needed —**
the named tunnel's auth is the existing `~/.cloudflared/cert.pem` plus the
per-tunnel credentials JSON. The full auth story: `cert.pem` authorises *creating*
tunnels and DNS routes in the zone; the `<TUNNEL_ID>.json` is the *running*
tunnel's credentials. Both get copied to the box; nothing else is minted.

**8a. Create the tunnel + DNS  [MAC]:**

> **⚠️ ALWAYS pass the tunnel UUID — NOT the name — to `route dns` (issue 18).**
> `cloudflared tunnel route dns <name> …` can silently resolve the name to the
> **WRONG** tunnel (observed on Mark: DNS got routed to an unrelated tunnel).
> Capture the UUID from `tunnel create` (or `tunnel list`) and use it everywhere.

> **⚠️ Re-pointing an EXISTING tunnel to a NEW box = split-brain (issue 17).** If
> the **old** box is still running `cloudflared` on that same tunnel, requests
> randomly hit either box → **intermittent 401s**. If you cannot reach the old box
> to stop its `cloudflared`, do **NOT** reuse the tunnel — **create a NEW tunnel**
> (e.g. `safeclaw-<CLIENT>-v2`) and repoint DNS with
> `cloudflared tunnel route dns --overwrite-dns <TUNNEL_UUID> <hostname>`. The old
> box then serves an orphaned tunnel harmlessly. **This is why the Mark reference
> tunnel is `safeclaw-mark-v2`.**

```bash
# Capture the UUID — route DNS by UUID, never by name (issue 18).
cloudflared tunnel create safeclaw-<CLIENT>      # prints a <TUNNEL_ID> (UUID) + creds JSON
TUNNEL_UUID=$(cloudflared tunnel list | awk '/safeclaw-<CLIENT>/{print $1; exit}')
cloudflared tunnel route dns "$TUNNEL_UUID" safeclaw-<CLIENT>.growthsystems.ai
cloudflared tunnel route dns "$TUNNEL_UUID" hermes-<CLIENT>.growthsystems.ai
# Re-pointing an existing hostname from an old box? add --overwrite-dns (issue 17):
#   cloudflared tunnel route dns --overwrite-dns "$TUNNEL_UUID" safeclaw-<CLIENT>.growthsystems.ai
```

**8b. Copy creds to the box  [MAC]→[BOX]:**

Copy `~/.cloudflared/<TUNNEL_ID>.json` AND `~/.cloudflared/cert.pem` into the box
at `/root/.cloudflared/` (write via `orgo_bash` heredocs, then `chmod 600`).

**8c. Write the config and run  [BOX]:**

```bash
orgo_bash 'mkdir -p /root/.cloudflared && cat > /root/.cloudflared/config.yaml <<EOF
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  # Console
  - hostname: safeclaw-<CLIENT>.growthsystems.ai
    service: http://localhost:8899
  # Hermes dashboard — MUST rewrite Host or the dashboard 400s
  - hostname: hermes-<CLIENT>.growthsystems.ai
    service: http://localhost:9119
    originRequest:
      httpHostHeader: localhost
  - service: http_status:404
EOF
tmux kill-session -t cf 2>/dev/null
tmux new-session -d -s cf "cloudflared tunnel --no-autoupdate --protocol http2 run safeclaw-<CLIENT>"
echo CF_UP'
```

> Pin `--protocol http2` — the box's QUIC path is flaky and leaves **QUIC
> orphans** that cause 502/530. The watchdog kills them with `pkill -x
> cloudflared` (NEVER `pkill -f "cloudflared tunnel"`).

**Verify (from the Mac, the real test):**
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://safeclaw-<CLIENT>.growthsystems.ai                       # 401 (basic-auth) ✓
curl -s -o /dev/null -w "%{http_code}\n" -u <CLIENT>:<UI_PASSWORD> https://safeclaw-<CLIENT>.growthsystems.ai  # 200 ✓
curl -s -o /dev/null -w "%{http_code}\n" https://hermes-<CLIENT>.growthsystems.ai                         # 200 ✓
```

**8d. WebSockets through the tunnel (required for the Hermes dashboard Chat terminal)  [MAC + CF dashboard]**

The dashboard's Chat tab is a **terminal over a WebSocket** (`/api/pty?token=…`).
HTTP pages work through the tunnel regardless, but the WS upgrade only survives if
the **Cloudflare zone** allows it. Findings from the Mark box (2026-06-01):

| Test | Result |
|------|--------|
| WS handshake directly on the box (loopback) | ✅ 101 |
| Same handshake on the box but with the tunnel's Host/Origin headers | ✅ 101 (Hermes's WS guards are NOT the blocker when bound `0.0.0.0 --insecure`) |
| Same handshake through Cloudflare | ❌ 401 (`{"detail":"Unauthorized"}` — the upgrade header was stripped, so Hermes saw a plain HTTP request and its API auth middleware rejected it) |
| Switching tunnel protocol http2 ↔ QUIC | makes **no difference** — the strip happens at the CF zone layer, not the tunnel transport |

**Pre-flight (one-time per zone, CF dashboard — there is no API token on the operator Mac with zone-settings scope):**
1. dash.cloudflare.com → `growthsystems.ai` → **Network** → **WebSockets → ON**
2. **Security → Bots → Bot Fight Mode → OFF** (known to break WS upgrades)

**Verify WS end-to-end (from the Mac):**
```bash
TOKEN=$(curl -s "https://hermes-<CLIENT>.growthsystems.ai/chat" | grep -o 'SESSION_TOKEN__="[^"]*"' | cut -d'"' -f2)
curl -s -o /dev/null -w "%{http_code}\n" "https://hermes-<CLIENT>.growthsystems.ai/api/pty?token=$TOKEN" \
  -H "Upgrade: websocket" -H "Connection: Upgrade" \
  -H "Origin: https://hermes-<CLIENT>.growthsystems.ai" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" -H "Sec-WebSocket-Version: 13"
# 101 = chat terminal will work in the browser ✓
# 401 = CF is still stripping the upgrade (zone settings above) ✗
```

> Until 101 is achieved, the **Console Quick Chat** tab is the supported in-browser
> chat (plain `POST /api/chat`, no WebSocket — always works through the tunnel).

---

## Step 9 — Watchdog / supervisor (tmux-only world)  **[BOX]**

No systemd, no OS cron, and `nohup`/`setsid` jobs get reaped — **only tmux
survives.** A `while-true` supervisor loop in tmux `wd` runs the watchdog every
30 s. It checks 8899 / 9119 / **3131 (brain HTTP server)** / cloudflared / the
actor gateway (so the cron scheduler AND `gbrain dream` stay alive), restarts any
dead one, and **re-syncs the clock** (orgo suspend/resume drifts the VM clock —
breaks TLS / Telegram / Composio). It ALSO performs a **nightly 04:00 gateway
restart** as the Slack-stale mitigation (Step 12e).

> **⚠️ Two health-check subtleties baked into the script below:**
> - **The Console `/healthz` is auth-gated (issue 16):** it returns **401**
>   without creds. The watchdog therefore treats **both 401 AND 200 as alive** —
>   only a connection failure / other code means dead. (A naive `curl -fsS` would
>   see the 401 as failure and restart a perfectly healthy Console in a loop.)
> - **The brain HTTP server (`:3131`) check (issue 22e):** a bare `GET /mcp`
>   returns **405** when alive — treat 405 (and any 2xx/4xx) as alive; only a
>   connection failure means the `brain` tmux session died and must be restarted
>   via `/opt/launch-brain.sh`.

```bash
orgo_bash 'cat > /opt/safeclaw-watchdog.sh <<"EOF"
#!/usr/bin/env bash
# one cycle: revive any dead service, re-sync clock, do the nightly slack-stale restart.
N20=/tmp/node-v20.18.1-linux-x64/bin
A=/root/.hermes/profiles/actor
R=/root/.hermes/profiles/reader

# Console :8899 — /healthz is AUTH-GATED: 401 AND 200 both mean ALIVE (issue 16).
# Only a connection failure (000) / other code means dead.
SUI_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 5 http://127.0.0.1:8899/healthz 2>/dev/null)
case "$SUI_CODE" in
  200|401) : ;;   # alive
  *) tmux new-session -d -s sui "export HERMES_HOME=/root/.hermes \
       SAFECLAW_UI_USER=<CLIENT> SAFECLAW_UI_PASS=$(cat /opt/safeclaw-ui/.uipass) \
       PATH=$N20:\$PATH PORT=8899 HOST=127.0.0.1; exec python3 /opt/safeclaw-ui/app.py" ;;
esac

# GBrain HTTP server :3131 — bare GET /mcp returns 405 when ALIVE (issue 22e).
# Any HTTP response (405/2xx/4xx) = alive; only a connection failure = dead.
BRAIN_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 5 http://127.0.0.1:3131/mcp 2>/dev/null)
[ "$BRAIN_CODE" = "000" ] && { tmux has-session -t brain 2>/dev/null || \
  tmux new-session -d -s brain /opt/launch-brain.sh; }

# Hermes dashboard :9119
curl -fsS -m 5 -H "Host: localhost" http://127.0.0.1:9119/ >/dev/null 2>&1 || \
  tmux new-session -d -s hd /opt/launch-hermes-dash.sh

# cloudflared (kill QUIC orphans only with -x, never -f "cloudflared tunnel")
tmux has-session -t cf 2>/dev/null || { pkill -x cloudflared; sleep 2; \
  tmux new-session -d -s cf "cloudflared tunnel --no-autoupdate --protocol http2 run safeclaw-<CLIENT>"; }

# actor gateway (Telegram poller + Slack Socket Mode + cron scheduler for gbrain dream)
tmux has-session -t gw 2>/dev/null || \
  tmux new-session -d -s gw "export HERMES_HOME=$A HERMES_ALLOW_ROOT_GATEWAY=1 PATH=$N20:\$PATH; \
    exec hermes gateway run > $A/logs/gateway.log 2>&1"

# clock-sync: orgo suspend/resume drifts the clock; re-sync from Cloudflare Date header
NET=$(curl -sI -m 10 https://www.cloudflare.com | grep -i "^date:" | cut -d" " -f2-)
[ -n "$NET" ] && date -u -s "$NET" >/dev/null 2>&1

# NIGHTLY 04:00 slack-stale mitigation: recycle actor + reader gateways once.
# The stdio slack_native MCP child goes silent after ~8h (ClosedResourceError,
# empty error string). Recreating the gateway respawns the MCP child.
H=$(date -u +%H); M=$(date -u +%M); STAMP=/tmp/.slack_restart_$(date -u +%Y%m%d)
if [ "$H" = "04" ] && [ "$M" -lt "01" ] && [ ! -f "$STAMP" ]; then
  touch "$STAMP"
  tmux kill-session -t gw 2>/dev/null; sleep 3
  tmux new-session -d -s gw "export HERMES_HOME=$A HERMES_ALLOW_ROOT_GATEWAY=1 PATH=$N20:\$PATH; \
    exec hermes gateway run > $A/logs/gateway.log 2>&1"
  # reader has no long-running gateway, but if a reader ingest gateway is up, recycle it too:
  tmux has-session -t rg 2>/dev/null && { tmux kill-session -t rg; sleep 2; \
    tmux new-session -d -s rg "export HERMES_HOME=$R HERMES_ALLOW_ROOT_GATEWAY=1 PATH=$N20:\$PATH; \
      exec hermes gateway run > $R/logs/gateway.log 2>&1"; }
fi
EOF
chmod +x /opt/safeclaw-watchdog.sh

cat > /opt/safeclaw-supervisor.sh <<"EOF"
#!/usr/bin/env bash
while true; do /opt/safeclaw-watchdog.sh; sleep 30; done
EOF
chmod +x /opt/safeclaw-supervisor.sh

tmux kill-session -t wd 2>/dev/null
tmux new-session -d -s wd /opt/safeclaw-supervisor.sh
echo WD_UP'
```

**Verify (auto-heal test):**
```bash
orgo_bash 'tmux kill-session -t sui; sleep 40; \
  curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8899/healthz'
```
Expected: `200` — the watchdog revived the Console within ~30 s.

---

## Step 10 — Telegram (dedicated bot per box)  **[BOX]**

**Dedicated bot per box.** Create it in @BotFather, get `<TELEGRAM_BOT_TOKEN>`.
The token goes **ONLY** in the actor profile `.env`. default `.env` and reader
`.env` keep Telegram off (verified: default=0, reader=0) — this is what makes the
dashboard's `--tui` gateway safe (Step 7). The actor gateway started in Step 7
picks the token up; just append it and recycle.

> **⚠️ Do NOT configure the token through the Hermes dashboard's Config/Keys page**
> (live-install learning #25). The dashboard writes it to the **default** profile's
> `.env` — the wrong profile. The dashboard's embedded `--tui` gateway then tries to
> start Telegram itself (crashes/conflicts), and the actor gateway never sees the
> token. If a user already did this: move both `TELEGRAM_*` lines from
> `/root/.hermes/.env` into the actor `.env`, then recycle BOTH `hd` and `gw`.

> **⚠️ Reusing a bot from a retired/old box** (live-install learning #26): the old
> box's gateway keeps polling that bot until it is killed — Telegram then ping-pongs
> the connection between boxes every ~45 s, and messages delivered to the old box are
> **silently lost** ("Hermes stopped responding"). Before going live on the new box,
> either (a) kill the old box's services / delete the box (see decommission note in
> Step 14), or (b) revoke the token in @BotFather and use the new one — the old
> box's poller dies on the next 401.

```bash
orgo_bash 'A=/root/.hermes/profiles/actor
echo "TELEGRAM_BOT_TOKEN=<TELEGRAM_BOT_TOKEN>" >> $A/.env
echo "TELEGRAM_ALLOWED_USERS=<TELEGRAM_NUMERIC_USER_ID>" >> $A/.env
tmux kill-session -t gw 2>/dev/null; sleep 3
tmux new-session -d -s gw "export HERMES_HOME=$A HERMES_ALLOW_ROOT_GATEWAY=1 \
  PATH=/tmp/node-v20.18.1-linux-x64/bin:\$PATH; \
  exec hermes gateway run > $A/logs/gateway.log 2>&1"
echo TG_UP'
```

> **Obtaining `<TELEGRAM_NUMERIC_USER_ID>`** (this is the boss/approver's numeric
> Telegram id — **different** from a Slack `U…` id): DM **@userinfobot** on
> Telegram (it replies with your numeric id), or read the gateway log's incoming
> update for the `from.id` field after the user DMs the bot once. Guessing wrong
> = the user's DMs are silently rejected as unauthorized.

> **getUpdates gotchas:**
> - One bot = exactly **one** `getUpdates` consumer. Sharing a bot across boxes
>   is impossible — hence one dedicated bot per box.
> - **Do not run `getUpdates` curl probes** — the probe itself opens a competing
>   long-poll and *causes* the conflict you're diagnosing. Read the gateway log.
> - The **real** gateway log is `$A/logs/gateway.log`, NOT `/tmp/gw.log`.

**Verify (success signature — match the proven Mark result):**
```bash
orgo_bash 'sleep 8; grep -iE "connected|polling|conflict|tools loaded|redaction" /root/.hermes/profiles/actor/logs/gateway.log | tail'
```
Expected: a clean "connected / polling" line, **0 conflicts**, `gbrain 88 tools`
loaded (gbrain 0.42 exposes 88), and secret-redaction on. Then DM the bot from the
allowed user and
confirm the message is **accepted** (not logged as `unauthorized`) and gets a
brain-backed reply:
```bash
# after DMing the bot from the allowed user, confirm authorization (not rejected):
orgo_bash 'grep -iE "unauthorized|not allowed|allowed user|<TELEGRAM_NUMERIC_USER_ID>" /root/.hermes/profiles/actor/logs/gateway.log | tail'
```
Expected: no `unauthorized`/`not allowed` line for the allowed user's id. If you
see one, `TELEGRAM_ALLOWED_USERS` has the wrong numeric id.

---

## Step 11 — Composio project-per-client + Gmail trust split  **[MAC] then [BOX]**

Two Composio MCP servers per Gmail account:
- **reader** (read-only): `GMAIL_FETCH_EMAILS`, `GMAIL_LIST_THREADS`,
  `GMAIL_GET_PROFILE`, `GMAIL_FETCH_MESSAGE_BY_THREAD_ID`, `GMAIL_GET_ATTACHMENT`.
- **actor** (draft, **NO SEND**): `GMAIL_CREATE_EMAIL_DRAFT`,
  `GMAIL_REPLY_TO_THREAD` + fetch.

### 11a. Unified path (recommended) — operator-side project provisioning  **[MAC]**

> **🔑 The org key never touches the box.** You hold one agency **Composio Org
> key** (it can create/modify projects across *every* client). Run the
> provisioner **on your Mac / the admin agent**. It creates an isolated Composio
> **project** for this client, builds the reader/actor MCP servers, and emits an
> env fragment containing only the per-client **project key** + MCP URLs — the
> things that are safe to put on the box. The org key is used solely to create
> the project and is never written or echoed. (See `scripts/provision-composio.py`.)

```bash
# [MAC] — org key stays local; only the printed fragment goes to the box.
COMPOSIO_ORG_API_KEY=ak_org_… \
  python3 scripts/provision-composio.py --client <CLIENT> --platforms gmail
# → prints:
#   COMPOSIO_API_KEY=ak_<project-scoped>
#   COMPOSIO_USER_ID=client:<CLIENT>
#   COMPOSIO_READER_MCP_URL=https://…
#   COMPOSIO_ACTOR_MCP_URL=https://…
#   # project_id=proj_… (Composio console reference)
```

Paste those four lines into the box's `client.env` (Step 6 Console env), then
restart the actor gateway. The **customer never sees Composio** — they connect
their own Google account later by clicking the connector on the **Connections**
tab (Step 7b), and the dashboard's `safeclaw-connections` plugin mints the OAuth
link server-side using this project key. The Composio **org** key, by design,
is on neither the box nor the customer's screen.

> What 11a does NOT do yet: it provisions the project + auth config + reader/
> actor MCP servers. Binding a *specific connected account* to each server still
> happens when the customer OAuths (Connections tab) — the MCP URL template
> carries `user_id`; `connected_account_id` is appended per connection.

### 11b. Manual / Console path (fallback or extra Gmail accounts)  **[BOX]**

If you are not using 11a (or are adding a second mailbox to an existing
project), use the Console Gmail panel or the manual wiring below — both operate
against whatever project key is already in `client.env`.

**Primary path — the Console Gmail panel.** Use `POST /api/gmail/wire` (the Gmail
panel button): it provisions BOTH Composio MCP servers, maps each connected Gmail
account to its own `auth_config`, self-heals account↔auth_config mismatches, writes
the servers into the right profile `config.yaml`, and auto-restarts the actor
gateway. This is the documented, verified path — prefer it over the manual block.

**Creating the two Composio MCP servers (what the Console does, for reference /
manual wiring):** In the Composio dashboard (or via the API) create **two** MCP
servers for the Gmail toolkit, with the exact allowlists above:
- **reader** server → read-only tools (`GMAIL_FETCH_EMAILS`, `GMAIL_LIST_THREADS`,
  `GMAIL_GET_PROFILE`, `GMAIL_FETCH_MESSAGE_BY_THREAD_ID`, `GMAIL_GET_ATTACHMENT`).
- **actor** server → draft tools (`GMAIL_CREATE_EMAIL_DRAFT`,
  `GMAIL_REPLY_TO_THREAD` + fetch). **No `GMAIL_SEND_EMAIL`.**

Each server's **base URL** is shown on its Composio detail page (the
`…/mcp/servers/<id>` create response, and on the dashboard). Those are
`<READER_MCP_BASE_URL>` and `<ACTOR_MCP_BASE_URL>` in the block below.

> **Composio route map (item ops differ from list/create):** list/create stay at
> `/mcp/servers`; **item GET/DELETE use `/api/v3/mcp/{id}`** — `/mcp/servers/{id}`
> 404s as HTML. The Console uses the right routes already.

> **Multi-inbox gotcha:** with multiple Gmail accounts, **each account connected
> in the Composio UI gets its OWN `auth_config`**, and the MCP server MUST be
> bound to that account's `auth_config` or execution fails with **"No connected
> account found."** The Console wire code maps `ca → auth_config` and self-heals
> mismatches — if wiring by hand, bind each server to the matching account.

> **⚠️ ALWAYS re-list IDs before wiring — they go stale (issue 24).** Composio
> `user_id`s and `connected_account_id`s change whenever an account is recreated.
> Do **not** trust IDs from docs/memory/a previous deploy. Re-fetch them live:
> ```bash
> # Find the gmail connected account + its user_id:
> curl -s "https://backend.composio.dev/api/v3/connected_accounts" \
>   -H "x-api-key: <COMPOSIO_API_KEY>" | python3 -m json.tool | grep -iE "id|user_id|gmail" | head
> # Get the reader/actor MCP server URLs:
> curl -s "https://backend.composio.dev/api/v3/mcp/servers" \
>   -H "x-api-key: <COMPOSIO_API_KEY>" | python3 -m json.tool | grep -iE "name|url|id" | head
> ```
> Plug the freshly-listed `connected_account_id`, `user_id`, and server base URLs
> into the wiring block below. (The Console `/api/gmail/wire` path re-lists
> automatically — by hand you must do it yourself.)

If wiring by hand, also mind these two load-bearing gotchas:

1. **The MCP URL needs BOTH params:**
   `…/mcp?user_id=<COMPOSIO_USER_ID>&connected_account_id=<CONNECTED_ACCOUNT_ID>`.
   `connected_account_id` alone fails at `tools/call`; the dashboard label is
   **not** the user_id — the real id is the `pg-test-…` string.
2. **`hermes mcp add --url` cannot attach the required `x-api-key` header**
   (`--env` is stdio-only). Write the gmail entry — url + `headers.x-api-key` —
   **directly into each profile's `config.yaml`** via PyYAML (the Console's
   `_add_gmail_mcp_to_profile()` does this) or it 401s.

```bash
orgo_bash 'python3 - <<"PY"
import yaml, pathlib
KEY="<COMPOSIO_API_KEY>"; UID="<COMPOSIO_USER_ID>"; CA="<CONNECTED_ACCOUNT_ID>"
plans = {
  "reader": "<READER_MCP_BASE_URL>",   # Composio /mcp/servers (read-only tools)
  "actor":  "<ACTOR_MCP_BASE_URL>",    # Composio /mcp/servers (draft tools)
}
for role, base in plans.items():
    cfg_path = pathlib.Path(f"/root/.hermes/profiles/{role}/config.yaml")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg.setdefault("mcp_servers", {})[f"gmail_{role}"] = {
        "url": f"{base.rstrip(chr(47))}/mcp?user_id={UID}&connected_account_id={CA}",
        "headers": {"x-api-key": KEY}, "timeout": 120, "connect_timeout": 30,
    }
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    print("wrote", cfg_path)
PY'
# reload the actor gateway so the new tools register
orgo_bash 'tmux kill-session -t gw 2>/dev/null; sleep 4; \
  tmux new-session -d -s gw "export HERMES_HOME=/root/.hermes/profiles/actor \
  HERMES_ALLOW_ROOT_GATEWAY=1 PATH=/tmp/node-v20.18.1-linux-x64/bin:\$PATH; \
  exec hermes gateway run > /root/.hermes/profiles/actor/logs/gateway.log 2>&1"'
```

**Verify:**
```bash
orgo_bash 'HERMES_HOME=/root/.hermes/profiles/actor hermes mcp list'
```
Expected: the actor lists `gbrain` + `gmail_actor` (draft tools, no send); the
reader lists `gbrain` + `gmail_reader` (read-only, no draft/send).

> **Unconfigured-MCP trap:** an MCP with a `__FILL_IN__` URL aborts the entire
> agentic run at startup. Keep any Gmail entry commented out until the customer
> has actually connected Gmail in Composio.

---

## Step 12 — SLACK (ported from the VPS — the better setup)  **[BOX] + [MAC]**

> **Why port it.** The orgo-native idea (Composio Slack) only saved tokens; the
> **VPS** Slack setup is richer and is the one we want: a **custom stdio MCP**
> (`mcp-tools/slack-api`, TypeScript) whose **trust split is baked into the
> source** via `SLACK_MCP_MODE`, plus **Socket Mode** for the actor's live
> presence. This section ports that VPS wiring from Docker paths to native
> `/opt` paths and Hermes-profile `config.yaml` format.

### 12a. Slack app creation  **[client, walks the form]**

Have the client create ONE Slack app per workspace. Condensed from
[`docs/SLACK-APP-WALKTHROUGH.md`](../docs/SLACK-APP-WALKTHROUGH.md) (the full
10-step guide with screenshots — link the client to it):

1. `api.slack.com/apps` → **Create New App** → **From scratch**.
2. Name it (`<Client>'s Assistant`) + pick the workspace.
3. **OAuth & Permissions → Bot Token Scopes**, add ALL:
   ```
   app_mentions:read  channels:history  channels:join  channels:read
   chat:write  chat:write.public  commands  bookmarks:read  bookmarks:write
   files:read  files:write  groups:history  groups:read  im:history  im:read
   im:write  links:write  mpim:history  mpim:read  pins:read  pins:write
   reactions:read  reactions:write  usergroups:read  users:read  users:read.email
   ```
   (No User scopes — SafeClaw is bot-token only.)
4. **Socket Mode → Enable**; create an App-Level Token with scope
   `connections:write` → copy the **`xapp-…`** token (shown once).
5. **Event Subscriptions → Enable**, subscribe to bot events:
   `app_mention`, `message.channels`, `message.groups`, `message.im`,
   `message.mpim`. **Save Changes.**
6. (optional) Slash commands `/safeclaw-help`, `/safeclaw-status`.
7. **App Home → Messages Tab on** + allow messages from the tab.
8. **Install App → Install to Workspace → Allow** → copy the **`xoxb-…`** Bot
   User OAuth Token. (Reinstall whenever scopes change.)
9. `/invite @<bot>` in each channel the bot should hear.
10. Copy the **`T…`** Workspace ID and **`U…`** your user ID (boss/approver).

**Outputs to collect:** `<SLACK_BOT_TOKEN>` (`xoxb-`), `<SLACK_APP_TOKEN>`
(`xapp-`), `<SLACK_WORKSPACE_ID>` (`T…`), `<SLACK_USER_ID>` (`U…`).

### 12b. Deploy the custom Slack MCP on the box  **[BOX]**

Clone/copy the repo's `mcp-tools/slack-api` to `/opt/mcp-tools/slack-api`, then
`npm install` + `npm run build` (the build needs Node 20 — that's why Step 1
installed it). This mirrors the VPS, where the MCP source is baked into the image
at the same path.

```bash
orgo_bash 'set -e
export PATH=/tmp/node-v20.18.1-linux-x64/bin:$PATH
mkdir -p /opt/mcp-tools
cp -r /opt/safeclaw/mcp-tools/slack-api /opt/mcp-tools/slack-api
cd /opt/mcp-tools/slack-api
npm install
npm run build              # tsc → dist/index.js
test -f dist/index.js && echo SLACK_MCP_BUILT'
```

**Verify:**
```bash
orgo_bash 'export PATH=/tmp/node-v20.18.1-linux-x64/bin:$PATH
SLACK_BOT_TOKEN=x SLACK_MCP_MODE=reader timeout 3 node /opt/mcp-tools/slack-api/dist/index.js 2>&1 | head -1'
```
Expected: `SafeClaw Slack MCP running in reader mode` on stderr (it then idles on
stdio; the timeout kills it — that's fine).

### 12c. Wire `slack_native` into BOTH profiles  **[BOX]**

The MCP's `src/index.ts` switches tools on `SLACK_MCP_MODE`:
- **reader mode** → `slack_list_channels`, `slack_get_channel_history`,
  `slack_get_user_info`, `slack_download_file` (read-only).
- **actor mode** → `slack_download_file`, `slack_send_message`,
  `slack_upload_file` (post/send).

The MCP always reads its token from `SLACK_BOT_TOKEN` (env, internal to the
child) — `mcp-tools/slack-api/src/index.ts` reads **only** `SLACK_BOT_TOKEN` and
**throws `SLACK_BOT_TOKEN environment variable is required`** if it's unset; it
does NOT read `SLACK_MCP_BOT_TOKEN`. The **trust split + Socket Mode rule** (12d)
is implemented by *which* token name we put it under:

> **🚨 Load-bearing assumption to VERIFY before shipping — gateway `${VAR}`
> expansion.** The reader scheme below sets the MCP child's `SLACK_BOT_TOKEN` to
> the literal string `"${SLACK_MCP_BOT_TOKEN}"` in `config.yaml`, relying on the
> Hermes gateway to interpolate `${SLACK_MCP_BOT_TOKEN}` from the profile `.env`
> and pass the resolved value down as `SLACK_BOT_TOKEN`. **If the gateway does
> NOT expand `${...}`, the child receives the literal `${SLACK_MCP_BOT_TOKEN}`
> (or empty) and crashes on startup** — and per the "unconfigured-MCP aborts the
> whole run" trap (Step 11), that takes down the **entire reader agent**.
> **Confirm interpolation empirically** (12c verify below: grep for the reader's
> `slack_native` child printing `running in reader mode`). **If it does NOT
> interpolate, use the fallback wiring:** put the **literal** bot token directly
> in the reader config's `env.SLACK_BOT_TOKEN` (it is internal to the child, not
> the gateway), and keep the reader gateway from opening Socket Mode by
> withholding only `SLACK_APP_TOKEN` from the reader's `.env` (no app token = no
> Socket Mode, regardless of the bot token).

```bash
orgo_bash 'python3 - <<"PY"
import yaml, pathlib
SLACK_XOXB="<SLACK_BOT_TOKEN>"   # xoxb- ; only the ACTOR profile env gets it raw
roles = {
  # READER: token routed via SLACK_MCP_BOT_TOKEN ONLY (NOT SLACK_BOT_TOKEN, see 12d).
  "reader": {"SLACK_BOT_TOKEN": "${SLACK_MCP_BOT_TOKEN}", "SLACK_MCP_MODE": "reader"},
  # ACTOR: gets the real SLACK_BOT_TOKEN (same one the Socket Mode adapter uses).
  "actor":  {"SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}",     "SLACK_MCP_MODE": "actor"},
}
for role, env in roles.items():
    cfg_path = pathlib.Path(f"/root/.hermes/profiles/{role}/config.yaml")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg.setdefault("mcp_servers", {})["slack_native"] = {
        "command": "node",
        "args": ["/opt/mcp-tools/slack-api/dist/index.js"],
        "env": env, "timeout": 30, "connect_timeout": 10,
    }
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    print("wrote slack_native into", cfg_path)
PY'
```

Now set the env vars each profile resolves `${…}` against:

```bash
orgo_bash 'A=/root/.hermes/profiles/actor; R=/root/.hermes/profiles/reader
# ACTOR: real bot token + app token (Socket Mode) — actor is the live presence.
echo "SLACK_BOT_TOKEN=<SLACK_BOT_TOKEN>"  >> $A/.env
echo "SLACK_APP_TOKEN=<SLACK_APP_TOKEN>"  >> $A/.env
echo "SLACK_WORKSPACE_ID=<SLACK_WORKSPACE_ID>" >> $A/.env
echo "SLACK_USER_ID=<SLACK_USER_ID>"      >> $A/.env
# READER: token reaches the MCP child ONLY via SLACK_MCP_BOT_TOKEN.
# SLACK_BOT_TOKEN stays BLANK so the reader NEVER opens a Socket Mode connection.
echo "SLACK_MCP_BOT_TOKEN=<SLACK_BOT_TOKEN>" >> $R/.env
echo "SLACK_BOT_TOKEN="                   >> $R/.env   # deliberately blank
echo SLACK_ENV_DONE'
```

**Verify the reader `slack_native` child actually starts (proves `${...}`
interpolation works).** Reload the reader's MCPs / start a reader gateway briefly
and confirm the child printed `running in reader mode` rather than crashing on a
missing token:
```bash
orgo_bash 'R=/root/.hermes/profiles/reader
# start a short-lived reader gateway to spawn its MCP children, then read the log
tmux kill-session -t rg 2>/dev/null; mkdir -p $R/logs
tmux new-session -d -s rg "export HERMES_HOME=$R HERMES_ALLOW_ROOT_GATEWAY=1 PATH=/tmp/node-v20.18.1-linux-x64/bin:\$PATH; exec hermes gateway run > $R/logs/gateway.log 2>&1"
sleep 8
grep -iE "running in reader mode|SLACK_BOT_TOKEN environment variable is required|starting MCP server .slack_native" $R/logs/gateway.log | tail
tmux kill-session -t rg 2>/dev/null'
```
Expected: a `running in reader mode` (or `starting MCP server 'slack_native'`)
line and **NO** `SLACK_BOT_TOKEN environment variable is required`. If you DO see
the "required" error, the gateway is **not** expanding `${SLACK_MCP_BOT_TOKEN}` —
switch to the fallback wiring (put the literal `<SLACK_BOT_TOKEN>` into the reader
config's `env.SLACK_BOT_TOKEN`, and withhold `SLACK_APP_TOKEN` from the reader to
keep Socket Mode closed). Do not proceed to 12d until the reader child starts
cleanly — an aborting MCP takes down the whole reader agent (Step 11 trap).

### 12d. Socket Mode rule — only the actor opens the connection

This is the crux of the ported design:

- **Actor** has the real `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN`, so its gateway
  opens **the one** Slack Socket Mode connection (live bot presence, receives
  @mentions/DMs, can post).
- **Reader** must NEVER open a second Socket Mode connection (two live
  connections = duplicate event delivery + a flapping presence). So the reader's
  `SLACK_BOT_TOKEN` is left **blank**, and the bot token reaches its MCP child
  **only** through `SLACK_MCP_BOT_TOKEN` (the config maps that into the child's
  `SLACK_BOT_TOKEN` env). The reader can thus call Slack *Web API* reads, but its
  gateway has no app token and no bot token of its own → it cannot and does not
  open Socket Mode.

Add the Slack platform config to the **actor** profile (require-mention,
thread-reply), mirroring the VPS:

```bash
orgo_bash 'python3 - <<"PY"
import yaml, pathlib
p = pathlib.Path("/root/.hermes/profiles/actor/config.yaml")
cfg = yaml.safe_load(p.read_text()) or {}
cfg["slack"] = {"require_mention": True, "unauthorized_dm_behavior": "pair"}
cfg.setdefault("platforms", {})["slack"] = {
    "reply_to_mode": "first",
    "extra": {"reply_in_thread": True, "reply_broadcast": False},
}
p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
print("wrote slack platform config into", p)
PY'
# reload the actor gateway to open Socket Mode + register slack_native(actor):
orgo_bash 'tmux kill-session -t gw 2>/dev/null; sleep 4; \
  tmux new-session -d -s gw "export HERMES_HOME=/root/.hermes/profiles/actor \
  HERMES_ALLOW_ROOT_GATEWAY=1 PATH=/tmp/node-v20.18.1-linux-x64/bin:\$PATH; \
  exec hermes gateway run > /root/.hermes/profiles/actor/logs/gateway.log 2>&1"'
```

**Verify:**
```bash
orgo_bash 'sleep 8
echo "== actor slack tools =="; HERMES_HOME=/root/.hermes/profiles/actor hermes mcp list | grep -i slack
echo "== reader slack tools =="; HERMES_HOME=/root/.hermes/profiles/reader hermes mcp list | grep -i slack
echo "== socket mode (actor only) =="; grep -iE "socket|slack.*connected" /root/.hermes/profiles/actor/logs/gateway.log | tail -3'
```
Expected: actor lists `slack_send_message`/`slack_upload_file`/`slack_download_file`;
reader lists `slack_list_channels`/`slack_get_channel_history`/`slack_get_user_info`/
`slack_download_file` (NO send/upload); the actor log shows ONE Slack Socket Mode
connection, and the reader log shows none. @mention the bot in an invited channel
→ expect a threaded reply.

### 12e. The ~8h stdio-MCP staleness gotcha (and its mitigation)

**Diagnostic signature:** after ~8 h uptime the long-lived stdio `slack_native`
child's pipes hit EOF; the child stays alive (no crash, no new "starting MCP
server 'slack_native'" line), and Hermes raises a **`ClosedResourceError` whose
`str()` is empty** — so `agent.log` shows `MCP tool .../call failed:` with
**nothing after the colon**. Slack reads/posts silently stop working.

**Mitigation (already wired in Step 9):** the watchdog does a **nightly 04:00
restart** of the actor (and reader, if its ingest gateway is up) gateway, which
respawns the `slack_native` MCP child. Confirm after a restart:

```bash
orgo_bash 'grep -i "starting MCP server" /root/.hermes/profiles/actor/logs/gateway.log | tail -2'
```
Expected: a fresh `starting MCP server 'slack_native'` line dated at/after 04:00.
If Slack goes silent *between* nightly restarts, recycle `gw` manually (Step 7
gateway block) — that's the same fix on demand.

---

## Step 13 — End-to-end verification (THE FINAL DELIVERABLE)  **[MAC] + [BOX]**

This is what "done" means. The operator finishes with **both** URLs returning the
right codes, plus Telegram, Gmail, and Slack round-trips verified.

```bash
# ── [MAC] both public URLs ────────────────────────────────────────────────────
curl -s -o /dev/null -w "Console (no auth):  %{http_code}\n" https://safeclaw-<CLIENT>.growthsystems.ai                       # 401
curl -s -o /dev/null -w "Console (auth):     %{http_code}\n" -u <CLIENT>:<UI_PASSWORD> https://safeclaw-<CLIENT>.growthsystems.ai  # 200
curl -s -o /dev/null -w "Hermes dashboard:   %{http_code}\n" https://hermes-<CLIENT>.growthsystems.ai                         # 200

# ── [BOX] every service tmux session present ──────────────────────────────────
orgo_bash 'tmux ls'   # expect 6 sessions: brain, cf, gw, hd, sui, wd

# ── [BOX] brain answers end-to-end (must reference the Step 2b seed page) ──────
orgo_bash 'HERMES_HOME=/root/.hermes hermes chat -q "what do you know about <CLIENT>?" -Q'
# Expected: a non-empty answer that references the seeded people/<CLIENT> page —
# NOT "I don't know". An empty brain (no Step 2b seed) cannot demonstrate this.

# ── [BOX] dreaming proven ─────────────────────────────────────────────────────
orgo_bash 'tail -5 /opt/brain/dream.log'   # 11 phases completed, no embed error
```

### Step 13b — Hand off to the customer (the click-click-click finish)  **[MAC]**

This is the last operator action and the whole point of the productized flow:
the customer connects their own accounts without ever seeing Composio, a token,
or an `.env`.

1. The handoff URL is the **Console connect page** (credential-embedded, one-click):
   `https://<user>:<password>@safeclaw-<CLIENT>.growthsystems.ai/connect-accounts`
   It serves `safeclaw-ui/templates/connect.html` (the per-client card page) and
   each card's `/connect?service=X` route mints a fresh Composio OAuth link
   server-side from `composio-services.json` + `COMPOSIO_API_KEY` (Step 6). The
   API key never reaches the browser.
2. Send that link to the customer over a **private channel** (it embeds the
   access credential — see the memory note on credential-embedded URLs).
3. The customer opens it, lands on **Connections**, and clicks **Connect** on
   each connector they want (Gmail, etc.). Each click mints a fresh Composio
   OAuth link **server-side** (project key never leaves the box), they approve at
   Google, and the account is bound — Reader gets read-only scope, Actor gets
   draft-only. No send tool is ever grantable from that page.
4. Back in **Settings → Setup checklist**, the "accounts connected" row flips
   green as they finish. That is "done."

> **Trust split holds end-to-end:** the customer-facing page can only create
> connections within the boundary's scope. Sending still requires the actor's
> human-approval gate — clicking a connector never grants send/exfiltration.

**The deliverable, panel by panel:**

| Surface | What the operator must see |
|---------|----------------------------|
| `…/connections` (customer) | One card per connector; **Connect with OAuth** opens Google consent, polls, and binds the account. Reader=read-only, Actor=draft — no send. |
| `…/settings` (operator) | Setup checklist all green; Composio project key set; brain alive; **handoff link** ready to copy. |
| `https://safeclaw-<CLIENT>.growthsystems.ai` | Console loads (200 with auth); the **Console Quick Chat** gives a brain-backed reply (this is the *reliable* in-browser chat — `POST /api/chat` → `hermes chat -q`); sidebar **Hermes Dashboard link points at THIS client** (`hermes-<CLIENT>…`, not a hard-coded box). |
| `https://hermes-<CLIENT>.growthsystems.ai` | Dashboard loads (200) and the **Chat tab is present** (`--tui`). **Note:** the dashboard's *terminal* chat (`/api/pty`) 401s through the tunnel **until the CF zone WebSocket pre-flight is done (Step 8d: WebSockets ON, Bot Fight Mode OFF)** — verify with the Step 8d curl (expect 101). The **Console Quick Chat** works regardless (no WebSocket). |
| **Telegram** | DM the bot from the allowed user → brain-backed reply; **0 conflicts** in `actor/logs/gateway.log`. |
| **Gmail** | Ask the actor to list recent threads → it reads; ask it to "send" → it can only **draft**, never sends. |
| **Slack** | @mention the bot in an invited channel → threaded reply (actor posts); reader can `slack_get_channel_history` but has no post tool; exactly ONE Socket Mode connection (actor). |
| **Dreaming** | `dream.log` shows a completed 11-phase run; `hermes cron list` (actor) shows `gbrain-dream` next-run set. |

| Check | Expected |
|-------|----------|
| Console URL (no auth / auth) | 401 / 200 |
| Hermes URL | 200 |
| `tmux ls` | 6 sessions: brain, cf, gw, hd, sui, wd all present |
| Telegram DM | brain-backed reply, 0 conflicts |
| Gmail via actor | drafts only; **never sends** |
| Slack | actor posts; reader read-only; 1 Socket Mode conn |
| Console Quick Chat | brain-backed reply |
| `gbrain dream` | 11 phases in `dream.log`, no embed error |
| `hermes cron list` (actor) | `gbrain-dream` registered |

---

## Step 14 — Golden snapshot / clone for the next client  **[MAC]**

### Decommissioning a replaced box (do this FIRST if migrating)

A replaced box left running will sabotage its successor: its gateway steals the
Telegram bot (~45 s ping-pong, silent message loss — learning #26) and its
cloudflared fights for the tunnel (split-brain 401s — issue 17). Proven
procedure (mark-agent migration, 2026-06-02):

```bash
# Use the OLD box's own orgo key (if not stored, it may be recoverable from the
# session transcript that created it: rg "sk_live_" ~/.claude/projects/<project>/*.jsonl)
OLD_KEY=<old box's orgo key>; OLD_CID=<old box's computer id>
# 1. kill every service in one shot (gateway, cloudflared, console, watchdog)
curl -s -X POST "https://www.orgo.ai/api/computers/$OLD_CID/bash" \
  -H "Authorization: Bearer $OLD_KEY" -H "Content-Type: application/json" \
  -d '{"command":"tmux kill-server"}'
# 2. delete the computer entirely
curl -s -X DELETE "https://www.orgo.ai/api/computers/$OLD_CID" \
  -H "Authorization: Bearer $OLD_KEY"
# 3. verify 404
curl -s "https://www.orgo.ai/api/computers/$OLD_CID" -H "Authorization: Bearer $OLD_KEY"
# 4. then revoke that orgo key (it's now useless anyway) + delete the old CF tunnel
```

If the old box's key is unrecoverable: revoke the Telegram bot token in
@BotFather (kills its poller on the next 401) and `--overwrite-dns` the
hostnames to a new tunnel (issue 17) — the box then idles harmlessly.

### Golden snapshot

Once a box is fully green, snapshot/clone it so the next client comes up in
minutes:

```bash
curl -s -X POST "https://www.orgo.ai/api/computers/$CID/clone" \
  -H "Authorization: Bearer $ORGO_API_KEY"
# new computer inherits Jake's paid workspace ⇒ already always-on; STILL run Step 0c to confirm.
```

**Parameterize per client after cloning** (everything else is baked into the
image — the native stack, profiles, Slack MCP build, watchdog, dream cron):

| Per-client value | Where |
|------------------|-------|
| Tunnel name + `<TUNNEL_ID>` + creds + DNS | `/root/.cloudflared/{config.yaml,<TUNNEL_ID>.json}` |
| Hostnames `safeclaw-<CLIENT>` / `hermes-<CLIENT>` | config.yaml ingress + watchdog `<CLIENT>` |
| Console basic-auth user/pass | `SAFECLAW_UI_USER` + `/opt/safeclaw-ui/.uipass` |
| **Console "Hermes Dashboard" sidebar link** | Derived from `SAFECLAW_UI_USER`=`<CLIENT>` → `hermes-<CLIENT>.growthsystems.ai` (or set `HERMES_DASH_URL` explicitly in the `sui` tmux env). **Confirm the rendered link points at THIS client's dashboard, not a hard-coded one.** |
| Telegram token + allowed user | actor `.env` only |
| Slack tokens/ids (`xoxb`/`xapp`/`T`/`U`) | actor `.env` (+ reader `SLACK_MCP_BOT_TOKEN`) |
| Composio key / user_id / connected_account_id | both profile config.yaml gmail entries |
| Embedding + LLM keys | profile `.env`s + `/opt/brain/.env` + the dream cron command |

> Fold the supervisor / Node 20 / dashboard launch / Slack MCP build / dream cron
> into the golden image plus a boot hook so they come up after a clone without a
> manual tmux start.

---

## tmux session map

| Session | Runs | Restart command |
|---------|------|-----------------|
| `brain` | **ONE** GBrain HTTP server (`gbrain serve --http --port 3131`) — the single PGLite writer; ALL profiles reach it as a URL MCP (Step 2c) | `tmux new-session -d -s brain /opt/launch-brain.sh` |
| `cf` | cloudflared named tunnel (http2) | `tmux new-session -d -s cf "cloudflared tunnel --no-autoupdate --protocol http2 run safeclaw-<CLIENT>"` |
| `wd` | watchdog supervisor (while-true, 30 s; nightly 04:00 slack restart) | `tmux new-session -d -s wd /opt/safeclaw-supervisor.sh` |
| `sui` | SafeClaw Console (Flask, :8899) | re-run the Step 6 tmux block |
| `hd` | Hermes dashboard (`--tui`, :9119) | `tmux new-session -d -s hd /opt/launch-hermes-dash.sh` |
| `gw` | actor gateway: Telegram poller + Slack Socket Mode + **cron scheduler (gbrain dream)** | re-run the Step 7 gateway block |
| `rg` *(optional)* | reader ingest gateway (only when ingesting) | start reader `hermes gateway run` |

> If everything 530/1033s at once: the box napped (shouldn't on paid — recheck
> Step 0c) or `cf`+`wd` died. Recreate `cf` and `wd`; the watchdog brings the
> rest back. **Dreaming and Slack Socket Mode both live inside `gw`** — if `gw`
> is down, the brain won't dream and Slack won't respond. **If `brain` is down,
> EVERY profile's gbrain tool calls fail** (the URL MCP has nothing to talk to) —
> the watchdog restarts it, or `tmux new-session -d -s brain /opt/launch-brain.sh`.

---

## Troubleshooting

| Symptom | Cause → Fix |
|---------|-------------|
| **Cloudflare 530 / error 1033** | Box asleep (re-check `auto-stop` = `0` / `configurable:true`; wrong account if not) **or** cloudflared/`wd` dead → recreate `cf` + `wd`. |
| **502** | Orphan cloudflared (QUIC). `pkill -x cloudflared` (NEVER `-f "cloudflared tunnel"`), recreate `cf`. |
| **400 "Invalid Host header"** on hermes URL | Missing `originRequest.httpHostHeader: localhost` in the tunnel ingress. |
| **Hermes Chat tab missing** | Dashboard launched without `--tui` (or `HERMES_DASHBOARD_TUI=1`). |
| **Hermes Chat tab present but terminal won't connect (WS `/api/pty` → 401 through tunnel)** | Cloudflare is stripping the WebSocket upgrade — NOT a Hermes problem (handshake returns 101 locally on the box). Fix in CF dashboard: zone → **Network → WebSockets ON**, **Security → Bots → Bot Fight Mode OFF**. Verify with the Step 8d curl (expect 101). Tunnel protocol (http2/QUIC) makes no difference. Until fixed, use Console Quick Chat. |
| **`--skip-build` not recognized** | You're on Hermes 0.11 — drop the flag, pre-build `/opt/hermes/web` once. |
| **Telegram "Conflict: terminated by other getUpdates"** | Second poller — token in default/reader `.env`, a `--tui` gateway also polling, an off-box instance on the same bot, or your own getUpdates probe. One bot per box; token only in actor `.env`; don't probe. |
| **Telegram replies, then "stops responding", then replies again (intermittent)** | Conflict ping-pong with the **previous box** that owned this bot — its gateway is still alive and steals the connection every ~45 s; messages it receives are silently lost (learning #26). Kill/delete the old box (Step 14 decommission) or revoke the token in @BotFather. Diagnose: `grep -c conflict gateway.log` keeps growing forever. |
| **Telegram never connects + dashboard Chat tab crashes (React #301)** | Token was configured via the dashboard Config page → it landed in the **default** profile `.env` (learning #25). Move both `TELEGRAM_*` lines to the actor `.env`, recycle `hd` + `gw`. |
| **Gmail "not authenticated" / "user ID does not match"** | MCP URL missing `user_id` (or only `connected_account_id`), or the `x-api-key` header wasn't written into config.yaml. |
| **An MCP with `__FILL_IN__` aborts the whole run** | Comment out any MCP whose creds aren't connected yet (Gmail stays commented until the customer connects). |
| **Slack: `MCP tool …/call failed:` with empty error** | The ~8h stdio `slack_native` staleness (`ClosedResourceError`, empty `str()`). Recycle `gw` (respawns the MCP child); the nightly 04:00 watchdog restart is the standing mitigation. |
| **Slack: duplicate replies / flapping presence** | A SECOND Socket Mode connection — the reader got a real `SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`. Blank the reader's `SLACK_BOT_TOKEN`; route its token only via `SLACK_MCP_BOT_TOKEN`. |
| **Slack: "missing_scope"** | Scope added after install — reinstall the app (Walkthrough Step 8). |
| **Dream never runs** | The cron only fires while a gateway runs — confirm `gw` (actor) is up (`tmux ls`); `hermes cron list` must show `gbrain-dream`. |
| **`GBrain: Timed out waiting for PGLite lock`** | Multiple consumers each spawned a `gbrain serve` stdio MCP and are fighting the single PGLite writer lock (issue 22). Run ONE HTTP server (`tmux brain`, Step 2c) and wire EVERY profile as a URL MCP (`http://127.0.0.1:3131/mcp` + Bearer) — never `hermes mcp add gbrain --command gbrain --args serve`. |
| **`/usr/bin/env: 'bun': No such file or directory`** | The `bun` symlink is missing (issue 21). gbrain's shebang is `#!/usr/bin/env bun`; non-interactive spawns (HTTP server, cron, watchdog, Console) need `bun` on PATH: `ln -sf /root/.bun/bin/bun /usr/local/bin/bun`. |
| **Hermes demands `OPENROUTER_API_KEY` for chat even with provider=ollama** | The installer left `model.base_url: https://openrouter.ai/api/v1` (issue 20). `hermes config set model.base_url https://ollama.com/v1` on EVERY profile. |
| **`gbrain init`/`gbrain auth create` hangs or prints usage** | init hangs on an interactive provider prompt — pass `--embedding-model …` (issue 6). `auth create` needs the `--name` flag (a positional name prints usage — issue 22b). |
| **Dream `sync` phase fails / filesystem phases skipped** | DB-only PGLite brain with no sync repo or zero commits (issue 14). `git init /opt/brain/repo`, `gbrain config set sync.repo_path /opt/brain/repo`, and make ≥1 commit. |
| **Dream embed phase errors `ZEROENTROPY_API_KEY`** | Embedding model not set at init, or `OPENROUTER_API_KEY` not in the dream script's sourced `/opt/brain/.env`. Re-init with `--embedding-model openrouter:openai/text-embedding-3-small` and ensure the dream script sources `/opt/brain/.env`. |
| **GBrain query/search returns [] but get_page works** | The slug uses a hard-excluded prefix (`test/`, `archive/`, `attachments/`, `.raw/`). Use real prefixes like `people/…`; verify with `scripts/smoke-brain.sh`. |
| **Ollama hangs (idle CPU, no error)** | Concurrency-cap HANG (not a 429) — another consumer (e.g. OpenClaw) is sharing the Ollama account. Give it a separate key or stop it. Per-call timeout defaults to 1800s, so a hang won't surface fast. |
| **Weekly Ollama cap vaporizes in ~1 day** | `auxiliary.compression.enabled:false` → O(n²) tokens. Set compression `true`, `max_turns: 25`, `api_max_retries: 2`. |
| **orgo /bash returns `-1` / empty** | Endpoint flakiness — retry; verify state with a read-only follow-up. |
| **Clock drift (TLS/auth failing after a nap)** | Suspend/resume drifted the VM clock. The watchdog re-syncs from Cloudflare's Date header each cycle — confirm `wd` is running. |
| **pkill killed my own command** | `pkill -f "<str>"` matched the orgo bash wrapper's cmdline. Use `pkill -f "wor[d]"` or `pkill -x <exactname>`. |

---

## Open items / not yet templated

- **Golden snapshot not yet proven end-to-end** — the per-client clone path
  (Step 14) is documented but unverified across a full second deploy.
- **Services are tmux-only, not boot-persistent** — after an unexpected
  suspend/resume the tmux sessions may need recreating. Fold supervisor / Node20 /
  dashboard / tunnel / Slack-MCP-build / dream-cron into the golden image + boot
  hook.
- **Hermes dashboard `/chat` through the tunnel** — root cause FOUND (2026-06-01):
  it is **Cloudflare stripping the WS upgrade at the zone layer**, NOT Hermes's
  WS guards (those pass — 101 locally on the box even with tunnel Host/Origin).
  Fix = zone settings (Step 8d: WebSockets ON, Bot Fight Mode OFF) — **awaiting the
  one-time CF dashboard toggle**, then verify with the Step 8d curl (expect 101).
  Until then the **Console Quick Chat tab** (`POST /api/chat`) is the supported
  in-browser chat.
- **Key rotation required (specific live creds, not "when convenient")** — any
  orgo / Ollama / OpenRouter / Composio / Telegram / Slack / UI-password value
  shared in chat must be rotated **before onboarding real client traffic**. In
  particular, the Jake paid-workspace orgo API key and the Mark-box Ollama key +
  UI password were shared in chat and are recorded (in plaintext) in
  brain-personal memory — rotate **those specific values** first, not just
  generically. (Never paste the actual values into this committed doc.)
- **Slack `chat:write.public`/approvals UX** — the VPS used Slack reactions
  (✅/❌) on draft cards for approvals; that approval-card flow is not yet ported
  to the orgo Console and remains a manual @mention-driven flow for now.
```
