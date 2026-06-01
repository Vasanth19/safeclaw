#!/usr/bin/env python3
"""Provision a new SafeClaw client on orgo.ai — one workspace, one computer.

The "duplicate a workspace, configure for a new customer, keep going" flow:

    1. create an orgo workspace      → client-<name>
    2. create a computer in it FROM A GOLDEN SNAPSHOT (pre-baked template)
    3. push the filled client.env onto the box
    4. bring up the brain compose (gbrain + postgres-brain)
    5. mint brain tokens (gbrain auth create) → back into client.env
    6. render agent configs from the connections registry
    7. bootstrap the brain (Gmail backfill) and start Hermes (dashboard + gateway)

Auth: reads ORGO_API_KEY from the environment. NEVER hardcode the key.
      >>> The sk_live_… key shared in chat is compromised — rotate it, export the
      >>> new one:  export ORGO_API_KEY=sk_live_…   before running this.

Status: the REST endpoints below follow orgo's documented surface
(https://www.orgo.ai/api). The workspace + snapshot/clone calls are marked
VERIFY — confirm exact paths/fields against docs.orgo.ai/llms-full.txt before a
real run (tracked as a follow-up task). Everything is fail-fast: a non-2xx
response raises, nothing is guessed silently.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("FATAL: pip install requests  (orgo REST client dependency)")

ORGO_API = os.environ.get("ORGO_API_BASE", "https://www.orgo.ai/api")
REPO_ON_BOX = "/opt/safeclaw"  # where the golden snapshot has SafeClaw cloned


def _key() -> str:
    k = os.environ.get("ORGO_API_KEY")
    if not k:
        sys.exit("FATAL: ORGO_API_KEY not set. Rotate the leaked key first, "
                 "then `export ORGO_API_KEY=sk_live_…`.")
    if not k.startswith("sk_"):
        sys.exit("FATAL: ORGO_API_KEY does not look like an orgo key (sk_…).")
    return k


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}


def _post(path: str, body: dict) -> dict:
    r = requests.post(f"{ORGO_API}{path}", json=body, headers=_headers(), timeout=60)
    if not r.ok:
        sys.exit(f"FATAL: POST {path} → {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


def create_workspace(name: str) -> str:
    # VERIFY path/fields against docs.orgo.ai/llms-full.txt
    print(f"→ creating workspace client-{name} …")
    data = _post("/workspaces", {"name": f"client-{name}"})
    ws_id = data.get("id") or data.get("workspace_id")
    if not ws_id:
        sys.exit(f"FATAL: workspace create returned no id: {data}")
    print(f"  workspace id = {ws_id}")
    return ws_id


def create_computer(workspace_id: str, name: str, snapshot_id: str) -> str:
    # VERIFY: field name for cloning from a snapshot/template ('snapshot_id'?
    # 'template'? 'image'?). Sized for the brain+Hermes box.
    print(f"→ creating computer from snapshot {snapshot_id} …")
    data = _post("/computers", {
        "workspace_id": workspace_id,
        "name": f"safeclaw-{name}",
        "snapshot_id": snapshot_id,
        "os": "ubuntu",
        "ram": 8, "cpu": 2,   # bump from the 4GB tier — brain+Hermes headroom
    })
    cid = data.get("id") or data.get("computer_id")
    if not cid:
        sys.exit(f"FATAL: computer create returned no id: {data}")
    print(f"  computer id = {cid}")
    return cid


def bash(computer_id: str, cmd: str, quiet: bool = False) -> str:
    # VERIFY: documented as POST /computers/{id}/bash with {"command": …}
    data = _post(f"/computers/{computer_id}/bash", {"command": cmd})
    out = data.get("output", data.get("stdout", ""))
    if not quiet:
        print(out.rstrip())
    return out


def push_env(computer_id: str, env_path: str) -> None:
    print("→ pushing client.env onto the box …")
    content = open(env_path).read()
    # Heredoc write — avoids a separate file-upload round trip.
    bash(computer_id,
         f"cat > {REPO_ON_BOX}/orgo/client.env <<'SAFECLAW_ENV_EOF'\n"
         f"{content}\nSAFECLAW_ENV_EOF\nchmod 600 {REPO_ON_BOX}/orgo/client.env",
         quiet=True)


def bring_up_brain(computer_id: str) -> None:
    print("→ bringing up brain (gbrain + postgres-brain) …")
    bash(computer_id,
         f"cd {REPO_ON_BOX} && bash scripts/init-secrets.sh orgo/client.env && "
         f"docker compose -f orgo/docker-compose.brain.yml --env-file orgo/client.env up -d")
    # wait for /health
    for _ in range(20):
        out = bash(computer_id, "curl -fsS http://127.0.0.1:3131/health || echo DOWN", quiet=True)
        if "DOWN" not in out:
            print("  brain healthy ✓"); return
        time.sleep(6)
    sys.exit("FATAL: brain did not become healthy in time.")


def mint_tokens_and_render(computer_id: str) -> None:
    print("→ minting brain tokens + rendering agent configs …")
    bash(computer_id,
         "R=$(docker exec safeclaw-brain gbrain auth create reader | tail -n1); "
         "A=$(docker exec safeclaw-brain gbrain auth create actor | tail -n1); "
         f"sed -i \"s|^SAFECLAW_BRAIN_READER_TOKEN=.*|SAFECLAW_BRAIN_READER_TOKEN=$R|\" {REPO_ON_BOX}/orgo/client.env; "
         f"sed -i \"s|^SAFECLAW_BRAIN_ACTOR_TOKEN=.*|SAFECLAW_BRAIN_ACTOR_TOKEN=$A|\" {REPO_ON_BOX}/orgo/client.env")
    for agent, base in (("reader", "config/reader-hermes.yaml"),
                        ("actor", "config/actor-hermes.yaml")):
        bash(computer_id,
             f"cd {REPO_ON_BOX} && python3 scripts/render-hermes-config.py "
             f"--agent {agent} --base {base} --out ~/.hermes/{agent}-config.yaml "
             f"--connections-dir ~/.hermes/connections --env-out orgo/client.env")


def start_hermes(computer_id: str) -> None:
    print("→ linking plugins + skills and starting Hermes (dashboard + gateway) …")
    bash(computer_id, f"""
