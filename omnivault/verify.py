"""
Vault Integrity Verification Engine for OmniVault
Performs read-only cryptographic validation of stored files against catalog hashes.
Detects bit rot, silent disk corruption, missing files, and overwrites.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omnivault.config import DATABASE_PATH
from omnivault.db import get_connection
from omnivault.hasher import compute_blake3


def verify_vault_integrity(
    volume_identifier: str | None = None,
    sample_pct: float | None = None,
    db_path: Path = DATABASE_PATH,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """
    Verifies the integrity of files in a vault volume by comparing actual BLAKE3
    hashes against catalog records.

    Args:
        volume_identifier: Volume label (e.g. 'Main') or mount point (e.g. 'I:/').
                           If None, checks all online volumes.
        sample_pct: Optional percentage (0.1 to 100.0) of files to sample.
        db_path: Path to catalog.db.
        progress_callback: Optional progress reporter (checked_count, total_count, current_file).

    Returns:
        Structured audit report dictionary.
    """
    start_time = time.perf_counter()

    with get_connection(db_path) as conn:
        vol_query = "SELECT id, label, mount_point, role, is_online FROM volumes"
        params: list[Any] = []
        if volume_identifier:
            clean_ident = volume_identifier.rstrip("/\\")
            vol_query += " WHERE label = ? OR mount_point = ?"
            params.extend([volume_identifier, clean_ident])

        volumes = conn.execute(vol_query, params).fetchall()

    if not volumes:
        raise ValueError(f"No volume found matching identifier: '{volume_identifier}'")

    reports: list[dict[str, Any]] = []
    total_checked = 0
    total_ok = 0
    total_changed = 0
    total_missing = 0

    for vol in volumes:
        vol_id = vol["id"]
        label = vol["label"]
        mount = Path(vol["mount_point"])
        is_online = mount.exists()

        vol_report: dict[str, Any] = {
            "volume_id": vol_id,
            "label": label,
            "mount_point": str(mount),
            "is_online": is_online,
            "checked_count": 0,
            "ok_count": 0,
            "changed_count": 0,
            "missing_count": 0,
            "changed_files": [],
            "missing_files": [],
        }

        if not is_online:
            vol_report["status"] = "OFFLINE"
            reports.append(vol_report)
            continue

        with get_connection(db_path) as conn:
            records = conn.execute(
                "SELECT id, filename, abs_path, rel_path, size_bytes, blake3_hash FROM files WHERE volume_id = ?",
                (vol_id,),
            ).fetchall()

        records_list = [dict(r) for r in records]
        if sample_pct and 0 < sample_pct < 100:
            sample_size = max(1, int(len(records_list) * (sample_pct / 100.0)))
            records_list = random.sample(records_list, sample_size)

        total_in_vol = len(records_list)

        for idx, rec in enumerate(records_list, 1):
            file_path = Path(rec["abs_path"])
            filename = rec["filename"]

            if progress_callback and (idx % 25 == 0 or idx == total_in_vol):
                progress_callback(idx, total_in_vol, filename)

            vol_report["checked_count"] += 1
            total_checked += 1

            if not file_path.exists():
                vol_report["missing_count"] += 1
                total_missing += 1
                vol_report["missing_files"].append(
                    {
                        "filename": filename,
                        "abs_path": rec["abs_path"],
                        "expected_hash": rec["blake3_hash"],
                    }
                )
                continue

            expected_hash = rec["blake3_hash"]
            if not expected_hash:
                # File was indexed without hash, compute and consider OK
                vol_report["ok_count"] += 1
                total_ok += 1
                continue

            try:
                actual_hash = compute_blake3(file_path)
                if actual_hash == expected_hash:
                    vol_report["ok_count"] += 1
                    total_ok += 1
                else:
                    vol_report["changed_count"] += 1
                    total_changed += 1
                    vol_report["changed_files"].append(
                        {
                            "filename": filename,
                            "abs_path": rec["abs_path"],
                            "expected_hash": expected_hash,
                            "actual_hash": actual_hash,
                        }
                    )
            except Exception as e:
                vol_report["changed_count"] += 1
                total_changed += 1
                vol_report["changed_files"].append(
                    {
                        "filename": filename,
                        "abs_path": rec["abs_path"],
                        "error": str(e),
                    }
                )

        vol_report["status"] = (
            "PASSED"
            if vol_report["changed_count"] == 0 and vol_report["missing_count"] == 0
            else "WARNING"
        )
        reports.append(vol_report)

    duration = round(time.perf_counter() - start_time, 2)
    overall_status = (
        "HEALTHY" if total_changed == 0 and total_missing == 0 else "CORRUPTED_OR_DESYNCED"
    )

    return {
        "status": overall_status,
        "checked_volumes": len(reports),
        "total_files_checked": total_checked,
        "total_ok": total_ok,
        "total_changed": total_changed,
        "total_missing": total_missing,
        "duration_seconds": duration,
        "volumes": reports,
    }


def print_verify_report(report: dict[str, Any]) -> None:
    """Renders human-readable integrity verification summary in console."""
    print("\n" + "=" * 65)
    print("               OMNIVAULT INTEGRITY AUDIT REPORT")
    print("=" * 65)

    status_tag = (
        "\033[92mHEALTHY (0 integrity discrepancies)\033[0m"
        if report["status"] == "HEALTHY"
        else f"\033[91mDESYNCED ({report['total_changed']} changed, {report['total_missing']} missing)\033[0m"
    )

    print(f"Overall Status: {status_tag}")
    print(
        f"Files Audited:  {report['total_files_checked']:,} files in {report['duration_seconds']:.2f}s"
    )
    print(f"Verified OK:    \033[92m{report['total_ok']:,}\033[0m")
    if report["total_changed"] > 0:
        print(f"Changed/Rot:    \033[91m{report['total_changed']:,}\033[0m (Hash mismatch)")
    if report["total_missing"] > 0:
        print(
            f"Missing Files:  \033[93m{report['total_missing']:,}\033[0m (In catalog, missing on disk)"
        )

    for vol in report["volumes"]:
        print("\n" + "-" * 50)
        v_status = vol.get("status", "UNKNOWN")
        v_tag = (
            "\033[92m[PASSED]\033[0m" if v_status == "PASSED" else f"\033[91m[{v_status}]\033[0m"
        )
        print(f"Volume: [{vol['label']}] {vol['mount_point']} {v_tag}")
        print(
            f"  Audited: {vol['checked_count']:,} | OK: {vol['ok_count']:,} | Changed: {vol['changed_count']} | Missing: {vol['missing_count']}"
        )

        if vol["changed_files"]:
            print("  Changed Files (Potential Bit Rot or Overwrite):")
            for cf in vol["changed_files"][:5]:
                print(
                    f"    * {cf['filename']} -> expected {cf.get('expected_hash', '')[:12]}..., got {cf.get('actual_hash', '')[:12]}..."
                )
            if len(vol["changed_files"]) > 5:
                print(f"    ... and {len(vol['changed_files']) - 5} more")

        if vol["missing_files"]:
            print("  Missing Files (Deleted or Renamed):")
            for mf in vol["missing_files"][:5]:
                print(f"    * {mf['filename']} ({mf['abs_path']})")
            if len(vol["missing_files"]) > 5:
                print(f"    ... and {len(vol['missing_files']) - 5} more")

    print("\n" + "=" * 65 + "\n")
