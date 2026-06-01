# SafeClaw on orgo.ai — Install Checklist (one page)

> Printable checkbox mirror of `ORGO-CLIENT-TEMPLATE.md`. Tick top-to-bottom.
> Worked example: `<CLIENT>=mark` in Jake McKinney's paid workspace
> (`9898964f-f0f8-4d05-b08c-20b89a2b401d`). **[M]** = Mac, **[B]** = box.
> Never write real secrets — use placeholders.

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
- [ ] `pip3 install --break-system-packages flask pyyaml requests`
- [ ] Node 20 tarball at `/tmp/node-v20.18.1-linux-x64/bin` + symlinks
- [ ] **cloudflared installed ON THE BOX** (`/usr/local/bin/cloudflared`, +x); `cloudflared --version` resolves
- [ ] gbrain cloned from `github.com/garrytan/gbrain` (NO `|| true`), `bun install && bun link`, symlinked to `/usr/local/bin/gbrain`
- [ ] Hermes installed via `setup-hermes.sh` (`>=0.11 for cron; prefer 0.15.1`); symlinked `/usr/local/bin/hermes`; **croniter installed**
- [ ] default profile: provider=ollama, **model=glm-4.7 (NOT kimi-k2.5)**; `OLLAMA_API_KEY` in `.env`
- [ ] `hermes mcp add gbrain --command gbrain --args serve`
- [ ] Verify: `which hermes` + `which gbrain` resolve; `hermes --version` (>=0.11); `mcp list | grep gbrain` = 1
- [ ] **Credential pool:** `hermes auth add ollama-cloud --type api-key --api-key <OLLAMA_FALLBACK_KEY> --label fallback` → `auth list` shows 2 creds (provider id `ollama-cloud`, NOT `custom`; pool is cached at gateway boot — recycle `gw` after later `auth add`)

### Step 2 — GBrain init + EMBEDDINGS (required)  **[B]**
- [ ] `GBRAIN_HOME=/opt/brain gbrain init --pglite` (NO `2>/dev/null || true` — must fail loudly)
- [ ] `.gbrain/config.json`: `embedding_model=openrouter:openai/text-embedding-3-small`, `dims=1536` (FILE config, not `config set`)
- [ ] `OPENROUTER_API_KEY` in `/opt/brain/.env` (OR OpenAI: `openai:text-embedding-3-small` + `OPENAI_API_KEY` — gbrain supports both)
- [ ] Verify: `gbrain embed --stale` runs with NO `ZEROENTROPY_API_KEY` error

### Step 2b — Seed the brain (identity/client page)  **[B]**
- [ ] Seed ≥1 real page (`gbrain put-page "people/<CLIENT>" …` or `scripts/bootstrap-brain.sh`), then `gbrain embed --stale`
- [ ] Verify: `gbrain list_pages | grep <CLIENT>` AND `gbrain query "<CLIENT>"` returns seeded content (proves embeddings are real, not an empty-brain no-op)

### Step 3 — Hermes profiles (reader / actor trust split)  **[B]**
- [ ] reader + actor profiles created; each: provider=ollama, **model=glm-4.7 (NOT kimi-k2.5)**, `OLLAMA_API_KEY` in `.env`
- [ ] **Token-economy knobs on BOTH profiles:** `agent.auxiliary.compression.enabled=true`, `agent.max_turns=25`, `agent.api_max_retries=2` (defaults cause O(n²) tokens → weekly cap dies in ~1 day)
- [ ] credential pool (`<OLLAMA_FALLBACK_KEY>`) added to BOTH profiles
- [ ] gbrain MCP added to BOTH profiles
- [ ] default `.env` has NO Telegram token, NO Slack app token
- [ ] **Concurrency rule noted:** reader+actor share the Ollama concurrency budget → separate keys/pool entries OR keep only actor hot; **never run OpenClaw on the same account** (saturation HANGS calls at `Auxiliary auto-detect`, not a 429)
- [ ] Verify: `mcp list` (both) → `gbrain`; `config get agent.max_turns`=25; `compression.enabled`=true; `auth list`=2 creds

### Step 4 — DREAMING: `gbrain dream` as Hermes cron  **[B]**
- [ ] `hermes cron create gbrain-dream --schedule "0 3 * * *"` (in **actor** profile)
- [ ] cron command exports `GBRAIN_HOME` + `OPENROUTER_API_KEY` inline, logs to `/opt/brain/dream.log`
- [ ] Verify: `hermes cron list` (actor) shows `gbrain-dream`, next-run set
- [ ] Force one run → `dream.log` shows 11 phases (incl. `patterns`), no embed error
- [ ] **Scheduler proven** (not just the binary): `hermes cron run gbrain-dream` OR a cron-fire line in `actor/logs/gateway.log` (cron only fires while `gw` runs)

### Step 5 — Routines / workflows  **[B]**
- [ ] Client routines registered as `hermes cron` entries in the **actor** profile (only actor cron fires)
- [ ] Routine schedules kept **off 03:00 (dream) and 04:00 (watchdog gateway recycle)** windows
- [ ] Verify: `hermes cron list` (actor) shows all routines with next-run times

