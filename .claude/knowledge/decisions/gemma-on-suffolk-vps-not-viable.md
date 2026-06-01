---
date: 2026-05-29
tags: [gemma, ollama, local-llm, suffolk, vps, capacity, decision, brookhaven, safeclaw]
related-services: [safeclaw-hermes-reader, ollama-local-host, brookhaven-solds]
source: session
status: rejected
---

# Decision: do NOT host Gemma (or any >1B local LLM) on the Suffolk VPS

## Context
When `naughty_bose_129` 429'd on its Ollama Cloud weekly cap, the operator asked whether we could pull Gemma onto the Suffolk box and use it locally as the ingest model — avoiding the cloud quota wall entirely. Worth evaluating: Ollama is already installed and active on the host (`/usr/local/bin/ollama`, 95 MB resident), so a `pull` would be a zero-install change.

## The box (measured 2026-05-29, not assumed)
| Resource | Value | Notes |
|---|---|---|
| CPU | 2 vCPU AMD EPYC 9354P | Fast Zen 4 cores but only 2 of them allocated to this VM |
| RAM | 7.8 GiB total / 1.4 GiB free / **4.6 GiB available** | `available` includes reclaimable buff/cache |
| Swap | **0 B** | Critical — any RAM spike → OOM killer |
| Disk | 65 GiB free on `/` | plenty |
| GPU | none | `lspci` finds nothing; no nvidia-smi |
| Top consumers | Brookhaven uvicorn 14.4% (1.18 GiB), Hermes reader+actor ~10%, postgres + dockerd ~5% | Brookhaven is the prime-directive app — cannot be displaced |

## Decision matrix — what could fit on 4.6 GiB available

| Model | Pull size (Q4_K_M) | Fits at rest? | OOM risk under load? | Tool-calling quality |
|---|---|---|---|---|
| `gemma3:1b` | ~815 MB | ✅ comfortably | low | **very weak** — too small for 78-tool structured calling |
| `gemma2:2b` | ~1.7 GB | ✅ comfortably | low-medium | weak |
| `gemma3:4b` | ~3.3 GB | ✅ tight | **MEDIUM-HIGH** — KV cache + 32k context spikes can push total >7.8 GiB | moderate-but-still-weak |
| `gemma3:12b` | ~7 GB | ❌ would crush Brookhaven | n/a | n/a |
| `gemma3n:e4b` | ~7.5 GB | ❌ same | n/a | n/a |

## Why "moderate" tool-calling isn't enough
Session 6's model scorecard already eliminated everything weaker than `glm-4.7` at structured tool-calling against this 78-tool agentic context:
- `gpt-oss:120b` returned all output in `reasoning` field, leaving `content` empty — never called `put_page`.
- `qwen3-coder:480b` correct but slow + `APITimeout`.
- `kimi-k2.5` reasoning model = ~3.7min/step.
- `qwen3-next:80b` returned no tool call.

Gemma small variants (1B–4B) are in the same "non-reasoning, small parameter count" bucket. They will be **worse** at structured tool_calls than glm-4.7 in this 78-tool context, not better.

## Why even a fitting model would be too slow
No GPU, 2 vCPU CPU-only inference. Session-5 measured llama3.2:3b at ~12.5 tok/s on this box. Gemma3:4b would be ~6-8 tok/s. A single agent step is 1-2k output tokens → **2-5 minutes per step**, and the ingest is multi-step per channel. Even an hourly cron can't keep up; 2h cron worse.

## Prime-directive risk (the deciding factor)
On a 0-swap, 7.8 GiB box where Brookhaven is the prime-directive live app (client's "Brookhaven Solds" — see project's `CLAUDE.md`), loading a 3.3 GiB model that spikes RAM during inference is a real OOM-killer risk. There's no swap to spill into. The kernel doesn't guarantee it kills Ollama before Brookhaven. **A model that fits at rest can still OOM-kill Brookhaven mid-request under load — and that violates the prime directive.**

## What WOULD be acceptable, if needed
- **`gemma3:1b`** (815 MB) is safe purely as an *auxiliary/compression helper* — not the main ingest LLM. Could be wired to Hermes' `auxiliary` provider to handle context compression without burning Ollama Cloud calls. If naughty_bose_129 walls again in the future and we want compression to stay free, pull this. **Don't pull it for the main `model.default`.**

## The actual right path (deferred but recommended)
**Hosted Anthropic key** (`sk-ant-…`): no weekly caps, native Hermes provider, drives 78-tool agentic loops reliably with clean structured tool_calls. The deploy guide has been recommending this since session 5. Operator preferred staying on Ollama; capturing the trade-off here so the next person doesn't re-evaluate from scratch.

## Status
- **Decision: rejected (2026-05-29).**
- **Trigger to revisit:** if Suffolk VPS is upgraded to ≥16 GiB RAM with at least 4 GiB swap, OR if a fresh box-spec measurement shows ≥8 GiB free RAM excluding Brookhaven peak, gemma3:4b becomes viable as a backup local engine — but tool-calling quality vs glm-4.7 should still be benchmarked before committing.

## Related
- `decisions/safeclaw-ingest-working-config.md` — the current working LLM stack (glm-4.7 on Ollama Cloud, with credential pool fallback).
- `gotchas/ollama-cloud-models-and-limits.md` — model scorecard that already eliminated comparable-size local models.
- Brookhaven prime-directive — Suffolk project root `CLAUDE.md`.
