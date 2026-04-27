"""Unit tests for validator format checks (offline only — we never hit
real upstreams in unit tests)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import validator  # noqa: E402


def test_composio_api_key_format():
    ok, msg = validator.validate_composio_api_key("")
    assert not ok
    ok, msg = validator.validate_composio_api_key("not_prefixed")
    assert not ok and "ak_" in msg


def test_composio_mcp_url_format():
    ok, msg = validator.validate_composio_mcp("", "Reader MCP")
    assert not ok
    ok, msg = validator.validate_composio_mcp("ftp://nope", "Reader MCP")
    assert not ok
    ok, msg = validator.validate_composio_mcp(
        "https://example.com/no-mcp-here", "Reader MCP"
    )
    assert not ok


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


def test_telegram_bot_token_format():
    ok, _ = validator.validate_telegram_bot("not-numeric:abcdef")
    assert not ok
    ok, _ = validator.validate_telegram_bot("missing-colon")
    assert not ok


def test_validate_all_aggregates_errors():
    errors = validator.validate_all({})  # empty form
    # Should not raise. Should report multiple field errors.
    assert "COMPOSIO_API_KEY" in errors
    assert "SLACK_BOT_TOKEN" in errors
    assert "SLACK_WORKSPACE_ID" in errors


if __name__ == "__main__":
    test_composio_api_key_format()
    test_composio_mcp_url_format()
    test_slack_bot_token_format()
    test_slack_app_token_format()
    test_telegram_bot_token_format()
    test_validate_all_aggregates_errors()
    print("validator: all tests passed")
