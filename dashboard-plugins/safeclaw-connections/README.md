# SafeClaw Connections — dashboard plugin

A Hermes dashboard plugin to wire up and manage SafeClaw's integrations —
**Gmail (one or many accounts)**, **Slack**, **Telegram**, **Google Drive** —
from the dashboard instead of hand-editing YAML. This is the "configure
Slack / Telegram / Gmail / GDrive" surface, including **multiple Gmail
accounts**.

## The one rule that keeps it secure

> A connection binds to one trust boundary and gets **only that boundary's
> scope**. It can never grant a send/exfiltration tool.

| Boundary | Scope a connection gets |
|----------|-------------------------|
| **Reader** | `read` — intake only; cannot send, draft, post, delete |
| **Actor**  | `draft` — drafts + uploads; **never** raw send |

Scope is **derived** from `(provider, agent)` server-side — never accepted from
the client. Any payload carrying `scope: send` (or `admin`/`delete`), a raw
`tools:` field, or a raw `mcp_servers:` field is rejected with **HTTP 422**
(`_reject_capability_escalation`). Adding a second Gmail to the Actor gives it
another *draft* mailbox — not a send tool. This is the same broken-trifecta
defense the `safeclaw-personas` plugin enforces.

## What it writes (and what it does NOT)

It owns a **connections registry** only — one YAML file per connection under
`SAFECLAW_CONNECTIONS_DIR` (default `~/.hermes/connections`). It **never**
rewrites the hand-tuned `config/{reader,actor}-hermes.yaml` (those carry
comments + YAML anchors a round-trip dump would destroy). Instead it computes
the `mcp_servers` snippet each connection implies; the render step injects them
non-destructively at provision time.

```
connection (registry YAML)  ──►  _mcp_snippet()  ──►  scripts/render-hermes-config.py
                                                        └─ injects into deployed config.yaml
```

## Provider catalog

| Provider | Backend | Multi-account | Boundaries (scope) |
|----------|---------|---------------|--------------------|
| Gmail | Composio MCP | ✅ yes | reader (read) · actor (draft) |
| Slack | native node MCP | no | reader (read) · actor (draft) |
| Telegram | Hermes gateway | no | actor (chat) |
| Google Drive | local drive-api MCP | no | actor (draft) |

## Layout

```
safeclaw-connections/
├── dashboard/
│   ├── manifest.json     plugin manifest (tab at /connections, after Personas)
│   ├── plugin_api.py     FastAPI router → /api/plugins/safeclaw-connections/
│   └── dist/index.js     UI bundle (IIFE on the Hermes Plugin SDK) — BUILD PENDING
└── src/index.js          UI source (bundle with esbuild → dashboard/dist/index.js)
```

## Install (native Hermes)

```bash
ln -s "$PWD/dashboard-plugins/safeclaw-connections" ~/.hermes/plugins/safeclaw-connections
# restart the Hermes web dashboard — a "Connections" tab appears after Personas
```

## Configuration (env)

| Var | Default | Purpose |
|-----|---------|---------|
| `SAFECLAW_CONNECTIONS_DIR` | `~/.hermes/connections` | where connection YAMLs live |

## API

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | reachability + registry dir |
| GET | `/providers` | catalog: providers × boundaries × derived scope |
| GET | `/connections` | all connections, hydrated with locked scope + mcp server name |
| GET | `/connections/{id}` | one connection + its computed `mcp_snippet` |
| POST | `/connections` | create — **422** on `scope: send`/`tools`/`mcp_servers`; **409** on duplicate single-account provider |
| DELETE | `/connections/{id}` | remove |
| GET | `/render` | dry-run: the `mcp_servers` entries (per boundary) + env vars the render step will inject |

## Example: connect a second Gmail to the Actor (draft-only)

```bash
curl -X POST localhost:9119/api/plugins/safeclaw-connections/connections \
  -H 'content-type: application/json' \
  -d '{"id":"gmail-hyphenlabs","provider":"gmail","agent":"actor",
       "label":"hyphenlabs","composio_account_id":"ca_abc123",
       "display_name":"hyphenlabs.com inbox"}'
```

Yields a registry entry whose `_mcp_snippet` is:

```yaml
gmail_hyphenlabs:
  url: "${COMPOSIO_ACTOR_MCP_URL}&connected_account_id=${GMAIL_HYPHENLABS_ACCOUNT_ID}"
  headers:
    x-api-key: "${COMPOSIO_API_KEY}"
    x-composio-user-id: "${COMPOSIO_USER_ID}"
  timeout: 120
  connect_timeout: 30
```

`render-hermes-config.py` injects that under the Actor's `mcp_servers:` and
sets `GMAIL_HYPHENLABS_ACCOUNT_ID=ca_abc123` in `client.env`. The Actor now has
a second draft mailbox — and still no send tool.
