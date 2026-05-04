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
PAGE_SIZE = 25  # Composio MCP returns 0 messages when max_results=100. 25 works reliably.

# Hard cap on pages per category to keep runaway runs bounded.
MAX_PAGES_PER_CATEGORY = 200

# Backoff parameters for HTTP retries against the Composio MCP endpoint.
HTTP_MAX_RETRIES = 3
HTTP_BACKOFF_SECONDS = 2.0

# Minimum word count for a body to be worth saving as a style sample.
MIN_STYLE_SAMPLE_WORDS = 8


# ─── Data shapes ───────────────────────────────────────────────────────────


@dataclass
class Attachment:
    """One Gmail attachment — metadata + (optionally) Drive landing."""

    attachment_id: str   # Gmail's attachmentId, used to fetch the bytes
    filename: str
    mime_type: str
    size_bytes: int
    drive_url: str = ""        # populated after Drive upload (empty if skipped/failed)
    drive_file_id: str = ""    # Google Drive file ID (for re-find / move ops)
    upload_error: str = ""     # populated if upload was attempted and failed


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
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def is_sent(self) -> bool:
        return "SENT" in self.labels


@dataclass
class BootstrapStats:
    emails_processed: int = 0
    sent_processed: int = 0
    journal_files_created: int = 0
    style_samples_saved: int = 0
    attachments_seen: int = 0
    attachments_uploaded: int = 0
    attachments_skipped: int = 0
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


def _iso_to_utc(iso: str | None) -> dt.datetime | None:
    """Parse Composio's ISO8601 messageTimestamp to UTC datetime."""
    if not iso:
        return None
    try:
        # Python 3.11+ handles trailing 'Z' natively in fromisoformat.
        s = str(iso).replace("Z", "+00:00")
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


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
    # Cloudflare in front of Composio blocks `Python-urllib/x.x` UA with 1010.
    # Identify ourselves as a normal client.
    req.add_header("User-Agent", "safeclaw-bootstrap/1.0 (+https://github.com/Vasanth19/safeclaw)")
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

    SSE spec: events are blank-line-separated. Within an event, multiple
    ``data:`` lines are concatenated with ``\\n`` to form the event's data.
    Composio's MCP usually emits one event with one ``data:`` line, but
    very large payloads (e.g. 25-message Gmail batches) can wrap across
    many lines — we MUST join ``data:`` lines per event before parsing
    or json.loads() fails on the truncated chunk.
    """
    events: list[str] = []
    current_data: list[str] = []
    # IMPORTANT: split on '\n' only, NOT str.splitlines(). Emails routed via
    # Composio Reader contain Unicode line separators (U+2028 LSEP and friends)
    # inside JSON string bodies; splitlines() treats those as line breaks and
    # shreds the JSON across multiple "lines", which then fail to parse.
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line == "":
            # Blank line ends an event.
            if current_data:
                events.append("\n".join(current_data))
                current_data = []
            continue
        if line.startswith("data:"):
            current_data.append(line[len("data:"):].lstrip())
        # Other SSE fields (event:, id:, retry:) are ignored.
    if current_data:
        events.append("\n".join(current_data))

    last_data_json: dict[str, Any] = {}
    last_decode_err: Exception | None = None
    for body in events:
        body = body.strip()
        if not body or body == "[DONE]":
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            last_decode_err = exc
            continue
        if isinstance(parsed, dict):
            last_data_json = parsed

    if not last_data_json:
        # Dump the raw to disk for forensic inspection (only on failure).
        dump_path = "/repo/composio_raw_debug.txt"
        try:
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(raw)
        except OSError:
            dump_path = "(could not write dump)"
        head = raw[:300].replace("\n", "\\n")
        tail = raw[-300:].replace("\n", "\\n")
        raise ComposioMCPError(
            "Composio MCP returned an SSE response with no parseable data lines "
            f"(raw_len={len(raw)}, events={len(events)}, decode_err={last_decode_err}, "
            f"dump={dump_path}). head={head!r}, tail={tail!r}"
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

        Account selection is baked into the MCP URL via the
        ``?connected_account_id=`` query parameter — NOT via tool arguments.
        Composio ignores ``connected_account_id`` when passed as a tool arg;
        it only honors it as a URL param at connection time.
        """
        args: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "include_payload": True,
        }
        if page_token:
            args["page_token"] = page_token
        return self.call_tool("GMAIL_FETCH_EMAILS", args)

    def fetch_attachment(
        self,
        *,
        message_id: str,
        attachment_id: str,
    ) -> bytes | None:
        """Wraps ``GMAIL_FETCH_ATTACHMENT``. Returns raw bytes or None on miss.

        Composio's GMAIL_FETCH_ATTACHMENT returns the attachment's content
        as base64url-encoded text. We decode here so callers get bytes.
        """
        if not message_id or not attachment_id:
            return None
        try:
            result = self.call_tool(
                "GMAIL_FETCH_ATTACHMENT",
                {"message_id": message_id, "attachment_id": attachment_id},
            )
        except ComposioMCPError:
            return None
        # Composio MCP returns isError=true with a "Tool ... not found" when
        # GMAIL_FETCH_ATTACHMENT isn't in the toolkit allowlist. Detect that
        # so callers can show a clear guidance message instead of mysterious
        # "empty bytes" warnings.
        if result.get("isError"):
            content = result.get("content", [])
            err_text = ""
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict):
                    err_text = first.get("text", "")
            if "not found" in err_text.lower():
                raise ComposioMCPError(
                    "GMAIL_FETCH_ATTACHMENT not enabled in Composio MCP toolkit. "
                    "Enable it in the Composio dashboard for the Reader (or Actor) MCP "
                    "to allow attachment download + Drive upload."
                )
            raise ComposioMCPError(f"GMAIL_FETCH_ATTACHMENT failed: {err_text or result}")
        # Same content-shape probing as fetch_emails: the payload may be in
        # result.content[0].text (JSON-encoded) or result.data.
        content = result.get("content")
        payload: dict[str, Any] | None = None
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and isinstance(first.get("text"), str):
                try:
                    parsed = json.loads(first["text"])
                    if isinstance(parsed, dict):
                        payload = parsed.get("data") or parsed
                except json.JSONDecodeError:
                    pass
        if payload is None:
            payload = result.get("data") or result
        if not isinstance(payload, dict):
            return None
        b64 = (
            payload.get("data")
            or payload.get("attachment_data")
            or payload.get("base64_data")
            or ""
        )
        if not b64:
            return None
        # Gmail uses URL-safe base64. Pad and decode.
        import base64
        try:
            padded = b64 + "=" * (-len(b64) % 4)
            return base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, TypeError):
            return None


