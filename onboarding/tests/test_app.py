"""Smoke tests for the Flask app — routes return what we expect."""
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


def test_setup_form_renders_with_four_steps():
    c = make_client()
    r = c.get("/setup")
    assert r.status_code == 200
    body = r.data.decode()
    # Exactly 4 steps — Composio is back as Step 2.
    assert 'data-step="1"' in body
    assert 'data-step="2"' in body
    assert 'data-step="3"' in body
    assert 'data-step="4"' in body
    assert 'data-step="5"' not in body
    # All four Composio fields are present, customer-facing.
    assert "COMPOSIO_API_KEY" in body
    assert "COMPOSIO_USER_ID" in body
    assert "COMPOSIO_READER_MCP_URL" in body
    assert "COMPOSIO_ACTOR_MCP_URL" in body
    # Slack fields still present
    assert "SLACK_BOT_TOKEN" in body
    assert "SLACK_APP_TOKEN" in body


def test_help_renders_with_composio_section():
    c = make_client()
    r = c.get("/help")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Slack" in body
    # Composio walkthrough section + anchor must be present.
    assert 'id="composio"' in body
    assert "GMAIL_FETCH_EMAILS" in body
    assert "GMAIL_CREATE_EMAIL_DRAFT" in body


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


def test_provision_rejects_missing_composio_fields():
    """A form submission missing Composio fields must surface per-field
    errors before booting anything."""
    c = make_client()
    payload = {
        "llm_provider": "openai",
        "LLM_API_KEY": "sk-not-real",
        "SLACK_BOT_TOKEN": "wrong",
        "SLACK_APP_TOKEN": "wrong",
        "SLACK_WORKSPACE_ID": "x",
        "SLACK_BOT_ADMIN_USER_ID": "x",
        "SLACK_PUBLIC_CHANNELS": "",
        # No COMPOSIO_* fields at all.
    }
    r = c.post("/api/provision", json=payload)
    assert r.status_code == 400
    body = r.get_json()
    assert body["success"] is False
    errs = body["errors"]
    # All four Composio errors must be reported.
    assert "COMPOSIO_API_KEY" in errs
    assert "COMPOSIO_USER_ID" in errs
    assert "COMPOSIO_READER_MCP_URL" in errs
    assert "COMPOSIO_ACTOR_MCP_URL" in errs
    # Slack errors should also be reported in the same response.
    assert "SLACK_BOT_TOKEN" in errs


def test_provision_returns_validation_errors_for_bad_creds():
    c = make_client()
    payload = {
        "llm_provider": "openai",
        "LLM_API_KEY": "sk-not-real",
        # Composio fields present but bad — we should still see Slack errors.
        "COMPOSIO_API_KEY": "sk-wrong-prefix",
        "COMPOSIO_USER_ID": "",
        "COMPOSIO_READER_MCP_URL": "not-a-url",
        "COMPOSIO_ACTOR_MCP_URL": "not-a-url",
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
    # Distinct field-level errors for bad inputs.
    assert "SLACK_BOT_TOKEN" in errs
    assert "SLACK_APP_TOKEN" in errs
    assert "SLACK_WORKSPACE_ID" in errs
    assert "COMPOSIO_API_KEY" in errs
    assert "COMPOSIO_USER_ID" in errs
    assert "COMPOSIO_READER_MCP_URL" in errs


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
    test_setup_form_renders_with_four_steps()
    test_help_renders_with_composio_section()
    test_healthz()
    test_provision_rejects_non_json()
    test_provision_rejects_empty_object()
    test_provision_rejects_missing_composio_fields()
    test_provision_returns_validation_errors_for_bad_creds()
    test_progress_404_for_unknown_install()
    test_status_404_for_unknown_install()
    test_install_id_pattern_rejects_path_traversal()
    print("app: all tests passed")
