---
date: 2026-05-27
tags: [safeclaw, suffolk, hermes, ingest, decision, config]
related-services: [safeclaw-hermes-reader, ollama-cloud, gbrain]
source: session
status: resolved
---

# SafeClaw Suffolk ingest — final working configuration

## Context
After a long debugging session through model behaviors, rate limits, key swaps, batching, and full-stack restarts, the Suffolk ingest is now running autonomously. This is the proven recipe. Capture so it's reproducible (and so other client deploys start here, not at zero).

## The recipe (each part matters)

1. **Single agent only** — just the Hermes reader. **NO OpenClaw**, no second agent, sharing the same Ollama account. (See `gotchas/openclaw-ollama-concurrency-conflict.md`.)
2. **Model: `glm-4.7`** (Ollama Cloud, OpenAI-compat). Fast, non-reasoning, clean tool-calls. (See `gotchas/ollama-cloud-models-and-limits.md` for the scorecard.)
3. **Multi-key credential pool** in `ollama-cloud`:
   - `#1` env `OLLAMA_API_KEY` = primary (upgraded plan account)
   - `#2` manual entry = fallback
   - (See `patterns/hermes-credential-pool-multi-key.md`.)
4. **~~`agent.auxiliary.compression.enabled: false`~~ → `true`** (REVERSED session 7 — see Update below). Disable was only valid while OpenClaw was hogging Ollama's concurrency; session 6 stopped OpenClaw, so the disable was already stale. Leaving it off caused O(n²) token-per-call growth that vaporized weekly credit in ~1 day. **CORRECT VALUE: `true`** (see `gotchas/hermes-compression-off-causes-quadratic-tokens.md`).
5. **`gmail_suffolk` MCP commented out** in the reader config — Composio Gmail isn't connected; an unconfigured MCP with a `__FILL_IN__` URL aborts the entire agentic run before any work happens.
6. **Cron cadence: `0 */2 * * *`** (every 2h — session 7) — paired with compression-on + max_turns=25 + api_max_retries=2 (below). Cadence history annotated in `config/reader-hermes.yaml` schedule comment. Hourly (`0 * * * *`) was tried session 6→7 and re-vaporized the weekly cap in ~1 day.
6a. **`agent.max_turns: 25`** (NEW session 7) — was Hermes' default 90. Observed runs hitting `msgs=94` walking the wide 71-channel scope; capping at 25 bounds the worst-case run cost, watermarks carry across runs.
6b. **`agent.api_max_retries: 2`** (NEW session 7) — was Hermes' default 3. The 3rd retry on hard 429 walls is pure waste; one retry still covers real transient blips.
7. **Brain embeddings**: host Ollama bound to `172.17.0.1:11434` (docker bridge, NOT 127.0.0.1) via systemd drop-in. Required for GBrain to embed pages.

## What got written
By the time this config settled, the Suffolk brain held **109+ pages** (96 of `callrail-new-daily-calls`, 8 of `expenses`, plus digests/summaries), all embedded, climbing hourly. Remaining: ~34 channels the bot is a member of still to be ingested (the cron will chip through them).

## Trade-offs evaluated and rejected
- **kimi-k2.5**: writes pages at small scope but reasons for minutes per agentic step under heavy tool load — won't scale.
- **gpt-oss:120b**: returns its output in `reasoning` field, leaving `content=""` → Hermes nudges forever, never calls `put_page`.
- **qwen3-coder:480b**: clean but slow + APITimeout on big runs.
- **glm-4.6**: tripped Hermes' OpenAI-compat tool-call parser bug (`'str' has no attribute 'get'`).
- **Hosted Anthropic key**: still recommended for highest-reliability one-pass ingest (no quota/concurrency caps), but operator chose to stay on Ollama Cloud with the upgraded plan.

## Operational rules (don't re-discover these)
- **Don't recreate the reader mid-run** — `SIGTERM` aborts the ingest before pages are written.
- **After `docker compose up -d --force-recreate hermes-reader`, wait ~30–45s** before triggering a cron run; otherwise the trigger is a silent no-op (gateway not booted).
- **Don't bring OpenClaw back on this Ollama account** — share-and-starve. Point OpenClaw at a different account or shut it down during ingest.
- **Don't expose the brain on a public port** — it holds client PII (names, phones, addresses). Anything user-facing goes behind the existing IP-allowlisted `:8443` listener (or stays internal).

## Timeline
- 2026-05-24: Initial ingest worked at 1-channel scope (kimi-k2.5, old key). 37 pages.
- 2026-05-26 (evening): Operator added bot to 36 channels; ingest started hanging.
- 2026-05-27 (early): Long debugging — concluded "Ollama capacity wall," recommended Anthropic.
- 2026-05-27 (mid): Operator stopped OpenClaw → next run wrote 50 pages. Root cause = concurrency starvation.
- 2026-05-27: Switched primary to upgraded `naughty_bose_129`, wired fallback `goofy_hugle_463` into pool, moved cron to hourly. Brain climbing autonomously.
- **2026-05-29 (session 7) — REVISION.** Brain plateaued at 147 pages (2 channels of real coverage out of 71). Three causes diagnosed + fixed: (a) `slack_native` MCP went stale after ~8h running (`ClosedResourceError`); (b) `goofy_hugle_463` fallback was revoked (HTTP 401, not 429 — silently rendered pool useless); (c) compression-off + hourly cron + 78 tool schemas + default-90 max_turns → O(n²) tokens/run, observed 94-turn runs sending 61,485 tokens in a single LLM call, torching the weekly cap in ~1 day. Shipped (commit `39c0210`): `auxiliary.compression.enabled: true`, `agent.max_turns: 25`, `agent.api_max_retries: 2`, `cron: 0 */2 * * *`. Key rotation (on-box, not committed): new `bf30…` key promoted to primary in `.env`; `naughty_bose_129` demoted to fallback in `auth.json` (marked exhausted to skip until weekly reset); dead `goofy_hugle_463` removed entirely. Brookhaven untouched throughout. Expected ~10-20× weekly budget headroom.

## Related
- `gotchas/openclaw-ollama-concurrency-conflict.md`
- `gotchas/ollama-cloud-models-and-limits.md`
- `patterns/hermes-credential-pool-multi-key.md`
- `gotchas/gbrain-deployment-gotchas.md` (earlier session — host-Ollama bind, GBrain init flags)
- `decisions/suffolk-deployment-tracker.md` (the ongoing tracker — update its status block)
