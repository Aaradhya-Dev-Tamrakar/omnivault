"""
Database Engine for OmniVault
High-performance SQLite FTS5 store with WAL mode, automated triggers, and sub-5ms queries.
"""

import sqlite3
import time
from pathlib import Path
from typing import Any

from omnivault.config import DATABASE_PATH


def get_connection(db_path: Path = DATABASE_PATH) -> sqlite3.Connection:
    """Returns a configured SQLite connection with WAL mode and row factory."""
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path = DATABASE_PATH) -> None:
    """Initializes the database schema and full-text search index."""
    with get_connection(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS volumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT UNIQUE,
            label TEXT NOT NULL,
            mount_point TEXT NOT NULL,
            role TEXT DEFAULT 'VAULT',
            disk_name TEXT,
            is_online INTEGER DEFAULT 1,
            last_scanned REAL
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            volume_id INTEGER NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
            rel_path TEXT NOT NULL,
            abs_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            extension TEXT,
            category TEXT,
            size_bytes INTEGER,
            mtime REAL,
            blake3_hash TEXT,
            has_thumbnail INTEGER DEFAULT 0,
            status TEXT DEFAULT 'COLD_ONLINE',
            indexed_at REAL,
            UNIQUE(volume_id, rel_path)
        );

        CREATE INDEX IF NOT EXISTS idx_files_hash ON files(blake3_hash);
        CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
        CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension);
        CREATE INDEX IF NOT EXISTS idx_files_volume ON files(volume_id);

        -- FTS5 Full-Text Search virtual table
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            filename,
            rel_path,
            extension,
            category,
            content='files',
            content_rowid='id'
        );

        -- Triggers to automatically keep FTS5 synchronized with files table
        CREATE TRIGGER IF NOT EXISTS trg_files_ai AFTER INSERT ON files BEGIN
            INSERT INTO files_fts(rowid, filename, rel_path, extension, category)
            VALUES (new.id, new.filename, new.rel_path, new.extension, new.category);
        END;

        CREATE TRIGGER IF NOT EXISTS trg_files_ad AFTER DELETE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, filename, rel_path, extension, category)
            VALUES ('delete', old.id, old.filename, old.rel_path, old.extension, old.category);
        END;

        CREATE TRIGGER IF NOT EXISTS trg_files_au AFTER UPDATE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, filename, rel_path, extension, category)
            VALUES ('delete', old.id, old.filename, old.rel_path, old.extension, old.category);
            INSERT INTO files_fts(rowid, filename, rel_path, extension, category)
            VALUES (new.id, new.filename, new.rel_path, new.extension, new.category);
        END;
        """)


def get_or_create_volume(
    mount_point: str,
    label: str,
    role: str = "VAULT",
    disk_name: str | None = None,
    db_path: Path = DATABASE_PATH,
) -> int:
    """Retrieves an existing volume ID or registers a new one."""
    clean_mount = mount_point.rstrip("/\\")
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM volumes WHERE label = ? OR mount_point = ?",
            (label, clean_mount),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE volumes SET mount_point = ?, is_online = 1 WHERE id = ?",
                (clean_mount, row["id"]),
            )
            return row["id"]

        cursor = conn.execute(
            """
            INSERT INTO volumes (uuid, label, mount_point, role, disk_name, is_online, last_scanned)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (
                f"{label.lower()}-{int(time.time())}",
                label,
                clean_mount,
                role,
                disk_name,
                time.time(),
            ),
        )
        return cursor.lastrowid


