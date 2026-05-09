# SafeClaw AI Assistant

A security-hardened, single-user personal AI assistant. SafeClaw watches the
inboxes and channels you connect it to, surfaces what matters, drafts replies
in your voice — and never auto-sends without an approval gate. The architecture
itself, not a prompt or a content filter, is what defends against prompt-injection
attacks.

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
   (Telegram in v1). You approve before anything goes out. Auto-send unlocks
   only after a 30-day clean run with explicit operator sign-off.

6. **Injection resistance** — All untrusted content (email body, Slack
   messages, filenames) is wrapped in XML tags and treated as DATA. The system
   prompt explicitly classifies embedded instructions as injection attacks and
   routes them to the security category.

---

## Folder Map

```
ai-assistant/
├── docker-compose.yml          The whole stack, single command startup
├── .env.example                Required env vars, with placeholders + comments
├── ARCHITECTURE.md             Canonical architecture reference
├── FIRST-RUN.md                Step-by-step initial deploy guide
├── DEPLOY-RUNBOOK.md           Day-2 operations runbook
├── IMPLEMENTATION-PLAN.md      Phased rollout plan + rollback procedures
├── brain/                      Human-readable PARA-style markdown layer
│                               (gitignored — cloned at install time from the
│                                Evolving Brain Template by Samin Yasar, MIT;
│                                github.com/Samin12/Evolving-Brain-Template)
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
│   ├── tasks-api/              Node MCP server wrapping PostgREST
│   └── brain-api/              Node MCP server exposing brain_recall / brain_write
├── scripts/
│   ├── bootstrap-brain.sh      First-run: backfills 90 days of Gmail history
│   └── verify-stack.sh         Phase-gated health checks
├── services/
│   ├── embedder/               sentence-transformers HTTP server (CPU-only)
│   └── reflector/              Weekly cron — proposes Soul/preference updates
└── mcp-servers/
    └── REVIEWED-MCP-SERVERS.md (superseded by Composio MCP — see ARCHITECTURE.md)
```

---

## Quick Start

```bash
# 1. Configure the environment
cp .env.example .env
# Edit .env — fill in every __FILL_IN__ value (Composio + Telegram).
# Leave the __GENERATE__ lines for the next step.

# 2. Generate secrets (DB passwords, JWT, agent JWT)
bash scripts/init-secrets.sh

# 3. Start the stack
docker compose up -d

# 4. Verify the foundation
bash scripts/verify-stack.sh --phase 0

# 5. Bootstrap the brain (clones the Evolving Brain Template + 90 days of mail)
bash scripts/bootstrap-brain.sh
```

For the full operator walkthrough (Composio MCP setup, Telegram bot creation,
day-2 commands) see **FIRST-RUN.md**. For the phased rollout plan see
**IMPLEMENTATION-PLAN.md**.
