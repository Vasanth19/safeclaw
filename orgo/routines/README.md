# Client routines — `hermes cron` scripts

Recurring jobs deployed onto orgo client boxes. Each script lives at
`$ACTOR_HOME/scripts/<name>.sh` on the box and is registered in the **actor**
profile's scheduler (the only always-running gateway — reader crons never fire).
See ORGO-CLIENT-TEMPLATE.md Step 5 for the registration pattern and the
03:00/04:00 blackout windows.

| Script | Schedule | Profile it runs | What it does |
|--------|----------|-----------------|--------------|
| `email-ingest.sh` | `15 * * * *` (hourly at :15) | reader (read-only Gmail) | Lists `category:primary` inbox mail from all connected inboxes (snippets only), LLM-filters to emails worth remembering, stores summary pages in gbrain under `emails/<date>-<subject>` with dedup. |

## Deploying a routine to a box

```bash
# 1. Copy the script (base64 over orgo /bash — no scp on orgo boxes)
B64=$(base64 -i orgo/routines/email-ingest.sh | tr -d '\n')
orgo_bash "echo '$B64' | base64 -d > /root/.hermes/profiles/actor/scripts/email-ingest.sh && chmod +x /root/.hermes/profiles/actor/scripts/email-ingest.sh"

# 2. Test it once manually in tmux (NEVER trust a routine you haven't run)
orgo_bash "tmux new-session -d -s ingest-test 'bash /root/.hermes/profiles/actor/scripts/email-ingest.sh > /tmp/ingest-test.log 2>&1; echo EXIT_CODE=\$? >> /tmp/ingest-test.log'"
# ... poll /tmp/ingest-test.log for the INGEST RESULT line

# 3. Register the cron (actor scheduler, --no-agent because the script runs hermes chat itself)
orgo_bash 'HERMES_HOME=/root/.hermes/profiles/actor hermes cron create "15 * * * *" \
  --name email-ingest --script email-ingest.sh --no-agent --deliver local'
```

## Gotchas (learned on mark-agent, 2026-06-02)

- **`hermes chat` flag order:** `-q` TAKES the prompt (`--query`); `-Q` is quiet.
  `-q -Q "..."` fails. Correct: `hermes chat -Q -q "<prompt>"`.
- **Reader profile caps iterations at 25** (`agent.max_turns` in its config) —
  a multi-inbox ingest needs more; pass `--max-turns 60` explicitly.
- **Never list emails with full bodies.** A 15-email fetch with payloads from a
  busy inbox is ~170 KB and blows the 50 KB tool-output cap. List with
  snippets/headers (`max_results<=10`, minimal payload), then fetch single
  messages by id only for emails that pass the filter.
- **Cadence floor is hourly.** glm-4.7 under the ~90-tool reader load takes
  minutes per step; a run can take 10–30 min. 15/30-min schedules will overlap.
- **🚨 hermes cron kills `--no-agent` scripts after 120s by default.** A run that
  finds nothing finishes in ~100s, but any run that actually ingests emails takes
  5–15+ min and gets killed — i.e. the routine only "succeeds" when there's nothing
  to do. Fix: set `cron.script_timeout_seconds: 1800` in the **actor** profile's
  `config.yaml` (also overridable via `HERMES_CRON_SCRIPT_TIMEOUT` env). The config
  cache is mtime-keyed, so the running gateway picks it up without restart.
  Found live on mark-agent: 3 of the first 10 scheduled runs died at 120s.
- **Transient MCP failures produce silent fake zeros.** One mark-agent run lost the
  Composio Gmail MCP connection and the agent reported `0 listed` instead of an
  error (it even suggested installing CLI mail tools). The prompt now opens with a
  tool-availability check that outputs `INGEST ERROR: gmail MCP tools unavailable`
  instead of a fake zero — grep cron output for `INGEST ERROR` when auditing.
