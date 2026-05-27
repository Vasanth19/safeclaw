# Suffolk Deployment Guide — SafeClaw (GBrain-backed) — RUNNING DOC

> **This is a living document.** Update the **Current Status** block and the **Update Log** every time the deploy moves or a new nuance is found. Secrets live in `suffolk.env` (gitignored) — never put them here.

---

## ⭐ CURRENT STATUS — START HERE (new agent: read this first)

**🎉 As of 2026-05-24 (session 5) — INGESTION IS LIVE. The brain is FILLING. A trial `slack_ingest` run completed end-to-end on `kimi-k2.5`: GBrain now holds 6 embedded `slack_message_observation` pages (`observations/slack/callrail-new-daily-calls/<ts>`), 6/6 embedded. Full chain works: Slack → kimi-k2.5 → put_page → GBrain embeds (host Ollama bind) → searchable. Brookhaven `{"status":"ok"}` throughout.**

**What made it work this session (in order):** (1) actor recreated on correct LLM env; (2) host Ollama embeddings bind fixed (`172.17.0.1:11434`); (3) **disabled the broken `gmail_suffolk` MCP** that was aborting every run; (4) discovered the Ollama Cloud **weekly cap is PER-MODEL** — qwen3-coder:480b + others 429'd from test runs, but **kimi-k2.5 still had quota**, so reader stays on kimi-k2.5; (5) the FIRST post-recreate trigger fired before the gateway finished booting (no-op) — **re-trigger AFTER the gateway is fully up** (~30s) and it runs.

**Operational notes for steady-state:** ingest cron is now `0 */6 * * *` (every 6h) to conserve the per-model weekly quota. If kimi-k2.5 later 429s, either wait for its weekly reset or switch `model.default` to whichever model still has quota (probe `/v1/chat/completions` per model). Watch for kimi reasoning ReadTimeouts on heavier runs; a hosted Anthropic key remains the most robust long-term LLM.

**✅⛔ Session 6 FINAL — model SOLVED (glm-4.7), now blocked only by Ollama plan usage cap.** Switched model to **`glm-4.7`** (committed `0598aeb`): benchmarked fastest clean tool-caller (~1s/call, minimal reasoning). In a real one-channel run it **worked** — drove the agentic loop 22 turns deep (fetch history → process → tool calls), no hang, no parse bug. BUT it hit `429 "session usage limit"` (~47k tokens; account `naughty_bose_129`) and then even a tiny probe 429s — the Ollama Cloud **plan-tier usage cap is too tight**; one channel's run exhausts it. Credits don't lift it ("upgrade for higher limits"). The ~47k/channel is inflated by 78 tool schemas (70 from the brain MCP) re-sent each turn; can't be trimmed at runtime (Hermes has no MCP tool-allowlist — would need an image rebuild, and the account cap is tight enough that a tiny probe 429s anyway). **The functional pipeline is DONE; the only blocker is LLM capacity. Resolve by: (1) UPGRADE the Ollama plan (`https://ollama.com/upgrade`) so glm-4.7 completes, or (2) hosted Anthropic key (no usage caps).** Reader model left on glm-4.7; full 71-channel list restored; 37 pages; Brookhaven ok.

**🎉 SESSION 6 RESOLVED (2026-05-26 late) — ROOT CAUSE was OpenClaw eating the account's CONCURRENCY.** The operator stopped the OpenClaw runtime on the box; immediately the old key `goofy_hugle_463` started serving requests (was "too many concurrent requests" because OpenClaw's many agents saturated the Pro account's concurrency slots). With OpenClaw stopped, a **single reader-agent ingest completed cleanly**: pages **37 → 87** (50 callrail observations, all embedded). **WORKING RECIPE: single agent (no OpenClaw) + old key `goofy_hugle_463` (has budget) + model `glm-4.7` (fast, no reasoning stall) + `agent.auxiliary.compression.enabled:false` (1 request at a time).** Every prior "hang" was concurrency starvation from OpenClaw, not model/scope/quota. Broader 71-channel ingest now running on the single agent (watermarks skip done channels); the 6h cron continues it autonomously. **⚠️ Do NOT run OpenClaw and the SafeClaw ingest against the same Ollama account concurrently — they starve each other's concurrency.**

