"""
SafeClaw — bootstrap_brain.py
=============================

The brain-seeding workhorse. This script is invoked by
``scripts/bootstrap-brain.sh`` and writes everything it learns into the
GBrain-backed ``safeclaw-brain`` service over its HTTP MCP endpoint. It needs
nothing but Python 3 stdlib + network access to ``safeclaw-brain`` (and,
optionally, Google's API client libraries for Drive attachment upload).

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
   - Writes a GBrain page via ``put_page`` slug ``people/<slug>``.
   - Optionally runs ``extract_facts`` over the person's email context so
     GBrain's hot-memory layer learns structured claims.

4. For each unique sender domain:

   - Writes a GBrain page via ``put_page`` slug ``companies/<domain>``.

5. For each *sent* message (``q=in:sent``):

   - Writes a GBrain page via ``put_page`` slug ``style/<id>`` tagged ``style``
     so the Actor can pull voice samples from day one. GBrain embeds the page
     itself (local Ollama) — this script never embeds anything.

6. Seeds a starter ``identity/soul`` page if one does not already exist.

7. Writes a human-readable summary report via ``put_page`` slug
   ``logs/bootstrap-<UTC-timestamp>``.

8. Tracks a watermark in ``brain/.bootstrap-state.json`` so re-runs only fetch
   messages newer than the last successful run. Use ``--reset`` to start over.

Why MCP and not the Gmail REST API directly
-------------------------------------------

The whole SafeClaw security story rests on never holding OAuth tokens on the
SafeClaw box. Composio holds them. The Reader MCP server in front of those
tokens has a strict toolkit allowlist (read-only), so even this bootstrap
script — which is presumably benign — cannot accidentally send or delete
anything. Belt and suspenders.

GBrain HTTP MCP contract
------------------------

Every write goes through the GBrain JSON-RPC ``tools/call`` endpoint::

    POST ${SAFECLAW_BRAIN_HTTP_URL}/mcp
    Authorization: Bearer ${SAFECLAW_BRAIN_ACTOR_TOKEN}
    Content-Type: application/json
    Accept: application/json
    {"jsonrpc":"2.0","id":N,"method":"tools/call",
     "params":{"name":"put_page","arguments":{"slug":"...","content":"..."}}}

The response is ``{"result":{"content":[{"type":"text","text":"<json>"}],
"isError":?},"jsonrpc":"2.0","id":N}`` — the operation's real return value is
the JSON-encoded string in ``result.content[0].text``.

CLI
---

::

    python bootstrap_brain.py                 # incremental
    python bootstrap_brain.py --dry-run       # parse + print, no writes
    python bootstrap_brain.py --reset         # clear watermark, full rerun
    python bootstrap_brain.py --days 30       # override BOOTSTRAP_DAYS
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
    people_pages_written: int = 0
    company_pages_written: int = 0
    facts_extracted: int = 0
    page_errors: int = 0
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


class GBrainError(RuntimeError):
    pass


class GBrainClient:
    """Authenticated client for the GBrain ``safeclaw-brain`` HTTP MCP endpoint.

    Talks JSON-RPC ``tools/call`` to ``${base_url}/mcp`` with a static
    ``Authorization: Bearer <token>``. GBrain handles chunking + embedding
    (local Ollama) internally — this client only ever writes pages, facts and
    timeline entries; it never embeds anything itself.

    Construct via :meth:`from_env` so the fail-fast env checks live in one place.
    """

    def __init__(self, base_url: str, token: str):
        self.mcp_url = base_url.rstrip("/") + "/mcp"
        self.headers = {
            "Authorization": f"Bearer {token}",
            # GBrain's HTTP transport accepts JSON; it does not stream SSE for
            # tools/call, but we advertise both to be safe.
            "Accept": "application/json, text/event-stream",
            "User-Agent": "SafeClaw-Bootstrap/2.0",
        }
        self._rpc_id = 0

    @classmethod
    def from_env(cls) -> "GBrainClient":
        """Build from ``SAFECLAW_BRAIN_HTTP_URL`` + ``SAFECLAW_BRAIN_ACTOR_TOKEN``.

        Fails fast (per the repo convention) with a clear message if either is
        missing or still a placeholder.
        """
        base_url = os.environ.get("SAFECLAW_BRAIN_HTTP_URL", "").strip()
        token = os.environ.get("SAFECLAW_BRAIN_ACTOR_TOKEN", "").strip()
        if not base_url:
            raise GBrainError(
                "SAFECLAW_BRAIN_HTTP_URL is not set. Point it at the GBrain "
                "service, e.g. http://safeclaw-brain:3131"
            )
        if not token or token in ("__FILL_IN__", "__GENERATE__", "__MINTED__"):
            raise GBrainError(
                "SAFECLAW_BRAIN_ACTOR_TOKEN is not set (or still a placeholder). "
                "Mint a read+write token with 'gbrain auth create' and pass it "
                "through the environment."
            )
        return cls(base_url, token)

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """JSON-RPC ``tools/call`` against GBrain. Returns the parsed op result.

        GBrain wraps the operation's return value as a JSON-encoded string in
        ``result.content[0].text``. We unwrap + json.loads it so callers see
        the operation's native return shape (a dict, list, etc.).
        """
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        resp = _http_post_json(self.mcp_url, self.headers, body)
        if resp.get("error"):
            raise GBrainError(f"GBrain MCP error for tool {tool_name}: {resp['error']}")
        result = resp.get("result") or {}
        content = result.get("content")
        text = ""
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text", "") or ""
        parsed: Any = None
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
        if result.get("isError"):
            raise GBrainError(f"GBrain tool {tool_name} returned an error: {parsed or text}")
        return parsed

    # ── High-level helpers ──────────────────────────────────────────────

    def put_page(self, slug: str, content: str) -> Any:
        """Create/update a page. GBrain chunks + embeds it server-side."""
        return self.call_tool("put_page", {"slug": slug, "content": content})

    def get_page(self, slug: str) -> Any | None:
        """Read a page by slug. Returns None when the page does not exist."""
        try:
            return self.call_tool("get_page", {"slug": slug})
        except GBrainError:
            # get_page raises (isError) when the slug is unknown; treat as absent.
            return None

    def extract_facts(self, turn_text: str, *, entity_hints: list[str] | None = None) -> Any:
        """Extract structured facts from a chunk of text into GBrain hot memory."""
        args: dict[str, Any] = {"turn_text": turn_text}
        if entity_hints:
            args["entity_hints"] = entity_hints
        return self.call_tool("extract_facts", args)

    def add_timeline_entry(
        self, slug: str, *, date: str, summary: str, detail: str = "", source: str = ""
    ) -> Any:
        """Append a timeline entry (date must be strict YYYY-MM-DD)."""
        args: dict[str, Any] = {"slug": slug, "date": date, "summary": summary}
        if detail:
            args["detail"] = detail
        if source:
            args["source"] = source
        return self.call_tool("add_timeline_entry", args)


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


class DriveActorError(Exception):
    """Raised when the Drive service-account client fails."""


class DriveActor:
    """Drive client backed by a Google service account.

    Mirrors the surface of ``mcp-tools/drive-api/main.py`` so the actor flow
    (real-time, per-attachment) and the bootstrap flow (historical, batched)
    behave identically against Drive.

    Reads the service-account JSON key from ``GDRIVE_CREDENTIALS_PATH``
    (the bootstrap container mounts it at ``/repo/config/drive_credentials.json``).
    No OAuth, no token refresh, no vendor in the upload path — see Step 5 of
    the onboarding setup page for how the operator generates the key.
    """

    def __init__(self, credentials_path: str):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover — embedder image carries these
            raise DriveActorError(
                "google-api-python-client / google-auth not installed in this "
                "container. Rebuild the embedder image (services/embedder/"
                "requirements.txt was updated)."
            ) from exc

        if not Path(credentials_path).exists():
            raise DriveActorError(
                f"Drive credentials file not found at {credentials_path!r}. "
                "Complete Step 5 of the onboarding setup (Google Drive service "
                "account JSON) before running bootstrap."
            )

        creds = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def find_or_create_folder(
        self,
        *,
        folder_path: list[str],
        folder_cache: dict[str, str],
    ) -> str:
        """Walk ``folder_path`` (top-down), creating any missing segment.

        Returns the leaf folder's Drive ID. Cached per-process so a run with
        100 attachments to the same monthly folder makes 1 lookup, not 100.
        """
        cache_key = "/".join(folder_path)
        if cache_key in folder_cache:
            return folder_cache[cache_key]

        parent_id: str | None = None
        running_path: list[str] = []
        for segment in folder_path:
            running_path.append(segment)
            running_key = "/".join(running_path)
            if running_key in folder_cache:
                parent_id = folder_cache[running_key]
                continue

            esc = segment.replace("\\", "\\\\").replace("'", "\\'")
            q = (
                f"name = '{esc}' "
                f"and mimeType = 'application/vnd.google-apps.folder' "
                f"and trashed = false"
            )
            if parent_id:
                q += f" and '{parent_id}' in parents"
            result = (
                self.service.files()
                .list(q=q, fields="files(id,name)", spaces="drive")
                .execute()
            )
            files = result.get("files", [])

            if files:
                new_id = files[0]["id"]
            else:
                meta: dict[str, Any] = {
                    "name": segment,
                    "mimeType": "application/vnd.google-apps.folder",
                }
                if parent_id:
                    meta["parents"] = [parent_id]
                folder = self.service.files().create(body=meta, fields="id").execute()
                new_id = folder["id"]

            if not new_id:
                raise DriveActorError(
                    f"could not create or find Drive folder {segment!r} under {parent_id}"
                )
            folder_cache[running_key] = new_id
            parent_id = new_id

        if parent_id is None:
            raise DriveActorError(f"empty folder path {folder_path!r}")
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
        import io
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(
            io.BytesIO(content),
            mimetype=mime_type or "application/octet-stream",
            resumable=True,
        )
        meta = {"name": filename, "parents": [parent_folder_id]}
        uploaded = (
            self.service.files()
            .create(body=meta, media_body=media, fields="id,name,webViewLink")
            .execute()
        )
        return {
            "file_id": str(uploaded.get("id") or ""),
            "web_view_link": str(uploaded.get("webViewLink") or ""),
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


# ─── Attachment rendering helper ──────────────────────────────────────────
#
# Used by build_person_page to render the per-person "Attachments" section
# from the metadata captured during Phase A (and the Drive URLs filled in by
# Phase A.5).


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


# ─── GBrain page builders ────────────────────────────────────────────────────
#
# Everything the bootstrap learns is persisted to the GBrain ``safeclaw-brain``
# service as markdown pages via put_page. GBrain chunks + embeds each page
# server-side (local Ollama), so we never embed anything here. Each builder
# returns the markdown body (with YAML frontmatter) that put_page expects.


def _yaml_escape(value: str) -> str:
    """Quote a scalar for a single-line YAML frontmatter value."""
    v = (value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{v}"'


def build_person_page(
    *,
    email: str,
    name: str,
    domain: str,
    frequency: int,
    first_seen: dt.datetime | None,
    last_seen: dt.datetime | None,
    attachments: list[dict[str, Any]] | None,
) -> str:
    """Render the markdown body for a ``people/<slug>`` page."""
    first = first_seen.date().isoformat() if first_seen else "?"
    last = last_seen.date().isoformat() if last_seen else "?"
    relationship = relationship_label(frequency)
    display = name or email
    lines = [
        "---",
        f"title: {_yaml_escape(display)}",
        "type: person",
        f"email: {_yaml_escape(email)}",
        f"domain: {_yaml_escape(domain)}",
        f"relationship: {relationship}",
        f"message_count: {frequency}",
        f"first_seen: {first}",
        f"last_seen: {last}",
        "tags: [person, contact]",
        "source: gmail-bootstrap",
        "---",
        "",
        f"# {display}",
        "",
        f"- Email: {email}",
    ]
    if domain:
        lines.append(f"- Company: [[companies/{domain}]]")
    lines.extend(
        [
            f"- Relationship: {relationship} ({frequency} messages in window)",
            f"- First seen: {first}",
            f"- Last seen: {last}",
        ]
    )
    att_records = attachments or []
    lines.extend(["", "## Attachments", "", _format_attachments_block(att_records)])
    lines.extend(["", "## Notes", ""])
    return "\n".join(lines) + "\n"


def build_company_page(
    *,
    domain: str,
    people_emails: Iterable[str],
    first_seen: dt.datetime | None,
    last_seen: dt.datetime | None,
) -> str:
    """Render the markdown body for a ``companies/<domain>`` page."""
    first = first_seen.date().isoformat() if first_seen else "?"
    last = last_seen.date().isoformat() if last_seen else "?"
    people = sorted(set(people_emails))
    lines = [
        "---",
        f"title: {_yaml_escape(domain)}",
        "type: company",
        f"domain: {_yaml_escape(domain)}",
        f"contact_count: {len(people)}",
        f"first_seen: {first}",
        f"last_seen: {last}",
        "tags: [company]",
        "source: gmail-bootstrap",
        "---",
        "",
        f"# {domain}",
        "",
        f"- Domain: {domain}",
        f"- First seen: {first}",
        f"- Last seen: {last}",
        "",
        "## Contacts",
        "",
    ]
    if people:
        for em in people:
            lines.append(f"- [[people/{slugify_email(em)}]] ({em})")
    else:
        lines.append("- (none seen)")
    lines.extend(["", "## Notes", ""])
    return "\n".join(lines) + "\n"


def build_style_page(
    *,
    sample_id: str,
    msg: "GmailMessage",
    relationship: str,
) -> str:
    """Render the markdown body for a ``style/<id>`` voice-sample page."""
    recipients = ", ".join(msg.recipient_emails[:5])
    date = msg.received_at.date().isoformat()
    subject = msg.subject or "(no subject)"
    body = (msg.body_text or "").strip()
    lines = [
        "---",
        f"title: {_yaml_escape('Voice sample — ' + subject)}",
        "type: style_sample",
        "tags: [style, voice]",
        f"recipient_relationship: {relationship}",
        f"sent_at: {date}",
        f"subject: {_yaml_escape(subject)}",
        f"recipients: {_yaml_escape(recipients)}",
        "source: gmail-bootstrap",
        f"message_id: {_yaml_escape(msg.message_id)}",
        "---",
        "",
        f"# Voice sample — {subject}",
        "",
        f"Sent {date} to {recipients or '(unknown)'} — relationship: {relationship}",
        "",
        "## Body",
        "",
        body,
        "",
    ]
    return "\n".join(lines) + "\n"


STARTER_SOUL = """\
---
title: "Soul"
type: identity
tags: [identity, soul]
source: bootstrap
---

