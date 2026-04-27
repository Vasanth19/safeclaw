"""In-memory SSE event publisher for SafeClaw provisioning.

Design choice (deliberate): we keep this in-memory rather than reaching for
Redis/Flask-SSE. The SafeClaw onboarding webapp runs as ONE process on ONE
customer VPS, with at most a handful of concurrent installs (typically 1).
Adding Redis as a SaaS-on-VPS dependency just to ferry a few JSON dicts
between threads is overkill.

Trade-offs accepted:
  * Single-process only. If we ever scale gunicorn workers > 1 for SSE,
    we'll need to revisit this (use --preload + shared memory, or Redis).
    For that reason, the gunicorn invocation in Dockerfile uses --threads,
    not extra --workers, for serving SSE.
  * State lost on webapp restart. If the customer refreshes after the
    container restarts mid-provision, they'll see "install not found".
    Acceptable for v1 — provision either finished (state on disk) or the
    customer just retries.

Public API:
  registry.create(install_id)           -> Install
  registry.get(install_id)              -> Install | None
  install.publish(event_dict)           -> None       # producer side
  install.subscribe()                   -> generator  # SSE consumer side
  install.snapshot()                    -> list[dict] # /api/status fallback
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Iterator


class Install:
    """Tracks one provision run's event stream."""

    # Cap event history at 500 entries — way more than any real provision
    # will produce, but bounded so a hung install can't OOM the box.
    MAX_EVENTS = 500

    def __init__(self, install_id: str) -> None:
        self.install_id = install_id
        self.created_at = time.time()
        self._events: deque[dict] = deque(maxlen=self.MAX_EVENTS)
        self._cond = threading.Condition()
        self._closed = False

    def publish(self, event: dict) -> None:
        """Append an event and wake all SSE subscribers."""
        if not isinstance(event, dict):
            raise TypeError("event must be a dict")
        # Copy so the caller can mutate their dict freely afterwards.
        event = dict(event)
        event.setdefault("ts", time.time())
        with self._cond:
            self._events.append(event)
            self._cond.notify_all()

    def close(self) -> None:
        """Signal terminal state. Subscribers will receive remaining events
        and then the generator returns."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def is_closed(self) -> bool:
        return self._closed

    def snapshot(self) -> list[dict]:
        """Return a point-in-time copy of all events. Used by the polling
        fallback at /api/status."""
        with self._cond:
            return list(self._events)

    def subscribe(self, last_index: int = 0) -> Iterator[str]:
        """Yield SSE-formatted event strings as they arrive.

        last_index lets a reconnecting client skip events it already saw
        (sent via the standard `Last-Event-ID` header — see app.py).
        """
        idx = last_index
        # Heartbeat keeps proxies (Caddy, nginx) from closing idle SSE.
        last_heartbeat = time.time()
        heartbeat_interval = 15.0

        while True:
            with self._cond:
                # Drain any events past idx.
                events = list(self._events)
                if idx < len(events):
                    pending = events[idx:]
                    idx = len(events)
                else:
                    pending = []
                    if self._closed:
                        return
                    # Wait for either a new event or heartbeat tick.
                    self._cond.wait(timeout=heartbeat_interval)

            for ev in pending:
                # The id: line allows clients to resume mid-stream.
                yield f"id: {idx - len(pending) + pending.index(ev) + 1}\n"
                yield f"event: {ev.get('phase', 'progress')}\n"
                yield f"data: {json.dumps(ev)}\n\n"

            now = time.time()
            if now - last_heartbeat >= heartbeat_interval:
                yield ": keepalive\n\n"
                last_heartbeat = now


class _Registry:
    """Process-global registry of in-flight installs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._installs: dict[str, Install] = {}

    def create(self, install_id: str) -> Install:
        with self._lock:
            if install_id in self._installs:
                raise ValueError(f"install {install_id} already exists")
            install = Install(install_id)
            self._installs[install_id] = install
            return install

    def get(self, install_id: str) -> Install | None:
        with self._lock:
            return self._installs.get(install_id)

    def remove(self, install_id: str) -> None:
        with self._lock:
            self._installs.pop(install_id, None)


registry = _Registry()
