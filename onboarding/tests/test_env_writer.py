"""Tests for env_writer — atomic .env writer + Composio preload helper."""
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
        "SLACK_PUBLIC_CHANNELS": "C123,C456 and a space",
    })
    text = (d / ".env").read_text()
    assert 'SLACK_PUBLIC_CHANNELS="C123,C456 and a space"' in text


def test_appends_keys_not_in_template():
    d = make_tempdir()
    env_writer.write_env(d, {
        "SLACK_WORKSPACE_ID": "T12345",
        "SLACK_PUBLIC_CHANNELS": "C111,C222",
    })
    text = (d / ".env").read_text()
    assert "SLACK_WORKSPACE_ID=T12345" in text
    assert "SLACK_PUBLIC_CHANNELS=" in text


def test_unknown_keys_are_dropped():
    d = make_tempdir()
    env_writer.write_env(d, {
        "SLACK_BOT_TOKEN": "xoxb-test",
        "SOMETHING_EVIL": "rm -rf /",  # not in ALLOWED_KEYS
    })
    text = (d / ".env").read_text()
    assert "SOMETHING_EVIL" not in text


def test_composio_keys_not_in_allowed_keys():
    """Form must NOT be able to overwrite preloaded COMPOSIO_* values."""
    assert "COMPOSIO_API_KEY" not in env_writer.ALLOWED_KEYS
    assert "COMPOSIO_USER_ID" not in env_writer.ALLOWED_KEYS
    assert "COMPOSIO_READER_MCP_URL" not in env_writer.ALLOWED_KEYS
    assert "COMPOSIO_ACTOR_MCP_URL" not in env_writer.ALLOWED_KEYS


def test_form_cannot_overwrite_composio_preload():
    """A form payload that maliciously includes COMPOSIO_* must be ignored,
    and the preloaded values in .env must be preserved."""
    d = make_tempdir()
    # Operator preloaded these into .env.
    env_writer.preload_composio(d / ".env", {
        "COMPOSIO_API_KEY": "ak_real",
        "COMPOSIO_USER_ID": "user_real",
        "COMPOSIO_READER_MCP_URL": "https://x.dev/r/mcp?user_id=u",
        "COMPOSIO_ACTOR_MCP_URL": "https://x.dev/a/mcp?user_id=u",
    })
    # Now a form-driven write tries to overwrite them.
    env_writer.write_env(d, {
        "SLACK_BOT_TOKEN": "xoxb-test",
        "COMPOSIO_API_KEY": "ak_evil",          # ignored — not in ALLOWED_KEYS
        "COMPOSIO_USER_ID": "user_evil",        # ignored
        "COMPOSIO_READER_MCP_URL": "https://evil/mcp?user_id=evil",
        "COMPOSIO_ACTOR_MCP_URL": "https://evil/mcp?user_id=evil",
    })
    text = (d / ".env").read_text()
    assert "COMPOSIO_API_KEY=ak_real" in text
    assert "COMPOSIO_USER_ID=user_real" in text
    assert "ak_evil" not in text
    assert "user_evil" not in text


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


# ── preload_composio (operator-driven) ──────────────────────────────────────
def test_preload_composio_writes_all_four_keys():
    d = make_tempdir()
    env_writer.preload_composio(d / ".env", {
        "COMPOSIO_API_KEY": "ak_op",
        "COMPOSIO_USER_ID": "user_op",
        "COMPOSIO_READER_MCP_URL": "https://x.dev/r/mcp?user_id=u",
        "COMPOSIO_ACTOR_MCP_URL": "https://x.dev/a/mcp?user_id=u",
    })
    text = (d / ".env").read_text()
    assert "COMPOSIO_API_KEY=ak_op" in text
    assert "COMPOSIO_USER_ID=user_op" in text
    # URLs containing '?' get shell-quoted to keep them safe in .env.
    assert 'COMPOSIO_READER_MCP_URL="https://x.dev/r/mcp?user_id=u"' in text
    assert 'COMPOSIO_ACTOR_MCP_URL="https://x.dev/a/mcp?user_id=u"' in text
    assert oct((d / ".env").stat().st_mode)[-3:] == "600"


def test_preload_composio_rejects_missing_key():
    d = make_tempdir()
    try:
        env_writer.preload_composio(d / ".env", {
            "COMPOSIO_API_KEY": "ak_op",
            # missing the other three
        })
    except env_writer.EnvWriteError as exc:
        assert "missing" in str(exc).lower()
    else:
        raise AssertionError("expected EnvWriteError")


def test_preload_composio_rejects_placeholders():
    d = make_tempdir()
    try:
        env_writer.preload_composio(d / ".env", {
            "COMPOSIO_API_KEY": "__FILL_IN__",
            "COMPOSIO_USER_ID": "user_op",
            "COMPOSIO_READER_MCP_URL": "https://x/mcp?user_id=u",
            "COMPOSIO_ACTOR_MCP_URL": "https://x/mcp?user_id=u",
        })
    except env_writer.EnvWriteError as exc:
        assert "placeholder" in str(exc).lower()
    else:
        raise AssertionError("expected EnvWriteError")


if __name__ == "__main__":
    test_writes_atomic_file_with_mode_600()
    test_substitutes_only_provided_keys()
    test_rejects_placeholder_input()
    test_quotes_values_with_special_chars()
    test_appends_keys_not_in_template()
    test_unknown_keys_are_dropped()
    test_composio_keys_not_in_allowed_keys()
    test_form_cannot_overwrite_composio_preload()
    test_atomic_no_partial_write_on_missing_template()
    test_preload_composio_writes_all_four_keys()
    test_preload_composio_rejects_missing_key()
    test_preload_composio_rejects_placeholders()
    print("env_writer: all tests passed")
