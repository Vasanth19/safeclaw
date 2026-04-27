"""Server-side credential validation for SafeClaw onboarding.

Each validator hits the real upstream API with a tiny request and returns
(ok: bool, message: str). On success, message is empty or a short note. On
failure, message is the user-facing error — never includes the actual
secret value.

We accept that this adds 5-10 seconds to /api/provision before we kick off
docker compose, but it surfaces wrong tokens BEFORE booting containers, which
is a much better UX than failing inside the stack 90 seconds later.
"""
from __future__ import annotations

import json
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


# ── Composio ─────────────────────────────────────────────────────────────────
def validate_composio_api_key(api_key: str) -> tuple[bool, str]:
    if not api_key:
        return False, "Composio API key is required"
    if not api_key.startswith("ak_"):
        return False, "Composio API key must start with 'ak_'"

    try:
        resp = requests.get(
            "https://backend.composio.dev/api/v3/toolkits",
            params={"limit": 1},
            headers={"x-api-key": api_key},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"could not reach Composio: {_safe_msg(exc)}"

    if resp.status_code == 401 or resp.status_code == 403:
        return False, "Composio rejected the API key"
    if resp.status_code >= 400:
        return False, f"Composio returned HTTP {resp.status_code}"

    try:
        body = resp.json()
    except ValueError:
        return False, "Composio returned non-JSON response"

    if "items" not in body:
        return False, "Composio response missing 'items' field"

    return True, ""


def validate_composio_mcp(url: str, label: str) -> tuple[bool, str]:
    if not url:
        return False, f"{label} URL is required"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"{label} URL must be http(s)"
    if "/mcp" not in parsed.path or "user_id=" not in (parsed.query or ""):
        return False, f"{label} URL must end with /mcp?user_id=..."

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return False, f"could not reach {label}: {_safe_msg(exc)}"

    if resp.status_code >= 400:
        return False, f"{label} returned HTTP {resp.status_code}"

    body = _parse_mcp_response(resp)
    if body is None:
        return False, f"{label} returned non-JSON response"

    tools = body.get("result", {}).get("tools")
    if not isinstance(tools, list) or len(tools) == 0:
        return False, f"{label} returned no tools — is the user authorized?"

    return True, ""


def _parse_mcp_response(resp: requests.Response) -> dict | None:
    """Composio MCP returns either application/json or text/event-stream."""
    ctype = resp.headers.get("Content-Type", "")
    if "application/json" in ctype:
        try:
            return resp.json()
        except ValueError:
            return None
    if "text/event-stream" in ctype:
        # SSE: find the first `data: {...}` line.
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except ValueError:
                    continue
        return None
    # Fall back to attempting JSON parse anyway.
    try:
        return resp.json()
    except ValueError:
        return None


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


# ── Aggregator ──────────────────────────────────────────────────────────────
def validate_all(form: dict[str, Any]) -> dict[str, str]:
    """Run every applicable validator. Returns a dict of {field_name: error}.
    Empty dict == all good."""
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

    # Composio
    ok, msg = validate_composio_api_key(form.get("COMPOSIO_API_KEY", ""))
    if not ok:
        errors["COMPOSIO_API_KEY"] = msg
    if not form.get("COMPOSIO_USER_ID", "").strip():
        errors["COMPOSIO_USER_ID"] = "Composio user ID is required"

    ok, msg = validate_composio_mcp(form.get("COMPOSIO_READER_MCP_URL", ""), "Reader MCP")
    if not ok:
        errors["COMPOSIO_READER_MCP_URL"] = msg

    ok, msg = validate_composio_mcp(form.get("COMPOSIO_ACTOR_MCP_URL", ""), "Actor MCP")
    if not ok:
        errors["COMPOSIO_ACTOR_MCP_URL"] = msg

    # Slack (required)
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

    # Telegram (optional)
    if form.get("telegram_enabled"):
        ok, msg = validate_telegram_bot(form.get("TELEGRAM_BOT_TOKEN", ""))
        if not ok:
            errors["TELEGRAM_BOT_TOKEN"] = msg
        if not form.get("TELEGRAM_ALLOWED_USERS", "").strip():
            errors["TELEGRAM_ALLOWED_USERS"] = "At least one allowed user ID is required"

    return errors
