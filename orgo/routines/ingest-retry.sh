#!/usr/bin/env bash
# Retry wrapper around email-ingest.sh: transient MCP cold-starts make the agent
# abort with INGEST ERROR before tools finish registering. Re-run until a clean
# INGEST RESULT lands (or attempts exhaust).
#   usage: ingest-retry.sh [WINDOW] [MAXTURNS] [ATTEMPTS]
S=/root/.hermes/profiles/actor/scripts/email-ingest.sh
WINDOW="${1:-30d}"; MAXTURNS="${2:-200}"; ATTEMPTS="${3:-4}"
for try in $(seq 1 "$ATTEMPTS"); do
  echo "=== attempt $try ($WINDOW, $MAXTURNS turns) ==="
  bash "$S" "$WINDOW" "$MAXTURNS" > /tmp/ingest.log 2>&1
  if grep -q "INGEST RESULT:" /tmp/ingest.log && ! tail -2 /tmp/ingest.log | grep -q "INGEST ERROR"; then
    echo "OK on attempt $try: $(grep -o 'INGEST RESULT:.*' /tmp/ingest.log | tail -1)"
    exit 0
  fi
  echo "attempt $try did not complete cleanly; retrying"
  sleep 15
done
echo "exhausted $ATTEMPTS attempts"
exit 1
