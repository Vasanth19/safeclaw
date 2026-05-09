-- SafeClaw Observations: Add source column for Slack/Gmail/Drive categorization
-- Idempotent: safe to re-run

ALTER TABLE IF EXISTS observations
ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'email';

-- Create index for fast source filtering
CREATE INDEX IF NOT EXISTS idx_observations_source_received
    ON observations (source, received_at DESC);
