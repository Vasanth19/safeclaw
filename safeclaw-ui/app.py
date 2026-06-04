"""SafeClaw UI — the configuration console for a native Hermes + GBrain box.

A single, lightweight Flask app (server-rendered SPA, no build step) that runs
ON the SafeClaw box and configures the *native* Hermes install:
  • MCP servers   → `hermes mcp add/remove/list`  (gbrain, Zapier, any URL)
  • secrets       → ~/.hermes/.env  (Slack / Telegram / Composio / API keys)
  • brain status  → `gbrain stats`

Panels: Dashboard · Slack · Telegram · Gmail · Google Drive · Zapier / MCP.

This is the orgo-native counterpart of the Docker `onboarding/` app. It reuses
that app's credential validators where possible. It NEVER exposes secret values
back to the browser — only whether a key is set.

Run:  HERMES_HOME=~/.hermes python3 app.py   (default port 8899, loopback)
Front it with the authenticated Caddy gate for a public URL (orgo/access/).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, Response

# Reuse the existing onboarding credential validators (hit real upstream APIs).
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "onboarding"))
try:
    from lib import validator  # type: ignore
except Exception:  # pragma: no cover - validators are best-effort
    validator = None

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
GBRAIN_BIN = os.environ.get("GBRAIN_BIN", "gbrain")
ENV_FILE = HERMES_HOME / ".env"

# Brain HTTP MCP server (the ONE `gbrain serve --http` process; template issue 22).
# The gbrain CLI cannot be used while that server runs — it holds the PGLite
# single-writer lock — so ALL Console brain reads go through this endpoint.
GBRAIN_HTTP_URL = os.environ.get("GBRAIN_HTTP_URL", "http://127.0.0.1:3131/mcp")
GBRAIN_TOKEN_FILE = Path(os.environ.get("GBRAIN_TOKEN_FILE", "/opt/brain/.hermes-token"))


def _brain_call(tool: str, arguments: dict | None = None, timeout: int = 30):
    """Call a tool on the brain HTTP MCP server. Returns (ok, parsed_result_or_error)."""
    import urllib.request
    try:
        token = GBRAIN_TOKEN_FILE.read_text().strip()
    except Exception:
        token = ""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments or {}},
    }).encode()
    req = urllib.request.Request(
        GBRAIN_HTTP_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
    except Exception as e:  # conn refused / timeout / 401 …
        return False, str(e)
    # Server replies in SSE framing ("event: message\ndata: {...}") or bare JSON.
    payload = next((l[5:].strip() for l in raw.splitlines() if l.startswith("data:")), raw)
    try:
        msg = json.loads(payload)
        text = msg["result"]["content"][0]["text"]
        try:
            return True, json.loads(text)
        except Exception:
            return True, text
    except Exception as e:
        return False, f"unparseable brain reply: {e}"


app = Flask(__name__, template_folder="templates", static_folder="static")

# Optional HTTP basic-auth — REQUIRED whenever the UI is exposed beyond loopback
# (e.g. via a tunnel), since it reads/writes secrets. Set SAFECLAW_UI_USER +
# SAFECLAW_UI_PASS to enable; unset = open (loopback-only dev).
_UI_USER = os.environ.get("SAFECLAW_UI_USER")
_UI_PASS = os.environ.get("SAFECLAW_UI_PASS")


@app.before_request
def _basic_auth():
    if not _UI_USER:
        return None
    from flask import Response
    auth = request.authorization
    if not auth or auth.username != _UI_USER or auth.password != _UI_PASS:
        return Response("auth required", 401,
                        {"WWW-Authenticate": 'Basic realm="SafeClaw"'})
    return None

# Which env keys each panel owns (so we can report set/unset without leaking).
SECRET_KEYS = {
    "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_HOME_CHANNEL"],
    "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS"],
    "gmail": ["COMPOSIO_API_KEY", "COMPOSIO_USER_ID",
              "COMPOSIO_READER_MCP_URL", "COMPOSIO_ACTOR_MCP_URL"],
    "llm": ["OLLAMA_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
}
KEY_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")


# ── helpers ──────────────────────────────────────────────────────────────────
def _run(args: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "HERMES_HOME": str(HERMES_HOME)})
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as exc:
        return 1, str(exc)


def _read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text().splitlines():
            m = KEY_RE.match(line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def _set_env(values: dict[str, str]) -> None:
    """Merge KEY=VALUE pairs into ~/.hermes/.env, atomically, 0600. No echo."""
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    current = ENV_FILE.read_text().splitlines() if ENV_FILE.is_file() else []
    remaining = dict(values)
    out: list[str] = []
    for line in current:
        m = KEY_RE.match(line)
        if m and m.group(1) in remaining:
            k = m.group(1)
            out.append(f"{k}={remaining.pop(k)}")
        else:
            out.append(line)
    for k, v in remaining.items():
        out.append(f"{k}={v}")
    tmp = ENV_FILE.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_FILE)


def _mcp_list() -> list[dict]:
    """Parse `hermes mcp list` (and config.yaml) into server records."""
    cfg = HERMES_HOME / "config.yaml"
    servers: list[dict] = []
    if cfg.is_file():
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(cfg.read_text()) or {}
            for name, spec in (data.get("mcp_servers") or {}).items():
                kind = "url" if spec.get("url") else "stdio"
                servers.append({
                    "name": name,
                    "transport": spec.get("url") or
                                 (spec.get("command", "") + " " +
                                  " ".join(spec.get("args", []))).strip(),
                    "kind": kind,
                })
        except Exception:
            pass
    return servers


def _set_status(d: dict, key: str, env: dict) -> None:
    d[key] = bool(env.get(key))


# ── pages ────────────────────────────────────────────────────────────────────
def _hermes_dash_url():
    """Client-aware Hermes dashboard URL for the sidebar link.

    Prefer an explicit HERMES_DASH_URL; otherwise derive it from the Console
    user (SAFECLAW_UI_USER == the <CLIENT> slug) as
    https://hermes-<CLIENT>.growthsystems.ai. This keeps every cloned client
    Console pointed at THEIR dashboard, not a hard-coded one.
    """
    explicit = os.environ.get("HERMES_DASH_URL")
    if explicit:
        return explicit
    client = os.environ.get("SAFECLAW_UI_USER")
    if client:
        return f"https://hermes-{client}.growthsystems.ai"
    return "https://localhost:9119"


@app.get("/")
def index():
    return render_template("index.html", hermes_dash_url=_hermes_dash_url())


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ── dashboard ────────────────────────────────────────────────────────────────
@app.get("/api/status")
def api_status():
    env = _read_env()
    # gbrain page count — via the brain HTTP MCP (the CLI can't run while the
    # HTTP server holds the PGLite writer lock; template issue 22)
    ok, res = _brain_call("list_pages", {}, timeout=30)
    pages = len(res) if ok and isinstance(res, list) else None
    cfg = HERMES_HOME / "config.yaml"
    model = "(unset)"
    if cfg.is_file():
        try:
            import yaml  # type: ignore
            m = (yaml.safe_load(cfg.read_text()) or {}).get("model", {})
            model = f"{m.get('provider','?')} / {m.get('default', m.get('model','?'))}"
        except Exception:
            pass
    return jsonify({
        "brain_pages": pages,
        "model": model,
        "mcp_servers": _mcp_list(),
        "connected": {
            "slack": bool(env.get("SLACK_BOT_TOKEN")),
            "telegram": bool(env.get("TELEGRAM_BOT_TOKEN")),
            "gmail": bool(env.get("COMPOSIO_ACTOR_MCP_URL")),
            "llm": bool(env.get("OLLAMA_API_KEY") or env.get("OPENAI_API_KEY")
                        or env.get("ANTHROPIC_API_KEY")),
        },
    })


# ── MCP servers (incl. Zapier) ───────────────────────────────────────────────
@app.get("/api/mcp")
def api_mcp_list():
    return jsonify({"servers": _mcp_list()})


@app.post("/api/mcp")
def api_mcp_add():
    """Add an MCP server by URL (Zapier MCP, or any hosted MCP endpoint)."""
    body = request.get_json(silent=True) or {}
    name = re.sub(r"[^a-z0-9_-]", "", (body.get("name") or "").lower())
    url = (body.get("url") or "").strip()
    if not name or not url:
        return jsonify({"ok": False, "error": "name and url are required"}), 400
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "url must be http(s)"}), 400
    # `yes Y` auto-confirms the "enable all tools?" prompt.
    rc, out = _run(["bash", "-lc",
                    f"yes Y | {shlex.quote(HERMES_BIN)} mcp add {shlex.quote(name)} "
                    f"--url {shlex.quote(url)}"], timeout=90)
    if rc != 0 and "Saved" not in out:
        return jsonify({"ok": False, "error": out[-400:]}), 500
    return jsonify({"ok": True, "servers": _mcp_list()})


@app.delete("/api/mcp/<name>")
def api_mcp_remove(name: str):
    name = re.sub(r"[^a-z0-9_-]", "", name.lower())
    rc, out = _run(["bash", "-lc",
                    f"yes Y | {shlex.quote(HERMES_BIN)} mcp remove {shlex.quote(name)}"],
                   timeout=30)
    return jsonify({"ok": rc == 0, "servers": _mcp_list()})


# ── Slack / Telegram (secrets → .env, validated) ─────────────────────────────
@app.post("/api/slack")
def api_slack():
    b = request.get_json(silent=True) or {}
    tok = (b.get("SLACK_BOT_TOKEN") or "").strip()
    if validator:
        ok, msg = validator.validate_slack_bot(tok)
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
    vals = {k: b[k].strip() for k in SECRET_KEYS["slack"] if b.get(k)}
    _set_env(vals)
    return jsonify({"ok": True, "saved": list(vals)})


@app.post("/api/telegram")
def api_telegram():
    b = request.get_json(silent=True) or {}
    tok = (b.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if validator:
        ok, msg = validator.validate_telegram_bot(tok)
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
    vals = {k: b[k].strip() for k in SECRET_KEYS["telegram"] if b.get(k)}
    _set_env(vals)
    return jsonify({"ok": True, "saved": list(vals)})


# ── Gmail (Composio, multi-account) ──────────────────────────────────────────
COMPOSIO_API = "https://backend.composio.dev/api/v3"
# Reader = read-only; Actor = draft-only (NO send). The trust split.
GMAIL_READER_TOOLS = ["GMAIL_FETCH_EMAILS", "GMAIL_LIST_THREADS", "GMAIL_GET_PROFILE",
                      "GMAIL_FETCH_MESSAGE_BY_THREAD_ID", "GMAIL_GET_ATTACHMENT"]
GMAIL_ACTOR_TOOLS = ["GMAIL_CREATE_EMAIL_DRAFT", "GMAIL_REPLY_TO_THREAD",
                     "GMAIL_FETCH_EMAILS", "GMAIL_LIST_THREADS"]


def _composio(method, path, key, body=None):
    import urllib.request
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(f"{COMPOSIO_API}{path}", data=data, method=method,
                               headers={"x-api-key": key, "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r, timeout=25))
    except Exception as exc:
        return {"_error": str(exc)}


# ── One-click Composio OAuth connect (the customer "connect your accounts" page) ──
# Serves the per-client connect-cards page (templates/connect.html) and mints a
# fresh Composio OAuth link per click — the on-box port of the old Netlify
# connect.js. The per-service auth_config_id / user_id / alias map lives in a
# per-client JSON (COMPOSIO_SERVICES_FILE, default /opt/safeclaw/composio-services.json)
# so the same template serves every client; only the JSON + COMPOSIO_API_KEY differ.
# The API key stays server-side — the browser only ever gets the redirect_url.
def _composio_services() -> dict:
    path = os.environ.get("COMPOSIO_SERVICES_FILE", "/opt/safeclaw/composio-services.json")
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


@app.get("/connect-accounts")
def connect_accounts():
    return render_template("connect.html")


@app.get("/connect")
def composio_connect():
    service = (request.args.get("service") or "").strip()
    svc = _composio_services().get(service)
    if not svc:
        return Response("Unknown service. Go back and choose one of the listed Connect buttons.",
                        400, {"Content-Type": "text/plain; charset=utf-8"})
    key = os.environ.get("COMPOSIO_API_KEY", "").strip()
    if not key:
        return Response("Setup is missing a server-side Composio key. Please contact your admin.",
                        500, {"Content-Type": "text/plain; charset=utf-8"})
    d = _composio("POST", "/connected_accounts/link", key, {
        "auth_config_id": svc["auth_config_id"],
        "user_id": svc["user_id"],
        "alias": svc.get("alias", service),
    })
    url = d.get("redirect_url") if isinstance(d, dict) else None
    if not url:
        return Response(f"Could not create a {svc.get('label', service)} connection link. "
                        f"Please contact your admin.", 502, {"Content-Type": "text/plain; charset=utf-8"})
    return redirect(url, code=302)


@app.get("/api/composio/status")
def composio_status():
    """Per-service connection status for the connect page, keyed by service.
    Returns e.g. {"gmail":"ACTIVE","calendar":"EXPIRED","googledocs":"ACTIVE"}.
    The page uses this to badge already-connected services instead of "Ready"."""
    key = os.environ.get("COMPOSIO_API_KEY", "").strip()
    services = _composio_services()
    if not key or not services:
        return jsonify({})
    d = _composio("GET", "/connected_accounts?limit=100", key)
    by_uid = {}
    if isinstance(d, dict):
        for a in (d.get("items") or []):
            uid, s = a.get("user_id"), a.get("status")
            if not uid:
                continue
            # A user_id can have several accounts (e.g. a fresh pending one from a
            # re-click). ACTIVE wins — never let a later non-active overwrite it.
            if by_uid.get(uid) == "ACTIVE":
                continue
            by_uid[uid] = s
    return jsonify({svc: by_uid.get((cfg or {}).get("user_id"))
                    for svc, cfg in services.items()})


@app.get("/api/gmail/accounts")
def api_gmail_accounts():
    """List Gmail accounts connected to a Composio API key. Key alone is enough —
    we auto-discover the connected accounts (each has a unique connected_account_id
    even when they share a user_id)."""
    key = (request.args.get("key") or "").strip()
    if not key.startswith("ak_"):
        return jsonify({"ok": False, "error": "Composio API key (ak_…) required"}), 400
    d = _composio("GET", "/connected_accounts?limit=50", key)
    if d.get("_error"):
        return jsonify({"ok": False, "error": d["_error"]}), 502
    out = []
    for a in d.get("items", []):
        if ((a.get("toolkit") or {}).get("slug") or "").lower() != "gmail":
            continue
        out.append({
            "ca_id": a.get("id"),
            "user_id": a.get("user_id"),
            "status": a.get("status"),
            "created": (a.get("created_at") or "")[:19],
        })
    return jsonify({"ok": True, "accounts": out})


@app.post("/api/gmail/wire")
def api_gmail_wire():
    """Wire selected Gmail accounts. Each selected connected_account_id gets a
    reader (read-only) MCP on the reader profile and an actor (draft) MCP on the
    actor profile, routed by connected_account_id so multiple accounts stay
    distinct even under one user_id."""
    b = request.get_json(silent=True) or {}
    key = (b.get("key") or "").strip()
    accounts = b.get("accounts") or []  # [{ca_id, label}]
    if not key.startswith("ak_") or not accounts:
        return jsonify({"ok": False, "error": "key + at least one account required"}), 400

    # find/create the gmail auth_config (MCP servers reference it)
    ac = _composio("GET", "/auth_configs?toolkit_slug=gmail&limit=5", key)
    items = ac.get("items", [])
    if not items:
        return jsonify({"ok": False, "error": "no gmail auth_config found"}), 400
    acid = items[0]["id"]

    # map connected_account_id -> its user_id AND its auth_config. Accounts
    # connected through different auth configs MUST have their MCP server bound
    # to THEIR config, or execution fails with "No connected account found".
    ca_to_uid, ca_to_acid = {}, {}
    for a in _composio("GET", "/connected_accounts?limit=50", key).get("items", []):
        ca_to_uid[a.get("id")] = a.get("user_id")
        ca_to_acid[a.get("id")] = ((a.get("auth_config") or {}).get("id")
                                   or a.get("auth_config_id"))

    wired = []
    for acct in accounts:
        ca = acct.get("ca_id")
        uid = ca_to_uid.get(ca, "")
        acct_acid = ca_to_acid.get(ca) or acid
        label = re.sub(r"[^a-z0-9]", "", (acct.get("label") or ca).lower())[:20] or "acct"
        for role, tools in (("reader", GMAIL_READER_TOOLS), ("actor", GMAIL_ACTOR_TOOLS)):
            # one client per workspace, so no client name needed in the MCP server name
            srv = _composio("POST", "/mcp/servers", key, {
                "name": f"safeclaw-{role}-{label}",
                "auth_config_ids": [acct_acid], "allowed_tools": tools,
                "managed_auth_via_composio": True,
            })
            url = srv.get("mcp_url") or srv.get("url")
            if not url:  # name already exists — reuse ONLY if its auth config matches
                lst = _composio("GET", "/mcp/servers?limit=100", key)
                existing = next((s for s in lst.get("items", [])
                                 if s.get("name") == f"safeclaw-{role}-{label}"), None)
                if existing and existing.get("auth_config_ids") == [acct_acid]:
                    url = existing.get("mcp_url")
                elif existing:
                    # bound to the WRONG auth config (e.g. another inbox's) —
                    # delete and recreate. NOTE: item route is /mcp/{id}, not /mcp/servers/{id}.
                    _composio("DELETE", f"/mcp/{existing['id']}", key)
                    srv = _composio("POST", "/mcp/servers", key, {
                        "name": f"safeclaw-{role}-{label}",
                        "auth_config_ids": [acct_acid], "allowed_tools": tools,
                        "managed_auth_via_composio": True,
                    })
                    url = srv.get("mcp_url") or srv.get("url")
            if url:
                # BOTH params required: user_id authenticates the Composio entity,
                # connected_account_id targets the specific inbox. user_id alone
                # is ambiguous with multiple accounts; connected_account_id ALONE
                # is rejected by Composio at execution ("user ID does not match").
                full = f"{url.rstrip('/')}/mcp?user_id={uid}&connected_account_id={ca}"
                _add_gmail_mcp_to_profile(role, f"gmail_{label}", full, key)
                wired.append({"role": role, "label": label, "ca_id": ca})
    # reload the actor gateway so new tools register
    _run(["bash", "-lc",
          "tmux kill-session -t gw 2>/dev/null; sleep 4; "
          "tmux new-session -d -s gw 'export HERMES_HOME=/root/.hermes/profiles/actor "
          "PATH=/root/.bun/bin:/tmp/node-v20.18.1-linux-x64/bin:$PATH HERMES_ALLOW_ROOT_GATEWAY=1; "
          "exec /opt/hermes/venv/bin/hermes gateway run > /tmp/gw.log 2>&1'"], timeout=30)
    return jsonify({"ok": True, "wired": wired})


def _add_gmail_mcp_to_profile(role, name, url, key):
    """Write a gmail MCP server (url + x-api-key header) into a profile's
    config.yaml — Hermes `mcp add --url` can't attach headers, so we edit YAML."""
    import yaml
    # profiles live at <hermes_home_root>/profiles/<role>; HERMES_HOME may already
    # point at the default home, so resolve the profiles dir from its root.
    root = HERMES_HOME
    if root.name in ("reader", "actor") and root.parent.name == "profiles":
        root = root.parent.parent
    cfg_path = root / "profiles" / role / "config.yaml"
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    except Exception:
        cfg = {}
    cfg = cfg or {}
    servers = cfg.setdefault("mcp_servers", {})
    servers[name] = {
        "url": url, "headers": {"x-api-key": key},
        "timeout": 120, "connect_timeout": 30,
    }
    # drop the stale single-account "gmail" once per-account servers exist, so
    # tools aren't duplicated across an ambiguous + specific server.
    if name.startswith("gmail_") and "gmail" in servers:
        del servers["gmail"]
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))


