---
date: 2026-05-27
tags: [ollama, ollama-cloud, hermes, models, rate-limits, openai-compat]
related-services: [ollama-cloud, safeclaw-hermes-reader]
source: session
---

# Ollama Cloud: model behaviors on Hermes' OpenAI-compat path + the three distinct limit types

## Context
Driving Hermes' agentic ingest (78 tools registered, streaming, tool-calling) against Ollama Cloud surfaced very different behaviors per model — and three completely different rate-limit categories that look superficially similar. Captured here so we don't trial-and-error through them again.

## Model scorecard (benchmark + real-run, Suffolk 2026-05-27)

Conditions: ~18 dummy tool schemas + large system prompt, streaming, asks for a single tool call. Real-run = actual SafeClaw ingest.

| Model | Latency | Tool call | Notes |
|---|---|---|---|
| **glm-4.7** | **~1.0s** | ✅ clean | minimal reasoning (~240 chars). **Winning model.** Drove the ingest to completion. |
| glm-4.6 | ~5.2s | ✅ | older. Earlier tripped Hermes' tool-call parser (`'str' object has no attribute 'get'`). Avoid. |
| glm-5 | ~3.5s | ✅ clean | acceptable fallback. |
| minimax-m2 | ~2.3s | ✅ clean | acceptable fallback. |
| gpt-oss:120b | ~4s | ✅ tool call, but **content=""** | Returns its prose in a `reasoning` field, leaves `content` empty. Hermes' loop reads `content`, sees nothing, nudges forever, never reaches `put_page`. **Unusable for this agentic loop.** |
| qwen3-coder:480b | slow | ✅ | works but slow + `APITimeout` on heavy runs. Huge model. |
| qwen3-next:80b | ~3.4s | ❌ none | Returned reasoning + content but no tool call on this prompt. Skip. |
| **kimi-k2.5** | ~1.9s benchmark, **~3.7 min/step in Hermes** | ✅ at benchmark | Reasoning model. Tiny probes return fast, but on the real prompt (system + 78 tool schemas + multi-step task) it thinks for **minutes per turn** → ingest never completes within any practical window. Did write the early Suffolk pages (when scope was 1 channel), but won't scale. |

**Default choice for agentic tool-calling on Ollama Cloud: `glm-4.7`.**

## The three distinct Ollama Cloud limits — they are NOT interchangeable

1. **Per-model WEEKLY usage limit** (free tier especially)
   - Error: `"you (<acct>) have reached your weekly usage limit, upgrade for higher limits"`
   - **Scope: one specific model.** A 429 on `qwen3-coder:480b` doesn't mean `kimi-k2.5` is exhausted — they have separate buckets.
   - Triage: probe other models with the same key. Whichever returns 200 has budget. Set `model.default` to it.
2. **Account-wide SESSION usage limit** (Pro plan; ours: `naughty_bose_129`)
   - Error: `"you (<acct>) have reached your session usage limit, upgrade for higher limits"`
   - **Scope: the whole account, every model.** Triggered by a heavy run consuming ~47k+ tokens (one Slack channel via the agentic loop). All models 429 simultaneously after this.
   - Resets ~2h per the dashboard. Adding credits does NOT raise this — needs **plan upgrade**.
3. **Concurrency cap** ("too many concurrent requests")
   - Error: `"too many concurrent requests"` (note: distinct wording — NOT a "usage limit" message).
   - **Scope: simultaneous in-flight requests on the account.** Independent of token budget.
   - When hit, requests don't error cleanly — they **block / queue / hang**. See `gotchas/openclaw-ollama-concurrency-conflict.md`.
   - Triggered when multiple processes share one account (OpenClaw + SafeClaw, or any pair of agents).

**Rule:** read the error string before reacting. "weekly" → swap model. "session" → wait for reset or upgrade plan. "concurrent" → find/stop the other consumer.

## Hermes-side gotchas tied to model choice
- The `auxiliary_client` for vision + compression auto-detects against the same provider/model at run start, so its concurrent calls share the same account concurrency budget. Disabling `agent.auxiliary.compression.enabled: false` cuts one concurrent caller — useful on a tight concurrency cap.
- The per-call request timeout default is **1800s** (30 min) — that means a reasoning-model hang won't surface as a timeout for a long time. Don't expect a quick error when the model is just thinking forever.

## Example — probing per-model status quickly
```bash
key=$OLLAMA_API_KEY
for m in glm-4.7 kimi-k2.5 qwen3-coder:480b gpt-oss:120b minimax-m2; do
  code=$(curl -s -m 25 -o /tmp/x.json -w '%{http_code}' \
    https://ollama.com/v1/chat/completions \
    -H "Authorization: Bearer $key" \
    -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":3}")
  msg=$(python3 -c 'import json;print(json.load(open("/tmp/x.json")).get("error","OK")[:70])' 2>/dev/null)
  printf '%-20s %s  %s\n' "$m" "$code" "$msg"
done
```

## Related
- `gotchas/openclaw-ollama-concurrency-conflict.md` — concurrency cap detection.
- `patterns/hermes-credential-pool-multi-key.md` — surviving per-model and per-session caps by rotating keys.
- `decisions/safeclaw-ingest-working-config.md` — final chosen model + cron config.
- `gotchas/hermes-compression-off-causes-quadratic-tokens.md` — the #1 reason an Ollama Pro weekly cap evaporates in 1-2 days.

---

## Update 2026-05-29 (session 7) — more limit-behavior nuances

### A "topped-up" account can stay 429-walled — top-up ≠ weekly-cap reset
Operator topped up `naughty_bose_129` on the Ollama dashboard. Direct probes from the box *immediately after* still returned `HTTP 429 — you (naughty_bose_129) have reached your weekly usage limit` on:
- `/api/chat` with `glm-4.7`
- `/v1/chat/completions` with `glm-4.7`
- `/api/chat` with `gpt-oss:20b` (smaller model)

All three returned the same weekly-cap error. So either (a) Ollama propagates plan changes on a delayed cadence (minutes-to-hours), OR (b) Pro-tier weekly *rate caps* are independent of credit balance and only reset on the weekly schedule. **Practical implication:** if you top up an account that has 429'd, don't assume the wall is gone — probe directly before re-pointing traffic at it. The credential pool's `last_status: exhausted` flag also persists in `auth.json` across restarts; clear it (`hermes auth reset <provider>` or hand-edit) when the wall actually lifts.

### Body includes account name in 429s, NOT in 200s — useful for diagnosis
Ollama exposes which account is being charged in the error body: `you (<account-name>) have reached your weekly usage limit`. A successful 200 response does NOT include the account name anywhere. So when diagnosing pool issues, **deliberately trigger a 429** (e.g. probe a walled key first) to confirm which account the credential pool actually rotated to.

### Verification probe (copy-paste, redact key)
```bash
KEY=<paste>
curl -s -w "\nHTTP=%{http_code}\n" -X POST https://ollama.com/api/chat \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"glm-4.7","messages":[{"role":"user","content":"ping"}],"stream":false}' | tail -c 400
```
- HTTP 200 + `"content": "pong"` → key works.
- HTTP 429 + `you (<acct>) have reached your weekly usage limit` → walled, identifies account.
- HTTP 401 + `unauthorized` → revoked/invalid key (NOT just walled — must be replaced).
