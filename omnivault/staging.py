"""
Staging & Ingestion Engine for OmniVault
Handles incoming files from LocalSend and Wired phone connections, with differential deduplication
and automated offload to the External Cold Vault.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from omnivault.config import (
    INCOMING_LOCALSEND,
    INCOMING_WIRED,
    SETTINGS,
    STAGING_DIR,
    get_category,
)
from omnivault.db import (
    format_bytes,
    get_connection,
    get_or_create_volume,
    upsert_files_batch,
)
from omnivault.hasher import compute_blake3
from omnivault.thumbnail import generate_thumbnail


def ensure_staging_dirs():
    """Creates staging intake folders if not already present."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    INCOMING_LOCALSEND.mkdir(parents=True, exist_ok=True)
    INCOMING_WIRED.mkdir(parents=True, exist_ok=True)


def resolve_collision(dest: Path, file_hash: str) -> Path | None:
    """
    Returns a safe destination path, or None if an identical file (same hash) already exists at dest.
    If a different file exists at dest, appends a content-hash suffix: <stem>__<hash[:8]><suffix>.
    """
    if not dest.exists():
        return dest

    try:
        if compute_blake3(dest) == file_hash:
            return None  # Identical content already archived / present
    except Exception:
        pass

    stem, suffix = dest.stem, dest.suffix
    candidate = dest.with_name(f"{stem}__{file_hash[:8]}{suffix}")
    n = 1
    while candidate.exists():
        try:
            if compute_blake3(candidate) == file_hash:
                return None  # Identical file already exists with candidate name
        except Exception:
            pass
        candidate = dest.with_name(f"{stem}__{file_hash[:8]}_{n}{suffix}")
        n += 1
    return candidate


def ingest_file_to_staging(
    src_path: Path | str,
    stream: str = "localsend",
    delete_source: bool = False,
    db_path: Path | None = None,
) -> dict | None:
    """
    Ingests a single file into the staging pipeline.
    Calculates BLAKE3 hash, checks for duplicates, and records in catalog.
    """
    src = Path(src_path)
    if not src.is_file():
        return None

    ensure_staging_dirs()
    dest_dir = INCOMING_LOCALSEND if stream == "localsend" else INCOMING_WIRED

    # Calculate BLAKE3 hash of source file
    file_hash = compute_blake3(src)
    stat_res = src.stat()
    ext = src.suffix.lower()
    category = get_category(ext)

    dest = resolve_collision(dest_dir / src.name, file_hash)
    if dest is None:
        # File with identical content is already in staging
        if delete_source and src.resolve() != (dest_dir / src.name).resolve():
            src.unlink()
        return {
            "record": {
                "rel_path": (dest_dir / src.name).relative_to(STAGING_DIR).as_posix(),
                "abs_path": str((dest_dir / src.name).resolve()),
                "filename": src.name,
                "extension": ext,
                "category": category,
                "size_bytes": stat_res.st_size,
                "blake3_hash": file_hash,
            },
            "is_duplicate": True,
            "existing_path": str((dest_dir / src.name).resolve()),
        }

    # If copying from outside staging
    if src.resolve() != dest.resolve():
        partial_dest = dest.with_name(dest.name + ".partial")
        shutil.copy2(src, partial_dest)
        new_hash = compute_blake3(partial_dest)
        if new_hash != file_hash:
            partial_dest.unlink(missing_ok=True)
            raise OSError(f"Integrity check failed during ingest of {src.name}!")
        partial_dest.replace(dest)
        if delete_source:
            src.unlink()

    # Check if duplicate exists in the catalog across any volume
    kwargs = {"db_path": db_path} if db_path else {}
    with get_connection(**kwargs) as conn:
        existing = conn.execute(
            "SELECT abs_path, volume_id FROM files WHERE blake3_hash = ?", (file_hash,)
        ).fetchone()

    # Generate thumbnail if image
    has_thumb = 0
    if category == "photos":
        thumb = generate_thumbnail(dest, file_hash)
        if thumb:
            has_thumb = 1

    # Register in Staging volume
    vol_id = get_or_create_volume(
        mount_point=str(STAGING_DIR),
        label="Staging",
        role="STAGING",
        disk_name="Laptop NVMe SSD",
        **kwargs,
    )

    record = {
        "rel_path": dest.relative_to(STAGING_DIR).as_posix(),
        "abs_path": str(dest.resolve()),
        "filename": dest.name,
        "extension": ext,
        "category": category,
        "size_bytes": stat_res.st_size,
        "mtime": stat_res.st_mtime,
        "blake3_hash": file_hash,
        "has_thumbnail": has_thumb,
        "status": "WARM_LAPTOP",
    }

    upsert_files_batch(vol_id, [record], **kwargs)

    return {
        "record": record,
        "is_duplicate": existing is not None,
        "existing_path": existing["abs_path"] if existing else None,
    }


