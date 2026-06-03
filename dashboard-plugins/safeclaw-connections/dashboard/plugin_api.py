"""SafeClaw Connections — dashboard plugin backend.

Mounted at /api/plugins/safeclaw-connections/ by the Hermes dashboard plugin
system. This is the "system on top of Hermes" that lets an operator wire up the
assistant's integrations — Gmail (one or many accounts), Slack, Telegram,
Google Drive — from the dashboard instead of hand-editing YAML.

────────────────────────────────────────────────────────────────────────────
The security contract (identical in spirit to safeclaw-personas)
────────────────────────────────────────────────────────────────────────────
A *connection* binds to exactly one **trust boundary** — the SafeClaw Reader or
the SafeClaw Actor — and is granted ONLY that boundary's scope:

    Reader connection  → READ-only  (intake; cannot send/draft/post/delete)
    Actor  connection  → DRAFT-only (drafts + uploads; never raw send)

The scope is DERIVED from (provider, agent). It is never accepted from the
client. Any inbound `scope: send`, `tools:`, or `mcp_servers:` field is
REJECTED with HTTP 422 — a connection can never reunite the lethal trifecta
(private data + untrusted input + exfiltration) that the Reader/Actor split
exists to break. Adding a second Gmail to the Actor grants another *draft*
mailbox, never a send tool.

────────────────────────────────────────────────────────────────────────────
What this plugin writes (and does NOT write)
────────────────────────────────────────────────────────────────────────────
It owns a connections REGISTRY only: one YAML file per connection under
SAFECLAW_CONNECTIONS_DIR (default ~/.hermes/connections). It NEVER rewrites the
hand-tuned, security-critical agent configs (config/{reader,actor}-hermes.yaml)
— those carry comments + YAML anchors that a round-trip dump would destroy.
Instead it computes the MCP-server snippet each connection implies; the render
step (scripts/render-hermes-config.py, run at provision time) injects those
snippets non-destructively into the deployed config.yaml.

Storage:  SAFECLAW_CONNECTIONS_DIR (default ~/.hermes/connections), one *.yaml each.
Truth:    provider catalog below decides which agents a provider may bind to
          and what scope each binding grants.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

# ── Trust boundaries ─────────────────────────────────────────────────────────
# Mirrors safeclaw-personas. A connection binds to one of these and inherits
# its posture. Kept in sync deliberately — same two agents, same guarantees.
AGENTS: dict[str, dict[str, str]] = {
    "reader": {
        "label": "Reader",
        "config": "reader-hermes.yaml",
        "trust": "Reads untrusted input (email, Slack). Read-only — cannot "
                 "send, draft, post, or delete.",
        "badge": "read-only",
    },
    "actor": {
        "label": "Actor",
        "config": "actor-hermes.yaml",
        "trust": "Drafts and uploads on your behalf. Draft-only by default; "
                 "every send is gated by your approval.",
        "badge": "draft only",
    },
}

# ── Provider catalog ─────────────────────────────────────────────────────────
# The ground truth for what can be connected and how it binds. For each provider
# we declare which agent boundaries it may attach to and the scope each binding
# grants. `scope` here is the ONLY scope a binding can ever have — it is derived,
# not client-supplied. There is intentionally no "send" scope anywhere.
#
# backend:
#   composio  → an HTTP MCP server pointed at a Composio connected account
#   native    → the baked-in slack-api node MCP (mode read|actor)
#   gateway   → a Hermes platform gateway (token in env, not an MCP server)
#   drive_api → the local drive-api python MCP (service account, draft/upload)
PROVIDERS: dict[str, dict[str, Any]] = {
    "gmail": {
        "label": "Gmail",
        "backend": "composio",
        "multi": True,  # multiple accounts allowed — this is the multi-Gmail story
        "bindings": {
            "reader": {"scope": "read", "mcp_prefix": "gmail"},
            "actor": {"scope": "draft", "mcp_prefix": "gmail"},
        },
        "needs_account_id": True,
        # ── OAuth onboarding (in-dashboard, on-box) ──────────────────────────
        # toolkit_slug + auth_config_env let the operator mint a fresh Composio
        # OAuth link from the dashboard itself (POST /connect-link) instead of
        # creating the connected account in Composio's external console and
        # pasting the ca_… id by hand. auth_config_env names the env var that
        # holds a pre-created Composio auth config id; if it is unset we fall
        # back to Composio managed auth via toolkit_slug. The COMPOSIO_API_KEY
        # never leaves the server — only the redirect_url is handed to the UI.
        "toolkit_slug": "gmail",
        "auth_config_env": "COMPOSIO_AUTHCONFIG_GMAIL",
    },
    "slack": {
        "label": "Slack",
        "backend": "native",
        "multi": False,
        "bindings": {
            "reader": {"scope": "read", "mcp_prefix": "slack_native"},
            "actor": {"scope": "draft", "mcp_prefix": "slack_native"},
        },
        "needs_account_id": False,
    },
    "telegram": {
        "label": "Telegram",
        "backend": "gateway",
        "multi": False,
        "bindings": {
            # Telegram is a chat surface for the Actor, not a data source.
            "actor": {"scope": "chat", "mcp_prefix": None},
        },
        "needs_account_id": False,
    },
    "gdrive": {
        "label": "Google Drive",
        "backend": "drive_api",
        "multi": False,
        "bindings": {
            "actor": {"scope": "draft", "mcp_prefix": "drive_api"},
        },
        "needs_account_id": False,
    },
}

# A scope value a client must never be able to assign. Belt-and-suspenders on
# top of "scope is derived" — if any of these slip into a payload, hard 422.
FORBIDDEN_SCOPES = {"send", "admin", "delete", "exfiltrate"}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,32}$")


def _connections_dir() -> Path:
    d = Path(os.environ.get(
        "SAFECLAW_CONNECTIONS_DIR",
        Path.home() / ".hermes" / "connections",
    )).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _conn_path(conn_id: str) -> Path:
    if not ID_RE.match(conn_id):
        raise HTTPException(400, f"invalid connection id: {conn_id!r}")
    return _connections_dir() / f"{conn_id}.yaml"


def _derive_scope(provider: str, agent: str) -> str:
    """Resolve the ONLY scope a (provider, agent) binding may have.

    Raises if the provider can't bind to that agent at all. This — not any
    client input — is the single source of truth for a connection's capability.
    """
    pmeta = PROVIDERS.get(provider)
    if not pmeta:
        raise HTTPException(422, f"unknown provider: {provider!r}; "
                                 f"one of {sorted(PROVIDERS)}")
    binding = pmeta["bindings"].get(agent)
    if not binding:
        allowed = sorted(pmeta["bindings"])
        raise HTTPException(
            422,
            f"provider {provider!r} cannot bind to {agent!r}. Allowed "
            f"boundaries for {provider!r}: {allowed}.",
        )
    return binding["scope"]


def _reject_capability_escalation(payload: dict[str, Any]) -> None:
    """The most important guard in this plugin — mirrors safeclaw-personas.

    A connection may never carry raw tools, raw mcp_servers, or a privileged
    scope. Scope is derived server-side; tools are inherited from the boundary.
    """
    if "tools" in payload or "mcp_servers" in payload:
        raise HTTPException(
            422,
            "A connection cannot declare its own tools or mcp_servers. "
            "Capabilities are inherited from the bound trust boundary "
            "(Reader=read-only, Actor=draft-only). If this integration "
            "genuinely needs a new capability, that is a change to the agent "
            "config + a re-validation of the security split — not a connection.",
        )
    scope = str(payload.get("scope", "")).lower()
    if scope in FORBIDDEN_SCOPES:
        raise HTTPException(
            422,
            f"scope {scope!r} is forbidden. A connection's scope is derived "
            f"from its boundary and is at most 'draft'. SafeClaw never grants "
            f"a connection raw send/admin/delete capability.",
        )


def _mcp_server_name(provider: str, agent: str, label: str) -> str | None:
    """The mcp_servers key this connection contributes, or None (gateway)."""
    binding = PROVIDERS[provider]["bindings"][agent]
    prefix = binding["mcp_prefix"]
    if prefix is None:
        return None
    if PROVIDERS[provider]["multi"]:
        return f"{prefix}_{label}"
    return prefix


def _env_var_name(provider: str, label: str) -> str | None:
    """The per-connection env var the render step + provisioner must set."""
    if provider == "gmail":
        return f"GMAIL_{label.upper().replace('-', '_')}_ACCOUNT_ID"
    return None


def _mcp_snippet(conn: dict[str, Any]) -> dict[str, Any] | None:
    """Compute the mcp_servers entry this connection implies.

    Returns a single-key dict {server_name: {...}} ready to be merged into the
    bound agent's config by the render step — or None for gateway providers
    (Telegram) which are configured via env, not an MCP server.
    """
    provider, agent, label = conn["provider"], conn["agent"], conn["label"]
    name = _mcp_server_name(provider, agent, label)
    if name is None:
        return None

    backend = PROVIDERS[provider]["backend"]
    if backend == "composio":
        # Reader uses the read-only Composio MCP URL; Actor the draft URL.
        url_var = ("${COMPOSIO_READER_MCP_URL}" if agent == "reader"
                   else "${COMPOSIO_ACTOR_MCP_URL}")
        env_var = _env_var_name(provider, label)
        return {name: {
            "url": f"{url_var}&connected_account_id=${{{env_var}}}",
            "headers": {
                "x-api-key": "${COMPOSIO_API_KEY}",
                "x-composio-user-id": "${COMPOSIO_USER_ID}",
            },
            "timeout": 120,
            "connect_timeout": 30,
        }}
    if backend == "native":  # slack-api node MCP, mode follows the boundary
        mode = "reader" if agent == "reader" else "actor"
        token_var = ("${SLACK_MCP_BOT_TOKEN}" if agent == "reader"
                     else "${SLACK_BOT_TOKEN}")
        return {name: {
            "command": "node",
            "args": ["/opt/mcp-tools/slack-api/dist/index.js"],
            "env": {"SLACK_BOT_TOKEN": token_var, "SLACK_MCP_MODE": mode},
            "timeout": 30,
            "connect_timeout": 10,
        }}
    if backend == "drive_api":  # local service-account drive MCP (upload/draft)
        return {name: {
            "command": "/opt/mcp-tools/drive-api/.venv/bin/python",
            "args": ["/opt/mcp-tools/drive-api/main.py"],
            "env": {"GDRIVE_CREDENTIALS_PATH": "/opt/config/drive_credentials.json"},
            "timeout": 60,
            "connect_timeout": 15,
        }}
    return None


def _hydrate(conn: dict[str, Any]) -> dict[str, Any]:
    """Attach derived, read-only security context for the UI."""
    provider, agent = conn.get("provider"), conn.get("agent")
    ameta = AGENTS.get(agent, {})
    pmeta = PROVIDERS.get(provider, {})
    return {
        **conn,
        "provider_label": pmeta.get("label", provider),
        "agent_label": ameta.get("label", agent),
        "agent_trust": ameta.get("trust", ""),
        "agent_badge": ameta.get("badge", ""),
        "scope_locked": True,  # UI renders this as a hard lock
        "mcp_server": _mcp_server_name(provider, agent, conn.get("label", ""))
        if provider and agent else None,
        "env_var": _env_var_name(provider, conn.get("label", ""))
        if provider else None,
    }


def _load(conn_id: str) -> dict[str, Any]:
    p = _conn_path(conn_id)
    if not p.exists():
        raise HTTPException(404, f"connection not found: {conn_id}")
    data = yaml.safe_load(p.read_text()) or {}
    data["id"] = conn_id
    return data


# ── Schemas ──────────────────────────────────────────────────────────────────
class ConnectionCreate(BaseModel):
    id: str
    provider: str
    agent: str
    label: str  # short slug used in the mcp_servers key, e.g. gmail_<label>
    composio_account_id: str | None = None  # required for composio providers
    display_name: str = ""


# ── Routes ───────────────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    return {"status": "ok", "dir": str(_connections_dir())}


@router.get("/providers")
async def list_providers():
    """The integration catalog: each provider, the boundaries it can bind to,
    and the (derived, immutable) scope each binding grants."""
    out = []
    for pid, meta in PROVIDERS.items():
        out.append({
            "id": pid,
            "label": meta["label"],
            "backend": meta["backend"],
            "multi": meta["multi"],
            "needs_account_id": meta.get("needs_account_id", False),
            # True when the operator can mint an OAuth link in-dashboard
            # (POST /connect-link) rather than pasting a connected-account id.
            "supports_oauth_link": meta["backend"] == "composio"
            and bool(meta.get("toolkit_slug") or meta.get("auth_config_env")),
            "bindings": [
                {
                    "agent": agent,
                    "agent_label": AGENTS[agent]["label"],
                    "scope": b["scope"],
                    "badge": AGENTS[agent]["badge"],
                }
                for agent, b in meta["bindings"].items()
            ],
        })
    return {"providers": out}


@router.get("/connections")
async def list_connections():
    out = []
    for f in sorted(_connections_dir().glob("*.yaml")):
        data = yaml.safe_load(f.read_text()) or {}
        data["id"] = f.stem
        out.append(_hydrate(data))
    return {"connections": out, "dir": str(_connections_dir())}


@router.get("/connections/{conn_id}")
async def get_connection(conn_id: str):
    conn = _load(conn_id)
    hydrated = _hydrate(conn)
    hydrated["mcp_snippet"] = _mcp_snippet(conn)
    return hydrated


@router.post("/connections")
async def create_connection(body: ConnectionCreate):
    payload = body.model_dump()
    _reject_capability_escalation(payload)

    if not LABEL_RE.match(body.label):
        raise HTTPException(422, f"invalid label {body.label!r}: "
                                 f"lowercase letters, digits, hyphens (≤33).")
    if body.agent not in AGENTS:
        raise HTTPException(422, f"agent must be one of {list(AGENTS)}")

    # Derive (and thereby validate) the scope. Never trust client scope.
    scope = _derive_scope(body.provider, body.agent)

    pmeta = PROVIDERS[body.provider]
    if pmeta.get("needs_account_id") and not body.composio_account_id:
        raise HTTPException(422, f"provider {body.provider!r} requires a "
                                 f"composio_account_id (the Composio connected "
                                 f"account to bind).")
    # Single-account providers can only be connected once per boundary.
    if not pmeta["multi"]:
        for f in _connections_dir().glob("*.yaml"):
            existing = yaml.safe_load(f.read_text()) or {}
            if (existing.get("provider") == body.provider
                    and existing.get("agent") == body.agent):
                raise HTTPException(
                    409,
                    f"{pmeta['label']} is already connected to the "
                    f"{body.agent}. It does not support multiple accounts.",
                )

    path = _conn_path(body.id)
    if path.exists():
        raise HTTPException(409, f"connection already exists: {body.id}")

    record = {
        "provider": body.provider,
        "agent": body.agent,
        "label": body.label,
        "scope": scope,                 # derived, stored for transparency
        "display_name": body.display_name or body.label,
        "status": "active",
        "created_at": _now(),
    }
    if body.composio_account_id:
        record["composio_account_id"] = body.composio_account_id
    path.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True))

    conn = _load(body.id)
    hydrated = _hydrate(conn)
    hydrated["mcp_snippet"] = _mcp_snippet(conn)
    return hydrated


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: str):
    p = _conn_path(conn_id)
    if not p.exists():
        raise HTTPException(404, f"connection not found: {conn_id}")
    p.unlink()
    return {"deleted": conn_id}


@router.get("/render")
async def render_preview():
    """Dry-run: the mcp_servers entries this registry would inject into each
    agent config, grouped by boundary. This is exactly what
    scripts/render-hermes-config.py composes into the deployed config.yaml at
    provision time — exposed here so the operator can see it before applying."""
    by_agent: dict[str, dict[str, Any]] = {"reader": {}, "actor": {}}
    env_vars: dict[str, str] = {}
    for f in sorted(_connections_dir().glob("*.yaml")):
        conn = yaml.safe_load(f.read_text()) or {}
        conn["id"] = f.stem
        agent = conn.get("agent")
        snippet = _mcp_snippet(conn)
        if agent in by_agent and snippet:
            by_agent[agent].update(snippet)
        env_var = _env_var_name(conn.get("provider", ""), conn.get("label", ""))
        if env_var:
            env_vars[env_var] = conn.get("composio_account_id", "")
    return {"mcp_servers": by_agent, "env_vars": env_vars}


# ─────────────────────────────────────────────────────────────────────────────
# Composio OAuth onboarding — in-dashboard, on-box
# ─────────────────────────────────────────────────────────────────────────────
# Ports the standalone Netlify `connect.js` flow into the dashboard so the whole
# "connect your accounts" experience lives on the Orgo box behind the loopback
# dashboard — no public page, no client touching a Composio console. The
# operator (or the client, via the authenticated tunnel/orgo desktop) clicks
# "Connect", we mint a fresh Composio OAuth link server-side, they approve it at
# Google, we poll until the connected account is ACTIVE, then register it
# through the existing scope-locked POST /connections path.
#
# Security posture (stricter than the public Netlify page it replaces):
#   • COMPOSIO_API_KEY is read from the server env and NEVER returned to the
#     browser — the client only ever receives the provider's redirect_url.
#   • The OAuth link binds to (provider, agent); the scope is still DERIVED
#     server-side by _derive_scope — a link can't request more than its
#     boundary allows.
#   • user_id is the single per-client COMPOSIO_USER_ID (the same id the Reader/
#     Actor MCP servers send as x-composio-user-id), so the resulting
#     connected_account_id is usable by the rendered config as-is.

COMPOSIO_API_BASE = "https://backend.composio.dev/api/v3"


def _composio_api_key() -> str:
    key = os.environ.get("COMPOSIO_API_KEY", "").strip()
    if not key:
        # Fail fast and loud — no silent fallback. Mirrors connect.js's
        # "missing a server-side Composio key" guard.
        raise HTTPException(
            500,
            "COMPOSIO_API_KEY is not set in the dashboard environment. OAuth "
            "onboarding cannot mint connection links without it.",
        )
    return key


def _composio_user_id() -> str:
    uid = os.environ.get("COMPOSIO_USER_ID", "").strip()
    if not uid:
        raise HTTPException(
            500,
            "COMPOSIO_USER_ID is not set in the dashboard environment. It is "
            "required so the new connected account is owned by the same Composio "
            "user the Reader/Actor MCP servers authenticate as.",
        )
    return uid


def _composio_call(method: str, path: str,
                   body: dict[str, Any] | None = None) -> tuple[int, Any]:
    """Blocking Composio v3 request. Call via asyncio.to_thread from routes.

    Returns (status_code, parsed_json_or_raw_text). Never raises for HTTP error
    status — the caller decides how to surface it (so we can sanitize messages
    and never leak the api key). Raises only on transport failure.
    """
    url = f"{COMPOSIO_API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-api-key", _composio_api_key())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:  # 4xx/5xx — read the body, don't raise
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except urllib.error.URLError as e:
        raise HTTPException(502, f"Could not reach Composio: {e.reason}")
    try:
        return status, (json.loads(raw) if raw else {})
    except json.JSONDecodeError:
        return status, raw


async def _resolve_auth_config_id(provider: str) -> str:
    """The Composio auth_config id to mint the OAuth link against.

    Prefers an operator-provided env var (auth_config_env) so each client can
    pin its own pre-created auth config; otherwise creates a managed-auth config
    from the provider's toolkit_slug (the connect.js fallback path).
    """
    pmeta = PROVIDERS[provider]
    env_name = pmeta.get("auth_config_env")
    if env_name:
        preset = os.environ.get(env_name, "").strip()
        if preset:
            return preset

    slug = pmeta.get("toolkit_slug")
    if not slug:
        raise HTTPException(
            422,
            f"provider {provider!r} has no auth config: set "
            f"{env_name or 'its auth_config_env'} or give it a toolkit_slug.",
        )
    status, data = await asyncio.to_thread(
        _composio_call, "POST", "/auth_configs",
        {
            "toolkit": {"slug": slug},
            "auth_config": {
                "type": "use_composio_managed_auth",
                "credentials": {},
                "restrict_to_following_tools": [],
            },
        },
    )
    auth_config_id = (data or {}).get("auth_config", {}).get("id") \
        if isinstance(data, dict) else None
    if status >= 300 or not auth_config_id:
        raise HTTPException(
            502,
            f"Could not create a Composio auth config for {provider!r}. "
            f"Composio returned HTTP {status}.",
        )
    return auth_config_id


# ── Schemas ──────────────────────────────────────────────────────────────────
class ConnectLinkRequest(BaseModel):
    provider: str
    agent: str
    label: str = Field(..., description="slug used for the alias, e.g. hyphenlabs")


# ── Routes ───────────────────────────────────────────────────────────────────
@router.post("/connect-link")
async def create_connect_link(body: ConnectLinkRequest):
    """Mint a fresh Composio OAuth link for (provider, agent).

    Returns {redirect_url, connected_account_id, status}. The browser opens
    redirect_url; the user approves at the provider; the UI then polls
    GET /connect-status?connected_account_id=… until ACTIVE, and finally
    registers the account through POST /connections (which locks the scope).
    """
    pmeta = PROVIDERS.get(body.provider)
    if not pmeta:
        raise HTTPException(422, f"unknown provider: {body.provider!r}")
    if pmeta["backend"] != "composio":
        raise HTTPException(
            422,
            f"{pmeta['label']} is not a Composio provider — OAuth links only "
            f"apply to Composio integrations (it uses the {pmeta['backend']!r} "
            f"backend, configured elsewhere).",
        )
    if not LABEL_RE.match(body.label):
        raise HTTPException(422, f"invalid label {body.label!r}: "
                                 f"lowercase letters, digits, hyphens (≤33).")
    # Validates the (provider, agent) binding and that scope is allowed at all.
    _derive_scope(body.provider, body.agent)

    # Fail fast on missing server-side secrets before doing any work — and so the
    # guard holds even when the network call is stubbed in tests.
    _composio_api_key()
    user_id = _composio_user_id()
    auth_config_id = await _resolve_auth_config_id(body.provider)
    alias = f"{body.provider}-{body.label}"

    status, data = await asyncio.to_thread(
        _composio_call, "POST", "/connected_accounts/link",
        {"auth_config_id": auth_config_id, "user_id": user_id, "alias": alias},
    )
    redirect_url = data.get("redirect_url") if isinstance(data, dict) else None
    if status >= 300 or not redirect_url:
        raise HTTPException(
            502,
            f"Could not create a {pmeta['label']} connection link "
            f"(Composio HTTP {status}). Check the auth config and try again.",
        )
    return {
        "redirect_url": redirect_url,
        "connected_account_id": data.get("id"),
        "status": data.get("status", "INITIATED"),
        "provider": body.provider,
        "agent": body.agent,
        "label": body.label,
    }


@router.get("/connect-status")
async def connect_status(connected_account_id: str):
    """Poll a Composio connected account until the user finishes OAuth.

    The UI calls this on an interval after opening the redirect_url. When status
    is ACTIVE the returned connected_account_id is ready to register via
    POST /connections.
    """
    if not re.match(r"^[A-Za-z0-9_-]{4,128}$", connected_account_id):
        raise HTTPException(400, "invalid connected_account_id")
    status, data = await asyncio.to_thread(
        _composio_call, "GET", f"/connected_accounts/{connected_account_id}",
    )
    if status >= 300:
        raise HTTPException(
            502, f"Composio returned HTTP {status} for that connection.")
    conn_status = data.get("status") if isinstance(data, dict) else None
    return {
        "connected_account_id": connected_account_id,
        "status": conn_status,            # INITIATED | ACTIVE | FAILED | EXPIRED
        "active": conn_status == "ACTIVE",
    }
