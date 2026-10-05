"""
Configuration for OmniVault.

Resolution order:
  1. ``OMNIVAULT_HOME`` environment variable (directory), else ``~/.omnivault``
  2. ``<OMNIVAULT_HOME>/config.toml`` user settings, merged over built-in defaults

Importing this module has no filesystem side effects. Directories and the default
config file are created by :func:`ensure_dirs`, which ``db.init_db`` calls.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    """Raised when config.toml cannot be parsed or has invalid values."""


def _resolve_home() -> Path:
    env = os.environ.get("OMNIVAULT_HOME")
    return Path(env).expanduser() if env else Path.home() / ".omnivault"


OMNIVAULT_HOME = _resolve_home()
CONFIG_PATH = OMNIVAULT_HOME / "config.toml"
DATABASE_PATH = OMNIVAULT_HOME / "catalog.db"
THUMBNAILS_DIR = OMNIVAULT_HOME / "thumbnails"

DEFAULT_CONFIG_TEMPLATE = """\
# OmniVault user configuration
# Paths accept "~" and forward or back slashes. Missing directories are skipped.

[paths]
# Landing zone for files arriving from your phone before they are offloaded
# to a cold vault. Defaults to <OMNIVAULT_HOME>/staging when omitted.
# staging_dir = "D:/OmniVault_Staging"

[vault]
# Default target for `omnivault offload` when --vault is not given.
# default_mount = "E:/"
# default_label = "Main"

[storage]
# Roots scanned for regenerable dev folders (node_modules, .venv, build, ...).
dev_scan_roots = ["~/Downloads", "~/Documents"]
# Extra folders scanned by `large-files` in addition to the catalog.
large_file_dirs = ["~/Downloads", "~/Videos", "~/.lmstudio/models", "~/.ollama/models"]

[web]
host = "127.0.0.1"
port = 7890
"""


def _as_path(value: Any, key: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{key}' must be a non-empty string path, got {value!r}")
    return Path(value).expanduser()


def _as_path_list(value: Any, key: str) -> list[Path]:
    if not isinstance(value, list):
        raise ConfigError(f"'{key}' must be a list of string paths, got {value!r}")
    return [_as_path(v, key) for v in value]


@dataclass(frozen=True)
class Settings:
    """Effective OmniVault settings (defaults merged with config.toml)."""

    home: Path
    staging_dir: Path
    default_vault_mount: str | None = None
    default_vault_label: str = "Main"
    dev_scan_roots: list[Path] = field(default_factory=list)
    large_file_dirs: list[Path] = field(default_factory=list)
    web_host: str = "127.0.0.1"
    web_port: int = 7890

    @property
    def incoming_localsend(self) -> Path:
        return self.staging_dir / "Incoming_LocalSend"

    @property
    def incoming_wired(self) -> Path:
        return self.staging_dir / "Incoming_Wired"


def load_settings(home: Path | None = None) -> Settings:
    """Load settings from ``<home>/config.toml`` (if present) over built-in defaults."""
    home = home or OMNIVAULT_HOME
    defaults = tomllib.loads(DEFAULT_CONFIG_TEMPLATE)
    user: dict[str, Any] = {}
    cfg_path = home / "config.toml"
    if cfg_path.is_file():
        try:
            user = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            raise ConfigError(f"Invalid config file {cfg_path}: {exc}") from exc

    def get(section: str, key: str, fallback: Any = None) -> Any:
        if key in user.get(section, {}):
            return user[section][key]
        return defaults.get(section, {}).get(key, fallback)

    staging_raw = get("paths", "staging_dir")
    staging = _as_path(staging_raw, "paths.staging_dir") if staging_raw else home / "staging"

    mount = get("vault", "default_mount")
    if mount is not None and not isinstance(mount, str):
        raise ConfigError(f"'vault.default_mount' must be a string, got {mount!r}")

    port = get("web", "port", 7890)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError(f"'web.port' must be an integer 1-65535, got {port!r}")

    return Settings(
        home=home,
        staging_dir=staging,
        default_vault_mount=mount or None,
        default_vault_label=str(get("vault", "default_label", "Main")),
        dev_scan_roots=_as_path_list(
            get("storage", "dev_scan_roots", []), "storage.dev_scan_roots"
        ),
        large_file_dirs=_as_path_list(
            get("storage", "large_file_dirs", []), "storage.large_file_dirs"
        ),
        web_host=str(get("web", "host", "127.0.0.1")),
        web_port=port,
    )


def ensure_dirs(home: Path | None = None) -> None:
    """Create the OmniVault home, thumbnail cache, and a default config.toml if missing."""
    home = home or OMNIVAULT_HOME
    home.mkdir(parents=True, exist_ok=True)
    (home / "thumbnails").mkdir(parents=True, exist_ok=True)
    cfg = home / "config.toml"
    if not cfg.exists():
        cfg.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")


SETTINGS = load_settings()

# Backwards-compatible module constants
STAGING_DIR = SETTINGS.staging_dir
INCOMING_LOCALSEND = SETTINGS.incoming_localsend
INCOMING_WIRED = SETTINGS.incoming_wired

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
