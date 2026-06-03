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
│   └── dist/index.js     UI bundle (IIFE on the Hermes Plugin SDK) — verbatim copy of src (no npm imports)
└── src/index.js          UI source → `cp src/index.js dashboard/dist/index.js` (or esbuild --minify)
```

## Install (native Hermes)

```bash
./dashboard-plugins/safeclaw-connections/build.sh   # src → dist/index.js (gitignored)
ln -s "$PWD/dashboard-plugins/safeclaw-connections" ~/.hermes/plugins/safeclaw-connections
# restart the Hermes web dashboard — a "Connections" tab appears after Personas
```

## Configuration (env)

| Var | Default | Purpose |
|-----|---------|---------|
| `SAFECLAW_CONNECTIONS_DIR` | `~/.hermes/connections` | where connection YAMLs live |
| `COMPOSIO_API_KEY` | — | **server-side only**; required for in-dashboard OAuth onboarding. Never sent to the browser. |
| `COMPOSIO_USER_ID` | — | the per-client Composio user the new connected account is owned by (same id the MCP servers send as `x-composio-user-id`) |
| `COMPOSIO_AUTHCONFIG_GMAIL` | — | *optional*; a pre-created Composio auth config id to mint Gmail links against. If unset, a managed-auth config is created from the toolkit slug. |

## API

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | reachability + registry dir |
| GET | `/providers` | catalog: providers × boundaries × derived scope; `supports_oauth_link` per provider |
| GET | `/connections` | all connections, hydrated with locked scope + mcp server name |
| GET | `/connections/{id}` | one connection + its computed `mcp_snippet` |
| POST | `/connections` | create — **422** on `scope: send`/`tools`/`mcp_servers`; **409** on duplicate single-account provider |
| DELETE | `/connections/{id}` | remove |
| GET | `/render` | dry-run: the `mcp_servers` entries (per boundary) + env vars the render step will inject |
| POST | `/connect-link` | **OAuth onboarding** — mint a fresh Composio OAuth link for `{provider, agent, label}`; returns `{redirect_url, connected_account_id, status}`. Scope is still derived; **422** for non-Composio providers or invalid bindings. |
| GET | `/connect-status?connected_account_id=…` | poll a connected account until `ACTIVE`; returns `{status, active}` |

## In-dashboard OAuth onboarding (on-box)

Replaces the old standalone Netlify "connect your accounts" page — the whole
flow now lives behind the **loopback dashboard** so nothing about onboarding
leaves the Orgo box. The operator (or the client, via the authenticated tunnel
/ orgo desktop) clicks **Connect with OAuth** on a Composio provider:

```
Connect → POST /connect-link → redirect_url opens at the provider (Google)
        → user approves → poll /connect-status until ACTIVE
        → POST /connections (scope LOCKED by boundary) → mcp snippet ready
```

Why this is *more* secure than the public page it replaces:

- `COMPOSIO_API_KEY` is read from the dashboard env and **never** reaches the
  browser — the client only receives the provider's `redirect_url`.
- There is **no public endpoint** that mints OAuth links; the minter is
  loopback-only.
- The link binds to `(provider, agent)` and the scope is **derived**, so an
  OAuth link can never request more than its trust boundary allows.

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
