#!/bin/bash
# Gmail message backfill to postgres-obs
# Fetches Gmail history and classifies into INGEST (brain) / LOG (signals) / DROP buckets
# Requires Composio Reader MCP URL and Gmail account connected

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

# Defaults
INBOX="personal"
DAYS=90
LIMIT=""
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --inbox)
            INBOX="$2"
            shift 2
            ;;
        --days)
            DAYS="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate inbox and map to Composio connected account UUID
case "$INBOX" in
    personal)
        COMPOSIO_ACCOUNT_UUID="7315a365-2bc0-4529-b343-fe8596c6c6b8"
        ;;
    hyphenlabs)
        COMPOSIO_ACCOUNT_UUID="e0c09e13-4929-4189-9c58-c5caebc61aaa"
        ;;
    growth)
        COMPOSIO_ACCOUNT_UUID="e5554c56-79d6-422f-8107-502d58a1148f"
        ;;
    *)
        echo "ERROR: invalid inbox '$INBOX'. Must be one of: personal, hyphenlabs, growth"
        exit 1
        ;;
esac

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_err() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

# Setup
DATA_DIR="$PROJECT_DIR/data"
WATERMARKS_FILE="$DATA_DIR/gmail_watermarks.json"
mkdir -p "$DATA_DIR"

if [ "$DRY_RUN" = true ]; then
    log_info "DRY RUN MODE: classifications will be printed but not written to DB"
fi

log_info "SafeClaw Gmail Bootstrap: Starting"
log_info "Inbox: $INBOX | Days: $DAYS | API: Composio MCP"

# Calculate cutoff date
if date --version 2>/dev/null | grep -q GNU; then
    # GNU date (Linux)
    CUTOFF_DATE=$(date -d "$DAYS days ago" +%Y/%m/%d)
else
    # BSD date (macOS)
    CUTOFF_DATE=$(date -v-${DAYS}d +%Y/%m/%d)
fi

log_info "Fetching emails after: $CUTOFF_DATE"

# Load or initialize watermarks
if [ -f "$WATERMARKS_FILE" ]; then
    log_info "Loading existing watermarks from $WATERMARKS_FILE"
    WATERMARKS=$(cat "$WATERMARKS_FILE")
else
    log_info "No existing watermarks; starting fresh"
    WATERMARKS='{}'
fi

# Load previous watermark for this inbox (if any)
PREVIOUS_WATERMARK=$(echo "$WATERMARKS" | jq -r ".\"$INBOX\" // empty")
if [ -n "$PREVIOUS_WATERMARK" ]; then
    log_info "Resume from previous watermark: $PREVIOUS_WATERMARK"
fi

# Build Gmail query: filter by date and skip previously seen
GMAIL_QUERY="after:$CUTOFF_DATE"
if [ -n "$PREVIOUS_WATERMARK" ]; then
    GMAIL_QUERY="$GMAIL_QUERY newer_than:${PREVIOUS_WATERMARK}d"
fi

log_info "Gmail query: $GMAIL_QUERY"

# Load brain people (for INGEST classification)
BRAIN_PEOPLE_FILE="/opt/brain/People" # container path
if [ ! -d "$BRAIN_PEOPLE_FILE" ]; then
    BRAIN_PEOPLE_FILE="$PROJECT_DIR/brain/People" # fallback to host path
fi

log_info "Loading brain people from: $BRAIN_PEOPLE_FILE"

# Export environment variables so they're available to Python
export INBOX DAYS LIMIT DRY_RUN COMPOSIO_API_KEY COMPOSIO_READER_MCP_URL COMPOSIO_ACCOUNT_UUID GMAIL_QUERY BRAIN_PEOPLE_FILE WATERMARKS_FILE PROJECT_DIR POSTGRES_OBS_USER POSTGRES_OBS_PASSWORD POSTGRES_OBS_DB

# Fetch all messages and classify them via Python
python3 <<'PYEOF'
import json
import os
import sys
import re
import html
from datetime import datetime, timedelta
from pathlib import Path
import urllib.request
import urllib.error

