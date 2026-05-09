# SafeClaw AI Assistant

> A security-hardened, single-user personal AI assistant that reads your inboxes,
> learns your voice, drafts replies, and answers your team's questions — all
> running on your own infrastructure.

SafeClaw is self-hosted Docker Compose stack. It watches the inboxes and channels
you connect it to, surfaces what matters, drafts replies in your voice, and never
auto-sends without an approval gate. The architecture itself — not a prompt or a
content filter — is what defends against prompt-injection attacks.

---

## Table of Contents

- [The Six Security Tenets](#the-six-security-tenets)
- [Architecture: Template vs Instance](#architecture-template-vs-instance)
- [System Requirements](#system-requirements)
- [Quick Start](#quick-start)
- [Folder Map](#folder-map)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## The Six Security Tenets

1. **Broken trifecta** — No single agent context has all three of: private data,
   untrusted input, and exfiltration capability. The Reader reads raw input and
   writes structured observations only. The Actor reads observations and writes
   actions only.

2. **Credential vault** — Composio holds all OAuth tokens for Gmail, Drive,
   Slack, and any other connected toolkit. Agents reach those services through
   per-toolkit Composio MCP servers; refresh tokens never touch agent memory.

3. **No SQL, ever** — Agents access the task database through PostgREST only,
   using a scoped JWT. Raw Postgres is unreachable from agent containers.

4. **Egress allowlist** — On Linux/VPS deployments, iptables rules on the
   Docker network restrict outbound traffic to the providers you actually use.
   All other egress is dropped at the network layer, not the prompt layer.

5. **No auto-send by default** — `gmail.drafts.create` only. Every proposed
   send appears as a draft in Gmail and an approval card in your chat surface
   (Telegram in v1, Slack in v2). You approve before anything goes out.
   Auto-send unlocks only after a 30-day clean run with explicit operator sign-off.

6. **Injection resistance** — All untrusted content (email body, Slack
   messages, filenames) is wrapped in XML tags and treated as DATA. The system
   prompt explicitly classifies embedded instructions as injection attacks and
   routes them to the security category.

---

## Architecture: Template vs Instance

SafeClaw uses a **template → instance** model:

| | This repo (`ai-assistant`) | Your deployed instance |
|---|---|---|
| **Role** | **Upstream template** — generic code, Dockerfiles, schemas, scripts | **Customer instance** — your `.env`, real tokens, real channel IDs, your brain data |
| **What changes flow here** | Dockerfiles, entrypoints, schema migrations, compose services, scripts, system prompts | `.env`, `config/actor-hermes.yaml` (your Composio UUIDs), data volumes |
| **Git** | `github.com/Vasanth19/safeclaw.git` | Your local repo, tracking this one as `upstream` |

**How it works:**
- Deploy from this template once per customer (or per personal install).
- Clone the repo, copy `.env.example` to `.env`, fill in your real values, and run.
- Your instance-specific files (`.env`, `data/`, `brain/`) are `.gitignored` so they never leak upstream.
- Pull new template releases with `git fetch upstream && git merge upstream/main`.

See [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) for the phased rollout and
rollback procedures.

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 2 cores | 4+ cores |
| **RAM** | 4 GB | 8 GB |
| **Disk** | 20 GB SSD | 40 GB SSD (brain + attachments grow over time) |
| **OS** | Linux (Debian/Ubuntu), macOS (OrbStack), or Windows (WSL2) | Linux VPS (Hostinger, Hetzner, DigitalOcean) |
| **Docker** | Engine 24+ with Compose v2 | Latest stable |

### Required Accounts (free tiers suffice)

| Service | Why | Sign up |
|---------|-----|---------|
| **Composio** | OAuth vault + MCP broker for Gmail, Drive, Slack | [app.composio.dev](https://app.composio.dev) |
| **Telegram** | v1 control surface (DM the bot to approve drafts) | App on phone/desktop |
| **Slack** | v2 control surface + team channel summaries | [api.slack.com/apps](https://api.slack.com/apps) |
| **Ollama Cloud** | Default LLM backend ($20/mo) — or use Anthropic, OpenAI, vLLM | [ollama.com](https://ollama.com) |
| **Firecrawl** | Web search + extract (500 pages free, then $29/mo) | [firecrawl.dev](https://www.firecrawl.dev) |

---

## Quick Start

```bash
# 1. Clone the template
git clone https://github.com/Vasanth19/safeclaw.git safeclaw
cd safeclaw

# 2. Configure the environment
cp .env.example .env
# Edit .env — fill in every __FILL_IN__ value (Composio, Slack, Telegram, Firecrawl).
# Leave the __GENERATE__ lines for the next step.

# 3. Generate secrets (DB passwords, JWT, agent JWT)
bash scripts/init-secrets.sh

# 4. Start the stack
docker compose up -d

# 5. Verify the foundation
bash scripts/verify-stack.sh --phase 0

# 6. Bootstrap the brain (seeds PARA-style vault + 90 days of mail)
bash scripts/bootstrap-brain.sh

# 7. Chat with your assistant
#   Telegram: DM your bot
#   Slack: @mention SafeClaw in your home channel
```

For the full operator walkthrough (Composio MCP setup, Slack/Telegram bot creation,
day-2 commands) see **[FIRST-RUN.md](FIRST-RUN.md)**. For the phased rollout plan
see **[IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md)**. For deployment to a VPS
see **[HOSTINGER-DEPLOY.md](HOSTINGER-DEPLOY.md)** or **[DEPLOY-RUNBOOK.md](DEPLOY-RUNBOOK.md)**.

---

## Folder Map

```
ai-assistant/
├── docker-compose.yml          The whole stack, single command startup
├── .env.example                Required env vars, with placeholders + comments
├── ARCHITECTURE.md             Canonical architecture reference (broken trifecta, threat model)
├── FIRST-RUN.md                Step-by-step initial deploy guide
├── DEPLOY-RUNBOOK.md           Day-2 operations runbook
├── IMPLEMENTATION-PLAN.md      Phased rollout plan + rollback procedures
├── INSTALL.md                  Comprehensive installation & deployment reference
├── CUSTOMER-ONBOARDING.md      Friendly walkthrough for non-technical operators
├── brain/                      Human-readable PARA-style markdown layer
│                               (gitignored — seeded at install time by the
│                                bootstrap script)
│   ├── 0 - Identity/           soul.md + identity scaffolds
│   ├── 1 - Aspirations/        long-horizon goals
│   ├── 2 - Live Logs/          per-day activity log (auto-populated in v2)
│   ├── 3 - Daily Journal/      daily reflections
│   ├── 4 - Meetings/           per-meeting notes (auto-populated in v2)
│   ├── 5 - Projects/           one file per active project
│   ├── 6 - Areas/              ongoing responsibilities (not project-bounded)
│   ├── 7 - Resources/          reference material
│   ├── 9 - Operations/         routines, SOPs, checklists
│   ├── People/                 populated by scripts/bootstrap-brain.sh
│   └── Companies/              populated by scripts/bootstrap-brain.sh
├── config/
│   ├── reader-hermes.yaml      Read-only agent config + system prompt
│   ├── actor-hermes.yaml       Write agent config + scheduled automations
│   └── postgrest.conf          PostgREST connection + JWT config
├── db/
│   ├── 001_obs_schema.sql      Observation DB schema (safeclaw_obs)
│   ├── 002_task_schema.sql     Task DB schema + RLS policies (safeclaw_tasks)
│   └── 003_brain_schema.sql    Brain layer (entities, style samples, embeddings)
├── mcp-tools/
│   ├── brain-api/              Node MCP server exposing brain_recall / brain_write
│   ├── tasks-api/              Node MCP server wrapping PostgREST
│   ├── slack-api/              Native Slack MCP (channel history, list, send)
│   └── drive-api/              Service-account Google Drive uploads (Python)
├── scripts/
│   ├── bootstrap-brain.sh      First-run: backfills 90 days of Gmail history
│   ├── init-secrets.sh           Generates DB passwords, JWT, agent JWT
│   ├── verify-stack.sh          Phase-gated health checks
│   └── build-images.sh          Build and push Docker images to GHCR
├── services/
│   ├── embedder/               sentence-transformers HTTP server (CPU-only, 384-dim)
│   └── reflector/              Weekly cron — proposes Soul/preference updates
└── onboarding/                 Flask webapp for customer self-service install
```

---

## Documentation

| Doc | Who | What |
|-----|-----|------|
| **[FIRST-RUN.md](FIRST-RUN.md)** | New operators | From `git clone` to "the assistant is helping me" |
| **[INSTALL.md](INSTALL.md)** | DevOps / maintainers | Full install reference, gotchas, post-install ops |
| **[DEPLOY-RUNBOOK.md](DEPLOY-RUNBOOK.md)** | Operators | Day-2 commands: restart, backup, update, debug |
| **[HOSTINGER-DEPLOY.md](HOSTINGER-DEPLOY.md)** | VPS operators | Hostinger-specific VPS provisioning + Caddy setup |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Contributors | Threat model, data flow, security boundaries |
| **[IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md)** | Project leads | Phased rollout, rollback, feature gates |
| **[CUSTOMER-ONBOARDING.md](CUSTOMER-ONBOARDING.md)** | End users | Friendly "what is this and how do I use it" guide |
| **[docs/COMPOSIO-MCP-SETUP.md](docs/COMPOSIO-MCP-SETUP.md)** | All | Connecting Gmail, Drive, Slack via Composio |

---

## Contributing

SafeClaw welcomes contributions — security audits, bug fixes, new MCP tool integrations,
and documentation improvements.

### Before you start

1. **Understand the template/instance boundary.** Generic changes (Dockerfiles,
   schema migrations, scripts, system prompt patterns) belong in this upstream repo.
   Customer-specific values (real Slack channel IDs, real Composio UUIDs) belong
   only in your instance's `.env`.

2. **Never commit `.env` or `data/`.** These are `.gitignored` for a reason.

3. **Security first.** If your change touches credential handling, data flow,
   or agent boundaries, read [ARCHITECTURE.md](ARCHITECTURE.md) §5 first and
   open a discussion issue before submitting.

### How to contribute

```bash
# 1. Fork and clone
git clone https://github.com/YOURNAME/safeclaw.git
cd safeclaw

# 2. Create a branch
git checkout -b feat/your-feature-name

# 3. Make your change, commit, push
git commit -m "feat: description of what changed and why"
git push origin feat/your-feature-name

# 4. Open a Pull Request against main
```

### What we need help with

- Security audits of the broken-trifecta architecture
- Additional LLM provider integrations (vLLM, Groq, etc.)
- MCP toolkits beyond Composio (local OAuth flows, self-hosted alternatives)
- Better observability (metrics, structured logging, alerting)
- Documentation translations
- Windows/WSL2 deployment guides

---

## License

SafeClaw is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

```
Copyright (C) 2026 Vasanth S / Hyphen Labs

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.
```

**Why AGPL?** SafeClaw is a full application stack, not a library. AGPL ensures
that anyone who hosts SafeClaw as a service (even modified) must share their
changes back with the community. This protects contributors and keeps the
project aligned with its privacy-first, user-sovereign values.

If you need a commercial license exception (e.g., to embed SafeClaw in a
closed-source product), contact vasanth@hyphenlabs.com.

---

**Built with care by [Hyphen Labs](https://hyphenlabs.com).**
