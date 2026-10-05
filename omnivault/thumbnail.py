"""
Micro-Thumbnail Generator for OmniVault
Extracts ultra-compact WebP thumbnails for offline visual previewing.
"""

from pathlib import Path

from PIL import Image, ImageOps

from omnivault.config import THUMBNAILS_DIR

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".gif"}


def generate_thumbnail(
    filepath: Path | str, file_hash: str, max_size: tuple[int, int] = (160, 160)
) -> Path | None:
    """
    Generates a tiny WebP thumbnail and saves it to the local cache.
    Returns the path to the thumbnail if successful, or None.
    """
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_IMAGE_EXTS:
        return None

    # Subdirectory sharding based on the first two hex characters of the hash
    shard = file_hash[:2]
    shard_dir = THUMBNAILS_DIR / shard
    shard_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = shard_dir / f"{file_hash}.webp"

    if thumb_path.exists():
        return thumb_path

    try:
        with Image.open(path) as img:
            # Auto-rotate based on EXIF orientation tag
            img = ImageOps.exif_transpose(img)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Convert RGBA/P to RGB if saving as WebP
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                # Keep alpha for WebP
                img.save(thumb_path, "WEBP", quality=75, method=4)
            else:
                img = img.convert("RGB")
                img.save(thumb_path, "WEBP", quality=75, method=4)

            return thumb_path
    except Exception:
        # Ignore corrupted or unreadable images
        return None
