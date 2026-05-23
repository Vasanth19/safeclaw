# Suffolk Deployment Guide — SafeClaw (GBrain-backed) — RUNNING DOC

> **This is a living document.** Update the **Current Status** block and the **Update Log** every time the deploy moves or a new nuance is found. Secrets live in `suffolk.env` (gitignored) — never put them here.

---

## ⭐ CURRENT STATUS — START HERE (new agent: read this first)

**As of 2026-05-22 (end of session 2). The full stack is DEPLOYED and RUNNING.**

- **What's up on the box (`/opt/safeclaw`, branch `feat/safeclaw-brain-gbrain`):** `safeclaw-brain` (GBrain, Postgres engine, Ollama embeddings) + `postgres-brain` + `postgres-tasks` + `postgrest` + `reflector` + `rclone` + `onboarding` + **both `hermes-reader` and `hermes-actor`** — all Up. Brain tokens minted, agents on a natively-built amd64 image.
- **🔴 THE ONE OPEN GAP — automated ingestion does not run.** Root cause: SafeClaw's reader config uses a `schedules:` key (e.g. `slack_ingest`, cron `*/30`), but **this Hermes version's gateway/config.py does NOT read a `schedules:` key** — it's silently ignored, so no ingestion cron is ever registered. The reader has the right tools (`slack_native` + `safeclaw_brain`) and instructions, but nothing triggers the task. **FIX:** register the ingest task in Hermes' REAL cron system (the `/cron` job store, persisted under `~/.hermes/cron/…`), e.g. have `safeclaw-entrypoint` translate config `schedules:` → Hermes cron jobs at startup. Needs a short dig into Hermes' cron-job format. Until then, **brain stays at 0 pages**.
- **🟡 Gmail ingestion also blocked (separate):** the customer's Composio account has **0 connected accounts** (Gmail not connected) AND Composio changed its MCP-create API (`/api/v3/mcp/create` is gone → use `/api/v3/mcp/servers`, which now needs `auth_config_ids`). Slack uses the bot token (NOT Composio), so Slack is unaffected by this — only Gmail needs Composio connected + the provisioner's Composio code updated to the new API.
- **Access (passwordless, IP-allowlisted to operator's IP):** https://srv1687869.hstgr.cloud:8443/setup and `/dashboard`. If it 403s, operator IP rotated (mobile IPv6) — add the new `client:` IP from `/var/log/nginx/error.log` to `/etc/nginx/sites-available/safeclaw-admin` and reload nginx.
- **Code:** branch `feat/safeclaw-brain-gbrain`, PR #1 (github `Vasanth19/safeclaw`) — **not merged**. Many fixes landed this session (see Update Log).
- **Creds:** `suffolk.env` (gitignored, local). All set EXCEPT Telegram (the actor logs a non-fatal `telegram InvalidToken __FILL_IN__` — optional). Ollama Cloud key is the LLM.
- **🚨 PRIME DIRECTIVE:** the box also runs the client's **LIVE "Brookhaven Solds" app** (nginx 80/443, uvicorn `:8001`, postgres `:5432`). **Never disturb it.** Everything SafeClaw is additive + isolated (port 8443 + internal docker net). Verify Brookhaven `/health` (https://srv1687869.hstgr.cloud/health → `{"status":"ok"}`) after any change.

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
- **2026-05-22 (session 2) — brought the full stack up + found the ingestion gap.** Fixes committed (branch `feat/safeclaw-brain-gbrain`): LLM endpoint → Ollama Cloud direct API `https://ollama.com/v1` (the `:11435` local-daemon routing fails headless); `validate_all` made LLM-only-required (Composio/Slack/Drive optional, Slack workspace/admin/home/ingest optional); `init-secrets.sh` JWT signer node→python3; compose pull `--ignore-buildable` + non-fatal; Composio MCP provisioning non-fatal + honors supplied URLs; **build-on-VPS** standardized (Dockerfile.safeclaw-hermes now clones `NousResearch/hermes-agent`@`6f1eed3` at build; compose `build:` enabled for both agents); reader observation-write fixed (was the removed obs DB → now `mcp_safeclaw_brain_put_page`). Ran provision via `fire_provision.py`; hit + fixed: postgres-brain password mismatch (wiped brain volumes), mint-too-early (revoke+refire), onboarding-self-recreate killing the provisioner (do final `up` from host), and the arm64 hermes image (`exec format error` → rebuilt amd64 on box). **Result: both Hermes agents running.** **Discovered: scheduled ingestion never fires — Hermes ignores the config `schedules:` key (see Current Status #1).** Brookhaven untouched throughout.

### Gotchas added this session (also in §6)
- **Hermes ignores `config.yaml: schedules:`** — its gateway only reads session_reset/quick_commands/stt/streaming/etc. Cron lives in the `/cron` job store. SafeClaw's `schedules:` block is dead config. → ingestion never triggers.
- **`hermes-*` GHCR image is arm64-only** → `exec format error` on amd64 VPS. Solved by build-on-VPS (clone-at-build). The Dockerfile needs the gitignored `vendor/hermes-agent` ONLY if you don't use the new clone-at-build path.
- **Composio API moved**: `/api/v3/mcp/create` (404) → `/api/v3/mcp/servers` (POST needs `auth_config_ids`, which require connected accounts). `provision_composio_mcps` in `onboarding/lib/validator.py` still uses the old API → update it when wiring Gmail.
- **Brain DB password**: postgres-brain bakes its password on first init; regenerating `BRAIN_DB_PASSWORD` after that → auth failure. Wipe `safeclaw_brain_db`+`safeclaw_brain_data` to re-init cleanly.
