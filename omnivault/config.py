"""
Configuration for OmniVault
Defines storage paths, default volume mappings, category rules, and system constants.
"""

import os
from pathlib import Path

# Base directories
USER_HOME = Path(os.path.expanduser("~"))
OMNIVAULT_HOME = USER_HOME / ".omnivault"
OMNIVAULT_HOME.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = OMNIVAULT_HOME / "catalog.db"
THUMBNAILS_DIR = OMNIVAULT_HOME / "thumbnails"
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

# Default staging directory for incoming mobile files (LocalSend / Wired)
STAGING_DIR = Path("F:/OmniVault_Staging")
INCOMING_LOCALSEND = STAGING_DIR / "Incoming_LocalSend"
INCOMING_WIRED = STAGING_DIR / "Incoming_Wired"

# Known default external volumes
DEFAULT_VOLUMES = {
    "I:": {"label": "Main", "role": "PRIMARY_VAULT", "disk_name": "WD3200BPVT (320GB)"},
    "H:": {"label": "Mini", "role": "SECONDARY_VAULT", "disk_name": "WD3200BPVT (320GB)"},
}

# Ignored directories during scans
IGNORED_DIRS = {
    "$recycle.bin",
    "system volume information",
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
}

# Categorization by extension
CATEGORIES = {
    "photos": {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".tiff",
        ".raw",
        ".cr2",
        ".nef",
        ".arw",
        ".heic",
        ".dng",
    },
    "videos": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v", ".3gp", ".ts"},
    "audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"},
    "documents": {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
        ".txt",
        ".md",
        ".csv",
        ".rtf",
        ".epub",
    },
    "code": {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".html",
        ".css",
        ".json",
        ".yaml",
        ".yml",
        ".c",
        ".cpp",
        ".h",
        ".rs",
        ".go",
        ".java",
        ".ps1",
        ".bat",
        ".sh",
    },
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst", ".iso"},
    "executables": {".exe", ".msi", ".dll", ".apk", ".bin"},
}


def get_category(extension: str) -> str:
    """Classifies file extension into a standard category."""
    ext = extension.lower()
    for category, extensions in CATEGORIES.items():
        if ext in extensions:
            return category
    return "other"