class ComposioActor:
    """Tiny client for the Composio Actor MCP server (write side).

    Owns Drive upload + folder creation. Kept separate from Reader so the
    trust boundary stays explicit — a misconfigured COMPOSIO_ACTOR_MCP_URL
    or missing Drive scope shows up as a clean error here, not as a silent
    Reader privilege escalation.
    """

    def __init__(self, mcp_url: str, api_key: str, user_id: str | None = None):
        self.mcp_url = mcp_url
        self.headers = {
            "x-api-key": api_key,
            "User-Agent": "SafeClaw-Bootstrap/1.0",
        }
        if user_id:
            self.headers["x-composio-user-id"] = user_id
        self._rpc_id = 0

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        resp = _http_post_json(self.mcp_url, self.headers, body)
        if "error" in resp and resp["error"]:
            raise ComposioMCPError(
                f"Composio Actor MCP error for tool {tool_name}: {resp['error']}"
            )
        return resp.get("result", {}) or {}

    @staticmethod
    def _extract_payload(result: dict[str, Any]) -> dict[str, Any]:
        """Probe the same content shapes the Reader uses."""
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and isinstance(first.get("text"), str):
                try:
                    parsed = json.loads(first["text"])
                    if isinstance(parsed, dict):
                        return parsed.get("data") or parsed
                except json.JSONDecodeError:
                    pass
        data = result.get("data")
        if isinstance(data, dict):
            return data
        return result if isinstance(result, dict) else {}

    def find_or_create_folder(
        self,
        *,
        folder_path: list[str],
        folder_cache: dict[str, str],
    ) -> str:
        """Walk ``folder_path`` (top-down), creating any missing segment.

        Returns the leaf folder's Drive ID. Cached per-process so a run
        with 100 attachments to the same monthly folder makes 1 lookup,
        not 100.
        """
        cache_key = "/".join(folder_path)
        if cache_key in folder_cache:
            return folder_cache[cache_key]

        parent_id = "root"
        running_path: list[str] = []
        for segment in folder_path:
            running_path.append(segment)
            running_key = "/".join(running_path)
            if running_key in folder_cache:
                parent_id = folder_cache[running_key]
                continue
            # Create (or find existing). Composio's GOOGLEDRIVE_CREATE_FOLDER
            # is idempotent on (name, parent) in our experience — but we still
            # try-then-find as a defensive belt.
            try:
                result = self.call_tool(
                    "GOOGLEDRIVE_CREATE_FOLDER",
                    {
                        "folder_name": segment,
                        "parent_id": parent_id,
                    },
                )
                payload = self._extract_payload(result)
                new_id = (
                    payload.get("id")
                    or payload.get("folder_id")
                    or payload.get("file_id")
                    or ""
                )
            except ComposioMCPError:
                new_id = ""
            if not new_id:
                # Fallback: GOOGLEDRIVE_FIND_FOLDER lookup by name+parent.
                try:
                    found = self.call_tool(
                        "GOOGLEDRIVE_FIND_FOLDER",
                        {"folder_name": segment, "parent_id": parent_id},
                    )
                    fpayload = self._extract_payload(found)
                    new_id = (
                        fpayload.get("id")
                        or fpayload.get("folder_id")
                        or ""
                    )
                except ComposioMCPError:
                    new_id = ""
            if not new_id:
                raise ComposioMCPError(
                    f"could not create or find Drive folder {segment!r} under {parent_id}"
                )
            folder_cache[running_key] = new_id
            parent_id = new_id
        return parent_id

    def upload_file(
        self,
        *,
        parent_folder_id: str,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, str]:
        """Upload bytes to Drive. Returns ``{file_id, web_view_link}``."""
        import base64
        b64 = base64.b64encode(content).decode("ascii")
        result = self.call_tool(
            "GOOGLEDRIVE_UPLOAD_FILE",
            {
                "file_name": filename,
                "parent_id": parent_folder_id,
                "mime_type": mime_type or "application/octet-stream",
                "file_content_base64": b64,
            },
        )
        payload = self._extract_payload(result)
        return {
            "file_id": str(
                payload.get("id") or payload.get("file_id") or ""
            ),
            "web_view_link": str(
                payload.get("webViewLink")
                or payload.get("web_view_link")
                or payload.get("url")
                or ""
            ),
        }


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

    # Composio MCP normalizes the message and returns these as top-level fields:
    #   sender = "Display Name <email@host>"
    #   to     = comma-separated recipients
    #   subject, messageText, messageTimestamp (ISO8601), labelIds
    # Older Gmail-API-shaped responses use payload.headers + bodyText/snippet.
    # We probe both.
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

    # Composio top-level fields take precedence when present.
    from_str = raw.get("sender") or header_map.get("from", "")
    to_str = raw.get("to") or header_map.get("to", "")
    cc_str = raw.get("cc") or header_map.get("cc", "")

    sender_name, sender_email = parse_address_header(from_str)
    recipients: list[str] = []
    for chunk in (str(to_str) + "," + str(cc_str)).split(","):
        _, email = parse_address_header(chunk)
        if email:
            recipients.append(email.lower())

    subject = raw.get("subject") or header_map.get("subject", "") or ""

    body_text = (
        raw.get("messageText")          # Composio MCP top-level (most common today)
        or raw.get("bodyText")
        or raw.get("body_text")
        or raw.get("snippet")
        or raw.get("body", {}).get("text")
        or ""
    )
    if isinstance(body_text, dict):
        body_text = body_text.get("data") or ""

    # Composio returns ISO timestamps; older shape uses epoch ms.
    received_at = (
        _iso_to_utc(raw.get("messageTimestamp"))
        or epoch_ms_to_utc(raw.get("internalDate") or raw.get("internal_date"))
    )

    label_ids = raw.get("labelIds") or raw.get("label_ids") or raw.get("labels") or []
    labels = [str(x).upper() for x in label_ids if x]

    # Attachments — Composio MCP returns these as ``attachmentList`` per
    # message. Each entry has at minimum filename + mimeType + (sometimes)
    # attachmentId + size. We capture metadata here; the byte payload is
    # fetched lazily later (via GMAIL_FETCH_ATTACHMENT) only if Drive upload
    # is enabled.
    attachments: list[Attachment] = []
    raw_atts = (
        raw.get("attachmentList")
        or raw.get("attachments")
        or raw.get("attachment_list")
        or []
    )
    if isinstance(raw_atts, list):
        for a in raw_atts:
            if not isinstance(a, dict):
                continue
            fname = (
                a.get("filename") or a.get("file_name")
                or a.get("name") or ""
            )
            if not fname:
                continue
            attachments.append(
                Attachment(
                    attachment_id=str(
                        a.get("attachmentId") or a.get("attachment_id") or ""
                    ),
                    filename=str(fname),
                    mime_type=str(a.get("mimeType") or a.get("mime_type") or ""),
                    size_bytes=int(a.get("size") or a.get("sizeBytes") or 0),
                )
            )

    if not sender_email and not body_text and not attachments:
        # Nothing to learn from this message.
        return None

    return GmailMessage(
        message_id=str(message_id),
        thread_id=str(raw.get("threadId") or raw.get("thread_id") or ""),
        sender_email=sender_email.lower() if sender_email else "",
        sender_name=sender_name or "",
        recipient_emails=recipients,
        subject=subject,
        body_text=str(body_text),
        received_at=received_at,
        labels=labels,
        attachments=attachments,
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


def attachments_state_path(brain_dir: Path) -> Path:
    """Sidecar for attachment idempotency: maps <message_id>:<attachment_id>
    to {drive_file_id, drive_url, sender, filename, uploaded_at}.

    Without this, re-running bootstrap would re-upload the same attachment
    every time. With this, we skip anything already in Drive."""
    return brain_dir / ".attachments-state.json"


def load_attachments_state(brain_dir: Path) -> dict[str, dict[str, Any]]:
    p = attachments_state_path(brain_dir)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_attachments_state(brain_dir: Path, state: dict[str, dict[str, Any]]) -> None:
    p = attachments_state_path(brain_dir)
    p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


# ─── Brain folder writers (People/, Companies/, Live Logs/) ───────────────


DAILY_JOURNAL_TEMPLATE = """\
---
date: {date}
source: gmail
account: {account}
inbound_count: {inbound_count}
sent_count: {sent_count}
---

# Daily Journal — {date}

## Inbound ({inbound_count})

{inbound_block}

## Sent ({sent_count})

{sent_block}

## Attachments

{attachments_block}

## Notes
"""


def _format_attachments_block(records: list[dict[str, Any]]) -> str:
    """Render the 'Attachments received' bullet list for a person's .md.

    ``records`` is a list of {date, filename, mime, size_bytes, drive_url, subject}
    dicts (most recent first). If empty, we leave a placeholder so the file
    layout stays predictable when attachments later arrive.
    """
    if not records:
        return "- (none yet)"
    lines: list[str] = []
    for r in records[:30]:  # cap so this section doesn't run away
        size_kb = max(1, int(r.get("size_bytes") or 0) // 1024)
        date = r.get("date") or "?"
        fname = r.get("filename") or "?"
        subj = r.get("subject") or ""
        drive = r.get("drive_url") or ""
        # Format: - 2026-04-28: `pricing.pdf` (PDF, 245KB) — "Re: Q3 pricing"
        #             [Drive](https://drive.google.com/...)
        meta = f"({(r.get('mime') or 'file').split('/')[-1].upper()}, {size_kb}KB)"
        head = f"- {date}: `{fname}` {meta}"
        if subj:
            head += f' — "{subj[:80]}"'
        lines.append(head)
        if drive:
            lines.append(f"  - [Open in Drive]({drive})")
    return "\n".join(lines)


def write_daily_journal(
    *,
    journal_dir: Path,
    date: dt.date,
    account: str,
    inbound: list[GmailMessage],
    sent: list[GmailMessage],
    attachments_map: dict[str, list[dict[str, Any]]],
    dry_run: bool,
) -> bool:
    """Write one Daily Journal file for a single date. Returns True if written."""
    out_path = journal_dir / f"{date.isoformat()}.md"

    # Group inbound by sender domain
    sender_groups: dict[str, list[GmailMessage]] = {}
    for msg in inbound:
        d = domain_of(msg.sender_email) or "unknown"
        sender_groups.setdefault(d, []).append(msg)

    inbound_lines: list[str] = []
    for domain, msgs in sorted(sender_groups.items(), key=lambda kv: -len(kv[1])):
        inbound_lines.append(f"### {domain} ({len(msgs)})")
        for msg in msgs:
            preview = msg.subject or "(no subject)"
            sender = msg.sender_name or msg.sender_email
            inbound_lines.append(f"- **{sender}** — {preview}")
        inbound_lines.append("")

    if not inbound_lines:
        inbound_lines.append("No inbound email.")

    sent_lines: list[str] = []
    for msg in sent:
        preview = msg.subject or "(no subject)"
        recipients = ", ".join(msg.recipient_emails[:3])
        body_preview = msg.body_text.strip().replace("\n", " ")[:80]
        sent_lines.append(f"- **To:** {recipients} — {preview}")
        if body_preview:
            sent_lines.append(f"  > {body_preview}")

    if not sent_lines:
        sent_lines.append("No sent email.")

    att_records: list[dict[str, Any]] = []
    for sender, records in attachments_map.items():
        att_records.extend(records)
    att_block = _format_attachments_block(att_records)

    content = DAILY_JOURNAL_TEMPLATE.format(
        date=date.isoformat(),
        account=account,
        inbound_count=len(inbound),
        sent_count=len(sent),
        inbound_block="\n".join(inbound_lines),
        sent_block="\n".join(sent_lines),
        attachments_block=att_block,
    )

    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8", errors="replace")
        if existing == content:
            return False

    if dry_run:
        return True
    journal_dir.mkdir(parents=True, exist_ok=True)
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
            query=query, page_token=page_token, max_results=PAGE_SIZE,
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
    composio_actor_url: str | None,
    composio_user_id: str | None,
    composio_account_ids: list[str],
    days: int,
    dry_run: bool,
    reset: bool,
) -> int:
    """Top-level entry. Returns process exit code."""
    started_at = utcnow()
    account_display = ", ".join(composio_account_ids) if composio_account_ids else "(default)"
    print(f"SafeClaw bootstrap_brain — UTC {started_at.isoformat()}")
    print(f"  brain dir : {brain_dir}")
    print(f"  user key  : {user_key}")
    print(f"  days back : {days}")
    print(f"  dry run   : {dry_run}")
    print(f"  reset     : {reset}")
    print(f"  accounts  : {account_display}")
    print()

    journal_dir = brain_dir / "3 - Daily Journal"
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

    # Build one ComposioReader per connected Gmail account.
    # Composio MCP resolves which account to use via the URL query parameter
    # ?user_id=<entity>&connected_account_id=<acct> — NOT via tool arguments.
    # When COMPOSIO_ACCOUNT_IDS is set, each ID gets its own URL and reader so
    # truly separate inboxes are all scanned. When the list has one entry (or is
    # empty), a single reader is used — the common case when both email addresses
    # are aliases on the same Google account.
    from urllib.parse import urlparse, urlunparse
    _parsed = urlparse(composio_reader_url)
    _base_url = urlunparse(_parsed._replace(query=""))
    _user_param = f"user_id={composio_user_id}" if composio_user_id else ""
    if composio_account_ids:
        readers: list[tuple[str, ComposioReader]] = [
            (
                acct_id,
                ComposioReader(
                    f"{_base_url}?{_user_param}&connected_account_id={acct_id}",
                    composio_api_key,
                ),
            )
            for acct_id in composio_account_ids
        ]
    else:
        readers = [
            (composio_user_id or "default",
             ComposioReader(composio_reader_url, composio_api_key, composio_user_id))
        ]

    stats = BootstrapStats()
    domain_to_people: dict[str, set[str]] = {}
    person_first_seen: dict[str, dt.datetime] = {}
    person_last_seen: dict[str, dt.datetime] = {}
    person_name: dict[str, str] = {}
    domain_first_seen: dict[str, dt.datetime] = {}
    domain_last_seen: dict[str, dt.datetime] = {}

    sent_samples: list[GmailMessage] = []
    all_inbound: list[GmailMessage] = []

    # Per-person attachment records, accumulated during Phase A and rendered
    # into brain/People/<slug>.md during Phase C. Key: sender_email, value:
    # list of dicts that match _format_attachments_block's expected shape.
    person_attachments: dict[str, list[dict[str, Any]]] = {}

    # Pending attachment uploads, deferred to Phase A.5 (Drive). We capture
    # everything we'd want to upload during Phase A so the loop above stays
    # fast (one Composio fetch_attachment call per attachment is slow).
    pending_attachments: list[dict[str, Any]] = []

    # ── Phase A: inbound (everyone who's emailed me) ──────────────────────
    # Each reader targets one Gmail account via its ?connected_account_id= URL.
    # Query is bare date-range (no in:inbox) to capture auto-archived threads.
    print("Phase A — fetching inbound mail...")
    inbound_query = base_query
    seen_message_ids: set[str] = set()

    for acct_id, reader in readers:
        acct_label = f"inbound/{acct_id[:8]}"
        print(f"  account: {acct_id}")
        for msg in fetch_messages(reader, query=inbound_query, label=acct_label):
            if msg.message_id in seen_message_ids:
                continue
            seen_message_ids.add(msg.message_id)
            if last_message_id and msg.message_id == last_message_id:
                # We've crossed the watermark; everything after is already known.
                break
            stats.emails_processed += 1

            # Skip outbound messages — Phase B handles sent mail separately.
            if msg.is_sent:
                continue

            sender = msg.sender_email
            if not sender:
                continue

            all_inbound.append(msg)
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

            # Capture attachment metadata + queue for Drive upload. We always
            # record metadata in the brain (cheap); the upload itself happens
            # in Phase A.5 only if the actor MCP is configured.
            if msg.attachments:
                for att in msg.attachments:
                    stats.attachments_seen += 1
                    record = {
                        "date": msg.received_at.date().isoformat(),
                        "filename": att.filename,
                        "mime": att.mime_type,
                        "size_bytes": att.size_bytes,
                        "subject": msg.subject,
                        "drive_url": "",   # filled by Phase A.5 if upload succeeds
                        "message_id": msg.message_id,
                        "attachment_id": att.attachment_id,
                    }
                    person_attachments.setdefault(sender, []).insert(0, record)
                    if att.attachment_id:
                        pending_attachments.append({
                            "record": record,
                            "sender_domain": d,
                            "sender_email": sender,
                            "received_at": msg.received_at,
                        })

            if stats.emails_processed % 200 == 0:
                print(f"  ...processed {stats.emails_processed} inbound messages")

    print(f"  done. {stats.emails_processed} inbound messages processed.")
    if stats.attachments_seen:
        print(f"  found {stats.attachments_seen} attachments across inbound messages.")
    print()

    # ── Phase A.5: download & upload attachments to Drive ─────────────────
    # Skipped silently if no actor URL configured — the metadata still
    # lands in brain/People/<slug>.md, just without Drive links.
    if pending_attachments and composio_actor_url and not dry_run:
        print(f"Phase A.5 — uploading {len(pending_attachments)} attachments to Google Drive...")
        att_state = load_attachments_state(brain_dir)
        actor = ComposioActor(composio_actor_url, composio_api_key, composio_user_id)
        folder_cache: dict[str, str] = {}
        # Drive layout: SafeClaw Inbox / <YYYY-MM> / <sender-domain> / <filename>
        DRIVE_ROOT = "SafeClaw Inbox"

        # Quick precondition probe: if GMAIL_FETCH_ATTACHMENT isn't in the
        # MCP toolkit, fail fast with a clear message instead of looping
        # over every attachment producing identical "not found" errors.
        toolkit_ok = True
        for entry in pending_attachments:
            record = entry["record"]
            mid = record["message_id"]
            aid = record["attachment_id"]
            state_key = f"{mid}:{aid}"
            # Idempotency: already uploaded in a prior run.
            if state_key in att_state:
                cached = att_state[state_key]
                record["drive_url"] = cached.get("drive_url", "")
                stats.attachments_skipped += 1
                continue
            if not toolkit_ok:
                # Earlier iteration already proved the toolkit is missing the
                # download tool — don't repeat the error for every file.
                continue
            # Download from Gmail.
            try:
                blob = reader.fetch_attachment(message_id=mid, attachment_id=aid)
            except ComposioMCPError as exc:
                if "not enabled" in str(exc):
                    print(f"  [error] {exc}")
                    print(f"  [error] Skipping Drive upload for remaining "
                          f"{len(pending_attachments) - stats.attachments_skipped} attachments. "
                          "Metadata is still recorded in brain/People/<slug>.md.")
                    toolkit_ok = False
                else:
                    print(f"  [warn] download failed for {record['filename']}: {exc}")
                continue
            except Exception as exc:  # pragma: no cover — defensive
                print(f"  [warn] download failed for {record['filename']}: {exc}")
                blob = None
            if not blob:
                print(f"  [warn] empty/missing bytes for {record['filename']} — skipping")
                continue
            # Resolve target folder.
            ym = entry["received_at"].strftime("%Y-%m")
            sender_domain = entry["sender_domain"] or "unknown"
            folder_path = [DRIVE_ROOT, ym, sender_domain]
            try:
                folder_id = actor.find_or_create_folder(
                    folder_path=folder_path, folder_cache=folder_cache,
                )
            except ComposioMCPError as exc:
                print(f"  [warn] folder resolve failed for {'/'.join(folder_path)}: {exc}")
                continue
            # Upload.
            try:
                up = actor.upload_file(
                    parent_folder_id=folder_id,
                    filename=record["filename"],
                    content=blob,
                    mime_type=record["mime"] or "application/octet-stream",
                )
            except ComposioMCPError as exc:
                print(f"  [warn] upload failed for {record['filename']}: {exc}")
                continue
            record["drive_url"] = up.get("web_view_link") or ""
            att_state[state_key] = {
                "drive_file_id": up.get("file_id", ""),
                "drive_url": record["drive_url"],
                "sender": entry["sender_email"],
                "filename": record["filename"],
                "uploaded_at": utcnow().isoformat(),
                "folder": "/".join(folder_path),
            }
            stats.attachments_uploaded += 1
        save_attachments_state(brain_dir, att_state)
        print(
            f"  done. uploaded={stats.attachments_uploaded} "
            f"skipped(already in Drive)={stats.attachments_skipped}"
        )
        print()
    elif pending_attachments and not composio_actor_url:
        print(
            f"Phase A.5 — skipping Drive upload "
            f"({len(pending_attachments)} attachments would have been uploaded). "
            "Set COMPOSIO_ACTOR_MCP_URL to enable."
        )
        print()

    # ── Phase B: sent (style samples) ─────────────────────────────────────
    print("Phase B — fetching sent mail (for style samples)...")
    sent_query = f"{base_query} in:sent"
    for acct_id, reader in readers:
        acct_label = f"sent/{acct_id[:8]}"
        for msg in fetch_messages(reader, query=sent_query, label=acct_label):
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

    # ── Phase C: write Daily Journal + DB ─────────────────────────────────
    print("Phase C — writing Daily Journal files and DB rows...")
    journal_dir.mkdir(parents=True, exist_ok=True)
    live_logs_dir.mkdir(parents=True, exist_ok=True)

    # Group messages by date for journal creation.
    daily_inbound: dict[str, list[GmailMessage]] = {}
    daily_sent: dict[str, list[GmailMessage]] = {}
    daily_attachments: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for msg in (m for m in all_inbound if m.sender_email):
        date_key = msg.received_at.date().isoformat()
        daily_inbound.setdefault(date_key, []).append(msg)
    for msg in sent_samples:
        date_key = msg.received_at.date().isoformat()
        daily_sent.setdefault(date_key, []).append(msg)
    for sender, records in person_attachments.items():
        for rec in records:
            date_key = rec.get("date") or started_at.date().isoformat()
            daily_attachments.setdefault(date_key, {}).setdefault(sender, []).append(rec)

    if dry_run:
        print("  [DRY] would write daily journals for:")
        for date_key in sorted(set(daily_inbound) | set(daily_sent)):
            ib = len(daily_inbound.get(date_key, []))
            se = len(daily_sent.get(date_key, []))
            print(f"    {date_key}: {ib} inbound, {se} sent")
        print(f"  [DRY] would save {len(sent_samples)} style samples")
        print()
        print(f"DRY RUN — no writes performed. Inbound={stats.emails_processed}, sent={stats.sent_processed}")
        return 0

    # Real DB + vault writes.
    with psycopg.connect(db_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            # Daily Journal files — one per date.
            for date_key in sorted(set(daily_inbound) | set(daily_sent)):
                d = dt.date.fromisoformat(date_key)
                changed = write_daily_journal(
                    journal_dir=journal_dir,
                    date=d,
                    account=account_display,
                    inbound=daily_inbound.get(date_key, []),
                    sent=daily_sent.get(date_key, []),
                    attachments_map=daily_attachments.get(date_key, {}),
                    dry_run=False,
                )
                if changed:
                    stats.journal_files_created += 1

            # Style samples (sent mail bodies) — still go to postgres.
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
        f"- daily journal files created/updated: `{stats.journal_files_created}`",
        f"- style samples saved: `{stats.style_samples_saved}`",
        f"- attachments seen: `{stats.attachments_seen}`",
        f"- attachments uploaded to Drive: `{stats.attachments_uploaded}`",
        f"- attachments skipped (already in Drive): `{stats.attachments_skipped}`",
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
    print(f"   Created   {stats.journal_files_created} Daily journals -> brain/3 - Daily Journal/")
    print(f"             {stats.style_samples_saved} Style samples    -> postgres-obs.style_samples")
    if stats.attachments_seen:
        print(f"             {stats.attachments_seen} Attachments seen "
              f"({stats.attachments_uploaded} uploaded to Drive, "
              f"{stats.attachments_skipped} skipped)")
    print()
    print("Next steps:")
    print("   1. Open brain/0 - Identity/ and edit your soul.md (1 min)")
    print("   2. Glance at brain/3 - Daily Journal/ — daily digest of emails")
    print("   3. Create People/ entries manually only for key relationships")
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

    # Optional — drives Phase A.5 (Drive upload). If absent, attachment
    # metadata still lands in brain/People/<slug>.md without Drive links.
    composio_actor_url = os.environ.get("COMPOSIO_ACTOR_MCP_URL") or None

    # Optional — comma-separated list of Composio connectedAccountIds.
    # When set, Phase A + B iterate over each account so all linked Gmail
    # inboxes are scanned. Example: "abc123,def456"
    raw_account_ids = os.environ.get("COMPOSIO_ACCOUNT_IDS", "")
    composio_account_ids = [a.strip() for a in raw_account_ids.split(",") if a.strip()]

    days_env = os.environ.get("BOOTSTRAP_DAYS")
    days = args.days or (int(days_env) if days_env else DEFAULT_DAYS)

    try:
        return run(
            brain_dir=brain_dir,
            db_url=db_url,
            user_key=user_key,
            composio_api_key=composio_api_key,
            composio_reader_url=composio_reader_url,
            composio_actor_url=composio_actor_url,
            composio_user_id=composio_user_id,
            composio_account_ids=composio_account_ids,
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
