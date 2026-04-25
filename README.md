# SafeClaw AI Assistant

Secure second-brain assistant for Rocking Spur Homes, LLC. Monitors three Gmail inboxes,
Google Drive, and Slack — surfaces critical items to Jake McKinney without ever holding
credentials or auto-sending email.

---

## The Six Security Tenets

1. **Broken trifecta** — No single agent context has all three of: private data, untrusted
   input, and exfiltration capability. Reader reads raw input and writes observations only.
   Actor reads observations and writes actions only.

2. **Credential vault** — Nango holds all OAuth tokens. Agents receive short-lived access
   tokens per request. No refresh tokens ever touch agent memory.

3. **No SQL, ever** — Agents access the task database through PostgREST only, using a
   scoped JWT. Raw Postgres is unreachable from agent containers.

4. **Egress allowlist** — iptables rules on the Docker network allow only
   `*.googleapis.com`, `*.slack.com`, and internal container traffic. All other egress is
   dropped at the network layer, not the prompt layer.

5. **No auto-send (Phase 1-3)** — `gmail.drafts.create` only. Every proposed send appears
   as a draft in Gmail and a card in `#safeclaw-review`. Jake approves before anything
   goes out.

6. **Injection resistance** — All untrusted content (email body, Slack messages, filenames)
   is wrapped in XML tags and treated as DATA. The system prompt explicitly classifies
   embedded instructions as injection attacks and routes them to the security category.

---

## Folder Map

```
ai-assistant/
├── docker-compose.yml          All 7 services, single command startup
├── .env.example                All required env vars with comments
├── config/
│   ├── reader-hermes.yaml      Read-only agent config + system prompt
│   ├── actor-hermes.yaml       Write agent config + scheduled automations
│   ├── postgrest.conf          PostgREST connection + JWT config
│   └── nango.yaml              OAuth integration definitions
├── db/
│   ├── 001_obs_schema.sql      Observation DB schema (safeclaw_obs)
│   └── 002_task_schema.sql     Task DB schema + RLS policies (safeclaw_tasks)
├── mcp-tools/tasks-api/        Node.js MCP server wrapping PostgREST
│   └── src/index.ts            4 tools: create_task, add_comment, update_status, list_my_open
├── scripts/
│   ├── setup-oauth.sh          Interactive OAuth walkthrough (run once after stack start)
│   └── verify-stack.sh         Phase-gated health checks
├── mcp-servers/
│   └── REVIEWED-MCP-SERVERS.md Curated MCP server list + OSV guidance
└── DEPLOY-RUNBOOK.md           Full operator guide
```

---

## Quick Start (3 commands)

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — fill in all required values (see DEPLOY-RUNBOOK.md §Environment Variables)

# 2. Start the stack
docker compose up -d

# 3. Verify foundation
bash scripts/verify-stack.sh --phase 0
```

After Phase 0 passes, run `bash scripts/setup-oauth.sh` to complete OAuth authorization,
then proceed through the phases in `IMPLEMENTATION-PLAN.md`.
