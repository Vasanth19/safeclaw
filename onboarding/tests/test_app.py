"""Smoke tests for the Flask app — routes return what we expect."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module  # noqa: E402


def make_client():
    return app_module.app.test_client()


def test_landing_renders():
    c = make_client()
    r = c.get("/")
    assert r.status_code == 200
    assert b"SafeClaw" in r.data or b"SAFE" in r.data


def test_setup_form_renders_with_all_steps():
    c = make_client()
    r = c.get("/setup")
    assert r.status_code == 200
    body = r.data.decode()
    # Each of the 4 steps should be present
    assert 'data-step="1"' in body
    assert 'data-step="2"' in body
    assert 'data-step="3"' in body
    assert 'data-step="4"' in body
    # Slack fields present
    assert "SLACK_BOT_TOKEN" in body
    assert "SLACK_APP_TOKEN" in body
    # Composio fields present
    assert "COMPOSIO_API_KEY" in body


def test_help_renders():
    c = make_client()
    r = c.get("/help")
    assert r.status_code == 200
    assert b"Slack" in r.data


def test_healthz():
    c = make_client()
    r = c.get("/api/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}


def test_provision_rejects_non_json():
    c = make_client()
    r = c.post("/api/provision", data="hello")
    assert r.status_code == 400


def test_provision_rejects_empty_object():
    c = make_client()
    r = c.post("/api/provision", json={})
    assert r.status_code == 400
    body = r.get_json()
    assert body["success"] is False
    assert "errors" in body


def test_provision_returns_validation_errors_for_bad_creds():
    c = make_client()
    payload = {
        "llm_provider": "openai",
        "OLLAMA_BASE_URL": "https://api.openai.com/v1",
        "OPENAI_API_KEY": "sk-not-real",
        "HERMES_DEFAULT_MODEL": "gpt-4o",
        "COMPOSIO_API_KEY": "wrong_format",
        "COMPOSIO_USER_ID": "user@example.com",
        "COMPOSIO_READER_MCP_URL": "not a url",
        "COMPOSIO_ACTOR_MCP_URL": "still not a url",
        "SLACK_BOT_TOKEN": "wrong",
        "SLACK_APP_TOKEN": "wrong",
        "SLACK_WORKSPACE_ID": "x",
        "SLACK_BOT_ADMIN_USER_ID": "x",
        "SLACK_PUBLIC_CHANNELS": "",
    }
    r = c.post("/api/provision", json=payload)
    assert r.status_code == 400
    body = r.get_json()
    assert body["success"] is False
    errs = body["errors"]
    # We should see distinct field-level errors for the bad inputs.
    assert "COMPOSIO_API_KEY" in errs
    assert "SLACK_BOT_TOKEN" in errs
    assert "SLACK_APP_TOKEN" in errs
    assert "SLACK_WORKSPACE_ID" in errs


def test_progress_404_for_unknown_install():
    c = make_client()
    r = c.get("/progress/aaaaaaaaaaaaaaaa")
    assert r.status_code == 404


def test_status_404_for_unknown_install():
    c = make_client()
    r = c.get("/api/status/aaaaaaaaaaaaaaaa")
    assert r.status_code == 404


def test_install_id_pattern_rejects_path_traversal():
    c = make_client()
    r = c.get("/progress/..%2Fetc")
    assert r.status_code in (404, 400)


if __name__ == "__main__":
    test_landing_renders()
    test_setup_form_renders_with_all_steps()
    test_help_renders()
    test_healthz()
    test_provision_rejects_non_json()
    test_provision_rejects_empty_object()
    test_provision_returns_validation_errors_for_bad_creds()
    test_progress_404_for_unknown_install()
    test_status_404_for_unknown_install()
    test_install_id_pattern_rejects_path_traversal()
    print("app: all tests passed")
