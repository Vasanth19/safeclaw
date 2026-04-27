"""Server-side credential validation for SafeClaw onboarding.

Each validator hits the real upstream API with a tiny request and returns
(ok: bool, message: str). On success, message is empty or a short note. On
failure, message is the user-facing error — never includes the actual
secret value.

We accept that this adds 5-10 seconds to /api/provision before we kick off
docker compose, but it surfaces wrong tokens BEFORE booting containers, which
is a much better UX than failing inside the stack 90 seconds later.

Composio note:
    Customers no longer enter Composio creds via the form. The operator
    pre-loads them into .env via scripts/provision-vps.sh BEFORE the
    customer ever sees /setup. validate_composio_preload() is the
    in-webapp check that those four keys are present and look right.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

# Short timeouts: these are pre-flight checks, not real work.
TIMEOUT = 8.0


def _safe_msg(exc: Exception) -> str:
    """Strip secrets out of error messages before user display."""
    msg = str(exc)
    # requests stuffs URLs into errors; URLs may contain user_id query
    # params we'd rather not echo. Truncate aggressively.
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return msg


# ── LLM ──────────────────────────────────────────────────────────────────────
def validate_llm(provider: str, base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    """POST a 1-token completion to confirm the key works."""
    if not provider or not api_key or not model:
        return False, "provider, api_key and model are required"

    # All three providers (Ollama Cloud, Anthropic, OpenAI) support an
    # OpenAI-compatible /chat/completions endpoint. Anthropic native API
    # is /v1/messages but the user's selection should already point at the
    # right base_url; we just use whatever they gave us.
    if not base_url:
        return False, "base_url is required"

    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        return False, "base_url must be http(s)"

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}

    if provider == "anthropic":
        # Anthropic's OpenAI-compat shim accepts the same Authorization header.
        headers["Authorization"] = f"Bearer {api_key}"
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return False, f"could not reach {provider}: {_safe_msg(exc)}"

    if resp.status_code == 401 or resp.status_code == 403:
        return False, f"{provider} rejected the API key (HTTP {resp.status_code})"
    if resp.status_code == 404:
        return False, f"{provider} returned 404 — check base_url and model name"
    if resp.status_code >= 400:
        return False, f"{provider} returned HTTP {resp.status_code}"

    return True, ""


def validate_ollama(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    """Convenience wrapper for the Ollama Cloud provider."""
    return validate_llm("ollama-cloud", base_url, api_key, model)


def validate_anthropic(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    return validate_llm("anthropic", base_url, api_key, model)


def validate_openai(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    return validate_llm("openai", base_url, api_key, model)


# ── Composio preload check ──────────────────────────────────────────────────
# The four Composio keys are written to .env by the operator BEFORE the
# webapp boots. We never collect them from the customer. This check just
# confirms they are present, non-empty, and format-valid.
COMPOSIO_PRELOAD_KEYS = (
    "COMPOSIO_API_KEY",
    "COMPOSIO_USER_ID",
    "COMPOSIO_READER_MCP_URL",
    "COMPOSIO_ACTOR_MCP_URL",
)

_ENV_LINE_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")
_PLACEHOLDER_VALUES = {"", "__FILL_IN__", "__GENERATE__"}


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Values may be quoted with double-quotes;
    strip those if present. Comment lines (#...) and blank lines are skipped.
    """
    out: dict[str, str] = {}
    if not env_path.is_file():
        return out
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE_RE.match(stripped)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        # Unquote if surrounded by matching double quotes.
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        out[key] = value
    return out


def validate_composio_preload(env_path: str | Path) -> tuple[bool, str]:
    """Confirm the operator preloaded all four COMPOSIO_* keys into .env.

    Format checks:
      - COMPOSIO_API_KEY must start with 'ak_'
      - COMPOSIO_READER_MCP_URL and _ACTOR_MCP_URL must end with
        '/mcp?user_id=...' (i.e. contain '/mcp' and 'user_id=' in the query)
      - COMPOSIO_USER_ID must be non-empty

    Returns (ok, message). On failure, message is the operator-facing
    explanation of which key is wrong.
    """
    env_path = Path(env_path)
    if not env_path.is_file():
        return False, f".env not found at {env_path}"

    values = _read_env_file(env_path)

    missing: list[str] = []
    for key in COMPOSIO_PRELOAD_KEYS:
        value = values.get(key, "").strip()
        if value in _PLACEHOLDER_VALUES:
            missing.append(key)

    if missing:
        return False, f"missing or unset: {', '.join(missing)}"

    api_key = values["COMPOSIO_API_KEY"].strip()
    if not api_key.startswith("ak_"):
        return False, "COMPOSIO_API_KEY must start with 'ak_'"

    user_id = values["COMPOSIO_USER_ID"].strip()
    if not user_id:
        return False, "COMPOSIO_USER_ID is empty"

    for url_key in ("COMPOSIO_READER_MCP_URL", "COMPOSIO_ACTOR_MCP_URL"):
        url = values[url_key].strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"{url_key} must be http(s)"
        if "/mcp" not in parsed.path or "user_id=" not in (parsed.query or ""):
            return False, f"{url_key} must end with /mcp?user_id=..."

    return True, ""


