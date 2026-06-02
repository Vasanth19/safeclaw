# SafeClaw on orgo.ai — Install Checklist (one page)

> Printable checkbox mirror of `ORGO-CLIENT-TEMPLATE.md`. Tick top-to-bottom.
> Worked example: `<CLIENT>=mark` in Jake McKinney's paid workspace
> (`9898964f-f0f8-4d05-b08c-20b89a2b401d`) — first real install 2026-06-01,
> **Hermes 0.15.1 + gbrain 0.42.1**, tunnel `safeclaw-mark-v2`, **6 tmux**
> (`brain`,`cf`,`gw`,`hd`,`sui`,`wd`). **[M]** = Mac, **[B]** = box.
> Never write real secrets — use placeholders.
>
> **Operator helper:** use the PURE-PYTHON `orgo_bash.py` (urllib, 6 retries,
> 5→30 s backoff) — orgo throws 503/502/conn-refused bursts lasting 30–60 s.
> **Verify every deploy command landed with a separate read-only call.** NEVER
> `sleep 30+` inside a /bash command. NEVER `pkill -f <str>` if `<str>` appears in
> your command (matches heredoc body — self-kill); use PID or `pkill -x`.

**Client:** `<CLIENT> = ____________`  ·  **CID:** `____________`  ·  **Date:** `________`

---

### Step 0 — Workspace + computer, ALWAYS-ON  **[M]**  (load-bearing — don't skip)
- [ ] `GET /api/me` → confirms **Jake's PAID** workspace (`jake@rspur.com`), not free
- [ ] Computer `<CLIENT>-agent` created via `POST /api/computers {"workspace_id":"9898…b401d","name":"<CLIENT>-agent"}`; parse `id` → `export CID=…`
- [ ] (Use the always-on **`mark-agent`** `7136d3d6…`, NOT the retired FREE box `cd6ec0dc…` that suspends every 15 min)
- [ ] `GET /computers/$CID/auto-stop` → `"configurable": true`  (false ⇒ WRONG ACCOUNT, STOP)
- [ ] `PATCH auto-stop {"auto_stop_minutes":0}` → 200  (403 ⇒ WRONG ACCOUNT, STOP)
- [ ] `orgo_bash "uname -a && nproc"` → Linux, 4 CPU, ~15 GB

