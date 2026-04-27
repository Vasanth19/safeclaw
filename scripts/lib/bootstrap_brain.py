"""
SafeClaw — bootstrap_brain.py
=============================

The brain-seeding workhorse. This script is invoked by
``scripts/bootstrap-brain.sh`` inside the ``embedder`` container, which
already has Python 3.12 + psycopg installed.

What it does, end-to-end
------------------------

1. Reads ``BOOTSTRAP_DAYS`` (default 90) from the environment and decides
   how far back in Gmail to scrape.
2. Pages through Gmail history via the **Composio Reader MCP**:

   - ``GMAIL_FETCH_EMAILS`` for inbound + sent mail (we filter sent locally).
   - We deliberately do NOT call any Gmail "send" or "draft" tool — the
     Reader MCP server's allowlist wouldn't expose them anyway, but this
     script also never asks for one.

3. For each unique sender:

   - Slugifies the email address (``alice@acme.com`` -> ``alice-at-acme-com``).
   - Upserts ``brain/People/<slug>.md`` from a small template.
   - Upserts a row into ``postgres-obs.entities`` (kind=``person``).

4. For each unique sender domain:

   - Upserts ``brain/Companies/<domain>.md``.
   - Upserts an ``entities`` row (kind=``company``).

5. For each *sent* message (``q=in:sent``):

   - Inserts a row into ``postgres-obs.style_samples`` so the Actor has voice
     samples from day one. The embedder service will vectorize them on its
     next polling cycle.

6. Writes a human-readable summary report to
   ``brain/2 - Live Logs/bootstrap-<UTC-timestamp>.md``.

7. Tracks a watermark in ``brain/.bootstrap-state.json`` so re-runs only fetch
   messages newer than the last successful run. Use ``--reset`` to start over.

Why MCP and not the Gmail REST API directly
-------------------------------------------

The whole SafeClaw security story rests on never holding OAuth tokens on the
SafeClaw box. Composio holds them. The Reader MCP server in front of those
tokens has a strict toolkit allowlist (read-only), so even this bootstrap
script — which is presumably benign — cannot accidentally send or delete
anything. Belt and suspenders.

CLI
---

::

    python bootstrap_brain.py                 # incremental
    python bootstrap_brain.py --dry-run       # parse + print, no DB writes
    python bootstrap_brain.py --reset         # clear watermark, full rerun
    python bootstrap_brain.py --days 30       # override BOOTSTRAP_DAYS

Attribution
-----------

The brain folder layout this script populates (``People/``, ``Companies/``,
``2 - Live Logs/``, etc.) follows Samin Yasar's **Evolving Brain Template**
(MIT licensed) — https://github.com/Samin12/Evolving-Brain-Template.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# psycopg is bundled in the embedder image (services/embedder/requirements.txt).
import psycopg


# ─── Constants ─────────────────────────────────────────────────────────────

DEFAULT_DAYS = 90

# Page size for GMAIL_FETCH_EMAILS. 100 is the typical Gmail API limit.
PAGE_SIZE = 100

# Hard cap on pages per category to keep runaway runs bounded.
MAX_PAGES_PER_CATEGORY = 200

# Backoff parameters for HTTP retries against the Composio MCP endpoint.
HTTP_MAX_RETRIES = 3
HTTP_BACKOFF_SECONDS = 2.0

# Minimum word count for a body to be worth saving as a style sample.
MIN_STYLE_SAMPLE_WORDS = 8


# ─── Data shapes ───────────────────────────────────────────────────────────


@dataclass
class GmailMessage:
    """A normalized subset of a Gmail message — only the fields we use."""

    message_id: str
    thread_id: str
    sender_email: str
    sender_name: str
    recipient_emails: list[str]
    subject: str
    body_text: str
    received_at: dt.datetime  # UTC
    labels: list[str] = field(default_factory=list)

    @property
    def is_sent(self) -> bool:
        return "SENT" in self.labels


@dataclass
class BootstrapStats:
    emails_processed: int = 0
    sent_processed: int = 0
    people_upserted: int = 0
    companies_upserted: int = 0
    style_samples_saved: int = 0
    contact_frequency: dict[str, int] = field(default_factory=dict)


# ─── Small helpers ─────────────────────────────────────────────────────────


def slugify_email(email: str) -> str:
    """``alice@acme.com`` -> ``alice-at-acme-com``.

    We use ``-at-`` rather than the literal ``@`` so the result is filesystem-
    safe on every platform we care about (Windows in particular is touchy).
    """
    e = email.strip().lower()
    e = re.sub(r"[^a-z0-9._@+-]", "", e)
    return e.replace("@", "-at-").replace(".", "-")


def domain_of(email: str) -> str:
    if "@" not in email:
        return ""
    return email.split("@", 1)[1].strip().lower()


def parse_address_header(header_value: str) -> tuple[str, str]:
    """Split an RFC 2822 ``"Alice <alice@acme.com>"`` header into (name, email).

    Returns ``("", "")`` if no email is found.
    """
    if not header_value:
        return ("", "")
    match = re.search(r"<([^>]+)>", header_value)
    if match:
        email = match.group(1).strip()
        name = header_value.split("<", 1)[0].strip().strip('"')
        return (name, email)
    # Bare address with no display name.
    bare = header_value.strip()
    if "@" in bare:
        return ("", bare)
    return (bare, "")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def epoch_ms_to_utc(ms: int | str | None) -> dt.datetime:
    if ms is None:
        return utcnow()
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc)
    except (TypeError, ValueError):
        return utcnow()


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", name).strip("-") or "unknown"


# ─── Composio MCP HTTP client ──────────────────────────────────────────────


class ComposioMCPError(RuntimeError):
    pass


def _http_post_json(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    """POST a JSON-RPC payload to a Composio MCP URL and parse the response.

    We use ``urllib.request`` so the script has zero external dependencies
    beyond what's already in the embedder image.
    """
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    # Composio MCP servers reject requests that don't accept both JSON and SSE.
    req.add_header("Accept", "application/json, text/event-stream")
    for k, v in headers.items():
        req.add_header(k, v)

    last_err: Exception | None = None
    for attempt in range(1, HTTP_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                content_type = (resp.headers.get("Content-Type") or "").lower()
                raw = resp.read().decode("utf-8")
                # Composio's HTTP/SSE transport may stream a single
                # `data: {...}` line back even when we're not interested in
                # streaming. Handle both content types defensively.
                if "text/event-stream" in content_type:
                    return _parse_sse_payload(raw)
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    # Some responses are SSE-shaped despite a JSON content
                    # type. Fall back to the SSE parser before giving up.
                    if raw.lstrip().startswith("event:") or raw.lstrip().startswith("data:"):
                        return _parse_sse_payload(raw)
                    raise ComposioMCPError(
                        f"Composio MCP returned non-JSON response: {raw[:200]!r}"
                    )
        except urllib.error.HTTPError as e:
            # Don't retry 4xx — those are config bugs, not transient failures.
            if 400 <= e.code < 500:
                body_preview = (e.read() or b"").decode("utf-8", errors="replace")[:300]
                raise ComposioMCPError(
                    f"Composio MCP HTTP {e.code}: {body_preview}"
                ) from e
            last_err = e
        except urllib.error.URLError as e:
            last_err = e
        if attempt < HTTP_MAX_RETRIES:
            time.sleep(HTTP_BACKOFF_SECONDS * attempt)
    raise ComposioMCPError(
        f"Composio MCP request failed after {HTTP_MAX_RETRIES} attempts: {last_err}"
    )


def _parse_sse_payload(raw: str) -> dict[str, Any]:
    """Pull the JSON body out of a Server-Sent-Events response.

    Composio's MCP servers respond with a sequence of ``data: {...}`` lines
    even for one-shot ``tools/call`` requests. We only care about the last
    ``data:`` payload — that's the final result.
    """
    last_data_json: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[len("data:"):].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            last_data_json = parsed
    if not last_data_json:
        raise ComposioMCPError(
            f"Composio MCP returned an SSE response with no parseable data lines: {raw[:200]!r}"
        )
    return last_data_json


class ComposioReader:
    """Tiny client for the Composio Reader MCP server.

    The MCP URL we receive in ``COMPOSIO_READER_MCP_URL`` is a JSON-RPC
    endpoint that already has ``?user_id=...`` baked in. We only need the
    ``tools/call`` method.
    """

    def __init__(self, mcp_url: str, api_key: str, user_id: str | None = None):
        self.mcp_url = mcp_url
        self.headers = {
            "x-api-key": api_key,
            # SafeClaw identifies itself in the User-Agent so Cloudflare's
            # default bot rules don't reject us out of hand.
            "User-Agent": "SafeClaw-Bootstrap/1.0",
        }
        if user_id:
            self.headers["x-composio-user-id"] = user_id
        self._rpc_id = 0

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """JSON-RPC ``tools/call`` against the MCP server."""
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        resp = _http_post_json(self.mcp_url, self.headers, body)
        if "error" in resp and resp["error"]:
            raise ComposioMCPError(
                f"Composio MCP error for tool {tool_name}: {resp['error']}"
            )
        return resp.get("result", {}) or {}

    # ── Higher-level helpers ────────────────────────────────────────────

    def fetch_emails(
        self,
        *,
        query: str,
        page_token: str | None,
        max_results: int,
    ) -> dict[str, Any]:
        """Wraps ``GMAIL_FETCH_EMAILS``.

        We pass through the most useful arguments; Composio normalizes the
        underlying Gmail API parameters. The result is whatever the MCP
        server returns — typically a dict with ``messages`` and
        ``nextPageToken``. We pass through unmodified so callers can deal
        with shape variation defensively.
        """
        args: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "include_payload": True,
        }
        if page_token:
            args["page_token"] = page_token
        return self.call_tool("GMAIL_FETCH_EMAILS", args)


# ─── MCP response normalization ────────────────────────────────────────────


def _extract_messages_payload(mcp_result: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Pull ``(messages, nextPageToken)`` out of a Composio MCP result.

    Composio nests the actual tool output one or two levels deep depending on
    the toolkit version. We probe for the common shapes:

    - ``result.content[0].text`` is a JSON string we can re-parse
    - ``result.data`` is the parsed object directly
    - ``result.messages`` is the parsed object directly
    """
    if not mcp_result:
        return ([], None)

    # Shape A: MCP "structured" response with text content.
    content = mcp_result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and isinstance(first.get("text"), str):
            try:
                parsed = json.loads(first["text"])
                if isinstance(parsed, dict):
                    msgs = parsed.get("messages") or parsed.get("data", {}).get("messages") or []
                    next_token = (
                        parsed.get("nextPageToken")
                        or parsed.get("next_page_token")
                        or parsed.get("data", {}).get("nextPageToken")
                    )
                    return (list(msgs), next_token)
            except json.JSONDecodeError:
                pass

    # Shape B: pre-parsed payload at top level.
    msgs = mcp_result.get("messages")
    if isinstance(msgs, list):
        next_token = mcp_result.get("nextPageToken") or mcp_result.get("next_page_token")
        return (msgs, next_token)

    # Shape C: Composio's "data" envelope.
    data = mcp_result.get("data")
    if isinstance(data, dict):
        msgs = data.get("messages") or []
        next_token = data.get("nextPageToken") or data.get("next_page_token")
        return (list(msgs), next_token)

    return ([], None)