**(historical) two-key reality (both have a distinct ceiling; model glm-4.7 is solved):**
- **NEW key `e292…` (acct `naughty_bose_129`)** — *serves* requests, runs glm-4.7 fine (reached 22 turns into a channel), but has a **session usage limit** ~one channel (≈47k tok) then 429; session resets ~2h. **This is the key in `.env` now.** Steady state: the 6h cron will chip through a channel or two per run as the session budget resets — slow but progressing. For fast/full ingest, **upgrade this account's plan**.
- **OLD key `605722…` (acct `goofy_hugle_463`, Pro, vasanth@hyphenlabs.com)** — dashboard shows budget (session 50% / weekly 29% used) BUT requests **hang / "too many concurrent requests"**: its concurrency slots are saturated (other usage on the main account + stale hung requests from our test runs). Disabling `agent.auxiliary.compression` (committed `01beef8`) did NOT clear it. **Unreliable for ingest unless that account's concurrency is freed/upgraded.**
- **Most reliable = hosted Anthropic key** (no session or concurrency caps).

**(superseded) earlier per-key notes:** NEW key `e292…` (acct `naughty_bose_129`) *serves* the heavy agentic call fast → ran 22 turns deep, then hit its **session usage limit** (~47k tok/channel; needs plan upgrade). OLD key `605722…` (acct `goofy_hugle_463`) returns 200 on tiny probes but the **heavy first agentic call HANGS** (idle, no response) — do NOT use it. So the working combo is **glm-4.7 + NEW key + a plan upgrade** (or Anthropic). `.env` is set to the NEW key.

**⛔ Session 6 earlier — kimi's PER-STEP LATENCY (superseded by glm-4.7 fix above).** Decisive tests: (a) raw API is fine — kimi-k2.5 returns a correct `tool_call` with tools+streaming in ~1.5s, and both old+new keys serve a 10k-token request in ~2s; (b) but inside Hermes the agentic run logs `auxiliary auto-detect` then takes **~3.7 minutes per step** (two detect cycles 00:43:41→00:47:21, then idle again) — a multi-step ingest needs many steps, so even a single channel never completes in a practical window; (c) a **full `docker compose down && up`** clean restart did NOT fix it (rules out stuck state). The big real prompt (system + 78 tool schemas + multi-step task) makes the reasoning model think for minutes/turn. **Conclusion: Ollama Cloud reasoning models are too slow per-step for this agentic ingest, and the non-reasoning ones fail otherwise (gpt-oss empty-content, qwen3-coder:480b slow/timeout). The fix is a faster engine — hosted Anthropic key (`sk-ant-…`).** Operator has been asked to decide. State left clean: full 71-channel list restored, model kimi-k2.5, Brookhaven ok, 37 pages.

**⚠️ Session 6 earlier — WIDE ingest (all channels) hangs; single-channel still works.** Operator added the bot to ~36 channels and supplied a NEW funded Ollama key (`e292…`, account has quota across all models incl. qwen3-coder:480b/gpt-oss:120b — old `goofy_hugle_463` key swapped out in `.env`). But a wide agentic run hangs on the **first model call**: gateway goes idle (~1% CPU) right after `auxiliary auto-detect`, agent.log frozen, **0 new pages**. Findings:
- It is NOT scope alone — even a **6-channel batch** hung the same way (tested + reverted; full 71-list restored).
- Model scorecard on Ollama Cloud's OpenAI-compat path: `glm-4.6` parse bug · `gpt-oss:120b` returns empty `content` (all output in `reasoning` field) so the loop never reaches put_page · `qwen3-coder:480b` correct but slow + `APITimeout` · `kimi-k2.5` a streaming probe also returned empty `content` with text in `reasoning` (likely max_tokens artifact, but suspicious). kimi is the only model that has ever written pages here (the 37).
- **No tool-allowlist exists** to trim the brain's 70 MCP tools — neither Hermes (`mcp_servers.*` has no tool filter) nor GBrain config. The reader loads **78 tools** total; that + the open-ended "process all channels" prompt makes the first reasoning-model call very heavy.
- Removed a **stray duplicate cron** `00b68ae3a6e9` ("Slack Ingestion Job", `*/30`, ran `./slack_ingestion.py`) that was double-loading the LLM.
- **Likely real fix = hosted Anthropic key** (`sk-ant-…`): reliably drives large agentic loops with many tools, returns proper `content`+`tool_calls`, no reasoning-channel/empty-content quirk, no Ollama timeout. Operator preferred staying on Ollama; this remains the open decision. Alternative Ollama path = engineer a smaller per-run batch loop AND find a non-reasoning model that returns real `content` (qwen3-coder works but is slow).
- State left clean: full 71-channel list restored, model `kimi-k2.5`, container synced, Brookhaven `{"status":"ok"}`, 37 pages intact.

