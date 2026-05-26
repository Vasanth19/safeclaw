"""SafeClaw Brain — Reflector Service.

Weekly (Monday 06:00 America/Chicago) the reflector reads recent activity from
the GBrain ``safeclaw-brain`` service plus ``review_queue`` feedback from
``postgres-tasks`` and drafts two kinds of proposals for human approval:

  1. A proposed revision to the pinned ``identity/soul`` GBrain page.
  2. ``review_queue`` entries (action_type='preference_update') with candidate
     rules extracted from rejections + patterns.

Both proposals are *queued* in ``review_queue`` — the reflector never writes the
Soul page directly. A human approves a ``soul_update`` row (via the same Slack
reaction / slash-command flow that handles every other review_queue action),
and only then does the approving step apply the patched body to GBrain via
``put_page(slug="identity/soul")``.

MVP scope: runs at startup (for immediate visibility) and then sleeps until the
next Monday 06:00 CT, repeating forever. Prompts the configured LLM via the
Anthropic SDK. Failures are logged but do not crash the loop.

Environment:
    DATABASE_URL              postgres connection string for postgres-TASKS
                              (review_queue lives here now, not the old obs DB)
    SAFECLAW_BRAIN_HTTP_URL   base URL of the GBrain service, e.g.
                              http://safeclaw-brain:3131 (MCP at /mcp)
    SAFECLAW_BRAIN_ACTOR_TOKEN  read+write bearer token for GBrain
    HERMES_LLM_API_KEY        Anthropic API key
    HERMES_LLM_BASE_URL       defaults to https://api.anthropic.com
    HERMES_MODEL              e.g. claude-sonnet-4-6
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

try:
    from anthropic import Anthropic  # type: ignore
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore

# ── Config ──────────────────────────────────────────────────────────────────

# DATABASE_URL now points at postgres-TASKS (review_queue lives there). The
# reflector no longer touches the old postgres-obs entities/facts/observations
# or user_profile/soul_revisions tables — all brain state is in GBrain.
DATABASE_URL = os.environ.get("DATABASE_URL")
BRAIN_HTTP_URL = os.environ.get("SAFECLAW_BRAIN_HTTP_URL")
BRAIN_TOKEN = os.environ.get("SAFECLAW_BRAIN_ACTOR_TOKEN")
LLM_API_KEY = os.environ.get("HERMES_LLM_API_KEY")
LLM_BASE_URL = os.environ.get("HERMES_LLM_BASE_URL", "https://api.anthropic.com")
MODEL = os.environ.get("HERMES_MODEL", "claude-sonnet-4-6")

SOUL_SLUG = "identity/soul"

if not DATABASE_URL:
    print("FATAL: DATABASE_URL environment variable is required (postgres-tasks)", file=sys.stderr)
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


# ── GBrain HTTP MCP client ────────────────────────────────────────────────────

class GBrainError(RuntimeError):
    pass


class GBrainClient:
    """Authenticated JSON-RPC client for the GBrain HTTP MCP endpoint.

    POSTs ``tools/call`` to ``${base_url}/mcp`` with a static
    ``Authorization: Bearer <token>``. The operation's return value comes back
    JSON-encoded in ``result.content[0].text`` — we unwrap + parse it.
    """

    def __init__(self, base_url: str, token: str):
        self.mcp_url = base_url.rstrip("/") + "/mcp"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "SafeClaw-Reflector/2.0",
        }
        self._rpc_id = 0

    @classmethod
    def from_env(cls) -> "GBrainClient | None":
        """Build from env, or return None (with a warning) when not configured.

        The reflector degrades gracefully without GBrain — it can still mine
        review_queue feedback for preference rules — so a missing brain is a
        warning, not a fatal error.
        """
        if not BRAIN_HTTP_URL:
            log.warning("SAFECLAW_BRAIN_HTTP_URL not set — reflector will skip GBrain reads/writes")
            return None
        if not BRAIN_TOKEN or BRAIN_TOKEN in ("__FILL_IN__", "__GENERATE__", "__MINTED__"):
            log.warning("SAFECLAW_BRAIN_ACTOR_TOKEN not set — reflector will skip GBrain reads/writes")
            return None
        return cls(BRAIN_HTTP_URL, BRAIN_TOKEN)

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.mcp_url, data=data, method="POST")
        for k, v in self.headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            preview = (e.read() or b"").decode("utf-8", errors="replace")[:300]
            raise GBrainError(f"GBrain HTTP {e.code} on {tool_name}: {preview}") from e
        except urllib.error.URLError as e:
            raise GBrainError(f"GBrain request failed for {tool_name}: {e}") from e

        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as e:
            raise GBrainError(f"GBrain returned non-JSON for {tool_name}: {raw[:200]!r}") from e
        if envelope.get("error"):
            raise GBrainError(f"GBrain MCP error for {tool_name}: {envelope['error']}")
        result = envelope.get("result") or {}
        content = result.get("content")
        text = ""
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text", "") or ""
        parsed: Any = None
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
        if result.get("isError"):
            raise GBrainError(f"GBrain tool {tool_name} returned an error: {parsed or text}")
        return parsed

    def get_soul(self) -> str:
        """Return the markdown body of identity/soul, or '' if absent."""
        try:
            page = self.call_tool("get_page", {"slug": SOUL_SLUG})
        except GBrainError as exc:
            log.warning("could not read %s: %s", SOUL_SLUG, exc)
            return ""
        if isinstance(page, dict):
            for key in ("content", "markdown", "body", "text"):
                val = page.get(key)
                if isinstance(val, str) and val.strip():
                    return val
        if isinstance(page, str):
            return page
        return ""

    def list_recent_pages(self, *, days: int, limit: int = 200) -> list[dict[str, Any]]:
        """List pages updated within the window (recent brain activity)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        try:
            pages = self.call_tool(
                "list_pages",
                {"updated_after": cutoff, "sort": "updated_desc", "limit": limit},
            )
        except GBrainError as exc:
            log.warning("list_pages failed: %s", exc)
            return []
        return pages if isinstance(pages, list) else []

    def query(self, text: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Semantic query over the brain for recent salient activity."""
        try:
            results = self.call_tool("query", {"query": text, "limit": limit})
        except GBrainError as exc:
            log.warning("query failed: %s", exc)
            return []
        return results if isinstance(results, list) else []

    def add_timeline_entry(self, *, slug: str, date: str, summary: str, detail: str = "") -> None:
        """Append a timeline entry to a page (best-effort)."""
        try:
            self.call_tool(
                "add_timeline_entry",
                {"slug": slug, "date": date, "summary": summary, "detail": detail, "source": "reflector"},
            )
        except GBrainError as exc:
            log.warning("add_timeline_entry failed for %s: %s", slug, exc)


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

def gather_reviews(conn: psycopg.Connection, days: int) -> list[dict[str, Any]]:
    """Read recent review_queue feedback from postgres-tasks.

    Returns an empty list (with a warning) if the table doesn't exist yet —
    schema init for the tasks DB is owned by other workstreams.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
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
            return cur.fetchall()
    except psycopg.errors.UndefinedTable:
        conn.rollback()
        log.warning("review_queue table not present in tasks DB yet — skipping review feedback")
        return []


def gather_window(conn: psycopg.Connection, brain: GBrainClient | None, days: int = 7) -> dict[str, Any]:
    reviews = gather_reviews(conn, days)

    soul_md = ""
    recent_pages: list[dict[str, Any]] = []
    salient: list[dict[str, Any]] = []
    if brain is not None:
        soul_md = brain.get_soul()
        recent_pages = brain.list_recent_pages(days=days)
        salient = brain.query("recent activity, decisions, and changes this week")

    return {
        "reviews": reviews,
        "soul_md": soul_md,
        "recent_pages": recent_pages,
        "salient": salient,
        "window_days": days,
    }


def _serialize_for_prompt(data: dict[str, Any], max_items: int = 40) -> str:
    trimmed = {
        "window_days": data["window_days"],
        "current_soul_md": (data["soul_md"] or "")[:4000],
        "recent_pages": [
            {
                "slug": p.get("slug"),
                "type": p.get("type"),
                "title": p.get("title"),
                "updated_at": p.get("updated_at"),
            }
            for p in data["recent_pages"][:max_items]
        ],
        "salient_results": [
            {
                "slug": r.get("slug") or r.get("page_slug"),
                "title": r.get("title"),
                "snippet": (r.get("snippet") or r.get("content") or r.get("text") or "")[:300],
            }
            for r in data["salient"][:max_items]
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

You read the last 7 days of brain activity (recent GBrain pages + salient search
results) and review_queue feedback for a single user, plus the user's current
Soul page, and propose two things in strict JSON:

  1. "soul_diff_summary": a SHORT (max 5 bullets) plain-text description of what
     the user's Soul page should change — or null if nothing material should
     change.

  2. "soul_revised_md": the FULL revised markdown body of the Soul page
     (preserving its YAML frontmatter and structure) reflecting the changes in
     soul_diff_summary — or null when soul_diff_summary is null. Keep edits
     minimal and surgical; do not rewrite sections that don't need to change.

  3. "preference_rules": an array of 0-5 candidate rules extracted from
     rejections and patterns. Each rule is
     {"rule": "...", "reason": "...", "confidence": 0.0-1.0}.

Be conservative. Only propose a Soul change when evidence across multiple pages
or reviews supports it. Only propose preference rules that are clearly
actionable for an agent (e.g. "always use 'Thanks,' not 'Best,' in closing to
vendors"). No vague rules.

Return ONLY valid JSON with keys: soul_diff_summary, soul_revised_md,
preference_rules. No prose.
"""


def generate_proposals(client: Any, payload: str) -> dict[str, Any] | None:
    if client is None:
        return None
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
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
    """Queue proposals into review_queue (postgres-tasks) for human approval.

    Nothing is written to GBrain here — the Soul revision is queued as a
    `soul_update` review_queue row carrying the full proposed body. The
    approving step (Slack reaction / slash command, same as every other
    review_queue action) is what applies it to GBrain via put_page.
    """
    soul_summary = proposals.get("soul_diff_summary")
    soul_revised = proposals.get("soul_revised_md")
    rules = proposals.get("preference_rules") or []

    with conn.cursor() as cur:
        if (
            isinstance(soul_summary, str)
            and soul_summary.strip()
            and isinstance(soul_revised, str)
            and soul_revised.strip()
        ):
            payload = {
                "slug": SOUL_SLUG,
                "diff_summary": soul_summary.strip(),
                "revised_md": soul_revised,
                "source": "reflector_weekly",
            }
            cur.execute(
                """
                INSERT INTO review_queue (action_type, payload)
                VALUES ('soul_update', %s::jsonb)
                """,
                (json.dumps(payload),),
            )
            log.info("queued soul_update proposal for %s (%d chars)", SOUL_SLUG, len(soul_revised))
        elif isinstance(soul_summary, str) and soul_summary.strip():
            log.info("soul_diff_summary present but no revised body — skipping soul_update")

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
            log.info("queued preference_update proposal: %s", rule_text[:80])

    conn.commit()


# ── Cycle + schedule ────────────────────────────────────────────────────────

def run_cycle() -> None:
    client = _build_client()
    brain = GBrainClient.from_env()
    try:
        with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
            data = gather_window(conn, brain, days=7)
            log.info(
                "reflection window: %d recent pages, %d salient hits, %d reviews",
                len(data["recent_pages"]),
                len(data["salient"]),
                len(data["reviews"]),
            )
            payload = _serialize_for_prompt(data)
            proposals = generate_proposals(client, payload)
            if proposals is None:
                log.info("no proposals generated this cycle")
                return
            persist_proposals(conn, proposals)

        # Best-effort: leave a breadcrumb on the Soul page timeline so the
        # human can see when the reflector last considered a revision.
        if brain is not None and isinstance(proposals.get("soul_diff_summary"), str):
            summary = proposals["soul_diff_summary"].strip()
            if summary:
                brain.add_timeline_entry(
                    slug=SOUL_SLUG,
                    date=datetime.now(timezone.utc).date().isoformat(),
                    summary="Reflector proposed a Soul revision (pending approval)",
                    detail=summary[:500],
                )
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
