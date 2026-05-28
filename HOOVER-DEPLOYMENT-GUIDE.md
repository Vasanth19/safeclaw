# Hoover Deployment Guide — SafeClaw (GBrain-backed) — RUNNING DOC

> **Living document.** Update the **Current Status** block + **Update Log** every time the deploy moves. Secrets live in the box's `/opt/safeclaw/.env` (chmod 600, gitignored) — never put them here. Modeled on `SUFFOLK-DEPLOYMENT-GUIDE.md`; read `CLIENT-DEPLOYMENT-PLAYBOOK.md` for the distilled gotchas.

---

## ⭐ CURRENT STATUS — START HERE (new agent: read this first)

**As of 2026-05-27 (session 1) — STACK FULLY UP & HEALTHY. Only Telegram creds remain.** Fresh/empty VPS (no client app to protect — unlike Suffolk). Tracking `main`. All custom images built **on-box** (amd64) — never pulled GHCR. All 6 services up & healthy; tokens minted; embeddings verified; brain MCP reachable + actor-token-authenticated; task DB migrated (13 RLS policies). LLM = **Ollama Cloud (paid key)**, validated 200 across kimi-k2.5 / qwen3-coder:480b / glm-4.6. Integration scope = **Telegram only**. Three `main` repo bugs found & fixed on-box (see below) — **should be committed to `main`** as they hit every fresh deploy.

**Final state (`docker compose ps`):** `safeclaw-brain` (healthy), `safeclaw-postgres-brain` (healthy), `safeclaw-postgres-tasks` (healthy), `safeclaw-postgrest` (up), `hermes-reader` (up, idle — no source connected), `hermes-actor` (up, gateway running, **awaiting Telegram token**). `gbrain stats` = 0 pages (expected: no ingest source connected yet).

**ONLY remaining step:** operator supplies the **Telegram bot token + allowed numeric user IDs** → set `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_USERS` in `/opt/safeclaw/.env` → `docker compose up -d --force-recreate hermes-actor`. Then DM the bot from an allowed user to confirm.

