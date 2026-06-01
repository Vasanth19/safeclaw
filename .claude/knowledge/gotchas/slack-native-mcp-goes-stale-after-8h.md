---
date: 2026-05-29
tags: [hermes, mcp, stdio-mcp, slack, long-running, watchdog, safeclaw]
related-services: [safeclaw-hermes-reader, slack-api-mcp]
source: session
---

# Hermes' stdio-spawned MCP child goes silent after ~8h running

## Context
SafeClaw's reader spawns a `slack_native` MCP as a long-lived stdio subprocess (`node /opt/mcp-tools/slack-api/dist/index.js`). The child does NOT crash — `/opt/data/logs/mcp-stderr.log` only ever shows `SafeClaw Slack MCP running in reader mode` on each fresh launch — but after ~8h of uptime the tool calls themselves silently fail with **empty-error `ClosedResourceError`** in the agent log:

```
ERROR [cron_…] tools.mcp_tool: MCP tool slack_native/slack_list_channels call failed:
ERROR [cron_…] tools.mcp_tool: MCP slack_native/list_resources failed:
```

Note the empty string after `failed:` — Hermes' MCP-tool wrapper caught a `ClosedResourceError` exception but the exception message is the empty string, so the operator sees a real failure with zero diagnostic content. Meanwhile, Slack's own API is healthy (`auth.test` returns ok, `conversations.list` returns channels) and the stderr log shows no crash, so it looks like nothing is wrong from any single side.

Suffolk timeline that surfaced this:
- 2026-05-28 01:01:01 — last `starting MCP server 'slack_native'` line in mcp-stderr.
- 2026-05-28 09:11 — last successful Slack ingest page written.
- 2026-05-28 09:12 → 2026-05-29 ~17:14 — every cron tick logs an empty-error MCP failure. No fresh stderr boot lines.
- 2026-05-29 17:12 — `docker compose restart hermes-reader` → fresh boot at 17:14:01 → calls work again.

## Why this happens (working theory)
A long-lived stdio MCP child shares a pair of pipes with the gateway. When the gateway-side reader closes (or the kernel's pipe buffer gets into a weird state, or the child's stdio handles drift after many millions of bytes), subsequent JSON-RPC reads return EOF immediately. The child process is still alive (no crash, no new "starting…" line) but its stdio is effectively closed → `anyio.ClosedResourceError`. The MCP wrapper raises with no message because `str(ClosedResourceError())` is empty by default.

## Workaround (until a watchdog ships)
**Restart the reader container.** This recycles the stdio MCP child:
```bash
ssh suffolk-vps 'cd /opt/safeclaw && docker compose restart hermes-reader'
# wait ~10-15s for the gateway to fully boot
docker exec safeclaw-hermes-reader tail -3 /opt/data/logs/mcp-stderr.log
# expect a new "===== [<ts>] starting MCP server 'slack_native' =====" line
```

Verify the next cron tick reaches Slack (no empty-error MCP failure):
```bash
docker exec safeclaw-hermes-reader tail -F /opt/data/logs/agent.log | grep -E "MCP tool|slack_list_channels|put_page"
```

## Proper fix (open follow-up)
One of:
1. **Daily reader restart cron on the host** (cheapest):
   ```cron
   15 4 * * *  /usr/bin/docker -c default compose -f /opt/safeclaw/docker-compose.yml restart hermes-reader
   ```
   Restart in a quiet window (4 AM), well outside the `0 */2 * * *` ingest schedule, to avoid clobbering an in-flight run.
2. **stdio-MCP watchdog in `scripts/safeclaw-cron-sync.py`** that pings each stdio MCP every hour and restarts the parent gateway on `ClosedResourceError`. More work but self-healing.
3. **Upstream fix** in `vendor/hermes-agent/tools/mcp_tool.py`: on `ClosedResourceError`, transparently respawn the stdio child instead of surfacing as a tool failure. Cleanest but lives in upstream Hermes code we don't own.

## Diagnostic signature (so you recognize it next time)
- `agent.log` has `MCP tool <name>/<call> call failed:` lines with **empty string after the colon** — that's the tell.
- `mcp-stderr.log` has NO new `starting MCP server` line since hours ago — the child didn't crash.
- Direct probe to the underlying service (Slack `auth.test`, Composio whoami, etc.) **succeeds** — rules out token / network / scope problems.
- Solved instantly by `docker compose restart <hermes-service>`.

## Don't confuse with
- **MCP failed to authorize / wrong token** — surfaces with a non-empty error like `invalid_auth` or `not_authed`.
- **MCP fully crashed / OOM'd** — mcp-stderr would show a fresh `starting…` block and probably a Node traceback above it.
- **The brain MCP HTTP transport going dead** — that's an HTTP-not-stdio MCP (`safeclaw_brain.url`), surfaces as `MCP safeclaw_brain/list_resources failed: Method not found` or `Connection refused`, not empty-string.

## Related
- `decisions/safeclaw-ingest-working-config.md` — the recovery procedure includes a `restart hermes-reader` step now.
- Hermes source: `vendor/hermes-agent/tools/mcp_tool.py` — `ClosedResourceError` handling is the empty-error culprit.
