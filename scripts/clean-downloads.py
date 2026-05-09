#!/usr/bin/env python3
"""
Clean up ~/Downloads by deleting exact duplicates and old installers.

Usage:
    python clean-downloads.py --dry-run    # preview
    python clean-downloads.py              # execute
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path

DOWNLOADS = Path("~/Downloads").expanduser()


def file_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def find_duplicate_copies() -> list[Path]:
    """Find files with (1), (2), etc. that are byte-identical to the base file."""
    files = [f for f in DOWNLOADS.iterdir() if f.is_file()]
    by_size: dict[int, list[Path]] = {}
    for f in files:
        by_size.setdefault(f.stat().st_size, []).append(f)

    to_delete: list[Path] = []
    for size, group in by_size.items():
        if len(group) < 2:
            continue
        hashes: dict[str, Path] = {}
        for f in group:
            h = file_hash(f)
            if h in hashes:
                existing = hashes[h]
                # Prefer keeping the one WITHOUT (N) suffix
                if re.search(r"\(\d+\)", f.name) and not re.search(r"\(\d+\)", existing.name):
                    to_delete.append(f)
                elif re.search(r"\(\d+\)", existing.name) and not re.search(r"\(\d+\)", f.name):
                    to_delete.append(existing)
                    hashes[h] = f
                else:
                    # tie-break by name length (shorter = cleaner)
                    if len(f.name) > len(existing.name):
                        to_delete.append(f)
                    elif len(existing.name) > len(f.name):
                        to_delete.append(existing)
                        hashes[h] = f
                    else:
                        # same length — keep earlier mtime
                        if f.stat().st_mtime > existing.stat().st_mtime:
                            to_delete.append(f)
                        else:
                            to_delete.append(existing)
                            hashes[h] = f
            else:
                hashes[h] = f
    return to_delete


def find_empty_dupes() -> list[Path]:
    """Delete empty files that duplicate .localized or other system files."""
    to_delete: list[Path] = []
    empty_files = [f for f in DOWNLOADS.iterdir() if f.is_file() and f.stat().st_size == 0]
    keep = {".localized", ".DS_Store"}
    for f in empty_files:
        if f.name not in keep:
            to_delete.append(f)
    return to_delete


def find_old_installers() -> list[Path]:
    """Delete obviously old/outdated installers and software."""
    to_delete: list[Path] = []
    old_patterns = [
        r"yaatuber-1\.0\.11",
        r"Descript Installer",
    ]
    for f in DOWNLOADS.iterdir():
        if not f.is_file():
            continue
        for pat in old_patterns:
            if re.search(pat, f.name, re.I):
                to_delete.append(f)
                break
    return to_delete


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean up Downloads")
    parser.add_argument("--dry-run", action="store_true", help="Preview deletions")
    args = parser.parse_args()

    dupes = find_duplicate_copies()
    empty = find_empty_dupes()
    old = find_old_installers()

    all_to_delete = sorted(set(dupes + empty + old), key=lambda p: p.name)

    if not all_to_delete:
        print("Nothing to clean up.")
        return 0

    total_bytes = sum(p.stat().st_size for p in all_to_delete)
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Deleting {len(all_to_delete)} file(s), freeing {total_bytes / 1_000_000:.1f} MB:\n")
    for p in all_to_delete:
        size_mb = p.stat().st_size / 1_000_000
        print(f"  {'(dry-run) ' if args.dry_run else ''}{p.name} ({size_mb:.1f} MB)")

    # Also list remaining installers for awareness
    installers = [f for f in DOWNLOADS.iterdir() if f.is_file() and f.suffix.lower() in {".dmg", ".pkg", ".app"} and f not in all_to_delete]
    if installers:
        print(f"\n  Remaining installers (kept):\n")
        for p in sorted(installers, key=lambda x: x.name):
            size_mb = p.stat().st_size / 1_000_000
            print(f"    {p.name} ({size_mb:.1f} MB)")

    if not args.dry_run:
        for p in all_to_delete:
            os.remove(p)
            print(f"  deleted: {p.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
