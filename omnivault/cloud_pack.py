"""
Cloud Cold-Storage Archiving & Packaging Engine for OmniVault
Specialized in packaging large pre-compressed game repacks, installers, and datasets
for cloud cold storage (Google Drive 5TB, OneDrive, external HDDs) with zero-recompression
Store Mode, Reed-Solomon recovery records, volume slicing, and shadow catalog indexing.
"""

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omnivault.config import DATABASE_PATH
from omnivault.db import format_bytes, get_connection, get_or_create_volume, upsert_files_batch
from omnivault.storage import get_drive_reports

PRECOMPRESSED_EXTENSIONS = {
    ".bin",
    ".pak",
    ".ucas",
    ".utoc",
    ".vpk",
    ".cas",
    ".bundle",
    ".iso",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".zst",
    ".mp4",
    ".mkv",
    ".webm",
    ".flac",
}


@dataclass
class PreFlightAnalysis:
    source_path: Path
    total_files: int
    total_bytes: int
    precompressed_bytes: int
    precompressed_pct: float
    is_precompressed: bool
    recommended_mode: str
    staging_drive: str | None
    staging_free_bytes: int
    has_sufficient_space: bool


def analyze_source_directory(source_path: Path) -> PreFlightAnalysis:
    """Analyzes source directory for size, pre-compression ratio, and disk staging."""
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source directory '{source_path}' does not exist.")

    total_files = 0
    total_bytes = 0
    precompressed_bytes = 0

    if source_path.is_file():
        total_files = 1
        total_bytes = source_path.stat().st_size
        if source_path.suffix.lower() in PRECOMPRESSED_EXTENSIONS:
            precompressed_bytes = total_bytes
    else:
        for root, _, files in os.walk(source_path):
            for f in files:
                total_files += 1
                fp = Path(root) / f
                try:
                    sz = fp.stat().st_size
                    total_bytes += sz
                    if fp.suffix.lower() in PRECOMPRESSED_EXTENSIONS:
                        precompressed_bytes += sz
                except OSError:
                    continue

    pct = (precompressed_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
    is_precomp = pct >= 40.0 or (total_bytes > 5 * 1024**3 and pct >= 25.0)
    rec_mode = "store" if is_precomp else "normal"

    # Find best staging drive (needs at least total_bytes * 1.12 free space)
    required_staging = int(total_bytes * 1.12)
    reports = get_drive_reports()
    # Sort drives by free space descending
    reports.sort(key=lambda r: r.free_bytes, reverse=True)

    best_drive = None
    best_free = 0
    has_space = False

    for rep in reports:
        if rep.free_bytes >= required_staging:
            best_drive = rep.letter
            best_free = rep.free_bytes
            has_space = True
            break

    if not best_drive and reports:
        best_drive = reports[0].letter
        best_free = reports[0].free_bytes
        has_space = best_free >= required_staging

    return PreFlightAnalysis(
        source_path=source_path,
        total_files=total_files,
        total_bytes=total_bytes,
        precompressed_bytes=precompressed_bytes,
        precompressed_pct=pct,
        is_precompressed=is_precomp,
        recommended_mode=rec_mode,
        staging_drive=best_drive,
        staging_free_bytes=best_free,
        has_sufficient_space=has_space,
    )


def detect_archiver() -> tuple[str, str]:
    """Detects available archiver (WinRAR or 7-Zip). Returns (tool_type, executable_path)."""
    # 1. Check WinRAR standard paths
    winrar_candidates = [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "WinRAR" / "Rar.exe",
        Path("C:\\Program Files\\WinRAR\\Rar.exe"),
        Path("C:\\Program Files (x86)\\WinRAR\\Rar.exe"),
    ]
    for cand in winrar_candidates:
        if cand.exists():
            return "winrar", str(cand)

    which_rar = shutil.which("rar") or shutil.which("Rar")
    if which_rar:
        return "winrar", which_rar

    # 2. Check 7-Zip
    sevenzip_candidates = [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "7-Zip" / "7z.exe",
        Path("C:\\Program Files\\7-Zip\\7z.exe"),
        Path("C:\\Program Files (x86)\\7-Zip\\7z.exe"),
    ]
    for cand in sevenzip_candidates:
        if cand.exists():
            return "7zip", str(cand)

    which_7z = shutil.which("7z")
    if which_7z:
        return "7zip", which_7z

    raise RuntimeError(
        "Neither WinRAR (Rar.exe) nor 7-Zip (7z.exe) was found on the system. "
        "Please install WinRAR or 7-Zip."
    )


def build_pack_command(
    source_path: Path,
    output_archive: Path,
    split_size: str = "10g",
    parity_pct: int = 3,
    password: str | None = None,
    store_mode: bool = True,
) -> tuple[str, list[str]]:
    """Constructs the optimal CLI packaging command based on available archiver."""
    tool_type, tool_path = detect_archiver()
    cmd: list[str] = [tool_path, "a"]

    if tool_type == "winrar":
        # Store mode: -m0
        cmd.append("-m0" if store_mode else "-m3")
        # Recovery record: -rrN%
        if parity_pct > 0:
            cmd.append(f"-rr{parity_pct}%")
        # Split volume: -v<size>
        if split_size:
            cmd.append(f"-v{split_size}")
        # Recurse subdirectories
        cmd.append("-r")
        # Password with encrypted headers
        if password:
            cmd.append(f"-hp{password}")
        cmd.append(str(output_archive))
        source_target = str(source_path / "*") if source_path.is_dir() else str(source_path)
        cmd.append(source_target)
    else:  # 7zip
        cmd.append("-mx=0" if store_mode else "-mx=5")
        if split_size:
            cmd.append(f"-v{split_size}")
        if password:
            cmd.append(f"-p{password}")
            cmd.append("-mhe=on")
        cmd.append(str(output_archive))
        source_target = str(source_path / "*") if source_path.is_dir() else str(source_path)
        cmd.append(source_target)

    return tool_type, cmd


def register_cloud_archive_in_catalog(
    archive_name: str,
    cloud_provider: str,
    original_path: str,
    total_bytes: int,
    volume_parts: list[Path],
    db_path: Path = DATABASE_PATH,
) -> int:
    """Registers the created cloud package and its parts into OmniVault catalog."""
    vol_label = f"Cloud-{cloud_provider.title()}"
    mount_point = f"{cloud_provider.upper()}://ColdStorage/{archive_name}"

    vol_id = get_or_create_volume(
        mount_point=mount_point,
        label=vol_label,
        role="CLOUD_VAULT",
        disk_name=f"Cloud Storage ({cloud_provider.title()})",
        db_path=db_path,
    )

    records: list[dict[str, Any]] = []
    now = time.time()

    # Register each part/volume
    if volume_parts:
        for vp in volume_parts:
            sz = vp.stat().st_size if vp.exists() else (total_bytes // len(volume_parts))
            records.append(
                {
                    "volume_id": vol_id,
                    "rel_path": f"{archive_name}/{vp.name}",
                    "abs_path": str(vp),
                    "filename": vp.name,
                    "extension": vp.suffix.lstrip(".").lower(),
                    "category": "archives",
                    "size_bytes": sz,
                    "mtime": now,
                    "blake3_hash": None,
                    "has_thumbnail": 0,
                    "status": "CLOUD_COLD",
                    "indexed_at": now,
                }
            )
    else:
        records.append(
            {
                "volume_id": vol_id,
                "rel_path": f"{archive_name}/{archive_name}.rar",
                "abs_path": mount_point,
                "filename": f"{archive_name}.rar",
                "extension": "rar",
                "category": "archives",
                "size_bytes": total_bytes,
                "mtime": now,
                "blake3_hash": None,
                "has_thumbnail": 0,
                "status": "CLOUD_COLD",
                "indexed_at": now,
            }
        )

    # Also register manifest reference to original title so searching original name hits
    clean_name = Path(original_path).name
    records.append(
        {
            "volume_id": vol_id,
            "rel_path": f"{archive_name}/[MANIFEST] {clean_name}",
            "abs_path": original_path,
            "filename": f"[MANIFEST] {clean_name}",
            "extension": "manifest",
            "category": "archives",
            "size_bytes": total_bytes,
            "mtime": now,
            "blake3_hash": None,
            "has_thumbnail": 0,
            "status": "CLOUD_MANIFEST",
            "indexed_at": now,
        }
    )

    with get_connection(db_path) as conn:
        conn.execute("UPDATE volumes SET is_online = 1 WHERE id = ?", (vol_id,))

    upsert_files_batch(vol_id, records, db_path=db_path)
    return vol_id


def run_cloud_pack(
    source_dir: Path,
    staging_dir: Path | None = None,
    archive_name: str | None = None,
    split_size: str = "10g",
    parity_pct: int = 3,
    password: str | None = None,
    cloud_provider: str = "Google Drive (5TB)",
    execute: bool = False,
    db_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """
    Main orchestration routine for cloud pack.
    Performs pre-flight analysis, chooses staging destination, builds CLI command,
    optionally executes packaging, and indexes package into OmniVault catalog.
    """
    source_path = Path(source_dir).resolve()
    analysis = analyze_source_directory(source_path)

    if not archive_name:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in source_path.name)
        archive_name = safe_name.strip("_") or "Archive_Payload"

    # Resolve staging folder
    if staging_dir:
        staging_path = Path(staging_dir).resolve()
    else:
        stg_drive = analysis.staging_drive or "C"
        staging_path = Path(f"{stg_drive}:\\OmniVault_Staging\\{archive_name}")

    output_archive = staging_path / f"{archive_name}.rar"

    tool_type, cmd = build_pack_command(
        source_path=source_path,
        output_archive=output_archive,
        split_size=split_size,
        parity_pct=parity_pct,
        password=password,
        store_mode=analysis.recommended_mode == "store",
    )

    result: dict[str, Any] = {
        "source": str(source_path),
        "total_files": analysis.total_files,
        "total_bytes": analysis.total_bytes,
        "total_formatted": format_bytes(analysis.total_bytes),
        "is_precompressed": analysis.is_precompressed,
        "precompressed_pct": round(analysis.precompressed_pct, 1),
        "recommended_mode": analysis.recommended_mode,
        "staging_dir": str(staging_path),
        "staging_drive": analysis.staging_drive,
        "staging_free": format_bytes(analysis.staging_free_bytes),
        "has_space": analysis.has_sufficient_space,
        "tool_type": tool_type,
        "command": cmd,
        "command_str": " ".join(f'"{c}"' if " " in c else c for c in cmd),
        "executed": False,
        "volume_parts": [],
        "catalog_volume_id": None,
    }

    if not execute:
        return result

    if not analysis.has_sufficient_space:
        raise OSError(
            f"Insufficient free space on staging drive {analysis.staging_drive}:. "
            f"Required: ~{format_bytes(int(analysis.total_bytes * 1.12))}, "
            f"Available: {format_bytes(analysis.staging_free_bytes)}."
        )

    # Create staging directory
    staging_path.mkdir(parents=True, exist_ok=True)

    print(f"\n[OmniVault Pack] Launching headless {tool_type} stream at full drive I/O...")
    print(f"[OmniVault Pack] Target: {staging_path}")
    print(f"[OmniVault Pack] Command: {result['command_str']}\n")

    start_t = time.perf_counter()
    proc = subprocess.run(cmd, stdout=sys.stdout, stderr=sys.stderr)
    elapsed = time.perf_counter() - start_t

    if proc.returncode != 0:
        raise RuntimeError(f"Archiver exited with error code {proc.returncode}")

    result["executed"] = True
    result["elapsed_seconds"] = round(elapsed, 2)

    # Collect generated parts
    parts = sorted(list(staging_path.glob(f"{archive_name}*.rar*")))
    result["volume_parts"] = [str(p) for p in parts]

    # Register into catalog
    vol_id = register_cloud_archive_in_catalog(
        archive_name=archive_name,
        cloud_provider=cloud_provider,
        original_path=str(source_path),
        total_bytes=analysis.total_bytes,
        volume_parts=parts,
        db_path=db_path,
    )
    result["catalog_volume_id"] = vol_id

    return result
