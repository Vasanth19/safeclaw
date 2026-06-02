# Admin onboarding control plane

This directory contains operator-facing artifacts for the SafeClaw admin onboarding flow.

## Client OAuth onboarding

`client-onboarding/matt-hoover/` contains the current Netlify source for Matt Hoover's assistant setup page. It uses a server-side Netlify function to create fresh Composio connection links on click. The static HTML does not store link tokens.

Use `client-onboarding/matt-hoover/` as the first reusable client-template implementation. The admin agent should copy this structure when provisioning a new Orgo client install, then replace client-specific labels, service cards, Composio user IDs, aliases, and auth config IDs. See `client-onboarding/README.md` for the human-in-the-loop Composio checkpoints.

Current services:

- Google Calendar
- Gmail
- Google Docs
- Google Sheets
- Google Tasks

Runtime secret requirement:

- `COMPOSIO_API_KEY` must be set as a server-side environment variable in the deployment host.

Do not commit Composio API keys, OAuth tokens, or generated one-time link URLs.

## Dashboard artifacts

`dashboard/marcus-v2/` contains the dashboard source and handoff contract that Jake asked to carry with this branch. It is included here as an admin-dashboard reference until it is wired into the SafeClaw runtime.
