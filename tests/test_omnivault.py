"""
Unit and Integration Tests for OmniVault
Tests hashing, indexing, FTS5 latency, storage profiling, and cache cleaner.
"""

import gc
import os
import time
from pathlib import Path
from PIL import Image
import pytest

from omnivault.db import (
    init_db,
    get_or_create_volume,
    upsert_files_batch,
    search,
    get_stats,
)
from omnivault.hasher import compute_blake3
from omnivault.thumbnail import generate_thumbnail
from omnivault.storage import (
    get_drive_reports,
    scan_cache_bloat,
    clean_cache_dir,
    find_duplicates,
)


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "catalog_test.db"
    init_db(db_path)
    yield db_path
    gc.collect()


def test_blake3_hasher(tmp_path):
    test_file = tmp_path / "hello.txt"
    test_file.write_text("Hello OmniVault world!")
    h1 = compute_blake3(test_file)
    assert len(h1) == 64
    assert h1 == compute_blake3(test_file)


def test_thumbnail_generation(tmp_path):
    img_path = tmp_path / "test.jpg"
    img = Image.new("RGB", (400, 300), color="blue")
    img.save(img_path)

    file_hash = compute_blake3(img_path)
    thumb_path = generate_thumbnail(img_path, file_hash)
    assert thumb_path is not None
    assert thumb_path.exists()
    assert thumb_path.suffix == ".webp"


def test_fts5_search_latency(temp_db):
    vol_id = get_or_create_volume("C:/MockVolume", "MockVol", "TEST", db_path=temp_db)

    # Insert 1,000 synthetic records
    records = []
    for i in range(1000):
        records.append({
            "rel_path": f"documents/report_{i}.pdf",
            "abs_path": f"C:/MockVolume/documents/report_{i}.pdf",
            "filename": f"report_{i}.pdf",
            "extension": ".pdf",
            "category": "documents",
            "size_bytes": 1024 * i,
            "mtime": time.time(),
            "blake3_hash": f"hash_{i}",
            "has_thumbnail": 0,
            "status": "COLD_ONLINE",
        })
    upsert_files_batch(vol_id, records, db_path=temp_db)

    # Execute search
    res = search("report_42", db_path=temp_db)
    assert res["total"] >= 1
    filenames = [item["filename"] for item in res["items"]]
    assert "report_42.pdf" in filenames
    assert res["duration_ms"] < 25.0  # Sub-25ms target


def test_drive_reports():
    reports = get_drive_reports()
    assert len(reports) >= 1
    letters = [r.letter for r in reports]
    assert "C" in letters
    c_drive = next(r for r in reports if r.letter == "C")
    assert c_drive.total_bytes > 0
    assert c_drive.used_pct > 0


def test_clean_cache_dry_run_and_execution(tmp_path):
    fake_cache = tmp_path / "fake_cache"
    fake_cache.mkdir()
    (fake_cache / "item1.tmp").write_text("temporary cache file 1")
    (fake_cache / "item2.tmp").write_text("temporary cache file 2")

    # 1. Dry run
    res_dry = clean_cache_dir(str(fake_cache), dry_run=True)
    assert res_dry["files_deleted"] == 2
    assert (fake_cache / "item1.tmp").exists()
    assert (fake_cache / "item2.tmp").exists()

    # 2. Real execution
    res_real = clean_cache_dir(str(fake_cache), dry_run=False)
    assert res_real["files_deleted"] == 2
    assert not (fake_cache / "item1.tmp").exists()
    assert not (fake_cache / "item2.tmp").exists()


def test_find_duplicates(temp_db):
    vol_id = get_or_create_volume("C:/MockVolume", "MockVol", "TEST", db_path=temp_db)
    identical_hash = "abc123def456" * 5

    records = [
        {
            "rel_path": "photos/photo_copy1.jpg",
            "abs_path": "C:/MockVolume/photos/photo_copy1.jpg",
            "filename": "photo_copy1.jpg",
            "extension": ".jpg",
            "category": "photos",
            "size_bytes": 50000,
            "mtime": time.time(),
            "blake3_hash": identical_hash,
            "has_thumbnail": 0,
            "status": "COLD_ONLINE",
        },
        {
            "rel_path": "backup/photo_copy2.jpg",
            "abs_path": "C:/MockVolume/backup/photo_copy2.jpg",
            "filename": "photo_copy2.jpg",
            "extension": ".jpg",
            "category": "photos",
            "size_bytes": 50000,
            "mtime": time.time(),
            "blake3_hash": identical_hash,
            "has_thumbnail": 0,
            "status": "COLD_ONLINE",
        },
    ]
    upsert_files_batch(vol_id, records, db_path=temp_db)

    dups = find_duplicates(min_size=1000, db_path=temp_db)
    assert len(dups) == 1
    assert dups[0]["count"] == 2
    assert dups[0]["wasted_bytes"] == 50000
