# Admin Onboarding Workstream

This branch starts the agency-operated onboarding rebuild.

## Current branch

`feat/admin-onboarding-control-plane`

## Primary spec

See [`docs/ADMIN-ONBOARDING-CONTROL-PLANE.md`](../docs/ADMIN-ONBOARDING-CONTROL-PLANE.md).

## Build order

1. Client registry schema and sample.
2. Admin-agent runbook.
3. Orgo remote execution helper.
4. Normal Hermes + G-Brain client bootstrap script.
5. Health checker.
6. Composio project-per-client helper/checklist.
7. Generic Reader/Actor profile templates.
8. Slack gateway routing spec.

## Principle

Preserve SafeClaw's useful architecture:

- Reader/Actor trust split.
- G-Brain memory-first behavior.
- structured observations.
- no auto-send by default.
- bootstrap from Gmail/Slack into brain.

But avoid making future client installs depend on a heavy custom SafeClaw runtime when normal Hermes + G-Brain can do the job.
