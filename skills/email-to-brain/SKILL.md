---
name: email-to-brain
description: Ingest important Gmail into the brain as deduplicated summary pages, filtering out noise.
version: 1.0.0
author: SafeClaw
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [gmail, email, ingestion, brain, integration]
    category: integrations
    requires_toolsets: [native-mcp]
---

# Email to brain ingestion

## When to use

Use this skill when the scheduled email routine runs, or when the user asks to
pull recent email into the brain. This is a **Reader** capability: it lists and
reads Gmail and writes summary pages to the brain. It never sends or drafts.

> Trust boundary: bound to the SafeClaw **Reader** (read only). It uses the
> Gmail MCP read tools plus `mcp_safeclaw_brain_*`. It must not be loaded into
> the Actor, and it never sends or deletes mail.

## Prerequisites

- A Gmail connection on the Reader (Connections tab, Gmail, Reader).
- gbrain reachable. The reader profile should carry **only** Gmail and gbrain
  (see pitfalls).

## Quick reference

| Tool | Purpose |
|------|---------|
| Gmail list/search | list recent inbox mail, snippets only |
| Gmail fetch by id | fetch one full message body, only after it passes the filter |
| `mcp_safeclaw_brain_get_page` | dedupe check by slug before storing |
| `mcp_safeclaw_brain_put_page` | store the summary page |

## Procedure

1. **Tool check first.** Confirm a Gmail MCP tool is present (the server may be
   named gmail, gmail_reader, gmail_elise, etc., any is fine) and that gbrain
   tools are present. If either is missing, stop and emit one line
   `INGEST ERROR: gmail MCP tools unavailable` (or the gbrain equivalent) rather
   than a fake zero.
2. **List.** For each Gmail inbox, search `in:inbox -in:spam -in:trash newer_than:<WINDOW>`
   with a small `max_results` and minimal payload (ids, from, subject, date,
   snippet). Do **not** request bodies in the list call.
3. **Filter** on from, subject, and snippet. Keep only mail written by a real
   person or carrying actionable business content (deals, invoices, payments,
   commitments, questions, meetings, deadlines, decisions). Discard newsletters,
   promotions, automated notices, OTP codes, social updates, receipts.
4. **Store**, oldest first. For each keeper: dedupe by slug
   `emails/<YYYY-MM-DD>-<short-kebab-subject>` with `get_page`; if new, fetch the
   single message body and `put_page` with From, To, Date, Subject, a short
   summary, action items, and the Gmail message id.
5. **Report.** End with one line:
   `INGEST RESULT: <listed> listed, <ingested> ingested, <filtered> out, <dupes> known`.

The deployed implementation is `orgo/routines/email-ingest.sh` (window and turn
cap are args). For backfills wrap it with `orgo/routines/ingest-retry.sh`.

## Pitfalls

- **Never add `category:primary`.** These mailboxes have no Gmail category tabs,
  so that filter matches nothing and every run reports zero. Use plain
  `in:inbox` and let the content filter drop promo mail.
- **Do not hard code Gmail server names.** Boxes name the server differently. Use
  whatever Gmail tool is present.
- **Keep the Reader profile lean: Gmail plus gbrain only.** Loading several remote
  Composio servers in the Reader makes Gmail lose the cold start race so the agent
  aborts before its tools register. Tasks, Sheets, Drive, and Chat belong in the
  Actor.
- **`gbrain list -n N` truncates at about 50 rows** regardless of `-n`. Never
  count or bulk delete pages by piping it to grep. Use Postgres directly.
- **Keep tool outputs small.** A multi message fetch with bodies can blow the tool
  output cap; list with snippets, fetch single bodies only for keepers.