# ── Self-test: "is everything working?" battery for the Dashboard ────────────
def _check(name, fn):
    """Run one check, never raise — return {name, ok, detail}."""
    try:
        ok, detail = fn()
        return {"name": name, "ok": bool(ok), "detail": str(detail)[:300]}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc)[:300]}


def _profiles_root() -> Path:
    root = HERMES_HOME
    if root.name in ("reader", "actor") and root.parent.name == "profiles":
        root = root.parent.parent
    return root / "profiles"


def _gmail_mcp_servers(role: str) -> dict[str, dict]:
    """gmail_* MCP entries from a profile's config.yaml: {name: {url, key}}."""
    import yaml
    cfg_path = _profiles_root() / role / "config.yaml"
    if not cfg_path.exists():
        return {}
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    out = {}
    for name, spec in (cfg.get("mcp_servers") or {}).items():
        if name.startswith("gmail") and spec.get("url"):
            out[name] = {"url": spec["url"],
                         "key": (spec.get("headers") or {}).get("x-api-key", "")}
    return out


def _mcp_call(url: str, key: str, tool: str, args: dict) -> tuple[bool, str]:
    """Call one tool on a Composio MCP server; True if it returns a non-error result."""
    import urllib.request
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": args}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "x-api-key": key, "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    # Composio answers in SSE framing: "event: message\ndata: {...}"
    data_line = next((l[5:].strip() for l in raw.splitlines() if l.startswith("data:")), raw)
    try:
        d = json.loads(data_line)
    except Exception:
        return False, raw[:200]
    result = d.get("result") or {}
    if result.get("isError"):
        txt = "".join(c.get("text", "") for c in result.get("content", []))
        return False, txt[:200]
    return True, "ok"