# Config from bash
inbox = os.environ.get('INBOX', 'personal')
composio_api_key = os.environ.get('COMPOSIO_API_KEY', '')
composio_reader_mcp_url = os.environ.get('COMPOSIO_READER_MCP_URL', '')
composio_account_uuid = os.environ.get('COMPOSIO_ACCOUNT_UUID', '')
gmail_query = os.environ.get('GMAIL_QUERY', '')
limit = os.environ.get('LIMIT', '')
dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
brain_people_file = os.environ.get('BRAIN_PEOPLE_FILE', '')
watermarks_file = os.environ.get('WATERMARKS_FILE', '')
project_dir = os.environ.get('PROJECT_DIR', '')
days = int(os.environ.get('DAYS', 90))

# Validate inputs
if not composio_api_key:
    print(f"[ERROR] COMPOSIO_API_KEY not set")
    sys.exit(1)
if not composio_reader_mcp_url:
    print(f"[ERROR] COMPOSIO_READER_MCP_URL not set")
    sys.exit(1)
if not composio_account_uuid:
    print(f"[ERROR] COMPOSIO_ACCOUNT_UUID not determined for inbox '{inbox}'")
    sys.exit(1)

# Build MCP URL with account selection
mcp_url = f"{composio_reader_mcp_url}&connected_account_id={composio_account_uuid}"
print(f"[DEBUG] MCP URL: {mcp_url[:100]}...")

# Load brain people emails
brain_people_emails = set()
if os.path.isdir(brain_people_file):
    for f in os.listdir(brain_people_file):
        if f.endswith('.md'):
            # Convert filename 'name-at-domain-com.md' -> 'name@domain.com'
            slug = f.replace('.md', '')
            email = slug.replace('-at-', '@').replace('-', '.')
            brain_people_emails.add(email.lower())

print(f"[INFO] Loaded {len(brain_people_emails)} brain people: {', '.join(sorted(brain_people_emails)[:3])}...")

# Classification function
def classify(msg, replied_thread_ids, brain_people_emails):
    """Classify a Gmail message into INGEST | LOG | DROP"""
    labels = msg.get('labelIds', [])
    subject = msg.get('subject', '') or ''
    sender = msg.get('sender', '') or ''
    thread_id = msg.get('threadId', '')

    # Extract email from sender header
    sender_email = ''
    match = re.search(r'<([^>]+)>', sender)
    if match:
        sender_email = match.group(1).lower()
    elif '@' in sender:
        sender_email = sender.split()[-1].lower()

    # ────────── VIP allowlist (mitigation #1) ──────────
    # Comma-separated emails or *@domain wildcards in env GMAIL_VIP_SENDERS.
    # Always INGEST regardless of category. Bypasses all DROP rules below.
    vip_raw = os.environ.get('GMAIL_VIP_SENDERS', '') or ''
    vip_list = [v.strip().lower() for v in vip_raw.split(',') if v.strip()]
    if sender_email:
        for v in vip_list:
            if v.startswith('*@'):
                if sender_email.endswith(v[1:]):
                    return ('INGEST', 'VIP_DOMAIN')
            elif sender_email == v:
                return ('INGEST', 'VIP_SENDER')

    # ────────── Urgent subject patterns (mitigation #2) ──────────
    # Promote LOG/DROP candidates to INGEST when subject signals urgency.
    # Catches bank fraud alerts, account-action emails, etc. that Gmail
    # sometimes mis-labels as Updates or Promotions.
    urgent_pattern = r'\b(fraud|unauthorized|urgent|verify|action required|action needed|expires|expired|password|2fa|security alert|suspicious)\b'
    if re.search(urgent_pattern, subject, re.IGNORECASE):
        return ('INGEST', 'URGENT_SUBJECT')

    # Tier 1: HARD DROPS — Promotions and Forums only
    if 'CATEGORY_PROMOTIONS' in labels:
        return ('DROP', 'CATEGORY_PROMOTIONS')
    if 'CATEGORY_FORUMS' in labels:
        return ('DROP', 'CATEGORY_FORUMS')

    # Tier 1b: SOCIAL → LOG (mitigation #3)
    # LinkedIn InMail, etc. land here. Keep queryable in gmail_signals
    # rather than dropping — small but real risk of recruiter signal.
    if 'CATEGORY_SOCIAL' in labels:
        return ('LOG', 'CATEGORY_SOCIAL')

    # Tier 2: STRONG SIGNAL (INGEST regardless)
    if 'IMPORTANT' in labels:
        return ('INGEST', 'IMPORTANT')
    if 'STARRED' in labels:
        return ('INGEST', 'STARRED')
    if thread_id in replied_thread_ids:
        return ('INGEST', 'REPLIED_THREAD')
    if sender_email and sender_email in brain_people_emails:
        return ('INGEST', 'BRAIN_PERSON')

    # Tier 3: PERSONAL category
    if 'CATEGORY_PERSONAL' in labels:
        return ('INGEST', 'CATEGORY_PERSONAL')

    # Tier 4: Subject transactional patterns
    transact_pattern = r'\b(receipt|invoice|order|shipped|payment|refund|contract|signed|billing|transaction|charged|renewal|subscription)\b'
    if re.search(transact_pattern, subject, re.IGNORECASE):
        return ('INGEST', 'TRANSACTIONAL_SUBJECT')

    # Tier 5: UPDATES → LOG only
    if 'CATEGORY_UPDATES' in labels:
        return ('LOG', 'CATEGORY_UPDATES')

    # Default: uncategorized
    return ('INGEST', 'UNCATEGORIZED')

