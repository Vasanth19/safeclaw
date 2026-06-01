---
date: 2026-05-27
tags: [openclaw, ollama, hermes, concurrency, safeclaw, ingest, deadlock]
related-services: [safeclaw-hermes-reader, openclaw, ollama-cloud]
source: session
---

# OpenClaw saturates the shared Ollama Cloud account's concurrency → Hermes ingest deadlocks

## Context
The Suffolk SafeClaw ingest runs (single Hermes reader agent → Ollama Cloud LLM via OpenAI-compat) were **hanging at the very first model call** — gateway idle (~1-2% CPU), agent.log frozen at `Auxiliary auto-detect`, **0 pages written for hours**. We spent a long debugging chain swapping models, keys, batching channels, restarting the whole stack — none of it fixed it.

The actual root cause: **OpenClaw was running on the same machine with multiple agents using the same Ollama account (`goofy_hugle_463`, vasanth@hyphenlabs.com). Its concurrent calls saturated the Pro plan's concurrency slots, so Hermes' ingest requests had no available slot and just hung indefinitely.** The instant the operator stopped OpenClaw, a single Hermes reader ingest sailed through and wrote 50 pages.

## Details
- **Symptom:** Hermes cron run starts (MCP servers register, "Running job 'slack_ingest'" logs, "Auxiliary auto-detect" logs), then **silence**. No `put_page`, no 429, no error, no progress. Gateway CPU near-idle. Pages don't grow.
- **Misleading signals** that wasted hours:
  - Tiny probes to the same key/model return `HTTP 200` in <1s → made it look like the account was fine.
  - Different models behaved differently when first tried — easy to misattribute the hang to model choice (kimi reasons, gpt-oss empty content, etc.).
  - The Ollama 429 was sometimes literally `"too many concurrent requests"` (not a token usage limit) — the account dashboard showed plenty of budget (50% session, 70% weekly), so it didn't look like the limit you'd expect.
- **Decisive evidence**: stopping the OpenClaw runtime on the box → the very next single-agent Hermes run completed and wrote 50 pages on the same key/model that had been hanging seconds earlier.

## Why the hang isn't a 429
Ollama Cloud's Pro plan has a **separate concurrency cap** distinct from token usage. When concurrency is saturated, additional requests don't get a clean error — they **block / queue / hang** until a slot frees. Hermes' agentic loop sees no response, the run sits idle until the per-call timeout (1800s default), and to the observer it looks like a model/model-config bug.

## Rule
**Never run OpenClaw and the SafeClaw ingest against the same Ollama Cloud account at the same time.** They share concurrency slots and starve each other.

## Detection / triage
When a Hermes ingest hangs at `Auxiliary auto-detect` with 0 pages:
1. Probe the key directly:
   ```bash
   curl -s -m 25 https://ollama.com/v1/chat/completions \
     -H "Authorization: Bearer $KEY" \
     -d '{"model":"glm-4.7","messages":[{"role":"user","content":"hi"}],"max_tokens":3}' \
     -w '\nHTTP %{http_code}\n'
   ```
   If the response is **`"too many concurrent requests"`** (not "usage limit"), the account is concurrency-saturated by another caller.
2. Look for other consumers on the host: `ps aux | grep -iE 'openclaw|claw'` and any other Hermes gateway / dashboard processes that share `OLLAMA_API_KEY`.
3. Stop or reroute the other consumer. Verify a fresh probe returns 200 quickly. Then re-trigger the Hermes ingest.

## Fixes (in order of cost)
1. **Stop OpenClaw on the same box** (operator action) — fixed Suffolk immediately.
2. **Give OpenClaw a different Ollama account/key** than SafeClaw.
3. **Wire a multi-key credential pool** in Hermes (`hermes auth add ollama-cloud --type api-key …`) so when one account is saturated/exhausted it rotates to another. See `patterns/hermes-credential-pool-multi-key.md`.
4. **Hosted Anthropic key** — no concurrency cap; sidesteps the whole class of issue.

## Example
Sequence from the Suffolk session (2026-05-27, captured here so we don't re-discover this):
- Operator added the assistant bot to 36 Slack channels → expected the hourly cron to ingest them.
- 5+ hours of hanging runs across kimi-k2.5, gpt-oss:120b, qwen3-coder:480b, glm-4.7 — every model hung at the first call.
- Probes returned 200, dashboard showed budget, errors.log was empty.
- Operator stopped OpenClaw. Next single-agent run: **37 → 87 pages in one pass.**

## Related
- `patterns/hermes-credential-pool-multi-key.md` — fallback rotation pattern.
- `gotchas/ollama-cloud-models-and-limits.md` — model scorecard + the three distinct Ollama limit types (per-model weekly, account session, concurrency).
- `decisions/safeclaw-ingest-working-config.md` — the proven config that finally worked.
