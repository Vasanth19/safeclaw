#!/usr/bin/env python3
"""
Reclassify a document already in the archive.

Moves the binary file to a new category/subcategory and updates the
brain index entry.

Usage:
    python scripts/reclassify-doc.py ~/vasanth-hq/documents/Inbox/report.pdf --category Growth-Systems-AI --subcategory Client-Delivery
    python scripts/reclassify-doc.py ~/vasanth-hq/documents/Personal/Taxes/2024-w2.pdf --category Personal --subcategory Identity
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

DOCS_DIR = Path("~/vasanth-hq/documents").expanduser()
BRAIN_DIR = Path("~/vasanth-hq/evolving-brain").expanduser()
BRAIN_DOCS_SUBDIR = "Documents"


def find_brain_index(stem: str, brain_docs_dir: Path) -> Path | None:
    """Find the .md index file matching a document stem."""
    candidates = list(brain_docs_dir.glob(f"{stem}.md")) + list(brain_docs_dir.glob(f"{stem}-*.md"))
    if not candidates:
        return None
    # Prefer exact match
    exact = brain_docs_dir / f"{stem}.md"
    if exact.exists():
        return exact
    # Return most recently modified
    return max(candidates, key=lambda p: p.stat().st_mtime)


def update_frontmatter(content: str, category: str, subcategory: str | None, new_file_path: str) -> str:
    """Update category, subcategory, and file_path in YAML frontmatter."""
    # Simple regex-based frontmatter update
    def replace_or_add(key: str, value: str | None) -> None:
        nonlocal content
        if value is None:
            # Remove line if present
            content = re.sub(rf"^{key}:.*\n?", "", content, flags=re.MULTILINE)
            return
        pattern = rf"^({key}:).*"
        replacement = rf"\1 {value}"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE, count=1)
        else:
            # Insert before closing ---
            content = re.sub(r"^(---\n.*?)(---\n)", rf"\1{key}: {value}\n\2", content, flags=re.DOTALL, count=1)

    replace_or_add("category", category)
    replace_or_add("subcategory", subcategory)
    replace_or_add("file_path", new_file_path)

    # Also update the Location line in the body
    content = re.sub(
        r"(\*\*Location:\*\* `).*?(`  \n)",
        rf"\g<1>{new_file_path}\g<2>",
        content,
    )
    # Update Category line in body
    if re.search(r"(\*\*Category:\*\* ).*?(  \n)", content):
        content = re.sub(
            r"(\*\*Category:\*\* ).*?(  \n)",
            rf"\g<1>{category}  \n",
            content,
        )
    else:
        content = re.sub(
            r"(\*\*Type:\*\* .*?  \n)",
            rf"\g<1>**Category:** {category}  \n",
            content,
            count=1,
        )

    # Update or remove Subcategory line in body
    if subcategory:
        if re.search(r"(\*\*Subcategory:\*\* ).*?(  \n)", content):
            content = re.sub(
                r"(\*\*Subcategory:\*\* ).*?(  \n)",
                rf"\g<1>{subcategory}  \n",
                content,
            )
        else:
            content = re.sub(
                r"(\*\*Category:\*\* .*?  \n)",
                rf"\g<1>**Subcategory:** {subcategory}  \n",
                content,
                count=1,
            )
    else:
        content = re.sub(r"\*\*Subcategory:\*\* .*?  \n", "", content)

    return content


def reclassify(
    file_path: Path,
    new_category: str,
    new_subcategory: str | None,
    *,
    dry_run: bool = False,
) -> None:
    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)

    # Ensure the file lives under the docs archive
    if DOCS_DIR not in file_path.parents and file_path.parent != DOCS_DIR:
        print(f"WARNING: {file_path} is not under {DOCS_DIR}")

    # Compute new destination
    new_dir = DOCS_DIR / new_category
    if new_subcategory:
        new_dir = new_dir / new_subcategory

    new_dest = new_dir / file_path.name
    # Handle collisions in new location
    i = 1
    while new_dest.exists() and new_dest.resolve() != file_path.resolve():
        new_dest = new_dir / f"{file_path.stem}-{i}{file_path.suffix}"
        i += 1

    # Find brain index
    brain_docs_dir = BRAIN_DIR / BRAIN_DOCS_SUBDIR
    index_path = find_brain_index(file_path.stem, brain_docs_dir)

    if dry_run:
        print(f"[dry-run] {file_path.name}")
        print(f"  move:   {file_path} → {new_dest}")
        if index_path:
            print(f"  index:  {index_path}")
        else:
            print(f"  index:  (not found)")
        return

    # Create directories
    new_dir.mkdir(parents=True, exist_ok=True)

    # Move file
    if new_dest.resolve() != file_path.resolve():
        shutil.move(str(file_path), str(new_dest))
        print(f"moved:   {file_path} → {new_dest}")
    else:
        print(f"already in place: {file_path}")

    # Update index
    if index_path and index_path.exists():
        content = index_path.read_text(encoding="utf-8")
        updated = update_frontmatter(content, new_category, new_subcategory, str(new_dest))
        index_path.write_text(updated, encoding="utf-8")
        print(f"updated: {index_path}")
    else:
        print(f"WARNING: no brain index found for {file_path.name}")

    print()
    print("Next step — re-index:")
    print(f"  cd {Path('~/vasanth-hq/safeclaw').expanduser()} && bash scripts/run-index-brain.sh")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclassify a document in the archive")
    parser.add_argument("file", type=Path, help="Path to the document in the archive")
    parser.add_argument("--category", required=True, help="New top-level category")
    parser.add_argument("--subcategory", default=None, help="New subcategory (optional)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    args = parser.parse_args()

    reclassify(
        args.file.expanduser().resolve(),
        args.category,
        args.subcategory,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
