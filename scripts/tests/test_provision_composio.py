"""Tests for the operator-side Composio provisioning script.

Pure stdlib — no Composio network. We inject a fake ComposioClient whose
`_request` records calls and returns canned responses, then assert:

  * the ORG key is used ONLY for project creation and never appears in the
    env fragment that goes to the box,
  * the project-scoped key is what lands in client.env,
  * reader/actor MCP servers carry the trust-split allowlists with NO send tool.
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "provision-composio.py"
_spec = importlib.util.spec_from_file_location("provision_composio", _SCRIPT)
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


class FakeClient(pc.ComposioClient):
    def __init__(self, org_key):
        super().__init__(org_key=org_key)
        self.calls = []

    def _request(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if url.endswith("/org/owner/project/new"):
            return 200, {"id": "proj_123", "name": body["name"], "api_key": "ak_project_SCOPED"}
        if url.endswith("/auth_configs"):
            return 200, {"auth_config": {"id": "ac_gmail_1"}}
        if url.endswith("/mcp/servers"):
            role = "reader" if "reader" in body["name"] else "actor"
            return 200, {"id": f"mcp_{role}", "mcp_url": f"https://mcp.composio/{role}"}
        raise AssertionError(f"unexpected url {url}")


def test_provision_happy_path_keeps_org_key_off_the_box():
    cc = FakeClient(org_key="ak_ORG_SUPER_SECRET")
    result = pc.provision("suffolk", ["gmail"], "client:suffolk",
                          org_key="ak_ORG_SUPER_SECRET", composio=cc)

    assert result["project_id"] == "proj_123"
    assert result["project_key"] == "ak_project_SCOPED"
    assert result["reader_mcp_url"] == "https://mcp.composio/reader"
    assert result["actor_mcp_url"] == "https://mcp.composio/actor"

    frag = pc.env_fragment(result)
    # The project-scoped key reaches the box…
    assert "COMPOSIO_API_KEY=ak_project_SCOPED" in frag
    # …and the org key NEVER does.
    assert "ak_ORG_SUPER_SECRET" not in frag
    assert "ak_ORG_SUPER_SECRET" not in pc.json.dumps(result)


def test_org_key_used_only_for_project_creation():
    cc = FakeClient(org_key="ak_ORG_SUPER_SECRET")
    pc.provision("suffolk", ["gmail"], "client:suffolk",
                 org_key="ak_ORG_SUPER_SECRET", composio=cc)
    for call in cc.calls:
        if call["url"].endswith("/org/owner/project/new"):
            assert call["headers"].get("x-org-api-key") == "ak_ORG_SUPER_SECRET"
        else:
            # every non-project call uses the project key, never the org key
            assert call["headers"].get("x-api-key") == "ak_project_SCOPED"
            assert "x-org-api-key" not in call["headers"]


def test_actor_server_has_no_send_tool():
    cc = FakeClient(org_key="ak_ORG")
    pc.provision("suffolk", ["gmail"], "client:suffolk", org_key="ak_ORG", composio=cc)
    server_calls = [c for c in cc.calls if c["url"].endswith("/mcp/servers")]
    assert len(server_calls) == 2  # reader + actor
    for c in server_calls:
        for tool in c["body"]["allowed_tools"]:
            assert "SEND" not in tool, f"{c['body']['name']} leaked a send tool: {tool}"


def test_reader_allowlist_is_read_only():
    cc = FakeClient(org_key="ak_ORG")
    pc.provision("suffolk", ["gmail"], "client:suffolk", org_key="ak_ORG", composio=cc)
    reader = next(c for c in cc.calls
                  if c["url"].endswith("/mcp/servers") and "reader" in c["body"]["name"])
    assert "GMAIL_CREATE_EMAIL_DRAFT" not in reader["body"]["allowed_tools"]
    assert "GMAIL_FETCH_EMAILS" in reader["body"]["allowed_tools"]


def test_unknown_platform_rejected():
    cc = FakeClient(org_key="ak_ORG")
    with pytest.raises(pc.ComposioError):
        pc.provision("suffolk", ["whatsapp"], "client:suffolk", org_key="ak_ORG", composio=cc)
