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

import logging
import os
import re
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
