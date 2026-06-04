"""SafeClaw Settings — dashboard plugin backend.

Mounted at /api/plugins/safeclaw-settings/ by the Hermes dashboard plugin
system. This is the single "Settings" tab that consolidates the operator's
manual setup state into one place, so onboarding a client is: check Settings →
share the handoff URL → the customer clicks connectors on the Connections tab.

────────────────────────────────────────────────────────────────────────────
What it shows — and the one rule it never breaks
────────────────────────────────────────────────────────────────────────────
It is STATUS-ONLY. It reports whether each piece of config is present and
whether each service is alive — it NEVER returns a secret value. The Composio
project key, MCP URLs, and the dashboard password are reported as booleans
("set" / "not set"), not echoed. The single exception is the client **handoff
URL**, which by design embeds the access credential so it is one-click — and
that is built ONLY when the operator has explicitly provided a plaintext access
password in the env (otherwise we return the host + a note, never a guess).

The org-level Composio key is deliberately NOT part of this surface: per the
operator-side orchestrator model, the org key never reaches the box. Project
creation happens on the operator machine (scripts/provision-composio.py); this
tab only reflects the per-client project key that provisioning wrote here.
"""

from __future__ import annotations

import asyncio
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter

router = APIRouter()

# Brain HTTP server (Step 2c): a bare GET /mcp returns 405 when ALIVE; any HTTP
# response means alive, only a connection failure means dead (issue 22e).
BRAIN_HTTP_URL = os.environ.get("GBRAIN_HTTP_URL", "http://127.0.0.1:3131/mcp")


def _is_set(var: str) -> bool:
    """True when an env var holds a real value (not blank, not a placeholder)."""
    v = os.environ.get(var, "").strip()
    return bool(v) and v not in {"__FILL_IN__", "__GENERATE__", "__MINTED__"}


def _connections_dir() -> Path:
    return Path(os.environ.get(
        "SAFECLAW_CONNECTIONS_DIR", Path.home() / ".hermes" / "connections",
    )).expanduser()


def _connection_count() -> int:
    d = _connections_dir()
    if not d.exists():
        return 0
    return len(list(d.glob("*.yaml")))


def _probe_brain() -> bool:
    """Any HTTP status = alive; only a transport failure = dead."""
    try:
        req = urllib.request.Request(BRAIN_HTTP_URL, method="GET")
        urllib.request.urlopen(req, timeout=4).close()
        return True
    except urllib.error.HTTPError:
        return True  # 405/4xx/5xx — the server answered, so it's alive
    except (urllib.error.URLError, OSError):
        return False


# ── Routes ───────────────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/status")
async def status():
    """Setup readiness — booleans + counts only, never secret values."""
    composio = {
        "project_key_set": _is_set("COMPOSIO_API_KEY"),
        "user_id_set": _is_set("COMPOSIO_USER_ID"),
        "reader_mcp_url_set": _is_set("COMPOSIO_READER_MCP_URL"),
        "actor_mcp_url_set": _is_set("COMPOSIO_ACTOR_MCP_URL"),
    }
    composio["ready"] = all(composio.values())
    brain_alive = await asyncio.to_thread(_probe_brain)
    return {
        "client": os.environ.get("CLIENT_NAME", "") or None,
        "composio": composio,
        "brain": {"http_url": BRAIN_HTTP_URL, "alive": brain_alive},
        "connections": {"count": _connection_count(), "dir": str(_connections_dir())},
    }


@router.get("/access")
async def access():
    """The client handoff URL — the one-click link you share.

    Deep-links straight to the Connections tab so the customer lands on the
    click-each-connector page. The credential is embedded ONLY when a plaintext
    access password is available in the env (DASHBOARD_AUTH_PASSWORD or
    UI_PASSWORD); the box normally stores only a bcrypt hash, so without a
    plaintext copy we return the host + the reason and never fabricate one.
    """
    host = (os.environ.get("PUBLIC_HOSTNAME", "").strip()
            or os.environ.get("HERMES_PUBLIC_HOSTNAME", "").strip())
    user = (os.environ.get("DASHBOARD_AUTH_USER", "").strip()
            or os.environ.get("SAFECLAW_UI_USER", "").strip())
    pw = (os.environ.get("DASHBOARD_AUTH_PASSWORD", "").strip()
          or os.environ.get("UI_PASSWORD", "").strip())
    pw_is_real = bool(pw) and pw not in {"__FILL_IN__", "__GENERATE__"}

    out: dict = {
        "public_hostname": host or None,
        "dashboard_user": user or None,
        "connections_path": "/connections",
        "handoff_url": None,
        "reason": None,
    }
    if not host:
        out["reason"] = "PUBLIC_HOSTNAME is not set — expose the tunnel (Step 8) first."
        return out
    if not (user and pw_is_real):
        out["reason"] = (
            "No plaintext access password on the box (only a bcrypt hash is "
            "stored). Share the handoff URL recorded at install, or set "
            "DASHBOARD_AUTH_PASSWORD to let this tab build the one-click link.")
        out["host_url"] = f"https://{host}/connections"
        return out

    out["handoff_url"] = f"https://{quote(user, safe='')}:{quote(pw, safe='')}@{host}/connections"
    return out


@router.get("/checklist")
async def checklist():
    """The consolidated manual-steps view — every onboarding gate in one list,
    each with a derived done/pending state, so the operator has a single screen
    instead of hunting across runbooks."""
    st = await status()
    acc = await access()
    items = [
        {"key": "composio_project", "label": "Composio project key on box",
         "done": st["composio"]["project_key_set"],
         "hint": "scripts/provision-composio.py writes COMPOSIO_API_KEY (project-scoped)."},
        {"key": "composio_user", "label": "Composio user_id set",
         "done": st["composio"]["user_id_set"], "hint": "COMPOSIO_USER_ID"},
        {"key": "mcp_reader", "label": "Reader MCP URL wired",
         "done": st["composio"]["reader_mcp_url_set"], "hint": "COMPOSIO_READER_MCP_URL"},
        {"key": "mcp_actor", "label": "Actor MCP URL wired (draft, no send)",
         "done": st["composio"]["actor_mcp_url_set"], "hint": "COMPOSIO_ACTOR_MCP_URL"},
        {"key": "brain", "label": "GBrain HTTP server alive",
         "done": st["brain"]["alive"], "hint": st["brain"]["http_url"]},
        {"key": "connections", "label": "≥1 account connected by the customer",
         "done": st["connections"]["count"] > 0,
         "hint": f"{st['connections']['count']} connected via the Connections tab"},
        {"key": "handoff", "label": "Client handoff URL ready to share",
         "done": bool(acc.get("handoff_url")),
         "hint": acc.get("reason") or "one-click link to the Connections tab"},
    ]
    done = sum(1 for i in items if i["done"])
    return {"items": items, "done": done, "total": len(items),
            "complete": done == len(items)}
