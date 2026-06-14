#!/usr/bin/env bash
# Recurring calendar sync: pull a recent window of Google Calendar via Composio,
# write gbrain daily files, then import + embed. Idempotent (day files overwrite,
# import upserts, embed only touches stale pages).
#   usage: calendar-sync.sh [DAYS_BACK]   (default 45)
export GBRAIN_HOME=/opt/brain
export PATH=/usr/local/bin:/tmp/node-v20.18.1-linux-x64/bin:$PATH
WINDOW="${1:-45}"
python3 /opt/brain/scripts/calendar-collect.py "$WINDOW" 2>&1 | tail -1
cd /opt/brain && gbrain import /opt/brain/repo/daily --no-embed 2>&1 | tail -1
gbrain embed --stale 2>&1 | tail -1
echo "CALENDAR SYNC DONE"
