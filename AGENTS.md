# AGENTS.md — Developer & AI Agent Guidelines for OmniVault

Welcome, Agent. This repository contains **OmniVault**, a high-performance tri-tier archival, instant sub-millisecond retrieval, and system storage optimization engine.

To preserve archive integrity, prevent silent data loss, maintain deterministic verification, and follow Aaradhya's ecosystem development standards, you **MUST** strictly adhere to the rules below.

---

## 1. Non-Negotiable Invariants & Safety Constraints

1. **Verify-Before-Delete Invariant**:
   - Files in staging must **never** be deleted until after a target copy has been written and its BLAKE3 cryptographic hash verified byte-for-byte against the catalog.
   - Any copy failure, I/O error, or hash mismatch must immediately abort the transfer, remove partial artifacts (`.partial`), and preserve the staged source file intact.

2. **Collision-Safe Vault Archival**:
   - **Never** silently overwrite existing archived files on external cold vaults or in staging.
   - If a file with identical content (`hash == expected`) already exists, the transfer is safely skipped and staging cleaned.
   - If a file with discrepant content exists, append a deterministic content-hash suffix (`<stem>__<hash[:8]><suffix>`) to preserve both versions.

3. **Safe Storage Cleanups (Dry-Run by Default)**:
   - All destructive storage operations (`clean-cache`, `clean-dev`, `offload`) **MUST** default to dry-run preview mode.
   - Real filesystem modifications require explicit flags (`--execute`).

4. **Zero Hardcoded Environment Paths**:
   - **Never** hardcode local machine paths (e.g. `F:\Aaradhya-Dev-Tamrakar`, `I:\`, `H:\`) into Python code.
   - All paths must resolve through `~/.omnivault/config.toml` via `omnivault.config.SETTINGS`.
   - Tests must run in isolated temporary environments using `OMNIVAULT_HOME` monkeypatching.

5. **Localhost Security Guard**:
   - The Web gateway binds strictly to loopback interfaces with CORS restricted to localhost.
   - Destructive POST endpoints (`/api/open`, `/api/storage/clean-cache`) require the active process `X-OmniVault-Token` header.
   - All user and filesystem strings inserted into the Web DOM must pass through HTML escaping.

---

## 2. Directory Layout & Module Ownership

```
omnivault/
├── omnivault/
│   ├── config.py       # Configuration loader (config.toml), paths, file categories
│   ├── db.py           # SQLite FTS5 catalog, WAL mode, schema, triggers, search
│   ├── hasher.py       # Streaming BLAKE3 cryptographic hashing
│   ├── indexer.py      # Volume crawling and batched catalog commits
│   ├── scanner.py      # Directory crawler with system directory noise filtering
│   ├── search.py       # High-level search CLI API with hardware status
│   ├── staging.py      # LocalSend/Wired intake, collision resolver, atomic offloader
│   ├── storage.py      # Drive usage profiling, duplicate detection, cache cleaner
│   ├── thumbnail.py    # Offline WebP micro-thumbnail extraction and sharding
│   ├── verify.py       # Cryptographic vault integrity validation (bit rot / loss)
│   ├── watcher.py      # Write-stable LocalSend staging watcher
│   ├── web.py          # FastAPI dashboard gateway with token defense and search UI
│   └── cli.py          # Unified CLI entry point (`omnivault`)
├── tests/              # Pytest test suites (unit, safety, config, security, verify)
├── pyproject.toml      # Modern packaging, ruff, pytest, and dev dependencies
├── sync.bat / sync.ps1 # Automated ecosystem synchronization wrapper
└── omnivault.bat       # Windows CLI execution wrapper
```

---

## 3. Git Workflow & Ecosystem Automation (CRITICAL — STRICT ENFORCEMENT)

To prevent breaking multi-branch tracking and bypass PowerShell execution restrictions across fresh devices:

**NEVER run individual `git add`, `git commit`, or `git push` commands directly.**

**ALWAYS execute `.\sync.bat` (or `.\sync.ps1`) for repository synchronization.**

```powershell
# Routine / active branch sync
.\sync.bat

# Conventional commit with message
.\sync.bat -m "feat(vault): add integrity verification engine (#1)"

# Dry-run preview
.\sync.bat -WhatIf

# Safe pull only
.\sync.bat -PullOnly
```

### GitHub Flow & Issue Anchoring
- Every non-trivial feature or fix must be anchored to an issue (`#<ID>`).
- Develop on isolated branch `feat/<slug>-#<ID>` or `fix/<slug>-#<ID>`.
- Keep issue task checklists updated as milestones complete.
- Verify test suite and linter before commit.

---

## 4. Verification Gates & Reality Layer

Before staging or committing any code, all gates must pass with zero errors:

```powershell
# 1. Complete test suite
uv run pytest -v

# 2. Linting verification
uv run ruff check .

# 3. Formatting verification
uv run ruff format --check .
```
