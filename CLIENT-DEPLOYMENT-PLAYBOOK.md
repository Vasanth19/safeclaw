# SafeClaw — Client Deployment Playbook (Gotchas & Pre-Flight)

> **Purpose:** the hard-won lessons from the **first** client deployment (Suffolk, 2026-05) so future client VPS deployments don't re-discover them. Read this BEFORE deploying SafeClaw to a new client box. The blow-by-blow narrative lives in `SUFFOLK-DEPLOYMENT-GUIDE.md`; this file is the distilled, reusable doctrine.

---

## TL;DR — the five things that cost the most time

1. **Host Ollama must bind the docker bridge, not localhost** — or the brain can't embed and pages stay at 0.
2. **Never enable an MCP whose creds aren't set** — one placeholder URL (`__FILL_IN__`) aborts the *entire* agentic run before any work happens.
3. **Ollama Cloud's weekly cap is PER-MODEL**, and the free tier is too small for agentic ingest — *testing itself* burns it. Budget for a paid LLM (hosted Anthropic key) or expect to dodge between models.
4. **After recreating a Hermes container, wait ~30s before triggering cron** — fire too early (before the gateway boots) and the trigger is a silent no-op.
5. **On a shared box, verify the client's existing live app `/health` after every change.** SafeClaw must be additive + isolated (own port + internal docker net).

---

## Get the code — track `main` (NOT the Suffolk branch)

