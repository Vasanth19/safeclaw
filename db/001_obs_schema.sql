-- SafeClaw: Observation Database Schema
-- Database: safeclaw_obs
-- Run as: obs_user (superuser on this DB)
-- Idempotent: safe to re-run; all objects use IF NOT EXISTS.

-- ─── Extensions ──────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─── Tables ───────────────────────────────────────────────────────────────────

-- Raw observations produced by hermes-reader from Gmail / Slack content.
-- One row per email message or Slack event processed.
CREATE TABLE IF NOT EXISTS observations (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    inbox           TEXT        NOT NULL,                     -- e.g. 'jake@rspur.com', 'jake@panhandlehomebuyer.com'
    message_id      TEXT        NOT NULL UNIQUE,             -- Gmail message ID or Slack event ts
    received_at     TIMESTAMPTZ NOT NULL,                    -- original message timestamp
    is_critical     BOOLEAN     NOT NULL DEFAULT FALSE,
    category        TEXT,                                    -- financial | legal | security | people | general
    sender          TEXT,
    subject         TEXT,
    summary         TEXT,
    suggested_action TEXT,
    raw_tags        TEXT,                                    -- XML-tagged raw content stored for audit
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Critical alerts derived from observations where is_critical = true.
-- Tracks whether a human acknowledged the alert in Slack.
CREATE TABLE IF NOT EXISTS critical_alerts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    observation_id  UUID        NOT NULL REFERENCES observations (id) ON DELETE CASCADE,
    alerted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    slack_ts        TEXT,                                    -- Slack message timestamp for thread replies
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ
);

-- Drive change events detected by rclone-sync or the Drive webhook.
CREATE TABLE IF NOT EXISTS drive_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id         TEXT        NOT NULL,
    event_type      TEXT        NOT NULL,                    -- created | modified | moved | deleted
    old_path        TEXT,
    new_path        TEXT,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Human-approval queue for actions proposed by hermes-actor.
-- Actor inserts a row; human approves/rejects via Slack reaction or slash command.
CREATE TABLE IF NOT EXISTS review_queue (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type     TEXT        NOT NULL,                    -- gmail_draft | slack_post | drive_move | task_create
    payload         JSONB       NOT NULL,
    proposed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    rejected_at     TIMESTAMPTZ,
    rejection_reason TEXT,
    CONSTRAINT one_outcome CHECK (
        (approved_at IS NULL OR rejected_at IS NULL)
    )
);

-- Proposed email sends awaiting approval (linked to review_queue).
-- Phase 1: only drafts are created. Phase 4+ allows actual sends.
CREATE TABLE IF NOT EXISTS proposed_send (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    review_queue_id UUID        NOT NULL REFERENCES review_queue (id) ON DELETE CASCADE,
    to_address      TEXT[]      NOT NULL,
    subject         TEXT        NOT NULL,
    body_preview    TEXT,                                    -- first 500 chars, never full body
    draft_id        TEXT,                                    -- Gmail draft ID
    sent_at         TIMESTAMPTZ                              -- NULL until actually sent (Phase 4+)
);

-- Audit log of emails that were auto-sent (Phase 4+ only).
-- Intentionally separate from proposed_send to make accidental sends obvious.
CREATE TABLE IF NOT EXISTS auto_sent (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    proposed_send_id UUID       NOT NULL REFERENCES proposed_send (id),
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    send_result     JSONB
);

-- ─── Indexes ──────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_observations_inbox_received
    ON observations (inbox, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_observations_critical_processed
    ON observations (is_critical, processed_at DESC);

CREATE INDEX IF NOT EXISTS idx_critical_alerts_alerted
    ON critical_alerts (alerted_at DESC);

CREATE INDEX IF NOT EXISTS idx_review_queue_type_proposed
    ON review_queue (action_type, proposed_at DESC);

CREATE INDEX IF NOT EXISTS idx_drive_events_file_id
    ON drive_events (file_id, processed_at DESC);
