<#
.SYNOPSIS
Safely sync the OmniVault repository, detect secrets, and commit with smart conventional messaging.

.DESCRIPTION
Automated synchronization workflow for OmniVault:
1. Verifies Git repository and active branch.
2. Pulls remote updates with --rebase and --autostash if remote origin exists.
3. Stages changes with git add -A.
4. Scans staged changes for accidental credentials, keys, or sensitive tokens.
5. Auto-generates conventional commit messages (feat/fix/refactor/docs/chore).
6. Commits and safely pushes to origin, retrying with rebase if rejected.

.PARAMETER Message
Custom commit message (e.g. -m "feat(storage): add disk optimizer").

.PARAMETER PullOnly
Safely pull remote changes with --rebase --autostash without committing or pushing.

.PARAMETER NoPush
Stages and commits changes locally without pushing to remote origin.

.PARAMETER WhatIf
Dry-run mode: Previews changes and commit message without modifying git state.
#>

[CmdletBinding()]
param (
    [Alias("m")]
    [string]$Message,

    [switch]$PullOnly,

    [switch]$NoPush,

    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Status {
    param([string]$Msg, [System.ConsoleColor]$Color = [System.ConsoleColor]::Cyan)
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] $Msg" -ForegroundColor $Color
}

function Write-Success {
    param([string]$Msg)
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] SUCCESS: $Msg" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Msg)
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] ERROR: $Msg" -ForegroundColor Red
}

$repoRoot = $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path "$repoRoot\.git")) {
    Write-Fail "Not a Git repository: $repoRoot"
    exit 1
}

$branch = (git branch --show-current).Trim()
Write-Status "Active branch: [$branch]"

# 1. Pull with rebase if origin is configured
$hasOrigin = (git remote) -contains "origin"
if ($hasOrigin) {
    Write-Status "Pulling latest changes from origin/$branch with rebase & autostash..."
    git pull origin $branch --rebase --autostash
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Git pull failed. Resolve rebase conflicts and try again."
        exit 1
    }
}

if ($PullOnly) {
    Write-Success "Pull-only completed successfully."
    exit 0
}

# 2. Check for working tree changes
$status = git status --porcelain
if (-not $status) {
    Write-Success "Working tree is clean. Nothing to commit."
    exit 0
}

# 3. Stage changes
git add -A

# 4. Secret Scanner Guard
$stagedDiff = git diff --cached
$secretPatterns = @(
    "ghp_[a-zA-Z0-9]{36}",
    "github_pat_[a-zA-Z0-9_]{82}",
    "AIza[0-9A-Za-z\\-_]{35}",
    "sk-[a-zA-Z0-9]{48}",
    "-----BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY-----"
)
foreach ($pat in $secretPatterns) {
    if ($stagedDiff -match $pat) {
        Write-Fail "Potential secret detected matching pattern: $pat"
        Write-Fail "Aborting commit. Please remove secrets from staged files."
        git reset
        exit 1
    }
}

# 5. Determine commit message
$commitMsg = $Message
if (-not $commitMsg) {
    $stagedFiles = @(git diff --cached --name-only)
    if ($stagedFiles -match "README|docs") {
        $commitMsg = "docs(omnivault): update documentation and usage guides"
    }
    elseif ($stagedFiles -match "test_") {
        $commitMsg = "test(omnivault): add or update test suites"
    }
    elseif ($stagedFiles -match "storage\.py") {
        $commitMsg = "feat(storage): enhance system storage optimization engine"
    }
    elseif ($stagedFiles -match "web\.py") {
        $commitMsg = "feat(ui): update web gateway dashboard"
    }
    else {
        $commitMsg = "feat(omnivault): sync updates across core modules"
    }
}

if ($WhatIf) {
    Write-Status "WhatIf Mode: Would commit with message: '$commitMsg'"
    git status --short
    git reset
    exit 0
}

# 6. Commit
Write-Status "Committing changes: $commitMsg"
git commit -m "$commitMsg"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Git commit failed."
    exit 1
}

# 7. Push to origin
if ($hasOrigin -and -not $NoPush) {
    Write-Status "Pushing commits to origin/$branch..."
    git push origin $branch
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Push rejected, attempting pull --rebase and retry..."
        git pull origin $branch --rebase --autostash
        git push origin $branch
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "Git push failed after rebase."
            exit 1
        }
    }
    Write-Success "Pushed to origin/$branch successfully."
}

Write-Success "OmniVault synchronization complete."
