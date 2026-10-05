# OmniVault 🛡️
> **Tri-Tier Archival, Sub-Second Retrieval & System Storage Optimization Engine**  
> Seamlessly bridges Mobile, Laptop, and External Cold Storage with offline shadow indexing, BLAKE3 deduplication, instant retrieval, and intelligent disk optimization.

---

## 🚀 Core Capabilities

OmniVault solves the fundamental friction of external storage, multi-device sync, and disk bloat:
- **Search Blindness Eliminated**: Searches 23,000+ files across disconnected external hard drives in **< 3 milliseconds**.
- **Offline Shadow Catalog**: The index lives on your Laptop's fast NVMe SSD (`~/.omnivault/catalog.db`). Even when your external drive is in a drawer, you can search filenames, tags, extensions, and inspect cached WebP thumbnails.
- **Dual Mobile Ingestion**:
  1. **LocalSend (Wireless LAN)**: Auto-detects and ingests files beamed from your phone over local Wi-Fi.
  2. **Wired USB Connection (High-Speed)**: Differential import from your phone via cable at full bus speed (100–300 MB/s), automatically skipping files that are already archived.
- **System Storage Management & Optimization**:
  - Real-time disk usage profiling across all internal and external volumes (C:, D:, E:, F:, H:, I:).
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

## ⚡ Quick Start

### 1. Launch Web Dashboard (Search + Storage Optimizer)
Double-click `run_web.bat` or run:
```cmd
omnivault.bat serve
```
Open **[http://127.0.0.1:7890](http://127.0.0.1:7890)** in your browser:
- **Instant Search Tab**: Search-as-you-type, offline WebP photo previews, 1-click open.
- **Storage & Optimizer Tab**: Drive health bars, 1-click cache purge, dev bloat breakdown, largest files table.

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
omnivault.bat scan "D:\" --label "Data"

# Check volume and catalog health
omnivault.bat status
```

### Storage Management & Optimization
```cmd
# Full system storage health report (drives, caches, bloat, duplicates, largest files)
omnivault.bat storage-report

# Preview safely purgeable cache bloat (dry-run)
omnivault.bat clean-cache

# Execute cache purge (reclaims ~13.9 GB)
omnivault.bat clean-cache --execute

# Inspect regenerable dev dependencies (node_modules, .venv)
omnivault.bat clean-dev

# Find largest files on the system (> 100MB)
omnivault.bat large-files --root "C:\Users" --min-mb 100

# Detect duplicate files via BLAKE3 cryptographic hashes
omnivault.bat duplicates
```

### Mobile Sync & Offload
```cmd
# 1. Watch incoming LocalSend folder for automated wireless ingestion
omnivault.bat watch-localsend

# 2. Differential wired phone dump via USB (skips files already archived)
omnivault.bat import-wired "This PC\Pixel 7\Internal shared storage\DCIM"

# 3. Offload staged files to external hard drive and reclaim laptop SSD space
omnivault.bat offload --vault "I:/"
```