**Remaining (non-blocking for text ingest):**
- **Slack `files:read`** — attachments (video/image) still can't download; operator must add the scope in the Suffolk workspace (see below).
- **Gmail ingest** — still needs the customer to connect Gmail in Composio; the gmail MCP is disabled until then.

### ✅ Fixed & deployed (session 5)
- **Blocker (old #2) CLOSED — hermes-actor recreated onto the correct LLM env** (was the old broken `glm-5.1:cloud` + dead `:11435` + `ollama-local` placeholder). Box was already at the fixed commit `bffe1f4`, so `docker compose up -d --force-recreate hermes-actor` was enough — actor now runs `kimi-k2.5` / `https://ollama.com/v1` / real key. Booted clean; only error is the known optional Telegram `__FILL_IN__` token (non-fatal).
- **Blocker (old #1) CLOSED — host Ollama embeddings bind fixed.** Wrote `/etc/systemd/system/ollama.service.d/override.conf` with `OLLAMA_HOST=172.17.0.1:11434`, `daemon-reload` + `restart ollama`. Verified: `ss -tlnp` now shows `172.17.0.1:11434`, and from inside `safeclaw-brain`, `curl http://172.17.0.1:11434/api/tags` returns `nomic-embed-text`. The brain CAN now embed. (Bound to the docker bridge, not `0.0.0.0` — no host firewall, so `0.0.0.0` would expose Ollama publicly.)
- **Ingest cron triggered** (`hermes cron run 187b27fb908d`) — ran end-to-end, reached the LLM, but failed on the 429 below. So the full pipeline is proven wired; only the quota wall stops pages.

### 🔴 NEW hard blocker — Ollama Cloud weekly usage limit (HTTP 429)
Triggering the ingest produced: `429 — you (goofy_hugle_463) have reached your weekly usage limit` (both reader AND actor). **Why it burns so fast:** the `slack_ingest` cron runs **every 30 min** (`*/30 * * * *`), each run is an agentic **kimi-k2.5 (thinking) model** job making several multi-step LLM calls (≈13 calls observed in one run). 48 runs/day × multi-call thinking = the free weekly cap is exhausted quickly. **The free Ollama tier is not sized for an every-30-min agentic cron.** Options (operator decision — see session-5 log): (a) repoint Hermes at a **hosted Anthropic key** (`sk-ant-…`, no weekly caps — the guide's recommended path), (b) add paid usage / upgrade at ollama.com/settings, or (c) wait for weekly reset. **✅ Cron cadence already dialed back (session 5): `slack_ingest` is now `0 */6 * * *` (every 6h, was `*/30`) — committed `a1bc55c`, deployed + verified in `/opt/data/cron/jobs.json`.** That alone cuts LLM call volume 12×; still needs a working LLM (resolve the 429 above) before pages fill.

**Local Llama on the box — evaluated session 5, NOT viable.** Box is 2 vCPU / 7.8 GiB / **0 swap**, no GPU. Tested `llama3.2:3b`: ran at ~12.5 tok/s (CPU) but loading it dropped free RAM to ~2.7 GiB next to live Brookhaven — an 8B (~4.7 GB) would risk OOM and the prime-directive app. Small Llamas are also weak at the structured tool-calling the agentic ingest needs. Test model removed; box clean. **Hosted Anthropic key is the path.**

### ✅ Fixed & deployed earlier session (reader)
- **LLM credential** — the box's `OLLAMA_API_KEY` was a 12-char placeholder (`ollama-local`, hardcoded in the compose `environment:` block, which overrode `.env`). The REAL 57-char key lives in `suffolk.env`. Fixed by: removing the hardcoded `OLLAMA_API_KEY` from both `environment:` blocks so it flows from `env_file:.env`, and writing the real key into the box `.env`. Verified working (`/v1/chat/completions` → 200).
- **LLM endpoint** — `OLLAMA_BASE_URL` pointed at the dead local daemon `host.docker.internal:11435` (the true cause of the original `APIConnectionError`). Changed to `https://ollama.com/v1` in both blocks.
- **Model** — was `glm-5.1:cloud` (does not exist). Switched to **`kimi-k2.5`** (agentic, the model the config author wanted) after `glm-4.6` tripped a Hermes OpenAI-compat tool-call parse bug (`'str' object has no attribute 'get'` at API call #13). kimi-k2.5 reads Slack cleanly.
- All of the above are committed (branch `feat/safeclaw-brain-gbrain`, latest `bffe1f4`) and deployed to **hermes-reader** on the box.

### 🔴 DECISIVE (session 5) — Ollama Cloud free tier is account-wide rate-limited; testing itself burns it
After fixing the gmail-MCP abort and switching the model, the trial ingests returned `HTTP 429 — you (goofy_hugle_463) have reached your weekly usage limit` on **both** kimi-k2.5 AND qwen3-coder:480b. The cap is **account-wide across all models**, and the agentic ingest + the few test runs this session re-exhausted a quota that had briefly reset. **Conclusion: the free Ollama Cloud tier cannot support this workload, and you can't even iterate on a model/timeout stopgap because each test burns the limited free quota.** The only real fixes are: (a) **hosted Anthropic key** (recommended — pay-as-you-go, no weekly wall, native Hermes support), (b) pay/upgrade at ollama.com/upgrade, or (c) wait for the weekly reset (unknown date) and immediately switch off the free tier. **Model is now `qwen3-coder:480b`** (committed `86f6224`) — kept because it's the better non-reasoning tool-caller for when quota returns. NOTE stale env-var footgun: `docker-compose.yml` hardcodes `HERMES_DEFAULT_MODEL: kimi-k2.5` (lines 222/301) and box `.env` has `glm-5.1:cloud`, but the config template's `model.default` wins (run logs confirmed `model=qwen3-coder:480b`); align these when finalizing.

### 🔴 (superseded by quota wall) kimi-k2.5 reasoning ReadTimeout + hallucinated tools
Two real fixes landed first: (1) **the `gmail_suffolk` MCP was aborting every `slack_ingest` run** — its URL was `__FILL_IN__&connected_account_id=` (Composio Gmail never connected) → "missing http:// protocol" → the failing MCP init killed the whole run before any Slack/LLM work. **Disabled it in `config/reader-hermes.yaml`** (commit `58a0889`); the agent now executes and reaches the LLM. BUT the run then stalls:
- Agent hallucinates a non-existent tool (`environment_info`) → self-correction.
- **`Connection to provider dropped (ReadTimeout)`** on substantive calls, while a trivial direct probe to `kimi-k2.5` returns HTTP 200 in ~2s. Root cause: **kimi-k2.5 is a reasoning model** — on the full ingest prompt it "thinks" longer than Hermes' provider read-timeout, so every real call times out. Pages still 0.
- This is the **3rd Ollama-Cloud OpenAI-compat friction point** (glm-4.6 tool-call parse bug → kimi timeout + hallucinated tools). **Decisive fix = switch Hermes to a hosted Anthropic key (`sk-ant-…`)** — native Anthropic support in Hermes, no OpenAI-compat tool-call quirks, no reasoning-vs-read-timeout problem, no weekly quota. Operator must supply the key into `suffolk.env`; agent then repoints both agents + recreates. (Cheaper stopgap if staying on Ollama: try a non-reasoning model and/or raise the provider read-timeout — but the pattern says move to Anthropic.)

### 🔴 Slack attachments — bot lacks `files:read` (operator-only, blocked on workspace access)
The `xoxb-` bot (`aiassistant` @ "Suffolk County House Buyers", team `TLL1P1QU9`, `suffolkcounty-emg4147.slack.com` — confirmed via `auth.test` session 5) has history/read scopes but NOT `files:read`, so Slack refuses file bytes → videos/images can't be downloaded. **Session-5 finding: the `aiassistant` app does NOT appear under the operator's api.slack.com/apps — that login only sees the "Hyphen labs" workspace (apps: SafeClaw, Jarvis, KEDB Solo). The operator's Slack browser session is signed into "Rocking Spur Homes" + "Hyphen labs" but NOT "Suffolk County House Buyers".** So to make the scope change you must FIRST sign into the Suffolk workspace (`suffolkcounty-emg4147.slack.com`) at slack.com/signin. THEN: api.slack.com/apps → aiassistant → OAuth & Permissions → add **`files:read`** → **Reinstall to Workspace** → put the new `xoxb-` token in `suffolk.env` + box `.env` → recreate reader. Also: the bot is in only **1 of 71 channels** — `/invite @aiassistant` into channels you want ingested.

### ▶️ To finish (once the LLM quota blocker is resolved — agent CAN do this)
```bash
ssh suffolk-vps 'cd /opt/safeclaw && docker compose exec -T -u 10000 hermes-reader /opt/hermes/.venv/bin/hermes cron run 187b27fb908d'   # slack_ingest job id
# wait ~120s (kimi is a thinking model), then:
ssh suffolk-vps 'docker exec safeclaw-brain gbrain stats'   # Pages should go > 0 (embeddings bind already fixed)
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
