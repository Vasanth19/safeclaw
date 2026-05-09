#!/usr/bin/env python3
"""
Slack message backfill into postgres-obs observations table.

Ingests 30 days of historical messages from each channel in SLACK_INGEST_CHANNELS.
Writes observations to the obs DB and tracks watermarks in data/slack_watermarks.json.

Usage:
    python scripts/slack-backfill.py

Environment:
    SLACK_BOT_TOKEN       — Slack bot token (xoxb-...)
    SLACK_INGEST_CHANNELS — comma-separated channel IDs
    DATABASE_URL          — postgres connection string (or build from POSTGRES_OBS_* env vars)
"""

import os
import json
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import uuid

import psycopg
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────────────────────────────────

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_INGEST_CHANNELS_STR = os.getenv("SLACK_INGEST_CHANNELS", "")
BACKFILL_DAYS = 30
RATE_LIMIT_DELAY_SEC = 1.2  # Tier 3: ~50 req/min = ~1.2 sec between calls
DATA_DIR = Path("/Users/vasanth/vasanth-hq/safeclaw/data")
WATERMARKS_FILE = DATA_DIR / "slack_watermarks.json"
ATTACHMENTS_STAGING = DATA_DIR / "attachments" / "staging"

# Postgres — build DATABASE_URL from env vars if not provided
database_url = os.getenv("DATABASE_URL")
if not database_url:
    postgres_obs_user = os.getenv("POSTGRES_OBS_USER", "obs_user")
    postgres_obs_password = os.getenv("POSTGRES_OBS_PASSWORD")
    postgres_obs_db = os.getenv("POSTGRES_OBS_DB", "safeclaw_obs")
    # For Docker: postgres-obs:5432
    # For local: localhost:5432
    postgres_host = os.getenv("POSTGRES_OBS_HOST", "postgres-obs")
    postgres_port = os.getenv("POSTGRES_OBS_PORT", "5432")

    if not postgres_obs_password:
        logger.error("POSTGRES_OBS_PASSWORD not set and DATABASE_URL not provided")
        sys.exit(1)

    database_url = (
        f"postgresql://{postgres_obs_user}:{postgres_obs_password}"
        f"@{postgres_host}:{postgres_port}/{postgres_obs_db}"
    )

# ────────────────────────────────────────────────────────────────────────────
# Slack Client
# ────────────────────────────────────────────────────────────────────────────

if not SLACK_BOT_TOKEN:
    logger.error("SLACK_BOT_TOKEN not set")
    sys.exit(1)

slack_client = WebClient(token=SLACK_BOT_TOKEN)

# ────────────────────────────────────────────────────────────────────────────
# Watermarks (per-channel timestamps)
# ────────────────────────────────────────────────────────────────────────────

def load_watermarks() -> dict:
    """Load watermarks from disk. Missing channels default to 30 days ago."""
    if WATERMARKS_FILE.exists():
        try:
            return json.loads(WATERMARKS_FILE.read_text())
        except Exception as e:
            logger.warning(f"Could not load watermarks: {e}. Starting fresh.")
    return {}

def save_watermarks(watermarks: dict) -> None:
    """Save watermarks to disk."""
    WATERMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATERMARKS_FILE.write_text(json.dumps(watermarks, indent=2))
    logger.info(f"Saved watermarks to {WATERMARKS_FILE}")

def get_oldest_timestamp() -> str:
    """Get UNIX timestamp for 30 days ago."""
    old_date = datetime.utcnow() - timedelta(days=BACKFILL_DAYS)
    return str(int(old_date.timestamp()))

# ────────────────────────────────────────────────────────────────────────────
# Database Access
# ────────────────────────────────────────────────────────────────────────────

