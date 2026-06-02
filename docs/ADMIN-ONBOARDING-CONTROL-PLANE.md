# Admin Onboarding Control Plane

Status: branch now includes the admin spec, Matt Hoover OAuth onboarding source, and the Marcus v2 dashboard handoff artifacts
Branch: `feat/admin-onboarding-oauth-dashboard`

## Goal

Turn SafeClaw from a client-operated self-hosted setup into an agency-operated onboarding and maintenance system.

The target experience:

1. An employee logs into the administrator Hermes agent on the agency ops computer.
2. The employee says: "Create a client install for Acme."
3. The admin agent provisions or updates the client infrastructure.
4. The client only approves OAuth/connect links and installs the agency-managed Slack app.
5. The admin agent verifies health and stores the resulting client registry entry.

Clients should not need to create Slack apps, paste raw tokens into forms, manage `.env` files, or understand Composio MCP server URLs.

## Non-goals

- Do not preserve SafeClaw as a heavy proprietary runtime if normal Hermes + G-Brain can provide the same behavior.
- Do not ask clients to create Slack apps.
- Do not ask clients for Composio API keys.
- Do not place agency-level Orgo or Composio credentials inside client installs.
- Do not merge the Reader and Actor trust boundary for convenience.

## Recommended architecture

### 1. Agency admin agent

A single administrator Hermes instance runs on the agency ops box, for example `jake-main-agent`.

It owns operational capabilities:

- Orgo workspace/computer operations.
- Client registry management.
- Composio project creation and connection checks.
- Install/update/health commands for client computers.
- G-Brain bootstrap and maintenance scripts.
- Employee-facing runbooks and skills.

The admin agent may hold agency-level credentials through the host secret store or environment. Those credentials must never be copied into client installs.

### 2. Client install

Each client gets a standard install package:

- Normal Hermes runtime.
- G-Brain-backed memory.
- Reader profile or process.
- Actor profile or process.
- Client-scoped Composio Project API key.
- Client-scoped OAuth connected accounts.
- Health check script.
- Bootstrap report in the client brain.

### 3. Reader / Actor trust split

Keep SafeClaw's most important security property, but implement it as a standard profile/config pattern.

Reader:

- Can read untrusted Gmail/Slack data through read-only tool allowlists.
- Can write structured observations to G-Brain.
- Cannot send email, post Slack messages, upload to arbitrary external URLs, or call actor tools.

Actor:

- Can query G-Brain and draft/post only through explicit approved tool paths.
- Cannot fetch raw inbound email or raw Slack history.
- Must create drafts by default; sends require explicit human approval.

The boundary must be enforced by tool availability/MCP allowlists, not by prompts alone.

### 4. Composio project-per-client

The agency owns the Composio organization. Every client install receives its own Composio Project.

For each client:

- Create or select a project.
- Create/read auth configs.
- Generate OAuth connect links for Gmail, Drive, Calendar, Slack, etc.
- Poll connection status until authorized.
- Generate Reader and Actor MCP servers with separate allowlists.
- Store only the client Project API key in the client install.

The agency/org-level token stays on the admin agent only.

### 5. Slack gateway

Use one agency-managed Slack app.

A central gateway receives Slack events, verifies signatures, reads `team_id`, and routes the event to the matching client install.

Mapping shape:

```json
{
  "team_id": "T0123456789",
  "client_slug": "acme",
  "orgo_computer_id": "...",
  "client_brain_slug": "clients/acme",
  "status": "active"
}
```

This avoids requiring every client to create a separate Slack app.

## Client registry

The admin agent needs a source-of-truth client registry. Initial implementation can be a JSON/YAML file, later migrated to G-Brain or a small database.

Suggested fields:

```yaml
clients:
  acme:
    display_name: Acme Co
    status: active
    orgo:
      workspace_id: null
      computer_id: null
      computer_name: acme-agent
    composio:
      project_id: null
      project_key_secret_ref: null
      user_id: null
      reader_mcp_url_secret_ref: null
      actor_mcp_url_secret_ref: null
    slack:
      team_id: null
      enterprise_id: null
      home_channel_id: null
      admin_user_ids: []
    brain:
      base_url: null
      health_url: null
    install:
      version: null
      last_health_check_at: null
      last_bootstrap_at: null
```

Secret values should be referenced by secret-store paths, not stored directly in the registry.

## Onboarding flow

### Phase A: Employee starts onboarding

Employee command to admin agent:

> Create a new client install for Acme. Primary admin is alice@example.com. They need Gmail, Drive, Slack, and Calendar.

Admin agent:

1. Normalizes `client_slug`.
2. Creates registry draft.
3. Creates Orgo computer or selects existing one.
4. Installs normal Hermes + G-Brain package.
5. Creates Composio Project.
6. Creates OAuth connection links or a dynamic setup page backed by server-side link creation.
7. Sends the setup page or links to the employee for client delivery.

Current Matt Hoover source is captured at `admin/client-onboarding/matt-hoover/`. It includes Google Calendar, Gmail, Google Docs, Google Sheets, and Google Tasks. Personal WhatsApp is intentionally excluded: Composio's WhatsApp connector is for WhatsApp Business, so it is not a useful onboarding target unless the client operates a WhatsApp Business account.

### Phase B: Client approves OAuth

Client clicks hosted links only. No developer dashboards.

Admin agent:

1. Polls connection status.
2. Confirms connected accounts.
3. Creates Reader/Actor MCP servers.
4. Writes client-scoped config onto the client computer.
5. Runs smoke checks.

### Phase C: Brain bootstrap

Admin agent runs:

1. Gmail/Slack backfill through Reader tools.
2. People page creation.
3. Company page creation.
4. Project/observation pages.
5. Style samples from sent mail if allowed.
6. Fact extraction.
7. Bootstrap report.

### Phase D: Slack activation

Admin agent:

1. Confirms Slack app installed.
2. Records `team_id` in registry.
3. Configures gateway route.
4. Sends a test DM/channel message.
5. Confirms approval gates.

### Phase E: Maintenance mode

Admin agent schedules recurring checks:

- Orgo computer reachable.
- Hermes doctor.
- G-Brain health.
- Composio connection health.
- Slack gateway route health.
- Last successful reader ingestion.
- Last successful actor response.
- Disk/memory/CPU pressure.

## First implementation slice

Build the smallest useful version in this branch:

1. Add client registry schema and sample file.
2. Add admin-agent onboarding runbook.
3. Add Orgo `/bash` execution helper.
4. Add client install bootstrap script for normal Hermes + G-Brain.
5. Add health check script.
6. Add Composio project-per-client checklist or helper.
7. Keep SafeClaw Reader/Actor config as templates, renamed to generic client profiles.

## Open questions

- Where should the production client registry live: G-Brain page, Git-backed YAML, SQLite, or Cloudflare D1?
- Should the Slack gateway be Cloudflare Worker/D1 from day one?
- Should client installs run one Hermes instance with profiles, or two separate Hermes processes?
- Which G-Brain deployment mode is best for Orgo: local Postgres service, PGLite, or remote managed Postgres?
- How should employees authenticate into the admin agent: Orgo desktop login, Hermes gateway, Slack admin channel, or all three?

## Decision so far

Use SafeClaw as the source of architectural patterns, not as the long-term forked runtime. The durable product should be an admin-controlled generic Hermes + G-Brain client install system that preserves SafeClaw's reader/actor safety boundary and memory bootstrap flow.
