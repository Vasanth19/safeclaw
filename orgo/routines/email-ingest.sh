#!/usr/bin/env bash
# SafeClaw email-ingestion routine.
# Runs the READER profile (read-only Gmail + gbrain). Registered as an actor-scheduler
# cron job with --no-agent: this script IS the job; its stdout is the run record.
#
# Cold-start hardening: the Composio Gmail HTTP MCP is intermittently not ready in
# the agent's first turn (~50% on a cold spawn), which makes the run report
# "gmail MCP tools unavailable" and ingest nothing even when mail is waiting. We
# retry up to 3 times, breaking as soon as a run does NOT report an MCP-unavailable
# error. The final run's output is the cron record.
export HERMES_HOME=/root/.hermes/profiles/reader
export PATH=/usr/local/bin:/tmp/node-v20.18.1-linux-x64/bin:$PATH

read -r -d '' PROMPT <<'PROMPT_EOF'
You are the scheduled email-ingestion routine. Work silently and do not ask questions.

CRITICAL - tool availability check FIRST: you MUST use the Gmail MCP tools (from the gmail_reader / gmail_* servers) for all email access. If those MCP tools are not in your tool list, do NOT improvise with CLI tools and do NOT report zero results - immediately stop and output exactly one line: INGEST ERROR: gmail MCP tools unavailable. Likewise if the gbrain tools are missing, output: INGEST ERROR: gbrain MCP tools unavailable.

IMPORTANT - keep tool outputs SMALL. Never fetch full email bodies in a list call: list with snippets/headers only, and fetch the full body of ONE email at a time, only for emails that pass the filter.

STEP 1 - LIST. For EACH connected Gmail inbox (every gmail_* MCP server): list emails using the Gmail search query: in:inbox category:primary -in:spam -in:trash newer_than:2h
Use max_results=10 and request MINIMAL payload (no bodies - ids, from, subject, date, snippet only; e.g. include_payload=false or verbose=false if the tool supports it). Gmail has already categorized these - only Primary-category inbox mail comes back. If a list returns nothing, that inbox has no new mail; move on.

STEP 2 - FILTER on from/subject/snippet. Keep ONLY emails worth remembering:
- written by a real person, OR
- containing actionable business content: deals, invoices, payments, commitments, questions, meeting requests, deadlines, decisions.
DISCARD: newsletters, marketing/promotional mail, automated notifications, OTP/verification codes, social-network updates, no-action receipts, calendar auto-responses.

STEP 3 - STORE. For each email that passed the filter:
a) Check the brain with get_page for slug: emails/<YYYY-MM-DD>-<short-kebab-subject>  - if it exists, skip (already ingested).
b) Otherwise fetch that single email by its message id to get the body.
c) Create the page with put_page:
   - slug: emails/<YYYY-MM-DD>-<short-kebab-subject>
   - title: the email subject
   - content: From, To, Date, Subject, which inbox it arrived in, a 3-5 sentence summary, any action items as a bullet list, and the Gmail message id.

STEP 4 - REPORT. End with exactly one line: INGEST RESULT: <listed> listed, <ingested> ingested, <filtered-out> filtered out, <dupes> already known.
PROMPT_EOF

out=""
for attempt in 1 2 3; do
  out="$(hermes chat -Q --max-turns 60 -q "$PROMPT" 2>&1)"
  if ! printf '%s' "$out" | grep -q "MCP tools unavailable"; then break; fi
  echo "[email-ingest] attempt ${attempt}/3 hit Composio MCP cold-start; retrying in 8s..." >&2
  sleep 8
done
printf '%s\n' "$out"
