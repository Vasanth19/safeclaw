# Orgo fleet hardening — week of 2026-06-08 to 06-13

> **What this is.** A changelog of the work done across the four live orgo client
> boxes this week (Matt, Travis, Elise, Phil), written so the changes can be
> reviewed and merged upstream. The headline is that the orgo brains moved off
> PGlite onto a supervised Postgres + pgvector, which corrects the single biggest
> deviation called out in `VPS-VS-ORGO-DEVIATIONS.md` ("no Postgres+pgvector").
>
> **No secrets.** Every credential below is a placeholder: `<COMPOSIO_API_KEY>`,
> `<OPENROUTER_API_KEY>`, `<BRAIN_DB_PASSWORD>`, `<ADMIN_BOOTSTRAP_TOKEN>`.

---

## 1. Brain engine: PGlite → supervised Postgres + pgvector (non-Docker)

**Why.** The orgo boxes have no Docker, so `docker-compose.brain.yml` never ran and
the brains fell back to PGlite. PGlite is a single-writer WASM Postgres; under
concurrent writers, dirty shutdowns, and reboots it corrupts, and the brains were
crashing fleet-wide with a WASM `Aborted()` error that took the brain offline until a
manual rebuild. (The earlier "macOS version" theory was a misattribution.)

**What changed.** Each brain now runs a real local Postgres with the pgvector
extension, supervised by supervisord so it restarts cleanly. Each brain stays
**self-contained on its own box** — deliberately NOT a shared database, because a
client must be able to leave with their own data. Durability was proven: `kill -9`
on Postgres recovered in ~3s with no data loss.

Supervisor program written to each box at `/etc/supervisor/conf.d/postgres-brain.conf`:

```ini
[program:postgres-brain]
command=/usr/lib/postgresql/16/bin/postgres -c config_file=/etc/postgresql/16/main/postgresql.conf
user=postgres
autostart=true
autorestart=true
stopsignal=INT
```

gbrain is pointed at Postgres by setting `GBRAIN_DATABASE_URL` in `/opt/brain/.env`;
gbrain auto-selects the Postgres engine when that env is present.

### 1a. The BYPASSRLS trap (important)

Creating the brain role with `SUPERUSER` alone is **not enough**. gbrain's v24 schema
step `rls_backfill_missing_tables` checks the explicit `rolbypassrls` flag, which
superuser does **not** set. The schema then halts at v23/113 and writes fail with
`column chunker_version does not exist`. Correct provisioning:

```sql
CREATE ROLE brain LOGIN SUPERUSER BYPASSRLS PASSWORD '<BRAIN_DB_PASSWORD>';
```

Then re-run `gbrain init --url <postgres-url> --embedding-model openrouter:openai/text-embedding-3-small`.
The embedding model must be named at init so the vector column is created at the right
width (1536). A dimension mismatch ("expected 1280 not 1536") means the column was made
before the model was set; `DROP DATABASE brain WITH (FORCE)` and re-init.

### 1b. Embeddings: OpenRouter, not local Ollama

The boxes embed via OpenRouter (`openai/text-embedding-3-small`, 1536-dim), not the
`BRAIN_EMBEDDINGS_URL` Ollama daemon the Docker path assumes. `OPENROUTER_API_KEY`
lives in `/opt/brain/.env`. This is a deviation from `client.env.example`.

### 1c. Durable admin bootstrap token

After a DB rebuild the gbrain OAuth token is orphaned and the brain MCP returns 401.
Set a durable `GBRAIN_ADMIN_BOOTSTRAP_TOKEN` in `/opt/brain/.env` so a rebuild can
re-mint the gateway api-key and rewire the gateway without manual surgery.

---

## 2. Gateway consolidation

The actor and reader profiles each had their own supervised gateway, which had drifted
into an inconsistent state across the fleet and was the source of most confusion when
something broke. Consolidated supervision to a **single** `hermes-gateway-actor` on
every box. The read-only reader profile is retained for ingestion (the cron jobs still
run it), but there is now one gateway and one consistent supervision shape.

The reader/actor trust split therefore remains as **profile + tool-allowlist
isolation**, but the gateway is no longer duplicated.

---

## 3. Ingestion fixes

See `routines/README.md` for the full gotcha list. Summary of this week's fixes to
`email-ingest.sh`:

- **`category:primary` returned zero.** These mailboxes do not use Gmail category
  tabs, so `in:inbox category:primary` matched nothing and every run reported nothing
  to ingest. Removed the category filter; the LLM content filter drops promo mail.
