"""SafeClaw — Onboarding Webapp (Flask)

Routes:
  GET  /                      Landing page
  GET  /setup                 4-step form
  GET  /help                  Setup help (Slack walkthrough, troubleshooting)
  GET  /done/<id>             Success page after a provision finishes
  GET  /progress/<id>         Live progress page (consumes SSE)
  POST /api/provision         Kicks off install. Returns {install_id}.
  GET  /api/progress/<id>     SSE event stream of install progress
  GET  /api/status/<id>       Polling fallback — JSON snapshot of events
  GET  /api/healthz           Liveness probe

Notes:
  * SSE state is in-memory (see lib/progress.py). Single-process gunicorn
    with --threads is the supported deploy model.
  * No customer secret ever leaves this VPS — provisioning happens on-box.
  * The webapp itself runs inside a container with /safeclaw bind-mounted
    and access to /var/run/docker.sock so it can drive `docker compose`.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from lib import provisioner
from lib.progress import registry

# ── Config ────────────────────────────────────────────────────────────────
INSTALL_DIR = Path(os.environ.get("SAFECLAW_INSTALL_DIR", "/safeclaw"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("safeclaw.app")


# ── Dashboard ─────────────────────────────────────────────────────────────
# Container names use a prefix that matches the compose project. Default is
# unprefixed ("") for the canonical customer deployment (project = "safeclaw");
# operators running a custom-named project (e.g. Vasanth's local "vasanth-safeclaw")
# can override via env var.
#   SAFECLAW_CONTAINER_PREFIX="vasanth-"  →  vasanth-safeclaw-hermes-reader, ...
_CONTAINER_PREFIX = os.environ.get("SAFECLAW_CONTAINER_PREFIX", "")

# brain-api-mcp / tasks-api-mcp / slack-api-mcp / drive-api-mcp were sidecar
# containers; they are now baked into the Hermes image (see
# Dockerfile.safeclaw-hermes Stage B) and run as Node/Python subprocesses
# inside hermes-reader / hermes-actor. No standalone container to track.
_CONTAINERS = {
    f"{_CONTAINER_PREFIX}safeclaw-hermes-reader":  {"label": "Reader Agent",  "kind": "agent"},
    f"{_CONTAINER_PREFIX}safeclaw-hermes-actor":   {"label": "Actor Agent",   "kind": "agent"},
    f"{_CONTAINER_PREFIX}safeclaw-postgres-obs":   {"label": "Obs DB",        "kind": "infra"},
    f"{_CONTAINER_PREFIX}safeclaw-postgres-tasks": {"label": "Tasks DB",      "kind": "infra"},
    f"{_CONTAINER_PREFIX}safeclaw-postgrest":      {"label": "PostgREST",     "kind": "infra"},
    f"{_CONTAINER_PREFIX}safeclaw-embedder":       {"label": "Embedder",      "kind": "infra"},
    f"{_CONTAINER_PREFIX}safeclaw-reflector":      {"label": "Reflector",     "kind": "infra"},
}


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.url_map.strict_slashes = False

    # ── Pages ─────────────────────────────────────────────────────────────
    @app.get("/")
    def landing():
        return render_template("landing.html")

    @app.get("/setup")
    def setup():
        return render_template("setup.html")

    @app.get("/help")
    def help_page():
        return render_template("help.html")

    @app.get("/progress/<install_id>")
    def progress_page(install_id: str):
        if not _valid_install_id(install_id):
            abort(404)
        if registry.get(install_id) is None:
            abort(404)
        return render_template("progress.html", install_id=install_id)

    @app.get("/done/<install_id>")
    def done_page(install_id: str):
        if not _valid_install_id(install_id):
            abort(404)
        return render_template("done.html", install_id=install_id)

    # ── API ───────────────────────────────────────────────────────────────
    @app.get("/api/healthz")
    @app.get("/health")           # alias used by provision-vps.sh + reverse proxies
    def healthz():
        return {"ok": True}, 200

    @app.get("/api/config")
    def api_config():
        """Return current .env values for form pre-population.
        Returns actual values so the user can edit them. Only ALLOWED_KEYS
        are returned — no generated secrets (JWT, DB passwords, etc.)."""
        from lib import env_writer
        from lib.env_writer import KEY_LINE_RE, ALLOWED_KEYS, PLACEHOLDERS
        env_path = Path(INSTALL_DIR) / ".env"
        if not env_path.is_file():
            return jsonify({}), 200
        result: dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            m = KEY_LINE_RE.match(line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip('"').strip("'")
            if key in ALLOWED_KEYS and val and val not in PLACEHOLDERS:
                result[key] = val
        return jsonify(result), 200

    @app.post("/api/save")
    def api_save():
        """Persist one or more config fields to .env without provisioning.
        Merges onto any existing .env so partial saves from different steps
        don't overwrite each other."""
        if not request.is_json:
            return jsonify({"success": False, "error": "JSON body required"}), 400
        form = request.get_json(force=True, silent=False) or {}
        from lib import env_writer
        filtered = {
            k: str(v) for k, v in form.items()
            if k in env_writer.ALLOWED_KEYS and v not in (None, "")
        }
        if not filtered:
            return jsonify({"success": False, "error": "No valid fields to save"}), 400
        try:
            env_writer.write_env(INSTALL_DIR, filtered)
            return jsonify({"success": True, "saved": list(filtered.keys())}), 200
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.post("/api/slack/lookup")
    def api_slack_lookup():
        """Resolve a bot token → team_id + user_id via Slack auth.test."""
        data = request.get_json(silent=True) or {}
        token = (data.get("bot_token") or "").strip()
        if not token.startswith("xoxb-"):
            return jsonify({"ok": False, "error": "invalid token format"}), 400
        import requests as _req
        try:
            r = _req.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            body = r.json()
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502
        if not body.get("ok"):
            return jsonify({"ok": False, "error": body.get("error", "slack_error")}), 400
        return jsonify({"ok": True, "team_id": body["team_id"], "user_id": body.get("user_id", "")})

    @app.get("/api/slack/list-channels")
    def api_slack_list_channels():
        """Return all public channels (and private ones the bot is in) via conversations.list."""
        token = (request.args.get("bot_token") or "").strip()
        if not token.startswith("xoxb-"):
            return jsonify({"ok": False, "error": "invalid token format"}), 400
        import requests as _req
        channels = []
        cursor = None
        try:
            while True:
                params = {"types": "public_channel,private_channel", "exclude_archived": "true", "limit": 200}
                if cursor:
                    params["cursor"] = cursor
                r = _req.get(
                    "https://slack.com/api/conversations.list",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                body = r.json()
                if not body.get("ok"):
                    return jsonify({"ok": False, "error": body.get("error", "slack_error")}), 400
                for ch in body.get("channels", []):
                    channels.append({"id": ch["id"], "name": ch.get("name", ch["id"]), "is_private": ch.get("is_private", False)})
                cursor = body.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502
        channels.sort(key=lambda c: c["name"])
        return jsonify({"ok": True, "channels": channels})

    @app.post("/api/slack/check-channels")
    def api_slack_check_channels():
        """Check whether the bot can see each channel ID."""
        data = request.get_json(silent=True) or {}
        token = (data.get("bot_token") or "").strip()
        channel_ids = [c.strip() for c in (data.get("channel_ids") or []) if c.strip()]
        if not token.startswith("xoxb-"):
            return jsonify({"ok": False, "error": "invalid token format"}), 400
        import requests as _req
        results = []
        for cid in channel_ids[:20]:  # hard cap
            try:
                r = _req.get(
                    "https://slack.com/api/conversations.info",
                    params={"channel": cid},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=6,
                )
                body = r.json()
                if body.get("ok"):
                    ch = body.get("channel", {})
                    results.append({"id": cid, "ok": True, "name": ch.get("name", cid)})
                else:
                    results.append({"id": cid, "ok": False, "error": body.get("error", "unknown")})
            except Exception as exc:
                results.append({"id": cid, "ok": False, "error": str(exc)})
        return jsonify({"ok": True, "channels": results})

    @app.post("/api/gdrive/validate")
    def api_gdrive_validate():
        """Parse a service-account JSON string and return the client_email."""
        data = request.get_json(silent=True) or {}
        raw = (data.get("json_str") or "").strip()
        if not raw:
            return jsonify({"ok": False, "error": "No JSON provided"}), 400
        from lib.validator import validate_gdrive
        errors = validate_gdrive({"GDRIVE_SERVICE_ACCOUNT_JSON": raw})
        if errors:
            return jsonify({"ok": False, "error": next(iter(errors.values()))}), 400
        try:
            creds = json.loads(raw)
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid JSON"}), 400
        return jsonify({
            "ok": True,
            "client_email": creds.get("client_email", ""),
            "project_id": creds.get("project_id", ""),
        })

    @app.post("/api/provision")
    def api_provision():
        # Reject anything that isn't JSON — keeps form parsers honest.
        if not request.is_json:
            return jsonify({"success": False, "error": "JSON body required"}), 400

        try:
            form = request.get_json(force=True, silent=False) or {}
        except Exception:
            return jsonify({"success": False, "error": "invalid JSON"}), 400

        if not isinstance(form, dict):
            return jsonify({"success": False, "error": "JSON body must be an object"}), 400

        # Hard cap on body size to prevent abuse.
        if request.content_length and request.content_length > 64 * 1024:
            return jsonify({"success": False, "error": "payload too large"}), 413

        # Run validators inline before kicking off the background thread —
        # this is what gives us the "fix all bad fields without re-asking"
        # UX. provisioner will run the same validation again, but cheap.
        from lib import validator
        errors = validator.validate_all(form)
        if errors:
            return jsonify({"success": False, "errors": errors}), 400

        install_id = uuid.uuid4().hex[:16]
        install = registry.create(install_id)

        # Kick off the provision in a background thread so the HTTP request
        # can return immediately. Daemon=True so it doesn't block process
        # shutdown.
        thread = threading.Thread(
            target=provisioner.run,
            args=(install, form, INSTALL_DIR),
            name=f"provision-{install_id}",
            daemon=True,
        )
        thread.start()

        return jsonify({"success": True, "install_id": install_id}), 202

    @app.get("/api/progress/<install_id>")
    def api_progress(install_id: str):
        if not _valid_install_id(install_id):
            abort(404)
        install = registry.get(install_id)
        if install is None:
            abort(404)

        # Last-Event-ID lets clients resume mid-stream after a network blip.
        last_event_id = request.headers.get("Last-Event-ID", "0")
        try:
            last_index = max(0, int(last_event_id))
        except ValueError:
            last_index = 0

        @stream_with_context
        def stream():
            yield from install.subscribe(last_index=last_index)

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        }
        return Response(stream(), headers=headers)

    @app.get("/api/status/<install_id>")
    def api_status(install_id: str):
        if not _valid_install_id(install_id):
            abort(404)
        install = registry.get(install_id)
        if install is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "install_id": install_id,
            "closed": install.is_closed(),
            "events": install.snapshot(),
        })

    # ── Dashboard ─────────────────────────────────────────────────────────
    @app.get("/dashboard")
    def dashboard():
        # Pass the prefixed container list so the log-stream dropdown shows
        # the correct names for whichever compose project is deployed.
        return render_template(
            "dashboard.html",
            container_options=[
                {"value": cname, "label": meta["label"]}
                for cname, meta in _CONTAINERS.items()
            ],
        )

    @app.get("/api/services")
    def api_services():
        results = []
        names = list(_CONTAINERS.keys())
        # `docker inspect a b c` returns exit 1 if any one is missing — but
        # stdout still contains valid JSON for the ones that exist. Parse
        # stdout regardless of exit code so a single absent container doesn't
        # mark all of them absent. Anything missing falls through to the
        # "absent" branch in the per-container loop below.
        inspected = []
        try:
            raw = subprocess.run(
                ["docker", "inspect"] + names,
                capture_output=True, text=True, timeout=8,
            )
            try:
                inspected = json.loads(raw.stdout) if raw.stdout.strip() else []
            except json.JSONDecodeError:
                inspected = []
        except Exception:
            inspected = []

        inspected_by_name = {c["Name"].lstrip("/"): c for c in inspected}

        for cname, meta in _CONTAINERS.items():
            c = inspected_by_name.get(cname)
            if c is None:
                results.append({**meta, "container": cname, "status": "absent", "uptime": None, "health": None})
                continue
            state = c.get("State", {})
            running = state.get("Running", False)
            status = "running" if running else "stopped"
            started_at = state.get("StartedAt", "")
            uptime_str = None
            if running and started_at:
                try:
                    dt = datetime.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    delta = datetime.datetime.now(datetime.timezone.utc) - dt
                    secs = int(delta.total_seconds())
                    h, m = divmod(secs // 60, 60)
                    uptime_str = f"{h}h {m:02d}m" if h else f"{m}m"
                except Exception:
                    pass
            health = None
            hc = state.get("Health")
            if hc:
                health = hc.get("Status")
            results.append({**meta, "container": cname, "status": status, "uptime": uptime_str, "health": health})
        return jsonify(results)

    @app.get("/api/logs/<service>")
    def api_logs(service: str):
        if service not in _CONTAINERS:
            abort(404)
        tail = request.args.get("tail", "200")
        try:
            tail = str(max(1, min(2000, int(tail))))
        except ValueError:
            tail = "200"

        @stream_with_context
        def _stream():
            try:
                proc = subprocess.Popen(
                    ["docker", "logs", "--tail", tail, "-f", "--timestamps", service],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    yield f"data: {json.dumps(line)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps(f'[error] {exc}')}\n\n"

        return Response(_stream(), content_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/services/<service>/restart")
    def api_restart(service: str):
        if service not in _CONTAINERS:
            abort(404)
        try:
            r = subprocess.run(
                ["docker", "restart", service],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                return jsonify({"ok": False, "error": r.stderr.strip()}), 500
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify({"ok": True})

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(500)
    def server_error(_e):
        log.exception("internal server error")
        return jsonify({"error": "internal server error"}), 500

    return app


# ── Helpers ───────────────────────────────────────────────────────────────
_INSTALL_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")


def _valid_install_id(install_id: str) -> bool:
    return bool(_INSTALL_ID_RE.match(install_id or ""))


# Module-level app for gunicorn `app:app`.
app = create_app()


if __name__ == "__main__":
    # Dev mode: `python app.py`
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
