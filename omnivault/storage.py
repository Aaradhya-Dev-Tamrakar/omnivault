"""
System Storage Management & Optimization Engine for OmniVault

Provides:
  - Multi-drive disk usage profiling with per-directory breakdown
  - Content-addressable duplicate detection via BLAKE3 hashes
  - Large file discovery (sorted by size, with category and location)
  - Temp / cache / bloat directory detection and safe cleanup
  - node_modules / .venv / build artifact reclamation
  - Storage optimization recommendations with reclaimable byte estimates
  - Safe deletion with confirmation and dry-run mode
"""

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from omnivault.config import DATABASE_PATH, IGNORED_DIRS, SETTINGS, get_category
from omnivault.db import format_bytes, get_connection, init_db

# ── Bloat / cache directories that are safe to purge ────────────────────────
KNOWN_CACHE_DIRS: list[dict] = [
    {"path": "{LOCALAPPDATA}\\Temp", "label": "Windows User Temp", "safe": True},
    {"path": "C:\\Windows\\Temp", "label": "Windows System Temp", "safe": True},
    {
        "path": "{LOCALAPPDATA}\\Microsoft\\Windows\\Explorer",
        "label": "Explorer Thumbnail Cache",
        "safe": True,
    },
    {
        "path": "{LOCALAPPDATA}\\Google\\Chrome\\User Data\\Default\\Cache",
        "label": "Chrome Browser Cache",
        "safe": True,
    },
    {
        "path": "{LOCALAPPDATA}\\Google\\Chrome\\User Data\\Default\\Code Cache",
        "label": "Chrome Code Cache",
        "safe": True,
    },
    {
        "path": "{LOCALAPPDATA}\\Microsoft\\Edge\\User Data\\Default\\Cache",
        "label": "Edge Browser Cache",
        "safe": True,
    },
    {"path": "{LOCALAPPDATA}\\pip\\cache", "label": "Python pip Cache", "safe": True},
    {"path": "{LOCALAPPDATA}\\npm-cache", "label": "npm Cache", "safe": True},
    {"path": "{APPDATA}\\Code\\Cache", "label": "VS Code Cache", "safe": True},
    {"path": "{APPDATA}\\Code\\CachedData", "label": "VS Code Cached Data", "safe": True},
    {
        "path": "{APPDATA}\\Code\\CachedExtensionVSIXs",
        "label": "VS Code Cached Extensions",
        "safe": True,
    },
    {"path": "{APPDATA}\\Code\\logs", "label": "VS Code Logs", "safe": True},
    {"path": "{LOCALAPPDATA}\\Yarn\\Cache", "label": "Yarn Cache", "safe": True},
    {"path": "{LOCALAPPDATA}\\pnpm-cache", "label": "pnpm Cache", "safe": True},
    {"path": "{LOCALAPPDATA}\\NuGet\\Cache", "label": ".NET NuGet Cache", "safe": True},
    {"path": "{USERPROFILE}\\.gradle\\caches", "label": "Gradle Build Cache", "safe": True},
    {"path": "{LOCALAPPDATA}\\CrashDumps", "label": "Windows Crash Dumps", "safe": True},
]

# Directories that bloat over time in dev projects
DEV_BLOAT_PATTERNS = [
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".tox",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
]

HEAVY_SYSTEM_DIRS = {
    "appdata",
    ".gradle",
    ".claude-profiles",
    ".gemini",
    ".cache",
    ".antigravity-ide",
    ".vscode",
    ".codex",
    "$recycle.bin",
    "system volume information",
}


def _expand(template: str) -> str:
    """Expand environment variable templates like {LOCALAPPDATA}."""
    result = template
    for var in ["LOCALAPPDATA", "APPDATA", "TEMP", "USERPROFILE"]:
        val = os.environ.get(var, "")
        result = result.replace(f"{{{var}}}", val)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 1. Drive Usage Profiler
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class DriveReport:
    letter: str
    label: str
    fs_type: str
    total_bytes: int
    free_bytes: int
    used_bytes: int
    used_pct: float