### Step 6 — SafeClaw Console (Flask) + basic-auth  **[B]**
- [ ] `/opt/safeclaw-ui` populated; `.uipass` written, chmod 600
- [ ] tmux `sui`: `SAFECLAW_UI_USER=<CLIENT>`/`SAFECLAW_UI_PASS`, PORT 8899, HOST 127.0.0.1
- [ ] Sidebar **Hermes Dashboard link** is client-aware (derives `hermes-<CLIENT>…` from `SAFECLAW_UI_USER`, or `HERMES_DASH_URL`) — NOT a hard-coded box
- [ ] Verify: `curl /healthz` → 200; know the `/api/selftest` "SYSTEM TEST" card (Hermes/GBrain/profiles/real Gmail per inbox/Telegram/tunnel/clock/LLM key — auto-restarts actor gw)

### Step 7 — Hermes dashboard (`--tui`) + actor gateway  **[B]**
- [ ] tmux `hd`: `hermes dashboard --port 9119 --host 0.0.0.0 --no-open --tui --insecure [--skip-build]` (launch script auto-drops `--skip-build` on <0.15; setup-hermes.sh pre-built `/opt/hermes/web` there)
- [ ] tmux `gw`: actor `hermes gateway run` (hosts Telegram + Slack Socket Mode + cron)
- [ ] Verify: `curl -H "Host: localhost" :9119/` → 200

### Step 8 — Cloudflare named tunnel (TWO hostnames, ONE tunnel)  **[M]→[B]**
- [ ] `[M]` `cloudflared tunnel create safeclaw-<CLIENT>` (note `<TUNNEL_ID>`)
- [ ] `[M]` route DNS for `safeclaw-<CLIENT>` AND `hermes-<CLIENT>` (no new API token)
- [ ] `[M]→[B]` copy `<TUNNEL_ID>.json` + `cert.pem` to `/root/.cloudflared/` (chmod 600)
- [ ] `[B]` config.yaml: Console→8899; Hermes→9119 with `originRequest.httpHostHeader: localhost`
- [ ] tmux `cf`: `cloudflared tunnel --no-autoupdate --protocol http2 run safeclaw-<CLIENT>`
- [ ] Verify `[M]`: Console 401/200, Hermes 200

### Step 9 — Watchdog / supervisor (tmux-only)  **[B]**
- [ ] `/opt/safeclaw-watchdog.sh` checks 8899/9119/cf/`gw`, restarts dead, re-syncs clock /30s
- [ ] Watchdog includes **nightly 04:00 actor(+reader) gateway restart** (Slack 8h-stale fix)
- [ ] tmux `wd` running supervisor (`while true; sleep 30`)
- [ ] Verify: kill `sui`, wait 40 s → `/healthz` 200 (auto-healed)

### Step 10 — Telegram (dedicated bot per box)  **[B]**
- [ ] `<TELEGRAM_BOT_TOKEN>` + `TELEGRAM_ALLOWED_USERS=<TELEGRAM_NUMERIC_USER_ID>` in **actor `.env` ONLY** (numeric id via @userinfobot or the gateway log's `from.id` — NOT a Slack `U…` id)
- [ ] actor `gw` recycled; no getUpdates probes
- [ ] Verify: gateway.log shows connected/polling, **0 conflicts**, `gbrain 87 tools` loaded, secret-redaction on; allowed user's DM accepted (NOT `unauthorized`) → brain reply

### Step 11 — Composio Gmail trust split  **[B]**
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
- [ ] `tmux ls` → cf, wd, sui, hd, gw
- [ ] Telegram round-trip ✓ (0 conflicts)
- [ ] Gmail round-trip ✓ (drafts only, never sends)
- [ ] Slack round-trip ✓ (actor posts, reader read-only, 1 Socket Mode)
- [ ] `dream.log` → 11 phases (incl. `patterns`), no embed error; `hermes cron list` shows `gbrain-dream`

### Step 14 — Golden snapshot / clone next client  **[M]**
- [ ] `POST /computers/$CID/clone`
- [ ] Re-run Step 0c on the clone (confirm always-on)
- [ ] Parameterize: tunnel/DNS, hostnames, UI pass, **Console Hermes-link (`SAFECLAW_UI_USER`/`HERMES_DASH_URL`)**, Telegram, Slack tokens, Composio ids, embed/LLM keys

### Final
- [ ] All shared secrets ROTATED (orgo, Ollama, OpenRouter, Composio, Telegram, Slack, UI)
- [ ] **Rotate the SPECIFIC live creds shared in chat BEFORE real traffic** (Jake paid-workspace orgo key + Mark-box Ollama key + UI pass are in brain-personal plaintext) — not "when convenient"
- [ ] Open items reviewed (boot-persistence, golden-snapshot proof, dashboard WS, Slack approval cards)
