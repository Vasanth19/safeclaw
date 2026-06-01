---
date: 2026-05-27
tags: [hermes, credential-pool, ollama, failover, rate-limit, safeclaw]
related-services: [safeclaw-hermes-reader, safeclaw-hermes-actor, ollama-cloud]
source: session
---

# Hermes credential pool: rotating multiple keys for one provider

## Context
Hermes' agentic runs against Ollama Cloud (or any rate-limited provider) regularly hit 429s — per-model weekly caps and per-account session caps. A single `OLLAMA_API_KEY` in `.env` means one 429 stalls the whole pipeline until the limit resets. Hermes ships a **credential pool** that auto-rotates between multiple credentials per provider on 429, but the docs are thin. This is the working setup, including the gotcha that ate ~20 minutes.

## Details
- The pool is stored at **`/opt/data/auth.json`** (the `HERMES_HOME`/`auth.json` file), which is on the mounted Docker volume `safeclaw_hermes_reader_data` → **persists across container recreates**.
- The provider id is `ollama-cloud` (NOT `custom` — that's the wrapper used in `config.yaml`'s `model.provider`).
- Pool entries: **`#1` is auto-derived from the env `OLLAMA_API_KEY`** (sourced at run time, marked `env:OLLAMA_API_KEY` in `auth list`). Additional entries are added manually via `hermes auth add`.
- On a `429`, the run log emits `credential pool: marking OLLAMA_API_KEY exhausted (status=429), rotating`. If a fallback exists in the pool, the next call uses it.

### ⚠ The biggest gotcha — pool is cached at gateway startup
The credential pool is loaded once when the Hermes gateway boots. **After `hermes auth add`, you MUST `docker compose up -d --force-recreate hermes-reader`** for the new key to take effect. A long-running gateway will silently keep using its cached single-entry pool and the new key never rotates in. (We watched this happen — `auth list` showed 2 entries while runs only ever loaded `1 entries`.)

### Commands

```bash
# Add a fallback key (provider id = ollama-cloud, NOT 'custom')
docker compose exec -u 10000 hermes-reader /opt/hermes/.venv/bin/hermes auth add ollama-cloud \
  --type api-key \
  --api-key <FALLBACK_KEY> \
  --label <human-friendly-label>

# Inspect — should show "<provider> (N credentials):" + each entry
docker compose exec -u 10000 hermes-reader /opt/hermes/.venv/bin/hermes auth list

# Clear 429 "exhausted" flags after a session reset
docker compose exec -u 10000 hermes-reader /opt/hermes/.venv/bin/hermes auth reset ollama-cloud

# Remove a pool entry by index, id, or label
docker compose exec -u 10000 hermes-reader /opt/hermes/.venv/bin/hermes auth remove ollama-cloud <label-or-index>

# REQUIRED — reload the pool into the live gateway
docker compose up -d --force-recreate hermes-reader
```

### Picking primary vs fallback
- Set `OLLAMA_API_KEY` in `.env` to the **primary** key (highest-capacity / upgraded account) — that becomes pool `#1` (env-sourced).
- Add the **fallback** key via `hermes auth add ollama-cloud --label <fallback>` — becomes `#2` (manual entry).
- The pool sorts by priority; the env entry takes #1 unless overridden. Don't add the same key twice (you'll get a duplicate that doesn't help).

### Verifying it works
After recreate, a fresh cron run should log:
```
cron.scheduler: Job '<id>': loaded credential pool for provider ollama-cloud with 2 entries
```
On a 429 mid-run:
```
agent.credential_pool: credential pool: marking <KEY-LABEL> exhausted (status=429), rotating
```
If you see `"credential pool: no available entries (all exhausted or empty)"`, both keys are spent — wait for reset or upgrade.

## Example — the Suffolk setup that works today

```text
ollama-cloud (2 credentials):
  #1  OLLAMA_API_KEY            api_key env:OLLAMA_API_KEY ←   (naughty_bose_129, upgraded plan — primary)
  #2  goofy_hugle_463_fallback  api_key manual                (Pro account, fallback)
```

