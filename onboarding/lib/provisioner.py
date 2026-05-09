"""Orchestrates the SafeClaw install: validate form -> write env -> secrets
-> docker compose -> bootstrap brain -> welcome.

Each phase emits SSE events via the Install instance from progress.py.

Errors do NOT raise out of run(); they're emitted as `phase=<name>,
status=error` events and the run terminates gracefully so the SSE stream
ends with a valid `done` close. The HTTP layer never sees an exception
from a background thread.

Composio note:
    The four COMPOSIO_* keys are supplied by the customer in Step 2 of the
    onboarding form (Composio is their account, where they did the OAuth
    dance for Gmail / Drive / Slack). They're validated alongside the LLM
    and Slack creds in the `validating` phase, then written to .env in
    `env_writing`.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from . import env_writer, validator
from .progress import Install

log = logging.getLogger("safeclaw.provisioner")

# Phase identifiers — kept stable so the frontend can keymap them to icons.
PHASES = [
    "validating",
    "env_writing",
    "secrets",
    "compose_pull",
    "compose_up",
    "waiting_health",
    "bootstrap",
    "welcome",
    "done",
]


class ProvisionError(Exception):
    """Raised internally to abort the run with a user-facing message."""

    def __init__(self, phase: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.phase = phase
        self.message = message
        self.hint = hint


def _emit(install: Install, phase: str, status: str, message: str, **extra) -> None:
    payload = {"phase": phase, "status": status, "message": message}
    payload.update(extra)
    install.publish(payload)


def _run_cmd(
    cmd: list[str],
    cwd: str | Path,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """Run a shell command and capture output. Never raises — returns the
    CompletedProcess so the caller can inspect returncode."""
    log.info("running: %s (cwd=%s)", shlex.join(cmd), cwd)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _tail_output(proc: subprocess.CompletedProcess, max_chars: int = 800) -> str:
    """Combine stdout + stderr and tail to last N chars for SSE display."""
    blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if len(blob) > max_chars:
        return "...\n" + blob[-max_chars:]
    return blob


# ── Phase implementations ─────────────────────────────────────────────────


def _phase_validate(install: Install, install_dir: Path, form: dict) -> None:
    _emit(install, "validating", "start", "Checking your credentials...")
    errors = validator.validate_all(form)
    if errors:
        # Surface ALL errors at once so the customer can fix them in one pass.
        details = "; ".join(f"{k}: {v}" for k, v in errors.items())
        raise ProvisionError(
            "validating",
            "Some credentials didn't check out.",
            hint=details,
        )
    _emit(install, "validating", "ok", "Credentials look good.")


def _phase_env(install: Install, install_dir: Path, form: dict) -> None:
    _emit(install, "env_writing", "start", "Writing configuration to .env...")

    # Server-side: derive base_url + model from the customer's provider radio
    # selection. Customer never sees these — they're infrastructure detail.
    provider = (form.get("llm_provider") or "ollama-cloud").strip()
    LLM_PRESETS = {
        "ollama-cloud": {
            "HERMES_INFERENCE_PROVIDER": "ollama-cloud",
            "OLLAMA_BASE_URL": "http://host.docker.internal:11435/v1",
            "HERMES_DEFAULT_MODEL": "glm-5.1:cloud",
        },
        "anthropic": {
            "HERMES_INFERENCE_PROVIDER": "anthropic",
            "OLLAMA_BASE_URL": "https://api.anthropic.com/v1",
            "HERMES_DEFAULT_MODEL": "claude-sonnet-4-6",
        },
        "openai": {
            "HERMES_INFERENCE_PROVIDER": "openai",
            "OLLAMA_BASE_URL": "https://api.openai.com/v1",
            "HERMES_DEFAULT_MODEL": "gpt-4o",
        },
    }
    preset = LLM_PRESETS.get(provider, LLM_PRESETS["ollama-cloud"])

    # Whitelist-driven mapping: only keys env_writer.ALLOWED_KEYS will land
    # in .env. Anything else the form posted is ignored.
    values = {k: v for k, v in form.items() if k in env_writer.ALLOWED_KEYS}

    # Move customer's API key from form's `LLM_API_KEY` into the right env var.
    # All three providers use OLLAMA_API_KEY downstream (env name is legacy;
    # actually any OpenAI-compatible endpoint reads from this slot).
    api_key = form.get("LLM_API_KEY", "").strip()
    if api_key:
        values["OLLAMA_API_KEY"] = api_key

    # Layer the provider preset on top — these always win over form input
    # so a customer can't accidentally point at the wrong endpoint.
    values.update(preset)

    # ── Composio Provisioning ────────────────────────────────────────────────
    # Automatically create the safeclaw-reader and safeclaw-actor MCP servers
    # using the customer's API key.
    composio_api_key = form.get("COMPOSIO_API_KEY", "").strip()
    composio_user_id = form.get("COMPOSIO_USER_ID", "").strip()
    if composio_api_key and composio_user_id:
        try:
            _emit(install, "env_writing", "progress", "Provisioning Composio MCP servers...")
            mcp_urls = validator.provision_composio_mcps(composio_api_key, composio_user_id)
            values.update(mcp_urls)
        except Exception as exc:
            raise ProvisionError(
                "env_writing",
                "Composio provisioning failed.",
                hint=str(exc)
            )

    try:
        env_writer.write_env(install_dir, values)
    except env_writer.EnvWriteError as exc:
        raise ProvisionError(
            "env_writing", f"could not write .env: {exc}",
            hint="Check filesystem permissions on the install directory.",
        ) from exc

    # Save Google Drive service-account JSON as a separate credentials file.
    gdrive_json = form.get("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    if gdrive_json:
        _emit(install, "env_writing", "progress", "Saving Drive credentials...")
        config_dir = install_dir / "config"
        config_dir.mkdir(exist_ok=True)
        creds_path = config_dir / "drive_credentials.json"
        fd, tmp = tempfile.mkstemp(prefix=".gdrive_creds.tmp.", dir=str(config_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(gdrive_json)
            os.chmod(tmp, 0o600)
            os.replace(tmp, creds_path)
        except Exception as exc:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise ProvisionError(
                "env_writing",
                "Could not save Drive credentials file.",
                hint=str(exc),
            ) from exc

    _emit(install, "env_writing", "ok", "Configuration written.")


def _phase_secrets(install: Install, install_dir: Path, form: dict) -> None:
    _emit(install, "secrets", "start", "Generating secrets...")
    proc = _run_cmd(
        ["bash", "scripts/init-secrets.sh"],
        cwd=install_dir,
        timeout=60,
    )
    if proc.returncode != 0:
        raise ProvisionError(
            "secrets",
            "init-secrets.sh failed.",
            hint=_tail_output(proc),
        )
    _emit(install, "secrets", "ok", "Secrets generated.")


def _phase_compose_pull(install: Install, install_dir: Path, form: dict) -> None:
    _emit(install, "compose_pull", "start", "Pulling Docker images (~30s)...")
    proc = _run_cmd(
        ["docker", "compose", "pull"],
        cwd=install_dir,
        timeout=600,
    )
    if proc.returncode != 0:
        raise ProvisionError(
            "compose_pull",
            "docker compose pull failed.",
            hint=_tail_output(proc),
        )
    _emit(install, "compose_pull", "ok", "Images ready.")


def _phase_compose_up(install: Install, install_dir: Path, form: dict) -> None:
    _emit(install, "compose_up", "start", "Booting the stack (~45s)...")
    proc = _run_cmd(
        ["docker", "compose", "up", "-d"],
        cwd=install_dir,
        timeout=300,
    )
    if proc.returncode != 0:
        raise ProvisionError(
            "compose_up",
            "docker compose up failed.",
            hint=_tail_output(proc),
        )
    _emit(install, "compose_up", "ok", "Containers are up.")


def _phase_health(install: Install, install_dir: Path, form: dict) -> None:
    _emit(install, "waiting_health", "start", "Waiting for services to be ready...")

    # Poll `docker compose ps --status running` until every required service
    # is marked running, or we hit the deadline.
    required = ["postgres-obs", "postgres-tasks", "embedder"]
    deadline = time.time() + 180

    while time.time() < deadline:
        proc = _run_cmd(
            ["docker", "compose", "ps", "--status", "running", "--services"],
            cwd=install_dir,
            timeout=30,
        )
        running = set((proc.stdout or "").split())
        missing = [s for s in required if s not in running]
        if not missing:
            _emit(install, "waiting_health", "ok", "All core services healthy.")
            return
        _emit(
            install, "waiting_health", "progress",
            f"Waiting on: {', '.join(missing)}",
        )
        time.sleep(5)

    raise ProvisionError(
        "waiting_health",
        "Services didn't become ready in time.",
        hint="Run 'docker compose logs' to see what's stuck.",
    )


def _phase_bootstrap(install: Install, install_dir: Path, form: dict) -> None:
    _emit(install, "bootstrap", "start", "Bootstrapping brain (3-5 min)...")
    proc = _run_cmd(
        ["bash", "scripts/bootstrap-brain.sh"],
        cwd=install_dir,
        timeout=900,
    )
    if proc.returncode != 0:
        raise ProvisionError(
            "bootstrap",
            "bootstrap-brain.sh failed.",
            hint=_tail_output(proc),
        )
    _emit(install, "bootstrap", "ok", "Brain bootstrapped from your last 90 days of email.")


def _phase_welcome(install: Install, install_dir: Path, form: dict) -> None:
    _emit(install, "welcome", "start", "Sending welcome message...")

    bot_token = form.get("SLACK_BOT_TOKEN", "")
    admin = form.get("SLACK_BOT_ADMIN_USER_ID", "")
    channels = form.get("SLACK_PUBLIC_CHANNELS", "")

    if not bot_token or not admin:
        # Soft-fail: the install is up, we just couldn't DM the user.
        _emit(
            install, "welcome", "warn",
            "Skipped welcome DM — Slack token or admin ID missing.",
        )
        return

    text = _welcome_text(channels)

    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"channel": admin, "text": text},
            timeout=10,
        )
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        _emit(
            install, "welcome", "warn",
            f"Welcome DM failed: {exc}. The stack is still running.",
        )
        return

    if not body.get("ok"):
        err = body.get("error", "unknown")
        _emit(
            install, "welcome", "warn",
            f"Slack rejected welcome DM: {err}. The stack is still running.",
        )
        return

    _emit(install, "welcome", "ok", "Welcome message sent — check your Slack DMs.")


def _welcome_text(channels: str) -> str:
    chan_list = ", ".join(c.strip() for c in (channels or "").split(",") if c.strip())
    chan_line = f"I'm in these channels: {chan_list}\n" if chan_list else ""
    return (
        "Your SafeClaw assistant is now active in this workspace.\n\n"
        f"{chan_line}"
        "What I can do (boss-only):\n"
        "  - Draft email replies in your voice\n"
        "  - Pull observations from your inbox\n"
        "  - Manage your task queue\n\n"
        "What anyone in invited channels can ask:\n"
        '  - "What\'s the status of <project>?"\n'
        '  - "Who emailed me about <topic> this week?"\n'
        '  - "Summarize today\'s important emails"\n\n'
        "Type `@<bot> help` anytime to see the full command list."
    )


# ── Public entry point ────────────────────────────────────────────────────

PHASE_FUNCS = [
    ("validating", _phase_validate),
    ("env_writing", _phase_env),
    ("secrets", _phase_secrets),
    ("compose_pull", _phase_compose_pull),
    ("compose_up", _phase_compose_up),
    ("waiting_health", _phase_health),
    ("bootstrap", _phase_bootstrap),
    ("welcome", _phase_welcome),
]


def run(install: Install, form: dict, install_dir: str | Path) -> None:
    """Execute the full provision pipeline. Always closes the Install
    when done (success or failure) so SSE clients get a clean end."""
    install_dir = Path(install_dir)

    if not install_dir.is_dir():
        _emit(
            install, "validating", "error",
            f"install directory not found: {install_dir}",
        )
        install.close()
        return

    try:
        for phase, func in PHASE_FUNCS:
            try:
                func(install, install_dir, form)
            except ProvisionError as exc:
                log.warning("phase %s failed: %s", exc.phase, exc.message)
                _emit(
                    install, exc.phase, "error", exc.message, hint=exc.hint,
                )
                return
            except subprocess.TimeoutExpired as exc:
                log.exception("phase %s timed out", phase)
                _emit(
                    install, phase, "error",
                    "Operation timed out.",
                    hint=f"Command exceeded {exc.timeout}s.",
                )
                return
            except Exception as exc:  # pragma: no cover — defensive catch-all
                log.exception("phase %s crashed", phase)
                _emit(install, phase, "error", "Unexpected error.", hint=str(exc))
                return

        _emit(install, "done", "ok", "Your assistant is live.")
    finally:
        install.close()
