#!/usr/bin/env python3
"""Operator-side Composio provisioning for a new SafeClaw client.

Run this ON THE OPERATOR MACHINE (your Mac / the admin agent) — NEVER on the
client's orgo box. It takes the agency **Composio Org key** (which can create
projects across every client) and, for one client:

  1. Creates an isolated Composio **project** for that client.
  2. Creates a managed-auth **auth config** per requested platform (e.g. gmail).
  3. Creates the **reader** and **actor** MCP servers with the SafeClaw
     trust-split tool allowlists (reader = read-only, actor = draft, NO send).
  4. Emits a `client.env` fragment containing ONLY the per-client **project
     key** + **MCP URLs** — the things that are safe to put on the box.

The Org key is used solely for step 1 and is NEVER written to disk or echoed.
Everything after step 1 uses the project-scoped key, so the box only ever holds
a key whose blast radius is this one client. This is the operator-side
orchestrator model (see ORGO-CLIENT-TEMPLATE.md Step 11).

Verified API surface (June 2026):
  POST /api/v3.1/org/owner/project/new   header x-org-api-key   -> {id, api_key}
  POST /api/v3/auth_configs              header x-api-key(proj) -> {auth_config:{id}}
  POST /api/v3/mcp/servers               header x-api-key(proj) -> {id, ..., url|mcp_url}

Usage:
  COMPOSIO_ORG_API_KEY=ak_org_… python3 scripts/provision-composio.py \
      --client suffolk --platforms gmail [--user-id client:suffolk] [--json]

Stdlib only (urllib) — no pip installs, runs anywhere Python 3 does.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

COMPOSIO_V3 = "https://backend.composio.dev/api/v3"
COMPOSIO_V31 = "https://backend.composio.dev/api/v3.1"

# ── Platform catalog ─────────────────────────────────────────────────────────
# The SafeClaw trust split, expressed as Composio tool allowlists. The reader
# server gets read-only tools; the actor server gets draft tools and NEVER a
# send tool. Adding a platform here is the only change needed to provision it.
PLATFORMS: dict[str, dict] = {
    "gmail": {
        "toolkit": "gmail",
        "reader_tools": [
            "GMAIL_FETCH_EMAILS",
            "GMAIL_LIST_THREADS",
            "GMAIL_GET_PROFILE",
            "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
            "GMAIL_GET_ATTACHMENT",
        ],
        "actor_tools": [
            # draft + the fetch tools needed to compose a reply. NO GMAIL_SEND_EMAIL.
            "GMAIL_CREATE_EMAIL_DRAFT",
            "GMAIL_REPLY_TO_THREAD",
            "GMAIL_FETCH_EMAILS",
            "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
        ],
    },
}

# Tools that must never appear in any allowlist — the broken-trifecta guard, in
# code. If a future platform edit slips one in, provisioning aborts.
FORBIDDEN_TOOL_SUBSTRINGS = ("SEND", "DELETE", "TRASH")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


class ComposioError(RuntimeError):
    pass


class ComposioClient:
    """Thin Composio REST client. `_request` is the single seam tests patch."""

    def __init__(self, org_key: str | None = None, project_key: str | None = None):
        self._org_key = org_key
        self._project_key = project_key

    # The only network seam — monkeypatch this in tests.
    def _request(self, method: str, url: str, headers: dict, body: dict | None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            status = e.code
        except urllib.error.URLError as e:
            raise ComposioError(f"could not reach Composio: {e.reason}") from None
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"_raw": raw}
        return status, parsed

    def create_project(self, name: str) -> tuple[str, str]:
        """Create a project with the ORG key. Returns (project_id, project_key)."""
        if not self._org_key:
            raise ComposioError("org key required to create a project")
        status, data = self._request(
            "POST", f"{COMPOSIO_V31}/org/owner/project/new",
            {"x-org-api-key": self._org_key},
            {
                "name": name,
                "should_create_api_key": True,
                "config": {
                    "is_2FA_enabled": False,
                    "mask_secret_keys_in_connected_account": True,
                    "log_visibility_setting": "show_all",
                },
            },
        )
        if status >= 300:
            raise ComposioError(f"project create failed (HTTP {status}): {_short(data)}")
        pid, key = data.get("id"), data.get("api_key")
        if not pid or not key:
            raise ComposioError(
                "project created but no api_key returned — ensure the org key "
                "has project-create rights and should_create_api_key is honored.")
        self._project_key = key
        return pid, key

    def create_auth_config(self, toolkit: str) -> str:
        """Create a managed-auth auth config in the project. Returns its id."""
        status, data = self._request(
            "POST", f"{COMPOSIO_V3}/auth_configs",
            {"x-api-key": self._require_project_key()},
            {
                "toolkit": {"slug": toolkit},
                "auth_config": {
                    "type": "use_composio_managed_auth",
                    "credentials": {},
                    "restrict_to_following_tools": [],
                },
            },
        )
        if status >= 300:
            raise ComposioError(f"auth_config create failed for {toolkit} "
                                f"(HTTP {status}): {_short(data)}")
        cid = (data.get("auth_config") or {}).get("id") or data.get("id")
        if not cid:
            raise ComposioError(f"auth_config for {toolkit}: no id in response")
        return cid

    def create_mcp_server(self, name: str, auth_config_id: str,
                          allowed_tools: list[str]) -> str:
        """Create an MCP server bound to an auth config + allowlist. Returns URL."""
        status, data = self._request(
            "POST", f"{COMPOSIO_V3}/mcp/servers",
            {"x-api-key": self._require_project_key()},
            {"name": name, "auth_config_ids": [auth_config_id],
             "allowed_tools": allowed_tools},
        )
        if status >= 300:
            raise ComposioError(f"mcp server create failed for {name} "
                                f"(HTTP {status}): {_short(data)}")
        url = data.get("mcp_url") or data.get("url") or data.get("base_url")
        if not url:
            raise ComposioError(f"mcp server {name}: no url in response: {_short(data)}")
        return url

    def _require_project_key(self) -> str:
        if not self._project_key:
            raise ComposioError("project key missing — create the project first")
        return self._project_key


def _short(data) -> str:
    s = json.dumps(data) if not isinstance(data, str) else data
    return s[:300]


def _validate_allowlists() -> None:
    for pname, meta in PLATFORMS.items():
        for role in ("reader_tools", "actor_tools"):
            for tool in meta[role]:
                for bad in FORBIDDEN_TOOL_SUBSTRINGS:
                    if bad in tool and not (bad == "DELETE" and tool.endswith("DRAFT")):
                        raise ComposioError(
                            f"platform {pname} {role} contains a forbidden tool "
                            f"{tool!r} (matched {bad!r}) — the trust split forbids it.")


def provision(client: str, platforms: list[str], user_id: str,
              org_key: str, display_name: str | None = None,
              composio: ComposioClient | None = None) -> dict:
    """Do the full provisioning. Returns a result dict (no secrets logged)."""
    _validate_allowlists()
    for p in platforms:
        if p not in PLATFORMS:
            raise ComposioError(f"unknown platform {p!r}; known: {sorted(PLATFORMS)}")

    cc = composio or ComposioClient(org_key=org_key)
    project_id, project_key = cc.create_project(display_name or f"safeclaw-{client}")

    reader_url = actor_url = None
    auth_configs: dict[str, str] = {}
    for p in platforms:
        meta = PLATFORMS[p]
        ac_id = cc.create_auth_config(meta["toolkit"])
        auth_configs[p] = ac_id
        # One reader + one actor server per platform. For a single platform these
        # become the COMPOSIO_READER/ACTOR_MCP_URL; multi-platform is a future slice.
        r_url = cc.create_mcp_server(f"{client}-{p}-reader", ac_id, meta["reader_tools"])
        a_url = cc.create_mcp_server(f"{client}-{p}-actor", ac_id, meta["actor_tools"])
        if reader_url is None:
            reader_url, actor_url = r_url, a_url

    return {
        "client": client,
        "project_id": project_id,
        "project_key": project_key,    # goes to the box as COMPOSIO_API_KEY
        "user_id": user_id,
        "platforms": platforms,
        "auth_configs": auth_configs,
        "reader_mcp_url": reader_url,
        "actor_mcp_url": actor_url,
    }


def env_fragment(result: dict) -> str:
    """The lines to add to the box's client.env. Project-scoped only."""
    return "\n".join([
        "# ── Composio (per-client project — generated by provision-composio.py) ──",
        f"COMPOSIO_API_KEY={result['project_key']}",
        f"COMPOSIO_USER_ID={result['user_id']}",
        f"COMPOSIO_READER_MCP_URL={result['reader_mcp_url']}",
        f"COMPOSIO_ACTOR_MCP_URL={result['actor_mcp_url']}",
        f"# project_id={result['project_id']} (Composio console reference)",
    ])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Provision a Composio project for a SafeClaw client (operator-side).")
    ap.add_argument("--client", required=True, help="client slug, e.g. suffolk")
    ap.add_argument("--platforms", default="gmail", help="comma list (default: gmail)")
    ap.add_argument("--user-id", default=None, help="Composio user_id (default: client:<slug>)")
    ap.add_argument("--display-name", default=None, help="project display name")
    ap.add_argument("--org-key", default=None, help="org key (or env COMPOSIO_ORG_API_KEY)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of an env fragment")
    args = ap.parse_args(argv)

    if not SLUG_RE.match(args.client):
        print(f"error: --client {args.client!r} must be a lowercase slug (a-z0-9-).", file=sys.stderr)
        return 2
    org_key = args.org_key or os.environ.get("COMPOSIO_ORG_API_KEY", "").strip()
    if not org_key:
        print("error: provide the org key via --org-key or COMPOSIO_ORG_API_KEY. "
              "It is used only to create the project and is never written to the box.", file=sys.stderr)
        return 2
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    user_id = args.user_id or f"client:{args.client}"

    try:
        result = provision(args.client, platforms, user_id, org_key, args.display_name)
    except ComposioError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        # Redact nothing here on purpose: this is operator-side stdout, and the
        # project key is exactly what must reach the box. Never log the ORG key —
        # and we don't: it is not part of `result`.
        print(json.dumps(result, indent=2))
    else:
        print(env_fragment(result))
        print(f"\n# next: paste the lines above into the box's client.env "
              f"(NOT the org key), then run Step 11 wiring.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
