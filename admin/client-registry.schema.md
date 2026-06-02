# Client Registry Schema

The admin agent uses this registry to know which Orgo computer, Composio project, Slack workspace, and brain belong to each client install.

Secret fields must store secret references, not raw secret values.

## YAML shape

```yaml
version: 1
clients:
  client_slug:
    display_name: Client Display Name
    status: planned | provisioning | active | paused | offboarding | archived
    owner:
      agency_admin: employee-name-or-id
      client_primary_email: person@example.com
    orgo:
      workspace_id: null
      computer_id: null
      computer_name: null
    composio:
      project_id: null
      project_key_secret_ref: null
      user_id: null
      reader_mcp_url_secret_ref: null
      actor_mcp_url_secret_ref: null
      onboarding_page_url: null
      onboarding_template_source: admin/client-onboarding/matt-hoover
      connected_accounts:
        gmail: pending | connected | failed | not_required
        drive: pending | connected | failed | not_required
        calendar: pending | connected | failed | not_required
        slack: pending | connected | failed | not_required
    slack:
      team_id: null
      enterprise_id: null
      home_channel_id: null
      admin_user_ids: []
      gateway_route_status: pending | active | failed | not_required
    brain:
      base_url: null
      health_url: null
      reader_token_secret_ref: null
      actor_token_secret_ref: null
      source_id: null
    install:
      runtime: hermes-gbrain
      version: null
      branch: null
      installed_at: null
      last_health_check_at: null
      last_bootstrap_at: null
      notes: null
```

## Status meanings

- `planned`: registry entry exists, no infrastructure yet.
- `provisioning`: admin agent is actively creating/installing.
- `active`: client is live and monitored.
- `paused`: client intentionally inactive, not offboarded.
- `offboarding`: revoke access, archive memory, remove compute.
- `archived`: no active infrastructure; historical record only.
