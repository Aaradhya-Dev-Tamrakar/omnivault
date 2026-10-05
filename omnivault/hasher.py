"""
High-Speed Cryptographic Hashing for OmniVault
Uses BLAKE3 (SIMD accelerated) with streaming chunk reads.
"""

from pathlib import Path
from typing import Optional

try:
    import blake3
    HAS_BLAKE3 = True
except ImportError:
    import hashlib
    HAS_BLAKE3 = False


def compute_blake3(filepath: Path | str, chunk_size: int = 1024 * 1024) -> str:
    """
    Computes BLAKE3 cryptographic hash for a file using streaming chunks.
    Falls back to blake2b if blake3 is not installed.
    """
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    if HAS_BLAKE3:
        hasher = blake3.blake3()
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    else:
        hasher = hashlib.blake2b()
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()


def compute_fast_sample(filepath: Path | str, sample_size: int = 65536) -> str:
    """
    Computes an ultra-fast partial hash (first 64KB + last 64KB + file size).
    Useful for preliminary deduplication detection on multi-gigabyte files.
    """
    path = Path(filepath)
    try:
        size = path.stat().st_size
    except OSError:
        return ""

    if size <= sample_size * 2:
        return compute_blake3(path)

    if HAS_BLAKE3:
        hasher = blake3.blake3()
    else:
        hasher = hashlib.blake2b()

    hasher.update(str(size).encode("utf-8"))
    with open(path, "rb") as f:
        hasher.update(f.read(sample_size))
        f.seek(-sample_size, 2)
        hasher.update(f.read(sample_size))

    return hasher.hexdigest()