@app.get("/api/selftest")
def api_selftest():
    """Run the full 'is everything working?' battery. Each check is independent
    and never raises; the UI renders one ✅/❌ row per check."""
    env = _read_env()
    checks = []

    def _hermes_check():
        rc, out = _run([HERMES_BIN, "--version"], timeout=20)
        return rc == 0, (out.strip().splitlines() or ["no output"])[0]
    checks.append(_check("Hermes CLI", _hermes_check))

    def _gbrain_check():
        # Via the brain HTTP MCP — the gbrain CLI deadlocks on the PGLite writer
        # lock while `gbrain serve --http` (tmux `brain`) is running (issue 22).
        ok, res = _brain_call("list_pages", {}, timeout=60)
        n = len(res) if ok and isinstance(res, list) else None
        return ok, (f"responds ({n} pages)" if ok else str(res)[:120] or "no reply")
    checks.append(_check("GBrain (knowledge brain)", _gbrain_check))

    def _embeddings_check():
        # "Installed but not initialized" guard: a brain with no embedding
        # provider (or unembedded chunks) means semantic search + the dream
        # embed phase silently don't work. Surface it on the SYSTEM TEST card.
        ok, stats = _brain_call("get_stats", {}, timeout=30)
        if not ok or not isinstance(stats, dict):
            return False, "brain unreachable — cannot verify embeddings"
        chunks = stats.get("chunk_count", 0)
        embedded = stats.get("embedded_count", 0)
        if chunks == 0:
            return True, "no content yet (seed a page to verify embeddings)"
        if embedded < chunks:
            return False, (f"only {embedded}/{chunks} chunks embedded — embedding "
                           "provider missing or its API key is dead")
        return True, f"all {embedded}/{chunks} chunks embedded"
    checks.append(_check("Embeddings (semantic search)", _embeddings_check))

    def _profiles_check():
        missing = [r for r in ("reader", "actor")
                   if not (_profiles_root() / r / "config.yaml").exists()]
        return (not missing, "reader + actor configured" if not missing
                else f"missing profile(s): {', '.join(missing)}")
    checks.append(_check("Trust-split profiles", _profiles_check))

    # Gmail: a REAL tools/call per wired account on the actor profile (this is
    # the call that fails when the MCP URL/auth is mis-wired).
    actor_gmail = _gmail_mcp_servers("actor")
    if not actor_gmail:
        checks.append({"name": "Gmail (Composio)", "ok": False,
                       "detail": "no Gmail accounts wired yet — use the Gmail panel"})
    for name, spec in actor_gmail.items():
        # FETCH_EMAILS is in both the reader and actor allowlists — a real fetch
        # is the truest "Gmail works" signal (auth + account routing + tool perms).
        checks.append(_check(f"Gmail · {name}", lambda s=spec: _mcp_call(
            s["url"], s["key"], "GMAIL_FETCH_EMAILS", {"max_results": 1})))

    def _telegram_check():
        rc, _ = _run(["pgrep", "-f", "hermes gateway run"], timeout=10)
        actor_env = _profiles_root() / "actor" / ".env"
        has_token = actor_env.exists() and "TELEGRAM_BOT_TOKEN=" in actor_env.read_text() \
            and not re.search(r"TELEGRAM_BOT_TOKEN=\s*$", actor_env.read_text(), re.M)
        if not has_token:
            return False, "no bot token in actor profile — use the Telegram panel"
        return rc == 0, "gateway running, bot token set" if rc == 0 \
            else "bot token set but gateway NOT running"
    checks.append(_check("Telegram agent", _telegram_check))

    def _tunnel_check():
        import yaml, urllib.request
        cf_cfg = Path("/root/.cloudflared/config.yaml")
        if not cf_cfg.exists():
            return False, "no cloudflared config on this box"
        ing = (yaml.safe_load(cf_cfg.read_text()) or {}).get("ingress", [])
        host = next((i.get("hostname") for i in ing if i.get("hostname")), None)
        if not host:
            return False, "no hostname in tunnel config"
        # curl UA: Cloudflare 403s bare python-urllib requests from the box.
        req = urllib.request.Request(f"https://{host}/", method="HEAD",
                                     headers={"User-Agent": "curl/8.0"})
        try:
            code = urllib.request.urlopen(req, timeout=15).status
        except urllib.error.HTTPError as e:
            code = e.code
        # 200/401/403 = Cloudflare answered for this host → tunnel is connected.
        # 530/52x = tunnel down.
        return code in (200, 401, 403), f"https://{host} → {code}"
    checks.append(_check("Public URL (tunnel)", _tunnel_check))

    def _clock_check():
        import urllib.request, email.utils, datetime
        r = urllib.request.urlopen(urllib.request.Request(
            "https://www.cloudflare.com", method="HEAD",
            headers={"User-Agent": "curl/8.0"}), timeout=10)
        net = email.utils.parsedate_to_datetime(r.headers["Date"])
        drift = abs((datetime.datetime.now(datetime.timezone.utc) - net).total_seconds())
        return drift < 120, f"clock drift {int(drift)}s"
    checks.append(_check("Box clock", _clock_check))

    def _llm_check():
        return (bool(env.get("OLLAMA_API_KEY") or env.get("OPENAI_API_KEY")
                     or env.get("ANTHROPIC_API_KEY")),
                "LLM API key set (use Quick Chat to test a real reply)")
    checks.append(_check("LLM key", _llm_check))

    return jsonify({"ok": all(c["ok"] for c in checks), "checks": checks})


