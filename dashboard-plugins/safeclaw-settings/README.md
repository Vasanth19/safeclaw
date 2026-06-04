# SafeClaw Settings — dashboard plugin

The single **Settings** tab that consolidates the operator's manual onboarding
steps into one screen, so finishing a client install is: open Settings → confirm
the checklist is green → share the **handoff URL** → the customer opens it and
clicks each connector on the **Connections** tab.

## The one rule

> **Status-only.** It reports whether each piece of config is present and
> whether each service is alive — it **never** returns a secret value. Composio
> keys, MCP URLs, and the dashboard password are reported as booleans, not
> echoed. The single exception is the **handoff URL**, which by design embeds
> the access credential so it is one-click — and only when the operator has
> supplied a plaintext access password (the box otherwise stores only a bcrypt
> hash, so we return the host + a reason instead of fabricating a URL).

The **org-level Composio key is never on this surface** (or on the box at all):
project creation runs operator-side via `scripts/provision-composio.py`, which
writes only the per-client **project key** + MCP URLs here.

## What it consolidates

| Section | Source | Shows |
|---------|--------|-------|
| Setup checklist | `GET /checklist` | every onboarding gate with a derived done/pending dot |
| Composio & brain | `GET /status` | project key set? · reader/actor MCP wired? · GBrain alive? · #accounts connected |
| Client handoff link | `GET /access` | the one-click `https://user:pass@host/connections` link (or host + reason) |

## API

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | reachability |
| GET | `/status` | booleans + counts only — composio readiness, brain alive, connection count |
| GET | `/access` | handoff URL (credential-embedded, deep-linked to `/connections`) **only** if a plaintext access password is set; else `host_url` + `reason` |
| GET | `/checklist` | all manual-step gates with derived done/pending + `done/total` |

## Configuration (env — all read, never written/echoed)

| Var | Purpose |
|-----|---------|
| `COMPOSIO_API_KEY` · `COMPOSIO_USER_ID` · `COMPOSIO_READER_MCP_URL` · `COMPOSIO_ACTOR_MCP_URL` | per-client Composio readiness (written by `provision-composio.py`) |
| `CLIENT_NAME` | client slug shown in the header |
| `PUBLIC_HOSTNAME` (or `HERMES_PUBLIC_HOSTNAME`) | the public dashboard host for the handoff URL |
| `DASHBOARD_AUTH_USER` (or `SAFECLAW_UI_USER`) | handoff URL username |
| `DASHBOARD_AUTH_PASSWORD` (or `UI_PASSWORD`) | **optional** plaintext access password — only set this if you want the tab to build the one-click URL; otherwise share the URL recorded at install |
| `GBRAIN_HTTP_URL` | brain probe target (default `http://127.0.0.1:3131/mcp`) |

## Install (native Hermes)

```bash
./dashboard-plugins/safeclaw-settings/build.sh   # src → dist/index.js (gitignored)
ln -s "$PWD/dashboard-plugins/safeclaw-settings" ~/.hermes/plugins/safeclaw-settings
# restart the Hermes web dashboard — a "Settings" tab appears after Connections
```

## Layout

```
safeclaw-settings/
├── build.sh              src → dist/index.js (pure-SDK copy, or esbuild --minify)
├── dashboard/
│   ├── manifest.json     tab at /settings, after Connections
│   ├── plugin_api.py     FastAPI router → /api/plugins/safeclaw-settings/
│   └── dist/index.js     UI bundle (gitignored; run build.sh)
├── src/index.js          UI source
└── tests/                pytest (status-only contract + handoff URL builder)
```
