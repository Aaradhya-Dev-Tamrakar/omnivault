# CLAUDE.md - Claude Code Guidelines for OmniVault

## Overview
**OmniVault** is a tri-tier archival, sub-millisecond retrieval, and system storage optimization engine.

All authoritative architectural rules, invariants, and git synchronization instructions are defined in [`AGENTS.md`](AGENTS.md).

## Quick Developer Commands

### Environment & Testing
```powershell
# Run full unit and integration test suite
uv run pytest -v

# Run linter checks
uv run ruff check .

# Format code with Ruff
uv run ruff format .
```

### Running OmniVault
```cmd
# Windows batch wrapper
omnivault.bat status
omnivault.bat find "search query"
omnivault.bat verify-vault --sample 10
omnivault.bat serve --port 7890
```

### Synchronization Protocol
```powershell
# Automated commit and push
.\sync.bat -m "feat(scope): conventional message (#ID)"
```
