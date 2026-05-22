---
date: 2026-05-22
tags: [suffolk, deployment, safeclaw, gbrain, ongoing]
related-services: [safeclaw, safeclaw-brain]
source: session
status: in-progress
---

# Suffolk VPS Deployment Tracker (SafeClaw + GBrain)

> ONGOING TRACKER — update this as the deploy progresses and issues arise.

## Goal
Deploy SafeClaw (now GBrain-backed) to the first client's production VPS — Suffolk.

## Target box
- `ssh suffolk-vps` → IP `187.77.30.131`, hostname `srv1687869`, public `srv1687869.hstgr.cloud`
- **x86_64**, Ubuntu, 2 vCPU, 7.8 GiB RAM (0 swap), 92 GB free, Docker 29.5.1 + Compose v5.1.3 present.
- **Already runs the client's LIVE "Brookhaven Solds" app**: nginx on 80/443, uvicorn :8001, host Postgres :5432, served at https://srv1687869.hstgr.cloud (`/health` → ok). MUST NOT be disturbed.

## Plan
Full runbook: `SUFFOLK-DEPLOY-PLAN.md` in the repo. Key adaptation: **do NOT run the stock provision-vps.sh** (it installs Caddy on 80/443 + does `ufw --force reset`). Instead add a SafeClaw **nginx subdomain vhost** (`safeclaw.srv1687869.hstgr.cloud` → 127.0.0.1:8080) alongside Brookhaven, issue cert via existing certbot. SafeClaw's Postgres are containerized (no host ports) → no clash with Brookhaven's :5432.

## Status — 2026-05-22
- ✅ Code complete + pushed: branch `feat/safeclaw-brain-gbrain`, PR #1 (github Vasanth19/safeclaw).
- ✅ Local smoke test PASSED (infra): image builds (arch-aware), brain boots healthy on Postgres, embeddings via local Ollama, MCP put_page/get_page round-trip, 401 without token.
- ✅ VPS readiness verdict: READY, no hard blockers (read-only assessment done).
- ⛔ NOT deployed yet — blocked on prerequisites below.

## Deploy prerequisites (BLOCKERS — only user/customer can satisfy)
1. **DNS** — create A record `safeclaw.srv1687869.hstgr.cloud → 187.77.30.131` (or a customer domain). Needed before certbot.
2. **Customer credentials** (entered in the /setup wizard): LLM key (Anthropic recommended — see gotcha re: Ollama :11435 vs :11434), Composio API key + user ID (Gmail/Drive/Slack connected), Telegram bot token + boss's user id, optional Slack/Firecrawl.
3. **Build for x86_64** — the box is amd64; build `--platform linux/amd64` or build on the box (native).
4. **(recommended) resolve the OPEN query/holder issue first** (see gotchas) — else the actor can't search the brain.

## Open issues
- ~~query/search return []~~ **RESOLVED 2026-05-22** — NOT a real bug. GBrain hard-excludes `test/`, `archive/`, `attachments/`, `.raw/` slug prefixes from search/query (`DEFAULT_HARD_EXCLUDES`). The smoke test used a `test/` slug → correctly filtered. Real slugs (`people/...`) return hits (search 0.29, query 0.96). Bootstrap only writes non-excluded prefixes → production retrieval was never broken. Verify with `scripts/smoke-brain.sh`. (Also: `delete_page` is a soft-delete — reusing a slug after delete needs care.)
- Hermes LLM points at Ollama :11435 but Ollama installs on :11434 → use a hosted LLM key for Hermes (brain uses :11434 for embeddings only).
- Actor can apply approved review_queue rows but can't read/close them via MCP (tasks-api lacks review_queue ops).

## Pre-stage progress (VPS, Brookhaven untouched — verified 200/ok after every step)
- ✅ repo cloned to `/opt/safeclaw` @ `29e0da6` (branch feat/safeclaw-brain-gbrain)
- ✅ Ollama installed (:11434) + `nomic-embed-text` pulled
- ✅ `safeclaw-brain` image **built on-box** (amd64 native, 452 MB)
- ✅ standard images pulled: `pgvector/pgvector:pg16`, `postgres:16-alpine`, `postgrest/postgrest:latest`
- ⛔ **hermes image blocker:** `ghcr.io/vasanth19/safeclaw-hermes:1.2` → registry **unauthorized** (GHCR package private/absent). Fallback: make it public, `docker login ghcr.io` on the box, OR uncomment the `build:` stanza in docker-compose.yml (lines ~200/273) and build from `docker/Dockerfile.safeclaw-hermes` on-box (heavy).
- NOT done (gated): nginx subdomain vhost + certbot (needs DNS), the /setup wizard (needs creds), `docker compose up` (full stack).

## Update log
- 2026-05-22: Tracker created. Code done + smoke-tested locally.
- 2026-05-22: query/search [] resolved as false alarm (test/ slug hard-exclude).
- 2026-05-22: VPS pre-staged safely (clone + Ollama + brain image + std images), zero Brookhaven impact. New blocker found: hermes GHCR image unauthorized. Remaining gates: DNS, customer creds, hermes-image access.