def import_wired_folder(
    source_folder: Path | str,
    skip_existing: bool = True,
    verbose: bool = True,
    db_path: Path | None = None,
) -> dict:
    """
    Imports files from a wired phone folder (e.g. MTP mounted drive or folder)
    with differential deduplication.
    """
    source = Path(source_folder)
    if not source.exists():
        raise FileNotFoundError(f"Source folder not found: {source}")

    ensure_staging_dirs()
    imported_count = 0
    skipped_count = 0
    total_bytes = 0

    files_to_process = [f for f in source.rglob("*") if f.is_file()]

    kwargs = {"db_path": db_path} if db_path else {}
    with get_connection(**kwargs) as conn:
        known_hashes = {
            row["blake3_hash"]
            for row in conn.execute(
                "SELECT blake3_hash FROM files WHERE blake3_hash IS NOT NULL"
            ).fetchall()
        }

    for f in files_to_process:
        try:
            h = compute_blake3(f)
            if skip_existing and h in known_hashes:
                skipped_count += 1
                if verbose:
                    print(f"Skipped duplicate: {f.name}")
                continue

            res = ingest_file_to_staging(f, stream="wired", db_path=db_path)
            if res:
                imported_count += 1
                total_bytes += res["record"]["size_bytes"]
                known_hashes.add(h)
                if verbose:
                    print(f"Imported: {f.name} ({format_bytes(res['record']['size_bytes'])})")
        except Exception as e:
            if verbose:
                print(f"Error importing {f.name}: {e}")

    return {
        "imported": imported_count,
        "skipped": skipped_count,
        "total_bytes": total_bytes,
        "total_formatted": format_bytes(total_bytes),
    }


def offload_staging_to_vault(
    vault_mount: str | None = None,
    vault_label: str | None = None,
    vault_subdir: str = "OmniVault/Library",
    dry_run: bool = False,
    verbose: bool = True,
    db_path: Path | None = None,
) -> dict:
    """
    Offloads files from staging to the external cold vault when the drive is connected.
    Resolves naming collisions with content-hash suffix, verifies cryptographic hash
    after transfer, updates catalog to COLD_ONLINE, and removes staged copy from laptop NVMe.
    """
    target_mount = vault_mount or SETTINGS.default_vault_mount or "I:/"
    target_label = vault_label or SETTINGS.default_vault_label or "Main"

    vault_root = Path(target_mount)
    if not vault_root.exists():
        raise FileNotFoundError(f"External Vault drive {target_mount} is disconnected.")

    target_base = vault_root / vault_subdir
    if not dry_run:
        target_base.mkdir(parents=True, exist_ok=True)

    kwargs = {"db_path": db_path} if db_path else {}
    staging_vol_id = get_or_create_volume(str(STAGING_DIR), "Staging", "STAGING", **kwargs)
    vault_vol_id = get_or_create_volume(target_mount, target_label, "PRIMARY_VAULT", **kwargs)

    with get_connection(**kwargs) as conn:
        staged_files = conn.execute(
            "SELECT * FROM files WHERE volume_id = ?", (staging_vol_id,)
        ).fetchall()

    if not staged_files:
        if verbose:
            print("[OmniVault] Staging area is clean. Nothing to offload.")
        return {"offloaded": 0, "bytes": 0, "formatted": "0 B"}

    offloaded_count = 0
    total_bytes = 0

    for f in staged_files:
        src = Path(f["abs_path"])
        if not src.exists():
            continue

        category = f["category"] or "other"
        mtime = f["mtime"] or time.time()
        year_str = time.strftime("%Y", time.localtime(mtime))
        month_str = time.strftime("%Y-%m", time.localtime(mtime))

        dest_folder = target_base / category.capitalize() / year_str / month_str
        initial_dest = dest_folder / src.name
        dest_file = resolve_collision(initial_dest, f["blake3_hash"])

        if dest_file is None:
            # Identical file already archived on vault!
            if verbose:
                print(
                    f"[Deduplicated] {src.name} already in vault ({initial_dest}), skipping copy."
                )
            if not dry_run:
                with get_connection(**kwargs) as conn:
                    conn.execute("DELETE FROM files WHERE id = ?", (f["id"],))
                src.unlink()
            offloaded_count += 1
            total_bytes += f["size_bytes"]
            continue

        if not dry_run:
            dest_folder.mkdir(parents=True, exist_ok=True)
            partial_dest = dest_file.with_name(dest_file.name + ".partial")
            shutil.copy2(src, partial_dest)

            # Integrity check before replacing
            new_hash = compute_blake3(partial_dest)
            if new_hash != f["blake3_hash"]:
                partial_dest.unlink(missing_ok=True)
                raise OSError(
                    f"Integrity check failed for {src.name}! Hash mismatch: expected {f['blake3_hash']}, got {new_hash}"
                )

            # Atomic replace
            partial_dest.replace(dest_file)

            # Record in vault volume
            rel_path = dest_file.relative_to(vault_root).as_posix()
            record = {
                "rel_path": rel_path,
                "abs_path": str(dest_file.resolve()),
                "filename": dest_file.name,
                "extension": f["extension"],
                "category": f["category"],
                "size_bytes": f["size_bytes"],
                "mtime": f["mtime"],
                "blake3_hash": f["blake3_hash"],
                "has_thumbnail": f["has_thumbnail"],
                "status": "COLD_ONLINE",
            }
            upsert_files_batch(vault_vol_id, [record], **kwargs)

            # Delete from staging volume and disk
            with get_connection(**kwargs) as conn:
                conn.execute("DELETE FROM files WHERE id = ?", (f["id"],))
            src.unlink()

        offloaded_count += 1
        total_bytes += f["size_bytes"]
        if verbose:
            tag = "[Would Offload]" if dry_run else "[Offloaded]"
            print(f"{tag} {src.name} -> {dest_file}")

    return {
        "offloaded": offloaded_count,
        "bytes": total_bytes,
        "formatted": format_bytes(total_bytes),
    }