# Soul

This is the pinned identity page for the SafeClaw operator. The Actor reads it
(`get_page(slug="identity/soul")`) for tone, principles, and blueprint before
drafting on your behalf.

## Who I am

_(Edit this — describe yourself in a few sentences.)_

## Principles

- _(How you like to communicate, what you value, what you never do.)_

## Voice

- _(Greeting / sign-off preferences, formality, length.)_

## Blueprint

- _(Current goals and priorities.)_

> Seeded by the SafeClaw bootstrap. The Reflector proposes revisions here,
> queued for your approval — but you can edit it directly any time.
"""


def style_sample_text(msg: "GmailMessage") -> str | None:
    """Return a sent-message body worth saving as a style sample, else None."""
    text = (msg.body_text or "").strip()
    if not text:
        return None
    if len(text.split()) < MIN_STYLE_SAMPLE_WORDS:
        return None
    return text


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
    gbrain: "GBrainClient | None",
    composio_api_key: str,
    composio_reader_url: str,
    drive_credentials_path: str | None,
    composio_user_id: str | None,
    composio_account_ids: list[str],
    extract_facts_enabled: bool,
    days: int,
    dry_run: bool,
    reset: bool,
) -> int:
    """Top-level entry. Returns process exit code."""
    started_at = utcnow()
    account_display = ", ".join(composio_account_ids) if composio_account_ids else "(default)"
    print(f"SafeClaw bootstrap_brain — UTC {started_at.isoformat()}")
    print(f"  brain dir : {brain_dir}")
    print(f"  gbrain    : {gbrain.mcp_url if gbrain else '(dry-run, none)'}")
    print(f"  days back : {days}")
    print(f"  dry run   : {dry_run}")
    print(f"  reset     : {reset}")
    print(f"  facts     : {extract_facts_enabled}")
    print(f"  accounts  : {account_display}")
    print()

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
    # Skipped silently if no Drive credentials configured — the metadata still
    # lands in brain/People/<slug>.md, just without Drive links. Uses a Google
    # service account directly (google-api-python-client), not Composio — the
    # actor flow at mcp-tools/drive-api/main.py uses the same credentials and
    # the same Drive layout.
    if pending_attachments and drive_credentials_path and not dry_run:
        print(f"Phase A.5 — uploading {len(pending_attachments)} attachments to Google Drive...")
        att_state = load_attachments_state(brain_dir)
        try:
            actor = DriveActor(drive_credentials_path)
        except DriveActorError as exc:
            print(f"  [error] Drive client init failed: {exc}")
            print(f"  [error] Skipping Drive upload for {len(pending_attachments)} attachments. "
                  "Metadata is still recorded in brain/People/<slug>.md.")
            actor = None
        folder_cache: dict[str, str] = {}
        # Drive layout: SafeClaw Inbox / <YYYY-MM> / <sender-domain> / <filename>
        DRIVE_ROOT = "SafeClaw Inbox"

        # Quick precondition probe: if GMAIL_FETCH_ATTACHMENT isn't in the
        # MCP toolkit, fail fast with a clear message instead of looping
        # over every attachment producing identical "not found" errors.
        toolkit_ok = actor is not None
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
                # download tool (or the Drive client failed to init) — don't
                # repeat the error for every file.
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
            except DriveActorError as exc:
                print(f"  [warn] folder resolve failed for {'/'.join(folder_path)}: {exc}")
                continue
            except Exception as exc:  # google-api-client raises HttpError, etc.
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
            except DriveActorError as exc:
                print(f"  [warn] upload failed for {record['filename']}: {exc}")
                continue
            except Exception as exc:  # google-api-client raises HttpError, etc.
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
    elif pending_attachments and not drive_credentials_path:
        print(
            f"Phase A.5 — skipping Drive upload "
            f"({len(pending_attachments)} attachments would have been uploaded). "
            "Set GDRIVE_CREDENTIALS_PATH (or complete Step 5 of onboarding) to enable."
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

    # ── Phase C: write pages to GBrain ────────────────────────────────────
    # People, companies, style samples, and a starter Soul all become GBrain
    # pages via put_page. GBrain chunks + embeds them server-side — we never
    # embed anything here.
    print("Phase C — writing pages to GBrain (safeclaw-brain)...")

    # Build the list of people / companies we discovered.
    people = sorted(person_name.keys())
    domains = sorted(domain_to_people.keys())

    if dry_run:
        print(f"  [DRY] would write {len(people)} people pages -> people/<slug>")
        print(f"  [DRY] would write {len(domains)} company pages -> companies/<domain>")
        n_style = sum(1 for m in sent_samples if style_sample_text(m))
        print(f"  [DRY] would write {n_style} style sample pages -> style/<id>")
        if extract_facts_enabled:
            print(f"  [DRY] would run extract_facts for {len(people)} people")
        print("  [DRY] would seed identity/soul if absent")
        print()
        print(f"DRY RUN — no writes performed. Inbound={stats.emails_processed}, sent={stats.sent_processed}")
        return 0

    assert gbrain is not None  # guaranteed by main() when not dry_run

    # 1) Seed the Soul page if absent. We do NOT clobber an existing one.
    if gbrain.get_page("identity/soul") is None:
        try:
            gbrain.put_page("identity/soul", STARTER_SOUL)
            print("  seeded identity/soul")
        except GBrainError as exc:
            stats.page_errors += 1
            print(f"  [warn] could not seed identity/soul: {exc}")
    else:
        print("  identity/soul already exists — leaving it as-is")

    # 2) People pages (+ optional fact extraction).
    for email in people:
        slug = f"people/{slugify_email(email)}"
        domain = domain_of(email)
        page = build_person_page(
            email=email,
            name=person_name.get(email, ""),
            domain=domain,
            frequency=stats.contact_frequency.get(email, 0),
            first_seen=person_first_seen.get(email),
            last_seen=person_last_seen.get(email),
            attachments=person_attachments.get(email),
        )
        try:
            gbrain.put_page(slug, page)
            stats.people_pages_written += 1
        except GBrainError as exc:
            stats.page_errors += 1
            print(f"  [warn] put_page failed for {slug}: {exc}")
            continue

        if extract_facts_enabled:
            # Feed the person page body to GBrain's fact extractor so the hot
            # memory layer learns structured claims. Best-effort; never fatal.
            try:
                r = gbrain.extract_facts(page, entity_hints=[slug])
                if isinstance(r, dict):
                    stats.facts_extracted += int(r.get("inserted") or 0)
            except GBrainError as exc:
                print(f"  [warn] extract_facts failed for {slug}: {exc}")

        if stats.people_pages_written % 50 == 0:
            print(f"  ...wrote {stats.people_pages_written} people pages")

    # 3) Company pages — one per sender domain.
    for domain in domains:
        slug = f"companies/{domain}"
        page = build_company_page(
            domain=domain,
            people_emails=domain_to_people.get(domain, set()),
            first_seen=domain_first_seen.get(domain),
            last_seen=domain_last_seen.get(domain),
        )
        try:
            gbrain.put_page(slug, page)
            stats.company_pages_written += 1
        except GBrainError as exc:
            stats.page_errors += 1
            print(f"  [warn] put_page failed for {slug}: {exc}")

    # 4) Style sample pages — sent mail bodies tagged `style` so the Actor
    #    can pull voice samples. Slug is deterministic per message id so
    #    re-runs upsert rather than duplicate.
    for msg in sent_samples:
        text = style_sample_text(msg)
        if not text:
            continue
        primary_recipient = msg.recipient_emails[0] if msg.recipient_emails else ""
        relationship = relationship_label(stats.contact_frequency.get(primary_recipient, 0))
        sample_id = safe_filename(msg.message_id) or uuid.uuid4().hex
        slug = f"style/{sample_id}"
        page = build_style_page(sample_id=sample_id, msg=msg, relationship=relationship)
        try:
            gbrain.put_page(slug, page)
            stats.style_samples_saved += 1
        except GBrainError as exc:
            stats.page_errors += 1
            print(f"  [warn] put_page failed for {slug}: {exc}")

    print(
        f"  done. people={stats.people_pages_written} companies={stats.company_pages_written} "
        f"style={stats.style_samples_saved} facts={stats.facts_extracted} errors={stats.page_errors}"
    )
    print()

    # ── Phase D: report page + watermark ──────────────────────────────────
    finished_at = utcnow()
    elapsed = (finished_at - started_at).total_seconds()
    report_slug = f"logs/bootstrap-{started_at.strftime('%Y%m%d-%H%M%S')}"
    top_contacts = sorted(stats.contact_frequency.items(), key=lambda kv: -kv[1])[:10]
    report_lines = [
        "---",
        f"title: {_yaml_escape('Bootstrap report ' + started_at.strftime('%Y-%m-%d %H:%M:%S'))}",
        "type: log",
        "tags: [bootstrap, log]",
        "source: gmail-bootstrap",
        "---",
        "",
        "# SafeClaw — Bootstrap Report",
        "",
        f"- run started: `{started_at.isoformat()}`",
        f"- run finished: `{finished_at.isoformat()}`",
        f"- elapsed: `{elapsed:.1f}s`",
        f"- days scanned: `{days}`",
        f"- inbound emails processed: `{stats.emails_processed}`",
        f"- sent emails processed: `{stats.sent_processed}`",
        f"- people pages written: `{stats.people_pages_written}`",
        f"- company pages written: `{stats.company_pages_written}`",
        f"- style samples saved: `{stats.style_samples_saved}`",
        f"- facts extracted: `{stats.facts_extracted}`",
        f"- page write errors: `{stats.page_errors}`",
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
    report_lines.append("")
    try:
        gbrain.put_page(report_slug, "\n".join(report_lines) + "\n")
    except GBrainError as exc:
        stats.page_errors += 1
        print(f"  [warn] could not write report page {report_slug}: {exc}")

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
    print(f"   Wrote     {stats.people_pages_written} People pages    -> people/<slug>")
    print(f"             {stats.company_pages_written} Company pages   -> companies/<domain>")
    print(f"             {stats.style_samples_saved} Style samples    -> style/<id>")
    if stats.facts_extracted:
        print(f"             {stats.facts_extracted} Facts extracted -> GBrain hot memory")
    if stats.attachments_seen:
        print(f"             {stats.attachments_seen} Attachments seen "
              f"({stats.attachments_uploaded} uploaded to Drive, "
              f"{stats.attachments_skipped} skipped)")
    print()
    print("Next steps:")
    print("   1. Read identity/soul (get_page slug=\"identity/soul\") and edit it (1 min)")
    print("   2. Search the brain to spot-check people/ and companies/ pages")
    print("   3. The Actor pulls voice samples from style/ pages automatically")
    print(bar)
    print(f"  Report page: {report_slug}")
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
        composio_api_key = os.environ["COMPOSIO_API_KEY"]
        composio_reader_url = os.environ["COMPOSIO_READER_MCP_URL"]
        composio_user_id = os.environ.get("COMPOSIO_USER_ID") or None
    except KeyError as missing:
        print(f"ERROR: required env var {missing} is not set.", file=sys.stderr)
        return 1

    # GBrain client — built from SAFECLAW_BRAIN_HTTP_URL + SAFECLAW_BRAIN_ACTOR_TOKEN.
    # Fail fast (per repo convention) when either is missing, EXCEPT for --dry-run
    # which never writes and so doesn't need a live brain.
    gbrain: GBrainClient | None = None
    if not args.dry_run:
        try:
            gbrain = GBrainClient.from_env()
        except GBrainError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # extract_facts can be disabled to keep runs fast / cheap (it calls an LLM
    # inside GBrain per page). On by default; set BOOTSTRAP_EXTRACT_FACTS=0 off.
    extract_facts_enabled = os.environ.get("BOOTSTRAP_EXTRACT_FACTS", "1").strip() not in (
        "0",
        "false",
        "no",
        "",
    )

    # Optional — drives Phase A.5 (Drive upload). If absent, attachment
    # metadata still lands in brain/People/<slug>.md without Drive links.
    # Default mirrors scripts/bootstrap-brain.sh's volume mount; the operator's
    # credentials JSON is generated by Step 5 of the onboarding setup.
    drive_credentials_path = (
        os.environ.get("GDRIVE_CREDENTIALS_PATH")
        or "/repo/config/drive_credentials.json"
    )
    if not Path(drive_credentials_path).exists():
        drive_credentials_path = None

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
            gbrain=gbrain,
            composio_api_key=composio_api_key,
            composio_reader_url=composio_reader_url,
            drive_credentials_path=drive_credentials_path,
            composio_user_id=composio_user_id,
            composio_account_ids=composio_account_ids,
            extract_facts_enabled=extract_facts_enabled,
            days=days,
            dry_run=args.dry_run,
            reset=args.reset,
        )
    except ComposioMCPError as e:
        print(f"ERROR: Composio MCP call failed — {e}", file=sys.stderr)
        return 2
    except GBrainError as e:
        print(f"ERROR: GBrain MCP call failed — {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