## Pitfalls also worth knowing
- `hermes auth add` needs the **flag before the subcommand** if you want `--accept-hooks`: `hermes cron --accept-hooks remove …` not `hermes cron remove --accept-hooks …`. (Different subcommand parsing quirk.)
- The pool only helps when the provider returns a *clean 429*. If the provider **hangs** on the request (concurrency cap), no rotation fires — the call is still in flight. See `gotchas/openclaw-ollama-concurrency-conflict.md`.
- Rotation status survives writes to `auth.json`. To start fresh after a session reset, run `hermes auth reset <provider>` and recreate.

## Related
- `gotchas/ollama-cloud-models-and-limits.md` — when rotation helps (per-model weekly / per-account session) vs when it doesn't (concurrency hangs).
- `decisions/safeclaw-ingest-working-config.md` — Suffolk's current 2-key pool.

---

## Update 2026-05-29 (session 7) — three more things learned

### Gotcha: a pool entry can be REVOKED (HTTP 401), not just exhausted (429)
The Suffolk pool's fallback `goofy_hugle_463` (`605722…`) silently became invalid between sessions. Direct probe to Ollama returned **`HTTP 401 unauthorized`**, not 429. Hermes' classifier treats 401 as a transport/auth failure separate from rate-limit, so the rotation logic does still rotate — but to a dead endpoint. **The pool log message `credential pool: rotated to <label>` does NOT mean the rotated-to entry is functional.** Always probe both keys directly when the pool is misbehaving:

```bash
curl -s -w "\nHTTP=%{http_code}\n" -X POST https://ollama.com/api/chat \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"glm-4.7","messages":[{"role":"user","content":"ping"}],"stream":false}' | tail -c 400
```

`HTTP 401` = dead key (remove from pool). `HTTP 429` with body `you (acct_name) have reached your weekly usage limit` = walled but valid (keep, will rotate back after cooldown). The body's account name is invaluable for diagnosis — Ollama exposes it in error responses but NOT in 200s.

### Pattern: priority-swap when primary is in cooldown
If the primary key 429s and the fallback works, **don't just rotate** — physically reorder so the working key is priority 0. Two reasons: (a) avoid every cron tick trying the exhausted key first and rotating, (b) the env-sourced #1 slot gets reseeded on gateway boot, so making it the working key is more durable than relying on auth.json overrides.

Procedure (no `hermes auth` CLI needed — direct file edit is faster + recovers from stale state):
```bash
# 1. Stop reader (atomic edit)
docker compose stop hermes-reader

# 2. Update .env: OLLAMA_API_KEY = the working key (becomes priority-0 on reseed)
sed -i 's|^OLLAMA_API_KEY=.*|OLLAMA_API_KEY=<WORKING_KEY>|' /opt/safeclaw/.env

# 3. Update /opt/data/auth.json — priority-1 entry holds the walled key with last_status='exhausted'
#    so the pool respects its cooldown.  Use docker compose run --rm --no-deps -u 10000 with a
#    python heredoc — see Suffolk session 7 for the exact script.

# 4. Start
docker compose up -d hermes-reader
```

### Gotcha: docker run -v <volume_guess> fails — use docker compose run
When editing `auth.json` from a one-shot Python script, do NOT use `docker run -v safeclaw_safeclaw_hermes_reader_data:/opt/data ...` — volume name guesses are fragile (the compose project prefix can be unexpected) and the mount silently misses, then `shutil.copyfile('/opt/data/auth.json', ...)` raises `FileNotFoundError`. Use `docker compose run --rm --no-deps --entrypoint='' -u 10000 hermes-reader python3 -c '...'` — that inherits the real volume mounts from the compose file.

### Suffolk pool today (post-session-7 rotation)
```text
ollama-cloud (2 credentials):
  #1  OLLAMA_API_KEY              api_key env:OLLAMA_API_KEY ←  (NEW bf30…, fresh, ✅ HTTP 200 verified)
  #2  naughty_bose_129_fallback   api_key manual               (e292aa…, marked exhausted — cooldown until weekly reset)

removed entirely: goofy_hugle_463 (605722…) — was 401-revoked
```
