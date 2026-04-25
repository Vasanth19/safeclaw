# SafeClaw Implementation Plan

Five phases from bare metal to full autonomous assistant with auto-send.
Each phase has explicit success criteria and a rollback procedure.

---

## Phase 0 — Foundation (Week 1)

**Goal:** All 7 services healthy, egress rules verified, credentials in place.

### Prerequisites

- OrbStack 1.0+ installed and running (https://orbstack.dev)
- `docker compose` v2 (verify: `docker compose version`)
- Git
- A Google Cloud project with OAuth 2.0 credentials (Client ID + Secret)
- A Slack workspace where you can create apps (workspace admin access)

### Steps

**Step 1: Clone and configure**
```bash
git clone <repo-url>
cd ai-assistant
cp .env.example .env
```
Open `.env` and fill in every variable. See `DEPLOY-RUNBOOK.md §Environment Variables`
for the complete table of required values and how to generate them.

**Step 2: Start the stack**
```bash
docker compose up -d
# Watch startup logs:
docker compose logs -f
```

Wait for all containers to show `healthy` or `running`:
```bash
docker compose ps
```

**Step 3: Apply egress rules (Linux/VPS only)**

On macOS with OrbStack, the egress iptables rules work — OrbStack exposes its Linux VM directly.
Apply them via `orb shell` (or `ssh orb`) then run the iptables commands below.

On Linux:
```bash
# Allow googleapis.com and slack.com; drop all other external egress from safeclaw_net
NETWORK_SUBNET=$(docker network inspect safeclaw_safeclaw_net --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')
iptables -I FORWARD -s "$NETWORK_SUBNET" -d 172.217.0.0/16 -j ACCEPT    # googleapis
iptables -I FORWARD -s "$NETWORK_SUBNET" -d 104.40.0.0/13 -j ACCEPT     # slack
iptables -I FORWARD -s "$NETWORK_SUBNET" -j DROP                         # everything else
```

**Step 4: Run Phase 0 verification**
```bash
bash scripts/verify-stack.sh --phase 0
```

### Success Criteria

- All 5 Phase 0 services running and healthy (postgres-obs, postgres-tasks, postgrest, nango, rclone-sync)
- `verify-stack.sh --phase 0` reports 0 FAIL
- hermes-reader CANNOT reach `https://example.com` (egress test)
- hermes-reader CAN reach `https://www.googleapis.com`

### Rollback

```bash
docker compose down -v   # Removes containers and named volumes (data loss — only for fresh start)
# Or to keep data:
docker compose down      # Stops containers, preserves volumes
```

---

## Phase 1 — Reader Online (Week 2)

**Goal:** Email arrives → observation row in DB → critical alert in Slack.

### Prerequisites

- Phase 0 complete and verified
- Google OAuth credentials configured in `.env`
- Slack app created (bot token + app-level token in `.env`)

### Steps

**Step 1: Run OAuth setup**
```bash
bash scripts/setup-oauth.sh
```
Follow the interactive walkthrough to authorize all 5 connections:
- `jake-rspur` (gmail-readonly + gmail-draft)
- `jake-panhandle` (gmail-readonly + gmail-draft)
- `jake-rockingspur` (gmail-readonly + gmail-draft)
- `jake-drive` (google-drive-file)
- `rspur-slack` (slack-bot)

**Step 2: Run database migrations**
```bash
docker compose exec postgres-obs psql \
  -U "$POSTGRES_OBS_USER" -d safeclaw_obs \
  -f /migrations/001_obs_schema.sql

docker compose exec postgres-tasks psql \
  -U "$POSTGRES_TASKS_USER" -d safeclaw_tasks \
  -f /migrations/002_task_schema.sql
```

**Step 3: Create the #safeclaw-review Slack channel**

In the Rocking Spur Homes Slack workspace:
1. Create channel `#safeclaw-review` (private is fine)
2. Invite the SafeClaw bot: `/invite @SafeClaw`
3. Copy the channel ID (right-click channel → Copy Link → extract the C... ID)
4. Paste the channel ID into `.env` as `SLACK_REVIEW_CHANNEL_ID`
5. Restart hermes-actor: `docker compose restart hermes-actor`

**Step 4: Configure Gmail Pub/Sub push subscriptions**

For each Gmail inbox:
1. Go to Google Cloud Console → Pub/Sub → Create Topic: `safeclaw-gmail-push`
2. Create a Push subscription pointing to your SafeClaw webhook receiver
3. In Gmail API, call `users.watch()` with the topic name
   (hermes-reader's `gmail_rearm` scheduled automation handles renewals after setup)

**Step 5: Run Phase 1 verification**
```bash
bash scripts/verify-stack.sh --phase 1
```
This will prompt you to send a test email and verify the observation row appears.

### Success Criteria

- Sending an email to the primary inbox creates an observation row within 60 seconds
- `is_critical=true` emails trigger a Slack card in `#safeclaw-review`
- Injection email (see verify-stack.sh §Injection test) logs `category=security` but
  produces no outbound email, draft, or external HTTP call

### Rollback

```bash
# Disable hermes-reader if it is causing issues:
docker compose stop hermes-reader
# Investigate logs:
docker compose logs --tail=100 hermes-reader
# Restart after fix:
docker compose start hermes-reader
```

---

## Phase 2 — Actor Online (Week 3)

**Goal:** Full read-write loop with human approval gate in Slack.

### Prerequisites

- Phase 1 complete and verified
- At least 5 observation rows in the obs DB (confirms reader is working)
- Slack bot installed and `#safeclaw-review` channel live

### Steps

**Step 1: Enable hermes-actor**
```bash
# Edit .env: set ACTOR_ENABLED=true
docker compose up -d hermes-actor
docker compose logs -f hermes-actor   # watch startup
```

**Step 2: Complete Slack bot installation**

If not already done in Phase 1:
- Slack App Dashboard → Socket Mode → Enable
- Generate App-Level Token (scope: `connections:write`) → paste as `SLACK_APP_TOKEN` in `.env`
- Restart actor: `docker compose restart hermes-actor`

**Step 3: Test task creation via Slack**
1. In any Slack channel, mention: `@SafeClaw create a task: Follow up on closing docs for 123 Main St`
2. Verify actor posts a proposed action card to `#safeclaw-review`
3. Approve with the checkmark reaction
4. Verify the task row appears in PostgREST:
   ```bash
   curl -H "Authorization: Bearer $TASKS_AGENT_JWT" http://localhost:3001/tasks
   ```

**Step 4: Test Drive file monitor**
1. Upload a test file to the monitored Google Drive folder
2. Wait up to 15 minutes (one rclone cycle)
3. Verify the file appears in `./drive-mirror/`
4. Verify a `drive_events` row appears in the obs DB

**Step 5: Test Gmail draft creation**
1. Trigger actor via Slack: `@SafeClaw please draft a reply to the most recent email observation`
2. Actor posts proposed draft to `#safeclaw-review`
3. Approve the draft
4. Verify a draft (NOT a sent email) appears in Jake's Gmail drafts folder

**Step 6: Run Phase 2 verification**
```bash
bash scripts/verify-stack.sh --phase 2
```

### Success Criteria

- hermes-actor starts and connects to Slack via Socket Mode
- Task creation creates a DB row; `verify-stack.sh --phase 2` reports 0 FAIL on PostgREST auth checks
- Gmail draft appears in Drafts folder after Slack approval — nothing in Sent
- Drive upload triggers a `drive_events` row

### Rollback

```bash
# Disable actor without affecting reader:
# Edit .env: ACTOR_ENABLED=false
docker compose up -d hermes-actor   # restarts with disabled flag, exits cleanly
```

---

## Phase 3 — Proactive Cadence (Week 4)

**Goal:** Daily briefings and reminders firing on schedule.

### Steps

**Step 1: Verify scheduled automations in actor config**

The scheduled automations are defined in `config/actor-hermes.yaml` under the `schedules`
block. Confirm the four schedules are present:
- `morning_briefing`: 7:00 AM CT daily
- `reminder_scan`: 3:00 PM CT daily
- `gmail_rearm`: midnight CT daily
- `critical_digest`: 6:00 PM CT daily

**Step 2: Trigger a manual test run**

Use the Hermes Agent API (if exposed) or restart the actor to force the morning briefing:
```bash
# Check Hermes docs for manual schedule trigger syntax
docker compose exec hermes-actor hermes-agent trigger morning_briefing
```

**Step 3: Verify Slack cards appear**

Each scheduled automation should post a formatted card to `#safeclaw-review`.
Morning briefing format:
- Total new messages per inbox (since midnight)
- Count of critical items
- Top 3 items by urgency
- Tasks due today

### Success Criteria

- Morning briefing card appears in `#safeclaw-review` by 7:15 AM CT on three consecutive days
- Reminder scan posts task reminders for any tasks due that day
- `gmail_rearm` prevents Pub/Sub expiry (verify no "watch expired" errors after Day 7)
- Critical digest posts end-of-day summary

### Rollback

Disable individual schedules in `actor-hermes.yaml` by removing the relevant block,
then `docker compose restart hermes-actor`.

---

## Phase 4 — 30-Day Clean Run + Auto-Send Unlock (Week 8+)

**Goal:** Enable allowlist-scoped auto-send after demonstrated trustworthiness.

### Prerequisites (ALL required — no exceptions)

- 30 rolling days with zero `proposed_send` rejections by Jake
- Zero prompt-injection incidents logged in the `observations` table (`category=security`)
- Client (Jake McKinney) signs off explicitly: written confirmation required
- Security review: run `bash scripts/verify-stack.sh --phase 2` and confirm all PASS
- Review the `auto_sent` and `proposed_send` tables — confirm send volumes are reasonable

**Who does what:**
- Vasanth (developer): runs the 30-day metrics query, prepares the sign-off document
- Jake McKinney (client): reviews the metrics, signs off in writing
- Vasanth: flips the flag after signed approval is on file

### Steps

**Step 1: Generate 30-day metrics report**
```sql
-- Run against safeclaw_obs:
SELECT
  COUNT(*) FILTER (WHERE rejected_at IS NOT NULL) AS rejected_sends,
  COUNT(*) FILTER (WHERE approved_at IS NOT NULL) AS approved_sends,
  COUNT(*) FILTER (WHERE category = 'security')  AS injection_attempts
FROM review_queue
WHERE proposed_at >= now() - interval '30 days';
```

All three counts must be 0 (rejections), N > 0 (approvals), 0 (injections).

**Step 2: Client sign-off**

Share the metrics report with Jake. Get written approval (email or Slack DM on record).

**Step 3: Enable auto-send**
```bash
# Edit .env: AUTO_SEND_ENABLED=true
docker compose restart hermes-actor
docker compose logs -f hermes-actor   # confirm it reads the new flag
```

**Step 4: Monitor closely for first 72 hours**

Check `auto_sent` table every 4 hours for the first three days:
```bash
docker compose exec postgres-obs psql -U "$POSTGRES_OBS_USER" -d safeclaw_obs \
  -c "SELECT * FROM auto_sent ORDER BY sent_at DESC LIMIT 10;"
```

### Success Criteria

- `AUTO_SEND_ENABLED=true` confirmed in actor logs
- First auto-sent email verified as correct (not a test or accidental send)
- Client confirms receipt and approves of the content

### Rollback (IMMEDIATE if anything unexpected is sent)

```bash
# Edit .env: AUTO_SEND_ENABLED=false
docker compose restart hermes-actor
# Immediately notify Jake if any unexpected email was sent
```

---

## Phase 5 — VAS-1 Architecture Write-up

**Goal:** Publish the SafeClaw architecture for the broader AI-safety / personal-AI community.

### Article: "Breaking the lethal trifecta: how we built a personal assistant that can't leak your inbox"

**Outline:**
1. The problem: why LLM personal assistants are inherently risky
2. The lethal trifecta: private data + untrusted input + exfiltration capability
3. SafeClaw's architectural solution: the reader/actor split
4. Credential vault pattern with Nango
5. Network-layer egress vs. prompt-layer egress: why prompts aren't enough
6. The approval gate and the 30-day clean-run prerequisite for auto-send
7. What we'd do differently (lessons learned)

**Target:** Vasanth's technical blog or a relevant publication (HN, LessWrong, substack).

**Who:** Vasanth authors; Jake reviews for any business-sensitive details before publishing.