def insert_observation(
    conn,
    inbox: str,
    message_id: str,
    received_at: datetime,
    sender: str,
    subject: str,
    summary: str,
    attachments: list = None,
    source: str = "slack",
) -> Optional[str]:
    """
    Insert an observation row. Return the observation UUID on success or None on duplicate.

    Uses parameterized queries to prevent SQL injection.
    """
    if attachments is None:
        attachments = []

    attachments_json = json.dumps(attachments)

    try:
        with conn.cursor() as cur:
            # Check for duplicate
            cur.execute(
                "SELECT id FROM observations WHERE message_id = %s",
                (message_id,)
            )
            if cur.fetchone():
                logger.debug(f"Observation {message_id} already exists, skipping")
                return None

            # Insert
            cur.execute(
                """
                INSERT INTO observations (
                    inbox, message_id, received_at, sender, subject, summary, raw_tags, source
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    inbox,
                    message_id,
                    received_at,
                    sender,
                    subject,
                    summary,
                    attachments_json,  # Store attachments in raw_tags for now
                    source,
                )
            )
            obs_id = cur.fetchone()[0]
            conn.commit()
            logger.debug(f"Inserted observation {obs_id} for message {message_id}")
            return obs_id
    except psycopg.Error as e:
        logger.error(f"DB error inserting observation: {e}")
        conn.rollback()
        return None

# ────────────────────────────────────────────────────────────────────────────
# Slack Fetching
# ────────────────────────────────────────────────────────────────────────────

def fetch_channel_history(channel_id: str, oldest_ts: str) -> list:
    """
    Fetch all messages in a channel since oldest_ts, handling pagination.

    Returns list of message dicts.
    """
    messages = []
    cursor = None

    while True:
        time.sleep(RATE_LIMIT_DELAY_SEC)  # Throttle to avoid rate limits

        try:
            logger.info(f"Fetching messages from {channel_id} (cursor={'<start>' if cursor is None else cursor[:20]}...)")

            result = slack_client.conversations_history(
                channel=channel_id,
                oldest=oldest_ts,
                limit=100,
                cursor=cursor,
            )

            # Add messages to list
            for msg in result.get("messages", []):
                # Skip bot messages and subtype=bot_message
                if msg.get("subtype") == "bot_message" or msg.get("bot_id"):
                    continue
                messages.append(msg)

            # Check for pagination
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
            break

    logger.info(f"Fetched {len(messages)} human messages from {channel_id}")
    return messages

def process_channel(conn, channel_id: str, channel_name: str, watermarks: dict) -> int:
    """
    Process all new messages in a channel. Return count inserted.

    Updates watermark to the most recent message timestamp.
    """
    # Determine oldest timestamp to fetch
    if channel_id in watermarks:
        oldest_ts = watermarks[channel_id]
        logger.info(f"Resume from watermark {oldest_ts} for {channel_name}")
    else:
        oldest_ts = get_oldest_timestamp()
        logger.info(f"No watermark for {channel_name}, starting from 30 days ago ({oldest_ts})")

    # Fetch messages
    messages = fetch_channel_history(channel_id, oldest_ts)
    if not messages:
        logger.info(f"No new messages in {channel_name}")
        return 0

    # Process each message
    inbox = f"slack/{channel_name}"
    inserted = 0
    max_ts = oldest_ts

    for msg in messages:
        ts = msg.get("ts")
        user = msg.get("user", "unknown")
        text = msg.get("text", "")

        # Track max timestamp
        if ts:
            try:
                if float(ts) > float(max_ts):
                    max_ts = ts
            except (ValueError, TypeError):
                pass

        # Prepare attachment list
        attachments = []
        if "files" in msg:
            for f in msg.get("files", []):
                attachments.append({
                    "filename": f.get("name"),
                    "size": f.get("size"),
                    "mimetype": f.get("mimetype"),
                    "url_private_download": f.get("url_private_download"),
                    "url_private": f.get("url_private"),
                })

        # Insert observation
        obs_id = insert_observation(
            conn,
            inbox=inbox,
            message_id=ts or str(uuid.uuid4()),
            received_at=datetime.fromtimestamp(float(ts)) if ts else datetime.utcnow(),
            sender=user,
            subject=f"Slack #{channel_name}",
            summary=text[:300] if text else "(no text)",
            attachments=attachments,
        )

        if obs_id:
            inserted += 1

            # Download attachments if any
            if attachments:
                download_attachments(channel_id, channel_name, ts, user, msg.get("files", []))

    # Update watermark
    watermarks[channel_id] = max_ts
    save_watermarks(watermarks)

    logger.info(f"Inserted {inserted} new messages from {channel_name}")
    return inserted

def download_attachments(channel_id: str, channel_name: str, msg_ts: str, user: str, files: list):
    """
    Download attachments to staging area. Create sidecar JSON metadata.
    """
    ATTACHMENTS_STAGING.mkdir(parents=True, exist_ok=True)

    # Convert ts (float) to ISO-8601
    try:
        received_at = datetime.fromtimestamp(float(msg_ts)).isoformat() + "Z"
    except (ValueError, TypeError):
        received_at = datetime.utcnow().isoformat() + "Z"

    for file_obj in files:
        filename = file_obj.get("name", "unknown")
        url = file_obj.get("url_private_download") or file_obj.get("url_private")

        if not url:
            logger.warning(f"No download URL for {filename}")
            continue

        # Safe local filename
        safe_name = f"{msg_ts}_{user}_{filename}"
        local_path = ATTACHMENTS_STAGING / safe_name

        # Write sidecar metadata
        metadata = {
            "source": "slack",
            "channel_id": channel_id,
            "channel_name": channel_name,
            "sender": user,
            "message_ts": msg_ts,
            "filename": filename,
            "mimetype": file_obj.get("mimetype"),
            "size": file_obj.get("size"),
            "saved_path": str(local_path),
            "received_at": received_at,
        }

        metadata_path = Path(str(local_path) + ".json")
        metadata_path.write_text(json.dumps(metadata, indent=2))
        logger.info(f"Wrote metadata sidecar to {metadata_path}")

        # NOTE: We do NOT download the actual file bytes here.
        # The actor's pipeline will pull on next sweep.
        # If we wanted to download, we'd do:
        #   response = requests.get(url, headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"})
        #   local_path.write_bytes(response.content)

# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────

def main():
    logger.info("SafeClaw Slack Backfill: Starting")

    # Validate config
    if not SLACK_INGEST_CHANNELS_STR:
        logger.error("SLACK_INGEST_CHANNELS not set or empty")
        sys.exit(1)

    channel_ids = [c.strip() for c in SLACK_INGEST_CHANNELS_STR.split(",") if c.strip()]
    logger.info(f"Will backfill {len(channel_ids)} channels: {channel_ids}")

    # Load watermarks
    watermarks = load_watermarks()

    # Connect to DB
    try:
        conn = psycopg.connect(database_url)
        logger.info("Connected to postgres-obs")
    except psycopg.Error as e:
        logger.error(f"Failed to connect to postgres: {e}")
        sys.exit(1)

    # Process each channel
    total_inserted = 0
    try:
        # First, fetch channel info (names)
        try:
            result = slack_client.conversations_list()
            channels_by_id = {c["id"]: c["name"] for c in result.get("channels", [])}
        except SlackApiError as e:
            logger.error(f"Failed to fetch channel list: {e}")
            channels_by_id = {}

        for channel_id in channel_ids:
            channel_name = channels_by_id.get(channel_id, channel_id)
            inserted = process_channel(conn, channel_id, channel_name, watermarks)
            total_inserted += inserted

    finally:
        conn.close()
        logger.info("Closed DB connection")

    logger.info(f"Backfill complete. Total inserted: {total_inserted}")
    return 0 if total_inserted >= 0 else 1

if __name__ == "__main__":
    sys.exit(main())
