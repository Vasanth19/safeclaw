# Suffolk Deployment Guide — SafeClaw (GBrain-backed) — RUNNING DOC

> **This is a living document.** Update the **Current Status** block and the **Update Log** every time the deploy moves or a new nuance is found. Secrets live in `suffolk.env` (gitignored) — never put them here.

---

## ⭐ CURRENT STATUS — START HERE (new agent: read this first)

**As of 2026-05-22.**

- **Where we are:** VPS is **pre-staged** and the **onboarding UI is live**; the **full agent stack is NOT started yet** (waiting on credentials to run the `/setup` wizard).
- **Next action:** collect the 3 remaining creds (**Composio user ID, an LLM key, Telegram bot token+user ID**) → open the wizard → it boots the full stack.
- **Access (passwordless, IP-allowlisted to operator):** https://srv1687869.hstgr.cloud:8443/setup and `/dashboard`
- **Code:** branch `feat/safeclaw-brain-gbrain`, PR #1 (github `Vasanth19/safeclaw`) — **not merged**. The VPS clone at `/opt/safeclaw` is on this branch.
- **Creds collected:** `suffolk.env` (gitignored, local). Composio API key, Slack bot+app tokens, workspace ID saved. **Pending:** Composio user ID, LLM key, Telegram.
- **🚨 PRIME DIRECTIVE:** the box also runs the client's **LIVE "Brookhaven Solds" app** (nginx 80/443, uvicorn `:8001`, postgres `:5432`). **Never disturb it.** Everything SafeClaw is additive + isolated (port 8443 + internal docker net). Verify Brookhaven `/health` after any change.

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

- **2026-05-22** — GBrain swap built + smoke-tested + pushed (PR #1). VPS pre-staged (repo, Ollama+model, brain image amd64, std + hermes images). Onboarding UI started; dashboard exposed on :8443 (switched basic-auth → IPv6/IPv4 allow-list after basic-auth broke wizard XHRs). Creds (Composio key, Slack bot+app tokens, workspace TLL1P1QU9) saved to suffolk.env. Brookhaven verified untouched throughout. **Pending:** Composio user ID, LLM key, Telegram → then run wizard.
