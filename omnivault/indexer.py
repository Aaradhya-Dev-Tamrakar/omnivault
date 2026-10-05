"""
Indexing Orchestrator for OmniVault
Coordinates scanning, cryptographic verification, batch database commits, and manifest backup.
"""

import time
from pathlib import Path
from typing import Optional
from omnivault.db import (
    init_db,
    get_or_create_volume,
    upsert_files_batch,
    format_bytes,
)
from omnivault.scanner import scan_directory


def index_volume(
    mount_point: str,
    label: str,
    role: str = "VAULT",
    disk_name: Optional[str] = None,
    compute_hash: bool = True,
    make_thumbnails: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Indexes a storage volume into the OmniVault SQLite database.
    
    Args:
        mount_point: Drive letter or root directory (e.g. 'I:/' or 'H:/')
        label: Human-friendly volume label ('Main', 'Mini', 'Laptop_Staging')
        role: Role of the volume ('PRIMARY_VAULT', 'SECONDARY_VAULT', 'STAGING')
        disk_name: Hardware drive descriptor (e.g. 'WD3200BPVT 320GB')
        compute_hash: Whether to compute BLAKE3 hashes for file integrity & deduplication
        make_thumbnails: Whether to extract WebP thumbnails for offline browsing
        verbose: Whether to print progress to console
    """
    init_db()
    start_time = time.perf_counter()

    root_path = Path(mount_point)
    if not root_path.exists():
        raise FileNotFoundError(f"Mount point does not exist or is disconnected: {mount_point}")

    volume_id = get_or_create_volume(
        mount_point=mount_point,
        label=label,
        role=role,
        disk_name=disk_name,
    )

    total_files = 0
    total_bytes = 0

    def progress(count: int, bytes_so_far: int, current_path: str):
        if verbose:
            elapsed = time.perf_counter() - start_time
            rate = count / elapsed if elapsed > 0 else 0
            print(f"\r[OmniVault] Indexing '{label}' -> {count} files ({format_bytes(bytes_so_far)}) @ {rate:.0f} files/s", end="", flush=True)

    for batch in scan_directory(
        root_path=root_path,
        compute_hash=compute_hash,
        make_thumbnails=make_thumbnails,
        batch_size=500,
        progress_callback=progress,
    ):
        upsert_files_batch(volume_id, batch)
        total_files += len(batch)
        total_bytes += sum(b["size_bytes"] for b in batch)

    duration = time.perf_counter() - start_time
    if verbose:
        print(f"\n[OmniVault] Finished indexing '{label}': {total_files} files ({format_bytes(total_bytes)}) in {duration:.2f}s.")

    return {
        "volume_id": volume_id,
        "label": label,
        "mount_point": mount_point,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size_formatted": format_bytes(total_bytes),
        "duration_seconds": round(duration, 2),
    }
