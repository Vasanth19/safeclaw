# CLAUDE.md — ai-assistant (SafeClaw)

This repo is **SafeClaw** (github `Vasanth19/safeclaw`): a security-hardened, single-user AI email assistant — **Hermes** trust-split agents (reader/actor) wired to a **GBrain**-powered brain. Trust split is enforced at the Composio MCP layer (reader can't send, actor can't see raw email). See `ARCHITECTURE.md`.

## 🚧 Active work — Suffolk deployment (READ THIS FIRST)

There is a **deployment in progress** to the first client's production VPS (Suffolk). A new agent MUST start by reading the running guide so you know **what's done and where to pick up**:

➡️ **`SUFFOLK-DEPLOYMENT-GUIDE.md`** — running document. Read its **"CURRENT STATUS — START HERE"** block first. **Keep it updated** (status block + update log) every time the deploy moves or you discover a new nuance.

Key facts for any agent touching this:
- The GBrain swap is **merged to `main`** (PR #1, merged 2026-05-26). **New client deployments track `main`** (see `CLIENT-DEPLOYMENT-PLAYBOOK.md`). The `feat/safeclaw-brain-gbrain` branch is **deliberately kept open** for in-flight Suffolk fixes and is *not* deleted. **Suffolk is the exception:** its VPS clone at `/opt/safeclaw` still tracks `feat/safeclaw-brain-gbrain` — **do not re-point Suffolk to `main`** while moving parts remain.
- **🚨 PRIME DIRECTIVE:** the Suffolk box also runs the client's **LIVE "Brookhaven Solds" app** (nginx 80/443, uvicorn `:8001`, postgres `:5432`). **Never disturb it.** All SafeClaw additions are isolated (port 8443 + internal docker net). Verify Brookhaven `/health` after any VPS change.
- Secrets live in **`suffolk.env`** (gitignored) — never commit secrets; never paste them into committed docs.
- Deployment knowledge is also mirrored in brain-personal (`projects/safeclaw/suffolk-deployment`) and `.claude/knowledge/decisions/suffolk-deployment-tracker.md`.

## Related docs
- `SUFFOLK-DEPLOYMENT-GUIDE.md` — the running deploy guide (primary)
- `CLIENT-DEPLOYMENT-PLAYBOOK.md` — **distilled gotchas + pre-flight checklist for FUTURE client deploys** (read before deploying to any new client box, so we don't re-hit the Suffolk traps)
- `SUFFOLK-DEPLOY-PLAN.md` — the detailed step-by-step deploy runbook
- `ARCHITECTURE.md` — system architecture (trust split, tiers, brain)
- `DEPLOY-RUNBOOK.md`, `INSTALL.md`, `FIRST-RUN.md`, `HOSTINGER-DEPLOY.md` — general deploy docs

## Quality checks
`docker compose --env-file .env.example config` to validate compose; `bash -n` / `python3 -m py_compile` for scripts; `bash scripts/smoke-brain.sh` for brain retrieval.