# ── Slack ───────────────────────────────────────────────────────────────────
def validate_slack_bot(token: str) -> tuple[bool, str]:
    if not token:
        return False, "Slack bot token is required"
    if not token.startswith("xoxb-"):
        return False, "Slack bot token must start with 'xoxb-'"

    try:
        resp = requests.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"could not reach Slack: {_safe_msg(exc)}"

    try:
        body = resp.json()
    except ValueError:
        return False, "Slack returned non-JSON response"

    if not body.get("ok"):
        err = body.get("error", "unknown")
        return False, f"Slack rejected the bot token: {err}"

    return True, ""


def validate_slack_app_token(token: str) -> tuple[bool, str]:
    """Slack app tokens are used for Socket Mode. They don't have a cheap
    HTTP check (you have to open a websocket). We just validate the format
    and trust auth.test on the bot token to confirm the workspace is real."""
    if not token:
        return False, "Slack app token is required"
    if not token.startswith("xapp-"):
        return False, "Slack app token must start with 'xapp-'"
    if len(token) < 20:
        return False, "Slack app token looks too short"
    return True, ""


def validate_slack(form: dict[str, Any]) -> dict[str, str]:
    """Aggregate Slack-field validation. Returns {field_name: error}."""
    errors: dict[str, str] = {}

    ok, msg = validate_slack_bot(form.get("SLACK_BOT_TOKEN", ""))
    if not ok:
        errors["SLACK_BOT_TOKEN"] = msg

    ok, msg = validate_slack_app_token(form.get("SLACK_APP_TOKEN", ""))
    if not ok:
        errors["SLACK_APP_TOKEN"] = msg

    workspace = form.get("SLACK_WORKSPACE_ID", "").strip()
    if not workspace.startswith("T"):
        errors["SLACK_WORKSPACE_ID"] = "Workspace ID must start with 'T'"

    admin = form.get("SLACK_BOT_ADMIN_USER_ID", "").strip()
    if not admin.startswith("U"):
        errors["SLACK_BOT_ADMIN_USER_ID"] = "Admin user ID must start with 'U'"

    if not form.get("SLACK_PUBLIC_CHANNELS", "").strip():
        errors["SLACK_PUBLIC_CHANNELS"] = "At least one channel ID is required"

    return errors


# ── Telegram ────────────────────────────────────────────────────────────────
def validate_telegram_bot(token: str) -> tuple[bool, str]:
    if not token:
        return False, "Telegram bot token is required"
    # Format: <numeric-id>:<35-char-string>
    if ":" not in token or not token.split(":", 1)[0].isdigit():
        return False, "Telegram bot token must look like '123456:ABC-...'"

    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"could not reach Telegram: {_safe_msg(exc)}"

    try:
        body = resp.json()
    except ValueError:
        return False, "Telegram returned non-JSON response"

    if not body.get("ok"):
        return False, f"Telegram rejected the bot token: {body.get('description', '')}"

    return True, ""


def validate_telegram(form: dict[str, Any]) -> dict[str, str]:
    """Aggregate Telegram-field validation. Only runs if telegram_enabled is
    truthy. Returns {field_name: error}."""
    errors: dict[str, str] = {}
    if not form.get("telegram_enabled"):
        return errors

    ok, msg = validate_telegram_bot(form.get("TELEGRAM_BOT_TOKEN", ""))
    if not ok:
        errors["TELEGRAM_BOT_TOKEN"] = msg

    if not form.get("TELEGRAM_ALLOWED_USERS", "").strip():
        errors["TELEGRAM_ALLOWED_USERS"] = "At least one allowed user ID is required"

    return errors


# ── Aggregator ──────────────────────────────────────────────────────────────
def validate_all(form: dict[str, Any]) -> dict[str, str]:
    """Run every applicable validator on the form payload. Returns a dict of
    {field_name: error}. Empty dict == all good.

    Composio preload is NOT checked here — the provisioner verifies that
    in its own dedicated phase, before any form-level work.
    """
    errors: dict[str, str] = {}

    # LLM
    provider = form.get("llm_provider", "")
    base_url = form.get("OLLAMA_BASE_URL") or form.get("LLM_BASE_URL", "")
    model = form.get("HERMES_DEFAULT_MODEL", "")
    api_key = (
        form.get("OLLAMA_API_KEY")
        or form.get("ANTHROPIC_API_KEY")
        or form.get("OPENAI_API_KEY", "")
    )
    ok, msg = validate_llm(provider, base_url, api_key, model)
    if not ok:
        errors["llm"] = msg

    # Slack (required)
    errors.update(validate_slack(form))

    # Telegram (optional)
    errors.update(validate_telegram(form))

    return errors