def get_drive_reports() -> list[DriveReport]:
    """Returns usage statistics for every mounted volume."""
    reports = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.isdir(root):
            try:
                total, used, free = shutil.disk_usage(root)
                # Get volume label via ctypes on Windows
                import ctypes

                buf = ctypes.create_unicode_buffer(1024)
                ctypes.windll.kernel32.GetVolumeInformationW(
                    root, buf, 1024, None, None, None, None, 0
                )
                label = buf.value or ""
                fs_buf = ctypes.create_unicode_buffer(256)
                ctypes.windll.kernel32.GetVolumeInformationW(
                    root, None, 0, None, None, None, fs_buf, 256
                )
                fs_type = fs_buf.value or "Unknown"
                pct = round((used / total) * 100, 1) if total > 0 else 0.0
                reports.append(
                    DriveReport(
                        letter=letter,
                        label=label,
                        fs_type=fs_type,
                        total_bytes=total,
                        free_bytes=free,
                        used_bytes=used,
                        used_pct=pct,
                    )
                )
            except Exception:
                pass
    return reports


def profile_directory(root: str | Path, depth: int = 1) -> list[dict]:
    """
    Returns sorted list of subdirectories under `root` with their sizes.
    depth=1 means only immediate children.
    """
    root = Path(root)
    results = []
    try:
        for entry in os.scandir(root):
            if not entry.is_dir(follow_symlinks=False):
                continue
            name_lower = entry.name.lower()
            if name_lower in IGNORED_DIRS or name_lower.startswith("."):
                continue
            total_size = 0
            file_count = 0
            try:
                for dirpath, _, filenames in os.walk(entry.path, followlinks=False):
                    for fn in filenames:
                        try:
                            total_size += os.path.getsize(os.path.join(dirpath, fn))
                            file_count += 1
                        except OSError:
                            pass
            except (PermissionError, OSError):
                pass
            results.append(
                {
                    "name": entry.name,
                    "path": entry.path,
                    "size_bytes": total_size,
                    "size_formatted": format_bytes(total_size),
                    "file_count": file_count,
                }
            )
    except (PermissionError, OSError):
        pass
    results.sort(key=lambda x: x["size_bytes"], reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 2. Duplicate File Detector
# ═══════════════════════════════════════════════════════════════════════════


def find_duplicates(min_size: int = 1024, db_path: Path = DATABASE_PATH) -> list[dict]:
    """
    Identifies duplicate files across all indexed volumes using BLAKE3 hashes.
    Returns groups of files sharing the same hash, sorted by wasted space (descending).
    """
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT blake3_hash, COUNT(*) as cnt, SUM(size_bytes) as total_size
            FROM files
            WHERE blake3_hash IS NOT NULL AND size_bytes >= ?
            GROUP BY blake3_hash
            HAVING cnt > 1
            ORDER BY total_size DESC
        """,
            (min_size,),
        ).fetchall()

        groups = []
        for row in rows:
            files = conn.execute(
                "SELECT f.filename, f.abs_path, f.size_bytes, f.category, v.label as volume_label "
                "FROM files f JOIN volumes v ON f.volume_id = v.id "
                "WHERE f.blake3_hash = ?",
                (row["blake3_hash"],),
            ).fetchall()
            wasted = row["total_size"] - (files[0]["size_bytes"] if files else 0)
            groups.append(
                {
                    "blake3_hash": row["blake3_hash"],
                    "count": row["cnt"],
                    "each_size": files[0]["size_bytes"] if files else 0,
                    "each_size_formatted": format_bytes(files[0]["size_bytes"]) if files else "0 B",
                    "wasted_bytes": wasted,
                    "wasted_formatted": format_bytes(wasted),
                    "files": [dict(f) for f in files],
                }
            )
    return groups


# ═══════════════════════════════════════════════════════════════════════════
# 3. Large File Finder
# ═══════════════════════════════════════════════════════════════════════════


def find_large_files(
    root: str | Path = "C:\\Users",
    min_size_mb: float = 100.0,
    limit: int = 50,
    include_indexed: bool = True,
) -> list[dict]:
    """Discovers the largest files from indexed volumes and user directories."""
    min_bytes = int(min_size_mb * 1024 * 1024)
    results = []
    seen_paths = set()

    # Priority 1: Pull from OmniVault SQLite catalog (instantaneous sub-millisecond query)
    if include_indexed:
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT filename, abs_path, size_bytes, category, extension FROM files WHERE size_bytes >= ? ORDER BY size_bytes DESC LIMIT ?",
                    (min_bytes, limit),
                ).fetchall()
                for r in rows:
                    p = r["abs_path"]
                    seen_paths.add(p.lower())
                    results.append(
                        {
                            "filename": r["filename"],
                            "path": p,
                            "size_bytes": r["size_bytes"],
                            "size_formatted": format_bytes(r["size_bytes"]),
                            "category": r["category"],
                            "extension": r["extension"],
                        }
                    )
        except Exception:
            pass

    # Priority 2: Scan key user folders on laptop (from settings)
    target_dirs = [Path(p) for p in SETTINGS.large_file_dirs]

    for target in target_dirs:
        if not target.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
            dirnames[:] = [
                d
                for d in dirnames
                if d.lower() not in HEAVY_SYSTEM_DIRS and d.lower() not in IGNORED_DIRS
            ]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                if fp.lower() in seen_paths:
                    continue
                try:
                    sz = os.path.getsize(fp)
                    if sz >= min_bytes:
                        ext = Path(fn).suffix.lower()
                        seen_paths.add(fp.lower())
                        results.append(
                            {
                                "filename": fn,
                                "path": fp,
                                "size_bytes": sz,
                                "size_formatted": format_bytes(sz),
                                "category": get_category(ext),
                                "extension": ext,
                            }
                        )
                except OSError:
                    pass

    results.sort(key=lambda x: x["size_bytes"], reverse=True)
    return results[:limit]


# ═══════════════════════════════════════════════════════════════════════════
# 4. Cache & Temp Bloat Scanner
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class BloatEntry:
    label: str
    path: str
    file_count: int
    size_bytes: int
    size_formatted: str
    safe_to_delete: bool


def scan_cache_bloat() -> list[BloatEntry]:
    """Scans known Windows and developer cache directories for reclaimable space."""
    results = []
    for entry in KNOWN_CACHE_DIRS:
        expanded = _expand(entry["path"])
        if os.path.isdir(expanded):
            total = 0
            count = 0
            try:
                for dirpath, _, fns in os.walk(expanded, followlinks=False):
                    for fn in fns:
                        try:
                            total += os.path.getsize(os.path.join(dirpath, fn))
                            count += 1
                        except OSError:
                            pass
            except (PermissionError, OSError):
                pass
            if total > 0:
                results.append(
                    BloatEntry(
                        label=entry["label"],
                        path=expanded,
                        file_count=count,
                        size_bytes=total,
                        size_formatted=format_bytes(total),
                        safe_to_delete=entry.get("safe", False),
                    )
                )
    results.sort(key=lambda x: x.size_bytes, reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 5. Dev Dependency Bloat Scanner (node_modules, .venv, etc.)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class DevBloatEntry:
    name: str
    path: str
    size_bytes: int
    size_formatted: str
    parent_project: str


def scan_dev_bloat(
    roots: list[str] | None = None,
    min_size_mb: float = 30.0,
    max_depth: int = 5,
) -> list[DevBloatEntry]:
    """Finds node_modules, .venv, and other regenerable dependency directories."""
    if roots is None:
        roots = [str(p) for p in SETTINGS.dev_scan_roots]

    min_bytes = int(min_size_mb * 1024 * 1024)
    found = []

    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, _ in os.walk(root, followlinks=False):
            # Prune known heavy system directories immediately
            dirnames[:] = [
                d
                for d in dirnames
                if d.lower() not in HEAVY_SYSTEM_DIRS and d.lower() not in IGNORED_DIRS
            ]

            # Depth limiter
            rel_depth = dirpath.replace(root, "").count(os.sep)
            if rel_depth >= max_depth:
                dirnames.clear()
                continue

            for pattern in DEV_BLOAT_PATTERNS:
                if pattern in dirnames:
                    full = os.path.join(dirpath, pattern)
                    total = 0
                    try:
                        for dp, _, fns in os.walk(full, followlinks=False):
                            for fn in fns:
                                try:
                                    total += os.path.getsize(os.path.join(dp, fn))
                                except OSError:
                                    pass
                    except (PermissionError, OSError):
                        pass

                    if total >= min_bytes:
                        found.append(
                            DevBloatEntry(
                                name=pattern,
                                path=full,
                                size_bytes=total,
                                size_formatted=format_bytes(total),
                                parent_project=dirpath,
                            )
                        )
                    # Don't recurse into the bloat dir itself
                    dirnames.remove(pattern)

    found.sort(key=lambda x: x.size_bytes, reverse=True)
    return found


# ═══════════════════════════════════════════════════════════════════════════
# 6. Full Storage Report Generator
# ═══════════════════════════════════════════════════════════════════════════


def generate_full_report(
    scan_caches: bool = True,
    scan_dev: bool = True,
    scan_duplicates: bool = True,
    scan_large_files: bool = True,
    large_file_root: str = "C:\\Users",
    large_file_min_mb: float = 100.0,
) -> dict:
    """
    Generates a comprehensive storage health report across all dimensions.
    Returns a structured dict for CLI/Web rendering.
    """
    report: dict = {"timestamp": time.time()}

    # 1. Drive summaries
    report["drives"] = [
        {
            "letter": d.letter,
            "label": d.label,
            "fs_type": d.fs_type,
            "total_formatted": format_bytes(d.total_bytes),
            "free_formatted": format_bytes(d.free_bytes),
            "used_formatted": format_bytes(d.used_bytes),
            "used_pct": d.used_pct,
            "total_bytes": d.total_bytes,
            "free_bytes": d.free_bytes,
        }
        for d in get_drive_reports()
    ]

    total_reclaimable = 0

    # 2. Cache bloat
    if scan_caches:
        caches = scan_cache_bloat()
        cache_total = sum(c.size_bytes for c in caches)
        total_reclaimable += cache_total
        report["cache_bloat"] = {
            "entries": [
                {
                    "label": c.label,
                    "path": c.path,
                    "files": c.file_count,
                    "size_formatted": c.size_formatted,
                    "size_bytes": c.size_bytes,
                    "safe": c.safe_to_delete,
                }
                for c in caches
            ],
            "total_bytes": cache_total,
            "total_formatted": format_bytes(cache_total),
        }

    # 3. Dev dependency bloat
    if scan_dev:
        dev_items = scan_dev_bloat()
        dev_total = sum(d.size_bytes for d in dev_items)
        total_reclaimable += dev_total
        report["dev_bloat"] = {
            "entries": [
                {
                    "name": d.name,
                    "path": d.path,
                    "project": d.parent_project,
                    "size_formatted": d.size_formatted,
                    "size_bytes": d.size_bytes,
                }
                for d in dev_items
            ],
            "total_bytes": dev_total,
            "total_formatted": format_bytes(dev_total),
        }

    # 4. Duplicate files
    if scan_duplicates:
        dups = find_duplicates()
        dup_wasted = sum(d["wasted_bytes"] for d in dups)
        total_reclaimable += dup_wasted
        report["duplicates"] = {
            "groups": dups[:30],  # Top 30 duplicate groups
            "total_groups": len(dups),
            "wasted_bytes": dup_wasted,
            "wasted_formatted": format_bytes(dup_wasted),
        }

    # 5. Large files
    if scan_large_files:
        large = find_large_files(root=large_file_root, min_size_mb=large_file_min_mb)
        large_total = sum(f["size_bytes"] for f in large)
        report["large_files"] = {
            "files": large[:30],
            "total_found": len(large),
            "total_bytes": large_total,
            "total_formatted": format_bytes(large_total),
        }

    report["total_reclaimable_bytes"] = total_reclaimable
    report["total_reclaimable_formatted"] = format_bytes(total_reclaimable)

    return report


# ═══════════════════════════════════════════════════════════════════════════
# 7. Safe Cleanup Actions
# ═══════════════════════════════════════════════════════════════════════════


def clean_cache_dir(path: str, dry_run: bool = True) -> dict:
    """Safely removes contents of a cache directory."""
    target = Path(path)
    if not target.is_dir():
        return {"error": f"Not a directory: {path}", "freed": 0}

    freed = 0
    deleted = 0
    errors = 0

    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                sz = os.path.getsize(fp)
                if not dry_run:
                    os.unlink(fp)
                freed += sz
                deleted += 1
            except (PermissionError, OSError):
                errors += 1
        if not dry_run:
            for dn in dirnames:
                dp = os.path.join(dirpath, dn)
                try:
                    os.rmdir(dp)
                except OSError:
                    pass

    return {
        "path": path,
        "dry_run": dry_run,
        "files_deleted": deleted,
        "freed_bytes": freed,
        "freed_formatted": format_bytes(freed),
        "errors": errors,
    }


def clean_dev_bloat_dir(path: str, dry_run: bool = True) -> dict:
    """Removes a regenerable dev dependency directory (node_modules, .venv, etc.)."""
    target = Path(path)
    if not target.is_dir():
        return {"error": f"Not a directory: {path}", "freed": 0}

    total = 0
    count = 0
    for dirpath, _, fns in os.walk(path, followlinks=False):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
                count += 1
            except OSError:
                pass

    if not dry_run:
        shutil.rmtree(path, ignore_errors=True)

    return {
        "path": path,
        "dry_run": dry_run,
        "files_removed": count,
        "freed_bytes": total,
        "freed_formatted": format_bytes(total),
    }