### 🟢 RESOLVED — `main` hermes image crash-loop (s6 mismatch) → entrypoint patched
**Root cause:** `main`'s `docker/Dockerfile.safeclaw-hermes` pins `HERMES_REF=6f1eed3`, which ships an **s6-overlay** runtime (`docker/stage2-hook.sh` calls `s6-setuidgid`; `docker/entrypoint.sh` is a deprecated shim that does NOT exec the CMD). But the Dockerfile builds a plain `debian:13.4` + `gosu`/`tini` image with **no s6 installed**, and `safeclaw-entrypoint.sh` Step 5 exec'd the dead shim → `s6-setuidgid: not found` → exit 127 → crash loop. Verified against Suffolk (runs an older pre-s6 image, so it escaped it).
**Fix (operator chose "bypass the s6 shim"):** rewrote `safeclaw-entrypoint.sh` Step 5 to replicate the essential bootstrap (seed `$HERMES_HOME` dirs + `skills_sync.py`, all as the hermes user via `gosu`) and **exec the gateway directly**. Handles both CMD forms via a `case`:
  - reader CMD = `gateway run --accept-hooks` → prepend the hermes binary (`hermes gateway run …`)
  - actor CMD = `sh -c "exec /opt/hermes/.venv/bin/hermes gateway run …"` → run as-is (`sh`/`bash`/`/*` matched).
  Two earlier iterations failed (first prepended `hermes` to the actor's `sh -c`; second used `[ -x "$1" ]` which is true for the `gateway` *directory*) — the `case` version is correct. `safeclaw-entrypoint.sh` is **baked into the image** (Dockerfile COPY), so each change needs a rebuild (cache-fast). **Mirror this fix into the repo `docker/safeclaw-entrypoint.sh` and commit to `main`.**

### 🟢 RESOLVED — two `db/002_task_schema.sql` bugs (worked around on-box)
1. **`CREATE POLICY IF NOT EXISTS` is invalid Postgres** → all 13 RLS policies silently failed (RLS enabled, zero policies = `tasks_agent` default-denied). Fixed to `DROP POLICY IF EXISTS … ; CREATE POLICY …` (idempotent). **Commit to `main`.**
2. **`sed -i` on a single-file bind mount swaps the inode** → the container keeps the old file; must `--force-recreate` the container (or edit preserving inode) for the mount to pick up changes. (Deploy-process gotcha, not a repo bug.)

### Deploy decisions (this client)
- **Build everything on the end box** (operator directive). Compose has both `build:` and `image:` for custom services; we run `docker compose build` on-box and never `docker compose pull` the `safeclaw-brain` / `safeclaw-hermes` images. Standard multi-arch images (pgvector, postgres:16-alpine, postgrest, rclone) are pulled normally.
- **Manual `.env` + manual bring-up** (DEPLOY-RUNBOOK §2–5), NOT the onboarding wizard — more deterministic on a fresh box, avoids Suffolk's nginx-admin/IP-allowlist dance.
- **Standard ports** — no coexistence constraint (empty box), so no need to isolate onto 8443 like Suffolk.

---

## 1. Target box + coexistence

`ssh hoover-vps` → `root@187.77.192.96` (hostname `srv1688747`). **Key-based auth** set up (`~/.ssh/hoover-vps`, alias in `~/.ssh/config`); password no longer needed.

- **Ubuntu 24.04.4 LTS, x86_64.** 2 vCPU / **7.8 GiB / 0 swap** / 94 GB free. Docker 29.5.2 + Compose v5.1.4.
- **No existing client app.** Recon (2026-05-26): no running containers, nothing listening but `:22` (ssh) + `:53` (resolved); no nginx, no postgres, no ollama pre-installed; `/opt` empty; load 0.00. **So there is NO prime-directive app to protect on this box** (confirmed with operator). SafeClaw can use standard ports.
- Same 2vCPU/7.8GiB/0-swap shape as Suffolk → **do not run an on-box LLM** (would risk OOM); LLM is Ollama Cloud, only embeddings run locally.

## 2. Architecture (same as Suffolk)

SafeClaw = **Hermes** trust-split reader/actor + **GBrain** (`safeclaw-brain`, Postgres backend, local Ollama `nomic-embed-text` embeddings, internal `safeclaw_net`, no host port). Agents reach the brain over HTTP MCP with static bearer tokens (minted post-boot). Full detail: `ARCHITECTURE.md`.

## 3. What's done (✅) / pending (⛔)

✅ **Access** — `hoover-vps` SSH key + alias; password-free.
✅ **Recon** — empty box confirmed; no coexistence constraint.
✅ **Clone** — `git clone -b main … /opt/safeclaw` (HEAD `5b135c9`).
✅ **Host Ollama embeddings** — installed; bound to **`172.17.0.1:11434`** (docker bridge, NOT `0.0.0.0` — no host firewall) via systemd drop-in; `nomic-embed-text` pulled. Verified listening.
✅ **LLM key validated** — Ollama Cloud paid key returns 200 on kimi-k2.5 / qwen3-coder:480b / glm-4.6 (no 429 wall).
✅ **`.env`** — created from `.env.example`; `init-secrets.sh` filled DB/JWT secrets; Ollama Cloud key + `OLLAMA_BASE_URL=https://ollama.com/v1` + `HERMES_DEFAULT_MODEL=qwen3-coder:480b`; `GBRAIN_VERSION=0.37.11.0`. Composio/Slack/Firecrawl left `__FILL_IN__` (unused). chmod 600.
✅ **Configs neutralized for Telegram-only:**
  - `reader-hermes.yaml` — disabled `slack_native` MCP + `slack_ingest` schedule. Reader keeps only the brain MCP → boots healthy + idle. `model.default=qwen3-coder:480b`.
  - `actor-hermes.yaml` — disabled `gmail_suffolk` + `composio_mgmt` (URL-placeholder run-aborters), `slack_native`, `drive_api`. Kept `safeclaw_brain` + `tasks_api`. Emptied all schedules (were Slack/obs-DB targeted). `model.default=kimi-k2.5`.
  - Both validated with `yaml.safe_load`.
✅ **On-box image build** — `docker compose build safeclaw-brain hermes-reader` (in progress / done — see Update Log).
⛔ **Bring-up** — pending build completion + Telegram creds.
⛔ **Telegram creds** — operator to supply bot token + allowed user IDs.

## 4. Effective model precedence (gotcha #6)
Config template's `model.default` wins, NOT compose env. Compose hardcodes `HERMES_DEFAULT_MODEL: kimi-k2.5` (lines 222/301) and `.env` has `qwen3-coder:480b` — effective: **reader=qwen3-coder:480b, actor=kimi-k2.5**. Both have quota.

## 5. Bring-up steps (once creds in)
```bash
ssh hoover-vps 'cd /opt/safeclaw && docker compose up -d postgres-brain safeclaw-brain'
# wait healthy, then mint tokens:
ssh hoover-vps 'cd /opt/safeclaw && docker compose exec -T safeclaw-brain gbrain auth create reader --takes-holders world,garry,brain'
ssh hoover-vps 'cd /opt/safeclaw && docker compose exec -T safeclaw-brain gbrain auth create actor  --takes-holders world,garry,brain'
# paste both gbrain_<hex> into .env (SAFECLAW_BRAIN_READER_TOKEN / _ACTOR_TOKEN), then:
ssh hoover-vps 'cd /opt/safeclaw && docker compose up -d'
# wait ~30s for the hermes gateway to boot BEFORE any cron trigger (gotcha #4)
```

## 6. Verification
```bash
ssh hoover-vps 'cd /opt/safeclaw && docker compose ps'
ssh hoover-vps 'docker exec safeclaw-brain gbrain stats'
ssh hoover-vps 'docker exec safeclaw-brain curl -s http://host.docker.internal:11434/api/tags'  # nomic-embed-text reachable from brain
# DM the Telegram bot from an allowed user → expect a reply
```

## 7. Key file locations
- VPS install dir: `/opt/safeclaw` (branch `main`)
- Box secrets: `/opt/safeclaw/.env` (chmod 600, gitignored)
- SSH: alias `hoover-vps`, key `~/.ssh/hoover-vps`
- This guide: repo root `HOOVER-DEPLOYMENT-GUIDE.md`

## 8. Update Log
- **2026-05-26/27 (session 1)** — Set up key auth + `hoover-vps` alias (initial password rejected; operator supplied working one; key installed). Recon: empty Ubuntu 24.04 box, no client app, 2vCPU/7.8GiB/0-swap. Cloned `main`. Installed host Ollama, bound `172.17.0.1:11434`, pulled `nomic-embed-text`. Validated Ollama Cloud paid key (200 on 3 models). Wrote `.env` (secrets generated, LLM wired, GBRAIN_VERSION 0.37.11.0). Neutralized both Hermes configs for Telegram-only (disabled Slack/Gmail/Composio/Drive MCPs + all Slack/obs-DB schedules; kept brain + tasks_api). Built custom images on-box (no GHCR pull). Brought up brain+Postgres+PostgREST; minted reader/actor tokens; verified embeddings reachable from brain. **Fixed `db/002_task_schema.sql` RLS bug** (`CREATE POLICY IF NOT EXISTS` invalid → DROP+CREATE), re-ran migration → 13 policies. **Diagnosed + fixed the `main` hermes s6-overlay crash-loop** by rewriting `safeclaw-entrypoint.sh` Step 5 to bypass the dead s6 shim and exec the gateway directly via `gosu` (handles reader's `gateway run` and actor's `sh -c` forms via a `case`). Rebuilt on-box, recreated both agents → **both stable**. Verified brain MCP reachable + actor-token-authenticated. **Stack fully up & healthy; brain empty (0 pages, no source).** **Pending:** Telegram creds → recreate actor. **TODO commit to `main`:** entrypoint s6 fix + RLS-policy syntax fix.
</content>
</invoke>
