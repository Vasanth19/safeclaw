"""SafeClaw Brain — Reflector Service.

Weekly (Monday 06:00 America/Chicago) reads the last 7 days of observations +
review_queue feedback and drafts two kinds of proposals, which go into tables
for human approval:

  1. soul_revisions — proposed markdown patches to user.soul.md
  2. review_queue   — action_type='preference_update' entries with a candidate rule

MVP scope: runs at startup (for immediate visibility) and then sleeps until the
next Monday 06:00 CT, repeating forever. Prompts the configured LLM via the
Anthropic SDK. Failures are logged but do not crash the loop.

Environment:
    DATABASE_URL           postgres connection string for postgres-obs
    HERMES_LLM_API_KEY     Anthropic API key
    HERMES_LLM_BASE_URL    defaults to https://api.anthropic.com
    HERMES_MODEL           e.g. claude-sonnet-4-6
    BRAIN_USER_KEY         e.g. 'primary'
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

try:
    from anthropic import Anthropic  # type: ignore
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore

# ── Config ──────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")
LLM_API_KEY = os.environ.get("HERMES_LLM_API_KEY")
LLM_BASE_URL = os.environ.get("HERMES_LLM_BASE_URL", "https://api.anthropic.com")
MODEL = os.environ.get("HERMES_MODEL", "claude-sonnet-4-6")
USER_KEY = os.environ.get("BRAIN_USER_KEY", "primary")

if not DATABASE_URL:
    print("FATAL: DATABASE_URL environment variable is required", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [reflector] %(levelname)s %(message)s",
)
log = logging.getLogger("reflector")

_shutdown = threading.Event()


def _handle_signal(signum: int, _frame: Any) -> None:
    log.info("received signal %d — will exit after current cycle", signum)
    _shutdown.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ── LLM client ──────────────────────────────────────────────────────────────

def _build_client() -> Any:
    if Anthropic is None:
        log.warning("anthropic SDK not installed — reflector will skip LLM calls")
        return None
    if not LLM_API_KEY or LLM_API_KEY.startswith("__FILL_IN"):
        log.warning("HERMES_LLM_API_KEY not set — reflector will skip LLM calls")
        return None
    return Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


# ── Data gather ─────────────────────────────────────────────────────────────

def gather_window(conn: psycopg.Connection, days: int = 7) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, inbox, received_at, is_critical, category, sender, subject, summary
              FROM observations
             WHERE received_at >= %s
             ORDER BY received_at DESC
             LIMIT 500
            """,
            (cutoff,),
        )
        observations = cur.fetchall()

        cur.execute(
            """
            SELECT id, action_type, approved_at, rejected_at, rejection_reason, proposed_at
              FROM review_queue
             WHERE proposed_at >= %s
             ORDER BY proposed_at DESC
             LIMIT 500
            """,
            (cutoff,),
        )
        reviews = cur.fetchall()

        cur.execute(
            "SELECT version, soul_md FROM user_profile WHERE user_key = %s",
            (USER_KEY,),
        )
        profile = cur.fetchone()

    return {
        "observations": observations,
        "reviews": reviews,
        "profile": profile,
        "window_days": days,
    }


def _serialize_for_prompt(data: dict[str, Any], max_items: int = 40) -> str:
    trimmed = {
        "window_days": data["window_days"],
        "current_soul_version": (data["profile"] or {}).get("version"),
        "current_soul_md": ((data["profile"] or {}).get("soul_md") or "")[:4000],
        "observation_sample": [
            {
                "category": o.get("category"),
                "sender": o.get("sender"),
                "subject": o.get("subject"),
                "summary": o.get("summary"),
                "is_critical": o.get("is_critical"),
            }
            for o in data["observations"][:max_items]
        ],
        "review_sample": [
            {
                "action_type": r.get("action_type"),
                "approved": r.get("approved_at") is not None,
                "rejected": r.get("rejected_at") is not None,
                "rejection_reason": r.get("rejection_reason"),
            }
            for r in data["reviews"][:max_items]
        ],
    }
    return json.dumps(trimmed, default=str, indent=2)


# ── Proposal generation ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are SafeClaw's Reflector.

