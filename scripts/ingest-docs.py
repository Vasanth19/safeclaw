#!/usr/bin/env python3
"""
SafeClaw Document Ingester

Moves files to ~/vasanth-hq/documents/ and writes a lightweight .md index
entry into ~/vasanth-hq/evolving-brain/Documents/ so the brain indexer can
embed a summary + location pointer without storing binary files in the vault.

Usage:
    python scripts/ingest-docs.py ~/Downloads/report.pdf ~/Downloads/notes.docx
    python scripts/ingest-docs.py --source-dir ~/Downloads --extensions pdf,docx,txt
    python scripts/ingest-docs.py ~/Downloads/file.pdf --copy   # keep original
    python scripts/ingest-docs.py --source-dir ~/Downloads --autonomous

Environment overrides:
    SAFECLAW_DOCS_DIR    target folder for moved files  (default: ~/vasanth-hq/documents)
    SAFECLAW_BRAIN_DIR   evolving brain root            (default: ~/vasanth-hq/evolving-brain)
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

DOCS_DIR = Path(os.environ.get("SAFECLAW_DOCS_DIR", "~/vasanth-hq/documents")).expanduser()
BRAIN_DIR = Path(os.environ.get("SAFECLAW_BRAIN_DIR", "~/vasanth-hq/evolving-brain")).expanduser()
BRAIN_DOCS_SUBDIR = "Documents"
CLASSIFIER_PATH = Path("~/vasanth-hq/safeclaw/config/doc-classifier.yaml").expanduser()
SUMMARY_CHARS = 1500

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".txt", ".md", ".csv", ".json",
    ".yaml", ".yml", ".html", ".htm", ".xlsx", ".doc",
}


# ── Classification ────────────────────────────────────────────────────────────

def load_classifier(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def classify_file(filename: str, classifier: dict | None = None) -> tuple[str, str | None]:
    """Return (category, subcategory) for a filename. Falls back to ('Inbox', None)."""
    if classifier is None:
        classifier = load_classifier(CLASSIFIER_PATH)

    stem = Path(filename).stem.lower()
    for category, subcats in classifier.items():
        if category == "Inbox":
            continue
        if not isinstance(subcats, dict):
            continue
        for subcategory, keywords in subcats.items():
            for kw in keywords:
                if kw.lower() in stem:
                    return category, subcategory
    return "Inbox", None


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_pdf(path: Path) -> str:
    # pdftotext (poppler) — gets proper text including layout
    try:
        r = subprocess.run(
            ["pdftotext", "-l", "4", str(path), "-"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()[:SUMMARY_CHARS]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # pypdf fallback
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        text = ""
        for page in reader.pages[:4]:
            text += page.extract_text() or ""
            if len(text) >= SUMMARY_CHARS:
                break
        if text.strip():
            return text.strip()[:SUMMARY_CHARS]
    except ImportError:
        pass
    return "(PDF — install pdftotext or pypdf for text extraction)"


def _extract_docx(path: Path) -> str:
    # python-docx
    try:
        import docx  # type: ignore
        doc = docx.Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        if text.strip():
            return text[:SUMMARY_CHARS]
    except ImportError:
        pass
    # Zip fallback — strip XML tags from word/document.xml
    try:
        with zipfile.ZipFile(str(path)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        text = re.sub(r"<[^>]+>", " ", xml)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return text[:SUMMARY_CHARS]
    except Exception:
        pass
    return "(DOCX — install python-docx for text extraction)"


def extract_text(path: Path) -> str:
    s = path.suffix.lower()
    try:
        if s == ".pdf":
            return _extract_pdf(path)
        if s == ".docx":
            return _extract_docx(path)
        if s in {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".html", ".htm"}:
            return path.read_text(encoding="utf-8", errors="replace")[:SUMMARY_CHARS]
    except Exception:
        return ""
    return ""


# ── Core ingest ───────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    return re.sub(r"-+", "-", name).strip("-")[:80]


def _unique_path(base: Path) -> Path:
    if not base.exists():
        return base
    i = 1
    while True:
        candidate = base.with_stem(f"{base.stem}-{i}")
        if not candidate.exists():
            return candidate
        i += 1


def ingest_file(
    src: Path,
    docs_dir: Path,
    brain_docs_dir: Path,
    *,
    move: bool = True,
    category: str = "Inbox",
    subcategory: str | None = None,
) -> None:
    # Build archive destination
    dest_dir = docs_dir / category
    if subcategory:
        dest_dir = dest_dir / subcategory
    dest_dir.mkdir(parents=True, exist_ok=True)
    brain_docs_dir.mkdir(parents=True, exist_ok=True)

    # Move / copy the binary file
    dest = _unique_path(dest_dir / src.name)
    if move:
        shutil.move(str(src), str(dest))
        action = "moved"
    else:
        shutil.copy2(str(src), str(dest))
        action = "copied"
    print(f"  {action}: {src.name} → {dest}")

    # Extract text for summary
    raw_text = extract_text(dest).strip() or "(no text extracted)"

    # Build .md index entry
    today = datetime.date.today().isoformat()
    file_type = dest.suffix.lstrip(".").upper() or "FILE"
    md_path = _unique_path(brain_docs_dir / f"{slugify(src.stem)}.md")

    cat_line = f"category: {category}\n"
    sub_line = f"subcategory: {subcategory}\n" if subcategory else ""

    md = (
        f"---\n"
        f"title: {src.stem}\n"
        f"file_path: {dest}\n"
        f"file_type: {file_type}\n"
        f"date_ingested: {today}\n"
        f"{cat_line}"
        f"{sub_line}"
        f"---\n\n"
        f"# {src.stem}\n\n"
        f"**Location:** `{dest}`  \n"
        f"**Type:** {file_type}  \n"
        f"**Category:** {category}  \n"
        f"{f'**Subcategory:** {subcategory}  \\n' if subcategory else ''}"
        f"**Ingested:** {today}\n\n"
        f"## Summary\n\n"
        f"{raw_text}\n"
    )
    md_path.write_text(md, encoding="utf-8")
    print(f"  indexed:  {md_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move documents to archive and create brain index entries."
    )
    parser.add_argument("files", nargs="*", type=Path, help="Files to ingest")
    parser.add_argument("--source-dir", type=Path,
                        help="Scan this directory and ingest all matching files")
    parser.add_argument("--extensions", default="pdf,docx,txt,md,csv",
                        help="Extensions to pick up from --source-dir (default: pdf,docx,txt,md,csv)")
    parser.add_argument("--docs-dir", type=Path, default=DOCS_DIR,
                        help=f"Archive folder for the actual files (default: {DOCS_DIR})")
    parser.add_argument("--brain-dir", type=Path, default=BRAIN_DIR,
                        help=f"Evolving brain root (default: {BRAIN_DIR})")
    parser.add_argument("--copy", action="store_true",
                        help="Copy instead of move (original stays in Downloads)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without writing anything")
    parser.add_argument("--autonomous", action="store_true",
                        help="Auto-classify files using doc-classifier.yaml")
    parser.add_argument("--skip-non-docs", action="store_true",
                        help="Skip files whose extension is not in the allowed-doc list")
    parser.add_argument("--category", type=str, default=None,
                        help="Override category for all files (e.g., 'Personal/Taxes')")
    args = parser.parse_args()

    brain_docs_dir = args.brain_dir / BRAIN_DOCS_SUBDIR

    # Determine if we should auto-classify and skip non-docs
    is_batch = args.source_dir is not None
    autonomous = args.autonomous or is_batch
    skip_non_docs = args.skip_non_docs or is_batch

    files: list[Path] = [f.expanduser().resolve() for f in (args.files or [])]
    if args.source_dir:
        exts = {f".{e.strip().lstrip('.')}" for e in args.extensions.split(",")}
        files += [
            p.resolve()
            for p in args.source_dir.expanduser().iterdir()
            if p.is_file() and p.suffix.lower() in exts
        ]

    if not files:
        print("No files specified. Pass FILE paths or use --source-dir.")
        return 1

    # Skip hidden/temp files
    before = len(files)
    files = [f for f in files if not f.name.startswith((".", "~$"))]
    skipped = before - len(files)
    if skipped:
        print(f"Skipped {skipped} hidden/temp file(s)")

    # Filter non-docs if requested
    if skip_non_docs:
        before = len(files)
        files = [f for f in files if f.suffix.lower() in ALLOWED_EXTENSIONS]
        skipped = before - len(files)
        if skipped:
            print(f"Skipped {skipped} non-document file(s)")

    if not files:
        print("No document files found after filtering.")
        return 0

    # Load classifier once
    classifier = load_classifier(CLASSIFIER_PATH) if autonomous else {}

    # Parse manual category override
    manual_category: str | None = None
    manual_subcategory: str | None = None
    if args.category:
        parts = args.category.split("/", 1)
        manual_category = parts[0]
        manual_subcategory = parts[1] if len(parts) > 1 else None

    print(f"Ingesting {len(files)} file(s)")
    print(f"  docs archive : {args.docs_dir}")
    print(f"  brain docs   : {brain_docs_dir}")
    print()

    errors = 0
    for f in files:
        if not f.exists():
            print(f"  SKIP (not found): {f}")
            errors += 1
            continue

        # Resolve category
        if manual_category:
            category = manual_category
            subcategory = manual_subcategory
        elif autonomous:
            category, subcategory = classify_file(f.name, classifier)
        else:
            category, subcategory = "Inbox", None

        if args.dry_run:
            text_preview = extract_text(f)[:120].replace("\n", " ")
            print(f"  [dry-run] {f.name}")
            print(f"            cat:  {category}{' / ' + subcategory if subcategory else ''}")
            print(f"            text: {text_preview or '(none)'}")
            continue

        try:
            ingest_file(
                f, args.docs_dir, brain_docs_dir,
                move=not args.copy, category=category, subcategory=subcategory,
            )
        except Exception as exc:
            print(f"  ERROR {f.name}: {exc}")
            errors += 1

    if not args.dry_run:
        print()
        print("Next step — embed the new index entries:")
        print(f"  cd {Path('~/vasanth-hq/safeclaw').expanduser()} && bash scripts/run-index-brain.sh")

    return errors


if __name__ == "__main__":
    sys.exit(main())