### Step 1 — Base software (native, NO Docker)  **[B]**
- [ ] `git clone -b main …/safeclaw /opt/safeclaw`
- [ ] `apt-get install -y python3-pip unzip` (**unzip REQUIRED** — bun's installer needs it; fresh 24.04 lacks it — issue 2)
- [ ] `pip3 install --break-system-packages flask pyyaml requests`
- [ ] Node 20 tarball at `/tmp/node-v20.18.1-linux-x64/bin` + symlinks
- [ ] **cloudflared installed ON THE BOX** (`/usr/local/bin/cloudflared`, +x); `cloudflared --version` resolves
- [ ] gbrain cloned (NO `|| true`), `bun install && bun link`, symlinked `/usr/local/bin/gbrain`
- [ ] **`bun` symlinked: `ln -sf /root/.bun/bin/bun /usr/local/bin/bun`** (gbrain shebang is `#!/usr/bin/env bun` — every non-interactive spawn fails without it — issue 21)
- [ ] Hermes installed via `setup-hermes.sh` (prefer 0.15.1); **symlink probes `/opt/hermes/venv/bin/hermes` then `~/.local/bin/hermes`** (NOT `/opt/hermes/bin/hermes` — issue 3); **croniter installed**
- [ ] **Run `setup-hermes.sh` BARE, check exit code, THEN tail log — NEVER `… | tail`** (a pipe masks the exit code — issue 4)
- [ ] default profile: provider=ollama, **model=glm-4.7 (NOT kimi-k2.5)**; **`hermes config set model.base_url https://ollama.com/v1`** (installer ships openrouter base_url → demands OPENROUTER_API_KEY — issue 20); `OLLAMA_API_KEY` in `.env`
- [ ] **gbrain NOT wired here** — wired as URL MCP after Step 2 (issue 5/22)
- [ ] Verify: `which hermes`+`which gbrain`+`which bun` resolve; `hermes --version` (>=0.11; gbrain **0.42.x**); `hermes config show | grep base_url` = `https://ollama.com/v1`
- [ ] **Credential pool:** `hermes auth add ollama-cloud --type api-key …` → `auth list` shows 2 creds (provider id `ollama-cloud`, NOT `custom`; pool cached at gateway boot — recycle `gw` after later `auth add`)

### Step 2 — GBrain init + EMBEDDINGS + sync repo (required)  **[B]**
- [ ] `OPENROUTER_API_KEY` exported in the SAME shell, then `gbrain init --pglite --embedding-model openrouter:openai/text-embedding-3-small` (plain `init --pglite` hangs on interactive prompt; the old `.gbrain/config.json` file-hack is OBSOLETE — issue 6)
- [ ] `OPENROUTER_API_KEY` in `/opt/brain/.env` (OR OpenAI: `--embedding-model openai:text-embedding-3-small` + `OPENAI_API_KEY`)
- [ ] **Sync repo (issue 14):** `git init /opt/brain/repo` (+ user.email/name), `gbrain config set sync.repo_path /opt/brain/repo` (DB-only PGLite skips dream's filesystem phases without it)
- [ ] Verify: `gbrain config show | grep -E "embedding_model|repo_path"`; `gbrain embed --stale` with NO `ZEROENTROPY_API_KEY` error
- [ ] **Budget note:** gbrain 0.42 auto-sets `chat_model=openrouter:openai/gpt-5.2` → dream's LLM phases bill the OpenRouter key (issue 7)

### Step 2c — ONE GBrain HTTP server (PGLite single-writer lock)  **[B]** ⭐ KEY ARCH CHANGE
- [ ] `/opt/launch-brain.sh` (exports GBRAIN_HOME/PATH, sources `/opt/brain/.env`) → tmux `brain`: `gbrain serve --http --port 3131` (PGLite allows ONE writer; multiple stdio `gbrain serve` MCPs deadlock on the lock — issue 22)
- [ ] Mint token: `gbrain auth create --name hermes` (**needs `--name`** — positional prints usage — issue 22b) → save to `/opt/brain/.hermes-token` chmod 600
- [ ] Wire gbrain as a **URL MCP** into EVERY profile (default+reader+actor) via PyYAML: `url: http://127.0.0.1:3131/mcp`, `headers.Authorization: "Bearer <GBRAIN_HTTP_TOKEN>"` — NOT a stdio `mcp add gbrain --command gbrain --args serve`
- [ ] Verify: `curl http://127.0.0.1:3131/mcp` → **405** (= alive; conn-failure = `brain` session died)

### Step 2b — Seed the brain (identity/client page) + first commit  **[B]**
- [ ] Seed ≥1 page via STDIN: `gbrain put "people/<CLIENT>" < file.md` (**`put-page` does NOT exist in 0.42** — issue 8; auto-embeds at put time → "Embedded 0 chunks" after a put is NORMAL)
- [ ] **First sync commit:** `cd /opt/brain/repo && git add -A && git commit -m "initial seed"` (dream `sync` fails with zero commits — issue 14)
- [ ] Verify: `gbrain list_pages | grep <CLIENT>` AND `gbrain query "<CLIENT>"` returns seeded content

### Step 3 — Hermes profiles (reader / actor trust split)  **[B]**
- [ ] **`hermes profile create <name>`** (singular `profile`; **NO `-p` flag** — operate via `HERMES_HOME=/root/.hermes/profiles/<name>` — issue 9); create COPIES default config+pool (issue 11)
- [ ] each profile: provider=ollama, **model=glm-4.7**, **`model.base_url=https://ollama.com/v1`** (issue 20)
- [ ] **Token-economy knobs on BOTH:** `agent.auxiliary.compression.enabled=true`, `agent.max_turns=25`, `agent.api_max_retries=2`
- [ ] **Different PRIMARY keys (issue 11):** actor=dedicated key, reader=shared key, each with the other as pool fallback (true concurrency isolation)
- [ ] gbrain URL MCP added to BOTH profiles (in Step 2c-c — NOT stdio)
- [ ] default `.env` has NO Telegram token, NO Slack app token
- [ ] **Concurrency rule:** reader+actor share the Ollama concurrency budget → separate keys OR keep only actor hot; **never run OpenClaw on the same account** (saturation HANGS at `Auxiliary auto-detect`, not a 429)
- [ ] Verify: `hermes config show | grep <key>` (**`config get` does NOT exist** — issue 10) → `max_turns: 25`, `compression.enabled: true`, `base_url`; `mcp list` → `gbrain`; `auth list`=2 creds

### Step 4 — DREAMING: `gbrain dream` as Hermes cron  **[B]**
- [ ] Dream **script** at `$HERMES_HOME/scripts/gbrain-dream.sh` (actor): exports GBRAIN_HOME/PATH, sources `/opt/brain/.env`, **STOPS `tmux brain` → `gbrain dream` → RESTARTS `tmux brain`** (dream CLI needs the PGLite lock the HTTP server holds — issue 22d), tees `/opt/brain/dream.log`
- [ ] Register cron (**new 0.15.1 syntax — issue 12**): `hermes cron create "0 3 * * *" --name gbrain-dream --script gbrain-dream.sh --no-agent` (schedule POSITIONAL; NO `--command`; `--no-agent` = no LLM tokens; script lives in `scripts/`)
- [ ] Verify: `hermes cron list` (actor) shows `gbrain-dream`, next-run set
- [ ] Force one run via the **script** → `dream.log` shows 11 phases (incl. `sync`,`patterns`), no embed error; `:3131` back to 405
- [ ] **Scheduler proven**: `hermes cron run gbrain-dream` OR a cron-fire line in `actor/logs/gateway.log` (cron only fires while `gw` runs)

### Step 5 — Routines / workflows  **[B]**
- [ ] Client routines = `hermes cron` entries in the **actor** profile, **new syntax** (positional schedule + `--script`; issue 12); only actor cron fires
- [ ] Routine schedules kept **off 03:00 (dream) and 04:00 (watchdog gateway recycle)** windows
- [ ] Verify: `hermes cron list` (actor) shows all routines with next-run times

### Step 6 — SafeClaw Console (Flask) + basic-auth  **[B]**
- [ ] `/opt/safeclaw-ui` populated; `.uipass` written, chmod 600
- [ ] tmux `sui`: `SAFECLAW_UI_USER=<CLIENT>`/`SAFECLAW_UI_PASS`, PORT 8899, HOST 127.0.0.1
- [ ] Sidebar **Hermes Dashboard link** is client-aware (derives `hermes-<CLIENT>…` from `SAFECLAW_UI_USER`, or `HERMES_DASH_URL`) — NOT a hard-coded box
- [ ] Verify: `curl /healthz` → **200 OR 401** (the Console `/healthz` is **auth-gated** — issue 16; both codes mean alive); know the `/api/selftest` "SYSTEM TEST" card (Hermes/GBrain/profiles/real Gmail per inbox/Telegram/tunnel/clock/LLM key — auto-restarts actor gw)

### Step 7 — Hermes dashboard (`--tui`) + actor gateway  **[B]**
- [ ] tmux `hd`: `hermes dashboard --port 9119 --host 0.0.0.0 --no-open --tui --insecure [--skip-build]` (launch script auto-drops `--skip-build` on <0.15; setup-hermes.sh pre-built `/opt/hermes/web` there)
- [ ] tmux `gw`: actor `hermes gateway run` (hosts Telegram + Slack Socket Mode + cron)
- [ ] Verify: `curl -H "Host: localhost" :9119/` → 200

### Step 8 — Cloudflare named tunnel (TWO hostnames, ONE tunnel)  **[M]→[B]**
- [ ] `[M]` `cloudflared tunnel create safeclaw-<CLIENT>` → capture **UUID** `<TUNNEL_ID>`
- [ ] `[M]` route DNS for both hostnames **BY UUID, never by name** (name can route to the WRONG tunnel — issue 18); no new API token
- [ ] **Re-pointing from an old box?** if the old box still runs cloudflared on that tunnel → split-brain → intermittent 401s. Make a **NEW tunnel `safeclaw-<CLIENT>-v2`** + `route dns --overwrite-dns <UUID> <host>` (issue 17). (Mark = `safeclaw-mark-v2`.)
- [ ] `[M]→[B]` copy `<TUNNEL_ID>.json` + `cert.pem` to `/root/.cloudflared/` (chmod 600)
- [ ] `[B]` config.yaml: Console→8899; Hermes→9119 with `originRequest.httpHostHeader: localhost`
- [ ] tmux `cf`: `cloudflared tunnel --no-autoupdate --protocol http2 run safeclaw-<CLIENT>[-v2]`
- [ ] Verify `[M]`: Console 401/200, Hermes 200

### Step 9 — Watchdog / supervisor (tmux-only)  **[B]**
- [ ] `/opt/safeclaw-watchdog.sh` checks 8899/9119/**3131 (brain)**/cf/`gw`, restarts dead, re-syncs clock /30s
- [ ] **Console `:8899` check treats 401 AND 200 as alive** (auth-gated /healthz — issue 16)
- [ ] **Brain `:3131` check: any HTTP code = alive (405 expected), only conn-failure = dead → restart `/opt/launch-brain.sh`** (issue 22e)
- [ ] Watchdog includes **nightly 04:00 actor(+reader) gateway restart** (Slack 8h-stale fix)
- [ ] tmux `wd` running supervisor (`while true; sleep 30`)
- [ ] Verify: kill `sui`, wait 40 s → `/healthz` 200/401 (auto-healed)

### Step 10 — Telegram (dedicated bot per box)  **[B]**
- [ ] `<TELEGRAM_BOT_TOKEN>` + `TELEGRAM_ALLOWED_USERS=<TELEGRAM_NUMERIC_USER_ID>` in **actor `.env` ONLY** (numeric id via @userinfobot or the gateway log's `from.id` — NOT a Slack `U…` id)
- [ ] **NOT via the dashboard Config page** (writes to default profile → crashes `--tui` gateway, learning #25); if already done: move TELEGRAM_* lines to actor `.env`, recycle `hd`+`gw`
- [ ] **Bot reused from an old box?** That box's gateway must be DEAD first (Step 14 decommission) or revoke the token in @BotFather (learning #26 — the competing poller silently eats messages)
- [ ] actor `gw` recycled; no getUpdates probes
- [ ] Verify: gateway.log shows connected/polling, **0 conflicts**, `gbrain 88 tools` loaded (gbrain 0.42), secret-redaction on; allowed user's DM accepted (NOT `unauthorized`) → brain reply

### Step 11 — Composio Gmail trust split  **[B]**
- [ ] **RE-LIST IDs LIVE before wiring (issue 24):** `GET /api/v3/connected_accounts` (gmail account + its `user_id`) and `GET /api/v3/mcp/servers` (reader/actor server URLs) — `user_id`/`connected_account_id` go stale; do NOT trust docs/memory
- [ ] Two Composio MCP servers created (`<READER_MCP_BASE_URL>` read-only, `<ACTOR_MCP_BASE_URL>` draft **NO SEND**) — Console `/api/gmail/wire` is the primary path
- [ ] reader MCP (read-only) + actor MCP (draft, **NO SEND**) written into each profile `config.yaml`
- [ ] URL has BOTH `user_id` (the `pg-test-…` string) + `connected_account_id`; `x-api-key` header in config (not via `mcp add --url`)
- [ ] **Multi-inbox:** each Gmail account has its OWN `auth_config` — bind each server to the matching account or "No connected account found" (Console self-heals)
- [ ] Composio routes: list/create `/mcp/servers`; item GET/DELETE `/api/v3/mcp/{id}` (not `/mcp/servers/{id}` → 404 HTML)
- [ ] Verify: actor lists `gmail_actor` (draft); reader lists `gmail_reader` (read-only)

### Step 12 — SLACK (ported from VPS)  **[B]/[M]**
- [ ] **12a** Client built Slack app (full scope list); collected `xoxb-`, `xapp-`, `T…`, `U…` (see `docs/SLACK-APP-WALKTHROUGH.md`)
- [ ] **12b** `mcp-tools/slack-api` → `/opt/mcp-tools/slack-api`; `npm install` + `npm run build` (Node 20) → `dist/index.js`
- [ ] **12c** `slack_native` MCP wired into BOTH profiles (reader mode = read-only; actor mode = post)
- [ ] **12c** actor `.env`: real `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` (+ `T…`/`U…`)
- [ ] **12d** reader `.env`: `SLACK_MCP_BOT_TOKEN=<xoxb>`; `SLACK_BOT_TOKEN=` **blank** (no 2nd Socket Mode)
- [ ] **12c VERIFY interpolation:** reader `slack_native` child starts (`running in reader mode`) — NO `SLACK_BOT_TOKEN environment variable is required`. If it errors, gateway isn't expanding `${...}` → put literal token in reader `env.SLACK_BOT_TOKEN`, withhold `SLACK_APP_TOKEN` (an aborting MCP kills the whole reader agent)
- [ ] **12d** actor `config.yaml`: slack `require_mention` + thread-reply platform config; gateway recycled
- [ ] Verify: actor = send/upload tools; reader = list/history (no post); ONE Socket Mode conn; @mention → threaded reply
- [ ] **12e** Aware of ~8h stale signature (`ClosedResourceError`, empty error) → nightly 04:00 restart mitigates

### Step 13 — END-TO-END (THE DELIVERABLE)  **[M]+[B]**
- [ ] `https://safeclaw-<CLIENT>.growthsystems.ai` → 401 no-auth / **200 auth**; **Console Quick Chat** brain-backed reply (the *reliable* chat); sidebar Hermes link → `hermes-<CLIENT>…`
- [ ] `https://hermes-<CLIENT>.growthsystems.ai` → **200**; Chat tab present (`--tui`). NOTE: dashboard *terminal* chat may 401 through tunnel — Console Quick Chat is the verified path
- [ ] Brain-backed: `hermes chat "what do you know about <CLIENT>?"` references the Step 2b seed page (NOT "I don't know")
- [ ] `tmux ls` → **6 sessions: brain, cf, gw, hd, sui, wd**
- [ ] Telegram round-trip ✓ (0 conflicts)
- [ ] Gmail round-trip ✓ (drafts only, never sends)
- [ ] Slack round-trip ✓ (actor posts, reader read-only, 1 Socket Mode)
- [ ] `dream.log` → 11 phases (incl. `patterns`), no embed error; `hermes cron list` shows `gbrain-dream`

### Step 14 — Golden snapshot / clone next client  **[M]**
- [ ] **Decommission any replaced box FIRST:** old box's own key → `tmux kill-server` via /bash → `DELETE /computers/{id}` → verify 404 → revoke its orgo key + delete its CF tunnel (else it steals the Telegram bot + tunnel from the new box)
- [ ] `POST /computers/$CID/clone`
- [ ] Re-run Step 0c on the clone (confirm always-on)
- [ ] Parameterize: tunnel/DNS, hostnames, UI pass, **Console Hermes-link (`SAFECLAW_UI_USER`/`HERMES_DASH_URL`)**, Telegram, Slack tokens, **re-listed Composio ids (issue 24)**, embed/LLM keys, **gbrain HTTP bearer token (`/opt/brain/.hermes-token`)**

### Final
- [ ] All shared secrets ROTATED (orgo, Ollama, OpenRouter, Composio, Telegram, Slack, UI)
- [ ] **Rotate the SPECIFIC live creds shared in chat BEFORE real traffic** (Jake paid-workspace orgo key + Mark-box Ollama key + UI pass are in brain-personal plaintext) — not "when convenient"
- [ ] Open items reviewed (boot-persistence, golden-snapshot proof, dashboard WS, Slack approval cards)
