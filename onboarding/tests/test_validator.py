"""Unit tests for validator format checks (offline only — we never hit
real upstreams in unit tests)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import validator  # noqa: E402


# ── Composio preload (file-based check) ─────────────────────────────────────
GOOD_ENV = """\
COMPOSIO_API_KEY=ak_test123
COMPOSIO_USER_ID=user-uuid-123
COMPOSIO_READER_MCP_URL=https://backend.composio.dev/v3/mcp/abc/mcp?user_id=u1
COMPOSIO_ACTOR_MCP_URL=https://backend.composio.dev/v3/mcp/def/mcp?user_id=u1
SLACK_BOT_TOKEN=__FILL_IN__
"""


def _write_env(text: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix="safeclaw_validator_"))
    p = d / ".env"
    p.write_text(text, encoding="utf-8")
    return p


def test_composio_preload_happy_path():
    env = _write_env(GOOD_ENV)
    ok, msg = validator.validate_composio_preload(env)
    assert ok, msg


def test_composio_preload_missing_file():
    ok, msg = validator.validate_composio_preload("/nonexistent/path/.env")
    assert not ok
    assert ".env not found" in msg


def test_composio_preload_missing_key():
    bad = GOOD_ENV.replace("COMPOSIO_USER_ID=user-uuid-123", "COMPOSIO_USER_ID=__FILL_IN__")
    env = _write_env(bad)
    ok, msg = validator.validate_composio_preload(env)
    assert not ok
    assert "COMPOSIO_USER_ID" in msg


def test_composio_preload_bad_api_key_format():
    bad = GOOD_ENV.replace("ak_test123", "wrong_prefix")
    env = _write_env(bad)
    ok, msg = validator.validate_composio_preload(env)
    assert not ok
    assert "ak_" in msg


def test_composio_preload_bad_url_format():
    bad = GOOD_ENV.replace(
        "https://backend.composio.dev/v3/mcp/abc/mcp?user_id=u1",
        "https://example.com/no-mcp-here",
    )
    env = _write_env(bad)
    ok, msg = validator.validate_composio_preload(env)
    assert not ok
    assert "user_id" in msg or "/mcp" in msg


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


# ── Aggregator (form-only — no Composio fields) ─────────────────────────────
def test_validate_all_no_composio_fields():
    """validate_all should NOT report Composio errors anymore — those keys
    are operator-preloaded and live in .env, not on the form."""
    errors = validator.validate_all({})
    assert "COMPOSIO_API_KEY" not in errors
    assert "COMPOSIO_USER_ID" not in errors
    assert "COMPOSIO_READER_MCP_URL" not in errors
    assert "COMPOSIO_ACTOR_MCP_URL" not in errors
    # But Slack should still be flagged.
    assert "SLACK_BOT_TOKEN" in errors


if __name__ == "__main__":
    test_composio_preload_happy_path()
    test_composio_preload_missing_file()
    test_composio_preload_missing_key()
    test_composio_preload_bad_api_key_format()
    test_composio_preload_bad_url_format()
    test_slack_bot_token_format()
    test_slack_app_token_format()
    test_validate_slack_aggregates()
    test_telegram_bot_token_format()
    test_validate_telegram_skipped_when_disabled()
    test_validate_telegram_required_when_enabled()
    test_validate_all_no_composio_fields()
    print("validator: all tests passed")
