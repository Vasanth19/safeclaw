#!/bin/bash
# Slack message backfill to postgres-obs
# Fetches 30 days of Slack history and inserts as observations

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

# Load environment
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env not found at $ENV_FILE"
    exit 1
fi
source "$ENV_FILE"

# Config
BACKFILL_DAYS=30
RATE_LIMIT_DELAY=1.2
DATA_DIR="$PROJECT_DIR/data"
WATERMARKS_FILE="$DATA_DIR/slack_watermarks.json"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_err() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Ensure data dir exists
mkdir -p "$DATA_DIR"

log_info "SafeClaw Slack Backfill: Starting"
log_info "Channels to backfill: $SLACK_INGEST_CHANNELS"

# Parse channel IDs
IFS=',' read -ra CHANNEL_ARRAY <<<"$SLACK_INGEST_CHANNELS"

# Get current Unix timestamp (30 days ago)
if command -v date &> /dev/null; then
    if date --version 2>/dev/null | grep -q GNU; then
        # GNU date (Linux)
        OLDEST_TS=$(date -d "30 days ago" +%s)
    else
        # BSD date (macOS)
        OLDEST_TS=$(date -v-30d +%s)
    fi
else
    log_err "date command not available"
    exit 1
fi

log_info "Oldest timestamp: $OLDEST_TS ($(date -d @$OLDEST_TS 2>/dev/null || date -r $OLDEST_TS 2>/dev/null))"

# Load or create watermarks
if [ -f "$WATERMARKS_FILE" ]; then
    log_info "Loading existing watermarks from $WATERMARKS_FILE"
    WATERMARKS=$(cat "$WATERMARKS_FILE")
else
    log_info "No existing watermarks, starting fresh"
    WATERMARKS='{}'
fi

# User ID → display name cache (resolved on demand via users.info)
declare -A USER_CACHE

resolve_user() {
    local uid="$1"
    [ -z "$uid" ] || [ "$uid" = "unknown" ] && { echo "unknown"; return; }
    if [ -n "${USER_CACHE[$uid]+x}" ]; then
        echo "${USER_CACHE[$uid]}"
        return
    fi
    local name
    name=$(curl -s -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
        "https://slack.com/api/users.info?user=$uid" \
        | jq -r '.user.profile.display_name // .user.profile.real_name // .user.name // empty')
    [ -z "$name" ] && name="$uid"
    USER_CACHE[$uid]="$name"
    sleep 0.3   # gentle on Tier 4 rate limit
    echo "$name"
}

