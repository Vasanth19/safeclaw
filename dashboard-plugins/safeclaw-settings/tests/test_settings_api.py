"""Tests for the SafeClaw Settings dashboard plugin.

Lock the two things that matter: (1) it is status-only — no secret value ever
appears in a response; (2) the handoff URL is built ONLY when a real plaintext
access password is present, and embeds the access credential when it is.

fastapi is only present in the dashboard runtime, so the module is skipped where
it is unavailable.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_PLUGIN = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"
_spec = importlib.util.spec_from_file_location("safeclaw_settings_api", _PLUGIN)
api = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = api
_spec.loader.exec_module(api)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolate from the operator's ambient shell, which may export COMPOSIO_*/
    # DASHBOARD_*/PUBLIC_HOSTNAME — tests must control every input.
    for var in ("COMPOSIO_API_KEY", "COMPOSIO_USER_ID", "COMPOSIO_READER_MCP_URL",
                "COMPOSIO_ACTOR_MCP_URL", "PUBLIC_HOSTNAME", "HERMES_PUBLIC_HOSTNAME",
                "DASHBOARD_AUTH_USER", "SAFECLAW_UI_USER", "DASHBOARD_AUTH_PASSWORD",
                "UI_PASSWORD", "CLIENT_NAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SAFECLAW_CONNECTIONS_DIR", str(tmp_path))
    # Brain probe is network — force it deterministic.
    monkeypatch.setattr(api, "_probe_brain", lambda: True)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_status_is_booleans_not_values(client, monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "ak_SECRET_PROJECT_KEY")
    monkeypatch.setenv("COMPOSIO_USER_ID", "client:acme")
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert body["composio"]["project_key_set"] is True
    assert body["composio"]["ready"] is False  # MCP urls still unset
    # The secret value must never leak into the response.
    assert "ak_SECRET_PROJECT_KEY" not in r.text


def test_status_placeholder_counts_as_unset(client, monkeypatch):
    monkeypatch.setenv("COMPOSIO_USER_ID", "__FILL_IN__")
    body = client.get("/status").json()
    assert body["composio"]["user_id_set"] is False


def test_access_no_password_returns_reason_not_url(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_HOSTNAME", "safeclaw-acme.example.com")
    monkeypatch.setenv("DASHBOARD_AUTH_USER", "acme")
    monkeypatch.delenv("DASHBOARD_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("UI_PASSWORD", raising=False)
    body = client.get("/access").json()
    assert body["handoff_url"] is None
    assert body["host_url"] == "https://safeclaw-acme.example.com/connections"
    assert "bcrypt" in body["reason"]


def test_access_builds_one_click_url_when_password_present(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_HOSTNAME", "safeclaw-acme.example.com")
    monkeypatch.setenv("DASHBOARD_AUTH_USER", "acme")
    monkeypatch.setenv("DASHBOARD_AUTH_PASSWORD", "p@ss/word")
    body = client.get("/access").json()
    # credential embedded + special chars percent-encoded + deep-linked to /connections
    assert body["handoff_url"] == "https://acme:p%40ss%2Fword@safeclaw-acme.example.com/connections"


def test_checklist_reflects_connections(client, monkeypatch, tmp_path):
    (tmp_path / "gmail-acme.yaml").write_text("provider: gmail\n")
    monkeypatch.setenv("SAFECLAW_CONNECTIONS_DIR", str(tmp_path))
    body = client.get("/checklist").json()
    conn_item = next(i for i in body["items"] if i["key"] == "connections")
    assert conn_item["done"] is True
    assert body["total"] == 7
