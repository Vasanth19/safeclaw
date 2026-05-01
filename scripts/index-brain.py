"""SafeClaw Brain Indexer — feeds brain .md files into brain_docs for vectorisation.

Walks the brain directory, extracts summaries from each .md file, and upserts
into brain_docs. The embedder polls brain_docs WHERE embedded = FALSE to fill
brain_doc_embeddings. Full .md files stay on disk; only summaries go to the DB.

Usage:
    python scripts/index-brain.py [--brain-dir PATH] [--dry-run] [--verbose]

Environment:
    BRAIN_OBS_DATABASE_URL   postgres connection string for postgres-obs
    BRAIN_USER_KEY           user key (default: "primary")
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
from pathlib import Path
from typing import Iterator

import psycopg

# ── Config ───────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("BRAIN_OBS_DATABASE_URL")
USER_KEY = os.environ.get("BRAIN_USER_KEY", "primary")

SUMMARY_BODY_CHARS = 400
SUMMARY_MAX_CHARS = 800

# Map directory name prefixes to doc_type.
# Checked in order — first match wins.
DIR_TYPE_MAP: list[tuple[str, str]] = [
    ("People", "person"),
    ("Companies", "company"),
    ("4 - Meetings", "meeting"),
    ("5 - Projects", "project"),
    ("3 - Daily Journal", "journal"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [index-brain] %(levelname)s %(message)s",
)
log = logging.getLogger("index-brain")


# ── Summary extraction ────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_MARKDOWN_NOISE_RE = re.compile(r"[#*_>`~\[\]]+")


def _extract_summary(title: str, raw: str) -> str:
    """Extract a short text summary from raw .md content (no LLM).

    Format: "[title]\n[frontmatter key: value lines]\n[first 400 chars of body]"
    Capped at SUMMARY_MAX_CHARS total.
    """
    frontmatter_text = ""
    body_start = 0

    m = _FRONTMATTER_RE.match(raw)
    if m:
        fm_block = m.group(1)
        # Include all frontmatter fields verbatim as "key: value" lines.
        frontmatter_text = fm_block.strip()
        body_start = m.end()

    body_raw = raw[body_start:]
    # Strip common markdown syntax characters from body.
    body_clean = _MARKDOWN_NOISE_RE.sub("", body_raw).strip()
    body_snippet = body_clean[:SUMMARY_BODY_CHARS]

    parts = [title]
    if frontmatter_text:
        parts.append(frontmatter_text)
    if body_snippet:
        parts.append(body_snippet)

    summary = "\n".join(parts)
    return summary[:SUMMARY_MAX_CHARS]


def _title_from_stem(stem: str, doc_type: str) -> str:
    """Derive a human-readable title from the file stem.

    For people files (e.g. john-at-example-com) strip the domain suffix.
    For all files convert hyphens/underscores to spaces.
    """
    name = stem.replace("-", " ").replace("_", " ")
    if doc_type == "person" and " at " in name:
        # "john at example com" → "john"
        name = name.split(" at ")[0].strip()
    return name


# ── Directory walk ────────────────────────────────────────────────────────────

def _resolve_doc_type(rel_path: Path) -> str:
    """Return doc_type based on the top-level directory of the relative path."""
    top = rel_path.parts[0] if rel_path.parts else ""
    for prefix, dtype in DIR_TYPE_MAP:
        if top == prefix:
            return dtype
    return "other"


def _iter_md_files(brain_dir: Path) -> Iterator[tuple[Path, str]]:
    """Yield (absolute_path, doc_type) for every .md file under brain_dir."""
    for path in sorted(brain_dir.rglob("*.md")):
        rel = path.relative_to(brain_dir)
        doc_type = _resolve_doc_type(rel)
        yield path, doc_type


# ── Upsert logic ──────────────────────────────────────────────────────────────

def _process_file(
    path: Path,
    brain_dir: Path,
    conn: psycopg.Connection,
    user_key: str,
    dry_run: bool,
    verbose: bool,
) -> str:
    """Read one file, compute summary + hash, upsert into brain_docs.

    Returns one of: "new", "updated", "unchanged", "skipped".
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        if verbose:
            log.warning("skip binary/non-utf8 file: %s", path)
        return "skipped"
    except OSError as exc:
        log.warning("cannot read %s: %s", path, exc)
        return "skipped"

    rel_path = str(path.relative_to(brain_dir))
    doc_type = _resolve_doc_type(Path(rel_path))
    title = _title_from_stem(path.stem, doc_type)
    content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    summary = _extract_summary(title, raw)

    if verbose:
        log.info("processing %s (type=%s, hash=%s…)", rel_path, doc_type, content_hash[:8])

    if dry_run:
        log.info("[dry-run] would upsert: %s", rel_path)
        return "new"

    # ON CONFLICT: only update if hash changed (WHERE clause in DO UPDATE).
    # psycopg returns rowcount 1 for INSERT and UPDATE, 0 for DO NOTHING.
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO brain_docs (user_key, file_path, doc_type, title, summary, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_key, file_path) DO UPDATE
                SET summary      = EXCLUDED.summary,
                    content_hash = EXCLUDED.content_hash,
                    embedded     = FALSE,
                    indexed_at   = now()
            WHERE brain_docs.content_hash <> EXCLUDED.content_hash
            """,
            (user_key, rel_path, doc_type, title, summary, content_hash),
        )
        # xmax == 0 means a fresh INSERT; xmax != 0 means UPDATE or DO NOTHING.
        # We use a separate SELECT to determine the outcome.
        # Simpler: check whether the row was newly inserted via RETURNING.
        # Instead, track via the result tag.
        tag = cur.statusmessage  # e.g. "INSERT 0 1" or "UPDATE 1" or "INSERT 0 0"

    conn.commit()

    if tag.startswith("INSERT 0 1"):
        return "new"
    if tag.startswith("UPDATE 1"):
        return "updated"
    # "INSERT 0 0" or "UPDATE 0" — conflict with no hash change → unchanged
    return "unchanged"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Index brain .md files into brain_docs for vector search."
    )
    parser.add_argument(
        "--brain-dir",
        default=str(Path(__file__).parent.parent / "brain"),
        help="Path to the brain folder (default: ../brain relative to this script)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be inserted without writing to the database",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log each file as it is processed",
    )
    args = parser.parse_args()

    brain_dir = Path(args.brain_dir).resolve()
    if not brain_dir.is_dir():
        log.error("brain-dir does not exist: %s", brain_dir)
        return 1

    if not args.dry_run and not DATABASE_URL:
        log.error("BRAIN_OBS_DATABASE_URL environment variable is required (or use --dry-run)")
        return 1

    log.info("brain dir  : %s", brain_dir)
    log.info("user_key   : %s", USER_KEY)
    log.info("dry_run    : %s", args.dry_run)

    counts = {"new": 0, "updated": 0, "unchanged": 0, "skipped": 0}

    if args.dry_run:
        # Walk without DB connection.
        for path, doc_type in _iter_md_files(brain_dir):
            rel_path = str(path.relative_to(brain_dir))
            title = _title_from_stem(path.stem, doc_type)
            log.info("[dry-run] %s  type=%s  title=%s", rel_path, doc_type, title)
            counts["new"] += 1
        _print_summary(counts)
        return 0

    try:
        conn = psycopg.connect(DATABASE_URL, autocommit=False)
    except Exception as exc:
        log.error("cannot connect to postgres: %s", exc)
        return 1

    with conn:
        for path, _doc_type in _iter_md_files(brain_dir):
            outcome = _process_file(
                path,
                brain_dir,
                conn,
                USER_KEY,
                dry_run=False,
                verbose=args.verbose,
            )
            counts[outcome] = counts.get(outcome, 0) + 1

    _print_summary(counts)
    return 0


def _print_summary(counts: dict[str, int]) -> None:
    total = counts["new"] + counts["updated"] + counts["unchanged"]
    print(
        f"Indexed {total} files "
        f"({counts['new']} new, {counts['updated']} updated, {counts['unchanged']} unchanged)"
    )
    if counts["skipped"]:
        print(f"Skipped {counts['skipped']} files (binary or unreadable)")


if __name__ == "__main__":
    sys.exit(main())
