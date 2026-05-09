-- SafeClaw: Gmail Signals Table
-- Lightweight signal log for classified Gmail messages (LOG tier)
-- Does NOT ingest messages into the brain; for tracking/reporting only
-- Idempotent: safe to re-run

CREATE TABLE IF NOT EXISTS gmail_signals (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id    TEXT NOT NULL UNIQUE,
  thread_id     TEXT NOT NULL,
  inbox         TEXT NOT NULL,           -- e.g. 'personal', 'hyphenlabs', 'growth'
  received_at   TIMESTAMPTZ NOT NULL,
  sender        TEXT,
  sender_email  TEXT,
  subject       TEXT,
  preview       TEXT,                    -- first 300 chars
  gmail_labels  TEXT[],                  -- raw label IDs for later filtering
  filter_reason TEXT,                    -- why it landed here ('CATEGORY_UPDATES', etc.)
  processed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gmail_signals_inbox_received ON gmail_signals(inbox, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_gmail_signals_sender_email ON gmail_signals(sender_email);
CREATE INDEX IF NOT EXISTS idx_gmail_signals_filter_reason ON gmail_signals(filter_reason);
