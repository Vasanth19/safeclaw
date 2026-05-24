# Suffolk Deployment Guide — SafeClaw (GBrain-backed) — RUNNING DOC

> **This is a living document.** Update the **Current Status** block and the **Update Log** every time the deploy moves or a new nuance is found. Secrets live in `suffolk.env` (gitignored) — never put them here.

---

## ⭐ CURRENT STATUS — START HERE (new agent: read this first)

**As of 2026-05-24 (session 5). The full stack is DEPLOYED and RUNNING. The LLM works, the reader runs the ingest end-to-end and SUCCESSFULLY READS SLACK (49 human messages pulled from `callrail-new-daily-calls`), and the ACTOR is now recreated on the correct LLM env (kimi-k2.5) so it answers Slack. Pages are still 0 because of TWO remaining, well-understood blockers below — both need an operator action only you can do.**

### ✅ Fixed & deployed (session 5 — actor)
- **hermes-actor recreated onto the correct LLM env** (was the old broken `glm-5.1:cloud` + dead `:11435` + `ollama-local` placeholder). Box was already at the fixed commit `bffe1f4`, so `docker compose up -d --force-recreate hermes-actor` was enough — actor now runs `kimi-k2.5` / `https://ollama.com/v1` / real key and answers Slack. Booted clean; only error is the known optional Telegram `__FILL_IN__` token (non-fatal). Brookhaven `/health` verified `{"status":"ok"}` after. This was blocker #2 — now closed.