def _normalize_message(raw: dict[str, Any]) -> GmailMessage | None:
    """Turn one raw Gmail message dict into a ``GmailMessage`` we can use.

    Returns None if the message is missing the fields we need.
    """
    message_id = raw.get("id") or raw.get("messageId") or raw.get("message_id")
    if not message_id:
        return None

    # Headers can show up in two places depending on Composio's version.
    headers_list = (
        raw.get("payload", {}).get("headers")
        or raw.get("headers")
        or []
    )
    header_map: dict[str, str] = {}
    for h in headers_list:
        name = (h.get("name") or h.get("Name") or "").lower()
        value = h.get("value") or h.get("Value") or ""
        if name:
            header_map[name] = value

    sender_name, sender_email = parse_address_header(header_map.get("from", ""))
    recipients: list[str] = []
    for header in ("to", "cc"):
        for chunk in (header_map.get(header, "") or "").split(","):
            _, email = parse_address_header(chunk)
            if email:
                recipients.append(email.lower())

    body_text = (
        raw.get("bodyText")
        or raw.get("body_text")
        or raw.get("snippet")
        or raw.get("body", {}).get("text")
        or ""
    )
    if isinstance(body_text, dict):
        body_text = body_text.get("data") or ""

    received_at = epoch_ms_to_utc(raw.get("internalDate") or raw.get("internal_date"))

    label_ids = raw.get("labelIds") or raw.get("label_ids") or raw.get("labels") or []
    labels = [str(x).upper() for x in label_ids if x]

    if not sender_email and not body_text:
        # Nothing to learn from this message.
        return None

    return GmailMessage(
        message_id=str(message_id),
        thread_id=str(raw.get("threadId") or raw.get("thread_id") or ""),
        sender_email=sender_email.lower() if sender_email else "",
        sender_name=sender_name or "",
        recipient_emails=recipients,
        subject=header_map.get("subject", "") or "",
        body_text=str(body_text),
        received_at=received_at,
        labels=labels,
    )