You read the last 7 days of observations and review_queue feedback for a single user
and propose two things in strict JSON:

  1. "soul_diff_summary": a SHORT (max 5 bullets) plain-text description of what the
     user's Soul profile should change — or null if nothing material should change.

  2. "preference_rules": an array of 0-5 candidate rules extracted from rejections
     and patterns. Each rule is {"rule": "...", "reason": "...", "confidence": 0.0-1.0}.

Be conservative. Only propose a Soul change when evidence across multiple observations
supports it. Only propose preference rules that are clearly actionable for an agent
(e.g. "always use 'Thanks,' not 'Best,' in closing to vendors"). No vague rules.

Return ONLY valid JSON with keys: soul_diff_summary, preference_rules. No prose.
"""


def generate_proposals(client: Any, payload: str) -> dict[str, Any] | None:
    if client is None:
        return None
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
        )
    except Exception as exc:
        log.error("LLM call failed: %s", exc)
        return None

    # Anthropic returns a content list of blocks; we want the first text block.
    text = ""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "") or ""
            break

    text = text.strip()
    if not text:
        log.warning("LLM returned empty text")
        return None

    # Strip Markdown code fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        return json.loads(text)
    except Exception as exc:
        log.error("LLM output not valid JSON (%s): %.200s", exc, text)
        return None


# ── Persist proposals ───────────────────────────────────────────────────────

def persist_proposals(conn: psycopg.Connection, proposals: dict[str, Any]) -> None:
    soul_summary = proposals.get("soul_diff_summary")
    rules = proposals.get("preference_rules") or []

    with conn.cursor() as cur:
        if isinstance(soul_summary, str) and soul_summary.strip():
            cur.execute(
                "SELECT version FROM user_profile WHERE user_key = %s",
                (USER_KEY,),
            )
            row = cur.fetchone()
            current_version = row[0] if row else 0
            cur.execute(
                """
                INSERT INTO soul_revisions
                    (user_key, from_version, to_version, diff_summary)
                VALUES (%s, %s, %s, %s)
                """,
                (USER_KEY, current_version, current_version + 1, soul_summary.strip()),
            )
            log.info("inserted soul_revision draft (v%d -> v%d)", current_version, current_version + 1)

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_text = str(rule.get("rule") or "").strip()
            reason = str(rule.get("reason") or "").strip() or None
            try:
                confidence = float(rule.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            if not rule_text:
                continue
            confidence = max(0.0, min(1.0, confidence))

            payload = {
                "user_key": USER_KEY,
                "rule": rule_text,
                "reason": reason,
                "confidence": confidence,
                "source": "reflector_weekly",
            }
            cur.execute(
                """
                INSERT INTO review_queue (action_type, payload)
                VALUES ('preference_update', %s::jsonb)
                """,
                (json.dumps(payload),),
            )
            log.info("inserted preference_update proposal: %s", rule_text[:80])

    conn.commit()


# ── Cycle + schedule ────────────────────────────────────────────────────────

def run_cycle() -> None:
    client = _build_client()
    try:
        with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
            data = gather_window(conn, days=7)
            log.info(
                "reflection window: %d observations, %d reviews",
                len(data["observations"]),
                len(data["reviews"]),
            )
            payload = _serialize_for_prompt(data)
            proposals = generate_proposals(client, payload)
            if proposals is None:
                log.info("no proposals generated this cycle")
                return
            persist_proposals(conn, proposals)
    except Exception as exc:
        log.error("cycle failed: %s", exc)


def seconds_until_next_monday_06() -> int:
    """Seconds from now until next Monday 06:00 UTC. (Close enough to CT for MVP.)"""
    now = datetime.now(timezone.utc)
    # weekday(): Monday=0 ... Sunday=6
    days_ahead = (0 - now.weekday()) % 7
    target = (now + timedelta(days=days_ahead)).replace(hour=6, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=7)
    return max(60, int((target - now).total_seconds()))


def main() -> int:
    log.info("reflector starting; will run once immediately then weekly (Mon 06:00 UTC)")
    # Run once at boot for MVP visibility.
    run_cycle()

    while not _shutdown.is_set():
        sleep_for = seconds_until_next_monday_06()
        log.info("sleeping %ds until next weekly reflection", sleep_for)
        for _ in range(sleep_for):
            if _shutdown.is_set():
                break
            time.sleep(1)
        if _shutdown.is_set():
            break
        run_cycle()
    log.info("reflector exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
