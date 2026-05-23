"""Server-side credential validation for SafeClaw onboarding.

Each validator hits the real upstream API with a tiny request and returns
(ok: bool, message: str). On success, message is empty or a short note. On
failure, message is the user-facing error — never includes the actual
secret value.

We accept that this adds 5-10 seconds to /api/provision before we kick off
docker compose, but it surfaces wrong tokens BEFORE booting containers, which
is a much better UX than failing inside the stack 90 seconds later.

Composio note:
    Customers provide their own Composio creds in Step 2 of the form —
    Composio is where they did the OAuth dance for Gmail / Drive / Slack,
    so the four COMPOSIO_* values come from them, not from the operator.
    validate_composio_api_key() and validate_composio_mcp_url() hit
    Composio's real endpoints to confirm the key and each MCP URL work.
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


def validate_ollama(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    """Convenience wrapper for the Ollama Cloud provider."""
    return validate_llm("ollama-cloud", base_url, api_key, model)


def validate_anthropic(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    return validate_llm("anthropic", base_url, api_key, model)


def validate_openai(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    return validate_llm("openai", base_url, api_key, model)


# ── Composio ─────────────────────────────────────────────────────────────────
COMPOSIO_API_BASE = "https://backend.composio.dev/api/v3"

# Composio is used ONLY for Gmail. Slack runs through the native bot-token MCP
# (slack-api-mcp), and Drive through the local drive-api MCP (Google service
# account) — neither goes through Composio, so no Slack/Drive auth config or
# toolkit is created here.
COMPOSIO_READER_TOOLS = ["GMAIL_FETCH_EMAILS", "GMAIL_LIST_THREADS", "GMAIL_GET_PROFILE"]
COMPOSIO_ACTOR_TOOLS = ["GMAIL_CREATE_EMAIL_DRAFT", "GMAIL_REPLY_TO_THREAD"]


def _composio_gmail_auth_config_id(headers: dict) -> str:
    """Return the id of a Composio-managed Gmail auth config, creating one if
    none exists.

    In Composio v3 an MCP server must reference an existing auth config
    (``auth_config_ids``) rather than bare ``app_names`` — this is the change
    that broke the old ``/api/v3/mcp/create`` flow.
    """
    # Reuse an existing Composio-managed Gmail auth config if one is present.
    resp = requests.get(
        f"{COMPOSIO_API_BASE}/auth_configs",
        params={"toolkit_slug": "gmail", "is_composio_managed": "true", "limit": 1},
        headers=headers,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if items and items[0].get("id"):
        return items[0]["id"]

    # None yet — create a Composio-managed one. (The customer still has to
    # connect their Gmail account in Composio before tool calls actually
    # succeed; this only wires up the auth config + MCP server.)
    resp = requests.post(
        f"{COMPOSIO_API_BASE}/auth_configs",
        json={
            "toolkit": {"slug": "gmail"},
            "auth_config": {"type": "use_composio_managed_auth"},
        },
        headers=headers,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["auth_config"]["id"]


def _composio_server_mcp_url(headers: dict, name: str, auth_config_ids: list[str],
                             allowed_tools: list[str]) -> str:
    """Create (or find, if it already exists) an MCP server and return its
    ``mcp_url``."""
    resp = requests.post(
        f"{COMPOSIO_API_BASE}/mcp/servers",
        json={
            "name": name,
            "auth_config_ids": auth_config_ids,
            "allowed_tools": allowed_tools,
            "managed_auth_via_composio": True,
        },
        headers=headers,
        timeout=TIMEOUT,
    )

    if resp.status_code in (400, 409):
        # Most likely the named server already exists — look it up.
        listed = requests.get(
            f"{COMPOSIO_API_BASE}/mcp/servers",
            params={"name": name, "limit": 1},
            headers=headers,
            timeout=TIMEOUT,
        )
        listed.raise_for_status()
        items = listed.json().get("items", [])
        server = next((s for s in items if s.get("name") == name),
                      items[0] if items else None)
        if not server:
            raise RuntimeError(
                f"could not create or find MCP server '{name}' "
                f"(HTTP {resp.status_code}: {resp.text[:200]})"
            )
    else:
        resp.raise_for_status()
        server = resp.json()

    mcp_url = server.get("mcp_url")
    if not mcp_url:
        raise RuntimeError(f"Composio returned no mcp_url for '{name}'")
    return mcp_url


def _with_user_id(mcp_url: str, user_id: str) -> str:
    """Scope an MCP server URL to a single end user via the user_id query param."""
    sep = "&" if "?" in mcp_url else "?"
    return f"{mcp_url}{sep}user_id={user_id}"


def provision_composio_mcps(api_key: str, user_id: str) -> dict[str, str]:
    """Programmatically create the Reader and Actor Gmail MCP servers via the
    Composio v3 API. Returns {COMPOSIO_READER_MCP_URL, COMPOSIO_ACTOR_MCP_URL}.
    Raises on error.

    v3 flow (the old ``/api/v3/mcp/create`` endpoint was removed):
      1. ensure a Composio-managed Gmail auth config exists  -> auth_config_id
      2. POST /api/v3/mcp/servers with that auth_config_id + allowed_tools
      3. scope each returned mcp_url to this user via ?user_id=
    """
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    try:
        gmail_ac = _composio_gmail_auth_config_id(headers)
        reader_url = _composio_server_mcp_url(
            headers, "safeclaw-reader", [gmail_ac], COMPOSIO_READER_TOOLS)
        actor_url = _composio_server_mcp_url(
            headers, "safeclaw-actor", [gmail_ac], COMPOSIO_ACTOR_TOOLS)
    except requests.RequestException as exc:
        raise RuntimeError(f"Composio request failed: {_safe_msg(exc)}") from exc

    return {
        "COMPOSIO_READER_MCP_URL": _with_user_id(reader_url, user_id),
        "COMPOSIO_ACTOR_MCP_URL": _with_user_id(actor_url, user_id),
    }


def validate_composio_api_key(api_key: str) -> tuple[bool, str]:
    """Confirm the customer's Composio API key works.

    One cheap call to /api/v3/toolkits?limit=1 — Composio rejects
    bad keys with 401/403 and returns a JSON body with an `items`
    array on success.
    """
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


def validate_composio_mcp_url(url: str, api_key: str = "", *, label: str = "MCP") -> tuple[bool, str]:
    """Confirm a Composio MCP URL responds to a `tools/list` JSON-RPC call
    with a non-empty tools array.

    Format checks first (cheap, no network):
      - http(s) scheme
      - path contains '/mcp'
      - query string contains 'user_id='

    Then we POST tools/list. A non-empty `result.tools` array means the URL
    + user_id are wired to a real MCP server with real authorized tools.

    The api_key arg is optional — Composio MCP URLs already embed
    authentication in the URL itself, but if Composio later requires an
    `x-api-key` header we'll add it here.
    """
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
    if api_key:
        headers["x-api-key"] = api_key

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


def validate_composio(form: dict[str, Any]) -> dict[str, str]:
    """Aggregate Composio-field validation. Returns {field_name: error}."""
    errors: dict[str, str] = {}

    api_key = (form.get("COMPOSIO_API_KEY") or "").strip()
    ok, msg = validate_composio_api_key(api_key)
    if not ok:
        errors["COMPOSIO_API_KEY"] = msg

    user_id = (form.get("COMPOSIO_USER_ID") or "").strip()
    if not user_id:
        errors["COMPOSIO_USER_ID"] = "Composio user ID is required"

    return errors


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

    # Workspace ID / admin user / home channel / ingest channels are all
    # OPTIONAL config (not auth) — only format-check the ones that are supplied.
    # Channels can be set/auto-discovered later; never block provisioning on them.
    workspace = form.get("SLACK_WORKSPACE_ID", "").strip()
    if workspace and not workspace.startswith("T"):
        errors["SLACK_WORKSPACE_ID"] = "Workspace ID must start with 'T'"

    admin = form.get("SLACK_BOT_ADMIN_USER_ID", "").strip()
    if admin and not admin.startswith("U"):
        errors["SLACK_BOT_ADMIN_USER_ID"] = "Admin user ID must start with 'U'"

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


# ── Google Drive (service account) ──────────────────────────────────────────
_GDRIVE_REQUIRED_FIELDS = (
    "type", "project_id", "private_key_id", "private_key",
    "client_email", "auth_uri", "token_uri",
)


def validate_gdrive(form: dict[str, Any]) -> dict[str, str]:
    """Validate the pasted service-account JSON. Returns {field: error}."""
    errors: dict[str, str] = {}
    raw = (form.get("GDRIVE_SERVICE_ACCOUNT_JSON") or "").strip()
    if not raw:
        errors["GDRIVE_SERVICE_ACCOUNT_JSON"] = "Service account JSON is required"
        return errors
    try:
        creds = json.loads(raw)
    except (ValueError, TypeError):
        errors["GDRIVE_SERVICE_ACCOUNT_JSON"] = "Invalid JSON — paste the full contents of the key file"
        return errors
    if creds.get("type") != "service_account":
        errors["GDRIVE_SERVICE_ACCOUNT_JSON"] = (
            f"Expected type 'service_account', got '{creds.get('type', '?')}' — "
            "make sure you downloaded a Service Account key, not an OAuth client"
        )
        return errors
    missing = [f for f in _GDRIVE_REQUIRED_FIELDS if not creds.get(f)]
    if missing:
        errors["GDRIVE_SERVICE_ACCOUNT_JSON"] = (
            f"JSON is missing required fields: {', '.join(missing)}"
        )
    return errors


# ── Aggregator ──────────────────────────────────────────────────────────────
# LLM provider preset — duplicated from provisioner so validate_all() knows
# which base_url + model to test the API key against. Keep these in sync;
# provisioner.LLM_PRESETS is the source of truth at write time.
_LLM_DEFAULTS = {
    "ollama-cloud": (
        # Ollama Cloud DIRECT API (OpenAI-compatible). The local-daemon :cloud
        # routing on :11435 fails headless; this endpoint + API key works and
        # matches the Hermes config (config/*-hermes.yaml).
        "https://ollama.com/v1",
        "glm-5.1:cloud",
    ),
    "anthropic": (
        "https://api.anthropic.com/v1",
        "claude-sonnet-4-6",
    ),
    "openai": (
        "https://api.openai.com/v1",
        "gpt-4o",
    ),
}


def validate_all(form: dict[str, Any]) -> dict[str, str]:
    """Run every applicable validator on the form payload. Returns a dict of
    {field_name: error}. Empty dict == all good.
    """
    errors: dict[str, str] = {}

    # LLM
    provider = (form.get("llm_provider") or "").strip()
    base_url, default_model = _LLM_DEFAULTS.get(
        provider, (form.get("OLLAMA_BASE_URL", ""), "")
    )
    # Form sends a single LLM_API_KEY; legacy paths still allow the
    # provider-specific names for backwards compat with older clients.
    api_key = (
        form.get("LLM_API_KEY")
        or form.get("OLLAMA_API_KEY")
        or form.get("ANTHROPIC_API_KEY")
        or form.get("OPENAI_API_KEY", "")
    ).strip()
    model = (form.get("HERMES_DEFAULT_MODEL") or default_model).strip()
    ok, msg = validate_llm(provider, base_url, api_key, model)
    if not ok:
        errors["llm"] = msg

    # Deployment policy: the LLM is the ONLY hard requirement. Every other
    # integration is OPTIONAL — validate a section only when its primary
    # credential is supplied, so a missing integration never blocks
    # provisioning (that feature simply stays off until configured later).
    if (form.get("COMPOSIO_API_KEY") or "").strip():
        errors.update(validate_composio(form))

    if (form.get("SLACK_BOT_TOKEN") or "").strip():
        errors.update(validate_slack(form))

    # Telegram already self-gates on `telegram_enabled`.
    errors.update(validate_telegram(form))

    if (form.get("GDRIVE_SERVICE_ACCOUNT_JSON") or "").strip():
        errors.update(validate_gdrive(form))

    return errors
