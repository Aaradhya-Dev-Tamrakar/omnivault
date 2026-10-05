# OmniVault 🛡️
> **Tri-Tier Archival, Sub-Second Retrieval & System Storage Optimization Engine**  
> Seamlessly bridges Mobile, Laptop, and External Cold Storage with offline shadow indexing, BLAKE3 deduplication, instant retrieval, and intelligent disk optimization.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](pyproject.toml)
[![Code Style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

---

## 🚀 Core Capabilities

OmniVault solves the fundamental friction of external storage, multi-device sync, and disk bloat:
- **Search Blindness Eliminated**: Searches 23,000+ files across disconnected external hard drives in **< 3 milliseconds**.
- **Offline Shadow Catalog**: The index lives on your Laptop's fast NVMe SSD (`~/.omnivault/catalog.db`). Even when your external drive is in a drawer, you can search filenames, tags, extensions, and inspect cached WebP thumbnails.
- **Cryptographic Vault Integrity**: `verify-vault` validates catalog hashes against on-disk bytes, detecting bit rot, silent drive corruption, and missing files before data loss occurs.
- **Collision-Safe Archival**: Differential hashing ensures incoming files from phones or cameras never overwrite archived files; discrepancies receive deterministic content-hash suffixes (`name__<hash[:8]>.ext`).
- **Dual Mobile Ingestion**:
  1. **LocalSend (Wireless LAN)**: Write-stable folder watcher auto-detects and ingests files beamed from your phone over local Wi-Fi.
  2. **Wired USB Connection (High-Speed)**: Differential import from your phone via cable at full bus speed (100–300 MB/s), automatically skipping files that are already archived.
- **System Storage Management & Optimization**:
  - Real-time disk usage profiling across all internal and external volumes.
  - One-click safe cleanup of temporary & developer build caches (Gradle, npm, pip, Windows Temp, VS Code).
  - Largest space-eater detection (> 100MB) with 1-click reveal in Windows Explorer.
  - Content-addressable BLAKE3 duplicate detection across drives.
- **Curated Human-Readable Layout**: Files on your External HDD remain in standard folders (`Library/Photos/YYYY/...`) readable on any operating system without proprietary lock-in.

---

## 📊 Current System State

```text
==================== OMNIVAULT STATUS ====================
Total Indexed Files: 23,308
Total Indexed Volume Size: 144.4 GB

Volumes:
  * [Main] I: (PRIMARY_VAULT)   -> 15,991 files (120.2 GB) [ONLINE]
  * [Mini] H: (SECONDARY_VAULT) ->  7,317 files ( 24.2 GB) [ONLINE]

Categories:
  * photos      : 13,131 files (16.1 GB)
  * videos      :  1,489 files (81.9 GB)
  * documents   :  1,902 files ( 4.2 GB)
  * audio       :    440 files ( 2.0 GB)
  * executables :    542 files ( 4.1 GB)
  * archives    :     53 files (24.9 GB)
  * code        :    428 files (18.9 MB)

Estimated Safely Reclaimable Cache Space: 13.9 GB
==========================================================
```

---

## ⚙️ Configuration (`~/.omnivault/config.toml`)

OmniVault automatically creates a default `config.toml` upon initialization. Customize your staging landing zones, vault defaults, and dev scan roots without editing source code:

```toml
[paths]
# Landing zone for files arriving from your phone before vault offload
staging_dir = "F:/OmniVault_Staging"

[vault]
# Default target for `omnivault offload` when --vault is omitted
default_mount = "I:/"
default_label = "Main"

[storage]
# Roots scanned for regenerable dev folders (node_modules, .venv, etc.)
dev_scan_roots = ["~/Downloads", "~/Documents", "F:/Aaradhya-Dev-Tamrakar"]
# Extra folders scanned by `large-files`
large_file_dirs = ["~/Downloads", "~/Videos", "~/.lmstudio/models", "~/.ollama/models"]

[web]
host = "127.0.0.1"
port = 7890
```

---

## ⚡ Quick Start

### Installation
```bash
# Clone the repository
git clone https://github.com/Aaradhya-Dev-Tamrakar/omnivault.git
cd omnivault

# Install in editable mode with development dependencies
uv sync --extra dev
# or: pip install -e .[dev]
```

### Launch Web Dashboard (Search + Storage Optimizer)
Double-click `run_web.bat` or run:
```cmd
omnivault.bat serve
```
Open **[http://127.0.0.1:7890](http://127.0.0.1:7890)** in your browser:
- **Instant Search Tab**: Search-as-you-type, offline WebP photo previews, 1-click open.
- **Storage & Optimizer Tab**: Drive health bars, 1-click cache purge, dev bloat breakdown, largest files table.
- **Security**: Localhost-bound with CSRF action token validation protecting all destructive actions.

---

## 🛠️ CLI Reference

### Archival & Retrieval
```cmd
# Instant search across all drives (< 3ms)
omnivault.bat find "passport"
omnivault.bat find "statement" --category documents
omnivault.bat find "2025" --category photos -n 10

# Scan & index a new drive or folder (runs at ~2,500+ files/s)
omnivault.bat scan "I:\" --label "Main" --role "PRIMARY_VAULT"
omnivault.bat scan "H:\" --label "Mini" --role "SECONDARY_VAULT"

# Check volume and catalog health
omnivault.bat status
```

### Integrity Verification (Bit Rot & Corruption Hunting)
```cmd
# Verify all online vault volumes against BLAKE3 catalog hashes
omnivault.bat verify-vault

# Audit a specific volume by label
omnivault.bat verify-vault --volume "Main"

# Fast spot-check: sample 10% of files on the drive
omnivault.bat verify-vault --sample 10.0

# Export audit findings as machine-readable JSON
omnivault.bat verify-vault --json
```

### Storage Management & Optimization
```cmd
# Full system storage health report (drives, caches, bloat, duplicates, largest files)
omnivault.bat storage-report

# Preview safely purgeable cache bloat (dry-run default)
omnivault.bat clean-cache

# Execute cache purge (reclaims ~13.9 GB)
omnivault.bat clean-cache --execute

# Inspect regenerable dev dependencies (node_modules, .venv)
omnivault.bat clean-dev

# Find largest files on the system (> 100MB)
omnivault.bat large-files --min-mb 100

# Detect duplicate files via BLAKE3 cryptographic hashes
omnivault.bat duplicates
```

### Mobile Sync & Offload
```cmd
# 1. Watch incoming LocalSend folder with write-stability detection
omnivault.bat watch-localsend

# 2. Differential wired phone dump via USB (skips files already archived)
omnivault.bat import-wired "This PC\Pixel 7\Internal shared storage\DCIM"

# 3. Offload staged files to external hard drive with collision resolution
omnivault.bat offload
```

---

## 🛡️ License

OmniVault is licensed under the [MIT License](LICENSE). Copyright © 2026 Aaradhya Dev Tamrakar.
