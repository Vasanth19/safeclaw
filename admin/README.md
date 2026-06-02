# Admin onboarding control plane

This directory contains operator-facing artifacts for the SafeClaw admin onboarding flow.

## Client OAuth onboarding

`client-onboarding/matt-hoover/` contains the current Netlify source for Matt Hoover's assistant setup page. It uses a server-side Netlify function to create fresh Composio connection links on click. The static HTML does not store link tokens.

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
