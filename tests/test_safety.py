"""
Unit and Regression Tests for OmniVault Collision Safety & Staging Engine
Verifies hash-based collision resolution, atomic verified copy, and data loss prevention.
"""

from __future__ import annotations

import gc
import time

import pytest

from omnivault.db import get_or_create_volume, init_db, upsert_files_batch
from omnivault.hasher import compute_blake3
from omnivault.staging import ingest_file_to_staging, offload_staging_to_vault, resolve_collision


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    """Sets up an isolated OmniVault environment with staging and vault folders."""
    home_dir = tmp_path / "omnivault_home"
    staging_dir = tmp_path / "staging"
    vault_dir = tmp_path / "vault"

    home_dir.mkdir()
    staging_dir.mkdir()
    vault_dir.mkdir()

    monkeypatch.setenv("OMNIVAULT_HOME", str(home_dir))
    monkeypatch.setattr("omnivault.config.STAGING_DIR", staging_dir)
    monkeypatch.setattr("omnivault.config.INCOMING_LOCALSEND", staging_dir / "Incoming_LocalSend")
    monkeypatch.setattr("omnivault.config.INCOMING_WIRED", staging_dir / "Incoming_Wired")
    monkeypatch.setattr("omnivault.staging.STAGING_DIR", staging_dir)
    monkeypatch.setattr("omnivault.staging.INCOMING_LOCALSEND", staging_dir / "Incoming_LocalSend")
    monkeypatch.setattr("omnivault.staging.INCOMING_WIRED", staging_dir / "Incoming_Wired")

    db_path = home_dir / "catalog.db"
    init_db(db_path)

    yield {
        "home": home_dir,
        "staging": staging_dir,
        "vault": vault_dir,
        "db": db_path,
    }
    gc.collect()


def test_resolve_collision_non_existent(tmp_path):
    target = tmp_path / "sample.jpg"
    res = resolve_collision(target, "dummyhash123")
    assert res == target


def test_resolve_collision_identical_content(tmp_path):
    target = tmp_path / "sample.jpg"
    target.write_text("Hello identical world")
    h = compute_blake3(target)

    # When file already exists and has identical hash, returns None (skip copy)
    res = resolve_collision(target, h)
    assert res is None


def test_resolve_collision_different_content(tmp_path):
    target = tmp_path / "sample.jpg"
    target.write_text("Version 1 of photo")
    new_content_file = tmp_path / "new.jpg"
    new_content_file.write_text("Version 2 of photo with same name")
    new_hash = compute_blake3(new_content_file)

    res = resolve_collision(target, new_hash)
    assert res is not None
    assert res != target
    assert f"__{new_hash[:8]}" in res.name
    assert res.suffix == ".jpg"


def test_ingest_collision_preserves_both(temp_env):
    source1 = temp_env["staging"] / "temp_src1.txt"
    source1.write_text("Doc 1 content")

    source2 = temp_env["staging"] / "temp_src2.txt"
    source2.write_text("Doc 2 content with same filename")

    # Ingest first file as invoice.pdf
    first_target = temp_env["staging"] / "invoice.pdf"
    first_target.write_text("Doc 1 content")
    res1 = ingest_file_to_staging(first_target, stream="localsend", db_path=temp_env["db"])
    assert res1 is not None
    assert not res1["is_duplicate"]

    # Ingest second file with different content but same filename
    second_target = temp_env["staging"] / "another_folder" / "invoice.pdf"
    second_target.parent.mkdir()
    second_target.write_text("Doc 2 content with same filename")
    res2 = ingest_file_to_staging(second_target, stream="localsend", db_path=temp_env["db"])
    assert res2 is not None
    assert not res2["is_duplicate"]

    # Verify both files exist in staging folder
    incoming = temp_env["staging"] / "Incoming_LocalSend"
    staged_files = list(incoming.iterdir())
    assert len(staged_files) == 2
    filenames = [f.name for f in staged_files]
    assert "invoice.pdf" in filenames
    # One file must have the hash suffix
    assert any("__" in f.name for f in staged_files)


