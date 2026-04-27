"""Unit tests for validator format checks (offline only — we never hit
real upstreams in unit tests; live calls are exercised via the /api/provision
HTTP path with mocked transports if needed)."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import validator  # noqa: E402


# ── Composio API key (format checks only; live HTTP mocked) ─────────────────
def test_composio_api_key_empty():
    ok, msg = validator.validate_composio_api_key("")
    assert not ok
    assert "required" in msg.lower()


def test_composio_api_key_wrong_prefix():
    ok, msg = validator.validate_composio_api_key("sk-not-composio")
    assert not ok
    assert "ak_" in msg


def test_composio_api_key_live_rejects_401():
    fake_resp = MagicMock(status_code=401)
    with patch("lib.validator.requests.get", return_value=fake_resp):
        ok, msg = validator.validate_composio_api_key("ak_test123")
    assert not ok
    assert "rejected" in msg.lower()


def test_composio_api_key_live_happy_path():
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = {"items": []}
    with patch("lib.validator.requests.get", return_value=fake_resp):
        ok, msg = validator.validate_composio_api_key("ak_test123")
    assert ok, msg


def test_composio_api_key_live_missing_items_field():
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = {"data": []}
    with patch("lib.validator.requests.get", return_value=fake_resp):
        ok, msg = validator.validate_composio_api_key("ak_test123")
    assert not ok
    assert "items" in msg


# ── Composio MCP URL ────────────────────────────────────────────────────────
def test_composio_mcp_url_empty():
    ok, msg = validator.validate_composio_mcp_url("", api_key="ak_x", label="Reader MCP")
    assert not ok
    assert "required" in msg.lower()


def test_composio_mcp_url_wrong_scheme():
    ok, msg = validator.validate_composio_mcp_url(
        "ftp://example.com/mcp?user_id=u1", api_key="ak_x"
    )
    assert not ok
    assert "http" in msg.lower()


def test_composio_mcp_url_missing_mcp_path():
    ok, msg = validator.validate_composio_mcp_url(
        "https://example.com/no-mcp-here?user_id=u1", api_key="ak_x"
    )
    assert not ok
    assert "/mcp" in msg or "user_id" in msg


def test_composio_mcp_url_missing_user_id():
    ok, msg = validator.validate_composio_mcp_url(
        "https://example.com/mcp", api_key="ak_x"
    )
    assert not ok
    assert "user_id" in msg


def test_composio_mcp_url_live_returns_tools():
    fake_resp = MagicMock(status_code=200)
    fake_resp.headers = {"Content-Type": "application/json"}
    fake_resp.json.return_value = {
        "result": {"tools": [{"name": "GMAIL_FETCH_EMAILS"}, {"name": "GMAIL_LIST_THREADS"}]}
    }
    with patch("lib.validator.requests.post", return_value=fake_resp):
        ok, msg = validator.validate_composio_mcp_url(
            "https://x.composio.dev/v3/mcp/abc/mcp?user_id=u1", api_key="ak_x"
        )
    assert ok, msg


def test_composio_mcp_url_live_empty_tools():
    fake_resp = MagicMock(status_code=200)
    fake_resp.headers = {"Content-Type": "application/json"}
    fake_resp.json.return_value = {"result": {"tools": []}}
    with patch("lib.validator.requests.post", return_value=fake_resp):
        ok, msg = validator.validate_composio_mcp_url(
            "https://x.composio.dev/v3/mcp/abc/mcp?user_id=u1", api_key="ak_x"
        )
    assert not ok
    assert "no tools" in msg.lower() or "authorized" in msg.lower()


# ── Composio aggregator ─────────────────────────────────────────────────────
def test_validate_composio_missing_all_fields():
    """Empty form must surface errors for all four Composio fields."""
    # API key validator hits the network — short-circuit format check first.
    errors = validator.validate_composio({})
    assert "COMPOSIO_API_KEY" in errors
    assert "COMPOSIO_USER_ID" in errors
    assert "COMPOSIO_READER_MCP_URL" in errors
    assert "COMPOSIO_ACTOR_MCP_URL" in errors


# ── Slack ───────────────────────────────────────────────────────────────────
def test_slack_bot_token_format():
    ok, msg = validator.validate_slack_bot("")
    assert not ok
    ok, msg = validator.validate_slack_bot("nope")
    assert not ok and "xoxb-" in msg


def test_slack_app_token_format():
    ok, msg = validator.validate_slack_app_token("")
    assert not ok
    ok, msg = validator.validate_slack_app_token("xapp-too-short")
    assert not ok
    ok, msg = validator.validate_slack_app_token("xapp-1-A0123456789-9999999999999-abcdef0123456789")
    assert ok


def test_validate_slack_aggregates():
    errs = validator.validate_slack({})
    assert "SLACK_BOT_TOKEN" in errs
    assert "SLACK_WORKSPACE_ID" in errs
    assert "SLACK_BOT_ADMIN_USER_ID" in errs
    assert "SLACK_PUBLIC_CHANNELS" in errs


# ── Telegram ────────────────────────────────────────────────────────────────
def test_telegram_bot_token_format():
    ok, _ = validator.validate_telegram_bot("not-numeric:abcdef")
    assert not ok
    ok, _ = validator.validate_telegram_bot("missing-colon")
    assert not ok


def test_validate_telegram_skipped_when_disabled():
    errs = validator.validate_telegram({})  # telegram_enabled falsy
    assert errs == {}


def test_validate_telegram_required_when_enabled():
    errs = validator.validate_telegram({"telegram_enabled": True})
    assert "TELEGRAM_BOT_TOKEN" in errs
    assert "TELEGRAM_ALLOWED_USERS" in errs


# ── Aggregator ──────────────────────────────────────────────────────────────
def test_validate_all_includes_composio():
    """validate_all should report missing Composio fields alongside Slack."""
    errors = validator.validate_all({})
    assert "COMPOSIO_API_KEY" in errors
    assert "COMPOSIO_USER_ID" in errors
    assert "COMPOSIO_READER_MCP_URL" in errors
    assert "COMPOSIO_ACTOR_MCP_URL" in errors
    assert "SLACK_BOT_TOKEN" in errors


if __name__ == "__main__":
    test_composio_api_key_empty()
    test_composio_api_key_wrong_prefix()
    test_composio_api_key_live_rejects_401()
    test_composio_api_key_live_happy_path()
    test_composio_api_key_live_missing_items_field()
    test_composio_mcp_url_empty()
    test_composio_mcp_url_wrong_scheme()
    test_composio_mcp_url_missing_mcp_path()
    test_composio_mcp_url_missing_user_id()
    test_composio_mcp_url_live_returns_tools()
    test_composio_mcp_url_live_empty_tools()
    test_validate_composio_missing_all_fields()
    test_slack_bot_token_format()
    test_slack_app_token_format()
    test_validate_slack_aggregates()
    test_telegram_bot_token_format()
    test_validate_telegram_skipped_when_disabled()
    test_validate_telegram_required_when_enabled()
    test_validate_all_includes_composio()
    print("validator: all tests passed")
