#!/usr/bin/env python3
"""Render connection MCP servers into a Hermes agent config — non-destructively.

The safeclaw-connections dashboard plugin owns a connections *registry*
(one YAML per connection under SAFECLAW_CONNECTIONS_DIR). It deliberately never
rewrites config/{reader,actor}-hermes.yaml, because those files carry hand-tuned
comments and a YAML anchor (&composio_headers) that a yaml.safe_load→safe_dump
round-trip would silently destroy.

This script bridges registry → config at PROVISION time. It reads the base
agent config as TEXT, finds the `mcp_servers:` line, and inserts the generated
server entries right after it (correctly indented). Everything else in the file
— comments, anchors, ordering — is byte-for-byte preserved.

Run once per agent at provision (and re-run whenever connections change):

    python3 scripts/render-hermes-config.py \
        --agent actor \
        --base   config/actor-hermes.yaml \
        --out    /opt/data/config.yaml \
        --connections-dir ~/.hermes/connections \
        --env-out client.env

The snippet logic here is a small, dependency-light mirror of
dashboard-plugins/safeclaw-connections/dashboard/plugin_api.py::_mcp_snippet
(the canonical source). Only PyYAML is required.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

# ── Canonical snippet logic (mirror of the connections plugin) ───────────────
# provider -> backend + which agent boundaries it may bind to + the mcp prefix.
PROVIDERS = {
    "gmail":    {"backend": "composio",  "multi": True,
                 "bindings": {"reader": "gmail", "actor": "gmail"}},
    "slack":    {"backend": "native",    "multi": False,
                 "bindings": {"reader": "slack_native", "actor": "slack_native"}},
    "telegram": {"backend": "gateway",   "multi": False,
                 "bindings": {"actor": None}},
    "gdrive":   {"backend": "drive_api", "multi": False,
                 "bindings": {"actor": "drive_api"}},
}


def mcp_server_name(provider: str, agent: str, label: str) -> str | None:
    pmeta = PROVIDERS.get(provider)
    if not pmeta or agent not in pmeta["bindings"]:
        return None
    prefix = pmeta["bindings"][agent]
    if prefix is None:
        return None
    return f"{prefix}_{label}" if pmeta["multi"] else prefix


def env_var_name(provider: str, label: str) -> str | None:
    if provider == "gmail":
        return f"GMAIL_{label.upper().replace('-', '_')}_ACCOUNT_ID"
    return None


def mcp_snippet(conn: dict) -> dict | None:
    provider, agent, label = conn["provider"], conn["agent"], conn["label"]
    name = mcp_server_name(provider, agent, label)
    if name is None:
        return None
    backend = PROVIDERS[provider]["backend"]
    if backend == "composio":
        url_var = ("${COMPOSIO_READER_MCP_URL}" if agent == "reader"
                   else "${COMPOSIO_ACTOR_MCP_URL}")
        env_var = env_var_name(provider, label)
        return {name: {
            "url": f"{url_var}&connected_account_id=${{{env_var}}}",
            "headers": {"x-api-key": "${COMPOSIO_API_KEY}",
                        "x-composio-user-id": "${COMPOSIO_USER_ID}"},
            "timeout": 120, "connect_timeout": 30,
        }}
    if backend == "native":
        mode = "reader" if agent == "reader" else "actor"
        token = ("${SLACK_MCP_BOT_TOKEN}" if agent == "reader"
                 else "${SLACK_BOT_TOKEN}")
        return {name: {
            "command": "node",
            "args": ["/opt/mcp-tools/slack-api/dist/index.js"],
            "env": {"SLACK_BOT_TOKEN": token, "SLACK_MCP_MODE": mode},
            "timeout": 30, "connect_timeout": 10,
        }}
    if backend == "drive_api":
        return {name: {
            "command": "/opt/mcp-tools/drive-api/.venv/bin/python",
            "args": ["/opt/mcp-tools/drive-api/main.py"],
            "env": {"GDRIVE_CREDENTIALS_PATH": "/opt/config/drive_credentials.json"},
            "timeout": 60, "connect_timeout": 15,
        }}
    return None


def load_connections(conn_dir: Path, agent: str) -> list[dict]:
    out = []
    if not conn_dir.exists():
        return out
    for f in sorted(conn_dir.glob("*.yaml")):
        data = yaml.safe_load(f.read_text()) or {}
        if data.get("agent") == agent:
            data["id"] = f.stem
            out.append(data)
    return out


def indent_block(snippet: dict, indent: int = 2) -> str:
    """YAML-dump one mcp server entry and indent it under `mcp_servers:`."""
    raw = yaml.safe_dump(snippet, sort_keys=False, default_flow_style=False)
    pad = " " * indent
    return "".join(pad + line if line.strip() else line
                   for line in raw.splitlines(keepends=True))


def render(base_text: str, snippets: list[dict]) -> str:
    """Insert generated entries right after the `mcp_servers:` line."""
    lines = base_text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if re.match(r"^mcp_servers:\s*$", line):
            # Skip any server whose key already exists in the base file.
            existing = set(re.findall(r"^\s{2}([A-Za-z0-9_]+):", base_text, re.M))
            blocks = []
            for snip in snippets:
                name = next(iter(snip))
                if name in existing:
                    print(f"  · skip {name} (already in base config)", file=sys.stderr)
                    continue
                blocks.append(indent_block(snip))
            if not blocks:
                return base_text
            insert = ("  # ── generated by render-hermes-config.py from the "
                      "connections registry ──\n" + "".join(blocks))
            lines.insert(i + 1, insert)
            return "".join(lines)
    raise SystemExit("FATAL: no `mcp_servers:` block found in base config — "
                     "cannot inject connections. (fail-fast, nothing written)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, choices=["reader", "actor"])
    ap.add_argument("--base", required=True, type=Path)
    ap.add_argument("--out", type=Path, help="output config path (default: stdout)")
    ap.add_argument("--connections-dir", type=Path,
                    default=Path.home() / ".hermes" / "connections")
    ap.add_argument("--env-out", type=Path,
                    help="append per-connection env vars (e.g. GMAIL_*_ACCOUNT_ID) here")
    args = ap.parse_args()

    if not args.base.exists():
        raise SystemExit(f"FATAL: base config not found: {args.base}")

    conns = load_connections(args.connections_dir, args.agent)
    snippets = [s for s in (mcp_snippet(c) for c in conns) if s]
    rendered = render(args.base.read_text(), snippets)

    if args.out:
        args.out.write_text(rendered)
        print(f"✓ wrote {args.out} ({len(snippets)} connection MCP server(s) "
              f"injected for {args.agent})")
    else:
        sys.stdout.write(rendered)

    if args.env_out:
        lines = []
        for c in conns:
            ev = env_var_name(c.get("provider", ""), c.get("label", ""))
            if ev and c.get("composio_account_id"):
                lines.append(f"{ev}={c['composio_account_id']}\n")
        if lines:
            with args.env_out.open("a") as fh:
                fh.write("# ── connection account IDs (render-hermes-config.py) ──\n")
                fh.writelines(lines)
            print(f"✓ appended {len(lines)} env var(s) to {args.env_out}")


if __name__ == "__main__":
    main()
