"""SafeClaw Brain — Embedder Service.

Polls postgres-obs every 30s for rows that need embeddings (observations, facts,
style_samples) and populates the pgvector sidecar tables. Also runs a tiny HTTP
server on port 8000 with `POST /embed` so other services (brain-api) can turn a
query string into a 384-dim vector.

Environment:
    DATABASE_URL                 postgres connection string for postgres-obs
    BRAIN_EMBEDDING_MODEL        sentence-transformers model name (default all-MiniLM-L6-v2)
    EMBEDDER_POLL_INTERVAL_SEC   seconds between poll cycles (default 30)
    EMBEDDER_BATCH_SIZE          max rows per poll per table (default 100)
    EMBEDDER_HTTP_PORT           HTTP server port (default 8000)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.rows import tuple_row
from sentence_transformers import SentenceTransformer

# ── Config ──────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")
MODEL_NAME = os.environ.get("BRAIN_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
POLL_INTERVAL_SEC = int(os.environ.get("EMBEDDER_POLL_INTERVAL_SEC", "30"))
BATCH_SIZE = int(os.environ.get("EMBEDDER_BATCH_SIZE", "100"))
HTTP_PORT = int(os.environ.get("EMBEDDER_HTTP_PORT", "8000"))
ENCODE_BATCH_SIZE = 32

if not DATABASE_URL:
    print("FATAL: DATABASE_URL environment variable is required", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [embedder] %(levelname)s %(message)s",
)
log = logging.getLogger("embedder")

# ── Shutdown flag ───────────────────────────────────────────────────────────

_shutdown = threading.Event()


def _handle_signal(signum: int, _frame: Any) -> None:
    log.info("received signal %d — finishing current batch then exiting", signum)
    _shutdown.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ── Model (loaded once, shared by poll loop + HTTP server) ──────────────────

log.info("loading sentence-transformers model %s ...", MODEL_NAME)
MODEL = SentenceTransformer(MODEL_NAME)
log.info("model loaded, embedding dim = %d", MODEL.get_sentence_embedding_dimension())

# Protect model inference across threads (poll loop + HTTP handler).
_model_lock = threading.Lock()


def encode_texts(texts: Sequence[str]) -> list[list[float]]:
    """Encode a batch of strings into 384-dim float lists. Thread-safe."""
    with _model_lock:
        vectors = MODEL.encode(
            list(texts),
            batch_size=ENCODE_BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
    return [vec.tolist() for vec in vectors]


def vector_literal(vec: Iterable[float]) -> str:
    """Format a float iterable as a pgvector literal: '[0.12,0.34,...]'."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


# ── Poll loop ───────────────────────────────────────────────────────────────

def _embed_observations(conn: psycopg.Connection) -> int:
    """Embed observations that have no row in observation_embeddings. Returns count."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT o.id, o.subject, o.summary
              FROM observations o
              LEFT JOIN observation_embeddings e ON o.id = e.observation_id
             WHERE e.observation_id IS NULL
             ORDER BY o.processed_at ASC
             LIMIT %s
            """,
            (BATCH_SIZE,),
        )
        rows = cur.fetchall()

    if not rows:
        return 0

    texts = [_compose_observation_text(subject, summary) for (_id, subject, summary) in rows]

    try:
        vectors = encode_texts(texts)
    except Exception as exc:  # pragma: no cover — runtime safety
        log.error("encode failed for observations batch: %s", exc)
        return 0

    inserted = 0
    with conn.cursor() as cur:
        for (obs_id, _subject, _summary), vec in zip(rows, vectors):
            try:
                cur.execute(
                    "INSERT INTO observation_embeddings (observation_id, embedding) "
                    "VALUES (%s, %s::vector) ON CONFLICT (observation_id) DO NOTHING",
                    (obs_id, vector_literal(vec)),
                )
                inserted += 1
            except Exception as exc:  # pragma: no cover
                log.warning("skip observation %s: %s", obs_id, exc)
                conn.rollback()
                continue
    conn.commit()
    return inserted


def _compose_observation_text(subject: str | None, summary: str | None) -> str:
    parts = [p for p in (subject, summary) if p]
    text = " ".join(parts).strip()
    return text if text else "(empty observation)"