### ✅ Fixed & deployed earlier session (reader)
- **LLM credential** — the box's `OLLAMA_API_KEY` was a 12-char placeholder (`ollama-local`, hardcoded in the compose `environment:` block, which overrode `.env`). The REAL 57-char key lives in `suffolk.env`. Fixed by: removing the hardcoded `OLLAMA_API_KEY` from both `environment:` blocks so it flows from `env_file:.env`, and writing the real key into the box `.env`. Verified working (`/v1/chat/completions` → 200).
- **LLM endpoint** — `OLLAMA_BASE_URL` pointed at the dead local daemon `host.docker.internal:11435` (the true cause of the original `APIConnectionError`). Changed to `https://ollama.com/v1` in both blocks.
- **Model** — was `glm-5.1:cloud` (does not exist). Switched to **`kimi-k2.5`** (agentic, the model the config author wanted) after `glm-4.6` tripped a Hermes OpenAI-compat tool-call parse bug (`'str' object has no attribute 'get'` at API call #13). kimi-k2.5 reads Slack cleanly.
- All of the above are committed (branch `feat/safeclaw-brain-gbrain`, latest `bffe1f4`) and deployed to **hermes-reader** on the box.

### 🔴 TWO remaining blockers (both operator-only)
1. **[OPERATOR] Brain embeddings — host Ollama bind.** GBrain embeds each page via the host Ollama (`nomic-embed-text`). The brain reaches it at `host.docker.internal` → `172.17.0.1:11434`, but host Ollama binds **`127.0.0.1` only** (verified again session 5: `ss -tlnp` shows `127.0.0.1:11434`) → connection refused → `put_page` fails → 0 pages. **Ollama Cloud has NO embeddings endpoint (`/v1/embeddings` 404), so cloud is not an option — the local embedder is required.** FIX (host change, needs you — the auto-mode classifier blocks an agent from doing this):
   ```bash
   ssh suffolk-vps 'mkdir -p /etc/systemd/system/ollama.service.d && printf "[Service]\nEnvironment=\"OLLAMA_HOST=172.17.0.1:11434\"\n" > /etc/systemd/system/ollama.service.d/override.conf && systemctl daemon-reload && systemctl restart ollama && sleep 4 && ss -tlnp | grep 11434 && curl -s https://srv1687869.hstgr.cloud/health'
   ```
   Bind to `172.17.0.1` (docker bridge), NOT `0.0.0.0` — no host firewall is active, so `0.0.0.0` would expose the unauthenticated Ollama API publicly.
2. **[OPERATOR] Slack attachments — bot lacks `files:read`.** The `xoxb-` bot (`aiassistant` @ "Suffolk County House Buyers") has history/read scopes but NOT `files:read`, so Slack refuses to hand over file bytes → videos/images sent to the assistant can't be downloaded. FIX: api.slack.com/apps → aiassistant → OAuth & Permissions → add **`files:read`** → **Reinstall to Workspace** → put the new `xoxb-` token in `suffolk.env` + box `.env`. Also: the bot is a member of only **1 of 71 channels** — `/invite @aiassistant` into any channel you want ingested.

### ▶️ To finish (once blocker #1 is done — agent CAN do these)
```bash
ssh suffolk-vps 'cd /opt/safeclaw && docker compose exec -T -u 10000 hermes-reader /opt/hermes/.venv/bin/hermes cron run 187b27fb908d'   # slack_ingest job id
# wait ~120s (kimi is a thinking model), then:
ssh suffolk-vps 'docker exec safeclaw-brain gbrain stats'   # Pages should go > 0
```

- **What's up on the box (`/opt/safeclaw`, branch `feat/safeclaw-brain-gbrain`):** `safeclaw-brain` (GBrain, Postgres engine, Ollama embeddings) + `postgres-brain` + `postgres-tasks` + `postgrest` + `reflector` + `rclone` + `onboarding` + **both `hermes-reader` and `hermes-actor`** — all Up. Brain tokens minted, agents on a natively-built amd64 image.
- **🟢 INGESTION WIRED + DEPLOYED (session 3) — cron fires and the reader reads Slack (session 4); now blocked only by the embeddings bind (blocker #1 above).** Root cause was confirmed: this Hermes version's gateway config loader ignores the `schedules:` key, so the `slack_ingest` cron never registered. **Fix shipped on the branch:** a new translator `scripts/safeclaw-cron-sync.py` reads the config's `schedules:` block and registers each entry in Hermes' REAL cron store (`$HERMES_HOME/cron/jobs.json` = `/opt/data/cron/jobs.json`, which `gateway run` ticks every 60s). It's invoked from `scripts/hermes-docker-init.sh` as the `hermes` user (uid 10000, so jobs.json ownership is right) with `HERMES_HOME=/opt/data` pinned, reading the mounted template `/safeclaw/config-template/config.yaml`. Idempotent + declarative: jobs are tagged `origin.source=safeclaw-config-sync`, so re-runs create/update/prune only sync-managed jobs and never touch agent/operator-created ones. **All files are bind-mounted → NO image rebuild needed; just `docker compose up -d` (recreate) on the box** (see deploy steps below). Verified locally against the real `cron.jobs` API (create/idempotent-noop/prune all pass).
- **🟡 Gmail ingestion (separate) — provisioner now v3-correct; still needs the customer to connect Gmail.** The Composio MCP provisioner (`onboarding/lib/validator.py::provision_composio_mcps`) was rewritten to the current v3 API: (1) get-or-create a Composio-managed **Gmail auth config**, (2) `POST /api/v3/mcp/servers` with `auth_config_ids` + `allowed_tools` + `managed_auth_via_composio`, (3) scope each returned `mcp_url` with `?user_id=`. Composio is **Gmail-only** now (Slack = native bot-token MCP, Drive = local drive-api MCP), so no Slack/Drive auth config is created. Schemas verified against Composio's published v3 OpenAPI; flow unit-tested with mocks (create + already-exists + reuse branches). **Still required for Gmail to actually pull:** the customer must connect their Gmail account in Composio (account currently has **0 connected accounts**) — the provisioner wires the server but can't connect the account. Slack ingestion does NOT depend on any of this.
- **Access (passwordless, IP-allowlisted to operator's IP):** https://srv1687869.hstgr.cloud:8443/setup and `/dashboard`. If it 403s, operator IP rotated (mobile IPv6) — add the new `client:` IP from `/var/log/nginx/error.log` to `/etc/nginx/sites-available/safeclaw-admin` and reload nginx.
- **Code:** branch `feat/safeclaw-brain-gbrain`, PR #1 (github `Vasanth19/safeclaw`) — **not merged**. Many fixes landed this session (see Update Log).
- **Creds:** `suffolk.env` (gitignored, local). All set EXCEPT Telegram (the actor logs a non-fatal `telegram InvalidToken __FILL_IN__` — optional). Ollama Cloud key is the LLM.
- **🚨 PRIME DIRECTIVE:** the box also runs the client's **LIVE "Brookhaven Solds" app** (nginx 80/443, uvicorn `:8001`, postgres `:5432`). **Never disturb it.** Everything SafeClaw is additive + isolated (port 8443 + internal docker net). Verify Brookhaven `/health` (https://srv1687869.hstgr.cloud/health → `{"status":"ok"}`) after any change.

### To deploy the session-3 ingestion + Composio fixes (NO image rebuild)
All changed files (`scripts/safeclaw-cron-sync.py`, `scripts/hermes-docker-init.sh`, `docker-compose.yml`, `onboarding/lib/validator.py`) are bind-mounted or read at runtime, so a container recreate is enough:
```bash
ssh suffolk-vps
cd /opt/safeclaw && git pull            # branch feat/safeclaw-brain-gbrain (or git fetch && reset to the PR head)
docker compose up -d hermes-reader      # recreate reader → cron-sync runs in hermes-docker-init.sh
# verify the cron job registered + boot log shows the sync:
docker compose logs --since 2m hermes-reader | grep -i 'cron-sync\|cron jobs'
docker compose exec -T -u 10000 hermes-reader sh -lc 'cat /opt/data/cron/jobs.json' | python3 -m json.tool | grep -A2 '"name"'
docker compose exec -T -u 10000 hermes-reader /opt/hermes/.venv/bin/hermes cron list   # should show slack_ingest [active]
# then watch the brain page count climb after the next */30 tick:
docker exec safeclaw-brain gbrain stats
```
Brookhaven check after recreate: `curl -s https://srv1687869.hstgr.cloud/health` → `{"status":"ok"}`.
For the Composio fix to take effect, re-run the provision (next block) so the new v3 URLs land in `.env`; the customer must also connect Gmail in Composio first.

### To re-run the provision (from the box, the working path)
`docker compose exec -T onboarding python3 /safeclaw/fire_provision.py` (reads `.env`, POSTs `/api/provision`). Then `docker compose up -d` FROM THE HOST (not via onboarding — the provisioner runs inside onboarding and recreating it mid-`up` kills the run). NOTE: if you wipe & re-init the brain, do it BEFORE secrets are finalized or the postgres-brain password (set on first init) won't match the regenerated `BRAIN_DB_PASSWORD` — symptom: `password authentication failed for user "safeclaw_brain"`. Fix = remove `safeclaw_brain_data` + `safeclaw_brain_db` volumes and let it re-init with the current `.env` password.

---

## 1. What SafeClaw is now (architecture)

SafeClaw = **Hermes** (trust-split reader/actor agents) + a **brain**. The bespoke brain (postgres-obs + custom `brain-api` MCP + local embedder + Obsidian vault) was **replaced by the GBrain engine** (`github.com/garrytan/gbrain` v0.37.11.0), run as a constant-named **`safeclaw-brain`** service:
- `gbrain serve --http :3131` on the internal `safeclaw_net` (no host port)
- **Postgres backend** (`postgres-brain`) — required for static bearer tokens
- **Local Ollama embeddings** (`ollama:nomic-embed-text`, :11434, no egress, no key)
- Both agents reach the brain over **HTTP MCP** with static `Authorization: Bearer` tokens (minted post-boot via `gbrain auth create`)
- Soul = pinned GBrain page `identity/soul`
- Trust split still enforced at the **Composio MCP layer** (reader = read-only Gmail/Slack; actor = send/draft). The brain is internal; both agents have read+write.

Full architecture: `ARCHITECTURE.md`. Full deploy runbook: `SUFFOLK-DEPLOY-PLAN.md`.

## 2. Target box + coexistence

`ssh suffolk-vps` → `187.77.30.131` / `srv1687869.hstgr.cloud`. x86_64, Ubuntu, 2 vCPU / 7.8 GiB / **0 swap** / 92 GB free. Docker 29.5.1 present.

**Brookhaven (must not disturb):** FastAPI/uvicorn `127.0.0.1:8001` behind **nginx 80/443**, host **Postgres 16 :5432**, static frontend `/var/www/brookhaven`, app dir `/opt/brookhaven-solds`, served at `https://srv1687869.hstgr.cloud`. Its nginx vhost: `/etc/nginx/sites-available/brookhaven` — **we never edit this file.**

## 3. What's been done (✅) and what's pending (⛔)

✅ **GBrain swap (Phases 1-5)** — coded on branch `feat/safeclaw-brain-gbrain` (PR #1): safeclaw-brain image+entrypoint, compose (postgres-obs→postgres-brain, embedder removed), Hermes configs → GBrain HTTP MCP, bootstrap+reflector rewritten, review_queue moved to postgres-tasks, docs.
✅ **Local smoke test** — image builds, brain boots on Postgres, Ollama embeddings work, MCP put_page/get_page/search/query verified.
✅ **VPS pre-staged** (Brookhaven verified 200 after each step):
  - repo cloned → `/opt/safeclaw` (feature branch)
  - Ollama installed (:11434) + `nomic-embed-text` pulled
  - `safeclaw-brain` image **built on-box** (amd64)
  - standard images pulled (pgvector, postgres:16-alpine, postgrest)
  - `ghcr.io/vasanth19/safeclaw-hermes:1.2` made public + pulled (3.31 GB)
✅ **Onboarding UI running** (`safeclaw-onboarding`, 127.0.0.1:8080) + exposed via `:8443` (see §4).
✅ **Creds** collected into `suffolk.env`.
⛔ **Full stack not started** — run the wizard (§5) once creds are complete.
⛔ **Pending creds:** Composio user ID, LLM key (Anthropic recommended), Telegram bot token + user ID.

## 4. Access to the dashboard / wizard (temporary)

A **separate nginx listener on port 8443** (file `/etc/nginx/sites-available/safeclaw-admin`, reuses the Brookhaven cert) proxies to the onboarding container. **Does NOT touch Brookhaven's vhost.** Gated by **IP allow-list** (operator's network) — **no password**:

```
https://srv1687869.hstgr.cloud:8443/setup
https://srv1687869.hstgr.cloud:8443/dashboard
```

- Allow-list currently: `2600:1008:a034:985b::/64` (operator IPv6) + `97.242.154.1` (IPv4). Operator is on **mobile IPv6 that can rotate** — if the dashboard returns **403**, the IP changed: get the new client IP from `/var/log/nginx/error.log` (grep `client:`) and add `allow <ip>;` to the safeclaw-admin config, `nginx -t && systemctl reload nginx`.
- Hostinger cloud firewall already allows 8443 externally.
- **Why IP-allowlist not basic-auth:** the operator's browser didn't send basic-auth on `fetch()`, so wizard XHRs got 401'd → "network error". IP-allowlist removed that.
- **TEARDOWN after setup:** `ssh suffolk-vps 'rm /etc/nginx/sites-enabled/safeclaw-admin && nginx -t && systemctl reload nginx'`

## 5. Running the wizard (brings up the full stack)

The wizard is at `/setup`. Fill it with the `suffolk.env` creds. On Submit the provisioner auto-runs: write `.env` → `init-secrets.sh` → `up -d safeclaw-brain` (Postgres+brain) → wait health → **mint reader/actor brain tokens** (`gbrain auth create … --takes-holders world,garry,brain`) → full `docker compose up -d` → bootstrap (90-day Gmail → brain pages) → welcome.

**LLM decision:** use a **hosted key (Anthropic `sk-ant-…`)** — Hermes' config points at Ollama `:11435` but Ollama is installed on `:11434` (embeddings only). Hosted LLM sidesteps this. If you must use Ollama Cloud, fix the `:11435` wiring first.

## 6. Nuances & gotchas (READ before touching anything)

**GBrain v0.37.11.0:**
- `gbrain auth create <name>` **drops the name unless `--takes-holders` is passed** (arg-parse bug). Always pass `--takes-holders world,garry,brain`.
- Dockerfile must compile per **`TARGETARCH`** (amd64/arm64), not hardcoded x86, or the binary can't find its linker.
- `gbrain init` defaults to **PGLite**; use `--supabase --non-interactive --url "$DATABASE_URL"` for Postgres.
- Pin the **published** commit `d0d0e2a` (origin/master = v0.37.11.0); the local `fe3499e` is unpushed and Docker can't clone it.
- **`query`/`search` hard-exclude `test/`, `archive/`, `attachments/`, `.raw/` slug prefixes.** A `test/` smoke slug returns `[]` (false alarm). Use `scripts/smoke-brain.sh`. `get_page` always works.
- `delete_page` is a **soft delete** — reusing a slug after delete needs care.

**VPS / infra:**
- Hermes image (`ghcr.io/vasanth19/safeclaw-hermes:1.2`) must be **public on GHCR** (or `docker login`, or build from `docker/Dockerfile.safeclaw-hermes`).
- nginx `auth_basic` htpasswd must be **chmod 644** (or www-data can't read it → 500).
- Operator's mobile **IPv6 rotates** — see §4 for re-adding.

**Local dev:** OrbStack VM crashes with `StorageFull` when the **Mac host disk** is full.

## 7. Verification

```bash
# SafeClaw stack
ssh suffolk-vps 'cd /opt/safeclaw && docker compose ps'
ssh suffolk-vps 'docker exec safeclaw-brain gbrain stats'        # pages/chunks/embedded
bash scripts/smoke-brain.sh                                       # brain retrieval (non-excluded slug)

# Brookhaven NON-INTERFERENCE (must all stay green)
ssh suffolk-vps 'curl -s https://srv1687869.hstgr.cloud/health'   # {"status":"ok"}
ssh suffolk-vps 'curl -s http://127.0.0.1:8001/health'           # {"status":"ok"}
ssh suffolk-vps 'stat -c %y /etc/nginx/sites-available/brookhaven' # unchanged (pre-2026-05-22)
```

## 8. Key file locations

- VPS install dir: `/opt/safeclaw` (branch `feat/safeclaw-brain-gbrain`)
- Admin nginx vhost: `/etc/nginx/sites-available/safeclaw-admin` (port 8443)
- Creds (local, gitignored): `suffolk.env`
- Brain knowledge tracker (local): `.claude/knowledge/decisions/suffolk-deployment-tracker.md`
- brain-personal: `projects/safeclaw/suffolk-deployment`, `projects/safeclaw/gotchas/gbrain-deployment`

## 9. Update Log

- **2026-05-22 (session 1)** — GBrain swap built + smoke-tested + pushed (PR #1). VPS pre-staged (repo, Ollama+model, brain image amd64, std + hermes images). Onboarding UI started; dashboard exposed on :8443 (switched basic-auth → IPv6/IPv4 allow-list after basic-auth broke wizard XHRs). Creds saved to suffolk.env. Brookhaven verified untouched.
- **2026-05-24 (session 4) — got the LLM working + reader reads Slack; isolated the last 3 blockers.** Discovered the real LLM failure was NOT just the key: the compose `environment:` blocks (reader+actor) **override `config.yaml`** and had `OLLAMA_API_KEY: ollama-local` (12-char placeholder), `OLLAMA_BASE_URL: http://host.docker.internal:11435/v1` (dead local daemon → the `APIConnectionError`), and `HERMES_DEFAULT_MODEL: glm-5.1:cloud` (nonexistent). Fixed all three in compose: removed the hardcoded key so it flows from `env_file:.env`, set `OLLAMA_BASE_URL=https://ollama.com/v1`, switched model to **`kimi-k2.5`** (glm-4.6 hit a Hermes OpenAI-compat parse bug `'str' object has no attribute 'get'`). Wrote the real 57-char key (from `suffolk.env`) into the box `.env`. Commits: `a38a25d`→`bffe1f4`. Recreated **hermes-reader** → it now reaches the LLM and **successfully reads Slack** (49 human msgs from `callrail-new-daily-calls`). **Pages still 0 — 3 blockers, see Current Status:** (1) host Ollama binds `127.0.0.1` so the brain can't embed (Ollama Cloud has NO embeddings endpoint — confirmed 404 — so a local embedder is mandatory; fix = `OLLAMA_HOST=172.17.0.1:11434` systemd drop-in, operator-only, classifier blocks the agent); (2) **hermes-actor NOT yet recreated** — still on the old broken env, needs `docker compose up -d --force-recreate hermes-actor`; (3) Slack bot lacks **`files:read`** scope (verified via auth.test) so attachments can't download — add scope + reinstall + new token; bot is in only 1/71 channels. Brookhaven `{"status":"ok"}` verified throughout. Also: confirmed `glm-5.1` (no `:cloud`), `kimi-k2.5/k2.6`, `qwen3-coder:480b` etc. are the real Ollama Cloud model ids.
- **2026-05-22 (session 3) — wired automated ingestion + fixed Composio v3 provisioning (both no-rebuild).** (1) **Ingestion:** new `scripts/safeclaw-cron-sync.py` translates the config `schedules:` block → real Hermes cron jobs in `/opt/data/cron/jobs.json`; invoked from `scripts/hermes-docker-init.sh` as uid 10000 with `HERMES_HOME=/opt/data`; script bind-mounted into both hermes services (`/safeclaw/cron-sync.py`). Idempotent/declarative via `origin.source=safeclaw-config-sync` (create/update/prune only its own jobs). Verified locally vs the real `cron.jobs` API: creates `slack_ingest` (`*/30`), re-run = no-op, prune-on-removal works; generic over the actor's 4 schedules too. (2) **Composio:** `provision_composio_mcps` rewritten to v3 (get-or-create Gmail auth config → `POST /api/v3/mcp/servers` with `auth_config_ids`+`allowed_tools`+`managed_auth_via_composio` → `?user_id=` scoping); Gmail-only (Slack/Drive use their own MCPs). Schemas pulled from Composio's published v3 OpenAPI; mock-tested create + already-exists + reuse branches. Quality gates pass (`compose config`, `bash -n`, `py_compile`). **DEPLOYED to the box this session:** `git pull` (HEAD `4a1f232`) + `docker compose up -d hermes-reader` → cron-sync ran, registered `slack_ingest` (`*/30`, job id `187b27fb908d`); a forced `hermes cron run` confirmed the gateway ticks and starts the agent session. **But it can't ingest:** the LLM call 401s because `OLLAMA_API_KEY` is a 12-char placeholder (`oll…al`). Also fixed+deployed the model name (`glm-5.1:cloud`→`glm-4.6`, verified live). Brookhaven `{"status":"ok"}` verified after every recreate. **Remaining blocker is operator-only: supply a valid LLM key** (Ollama Cloud or Anthropic). Customer must also connect Gmail in Composio for the Gmail path. **⚠️ Noted, not changed:** the actor's `schedules:` (`morning_briefing`/`reminder_scan`/`critical_digest`) still reference the removed obs DB — the generic sync will register them once `ACTOR_ENABLED=true`, and they'll error until rewritten to source from the brain. Left for a product decision (actor is gated off for now).
- **2026-05-22 (session 2) — brought the full stack up + found the ingestion gap.** Fixes committed (branch `feat/safeclaw-brain-gbrain`): LLM endpoint → Ollama Cloud direct API `https://ollama.com/v1` (the `:11435` local-daemon routing fails headless); `validate_all` made LLM-only-required (Composio/Slack/Drive optional, Slack workspace/admin/home/ingest optional); `init-secrets.sh` JWT signer node→python3; compose pull `--ignore-buildable` + non-fatal; Composio MCP provisioning non-fatal + honors supplied URLs; **build-on-VPS** standardized (Dockerfile.safeclaw-hermes now clones `NousResearch/hermes-agent`@`6f1eed3` at build; compose `build:` enabled for both agents); reader observation-write fixed (was the removed obs DB → now `mcp_safeclaw_brain_put_page`). Ran provision via `fire_provision.py`; hit + fixed: postgres-brain password mismatch (wiped brain volumes), mint-too-early (revoke+refire), onboarding-self-recreate killing the provisioner (do final `up` from host), and the arm64 hermes image (`exec format error` → rebuilt amd64 on box). **Result: both Hermes agents running.** **Discovered: scheduled ingestion never fires — Hermes ignores the config `schedules:` key (see Current Status #1).** Brookhaven untouched throughout.

### Gotchas added this session (also in §6)
- **Hermes ignores `config.yaml: schedules:`** — its gateway only reads session_reset/quick_commands/stt/streaming/etc. Cron lives in the `/cron` job store (`$HERMES_HOME/cron/jobs.json`). SafeClaw's `schedules:` block is dead config to Hermes. **RESOLVED (session 3):** `scripts/safeclaw-cron-sync.py` (invoked from `hermes-docker-init.sh`) translates `schedules:` → real cron jobs at startup. Jobs MUST be written as uid 10000 with `HERMES_HOME=/opt/data` or the gateway (running as hermes) can't read/update `jobs.json`.
- **`hermes-*` GHCR image is arm64-only** → `exec format error` on amd64 VPS. Solved by build-on-VPS (clone-at-build). The Dockerfile needs the gitignored `vendor/hermes-agent` ONLY if you don't use the new clone-at-build path.
- **Composio API moved**: `/api/v3/mcp/create` (404) → `/api/v3/mcp/servers` (POST needs `auth_config_ids`, not `app_names`). **RESOLVED (session 3):** `provision_composio_mcps` now does get-or-create Gmail auth config → create MCP server with `auth_config_ids`+`allowed_tools` → scope `mcp_url` with `?user_id=`. Composio is Gmail-only (Slack/Drive go through their own MCPs). Auth configs need the customer's Gmail to be **connected in Composio** before tools actually return data — the provisioner can't do that connection step.
- **Brain DB password**: postgres-brain bakes its password on first init; regenerating `BRAIN_DB_PASSWORD` after that → auth failure. Wipe `safeclaw_brain_db`+`safeclaw_brain_data` to re-init cleanly.
