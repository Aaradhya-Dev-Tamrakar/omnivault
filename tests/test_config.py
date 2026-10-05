"""
Unit Tests for OmniVault Configuration Engine
Verifies loading config.toml, environment overrides, and directory bootstrapping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omnivault.config import ConfigError, ensure_dirs, load_settings


def test_default_settings(tmp_path):
    home = tmp_path / "omnivault_home"
    settings = load_settings(home=home)

    assert settings.home == home
    assert settings.staging_dir == home / "staging"
    assert settings.web_port == 7890
    assert settings.web_host == "127.0.0.1"
    assert len(settings.dev_scan_roots) > 0


def test_custom_config_toml(tmp_path):
    home = tmp_path / "omnivault_home"
    home.mkdir()
    cfg_file = home / "config.toml"
    cfg_file.write_text(
        """
[paths]
staging_dir = "D:/CustomStaging"

[vault]
default_mount = "E:/"
default_label = "BackupDrive"

[storage]
dev_scan_roots = ["C:/Projects", "D:/Work"]
large_file_dirs = ["D:/Models"]

[web]
host = "0.0.0.0"
port = 9000
""",
        encoding="utf-8",
    )

    settings = load_settings(home=home)
    assert settings.staging_dir == Path("D:/CustomStaging")
    assert settings.default_vault_mount == "E:/"
    assert settings.default_vault_label == "BackupDrive"
    assert len(settings.dev_scan_roots) == 2
    assert settings.web_port == 9000
    assert settings.web_host == "0.0.0.0"


def test_invalid_config_error(tmp_path):
    home = tmp_path / "omnivault_home"
    home.mkdir()
    cfg_file = home / "config.toml"
    cfg_file.write_text("invalid = toml [[", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_settings(home=home)


def test_invalid_port_range(tmp_path):
    home = tmp_path / "omnivault_home"
    home.mkdir()
    cfg_file = home / "config.toml"
    cfg_file.write_text("[web]\nport = 99999\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_settings(home=home)


def test_ensure_dirs_creates_structure(tmp_path):
    home = tmp_path / "omnivault_test_home"
    ensure_dirs(home=home)

    assert home.exists()
    assert (home / "thumbnails").is_dir()
    assert (home / "config.toml").is_file()
    # Running a second time is safe and idempotent
    ensure_dirs(home=home)
