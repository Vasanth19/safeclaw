# Suffolk Deployment Guide — SafeClaw (GBrain-backed) — RUNNING DOC

> **This is a living document.** Update the **Current Status** block and the **Update Log** every time the deploy moves or a new nuance is found. Secrets live in `suffolk.env` (gitignored) — never put them here.

---

## ⭐ CURRENT STATUS — START HERE (new agent: read this first)

**As of 2026-05-22 (end of session 3). The full stack is DEPLOYED and RUNNING. Ingestion + Composio fixes are CODED on the branch — pending a no-rebuild container recreate on the box.**

- **What's up on the box (`/opt/safeclaw`, branch `feat/safeclaw-brain-gbrain`):** `safeclaw-brain` (GBrain, Postgres engine, Ollama embeddings) + `postgres-brain` + `postgres-tasks` + `postgrest` + `reflector` + `rclone` + `onboarding` + **both `hermes-reader` and `hermes-actor`** — all Up. Brain tokens minted, agents on a natively-built amd64 image.
- **🟢 INGESTION WIRED (session 3) — pending deploy.** Root cause was confirmed: this Hermes version's gateway config loader ignores the `schedules:` key, so the `slack_ingest` cron never registered. **Fix shipped on the branch:** a new translator `scripts/safeclaw-cron-sync.py` reads the config's `schedules:` block and registers each entry in Hermes' REAL cron store (`$HERMES_HOME/cron/jobs.json` = `/opt/data/cron/jobs.json`, which `gateway run` ticks every 60s). It's invoked from `scripts/hermes-docker-init.sh` as the `hermes` user (uid 10000, so jobs.json ownership is right) with `HERMES_HOME=/opt/data` pinned, reading the mounted template `/safeclaw/config-template/config.yaml`. Idempotent + declarative: jobs are tagged `origin.source=safeclaw-config-sync`, so re-runs create/update/prune only sync-managed jobs and never touch agent/operator-created ones. **All files are bind-mounted → NO image rebuild needed; just `docker compose up -d` (recreate) on the box** (see deploy steps below). Verified locally against the real `cron.jobs` API (create/idempotent-noop/prune all pass).
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
- **2026-05-22 (session 3) — wired automated ingestion + fixed Composio v3 provisioning (both no-rebuild).** (1) **Ingestion:** new `scripts/safeclaw-cron-sync.py` translates the config `schedules:` block → real Hermes cron jobs in `/opt/data/cron/jobs.json`; invoked from `scripts/hermes-docker-init.sh` as uid 10000 with `HERMES_HOME=/opt/data`; script bind-mounted into both hermes services (`/safeclaw/cron-sync.py`). Idempotent/declarative via `origin.source=safeclaw-config-sync` (create/update/prune only its own jobs). Verified locally vs the real `cron.jobs` API: creates `slack_ingest` (`*/30`), re-run = no-op, prune-on-removal works; generic over the actor's 4 schedules too. (2) **Composio:** `provision_composio_mcps` rewritten to v3 (get-or-create Gmail auth config → `POST /api/v3/mcp/servers` with `auth_config_ids`+`allowed_tools`+`managed_auth_via_composio` → `?user_id=` scoping); Gmail-only (Slack/Drive use their own MCPs). Schemas pulled from Composio's published v3 OpenAPI; mock-tested create + already-exists + reuse branches. Quality gates pass (`compose config`, `bash -n`, `py_compile`). **⚠️ Still TODO on the box:** `git pull` + `docker compose up -d hermes-reader` to activate; customer must connect Gmail in Composio for Gmail to pull. **⚠️ Noted, not changed:** the actor's `schedules:` (`morning_briefing`/`reminder_scan`/`critical_digest`) still reference the removed obs DB — the generic sync will register them once `ACTOR_ENABLED=true`, and they'll error until rewritten to source from the brain. Left for a product decision (actor is gated off for now).
- **2026-05-22 (session 2) — brought the full stack up + found the ingestion gap.** Fixes committed (branch `feat/safeclaw-brain-gbrain`): LLM endpoint → Ollama Cloud direct API `https://ollama.com/v1` (the `:11435` local-daemon routing fails headless); `validate_all` made LLM-only-required (Composio/Slack/Drive optional, Slack workspace/admin/home/ingest optional); `init-secrets.sh` JWT signer node→python3; compose pull `--ignore-buildable` + non-fatal; Composio MCP provisioning non-fatal + honors supplied URLs; **build-on-VPS** standardized (Dockerfile.safeclaw-hermes now clones `NousResearch/hermes-agent`@`6f1eed3` at build; compose `build:` enabled for both agents); reader observation-write fixed (was the removed obs DB → now `mcp_safeclaw_brain_put_page`). Ran provision via `fire_provision.py`; hit + fixed: postgres-brain password mismatch (wiped brain volumes), mint-too-early (revoke+refire), onboarding-self-recreate killing the provisioner (do final `up` from host), and the arm64 hermes image (`exec format error` → rebuilt amd64 on box). **Result: both Hermes agents running.** **Discovered: scheduled ingestion never fires — Hermes ignores the config `schedules:` key (see Current Status #1).** Brookhaven untouched throughout.

### Gotchas added this session (also in §6)
- **Hermes ignores `config.yaml: schedules:`** — its gateway only reads session_reset/quick_commands/stt/streaming/etc. Cron lives in the `/cron` job store (`$HERMES_HOME/cron/jobs.json`). SafeClaw's `schedules:` block is dead config to Hermes. **RESOLVED (session 3):** `scripts/safeclaw-cron-sync.py` (invoked from `hermes-docker-init.sh`) translates `schedules:` → real cron jobs at startup. Jobs MUST be written as uid 10000 with `HERMES_HOME=/opt/data` or the gateway (running as hermes) can't read/update `jobs.json`.
- **`hermes-*` GHCR image is arm64-only** → `exec format error` on amd64 VPS. Solved by build-on-VPS (clone-at-build). The Dockerfile needs the gitignored `vendor/hermes-agent` ONLY if you don't use the new clone-at-build path.
- **Composio API moved**: `/api/v3/mcp/create` (404) → `/api/v3/mcp/servers` (POST needs `auth_config_ids`, not `app_names`). **RESOLVED (session 3):** `provision_composio_mcps` now does get-or-create Gmail auth config → create MCP server with `auth_config_ids`+`allowed_tools` → scope `mcp_url` with `?user_id=`. Composio is Gmail-only (Slack/Drive go through their own MCPs). Auth configs need the customer's Gmail to be **connected in Composio** before tools actually return data — the provisioner can't do that connection step.
- **Brain DB password**: postgres-brain bakes its password on first init; regenerating `BRAIN_DB_PASSWORD` after that → auth failure. Wipe `safeclaw_brain_db`+`safeclaw_brain_data` to re-init cleanly.
