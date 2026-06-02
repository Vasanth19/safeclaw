# Handoff: Wire Hermes's nightly dreaming into the dashboard's Active Priorities

**For:** Hermes (the nightly agent)
**From:** Marcus dashboard
**Goal:** Make the "Active Priorities" view at dashboard.therereset.com show the real work that has to get done now and coming up, ranked by the dreaming phase.

The dashboard (consumer) side is already built and live. This doc is the producer contract: what Hermes must write each night so the dashboard picks it up. Nothing in the dashboard changes after this. Your job is to fill the store the dashboard already reads.

---

## How it fits together

There are two planes. Keep them separate.

1. **Dream plane (yours).** Every night the dreaming phase reasons over everything in the brain plus ClickUp, calendar, mail, and Slack, then writes a ranked list of priorities into the Supabase table `marcus_priorities` with `source = 'brain'`. These carry a one-line rationale and, when a priority maps to a ClickUp task, the task id + url.

2. **Live plane (dashboard's).** At every page load the dashboard pulls open ClickUp tasks assigned to Jake directly from the ClickUp API and merges them in, so due dates and brand-new tasks are always current without waiting for the next dream. The dashboard de-dupes: any ClickUp task you already cited (by `clickup_task_id` or `url`) is shown once, using your row.

So you do **not** write ClickUp tasks as separate rows. You write reasoned priorities. When one of your priorities *is* a ClickUp task, cite it so the live merge collapses them.

The dashboard endpoint is `GET /api/priorities` in `marcus-agent/v2/dashboard/server.js`. Read that handler if you want the exact merge and bucketing logic. You don't need to call it; you only need to write the table correctly.

---

## Where to write: Supabase `marcus_priorities`

The dashboard reads this table with `select('*')` and ignores rows whose `status` is `dropped` or `superseded`. The base table exists (`marcus-agent/migrations/001_initial_schema.sql`). It needs a few additive columns. Run this migration once:

```sql
-- 004_priorities_dream_fields.sql
alter table marcus_priorities add column if not exists source text not null default 'manual';
  -- 'brain'   = written by the nightly dreaming phase
  -- 'manual'  = committed by Jake on a call / by hand
  -- (never write 'clickup' here; the dashboard merges those live)

alter table marcus_priorities add column if not exists due timestamptz;
  -- hard deadline if one exists; null is fine

alter table marcus_priorities add column if not exists url text;
  -- deep link the priority opens to (ClickUp task, doc, etc.)

alter table marcus_priorities add column if not exists clickup_task_id text;
  -- set when this priority corresponds to a ClickUp task, so the live
  -- ClickUp merge de-dupes against it

alter table marcus_priorities add column if not exists rationale text;
  -- one short line: WHY this is a priority now. shown under the item.

alter table marcus_priorities add column if not exists owner text;
  -- optional, e.g. 'Jake', 'Mark'. shown as a small chip.

create index if not exists marcus_priorities_source_status_idx
  on marcus_priorities (source, status, committed_at desc);
```

### Field contract (what the dashboard reads per row)

| Column            | Type        | Required | Notes |
|-------------------|-------------|----------|-------|
| `content`         | text        | yes      | The priority statement. Plain, imperative, one line. e.g. "Send Atomic Stays deposit invoice." Falls back to `text`/`title` if `content` is null, but write `content`. |
| `scope`           | text        | yes      | One of `day`, `week`, `month`, `quarter`, `ongoing`. Used to bucket undated items. See mapping below. |
| `status`          | text        | yes      | `active` for live priorities. `done` for recently completed (still shown under "Recently Done"). `dropped`/`superseded` are hidden. |
| `source`          | text        | yes      | `brain` for dream output. |
| `due`             | timestamptz | no       | Hard deadline. Drives bucketing and the due/overdue chip. |
| `url`             | text        | no       | Link the item opens to. |
| `clickup_task_id` | text        | no       | Set if this maps to a ClickUp task (enables live de-dupe). |
| `rationale`       | text        | no       | One short line of why-now. Strongly recommended. |
| `owner`           | text        | no       | Optional chip. |
| `committed_at`    | timestamptz | yes      | Set to the dream run time. The dashboard uses the newest `committed_at` among `source='brain'` rows as "last dreamed" in the banner. |
| `completed_at`    | timestamptz | no       | Set when `status='done'`. |

### How the dashboard buckets each row

The dashboard puts each item in one of four buckets, top to bottom:

- **Now / Overdue** — `due` is overdue or due today; or undated and `scope='day'`.
- **This Week** — `due` within the next 7 days; or undated and `scope='week'`.
- **Upcoming** — `due` later than 7 days; or undated `month`/`quarter`/`ongoing`.
- **Recently Done** — `status='done'` or `completed_at` set.

So the lever you control is `due` first, `scope` second. If something must happen now but has no calendar deadline, give it `scope='day'`. If it's a this-week push, `scope='week'`.

Within a bucket the dashboard sorts by soonest `due`, then `brain` rows ahead of raw ClickUp on ties.

---

## The nightly dreaming routine

Each night, in this order:

1. **Gather.** Pull the candidate set of "what has to get done":
   - ClickUp: open tasks assigned to Jake, with due dates and lists.
   - gBrain: commitments, promises, follow-ups, and deadlines surfaced from recent Gmail / Slack / Granola / calendar ingestion (your normal dreaming inputs). Anything Jake said he'd do, anyone waiting on him, anything time-boxed.
   - Calendar: upcoming hard dates (closings, client calls, filing dates).
   - Active client and project state from the brain (e.g. Atomic Stays closing, KBR/Waypoint SOW, Lead Forge deploys).

2. **Reason and rank.** Collapse duplicates across sources, drop noise, and rank by what actually has to move. This is the dreaming judgement: a ClickUp task with no real consequence ranks below an unticketed promise to a closing client. Keep the active list tight (aim for the 10-20 that matter, not every open ticket).

3. **Write rationale.** For each kept priority, one short line of why it's on the list now: the deadline, who's blocked, the dollar consequence. Plain words. No hype. (Honor the brand voice rules: no em dashes, no "not X it's Y", no clichés.)

4. **Cite ClickUp when applicable.** If a priority is a ClickUp task, set `clickup_task_id` and `url` to that task so the live merge de-dupes. If it has no ticket, leave them null. Consider creating the ticket in ClickUp if it should be tracked there, then cite it.

5. **Replace last night's dream (idempotency).** Do not append a new pile every night. Before inserting, mark the prior dream stale:

   ```sql
   update marcus_priorities
     set status = 'superseded'
     where source = 'brain' and status = 'active';
   ```

   Then insert tonight's ranked rows with `source='brain'`, `status='active'`, `committed_at = now()`. Leave `source='manual'` rows untouched: those are Jake's own commitments and you don't own them.

   - If a priority carries over night to night, you can re-insert it fresh (simplest), or match on `clickup_task_id`/`content` and keep the existing row. Re-inserting fresh is fine; just supersede the old one so there's one active row per priority.

6. **Mark completions.** If a cited ClickUp task closed, or a tracked commitment is clearly satisfied in the brain, write that row as `status='done'`, `completed_at=now()` instead of superseding it. It shows under "Recently Done" for the day, then ages out on the next dream.

### Optional but recommended: leave a reasoning artifact in the brain

Also write one gBrain page per dream so there's an audit trail and Marcus can recall your reasoning:

- Slug: `priorities-now` (overwrite each night)
- Tag: `priorities`
- Body: the ranked list with the rationale for each, plus what you dropped and why.

The dashboard does not read this page; the Supabase rows are the contract. The page is for traceability.

---

## Worked example

A dream produces this priority. The row you insert:

```sql
insert into marcus_priorities
  (content, scope, status, source, due, url, clickup_task_id, rationale, owner, committed_at)
values
  ('Send Atomic Stays deposit invoice',
   'day', 'active', 'brain',
   '2026-06-01T23:00:00Z',
   'https://app.clickup.com/t/abc123',
   'abc123',
   'Closing July 1, $1K deposit gates kickoff. Kyle expects it today.',
   'Jake',
   now());
```

On the dashboard this lands in **Now / Overdue**, shows the `brain` badge, a `due today` chip, the rationale line, and clicking the title opens the ClickUp task. Because `clickup_task_id` is set, the live ClickUp merge will not show it a second time.

---

## Done when

- Migration `004_priorities_dream_fields.sql` is applied.
- The nightly dreaming job writes `source='brain'` rows each night and supersedes the prior night's.
- Open dashboard.therereset.com -> Priority view. You see the ranked list bucketed Now / This Week / Upcoming, brain items with rationale, live ClickUp tasks merged in, and the banner reads "dreamed <time> ago · ClickUp live".

Questions on the merge or bucketing: read `app.get('/api/priorities')` in `marcus-agent/v2/dashboard/server.js`. That is the single source of truth for how your rows get displayed.