# Replace all <@Uxxx> mentions in a string with @display-name
resolve_mentions() {
    local text="$1"
    # Extract every Uxxx referenced
    local uids
    uids=$(echo "$text" | grep -oE '<@U[A-Z0-9]+>' | sort -u | sed 's/[<>@]//g')
    for uid in $uids; do
        local name
        name=$(resolve_user "$uid")
        text=${text//<@$uid>/@$name}
    done
    echo "$text"
}

# Process each channel
TOTAL_INSERTED=0

for CHANNEL_ID in "${CHANNEL_ARRAY[@]}"; do
    CHANNEL_ID=$(echo "$CHANNEL_ID" | xargs)  # trim whitespace

    # Get channel name
    CHANNEL_NAME=$(curl -s -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
        "https://slack.com/api/conversations.info?channel=$CHANNEL_ID" \
        | jq -r '.channel.name // empty')

    if [ -z "$CHANNEL_NAME" ]; then
        log_warn "Could not fetch name for channel $CHANNEL_ID, skipping"
        continue
    fi

    log_info "Processing channel #$CHANNEL_NAME ($CHANNEL_ID)"

    # Determine oldest_ts for this channel
    WATERMARK=$(echo "$WATERMARKS" | jq -r ".[\"$CHANNEL_ID\"] // \"$OLDEST_TS\"")

    log_info "  Resume from timestamp: $WATERMARK"

    # Fetch all messages for this channel with pagination
    CURSOR=""
    INSERTED=0
    MAX_TS=$WATERMARK

    while true; do
        sleep $RATE_LIMIT_DELAY  # Rate limit

        log_info "  Fetching messages (cursor=${CURSOR:0:20}...)"

        # Build query parameters
        QUERY="channel=$CHANNEL_ID&oldest=$WATERMARK&limit=100"
        if [ -n "$CURSOR" ]; then
            QUERY="$QUERY&cursor=$CURSOR"
        fi

        RESPONSE=$(curl -s -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
            "https://slack.com/api/conversations.history?$QUERY")

        # Extract messages
        MESSAGES=$(echo "$RESPONSE" | jq -r '.messages[]')

        if [ -z "$MESSAGES" ]; then
            log_info "  No messages found"
            break
        fi

        # Process each message (skip bot messages)
        while IFS= read -r MSG; do
            TS=$(echo "$MSG" | jq -r '.ts // empty')
            SUBTYPE=$(echo "$MSG" | jq -r '.subtype // empty')
            BOT_ID=$(echo "$MSG" | jq -r '.bot_id // empty')
            USER_ID=$(echo "$MSG" | jq -r '.user // "unknown"')
            USER=$(resolve_user "$USER_ID")
            TEXT_RAW=$(echo "$MSG" | jq -r '.text // ""')
            TEXT=$(resolve_mentions "$TEXT_RAW")
            FILES=$(echo "$MSG" | jq -r '.files // []')

            # Skip bot messages
            if [ "$SUBTYPE" = "bot_message" ] || [ -n "$BOT_ID" ]; then
                continue
            fi

            if [ -z "$TS" ]; then
                continue
            fi

            # Update max_ts
            if (( $(echo "$TS > $MAX_TS" | bc -l) )); then
                MAX_TS=$TS
            fi

            # Prepare summary (first 300 chars)
            SUMMARY=$(echo "$TEXT" | cut -c1-300)
            [ -z "$SUMMARY" ] && SUMMARY="(no text)"

            # Prepare attachments JSON
            ATTACHMENTS=$(echo "$FILES" | jq -c 'map({filename: .name, size: .size, mimetype: .mimetype, url_private_download: .url_private_download, url_private: .url_private})')

            # Convert TS to ISO-8601 timestamp
            RECEIVED_AT=$(printf '%.0f' "$TS" | xargs -I {} date -u -d @{} +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || printf '%.0f' "$TS" | xargs -I {} date -u -r {} +%Y-%m-%dT%H:%M:%SZ)

            # Insert into database
            docker compose exec -T postgres-obs psql -U obs_user -d safeclaw_obs <<EOSQL
INSERT INTO observations (inbox, message_id, received_at, sender, subject, summary, raw_tags, source)
VALUES (
    'slack/$CHANNEL_NAME',
    '$TS',
    '$RECEIVED_AT'::timestamptz,
    '$USER',
    'Slack #$CHANNEL_NAME',
    '$SUMMARY',
    '$ATTACHMENTS',
    'slack'
)
ON CONFLICT (message_id) DO NOTHING;
EOSQL

            ((INSERTED++))
        done <<< "$(echo "$MESSAGES" | jq -c '.')"

        # Check for pagination
        CURSOR=$(echo "$RESPONSE" | jq -r '.response_metadata.next_cursor // empty')
        if [ -z "$CURSOR" ]; then
            break
        fi
    done

    log_info "  Inserted $INSERTED messages from #$CHANNEL_NAME"
    ((TOTAL_INSERTED += INSERTED))

    # Update watermark
    WATERMARKS=$(echo "$WATERMARKS" | jq ".\"$CHANNEL_ID\" = \"$MAX_TS\"")
done

# Save watermarks
echo "$WATERMARKS" | jq '.' > "$WATERMARKS_FILE"
log_info "Saved watermarks to $WATERMARKS_FILE"

log_info "Backfill complete! Total inserted: $TOTAL_INSERTED"