# ── Google Drive (service-account JSON) ──────────────────────────────────────
@app.post("/api/chat")
def api_chat():
    """Send a one-shot message to Hermes (kimi via Ollama) and return its reply.

    Runs `hermes chat -q <msg>` server-side — Hermes loads the gbrain MCP, so
    answers are brain-backed. Synchronous; the agent loop can take ~20-40s.
    """
    b = request.get_json(silent=True) or {}
    msg = (b.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "error": "empty message"}), 400
    if len(msg) > 2000:
        return jsonify({"ok": False, "error": "message too long"}), 400
    try:
        r = subprocess.run(
            [HERMES_BIN, "chat", "-q", msg, "-Q"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "HERMES_HOME": str(HERMES_HOME),
                 "HERMES_ALLOW_ROOT_GATEWAY": "1"},
        )
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Hermes timed out (>120s)"}), 504
    out = (r.stdout or "").strip()
    # Strip ANSI escape codes and the box-drawing chrome Hermes prints.
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)
    out = "\n".join(l for l in out.splitlines()
                    if not re.match(r"^[\s│┊─╶╴⚡⚕✓✗]*$", l)
                    and "Resume this session" not in l
                    and not l.startswith(("Session:", "Duration:", "Messages:")))
    if not out:
        out = (r.stderr or "Hermes returned no output").strip()[:500]
    return jsonify({"ok": True, "reply": out})


@app.post("/api/gdrive")
def api_gdrive():
    b = request.get_json(silent=True) or {}
    raw = (b.get("GDRIVE_SERVICE_ACCOUNT_JSON") or "").strip()
    if validator:
        errs = validator.validate_gdrive({"GDRIVE_SERVICE_ACCOUNT_JSON": raw})
        if errs:
            return jsonify({"ok": False, "error": next(iter(errs.values()))}), 400
    dest = Path(os.environ.get("GDRIVE_CREDENTIALS_PATH",
                               "/opt/config/drive_credentials.json"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(raw)
    try:
        email = json.loads(raw).get("client_email", "")
    except Exception:
        email = ""
    return jsonify({"ok": True, "client_email": email, "path": str(dest)})


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8899")), debug=False)