New client boxes always clone the **`main`** branch — the stable, merged line (GBrain swap merged via PR #1, 2026-05-26):

```bash
git clone -b main https://github.com/Vasanth19/safeclaw.git /opt/safeclaw
# idempotent re-sync on the box later:
git -C /opt/safeclaw fetch && git -C /opt/safeclaw reset --hard origin/main
```

> ⚠️ **Do NOT clone `feat/safeclaw-brain-gbrain` for a new client.** That branch is the **Suffolk-only** in-flight line (LLM/model fixes still landing). It is kept open on purpose; only the Suffolk box at `/opt/safeclaw` tracks it. Everyone else tracks `main`.

---

## Pre-flight checklist (do these before/early in any client deploy)

- [ ] **Clone `main`** (see above) — never the Suffolk feature branch.
- [ ] **Confirm coexistence:** what else runs on the box? Record its ports, app dir, nginx vhost, and `/health` URL. Never edit the client's vhost. Pick a non-conflicting port (Suffolk used 8443) on an internal docker net.
- [ ] **Embeddings reachability:** GBrain embeds via host Ollama (`nomic-embed-text`). The brain reaches the host at `host.docker.internal` → `172.17.0.1`. Host Ollama defaults to binding `127.0.0.1` → **connection refused**. Fix with a systemd drop-in (see below). Bind to the **bridge IP `172.17.0.1`**, NOT `0.0.0.0` (an unfirewalled box would expose the unauthenticated Ollama API publicly).
- [ ] **LLM provider decided up front.** Ollama Cloud free tier is NOT sufficient for production ingest (per-model weekly caps, exhausted by normal use + testing). Prefer a **hosted Anthropic key** (`sk-ant-…`, native Hermes support, no quota wall, best tool-calling). If using Ollama Cloud, confirm the key's account is funded AND on a plan tier whose weekly limit clears the workload.
- [ ] **Disable every MCP the client hasn't connected yet** (Gmail/Composio especially). Only enable an MCP whose URL/creds are real.
- [ ] **Slack app lives in the CLIENT's workspace.** The operator's own api.slack.com login won't show it. Plan for the client (or operator-as-member) to add scopes there.
- [ ] **Set a conservative cron cadence** (e.g. every 6h, not the shipped `*/30`) to conserve LLM quota.

---

## Gotchas, with fixes

### 1. Host Ollama bind (embeddings) — `0 pages` symptom
Host Ollama binds `127.0.0.1` by default; the brain container can't reach it. Fix (operator/root):
```bash
mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=172.17.0.1:11434"\n' > /etc/systemd/system/ollama.service.d/override.conf
systemctl daemon-reload && systemctl restart ollama
ss -tlnp | grep 11434   # expect 172.17.0.1:11434
```
Verify from inside the brain: `docker exec <brain> curl -s http://172.17.0.1:11434/api/tags` returns `nomic-embed-text`.

### 2. Broken/unconfigured MCP aborts the whole run
A Composio MCP with an unset URL resolves to e.g. `__FILL_IN__&connected_account_id=` → *"Request URL is missing an 'http://' or 'https://' protocol"* → the failing init kills the agentic run before any LLM/tool work → **0 pages, no obvious error**. **Comment out any MCP whose creds aren't set.** Re-enable only once the client connects that service. Slack ingestion does not need Gmail.

### 3. Ollama Cloud weekly cap is PER-MODEL
A `429 "weekly usage limit"` on one model does **not** mean the account is dead — other models may still have quota (Suffolk: `qwen3-coder:480b` 429'd while `kimi-k2.5` returned 200). Probe per model:
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://ollama.com/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"<model>","messages":[{"role":"user","content":"hi"}],"max_tokens":3}'
```
Set `model.default` to whichever has quota. **But the real lesson: the free tier can't sustain agentic ingest, and every test run burns it — move to a hosted Anthropic key for any real client.** Adding *credits* does not lift a *plan-tier weekly cap*; that needs a plan **upgrade**.

### 4. Model behavior on the OpenAI-compat path
- `glm-4.6` tripped a Hermes tool-call parse bug (`'str' object has no attribute 'get'`).
- `kimi-k2.5` works but is a **reasoning** model — on heavy prompts it can exceed the connection read window (ReadTimeout) and occasionally hallucinates tool names. It completes the Suffolk ingest, but watch it.
- Per-call request timeout default is already **1800s**; raising it is rarely the fix. Model choice + quota are the real levers. Hosted Anthropic sidesteps all of this.

### 5. Cron trigger timing
After `docker compose up -d --force-recreate hermes-reader`, the gateway takes ~30s to boot. A `hermes cron run <id>` issued before then is a **silent no-op**. Wait for the gateway banner / `No messaging platforms enabled`, then trigger.

### 6. Config model override precedence (footgun)
Effective model = the config template's `model.default`. Stale `HERMES_DEFAULT_MODEL` in `docker-compose.yml` and `HERMES_*` in `.env` can mislead `docker inspect` but don't win. Keep them aligned to avoid confusion.

### 7. GBrain-on-Postgres specifics
- `gbrain auth create <name>` drops the name unless `--takes-holders world,garry,brain` is passed.
- `gbrain init` defaults to PGLite — use `--supabase --non-interactive --url "$DATABASE_URL"` for Postgres.
- Dockerfile must compile per `TARGETARCH` (amd64/arm64), not hardcoded x86.

### 8. Slack bot
- Add **`files:read`** scope *before* handoff if attachments matter (reinstall after). The bot also joins only **1 channel by default** — `/invite` it into every channel to ingest.
- The app is in the **client's** Slack workspace; the operator must be signed into that workspace to edit it.

### 9. Hermes image s6-overlay mismatch — crash loop (exit 127) on fresh on-box build (Hoover, 2026-05)
The pinned `HERMES_REF` (currently `6f1eed3`) ships an **s6-overlay** runtime: `docker/stage2-hook.sh` calls `s6-setuidgid`, and `docker/entrypoint.sh` is a deprecated shim that does NOT exec the CMD. But `docker/Dockerfile.safeclaw-hermes` builds a plain `debian:13.4` + `gosu`/`tini` image with **no s6 installed**. A fresh on-box build crash-loops both agents with `s6-setuidgid: not found` (exit 127). Suffolk only escapes it because it's running a months-old image built before the upstream switched to s6.
**Fix (in `docker/safeclaw-entrypoint.sh` Step 5):** bypass the dead shim and exec the gateway directly via `gosu`. Replicate the bootstrap (seed `$HERMES_HOME` dirs + `skills_sync.py` as the hermes user). Handle both CMD forms with a `case`:
```sh
case "${1:-}" in
    sh|bash|/*) exec "$GOSU" hermes "$@" ;;          # actor: ["sh","-c","exec hermes …"] runs as-is
    *)          exec "$GOSU" hermes "$HERMES_BIN" "$@" ;;  # reader: ["gateway","run",…] prepends hermes
esac
```
The `case` is load-bearing: an earlier version using `[ -x "$1" ]` matched the `gateway` *directory* (dirs are `-x`-true) and routed the reader to the wrong branch. `safeclaw-entrypoint.sh` is **baked into the image** (Dockerfile COPY), so each change needs a rebuild — Docker cache makes it fast (only the COPY layer at line ~110 invalidates).

### 10. `db/002_task_schema.sql` — invalid `CREATE POLICY IF NOT EXISTS` silently denies tasks_agent
Postgres has never supported `IF NOT EXISTS` for `CREATE POLICY`. The migration enables RLS on all four task tables, then all 13 `CREATE POLICY IF NOT EXISTS …` statements fail with syntax errors — leaving RLS *enabled* with **zero policies**, which default-denies the `tasks_agent` role (PostgREST → actor) on every table. Easy to miss because `psql` continues past the errors and the table count looks right.
**Fix:** idempotent `DROP POLICY IF EXISTS … ; CREATE POLICY …`:
```sh
sed -E -i 's/CREATE POLICY IF NOT EXISTS ([a-zA-Z_]+) ON ([a-zA-Z_]+)/DROP POLICY IF EXISTS \1 ON \2;\nCREATE POLICY \1 ON \2/' db/002_task_schema.sql
```
Then re-run; verify `SELECT count(*) FROM pg_policies WHERE schemaname='public'` = 13.

### 11. `sed -i` on a single-file bind mount → container keeps the OLD file
`sed -i` writes a temp file and renames it over the target, creating a **new inode**. Single-file Docker bind mounts (e.g. `./db/002_task_schema.sql:/migrations/002_task_schema.sql:ro`) pin the old inode at mount time, so the container keeps reading the unedited file even after `sed -i` updates the host path. Symptoms: re-running the migration shows the same errors you just "fixed."
**Fix:** `docker compose up -d --force-recreate <service>` after a `sed -i` to remount the new inode. Or edit preserving inode (`cp tmp.sql original`).

---

## Standard verification after every change
```bash
curl -s https://<client-host>/health          # client's live app — MUST stay {"status":"ok"}
docker exec <brain> gbrain stats               # Pages should climb after an ingest
```