def test_offload_collision_preserves_both(temp_env):
    db_path = temp_env["db"]
    vault_root = temp_env["vault"]
    now = time.time()
    year_str = time.strftime("%Y", time.localtime(now))
    month_str = time.strftime("%Y-%m", time.localtime(now))
    vault_lib = vault_root / "OmniVault" / "Library" / "Documents" / year_str / month_str
    vault_lib.mkdir(parents=True)

    # Pre-existing file on vault
    existing_vault_file = vault_lib / "report.pdf"
    existing_vault_file.write_text("Old 2025 archived report")
    old_hash = compute_blake3(existing_vault_file)

    # Register vault volume
    vault_vol_id = get_or_create_volume(
        str(vault_root), "VaultTest", "PRIMARY_VAULT", db_path=db_path
    )
    upsert_files_batch(
        vault_vol_id,
        [
            {
                "rel_path": existing_vault_file.relative_to(vault_root).as_posix(),
                "abs_path": str(existing_vault_file.resolve()),
                "filename": existing_vault_file.name,
                "extension": ".pdf",
                "category": "documents",
                "size_bytes": existing_vault_file.stat().st_size,
                "mtime": now,
                "blake3_hash": old_hash,
                "status": "COLD_ONLINE",
            }
        ],
        db_path=db_path,
    )

    # Staged new file with same filename but different content
    staged_file = temp_env["staging"] / "Incoming_LocalSend" / "report.pdf"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text("Brand new report with same name!")
    new_hash = compute_blake3(staged_file)

    staging_vol_id = get_or_create_volume(
        str(temp_env["staging"]), "Staging", "STAGING", db_path=db_path
    )
    upsert_files_batch(
        staging_vol_id,
        [
            {
                "rel_path": "Incoming_LocalSend/report.pdf",
                "abs_path": str(staged_file.resolve()),
                "filename": "report.pdf",
                "extension": ".pdf",
                "category": "documents",
                "size_bytes": staged_file.stat().st_size,
                "mtime": now,
                "blake3_hash": new_hash,
                "status": "WARM_LAPTOP",
            }
        ],
        db_path=db_path,
    )

    # Execute offload
    res = offload_staging_to_vault(
        vault_mount=str(vault_root),
        vault_label="VaultTest",
        dry_run=False,
        verbose=False,
        db_path=db_path,
    )

    assert res["offloaded"] == 1
    # Both files must now exist in vault directory!
    vault_files = list(vault_lib.iterdir())
    assert len(vault_files) == 2
    # Original content preserved intact
    assert existing_vault_file.read_text() == "Old 2025 archived report"
    # New file offloaded with hash suffix
    collided_file = next(f for f in vault_files if f != existing_vault_file)
    assert f"__{new_hash[:8]}" in collided_file.name
    assert collided_file.read_text() == "Brand new report with same name!"
    # Staging file deleted from NVMe
    assert not staged_file.exists()


def test_offload_identical_content_skips_and_cleans_staging(temp_env):
    db_path = temp_env["db"]
    vault_root = temp_env["vault"]
    now = time.time()
    year_str = time.strftime("%Y", time.localtime(now))
    month_str = time.strftime("%Y-%m", time.localtime(now))
    vault_lib = vault_root / "OmniVault" / "Library" / "Documents" / year_str / month_str
    vault_lib.mkdir(parents=True)

    # Pre-existing file on vault
    identical_text = "Exactly identical document contents"
    existing_vault_file = vault_lib / "duplicate.pdf"
    existing_vault_file.write_text(identical_text)
    file_hash = compute_blake3(existing_vault_file)

    # Staged identical file
    staged_file = temp_env["staging"] / "Incoming_LocalSend" / "duplicate.pdf"
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    staged_file.write_text(identical_text)

    staging_vol_id = get_or_create_volume(
        str(temp_env["staging"]), "Staging", "STAGING", db_path=db_path
    )
    upsert_files_batch(
        staging_vol_id,
        [
            {
                "rel_path": "Incoming_LocalSend/duplicate.pdf",
                "abs_path": str(staged_file.resolve()),
                "filename": "duplicate.pdf",
                "extension": ".pdf",
                "category": "documents",
                "size_bytes": staged_file.stat().st_size,
                "mtime": now,
                "blake3_hash": file_hash,
                "status": "WARM_LAPTOP",
            }
        ],
        db_path=db_path,
    )

    # Execute offload
    res = offload_staging_to_vault(
        vault_mount=str(vault_root),
        vault_label="VaultTest",
        dry_run=False,
        verbose=False,
        db_path=db_path,
    )

    assert res["offloaded"] == 1
    # Only 1 file should exist on vault (no duplicate written)
    vault_files = list(vault_lib.iterdir())
    assert len(vault_files) == 1
    # Staged copy deleted
    assert not staged_file.exists()