cd {REPO_ON_BOX}
mkdir -p ~/.hermes/plugins ~/.hermes/skills/integrations ~/.hermes/personas ~/.hermes/connections
for p in dashboard-plugins/*/; do ln -sfn "$PWD/$p" ~/.hermes/plugins/"$(basename "$p")"; done
for s in skills/*/;            do ln -sfn "$PWD/$s" ~/.hermes/skills/integrations/"$(basename "$s")"; done
cp -n dashboard-plugins/safeclaw-personas/seed-personas/*.yaml ~/.hermes/personas/ 2>/dev/null || true
# chat mode + dashboard on loopback (orgo desktop reaches it; not public)
hermes dashboard --port 9119 --host 127.0.0.1 --no-open --insecure >/tmp/hermes-dash.log 2>&1 &
hermes gateway start >/tmp/hermes-gw.log 2>&1 &
echo "hermes launched (dashboard :9119, gateway polling)"
""")


def bootstrap(computer_id: str) -> None:
    print("→ bootstrapping brain (Gmail backfill) …")
    bash(computer_id, f"cd {REPO_ON_BOX} && bash scripts/bootstrap-brain.sh || "
                      f"echo 'bootstrap skipped/failed — run manually once Composio Gmail is connected'")


def main() -> None:
    ap = argparse.ArgumentParser(description="Provision a SafeClaw client on orgo.ai")
    ap.add_argument("--name", required=True, help="client slug, e.g. suffolk")
    ap.add_argument("--snapshot-id", required=True,
                    help="golden orgo snapshot/template id (built once; see ORGO-DEPLOY.md)")
    ap.add_argument("--env", default="orgo/client.env", help="filled client.env path")
    ap.add_argument("--skip-bootstrap", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.env):
        sys.exit(f"FATAL: {args.env} not found. Copy orgo/client.env.example, fill it, retry.")

    _key()  # fail fast before creating anything
    ws = create_workspace(args.name)
    cid = create_computer(ws, args.name, args.snapshot_id)
    push_env(cid, args.env)
    bring_up_brain(cid)
    mint_tokens_and_render(cid)
    start_hermes(cid)
    if not args.skip_bootstrap:
        bootstrap(cid)

    print("\n✓ provisioned.")
    print(f"  workspace : client-{args.name}")
    print(f"  computer  : {cid}")
    print(f"  next      : open the orgo desktop → dashboard at 127.0.0.1:9119 "
          f"→ Connections tab to add Gmail/Slack/Telegram/Drive.")
    print(f"  verify    : bash scripts/smoke-brain.sh  + send a test Telegram DM.")


if __name__ == "__main__":
    main()