# ─── Watermark / state ────────────────────────────────────────────────────


def state_path(brain_dir: Path) -> Path:
    return brain_dir / ".bootstrap-state.json"


def load_state(brain_dir: Path) -> dict[str, Any]:
    p = state_path(brain_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(brain_dir: Path, state: dict[str, Any]) -> None:
    p = state_path(brain_dir)
    p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


# ─── Brain folder writers (People/, Companies/, Live Logs/) ───────────────


PERSON_TEMPLATE = """\
---
type: person
email: {email}
name: {name}
companies: {companies}
first_seen: {first_seen}
last_contact: {last_contact}
contact_frequency: {frequency}
---

# {display_name}

## Topics
- (auto-populated by the reflector)

## Recent activity
- {last_contact}: last seen in inbox

## Notes
"""


COMPANY_TEMPLATE = """\
---
type: company
domain: {domain}
first_seen: {first_seen}
last_contact: {last_contact}
people_count: {people_count}
---

# {domain}

## People
{people_list}

## Notes
"""


def upsert_person_file(
    *,
    people_dir: Path,
    email: str,
    name: str,
    company_domain: str,
    first_seen: dt.datetime,
    last_contact: dt.datetime,
    frequency: int,
    dry_run: bool,
) -> bool:
    """Idempotently write a People/<slug>.md file. Returns True if a file
    was created or modified."""
    slug = slugify_email(email)
    out_path = people_dir / f"{slug}.md"
    display = name or email
    content = PERSON_TEMPLATE.format(
        email=email,
        name=name,
        companies=f"[{company_domain}]" if company_domain else "[]",
        first_seen=first_seen.date().isoformat(),
        last_contact=last_contact.date().isoformat(),
        frequency=frequency,
        display_name=display,
    )

    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8", errors="replace")
        if existing == content:
            return False  # idempotent no-op

    if dry_run:
        return True
    people_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return True


def upsert_company_file(
    *,
    companies_dir: Path,
    domain: str,
    first_seen: dt.datetime,
    last_contact: dt.datetime,
    people: list[str],
    dry_run: bool,
) -> bool:
    fname = safe_filename(domain) + ".md"
    out_path = companies_dir / fname
    people_lines = "\n".join(f"- {p}" for p in sorted(set(people))) or "- (none yet)"
    content = COMPANY_TEMPLATE.format(
        domain=domain,
        first_seen=first_seen.date().isoformat(),
        last_contact=last_contact.date().isoformat(),
        people_count=len(set(people)),
        people_list=people_lines,
    )

    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8", errors="replace")
        if existing == content:
            return False

    if dry_run:
        return True
    companies_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return True


# ─── Postgres writers ──────────────────────────────────────────────────────


def upsert_entity(
    cur: psycopg.Cursor,
    *,
    kind: str,
    name: str,
    canonical_email: str | None,
    aliases: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> uuid.UUID | None:
    """Upsert one row into ``entities`` keyed on ``(kind, lower(name))``.

    The schema (db/003_brain_schema.sql) has a UNIQUE INDEX on
    ``entities (kind, lower(name))``. We use ON CONFLICT against that index
    to make this safe to call repeatedly.
    """
    if not name:
        return None
    aliases_arr = aliases or []
    cur.execute(
        """
        INSERT INTO entities (kind, name, aliases, canonical_email, metadata, last_seen_at)
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (kind, lower(name)) DO UPDATE
            SET aliases         = (SELECT ARRAY(SELECT DISTINCT unnest(entities.aliases || EXCLUDED.aliases))),
                canonical_email = COALESCE(entities.canonical_email, EXCLUDED.canonical_email),
                metadata        = COALESCE(entities.metadata, '{}'::jsonb) || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
                last_seen_at    = now()
        RETURNING id
        """,
        (
            kind,
            name,
            aliases_arr,
            canonical_email,
            json.dumps(metadata or {}),
        ),
    )
    row = cur.fetchone()
    return row[0] if row else None


def insert_style_sample(
    cur: psycopg.Cursor,
    *,
    user_key: str,
    sample_text: str,
    recipient_relationship: str | None,
    topic_category: str | None,
) -> bool:
    """Insert one row into ``style_samples``. Returns True if inserted."""
    text = (sample_text or "").strip()
    if not text:
        return False
    word_count = len(text.split())
    if word_count < MIN_STYLE_SAMPLE_WORDS:
        return False

    cur.execute(
        """
        INSERT INTO style_samples
            (user_key, sample_text, recipient_relationship, topic_category, word_count)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (user_key, text, recipient_relationship, topic_category, word_count),
    )
    return True


# ─── Main pipeline ────────────────────────────────────────────────────────


def relationship_label(frequency: int) -> str:
    """Crude bucket for which voice the operator uses with this recipient."""
    if frequency >= 25:
        return "close_contact"
    if frequency >= 5:
        return "regular_contact"
    return "cold"


def fetch_messages(
    reader: ComposioReader,
    *,
    query: str,
    label: str,
) -> Iterable[GmailMessage]:
    """Page through all Gmail messages matching ``query``."""
    page_token: str | None = None
    pages = 0
    while True:
        pages += 1
        if pages > MAX_PAGES_PER_CATEGORY:
            print(
                f"  [{label}] hit MAX_PAGES_PER_CATEGORY={MAX_PAGES_PER_CATEGORY}, stopping."
            )
            break
        result = reader.fetch_emails(
            query=query, page_token=page_token, max_results=PAGE_SIZE
        )
        raw_msgs, next_token = _extract_messages_payload(result)
        if not raw_msgs:
            break
        for raw in raw_msgs:
            msg = _normalize_message(raw)
            if msg:
                yield msg
        if not next_token:
            break
        page_token = next_token


def run(
    *,
    brain_dir: Path,
    db_url: str,
    user_key: str,
    composio_api_key: str,
    composio_reader_url: str,
    composio_user_id: str | None,
    days: int,
    dry_run: bool,
    reset: bool,
) -> int:
    """Top-level entry. Returns process exit code."""
    started_at = utcnow()
    print(f"SafeClaw bootstrap_brain — UTC {started_at.isoformat()}")
    print(f"  brain dir : {brain_dir}")
    print(f"  user key  : {user_key}")
    print(f"  days back : {days}")
    print(f"  dry run   : {dry_run}")
    print(f"  reset     : {reset}")
    print()

    people_dir = brain_dir / "People"
    companies_dir = brain_dir / "Companies"
    live_logs_dir = brain_dir / "2 - Live Logs"

    state = {} if reset else load_state(brain_dir)
    last_run = state.get("last_run_iso")
    last_message_id = state.get("last_message_id")
    print(f"  last run  : {last_run or '(never)'}")
    print(f"  last id   : {last_message_id or '(none)'}")
    print()

    # Build the Gmail query window. We use Gmail's `newer_than` operator
    # so the underlying request is reasonable, then page through.
    days_window = max(1, days)
    base_query = f"newer_than:{days_window}d"

    reader = ComposioReader(composio_reader_url, composio_api_key, composio_user_id)

    stats = BootstrapStats()
    domain_to_people: dict[str, set[str]] = {}
    person_first_seen: dict[str, dt.datetime] = {}
    person_last_seen: dict[str, dt.datetime] = {}
    person_name: dict[str, str] = {}
    domain_first_seen: dict[str, dt.datetime] = {}
    domain_last_seen: dict[str, dt.datetime] = {}

    sent_samples: list[GmailMessage] = []

    # ── Phase A: inbound (everyone who's emailed me) ──────────────────────
    print("Phase A — fetching inbound mail...")
    inbound_query = f"{base_query} -in:sent -in:chats"
    seen_message_ids: set[str] = set()

    for msg in fetch_messages(reader, query=inbound_query, label="inbound"):
        if msg.message_id in seen_message_ids:
            continue
        seen_message_ids.add(msg.message_id)
        if last_message_id and msg.message_id == last_message_id:
            # We've crossed the watermark; everything after is already known.
            break
        stats.emails_processed += 1

        sender = msg.sender_email
        if not sender:
            continue

        stats.contact_frequency[sender] = stats.contact_frequency.get(sender, 0) + 1
        person_name.setdefault(sender, msg.sender_name or sender)
        person_first_seen.setdefault(sender, msg.received_at)
        if msg.received_at > person_last_seen.get(sender, dt.datetime.min.replace(tzinfo=dt.timezone.utc)):
            person_last_seen[sender] = msg.received_at

        d = domain_of(sender)
        if d:
            domain_to_people.setdefault(d, set()).add(sender)
            domain_first_seen.setdefault(d, msg.received_at)
            if msg.received_at > domain_last_seen.get(d, dt.datetime.min.replace(tzinfo=dt.timezone.utc)):
                domain_last_seen[d] = msg.received_at

        if stats.emails_processed % 200 == 0:
            print(f"  ...processed {stats.emails_processed} inbound messages")

    print(f"  done. {stats.emails_processed} inbound messages processed.")
    print()

    # ── Phase B: sent (style samples) ─────────────────────────────────────
    print("Phase B — fetching sent mail (for style samples)...")
    sent_query = f"{base_query} in:sent"
    for msg in fetch_messages(reader, query=sent_query, label="sent"):
        if msg.message_id in seen_message_ids:
            continue
        seen_message_ids.add(msg.message_id)
        stats.sent_processed += 1
        if msg.body_text:
            sent_samples.append(msg)
        if stats.sent_processed % 200 == 0:
            print(f"  ...processed {stats.sent_processed} sent messages")
    print(f"  done. {stats.sent_processed} sent messages processed.")
    print()

    # ── Phase C: write brain folder + DB ──────────────────────────────────
    print("Phase C — writing People/, Companies/, and DB rows...")
    people_dir.mkdir(parents=True, exist_ok=True)
    companies_dir.mkdir(parents=True, exist_ok=True)
    live_logs_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        # Show what we would do, then exit.
        for email, freq in sorted(stats.contact_frequency.items(), key=lambda kv: -kv[1])[:20]:
            print(f"  [DRY] would upsert person: {email!r} freq={freq}")
        for d in sorted(domain_to_people):
            print(f"  [DRY] would upsert company: {d} ({len(domain_to_people[d])} people)")
        for s in sent_samples[:5]:
            preview = s.body_text.strip().replace("\n", " ")[:80]
            print(f"  [DRY] would save style sample (subject={s.subject!r}): {preview!r}")
        print()
        print(f"DRY RUN — no writes performed. Inbound={stats.emails_processed}, sent={stats.sent_processed}")
        return 0

    # Real DB writes.
    with psycopg.connect(db_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            # People
            for email, freq in stats.contact_frequency.items():
                name = person_name.get(email, email)
                first_seen = person_first_seen.get(email, started_at)
                last_seen = person_last_seen.get(email, started_at)
                d = domain_of(email)

                changed = upsert_person_file(
                    people_dir=people_dir,
                    email=email,
                    name=name,
                    company_domain=d,
                    first_seen=first_seen,
                    last_contact=last_seen,
                    frequency=freq,
                    dry_run=False,
                )
                if changed:
                    stats.people_upserted += 1

                upsert_entity(
                    cur,
                    kind="person",
                    name=name or email,
                    canonical_email=email,
                    aliases=[email],
                    metadata={"domain": d, "frequency": freq},
                )

            # Companies
            for d, people in domain_to_people.items():
                changed = upsert_company_file(
                    companies_dir=companies_dir,
                    domain=d,
                    first_seen=domain_first_seen.get(d, started_at),
                    last_contact=domain_last_seen.get(d, started_at),
                    people=sorted(people),
                    dry_run=False,
                )
                if changed:
                    stats.companies_upserted += 1
                upsert_entity(
                    cur,
                    kind="company",
                    name=d,
                    canonical_email=None,
                    aliases=[d],
                    metadata={"people_count": len(people)},
                )

            # Style samples (sent mail bodies)
            for msg in sent_samples:
                primary_recipient = msg.recipient_emails[0] if msg.recipient_emails else ""
                relationship = relationship_label(
                    stats.contact_frequency.get(primary_recipient, 0)
                )
                inserted = insert_style_sample(
                    cur,
                    user_key=user_key,
                    sample_text=msg.body_text,
                    recipient_relationship=relationship,
                    topic_category=None,
                )
                if inserted:
                    stats.style_samples_saved += 1

        conn.commit()

    # ── Phase D: report + watermark ───────────────────────────────────────
    finished_at = utcnow()
    elapsed = (finished_at - started_at).total_seconds()
    report_path = (
        live_logs_dir
        / f"bootstrap-{started_at.strftime('%Y%m%d-%H%M%S')}.md"
    )
    top_contacts = sorted(
        stats.contact_frequency.items(), key=lambda kv: -kv[1]
    )[:10]
    report_lines = [
        "# SafeClaw — Bootstrap Report",
        "",
        f"- run started: `{started_at.isoformat()}`",
        f"- run finished: `{finished_at.isoformat()}`",
        f"- elapsed: `{elapsed:.1f}s`",
        f"- days scanned: `{days}`",
        f"- inbound emails processed: `{stats.emails_processed}`",
        f"- sent emails processed: `{stats.sent_processed}`",
        f"- People profiles created/updated: `{stats.people_upserted}`",
        f"- Companies profiles created/updated: `{stats.companies_upserted}`",
        f"- style samples saved: `{stats.style_samples_saved}`",
        "",
        "## Top contacts (by message volume)",
        "",
    ]
    for email, freq in top_contacts:
        report_lines.append(f"- `{email}` — {freq} messages")
    if not top_contacts:
        report_lines.append("- (none seen)")
    report_lines.extend([
        "",
        "*Brain folder layout based on Samin Yasar's Evolving Brain Template (MIT) —*",
        "*https://github.com/Samin12/Evolving-Brain-Template*",
        "",
    ])
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    # Update watermark.
    new_state = dict(state)
    new_state["last_run_iso"] = finished_at.isoformat()
    if seen_message_ids:
        # We can't sort message IDs by time without a parse — so we just
        # remember the most recent received_at as the watermark and the
        # most recently-seen ID for tie-breaking.
        most_recent = max(person_last_seen.values()) if person_last_seen else finished_at
        new_state["watermark_received_at"] = most_recent.isoformat()
        # Pick any stable id from the run as a tie-breaker (set is unordered;
        # this is an opportunistic check).
        new_state["last_message_id"] = next(iter(seen_message_ids))
    save_state(brain_dir, new_state)

    # Print the final banner the operator sees.
    bar = "━" * 60
    print()
    print(bar)
    print(f"  Brain bootstrapped from {days} days of Gmail history")
    print(bar)
    print(f"   Created   {stats.people_upserted} People profiles  -> brain/People/")
    print(f"             {stats.companies_upserted} Companies        -> brain/Companies/")
    print(f"             {stats.style_samples_saved} Style samples    -> postgres-obs.style_samples")
    print()
    print("Next steps:")
    print("   1. Open brain/0 - Identity/ and edit your soul.md (1 min)")
    print("   2. Glance at brain/People/ — verify it picked up the right contacts")
    print("   3. DM your bot on Telegram — it now knows who you talk to")
    print(bar)
    print(f"  Report: {report_path.relative_to(brain_dir.parent)}")
    print(f"  Brain layout: Evolving Brain Template (MIT) by Samin Yasar")
    print(bar)
    return 0


# ─── CLI plumbing ─────────────────────────────────────────────────────────


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="bootstrap_brain.py",
        description="Seed the SafeClaw brain from N days of Gmail history.",
    )
    p.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"How many days back to scrape (default: BOOTSTRAP_DAYS env or {DEFAULT_DAYS}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse + print what would happen, do not write anything.",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Clear the watermark and reprocess everything in the window.",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    brain_dir = Path(os.environ.get("BRAIN_DIR", "/repo/brain")).resolve()
    if not brain_dir.exists():
        print(f"ERROR: brain dir not found at {brain_dir}", file=sys.stderr)
        print("       Run scripts/bootstrap-brain.sh — it clones the template first.", file=sys.stderr)
        return 1

    # Required env vars (the wrapper script already checks these, but we
    # check again for the case where the operator runs the .py directly).
    try:
        db_url = os.environ["BRAIN_OBS_DATABASE_URL"]
        composio_api_key = os.environ["COMPOSIO_API_KEY"]
        composio_reader_url = os.environ["COMPOSIO_READER_MCP_URL"]
        user_key = os.environ.get("BRAIN_USER_KEY", "primary")
        composio_user_id = os.environ.get("COMPOSIO_USER_ID") or None
    except KeyError as missing:
        print(f"ERROR: required env var {missing} is not set.", file=sys.stderr)
        return 1

    days_env = os.environ.get("BOOTSTRAP_DAYS")
    days = args.days or (int(days_env) if days_env else DEFAULT_DAYS)

    try:
        return run(
            brain_dir=brain_dir,
            db_url=db_url,
            user_key=user_key,
            composio_api_key=composio_api_key,
            composio_reader_url=composio_reader_url,
            composio_user_id=composio_user_id,
            days=days,
            dry_run=args.dry_run,
            reset=args.reset,
        )
    except ComposioMCPError as e:
        print(f"ERROR: Composio MCP call failed — {e}", file=sys.stderr)
        return 2
    except psycopg.Error as e:
        print(f"ERROR: Postgres error — {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