def parse_sse_payload(raw):
    """Parse Server-Sent Events response from Composio MCP"""
    events = []
    current_data = []

    for line in raw.replace("\r\n", "\n").split("\n"):
        if line == "":
            # Blank line ends an event
            if current_data:
                events.append("\n".join(current_data))
                current_data = []
            continue
        if line.startswith("data:"):
            current_data.append(line[len("data:"):].lstrip())

    if current_data:
        events.append("\n".join(current_data))

    last_data_json = {}
    for body in events:
        body = body.strip()
        if not body or body == "[DONE]":
            continue
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                last_data_json = parsed
        except json.JSONDecodeError:
            continue

    return last_data_json

def unwrap_mcp_result(result):
    """Unwrap Composio MCP result wrapper.

    The MCP server may wrap the actual tool result in a content array.
    If the result has content[0].text that's a JSON string, parse it.
    """
    if isinstance(result, dict):
        # Check if this is a content-wrapped response
        content = result.get('content', [])
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get('text', '')
                if text and isinstance(text, str):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        pass
    return result

def call_mcp_tool(tool_name, arguments):
    """Call a Composio MCP tool via JSON-RPC"""
    rpc_id = 1
    body = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(mcp_url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("User-Agent", "safeclaw-gmail-bootstrap/1.0")
    req.add_header("x-api-key", composio_api_key)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                raise Exception(f"Empty response from MCP")

            # Try JSON first, fall back to SSE
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = parse_sse_payload(raw)

            if "error" in result and result["error"]:
                raise Exception(f"MCP error: {result['error']}")

            # Unwrap result if needed
            wrapped = result.get("result", result)
            unwrapped = unwrap_mcp_result(wrapped)
            return unwrapped or {}
    except urllib.error.HTTPError as e:
        print(f"[ERROR] HTTP {e.code}: {e.reason}")
        err_resp = e.read().decode('utf-8')
        print(f"[DEBUG] Response: {err_resp[:500]}")
        raise
    except Exception as e:
        print(f"[ERROR] MCP call failed: {e}")
        raise

# Fetch replied thread IDs (one call: from:me)
print("[INFO] Fetching user's own messages to detect replied threads...")
replied_thread_ids = set()

try:
    payload = call_mcp_tool("GMAIL_FETCH_EMAILS", {
        "query": "from:me",
        "max_results": 50,
        "include_payload": True,
    })

    for msg in payload.get('data', {}).get('messages', []):
        thread_id = msg.get('threadId')
        if thread_id:
            replied_thread_ids.add(thread_id)

    print(f"[INFO] Found {len(replied_thread_ids)} threads with user replies")
except Exception as e:
    print(f"[WARN] Could not fetch replied threads: {e}")
    replied_thread_ids = set()

# Main fetch loop with pagination
print(f"[INFO] Fetching emails from inbox '{inbox}' with query: {gmail_query}")

all_messages = []
page_token = None
call_count = 0
max_results = 20

while True:
    try:
        import time

        payload = {
            "query": gmail_query,
            "max_results": max_results,
            "include_payload": True,
        }

        if page_token:
            payload["page_token"] = page_token

        print(f"[DEBUG] Composio call #{call_count + 1} (page_token={page_token[:20] if page_token else 'None'}...)")

        data = call_mcp_tool("GMAIL_FETCH_EMAILS", payload)
        print(f"[DEBUG] MCP response keys: {list(data.keys())}")
        messages = data.get('data', {}).get('messages', [])
        if not messages:
            print(f"[DEBUG] Full response: {json.dumps(data, indent=2)[:500]}")

        if not messages:
            print(f"[INFO] No messages in this batch; stopping")
            break

        print(f"[DEBUG] Got {len(messages)} messages in this batch")
        all_messages.extend(messages)

        # Check pagination
        page_token = data.get('data', {}).get('nextPageToken')
        if not page_token:
            print(f"[INFO] No more pages; stopping")
            break

        # Apply limit if set
        if limit:
            if len(all_messages) >= int(limit):
                all_messages = all_messages[:int(limit)]
                print(f"[INFO] Reached limit of {limit} messages")
                break

        time.sleep(1.0)  # Rate limit

    except Exception as e:
        print(f"[ERROR] Fetch failed: {e}")
        sys.exit(1)

print(f"[INFO] Fetched {len(all_messages)} total messages")

# Dedup by thread (keep most recent per thread)
threads_seen = {}
deduplicated = []
for msg in sorted(all_messages, key=lambda m: m.get('messageTimestamp', ''), reverse=True):
    thread_id = msg.get('threadId')
    if thread_id not in threads_seen:
        threads_seen[thread_id] = True
        deduplicated.append(msg)

print(f"[INFO] After thread dedup: {len(deduplicated)} unique threads")

# Classify each message
buckets = {'INGEST': [], 'LOG': [], 'DROP': []}
sender_domains = {'INGEST': {}, 'LOG': {}, 'DROP': {}}

for msg in deduplicated:
    msg_id = msg.get('messageId', 'unknown')
    thread_id = msg.get('threadId', 'unknown')
    subject = msg.get('subject', '(no subject)')
    sender = msg.get('sender', '(unknown)')
    preview_raw = msg.get('preview', '(no preview)')
    if isinstance(preview_raw, str):
        preview = preview_raw[:300]
    else:
        preview = str(preview_raw)[:300]
    labels = msg.get('labelIds', [])
    timestamp = msg.get('messageTimestamp', '')

    # Extract email from sender
    sender_email = ''
    match = re.search(r'<([^>]+)>', sender)
    if match:
        sender_email = match.group(1).lower()
    elif '@' in sender:
        parts = sender.split()
        sender_email = parts[-1].lower()

    # Classify
    bucket, reason = classify(msg, replied_thread_ids, brain_people_emails)
    buckets[bucket].append({
        'messageId': msg_id,
        'threadId': thread_id,
        'sender': sender,
        'senderEmail': sender_email,
        'subject': subject,
        'preview': preview,
        'labels': labels,
        'timestamp': timestamp,
        'reason': reason
    })

    # Track sender domain distribution
    if sender_email and '@' in sender_email:
        domain = sender_email.split('@')[1]
        sender_domains[bucket][domain] = sender_domains[bucket].get(domain, 0) + 1

# Print summary
print(f"\n[SUMMARY] Classification Results")
print(f"  INGEST (→ brain): {len(buckets['INGEST'])}")
print(f"  LOG (→ signals):  {len(buckets['LOG'])}")
print(f"  DROP:             {len(buckets['DROP'])}")

print(f"\n[SUMMARY] Top sender domains per bucket:")
for bucket in ['INGEST', 'LOG', 'DROP']:
    if sender_domains[bucket]:
        sorted_domains = sorted(sender_domains[bucket].items(), key=lambda x: x[1], reverse=True)[:10]
        print(f"\n  {bucket}:")
        for domain, count in sorted_domains:
            print(f"    {domain}: {count}")

# Print first 10 INGEST messages for spot-check
print(f"\n[SUMMARY] First 10 INGEST messages for spot-check:")
for i, msg in enumerate(buckets['INGEST'][:10], 1):
    print(f"  {i}. From: {msg['sender']}")
    print(f"     Subject: {msg['subject'][:70]}")
    print(f"     Reason: {msg['reason']}")

# If dry run, stop here
if dry_run:
    print(f"\n[INFO] Dry run complete. No database writes performed.")
    sys.exit(0)

# Database writes via docker exec psql (since container doesn't expose port)
import subprocess

db_user = os.environ.get('POSTGRES_OBS_USER', 'obs_user')
db_name = os.environ.get('POSTGRES_OBS_DB', 'safeclaw_obs')

# Process INGEST bucket
print(f"\n[INFO] Writing INGEST messages to observations table...")
ingest_count = 0
ingest_sql = ""

for msg in buckets['INGEST']:
    msg_id = msg['messageId']
    timestamp = msg['timestamp']
    sender = msg['sender']
    subject = msg['subject']
    preview = msg['preview']

    # Parse timestamp (ISO-8601)
    try:
        received_at = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).isoformat()
    except:
        received_at = datetime.utcnow().isoformat()

    # Create summary from preview (strip HTML if present)
    summary = html.unescape(preview)
    summary = re.sub(r'<[^>]+>', '', summary)  # Remove HTML tags
    summary = summary[:500]  # Limit to 500 chars

    # Escape for SQL
    sender_esc = sender.replace("'", "''")
    subject_esc = subject.replace("'", "''")
    summary_esc = summary.replace("'", "''")

    ingest_sql += f"""
INSERT INTO observations (inbox, message_id, received_at, sender, subject, summary, source)
VALUES ('gmail/{inbox}', '{msg_id}', '{received_at}'::timestamptz, '{sender_esc}', '{subject_esc}', '{summary_esc}', 'gmail')
ON CONFLICT (message_id) DO NOTHING;
"""
    ingest_count += 1

