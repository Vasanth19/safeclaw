---
name: calendar-to-brain
description: Pull Google Calendar through Composio into gbrain daily files so the agent knows the schedule and meeting history.
version: 1.0.0
author: SafeClaw
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [google-calendar, calendar, ingestion, brain, composio, integration]
    category: integrations
    requires_toolsets: [native-mcp]
---

# Calendar to brain ingestion

## When to use

Use this skill to sync Google Calendar into the brain, either as a one time
backfill or on a recurring schedule. It writes one searchable page per day with
events, attendees, and locations, which is the foundation for meeting prep and
relationship history. This is a **Reader** capability: read only, no writes back
to the calendar.

> Trust boundary: read only. It reads calendar events through Composio and writes
> `daily/calendar/...` pages to the brain. It never creates or edits events.

## Why through Composio

gbrain ships a native `calendar-to-brain` recipe, but it depends on its own
credential gateway (ClawVisor or a direct Google OAuth app). SafeClaw uses
**Composio** for the client login (one authorize link). So this skill calls
Calendar **through Composio's tool execute API**: Composio owns the OAuth and the
token refresh, and we hold no token files. This also follows the deterministic
collector rule, code pulls the data, the model only judges.

## Prerequisites

- An **active** Google Calendar connection in the client's Composio project.
- The box Composio key (the collector searches `/opt/brain/.env`,
  `/root/.hermes/.env`, `/opt/safeclaw/client.env`).
- gbrain reachable.

## Procedure

The deployed implementation is `orgo/routines/calendar-collect.py`, wrapped for
recurring runs by `orgo/routines/calendar-sync.sh` (daily cron). The flow:

1. Resolve the account: `GET /api/v3/connected_accounts?statuses=ACTIVE`, pick
   `toolkit.slug == "googlecalendar"`, take its `id` and `user_id`.
2. Page through events: execute `GOOGLECALENDAR_EVENTS_LIST` at
   `POST /api/v3/tools/execute/<SLUG>` with body
   `{user_id, connected_account_id, arguments}`. Arguments need
   `calendarId: "primary"`, a `timeMin`/`timeMax` window, `singleEvents: true`,
   `orderBy: "startTime"`. Follow `nextPageToken`.
3. Write one file per day at `daily/calendar/{YYYY}/{YYYY-MM-DD}.md` with each
   event's time, title, attendee names (no email addresses), and location. Skip
   cancelled events.
4. `gbrain import daily/calendar/...` then `gbrain embed --stale`. Idempotent:
   day files overwrite, import upserts, embed only touches stale pages.

## Pitfalls

- **Both `user_id` and `connected_account_id` are required** on the execute call,
  and Calendar also requires `arguments.calendarId`. Omitting any returns a 400.
- **The Composio key location varies by box.** Search the standard env files,
  do not assume one path.
- **A connection that shows EXPIRED never finished consent.** If the backfill
  finds no active calendar, the client did not complete the Google authorize
  screen; have them reconnect and finish the Allow step.
- **Backfill window vs incremental.** Pass a large days back value (for example
  365) for the first backfill, a small one (for example 45) for the recurring
  sync so it stays current cheaply.