- **Stale, box-specific server names.** The prompt hard-referenced `gmail_reader /
  gmail_acct1 / gmail_acct2` and named inboxes that do not exist on these boxes, so the
  availability check aborted. The routine is now **generic**: it uses whatever Gmail MCP
  tool is present (gmail / gmail_reader / gmail_elise / ...) and the window and turn cap
  are arguments (`email-ingest.sh <WINDOW> <MAXTURNS>`).
- **Cold-start fragility.** One box loaded five remote Composio servers in its reader
  profile (gmail + tasks + sheets + drive + chat) and Gmail lost the startup race, so
  the agent aborted before its tools registered. **Keep the reader profile lean: gmail +
  gbrain only.** The other Google tools belong in the actor profile.
- Added `ingest-retry.sh`, a retry wrapper for backfills that re-runs until a clean
  `INGEST RESULT` lands, to ride out transient MCP cold-starts.

---

## 4. New capability: Composio → gbrain calendar bridge

`routines/calendar-collect.py` is a deterministic collector that pulls Google Calendar
through **Composio's tool-execute API** and writes gbrain's native daily files at
`/opt/brain/repo/daily/calendar/{YYYY}/{YYYY-MM-DD}.md`, which then `gbrain import` +
`gbrain embed --stale`.

**Why this shape.** gbrain ships native Gmail and Calendar senses, but they depend on
its own credential gateway (ClawVisor or a direct Google OAuth app). We use Composio for
client login (one authorize link). Rather than switch credential systems, the collector
calls Gmail/Calendar **through Composio**, so Composio owns all OAuth and token refresh
and we hold no token files. This also follows gbrain's own "code pulls data, LLM only
judges" rule, which the agent-driven ingest violated.

Key implementation facts:
- Calendar list tool: `GOOGLECALENDAR_EVENTS_LIST`. Execute at
  `POST https://backend.composio.dev/api/v3/tools/execute/<SLUG>` with body
  `{user_id, connected_account_id, arguments}`. **Both** user_id and
  connected_account_id are required; calendar also needs `arguments.calendarId:"primary"`.
  Paginate on `nextPageToken`.
- Resolve the account from `GET /api/v3/connected_accounts?statuses=ACTIVE`, pick
  `toolkit.slug=="googlecalendar"`, use its `id` + `user_id`. The Composio key is read
  from any of `/opt/brain/.env`, `/root/.hermes/.env`, `/opt/safeclaw/client.env`
  (location varies by box — Matt's is in `client.env`).

**Recurring sync.** `calendar-sync.sh` wraps the collector: it runs
`calendar-collect.py <days>` (45 by default for incremental catch-up) then
`gbrain import` + `embed --stale`, and is registered as a daily `hermes cron`
(`30 5 * * *`, `--no-agent`). Idempotent — day files overwrite, import upserts.

**Deployment status (2026-06-13).** Deployed, backfilled (365 days), and scheduled on
all three calendar-connected boxes: Elise 335 day-pages, Matt 258 (438 events), Travis
197 (403 events). Phil has no Composio, so no calendar.

### 4a. gbrain gotcha: `list` truncates at 50

`gbrain list -n N` caps output at ~50 rows regardless of `-n`. Never count or bulk-
delete pages by piping it to grep — it under-reports and makes deletions look like data
loss. Use Postgres directly for any bulk operation:
`psql -d brain -tAc "select slug from pages where ... and deleted_at is null"`.

---

## 5. Current fleet state (2026-06-13)

All four boxes: Postgres engine, supervised, gateway healthy, embeddings on.

| Box | Pages | Calendar | Connectors live |
|-----|-------|----------|-----------------|
| Elise | 5 email + 335 calendar | yes | gmail, calendar, docs, sheets, tasks |
| Matt | 12 email + 258 calendar | yes | gmail, calendar, GHL |
| Travis | 6 email + 197 calendar | yes | gmail, calendar, drive, sheets, tasks, GHL |
| Phil | 0 | no | none (WhatsApp only) |

Email ingestion is scheduled hourly and succeeding on Travis/Matt/Elise (Travis's cron
was timing out at 120s until `cron.script_timeout_seconds: 1800` was added to his actor
config and the schedule fixed to hourly). The calendar bridge is deployed, backfilled,
and scheduled daily on all three.

Open items: Phil has no Composio wired yet (no data source); a security tightening pass
(scope-down, surgical approval gates, per-client credential isolation) is the next phase.