# Process LOG bucket
print(f"[INFO] Writing LOG messages to gmail_signals table...")
log_count = 0
signals_sql = ""

for msg in buckets['LOG']:
    msg_id = msg['messageId']
    thread_id = msg['threadId']
    timestamp = msg['timestamp']
    sender = msg['sender']
    sender_email = msg['senderEmail']
    subject = msg['subject']
    preview = msg['preview']
    labels = msg['labels']
    reason = msg['reason']

    # Parse timestamp
    try:
        received_at = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).isoformat()
    except:
        received_at = datetime.utcnow().isoformat()

    # Escape for SQL
    sender_esc = sender.replace("'", "''")
    sender_email_esc = sender_email.replace("'", "''")
    subject_esc = subject.replace("'", "''")
    preview_esc = preview.replace("'", "''")
    reason_esc = reason.replace("'", "''")

    # Format labels array
    labels_str = "{" + ",".join([f'"{l}"' for l in labels]) + "}"

    signals_sql += f"""
INSERT INTO gmail_signals (message_id, thread_id, inbox, received_at, sender, sender_email, subject, preview, gmail_labels, filter_reason)
VALUES ('{msg_id}', '{thread_id}', '{inbox}', '{received_at}'::timestamptz, '{sender_esc}', '{sender_email_esc}', '{subject_esc}', '{preview_esc}', '{labels_str}'::text[], '{reason_esc}')
ON CONFLICT (message_id) DO NOTHING;
"""
    log_count += 1