def update_volume_status(volume_id: int, is_online: bool, db_path: Path = DATABASE_PATH) -> None:
    """Updates the online/offline presence flag for a volume."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE volumes SET is_online = ? WHERE id = ?",
            (1 if is_online else 0, volume_id),
        )


def check_all_volumes_online_status(db_path: Path = DATABASE_PATH) -> list[dict[str, Any]]:
    """Checks the physical existence of mount points and updates online status."""
    results = []
    with get_connection(db_path) as conn:
        volumes = conn.execute(
            "SELECT id, label, mount_point, role, is_online FROM volumes"
        ).fetchall()
        for v in volumes:
            mount = Path(v["mount_point"])
            online = mount.exists()
            if (1 if online else 0) != v["is_online"]:
                conn.execute(
                    "UPDATE volumes SET is_online = ? WHERE id = ?", (1 if online else 0, v["id"])
                )
            results.append(
                {
                    "id": v["id"],
                    "label": v["label"],
                    "mount_point": v["mount_point"],
                    "role": v["role"],
                    "is_online": online,
                }
            )
    return results


def upsert_files_batch(
    volume_id: int, records: list[dict[str, Any]], db_path: Path = DATABASE_PATH
) -> int:
    """
    Inserts or updates a batch of file records in a single high-speed transaction.
    """
    if not records:
        return 0

    now = time.time()
    query = """
    INSERT INTO files (
        volume_id, rel_path, abs_path, filename, extension,
        category, size_bytes, mtime, blake3_hash, has_thumbnail,
        status, indexed_at
    ) VALUES (
        :volume_id, :rel_path, :abs_path, :filename, :extension,
        :category, :size_bytes, :mtime, :blake3_hash, :has_thumbnail,
        :status, :indexed_at
    )
    ON CONFLICT(volume_id, rel_path) DO UPDATE SET
        abs_path = excluded.abs_path,
        filename = excluded.filename,
        extension = excluded.extension,
        category = excluded.category,
        size_bytes = excluded.size_bytes,
        mtime = excluded.mtime,
        blake3_hash = COALESCE(excluded.blake3_hash, files.blake3_hash),
        has_thumbnail = MAX(excluded.has_thumbnail, files.has_thumbnail),
        status = excluded.status,
        indexed_at = excluded.indexed_at
    """
    # Enforce volume_id and indexed_at
    for r in records:
        r["volume_id"] = volume_id
        r["indexed_at"] = now
        if "has_thumbnail" not in r:
            r["has_thumbnail"] = 0
        if "status" not in r:
            r["status"] = "COLD_ONLINE"

    with get_connection(db_path) as conn:
        conn.executemany(query, records)
        conn.execute("UPDATE volumes SET last_scanned = ? WHERE id = ?", (now, volume_id))

    return len(records)


def format_bytes(size: int) -> str:
    """Converts raw byte count into human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def search(
    query: str,
    category: str | None = None,
    volume_label: str | None = None,
    extension: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """
    Executes a high-speed search across the archive using FTS5 and SQL filters.
    Returns results, total matched count, and execution time in milliseconds.
    """
    start_time = time.perf_counter()

    conditions = []
    params: list[Any] = []

    clean_query = query.strip()
    use_fts = bool(clean_query and clean_query != "*")

    if use_fts:
        # Sanitize query for FTS5 (escape special punctuation)
        sanitized = "".join(c if c.isalnum() or c in " _-*" else " " for c in clean_query)
        # Prefix match on last term
        terms = sanitized.split()
        if terms:
            fts_expression = " ".join(f'"{t}"*' for t in terms)
            conditions.append("files.id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?)")
            params.append(fts_expression)

    if category and category != "all":
        conditions.append("files.category = ?")
        params.append(category.lower())

    if extension:
        clean_ext = extension if extension.startswith(".") else f".{extension}"
        conditions.append("files.extension = ?")
        params.append(clean_ext.lower())

    if volume_label:
        conditions.append("volumes.label = ?")
        params.append(volume_label)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_connection(db_path) as conn:
        count_sql = f"""
        SELECT COUNT(*) as total
        FROM files
        JOIN volumes ON files.volume_id = volumes.id
        {where_clause}
        """
        total = conn.execute(count_sql, params).fetchone()["total"]

        sql = f"""
        SELECT
            files.id,
            files.filename,
            files.rel_path,
            files.abs_path,
            files.extension,
            files.category,
            files.size_bytes,
            files.mtime,
            files.blake3_hash,
            files.has_thumbnail,
            files.status,
            volumes.label as volume_label,
            volumes.mount_point,
            volumes.is_online
        FROM files
        JOIN volumes ON files.volume_id = volumes.id
        {where_clause}
        ORDER BY files.mtime DESC
        LIMIT ? OFFSET ?
        """
        rows = conn.execute(sql, params + [limit, offset]).fetchall()

    duration_ms = (time.perf_counter() - start_time) * 1000

    items = []
    for r in rows:
        vol_online = bool(r["is_online"])
        # If the volume is offline, status is COLD_OFFLINE
        status = "COLD_ONLINE" if vol_online else "COLD_OFFLINE"
        items.append(
            {
                "id": r["id"],
                "filename": r["filename"],
                "rel_path": r["rel_path"],
                "abs_path": r["abs_path"],
                "extension": r["extension"],
                "category": r["category"],
                "size_bytes": r["size_bytes"],
                "size_formatted": format_bytes(r["size_bytes"] or 0),
                "mtime": r["mtime"],
                "blake3_hash": r["blake3_hash"],
                "has_thumbnail": bool(r["has_thumbnail"]),
                "volume_label": r["volume_label"],
                "mount_point": r["mount_point"],
                "is_online": vol_online,
                "status": status,
            }
        )

    return {
        "query": query,
        "total": total,
        "items": items,
        "duration_ms": round(duration_ms, 2),
    }


def get_stats(db_path: Path = DATABASE_PATH) -> dict[str, Any]:
    """Returns overview statistics across all indexed volumes."""
    with get_connection(db_path) as conn:
        total_files = conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
        total_size = conn.execute("SELECT SUM(size_bytes) as s FROM files").fetchone()["s"] or 0
        categories = conn.execute(
            "SELECT category, COUNT(*) as c, SUM(size_bytes) as s FROM files GROUP BY category"
        ).fetchall()
        volumes = conn.execute(
            "SELECT volumes.id, volumes.label, volumes.mount_point, volumes.role, volumes.is_online, volumes.last_scanned, "
            "COUNT(files.id) as file_count, SUM(files.size_bytes) as total_bytes "
            "FROM volumes LEFT JOIN files ON volumes.id = files.volume_id GROUP BY volumes.id"
        ).fetchall()

    return {
        "total_files": total_files,
        "total_size_bytes": total_size,
        "total_size_formatted": format_bytes(total_size),
        "categories": [
            {"name": c["category"], "count": c["c"], "size_formatted": format_bytes(c["s"] or 0)}
            for c in categories
        ],
        "volumes": [
            {
                "id": v["id"],
                "label": v["label"],
                "mount_point": v["mount_point"],
                "role": v["role"],
                "is_online": bool(v["is_online"]),
                "last_scanned": v["last_scanned"],
                "file_count": v["file_count"],
                "total_size_formatted": format_bytes(v["total_bytes"] or 0),
            }
            for v in volumes
        ],
    }
