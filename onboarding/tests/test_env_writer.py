"""Tests for env_writer — atomic .env writer with whitelist enforcement."""
import os
import sys
import tempfile
from pathlib import Path

# Allow tests to import from sibling lib/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import env_writer  # noqa: E402


SAMPLE_TEMPLATE = """\
# Header comment
POSTGRES_OBS_USER=obs_user
POSTGRES_OBS_PASSWORD=__GENERATE__
COMPOSIO_API_KEY=__FILL_IN__
COMPOSIO_USER_ID=__FILL_IN__
COMPOSIO_READER_MCP_URL=__FILL_IN__
COMPOSIO_ACTOR_MCP_URL=__FILL_IN__
SLACK_BOT_TOKEN=__FILL_IN__
TELEGRAM_BOT_TOKEN=__FILL_IN__
ACTOR_ENABLED=true
"""


def make_tempdir() -> Path:
    d = Path(tempfile.mkdtemp(prefix="safeclaw_test_"))
    (d / ".env.example").write_text(SAMPLE_TEMPLATE, encoding="utf-8")
    return d


# ── ALLOWED_KEYS expectations ───────────────────────────────────────────────
def test_composio_keys_in_allowed_keys():
    """Customer enters Composio creds via the form, so these MUST be in
    ALLOWED_KEYS."""
    assert "COMPOSIO_API_KEY" in env_writer.ALLOWED_KEYS
    assert "COMPOSIO_USER_ID" in env_writer.ALLOWED_KEYS
    assert "COMPOSIO_READER_MCP_URL" in env_writer.ALLOWED_KEYS
    assert "COMPOSIO_ACTOR_MCP_URL" in env_writer.ALLOWED_KEYS


# ── write_env (form-driven) ─────────────────────────────────────────────────
def test_writes_atomic_file_with_mode_600():
    d = make_tempdir()
    env_writer.write_env(d, {
        "SLACK_BOT_TOKEN": "xoxb-test",
    })
    target = d / ".env"
    assert target.exists()
    assert oct(target.stat().st_mode)[-3:] == "600"


def test_substitutes_only_provided_keys():
    d = make_tempdir()
    env_writer.write_env(d, {
        "SLACK_BOT_TOKEN": "xoxb-test",
    })
    text = (d / ".env").read_text()
    assert "SLACK_BOT_TOKEN=xoxb-test" in text
    # Untouched keys remain placeholders
    assert "POSTGRES_OBS_PASSWORD=__GENERATE__" in text
    # Comments preserved
    assert "# Header comment" in text


def test_writes_composio_values_through_form():
    """Composio is now form-driven — write_env should substitute the four
    values when the form provides them."""
    d = make_tempdir()
    env_writer.write_env(d, {
        "COMPOSIO_API_KEY": "ak_real",
        "COMPOSIO_USER_ID": "user_real",
        "COMPOSIO_READER_MCP_URL": "https://x.dev/r/mcp?user_id=u",
        "COMPOSIO_ACTOR_MCP_URL": "https://x.dev/a/mcp?user_id=u",
    })
    text = (d / ".env").read_text()
    assert "COMPOSIO_API_KEY=ak_real" in text
    assert "COMPOSIO_USER_ID=user_real" in text
    assert 'COMPOSIO_READER_MCP_URL="https://x.dev/r/mcp?user_id=u"' in text
    assert 'COMPOSIO_ACTOR_MCP_URL="https://x.dev/a/mcp?user_id=u"' in text


def test_rejects_placeholder_input():
    d = make_tempdir()
    try:
        env_writer.write_env(d, {"SLACK_BOT_TOKEN": "__FILL_IN__"})
    except env_writer.EnvWriteError as exc:
        assert "placeholder" in str(exc)
    else:
        raise AssertionError("expected EnvWriteError")


def test_quotes_values_with_special_chars():
    d = make_tempdir()
    env_writer.write_env(d, {
        "SLACK_INGEST_CHANNELS": "C123,C456 and a space",
    })
    text = (d / ".env").read_text()
    assert 'SLACK_INGEST_CHANNELS="C123,C456 and a space"' in text


def test_appends_keys_not_in_template():
    d = make_tempdir()
    env_writer.write_env(d, {
        "SLACK_WORKSPACE_ID": "T12345",
        "SLACK_INGEST_CHANNELS": "C111,C222",
    })
    text = (d / ".env").read_text()
    assert "SLACK_WORKSPACE_ID=T12345" in text
    assert "SLACK_INGEST_CHANNELS=" in text


def test_unknown_keys_are_dropped():
    d = make_tempdir()
    env_writer.write_env(d, {
        "SLACK_BOT_TOKEN": "xoxb-test",
        "SOMETHING_EVIL": "rm -rf /",  # not in ALLOWED_KEYS
    })
    text = (d / ".env").read_text()
    assert "SOMETHING_EVIL" not in text


def test_atomic_no_partial_write_on_missing_template():
    d = Path(tempfile.mkdtemp(prefix="safeclaw_test_"))
    # No .env.example present
    try:
        env_writer.write_env(d, {"SLACK_BOT_TOKEN": "xoxb-test"})
    except env_writer.EnvWriteError:
        pass
    else:
        raise AssertionError("expected EnvWriteError")
    assert not (d / ".env").exists()


def test_existing_env_preserves_non_form_keys():
    """If .env already exists with extra keys (e.g. JWT_SECRET written by
    init-secrets), write_env should preserve them."""
    d = make_tempdir()
    # Pretend init-secrets ran first.
    (d / ".env").write_text(
        SAMPLE_TEMPLATE.replace("POSTGRES_OBS_PASSWORD=__GENERATE__",
                                "POSTGRES_OBS_PASSWORD=secret123"),
        encoding="utf-8",
    )
    env_writer.write_env(d, {"SLACK_BOT_TOKEN": "xoxb-test"})
    text = (d / ".env").read_text()
    assert "POSTGRES_OBS_PASSWORD=secret123" in text
    assert "SLACK_BOT_TOKEN=xoxb-test" in text


if __name__ == "__main__":
    test_composio_keys_in_allowed_keys()
    test_writes_atomic_file_with_mode_600()
    test_substitutes_only_provided_keys()
    test_writes_composio_values_through_form()
    test_rejects_placeholder_input()
    test_quotes_values_with_special_chars()
    test_appends_keys_not_in_template()
    test_unknown_keys_are_dropped()
    test_atomic_no_partial_write_on_missing_template()
    test_existing_env_preserves_non_form_keys()
    print("env_writer: all tests passed")