# Combine SQL and execute via docker exec
all_sql = ingest_sql + signals_sql

if all_sql:
    try:
        result = subprocess.run(
            ['docker', 'exec', '-i', 'vasanth-safeclaw-postgres-obs', 'psql', '-U', db_user, '-d', db_name],
            input=all_sql.encode('utf-8'),
            capture_output=True,
            timeout=60
        )
        if result.returncode != 0:
            print(f"[WARN] PostgreSQL returned exit code {result.returncode}")
            print(f"[DEBUG] stderr: {result.stderr.decode('utf-8', errors='replace')[:500]}")
        else:
            print(f"[INFO] Wrote {ingest_count} messages to observations")
            print(f"[INFO] Wrote {log_count} messages to gmail_signals")
    except Exception as e:
        print(f"[ERROR] Could not write to database: {e}")
        sys.exit(1)
else:
    print(f"[INFO] No messages to write")

# Update watermarks
if deduplicated:
    latest_timestamp = max(deduplicated, key=lambda m: m.get('messageTimestamp', '')).get('messageTimestamp', '')
    if latest_timestamp:
        watermarks = json.load(open(watermarks_file, 'r')) if os.path.exists(watermarks_file) else {}
        watermarks[inbox] = latest_timestamp
        with open(watermarks_file, 'w') as f:
            json.dump(watermarks, f, indent=2)
        print(f"[INFO] Updated watermark for {inbox}: {latest_timestamp}")

print(f"\n[SUCCESS] Gmail bootstrap complete!")
print(f"  INGEST (brain):  {ingest_count}")
print(f"  LOG (signals):   {log_count}")

PYEOF

exit_code=$?
if [ $exit_code -ne 0 ]; then
    log_err "Python classification failed"
    exit $exit_code
fi

log_info "SafeClaw Gmail Bootstrap: Complete"
