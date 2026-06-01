---
date: 2026-05-29
tags: [hermes, tokens, ollama, agentic-loop, compression, rate-limit, cost, safeclaw]
related-services: [safeclaw-hermes-reader, ollama-cloud]
source: session
---

# Disabling `auxiliary.compression` makes Hermes per-call tokens grow O(n²) in turns

## Context
Hermes' agentic loop sends the **entire growing conversation history** on every LLM call. When `agent.auxiliary.compression.enabled: true`, an auxiliary client periodically summarizes older turns so each call's input size stays roughly flat. When it's `false`, every turn adds its full message (tool result, model output, observation) to the next call's input without ever summarizing. Net effect: per-call input tokens grow ~linearly with turn count, and **total tokens consumed over the run grow quadratically (O(n²))** in the number of turns.

This setting was deliberately set `false` in session 6 (commit `01beef8`) for a different reason: OpenClaw was eating Ollama's concurrency slots, so we wanted Hermes to make only 1 concurrent request to leave a slot free. Once OpenClaw was stopped (later session 6), the disable was no longer needed — but it stayed off. By session 7 it had become the single biggest cause of Ollama weekly-cap exhaustion.

## The smoking-gun evidence (Suffolk session 7)
From `agent.log`:
```
2026-05-27 01:09: 22 msgs → 47,442 tokens in one call (429: session limit)
2026-05-29 01:07: 64 msgs → 35,474 tokens
2026-05-29 17:18: 43 msgs → 56,995 tokens
2026-05-29 18:13: 94 msgs → 61,485 tokens (94-turn run)
```

The `tokens=~N` field in the `API call failed after N retries. HTTP 429:` log line is **input tokens for that single call**. With compression OFF, a 94-turn run sends ~60k tokens in its final call alone, AND every call before that also re-sent the growing history. Total tokens for a 50-turn run ≈ Σ(growing per-call size) ≈ 1–1.5M tokens **per cron tick**.

Pair that with hourly cron (`0 * * * *` was the cadence at the time) = 24 runs/day × 1.25M = **~30M tokens/day**. A Pro-tier weekly cap of roughly 30M dies in 1 day.

## Why it especially hurts an ingest agent
Three multiplicative factors:
1. **Wide tool registry** — the brain MCP alone registers 70 tools; total system-prompt schema overhead is ~78 tools / ~15k tokens. Every turn re-sends those schemas.
2. **Wide scope** — the ingest agent walks all channels in `SLACK_INGEST_CHANNELS` (71 channels at Suffolk). Each channel iteration is multiple LLM turns. Easily 40-100 turns per cron run.
3. **No turn cap by default** — Hermes' `agent.max_turns` defaults to 90. Without an explicit cap, the agent grinds until the model 429s, which under compression-off means tens of expensive calls before failure.

## The fix
Three knobs, smallest commit imaginable:
```yaml
agent:
  auxiliary:
    compression:
      enabled: true     # was false — biggest single saving
  max_turns: 25          # NEW — bound the loop, was default 90
  api_max_retries: 2     # NEW — was default 3, skip wasted 3rd retry on 429 walls
```

With all three: per-call tokens stay ~5-10k regardless of turn position; max turn budget is 25; failed calls don't burn an extra retry. Expected combined effect: **5-10× per-run token reduction**.

Pair with halving the cron cadence (Suffolk went `0 * * * *` → `0 */2 * * *`) and you get another 2× = **~10-20× weekly token budget headroom** on the same Ollama Pro plan.

## When you'd legitimately disable compression
The session-6 reason was real: if the upstream provider has a tight CONCURRENCY cap and Hermes' auxiliary client deadlocks with the main client by competing for the last available slot. But this is a narrow case — solved better by either (a) using a provider/plan with adequate concurrency, or (b) writing a leaky-bucket scheduler that gates auxiliary calls outside the main-call window. **Compression-off is a last-resort workaround, not a default operating mode.**

## Diagnostic signature (so you spot it next time)
Inspect agent.log for `tokens=~N` on 429 lines. If N is regularly above ~20k AND `msgs=M` is regularly above ~20, compression is almost certainly off. Confirm:
```bash
grep -A 1 "auxiliary:" config/<reader>-hermes.yaml | grep -E "compression|enabled"
```
If `enabled: false`, you've found the leak.

## Don't confuse with
- **Per-step latency stalls** (e.g. kimi-k2.5 reasoning for minutes) — that's a model-choice problem, not a compression problem. See `gotchas/ollama-cloud-models-and-limits.md`.
- **Concurrency starvation** (provider hangs on first call, never returns) — that's a concurrency-cap problem, not a per-call-size problem. See `gotchas/openclaw-ollama-concurrency-conflict.md`.
- **Wide tool registry alone** — high schema overhead is real (~15k of the per-call tokens) but it's a fixed multiplier; compression-off is what turns a fixed multiplier into quadratic growth.

## Related
- `decisions/safeclaw-ingest-working-config.md` — current working values (compression on, max_turns=25, retries=2, cron 2h).
- `gotchas/ollama-cloud-models-and-limits.md` — the rate-limit categories this gotcha torches through.
- `patterns/hermes-credential-pool-multi-key.md` — credit-pool rotation can't save you from a leak this size; only fix the leak.
