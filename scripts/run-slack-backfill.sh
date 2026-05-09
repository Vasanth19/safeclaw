#!/bin/bash
# Wrapper to run slack-backfill.py inside the hermes-reader container

set -e

echo "SafeClaw Slack Backfill — Starting"
echo "Channels: $SLACK_INGEST_CHANNELS"

# Build database URL
if [ -z "$DATABASE_URL" ]; then
    DATABASE_URL="postgresql://${POSTGRES_OBS_USER}:${POSTGRES_OBS_PASSWORD}@postgres-obs:5432/${POSTGRES_OBS_DB}"
fi

# Run the backfill
python3 /workspace/scripts/slack-backfill.py

echo "Backfill complete!"
