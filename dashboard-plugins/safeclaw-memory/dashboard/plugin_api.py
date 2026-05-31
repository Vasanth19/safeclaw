"""SafeClaw Memory — dashboard plugin backend.

Mounted at /api/plugins/safeclaw-memory/ by the Hermes dashboard plugin system.

Pulls the brain's pages from GBrain (the hybrid vector + knowledge-graph store)
over its MCP endpoint and shapes them into a force-graph payload:

    nodes = pages (+ one hub per page type)
    links = page → its type hub  (+ explicit page→page links when present)

GBrain has thousands of pages but few explicit links, so the type hubs give the
constellation its structure: each page is a star orbiting its category. Color
encodes type; node size encodes how connected a node is.

Config (env):
    GBRAIN_MCP_URL   default http://localhost:3131/mcp
    GBRAIN_TOKEN     bearer token (already present in the SafeClaw env)
    SAFECLAW_MEMORY_LIMIT   max pages to pull (default 600)
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections import Counter

from fastapi import APIRouter, HTTPException

router = APIRouter()

GBRAIN_URL = os.environ.get("GBRAIN_MCP_URL", "http://localhost:3131/mcp")

# Stable palette keyed by page type. Anything unmapped falls back to GREY.
TYPE_COLORS = {
    "project": "#3ddc97",
    "decision": "#a78bfa",
    "decisions": "#a78bfa",
    "adr": "#a78bfa",
    "concept": "#60a5fa",
    "observation": "#f472b6",
    "note": "#7be0c8",
    "diary": "#f5b14c",
    "gotcha": "#ef5a5a",
    "pattern": "#fbbf24",
    "sop": "#34d399",
    "person": "#e879f9",
    "slack": "#38bdf8",
    "reference": "#94a3b8",
    "migrated-drawer": "#475569",
}
GREY = "#8a93a3"
HUB = "#e6ebf2"


def _mcp_call(tool: str, arguments: dict) -> object:
    """Call a GBrain MCP tool over streamable HTTP and return its parsed result.

    The server replies with a single SSE frame:  `event: message\\n data: {…}`.
    We pull the `data:` line, decode the JSON-RPC envelope, then decode the
    tool's text payload (GBrain returns its result as a JSON string).
    """
    token = os.environ.get("GBRAIN_TOKEN", "")
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }).encode()
    req = urllib.request.Request(
        GBRAIN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
    except Exception as exc:  # noqa: BLE001 — surface a clean 502 to the UI
        raise HTTPException(502, f"GBrain unreachable at {GBRAIN_URL}: {exc}")

    payload = None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = json.loads(line[5:].strip())
            break
    if payload is None:  # not SSE-framed — try plain JSON
        payload = json.loads(raw)

    if "error" in payload:
        raise HTTPException(502, f"GBrain error: {payload['error']}")
    content = payload.get("result", {}).get("content", [])
    if content and content[0].get("type") == "text":
        return json.loads(content[0]["text"])
    return content


def _fetch_type(page_type: str, max_total: int = 2000) -> list[dict]:
    """Fetch every page of one type, working around GBrain's 100-row cap.

    `list_pages` returns at most 100 rows and has no offset, so we cursor on
    `updated_at` (ascending): grab 100, remember the last timestamp, ask for
    everything strictly after it, repeat. Dedupe by slug and stop when a batch
    is short or adds nothing new — both guard against timestamp collisions in
    bulk-imported pages.
    """
    out: dict[str, dict] = {}
    cursor: str | None = None
    while len(out) < max_total:
        args: dict = {"type": page_type, "limit": 100, "sort": "updated_asc"}
        if cursor:
            args["updated_after"] = cursor
        batch = _mcp_call("list_pages", args)
        if not isinstance(batch, list) or not batch:
            break
        added = 0
        for p in batch:
            slug = p.get("slug")
            if slug and slug not in out:
                out[slug] = p
                added += 1
        cursor = batch[-1].get("updated_at")
        if len(batch) < 100 or added == 0:
            break
    return list(out.values())


@router.get("/health")
async def health():
    """Cheap reachability check the UI can use before rendering the graph."""
    try:
        _mcp_call("list_pages", {"limit": 1})
        return {"ok": True, "gbrain": GBRAIN_URL}
    except HTTPException as exc:
        return {"ok": False, "gbrain": GBRAIN_URL, "detail": exc.detail}


@router.get("/graph")
async def graph(limit: int | None = None, include_drawer: bool = False):
    """Return the brain as a force-graph payload.

    `include_drawer=false` (default) hides the ~560 legacy `migrated-drawer`
    pages so the meaningful, hand-authored knowledge stands out.
    """
    # Fetch per type so the 100-row cap never truncates us: each type is paged
    # to completion via _fetch_type. `limit` (if given) still bounds the total.
    stats = _mcp_call("get_stats", {})
    by_type = stats.get("pages_by_type", {}) if isinstance(stats, dict) else {}
    wanted = [t for t in by_type if include_drawer or t != "migrated-drawer"]

    pages: list[dict] = []
    for t in sorted(wanted):
        pages.extend(_fetch_type(t))
    if limit:
        pages = pages[:limit]

    nodes: list[dict] = []
    links: list[dict] = []
    type_counts: Counter = Counter()

    # One hub node per type — the gravity well each page orbits.
    types = sorted({(p.get("type") or "note") for p in pages})
    for t in types:
        nodes.append({
            "id": f"type::{t}",
            "name": t,
            "kind": "type",
            "type": t,
            "color": TYPE_COLORS.get(t, GREY),
            "val": 14,
        })

    for p in pages:
        slug = p.get("slug")
        if not slug:
            continue
        t = p.get("type") or "note"
        type_counts[t] += 1
        nodes.append({
            "id": slug,
            "name": p.get("title") or slug,
            "kind": "page",
            "type": t,
            "color": TYPE_COLORS.get(t, GREY),
            "updated": p.get("updated_at"),
            "val": 2,
        })
        links.append({"source": slug, "target": f"type::{t}", "kind": "type"})

    # A faint core that ties the type hubs together into one constellation.
    nodes.append({"id": "brain::core", "name": "SafeClaw Brain", "kind": "core",
                  "type": "core", "color": "#3ddc97", "val": 40})
    for t in types:
        links.append({"source": f"type::{t}", "target": "brain::core", "kind": "core"})

    return {
        "nodes": nodes,
        "links": links,
        "legend": [
            {"type": t, "color": TYPE_COLORS.get(t, GREY), "count": type_counts[t]}
            for t in types
        ],
        "stats": {
            "pages": sum(type_counts.values()),
            "types": len(types),
            "drawer_hidden": not include_drawer,
        },
    }
