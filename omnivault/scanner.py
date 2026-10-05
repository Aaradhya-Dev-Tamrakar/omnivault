"""
High-Performance Directory Scanner for OmniVault
Traverses drives using os.scandir, filters system noise, and generates metadata batches.
"""

import os
from collections.abc import Callable, Generator
from pathlib import Path

from omnivault.config import IGNORED_DIRS, get_category
from omnivault.hasher import compute_blake3
from omnivault.thumbnail import generate_thumbnail


def scan_directory(
    root_path: Path | str,
    compute_hash: bool = True,
    make_thumbnails: bool = True,
    batch_size: int = 500,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> Generator[list[dict], None, None]:
    """
    Crawls a root directory and yields batches of file metadata records.

    Args:
        root_path: Starting folder or drive root (e.g. 'I:/')
        compute_hash: Whether to calculate cryptographic BLAKE3 hashes
        make_thumbnails: Whether to extract WebP thumbnails for image files
        batch_size: Number of records to yield per batch
        progress_callback: Optional callback(scanned_count, total_bytes, current_path)
    """
    root = Path(root_path).resolve()
    batch = []
    scanned_count = 0
    total_bytes = 0

    stack = [root]

    while stack:
        current_dir = stack.pop()
        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    try:
                        # Skip system and ignored directories
                        name_lower = entry.name.lower()
                        if entry.is_dir(follow_symlinks=False):
                            if name_lower not in IGNORED_DIRS and not name_lower.startswith("."):
                                stack.append(Path(entry.path))
                            continue

                        if not entry.is_file(follow_symlinks=False):
                            continue

                        # Extract basic stats
                        stat_res = entry.stat(follow_symlinks=False)
                        size = stat_res.st_size
                        mtime = stat_res.st_mtime
                        ext = Path(entry.name).suffix.lower()
                        category = get_category(ext)

                        try:
                            rel = Path(entry.path).relative_to(root).as_posix()
                        except ValueError:
                            rel = entry.name

                        file_hash = None
                        has_thumb = 0

                        if compute_hash:
                            try:
                                file_hash = compute_blake3(entry.path)
                            except Exception:
                                file_hash = None

                        if make_thumbnails and file_hash and category == "photos":
                            try:
                                thumb_path = generate_thumbnail(entry.path, file_hash)
                                if thumb_path:
                                    has_thumb = 1
                            except Exception:
                                has_thumb = 0

                        record = {
                            "rel_path": rel,
                            "abs_path": entry.path,
                            "filename": entry.name,
                            "extension": ext,
                            "category": category,
                            "size_bytes": size,
                            "mtime": mtime,
                            "blake3_hash": file_hash,
                            "has_thumbnail": has_thumb,
                            "status": "COLD_ONLINE",
                        }

                        batch.append(record)
                        scanned_count += 1
                        total_bytes += size

                        if progress_callback and scanned_count % 100 == 0:
                            progress_callback(scanned_count, total_bytes, entry.path)

                        if len(batch) >= batch_size:
                            yield batch
                            batch = []

                    except (PermissionError, FileNotFoundError, OSError):
                        continue
        except (PermissionError, FileNotFoundError, OSError):
            continue

    if batch:
        yield batch
