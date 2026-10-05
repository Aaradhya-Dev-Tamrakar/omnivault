"""
Unit Tests for OmniVault Vault Integrity Engine
Verifies cryptographic validation, corruption detection, and missing file discovery.
"""

from __future__ import annotations

import gc

import pytest

from omnivault.db import get_or_create_volume, init_db, upsert_files_batch
from omnivault.hasher import compute_blake3
from omnivault.verify import verify_vault_integrity


@pytest.fixture
def mock_vault(tmp_path):
    db_path = tmp_path / "catalog_verify.db"
    init_db(db_path)

    mount_dir = tmp_path / "TestDrive"
    mount_dir.mkdir()

    # Create 3 sample files on disk
    f1 = mount_dir / "doc1.txt"
    f1.write_text("Integrity doc 1")

    f2 = mount_dir / "doc2.txt"
    f2.write_text("Integrity doc 2")

    f3 = mount_dir / "doc3.txt"
    f3.write_text("Integrity doc 3")

    vol_id = get_or_create_volume(
        mount_point=str(mount_dir),
        label="TestDrive",
        role="PRIMARY_VAULT",
        db_path=db_path,
    )

    records = [
        {
            "rel_path": "doc1.txt",
            "abs_path": str(f1.resolve()),
            "filename": "doc1.txt",
            "extension": ".txt",
            "category": "documents",
            "size_bytes": f1.stat().st_size,
            "mtime": f1.stat().st_mtime,
            "blake3_hash": compute_blake3(f1),
            "status": "COLD_ONLINE",
        },
        {
            "rel_path": "doc2.txt",
            "abs_path": str(f2.resolve()),
            "filename": "doc2.txt",
            "extension": ".txt",
            "category": "documents",
            "size_bytes": f2.stat().st_size,
            "mtime": f2.stat().st_mtime,
            "blake3_hash": compute_blake3(f2),
            "status": "COLD_ONLINE",
        },
        {
            "rel_path": "doc3.txt",
            "abs_path": str(f3.resolve()),
            "filename": "doc3.txt",
            "extension": ".txt",
            "category": "documents",
            "size_bytes": f3.stat().st_size,
            "mtime": f3.stat().st_mtime,
            "blake3_hash": compute_blake3(f3),
            "status": "COLD_ONLINE",
        },
    ]
    upsert_files_batch(vol_id, records, db_path=db_path)

    yield {
        "db": db_path,
        "mount": mount_dir,
        "files": [f1, f2, f3],
        "vol_label": "TestDrive",
    }
    gc.collect()


def test_verify_vault_healthy(mock_vault):
    report = verify_vault_integrity(
        volume_identifier=mock_vault["vol_label"],
        db_path=mock_vault["db"],
    )

    assert report["status"] == "HEALTHY"
    assert report["total_files_checked"] == 3
    assert report["total_ok"] == 3
    assert report["total_changed"] == 0
    assert report["total_missing"] == 0


def test_verify_vault_detects_changed_content(mock_vault):
    # Alter content of doc2.txt (simulate silent corruption or external edit)
    f2 = mock_vault["files"][1]
    f2.write_text("Corrupted content with invalid hash!")

    report = verify_vault_integrity(
        volume_identifier=mock_vault["vol_label"],
        db_path=mock_vault["db"],
    )

    assert report["status"] == "CORRUPTED_OR_DESYNCED"
    assert report["total_files_checked"] == 3
    assert report["total_ok"] == 2
    assert report["total_changed"] == 1
    assert report["total_missing"] == 0
    assert report["volumes"][0]["changed_files"][0]["filename"] == "doc2.txt"


def test_verify_vault_detects_missing_file(mock_vault):
    # Delete doc3.txt from disk
    f3 = mock_vault["files"][2]
    f3.unlink()

    report = verify_vault_integrity(
        volume_identifier=mock_vault["vol_label"],
        db_path=mock_vault["db"],
    )

    assert report["status"] == "CORRUPTED_OR_DESYNCED"
    assert report["total_files_checked"] == 3
    assert report["total_ok"] == 2
    assert report["total_changed"] == 0
    assert report["total_missing"] == 1
    assert report["volumes"][0]["missing_files"][0]["filename"] == "doc3.txt"


def test_verify_vault_sample(mock_vault):
    # Check with sample percentage
    report = verify_vault_integrity(
        volume_identifier=mock_vault["vol_label"],
        sample_pct=33.3,
        db_path=mock_vault["db"],
    )
    assert report["total_files_checked"] >= 1
    assert report["status"] == "HEALTHY"
