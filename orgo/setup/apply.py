#!/usr/bin/env python3
"""Auto-configure a SafeClaw client on orgo from uploaded credentials.

This is the "upload your Gmail/Google/Slack/Telegram tokens and everything wires
itself up" pipeline — the orgo counterpart of the current SafeClaw onboarding's
provisioner, but targeting the Hermes-native stack instead of `docker compose`.

It REUSES the battle-tested onboarding modules (no reinvention):
  • onboarding/lib/validator.py  — validates creds against the REAL upstream
    APIs and PROVISIONS the Composio Reader/Actor Gmail MCP servers.
  • onboarding/lib/env_writer.py — atomic, whitelisted, 0600 .env writer.

Pipeline (each step fail-fast — a bad credential stops everything, nothing is
half-applied):

  1. validate_all(form)                     reject bad creds before touching disk
  2. provision_composio_mcps(key, user)     create Reader/Actor Gmail MCP URLs
  3. write service-account JSON             → /opt/config/drive_credentials.json (0600)
  4. write_env(client.env, form)            persist secrets atomically
  5. register connections                   one registry YAML per account/provider
  6. render-hermes-config.py (reader+actor) inject MCP servers into deployed config
  7. restart Hermes                         pick up the new config

Usage:
    python3 orgo/setup/apply.py --creds creds.json --install-dir . [--restart]

`creds.json` is the setup form payload — the same field names the onboarding
form already posts (COMPOSIO_API_KEY, SLACK_BOT_TOKEN, TELEGRAM_BOT_TOKEN,
GDRIVE_SERVICE_ACCOUNT_JSON, …), plus an optional `gmail_accounts` list:
    {"gmail_accounts": [{"label": "suffolk", "connected_account_id": "ca_…",
                          "agent": "actor"}], ...}
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Reuse the onboarding validators + env writer (the existing auto-config core).
sys.path.insert(0, str(REPO_ROOT / "onboarding"))
try:
    from lib import validator, env_writer  # type: ignore
except ImportError as e:  # pragma: no cover
    sys.exit(f"FATAL: cannot import onboarding modules ({e}). "
             f"Run from the repo so onboarding/lib is importable.")


def _connections_dir() -> Path:
    d = Path(os.environ.get("SAFECLAW_CONNECTIONS_DIR",
                            Path.home() / ".hermes" / "connections")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def step(msg: str) -> None:
    print(f"→ {msg}", flush=True)


# ── 1. validate ──────────────────────────────────────────────────────────────
def validate(form: dict) -> None:
    step("validating credentials against upstream APIs …")
    errors = validator.validate_all(form)
    if errors:
        for field, msg in errors.items():
            print(f"   ✗ {field}: {msg}", file=sys.stderr)
        sys.exit("FATAL: credential validation failed — nothing written.")
    print("   ✓ all supplied credentials valid")


# ── 2. provision Composio MCP servers ────────────────────────────────────────
def provision_composio(form: dict) -> None:
    key = (form.get("COMPOSIO_API_KEY") or "").strip()
    user = (form.get("COMPOSIO_USER_ID") or "").strip()
    if not key or not user:
        return
    step("provisioning Composio Reader/Actor Gmail MCP servers …")
    urls = validator.provision_composio_mcps(key, user)  # raises on failure
    form.update(urls)  # COMPOSIO_READER_MCP_URL / COMPOSIO_ACTOR_MCP_URL
    print(f"   ✓ reader + actor MCP URLs provisioned")


# ── 3. Google service-account JSON ───────────────────────────────────────────
def write_gdrive_credentials(form: dict) -> None:
    raw = (form.get("GDRIVE_SERVICE_ACCOUNT_JSON") or "").strip()
    if not raw:
        return
    step("writing Google Drive service-account credentials …")
    # validate_all already parsed this; write it where the drive-api MCP expects.
    dest = Path(os.environ.get("GDRIVE_CREDENTIALS_PATH",
                               "/opt/config/drive_credentials.json"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(raw)
    # Don't keep the key material in the .env too.
    form.pop("GDRIVE_SERVICE_ACCOUNT_JSON", None)
    print(f"   ✓ wrote {dest} (0600)")


# ── 4. write secrets ─────────────────────────────────────────────────────────
def write_secrets(form: dict, install_dir: Path) -> None:
    step("writing client.env (atomic, 0600) …")
    env_writer.write_env(
        install_dir, {k: v for k, v in form.items() if v not in (None, "")},
        template_name="orgo/client.env.example", target_name="orgo/client.env",
    )
    print("   ✓ client.env updated")


# ── 5. register connections ──────────────────────────────────────────────────
def register_connections(form: dict) -> None:
    """Turn the uploaded creds into connections-registry YAMLs so the dashboard
    Connections tab and the render step both see them. Scope is implicit in the
    boundary (reader=read, actor=draft) — see the connections plugin."""
    import yaml
    step("registering connections …")
    cdir = _connections_dir()
    count = 0

    def write_conn(cid: str, record: dict) -> None:
        nonlocal count
        (cdir / f"{cid}.yaml").write_text(
            yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
        count += 1

    # Gmail (multi-account). Each account → an actor (draft) connection, and a
    # reader (read) connection if a reader Composio URL exists.
    for acct in form.get("gmail_accounts", []) or []:
        label = acct["label"]
        aid = acct.get("connected_account_id", "")
        write_conn(f"gmail-{label}-actor", {
            "provider": "gmail", "agent": "actor", "label": label,
            "scope": "draft", "composio_account_id": aid, "status": "active",
        })
        if (form.get("COMPOSIO_READER_MCP_URL") or "").strip():
            write_conn(f"gmail-{label}-reader", {
                "provider": "gmail", "agent": "reader", "label": label,
                "scope": "read", "composio_account_id": aid, "status": "active",
            })

    if (form.get("SLACK_BOT_TOKEN") or "").strip():
        write_conn("slack-actor", {"provider": "slack", "agent": "actor",
                                   "label": "workspace", "scope": "draft", "status": "active"})
        write_conn("slack-reader", {"provider": "slack", "agent": "reader",
                                    "label": "workspace", "scope": "read", "status": "active"})
    if (form.get("TELEGRAM_BOT_TOKEN") or "").strip():
        write_conn("telegram-actor", {"provider": "telegram", "agent": "actor",
                                      "label": "bot", "scope": "chat", "status": "active"})
    if (form.get("GDRIVE_SERVICE_ACCOUNT_JSON") or "").strip() or \
       os.path.exists("/opt/config/drive_credentials.json"):
        write_conn("gdrive-actor", {"provider": "gdrive", "agent": "actor",
                                    "label": "main", "scope": "draft", "status": "active"})
    print(f"   ✓ registered {count} connection(s) in {cdir}")


# ── 6. render Hermes MCP config ──────────────────────────────────────────────
def render_configs(install_dir: Path) -> None:
    step("rendering Hermes agent configs from the connections registry …")
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    for agent, base in (("reader", "config/reader-hermes.yaml"),
                        ("actor", "config/actor-hermes.yaml")):
        out = hermes_home / f"{agent}-config.yaml"
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "render-hermes-config.py"),
             "--agent", agent, "--base", str(install_dir / base), "--out", str(out),
             "--connections-dir", str(_connections_dir()),
             "--env-out", str(install_dir / "orgo" / "client.env")],
            capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"FATAL: render failed for {agent}: {r.stderr.strip()}")
        print(f"   ✓ {out}")


# ── 7. restart Hermes ────────────────────────────────────────────────────────
def restart_hermes() -> None:
    step("restarting Hermes (gateway) to pick up the new config …")
    # pkill is best-effort; the orgo provisioner's start_hermes relaunches it.
    subprocess.run(["pkill", "-f", "hermes gateway"], check=False)
    subprocess.Popen(["hermes", "gateway", "start"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("   ✓ gateway restarted")


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-configure SafeClaw from uploaded creds")
    ap.add_argument("--creds", required=True, type=Path, help="setup form payload JSON")
    ap.add_argument("--install-dir", type=Path, default=REPO_ROOT)
    ap.add_argument("--restart", action="store_true", help="restart Hermes at the end")
    args = ap.parse_args()

    if not args.creds.exists():
        sys.exit(f"FATAL: creds file not found: {args.creds}")
    form = json.loads(args.creds.read_text())
    if not isinstance(form, dict):
        sys.exit("FATAL: creds JSON must be an object")

    validate(form)
    provision_composio(form)
    write_gdrive_credentials(form)
    write_secrets(form, args.install_dir)
    register_connections(form)
    render_configs(args.install_dir)
    if args.restart:
        restart_hermes()

    print("\n✓ auto-config complete. Open the dashboard → Connections to review; "
          "send a test Telegram DM to confirm.")


if __name__ == "__main__":
    main()
