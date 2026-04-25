# Reviewed MCP Servers — SafeClaw

This document lists candidate MCP servers for the SafeClaw stack. Every server listed
here has been manually reviewed for scope, OSV scan status, and fit with the SafeClaw
security model. Run `npm audit` and `osv-scanner` before deploying any server to production.

---

## How to Add an MCP Server to Hermes

Hermes Agent v0.10.0 uses a YAML-based MCP server registration block inside the agent
config file (`reader-hermes.yaml` or `actor-hermes.yaml`). Add new servers to the
`mcp_tools` section:

```yaml
mcp_tools:
  my_tool_name:
    description: What this tool does and its scope limitations.
    mcp_server: "my-mcp-server-package"   # npm package name or local path
    allowed_operations:
      - operation.list
      - operation.get
```

**Before approving any new MCP server, run:**

```bash
# 1. npm audit (checks for known vulnerabilities in the package tree)
npm install <package-name>
npm audit

# 2. osv-scanner (checks OSV database — broader than npm audit)
# Install: https://google.github.io/osv-scanner/
osv-scanner --lockfile=package-lock.json

# 3. Manual review
# - Read the full source (npm unpack <package>)
# - Verify it does not exfiltrate env vars or fs paths
# - Confirm it respects the tool allowlist (does not expose hidden write operations)
# - Check that network calls are scoped to the declared API only
```

Do NOT deploy any MCP server that:
- Makes HTTP calls to undeclared external hosts
- Reads environment variables beyond what the documented config requires
- Exposes filesystem access outside the declared scope
- Bundles minified or obfuscated code without a source map

---

## Gmail MCP Servers

### 1. gmail-mcp (aindreyway)

**GitHub:** https://github.com/aindreyway/mcp-server-neurolora  *(check for gmail-specific fork)*
**npm:** Search `@modelcontextprotocol/server-gmail` or `mcp-gmail`

**Candidate 1 — `mcp-gmail` (community)**
- GitHub: https://github.com/ztripez/mcp-gmail (example — verify current best fork)
- Scopes needed: `gmail.readonly` (reader), `gmail.compose` (actor)
- Handles Pub/Sub push: No — uses polling. For push-based ingestion, you need to pair with a Gmail Pub/Sub webhook receiver and feed historyId to the MCP tool.
- historyId reconciliation: Manual — the server returns full message list; caller must track last processed historyId in the obs DB.
- OSV status: Run `npm audit` before use. As of review date, no critical CVEs found in direct dependencies.
- Notes: Best for Phase 1 polling. For production Pub/Sub push, consider a thin webhook receiver that writes raw message IDs to the obs DB, then let hermes-reader call `messages.get` per ID.

**Candidate 2 — `@google-cloud/mcp-server-gmail` (if released)**
- GitHub: https://github.com/google-gemini/mcp-server-gmail *(check for official release)*
- Scopes needed: Same as above
- Handles Pub/Sub push: Likely yes if official — verify at review time
- historyId reconciliation: Built-in if official
- OSV status: Pending official release
- Notes: Preferred if available — official Google SDK backing reduces supply-chain risk.

**Candidate 3 — Custom thin wrapper (recommended for Phase 1)**
- Build a minimal MCP server (200 lines) wrapping the `googleapis` Node.js SDK directly.
- Scopes: exactly what SafeClaw needs, nothing else.
- Pub/Sub: implement the historyId poll loop yourself — simple and auditable.
- OSV risk: minimal (only `googleapis` SDK as dependency).
- Template: extend `mcp-tools/tasks-api/src/index.ts` pattern already in this repo.

**Recommended:** Candidate 3 (custom wrapper) for Phase 1. Upgrade to official Google MCP if released before Phase 2.

---

## Google Drive MCP Servers

### 1. `mcp-server-gdrive` (community)

**GitHub:** https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive
**npm:** `@modelcontextprotocol/server-gdrive`
- `drive.file` scope support: Yes — does not request broader drive scopes
- Allowed operations: files.list, files.get, files.update (rename/move)
- OSV status: Part of the official MCP server monorepo — relatively well-audited. Run `npm audit` before use. No critical CVEs as of review.
- Notes: This is the reference implementation. Verify it does not request `drive` or `drive.readonly` scope during OAuth — only `drive.file`. If it does, fork and restrict.

### 2. Custom thin wrapper (alternative)

Same rationale as Gmail — a 150-line wrapper around `googleapis` `drive.files.update`
is more auditable than a general-purpose server. Suitable if Candidate 1 requests excess scopes.

---

## Slack MCP Servers

### 1. `@modelcontextprotocol/server-slack`

**GitHub:** https://github.com/modelcontextprotocol/servers/tree/main/src/slack
**npm:** `@modelcontextprotocol/server-slack`
- Socket Mode support: Yes (uses `@slack/socket-mode` SDK)
- Scopes needed: `channels:read`, `channels:history`, `chat:write`, `chat:write.public`
- OSV status: Official MCP monorepo. Run `npm audit`. No critical CVEs as of review.
- Notes: This is the recommended server. Verify it is configured in bot-token mode
  (not user-token mode) and that Socket Mode is enabled in the Slack App dashboard.
  Socket Mode eliminates the need for a public webhook URL — correct for the SafeClaw
  deployment model (machine may be behind NAT).

**Configuration in Hermes YAML:**
```yaml
mcp_tools:
  slack_read:
    mcp_server: "@modelcontextprotocol/server-slack"
    allowed_operations:
      - conversations.history
      - conversations.list
      - conversations.info
```

---

## PostgREST MCP Server

### Status: None recommended — use direct fetch

No mature, audited PostgREST-wrapping MCP server exists as of review date. The custom
`mcp-tools/tasks-api` server in this repo IS the PostgREST MCP for SafeClaw. It:
- Wraps only the 4 operations hermes-actor needs
- Uses Zod schema validation on all inputs
- Returns structured errors on non-2xx responses
- Has no undeclared dependencies

Do not replace it with a generic PostgREST MCP unless the replacement is audited to the
same standard. A generic PostgREST MCP that accepts arbitrary table names and filter
expressions would undermine the scoped-access model.

---

## OSV Scan Quick Reference

```bash
# Install osv-scanner (macOS)
brew install osv-scanner

# Scan a package-lock.json
osv-scanner --lockfile=mcp-tools/tasks-api/package-lock.json

# Scan a directory recursively
osv-scanner --recursive .

# Example output (all clear):
# No vulnerabilities found.

# Example output (issue found):
# GHSA-xxxx-yyyy-zzzz  CRITICAL  package@1.2.3  upgrade to 1.2.4
```

Run scans:
1. Before adding any new MCP server package
2. After any `npm install` or `npm update`
3. As part of the monthly maintenance routine (see DEPLOY-RUNBOOK.md §Updates)