def _embed_facts(conn: psycopg.Connection) -> int:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT id, fact
              FROM facts
             WHERE embedded = FALSE
             ORDER BY created_at ASC
             LIMIT %s
            """,
            (BATCH_SIZE,),
        )
        rows = cur.fetchall()

    if not rows:
        return 0

    texts = [fact or "(empty fact)" for (_id, fact) in rows]

    try:
        vectors = encode_texts(texts)
    except Exception as exc:
        log.error("encode failed for facts batch: %s", exc)
        return 0

    inserted = 0
    with conn.cursor() as cur:
        for (fact_id, _text), vec in zip(rows, vectors):
            try:
                cur.execute(
                    "INSERT INTO fact_embeddings (fact_id, embedding) "
                    "VALUES (%s, %s::vector) ON CONFLICT (fact_id) DO NOTHING",
                    (fact_id, vector_literal(vec)),
                )
                cur.execute("UPDATE facts SET embedded = TRUE WHERE id = %s", (fact_id,))
                inserted += 1
            except Exception as exc:
                log.warning("skip fact %s: %s", fact_id, exc)
                conn.rollback()
                continue
    conn.commit()
    return inserted


def _embed_style_samples(conn: psycopg.Connection) -> int:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT id, sample_text
              FROM style_samples
             WHERE embedded = FALSE
             ORDER BY created_at ASC
             LIMIT %s
            """,
            (BATCH_SIZE,),
        )
        rows = cur.fetchall()

    if not rows:
        return 0

    texts = [sample or "(empty sample)" for (_id, sample) in rows]

    try:
        vectors = encode_texts(texts)
    except Exception as exc:
        log.error("encode failed for style_samples batch: %s", exc)
        return 0

    inserted = 0
    with conn.cursor() as cur:
        for (sample_id, _text), vec in zip(rows, vectors):
            try:
                cur.execute(
                    "INSERT INTO style_sample_embeddings (sample_id, embedding) "
                    "VALUES (%s, %s::vector) ON CONFLICT (sample_id) DO NOTHING",
                    (sample_id, vector_literal(vec)),
                )
                cur.execute(
                    "UPDATE style_samples SET embedded = TRUE WHERE id = %s",
                    (sample_id,),
                )
                inserted += 1
            except Exception as exc:
                log.warning("skip style_sample %s: %s", sample_id, exc)
                conn.rollback()
                continue
    conn.commit()
    return inserted


def _embed_brain_docs(conn: psycopg.Connection) -> int:
    """Embed brain_docs that have no row in brain_doc_embeddings. Returns count inserted."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT id, title, summary
              FROM brain_docs
             WHERE embedded = FALSE
             ORDER BY indexed_at ASC
             LIMIT %s
            """,
            (BATCH_SIZE,),
        )
        rows = cur.fetchall()

    if not rows:
        return 0

    texts = [
        f"{title or ''}\n{summary or '(empty)'}".strip()[:1000]
        for (_id, title, summary) in rows
    ]

    try:
        vectors = encode_texts(texts)
    except Exception as exc:
        log.error("encode failed for brain_docs batch: %s", exc)
        return 0

    inserted = 0
    with conn.cursor() as cur:
        for (doc_id, _title, _summary), vec in zip(rows, vectors):
            try:
                cur.execute(
                    "INSERT INTO brain_doc_embeddings (doc_id, embedding) "
                    "VALUES (%s, %s::vector) ON CONFLICT (doc_id) DO NOTHING",
                    (doc_id, vector_literal(vec)),
                )
                cur.execute(
                    "UPDATE brain_docs SET embedded = TRUE WHERE id = %s",
                    (doc_id,),
                )
                inserted += 1
            except Exception as exc:
                log.warning("skip brain_doc %s: %s", doc_id, exc)
                conn.rollback()
                continue
    conn.commit()
    return inserted


def run_poll_loop() -> None:
    log.info("poll loop starting, interval=%ds, batch=%d", POLL_INTERVAL_SEC, BATCH_SIZE)
    while not _shutdown.is_set():
        try:
            with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
                n_obs = _embed_observations(conn)
                n_facts = _embed_facts(conn)
                n_style = _embed_style_samples(conn)
                n_brain = _embed_brain_docs(conn)
            if n_obs or n_facts or n_style or n_brain:
                log.info(
                    "embedded %d observations, %d facts, %d style samples, %d brain docs",
                    n_obs, n_facts, n_style, n_brain,
                )
        except Exception as exc:
            log.error("poll cycle failed: %s", exc)
        # Sleep in short slices so SIGTERM shuts us down quickly.
        for _ in range(POLL_INTERVAL_SEC):
            if _shutdown.is_set():
                break
            time.sleep(1)
    log.info("poll loop exited cleanly")


# ── HTTP server (POST /embed, GET /health) ──────────────────────────────────

class EmbedHandler(BaseHTTPRequestHandler):
    # Silence default logging; we use our own logger below.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        log.debug("http %s - %s", self.address_string(), format % args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path == "/health":
            self._send_json(200, {"ok": True, "model": MODEL_NAME})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/embed":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return

        length_header = self.headers.get("Content-Length")
        if not length_header or not length_header.isdigit():
            self._send_json(400, {"ok": False, "error": "content_length_required"})
            return

        length = int(length_header)
        if length <= 0 or length > 1_000_000:
            self._send_json(413, {"ok": False, "error": "payload_too_large"})
            return

        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            self._send_json(400, {"ok": False, "error": "text_required"})
            return

        if len(text) > 8000:
            self._send_json(413, {"ok": False, "error": "text_too_long", "limit": 8000})
            return

        try:
            vector = encode_texts([text])[0]
        except Exception as exc:
            log.error("embed HTTP call failed: %s", exc)
            self._send_json(500, {"ok": False, "error": "embed_failed"})
            return

        self._send_json(200, {"ok": True, "embedding": vector, "dim": len(vector)})


def run_http_server() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), EmbedHandler)
    log.info("http server listening on 0.0.0.0:%d", HTTP_PORT)

    def _stop_server() -> None:
        _shutdown.wait()
        log.info("shutting down http server")
        server.shutdown()

    threading.Thread(target=_stop_server, daemon=True).start()
    server.serve_forever()


# ── Entrypoint ──────────────────────────────────────────────────────────────

def main() -> int:
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    try:
        run_poll_loop()
    except KeyboardInterrupt:
        _shutdown.set()
    # Give the HTTP server a beat to wind down.
    http_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
