"""Tests for the in-dashboard Composio OAuth onboarding routes.

These lock the security contract that makes it safe to host the "connect your
accounts" flow on-box behind the loopback dashboard:

  * the COMPOSIO_API_KEY is never returned to the client,
  * the scope is still DERIVED from (provider, agent) — an OAuth link can't
    request a boundary a provider may not bind to,
  * only Composio-backed providers expose OAuth links.

fastapi is only present in the dashboard runtime, so the whole module is
skipped where it is unavailable (e.g. a bare dev box).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Load plugin_api.py by path (it lives under dashboard/, not an importable pkg).
_PLUGIN = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"
_spec = importlib.util.spec_from_file_location("safeclaw_connections_api", _PLUGIN)
api = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = api
_spec.loader.exec_module(api)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SAFECLAW_CONNECTIONS_DIR", str(tmp_path))
    monkeypatch.setenv("COMPOSIO_API_KEY", "sk_test_SECRET")
    monkeypatch.setenv("COMPOSIO_USER_ID", "user_abc")
    monkeypatch.setenv("COMPOSIO_AUTHCONFIG_GMAIL", "ac_pinned")
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _stub_composio(monkeypatch, handler):
    """Replace the network call with a deterministic handler(method, path, body)."""
    def fake(method, path, body=None):
        return handler(method, path, body)
    monkeypatch.setattr(api, "_composio_call", fake)


def test_connect_link_returns_redirect_and_never_leaks_key(client, monkeypatch):
    def handler(method, path, body):
        assert path == "/connected_accounts/link"
        assert body["auth_config_id"] == "ac_pinned"   # pinned env used, no create
        assert body["user_id"] == "user_abc"
        assert body["alias"] == "gmail-hyphenlabs"
        return 200, {"id": "ca_new123", "redirect_url": "https://accounts.google/x", "status": "INITIATED"}
    _stub_composio(monkeypatch, handler)

    r = client.post("/connect-link", json={"provider": "gmail", "agent": "actor", "label": "hyphenlabs"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["redirect_url"].startswith("https://accounts.google/")
    assert data["connected_account_id"] == "ca_new123"
    # The api key must never appear anywhere in the response.
    assert "sk_test_SECRET" not in r.text


def test_connect_link_rejects_non_composio_provider(client, monkeypatch):
    _stub_composio(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call composio")))
    r = client.post("/connect-link", json={"provider": "slack", "agent": "reader", "label": "main"})
    assert r.status_code == 422
    assert "not a Composio provider" in r.text


def test_connect_link_rejects_gateway_provider(client, monkeypatch):
    # telegram is a gateway provider (not Composio) → rejected before any
    # network call, never minting an OAuth link.
    _stub_composio(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call composio")))
    r = client.post("/connect-link", json={"provider": "telegram", "agent": "actor", "label": "x"})
    assert r.status_code == 422
    assert "not a Composio provider" in r.text


def test_connect_link_500_without_api_key(client, monkeypatch):
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    # auth config is pinned (no create needed), so the first key use is the link call.
    def handler(method, path, body):
        return 200, {"id": "ca", "redirect_url": "https://x", "status": "INITIATED"}
    _stub_composio(monkeypatch, handler)
    r = client.post("/connect-link", json={"provider": "gmail", "agent": "actor", "label": "x"})
    assert r.status_code == 500
    assert "COMPOSIO_API_KEY" in r.text


def test_connect_status_maps_active(client, monkeypatch):
    def handler(method, path, body):
        assert method == "GET"
        assert path == "/connected_accounts/ca_new123"
        return 200, {"status": "ACTIVE"}
    _stub_composio(monkeypatch, handler)
    r = client.get("/connect-status", params={"connected_account_id": "ca_new123"})
    assert r.status_code == 200
    assert r.json() == {"connected_account_id": "ca_new123", "status": "ACTIVE", "active": True}


def test_providers_flags_oauth_support(client):
    provs = {p["id"]: p for p in client.get("/providers").json()["providers"]}
    assert provs["gmail"]["supports_oauth_link"] is True
    assert provs["slack"]["supports_oauth_link"] is False
