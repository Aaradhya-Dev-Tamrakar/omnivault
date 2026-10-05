"""
FastAPI Instant Search & Storage Optimization Web Gateway for OmniVault
Provides lightning-fast search-as-you-type, offline thumbnail previews,
drive health monitoring, cache cleaning, and large file analysis.
"""

from __future__ import annotations

import secrets
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from omnivault.config import SETTINGS, THUMBNAILS_DIR
from omnivault.db import (
    check_all_volumes_online_status,
    format_bytes,
    get_stats,
    init_db,
    search,
)
from omnivault.storage import (
    clean_cache_dir,
    generate_full_report,
    scan_cache_bloat,
)

# Cryptographic token generated per server process to protect sensitive local actions
ACTION_TOKEN = secrets.token_urlsafe(32)


def verify_action_token(x_omnivault_token: str | None = Header(None)) -> str:
    """Validates that destructive localhost requests include the active process token."""
    if not x_omnivault_token or not secrets.compare_digest(x_omnivault_token, ACTION_TOKEN):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Invalid or missing X-OmniVault-Token authentication header.",
        )
    return x_omnivault_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="OmniVault Web Gateway", version="0.2.0", lifespan=lifespan)

# Restrict CORS strictly to loopback interfaces
allowed_origins = [
    "http://127.0.0.1",
    "http://localhost",
    f"http://127.0.0.1:{SETTINGS.web_port}",
    f"http://localhost:{SETTINGS.web_port}",
    "http://127.0.0.1:7890",
    "http://localhost:7890",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/stats")
def api_stats():
    check_all_volumes_online_status()
    return get_stats()


@app.get("/api/search")
def api_search(
    q: str = Query("", description="Search query"),
    category: str | None = Query(None, description="Category filter"),
    volume: str | None = Query(None, description="Volume label filter"),
    ext: str | None = Query(None, description="Extension filter"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    check_all_volumes_online_status()
    return search(
        query=q,
        category=category,
        volume_label=volume,
        extension=ext,
        limit=limit,
        offset=offset,
    )


@app.get("/api/thumb/{file_hash}")
def api_thumbnail(file_hash: str):
    """Serves the cached offline WebP thumbnail."""
    shard = file_hash[:2]
    thumb_path = THUMBNAILS_DIR / shard / f"{file_hash}.webp"
    if thumb_path.is_file():
        return FileResponse(thumb_path, media_type="image/webp")
    raise HTTPException(status_code=404, detail="Thumbnail not found")


@app.post("/api/open", dependencies=[Depends(verify_action_token)])
def api_open_file(path: str = Query(..., description="Absolute path to open or reveal")):
    target = Path(path)
    if not target.exists():
        raise HTTPException(
            status_code=404, detail="File is currently offline or volume is disconnected."
        )

    # Reveal in Windows Explorer
    subprocess.Popen(["explorer.exe", f"/select,{str(target)}"])
    return {"status": "ok", "message": f"Revealed {target.name} in Explorer"}


@app.get("/api/storage/report")
def api_storage_report():
    """Generates complete storage health and optimization metrics."""
    return generate_full_report()


@app.post("/api/storage/clean-cache", dependencies=[Depends(verify_action_token)])
def api_clean_cache(execute: bool = Query(False, description="Whether to actually delete files")):
    """Scans and optionally cleans safe system and dev caches."""
    caches = scan_cache_bloat()
    results = []
    total_freed = 0
    for c in caches:
        if c.safe_to_delete:
            res = clean_cache_dir(c.path, dry_run=not execute)
            res["label"] = c.label
            total_freed += res["freed_bytes"]
            results.append(res)

    return {
        "executed": execute,
        "total_freed_bytes": total_freed,
        "total_freed_formatted": format_bytes(total_freed),
        "results": results,
    }


@app.get("/", response_class=HTMLResponse)
def index_page():
    return HTML_CONTENT.replace("{{OMNIVAULT_TOKEN}}", ACTION_TOKEN)


HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OmniVault - Archival, Retrieval & Storage Optimization</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    body { background-color: #0b0f17; color: #e2e8f0; font-family: system-ui, -apple-system, sans-serif; }
    .glass { background: rgba(18, 24, 38, 0.75); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
    .glass-card { background: rgba(22, 30, 48, 0.6); backdrop-filter: blur(8px); border: 1px solid rgba(255, 255, 255, 0.06); }
    .glass-card:hover { border-color: rgba(56, 189, 248, 0.4); }
  </style>
</head>
<body class="min-h-screen flex flex-col">

  <!-- Top Navigation & Volume Status Bar -->
  <header class="glass sticky top-0 z-50 px-6 py-4 flex flex-wrap items-center justify-between gap-4 border-b">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
        <i class="fa-solid fa-vault text-white text-xl"></i>
      </div>
      <div>
        <h1 class="text-lg font-bold tracking-tight text-white flex items-center gap-2">
          OmniVault <span class="text-xs px-2 py-0.5 rounded-full bg-cyan-950 text-cyan-400 border border-cyan-800 font-mono">v0.2</span>
        </h1>
        <p class="text-xs text-slate-400">Tri-Tier Archival & System Storage Optimization</p>
      </div>
    </div>

    <!-- Mode Tabs -->
    <div class="flex items-center rounded-xl bg-slate-900/80 p-1 border border-slate-800">
      <button id="tab-search" class="px-4 py-1.5 rounded-lg text-xs font-semibold bg-cyan-600 text-white flex items-center gap-2 shadow transition-all">
        <i class="fa-solid fa-magnifying-glass"></i> Instant Search
      </button>
      <button id="tab-storage" class="px-4 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white flex items-center gap-2 transition-all">
        <i class="fa-solid fa-gauge-high"></i> Storage & Optimizer
      </button>
    </div>

    <!-- Live Volumes Presence Indicator -->
    <div id="volumes-bar" class="flex items-center gap-2 text-xs">
      <span class="text-slate-400 mr-1"><i class="fa-solid fa-hard-drive"></i> Drives:</span>
      <div class="animate-pulse text-slate-500">Checking drives...</div>
    </div>
  </header>

  <!-- ═══════════════════════════════════════════════════════════════════ -->
  <!-- TAB 1: Instant Search View -->
  <!-- ═══════════════════════════════════════════════════════════════════ -->
  <main id="view-search" class="flex-1 max-w-7xl w-full mx-auto px-6 py-8 flex flex-col gap-6">

    <!-- Search Hero -->
    <div class="flex flex-col gap-3">
      <div class="relative">
        <i class="fa-solid fa-magnifying-glass absolute left-5 top-1/2 -translate-y-1/2 text-slate-400 text-lg"></i>
        <input
          id="search-input"
          type="text"
          placeholder="Search by filename, extension, tag, or topic across all drives..."
          class="w-full pl-14 pr-12 py-4 rounded-2xl glass text-white placeholder-slate-500 text-lg focus:outline-none focus:ring-2 focus:ring-cyan-500 transition-all shadow-xl"
          autofocus
        />
        <button id="clear-btn" class="absolute right-4 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white p-2 hidden">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>

      <!-- Filter Pills -->
      <div class="flex flex-wrap items-center justify-between gap-3 text-sm pt-1">
        <div id="category-pills" class="flex flex-wrap gap-2">
          <button data-cat="" class="cat-pill px-3 py-1.5 rounded-lg text-xs font-medium bg-cyan-600 text-white shadow-sm">All Files</button>
          <button data-cat="photos" class="cat-pill px-3 py-1.5 rounded-lg text-xs font-medium glass text-slate-300 hover:text-white">Photos</button>
          <button data-cat="videos" class="cat-pill px-3 py-1.5 rounded-lg text-xs font-medium glass text-slate-300 hover:text-white">Videos</button>
          <button data-cat="documents" class="cat-pill px-3 py-1.5 rounded-lg text-xs font-medium glass text-slate-300 hover:text-white">Documents</button>
          <button data-cat="audio" class="cat-pill px-3 py-1.5 rounded-lg text-xs font-medium glass text-slate-300 hover:text-white">Audio</button>
          <button data-cat="archives" class="cat-pill px-3 py-1.5 rounded-lg text-xs font-medium glass text-slate-300 hover:text-white">Archives</button>
          <button data-cat="code" class="cat-pill px-3 py-1.5 rounded-lg text-xs font-medium glass text-slate-300 hover:text-white">Code</button>
        </div>

        <div id="stats-summary" class="text-xs text-slate-400">
          Loading catalog...
        </div>
      </div>
    </div>

    <!-- Results Meta -->
    <div id="results-meta" class="flex items-center justify-between text-xs text-slate-400 border-b border-slate-800 pb-2">
      <span id="results-count">Type to search across the offline catalog...</span>
      <span id="results-speed"></span>
    </div>

    <!-- Results Grid -->
    <div id="results-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"></div>

    <!-- Empty State -->
    <div id="empty-state" class="hidden flex-col items-center justify-center py-20 text-slate-500 gap-3">
      <i class="fa-regular fa-folder-open text-5xl text-slate-600"></i>
      <p class="text-base font-medium">No files matched your query</p>
      <p class="text-xs text-slate-600">Try broader keywords or clear your category filter</p>
    </div>

  </main>

  <!-- ═══════════════════════════════════════════════════════════════════ -->
  <!-- TAB 2: Storage Health & Optimization View -->
  <!-- ═══════════════════════════════════════════════════════════════════ -->
  <main id="view-storage" class="hidden flex-1 max-w-7xl w-full mx-auto px-6 py-8 flex flex-col gap-8">

    <!-- Header Actions -->
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
          <i class="fa-solid fa-chart-pie text-cyan-400"></i> System Storage Health & Optimization
        </h2>
        <p class="text-xs text-slate-400 mt-1">Real-time drive status, cache bloat detection, and one-click space reclamation</p>
      </div>
      <div class="flex items-center gap-3">
        <button id="btn-refresh-storage" class="px-4 py-2 rounded-xl glass hover:border-cyan-500 text-xs font-semibold text-slate-200 flex items-center gap-2">
          <i class="fa-solid fa-arrows-rotate"></i> Refresh Report
        </button>
        <button id="btn-clean-cache" class="px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-xs font-bold text-white flex items-center gap-2 shadow-lg shadow-emerald-900/30">
          <i class="fa-solid fa-broom"></i> Clean Reclaimable Caches
        </button>
      </div>
    </div>

    <!-- Total Reclaimable Banner -->
    <div class="glass-card rounded-2xl p-6 flex flex-wrap items-center justify-between gap-6 border-cyan-900/40 bg-gradient-to-r from-cyan-950/30 to-blue-950/20">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 text-2xl">
          <i class="fa-solid fa-leaf"></i>
        </div>
        <div>
          <span class="text-xs font-mono uppercase tracking-wider text-slate-400">Total Safely Reclaimable Space</span>
          <div id="storage-reclaimable-total" class="text-3xl font-extrabold text-emerald-400">Scanning...</div>
        </div>
      </div>
      <div class="text-xs text-slate-400 max-w-md">
        Includes safe build caches (Gradle, npm, pip), temp directories, browser caches, and unlinked extensions. No personal files or active code will be deleted.
      </div>
    </div>

    <!-- 1. Drives Usage Overview -->
    <div class="flex flex-col gap-3">
      <h3 class="text-sm font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
        <i class="fa-solid fa-hard-drive text-cyan-400"></i> Mounted Volumes Status
      </h3>
      <div id="drives-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <!-- Rendered via JS -->
      </div>
    </div>

    <!-- 2. Reclaimable Caches & Bloat Breakdown -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">

      <!-- Cache Bloat List -->
      <div class="glass-card rounded-2xl p-5 flex flex-col gap-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
          <h4 class="text-sm font-bold text-white flex items-center gap-2">
            <i class="fa-solid fa-trash-can text-amber-400"></i> Safely Purgeable Caches
          </h4>
          <span id="cache-bloat-sum" class="text-xs font-mono font-bold text-amber-400">0 B</span>
        </div>
        <div id="cache-bloat-list" class="flex flex-col gap-2 max-h-80 overflow-y-auto pr-1">
          <!-- Rendered via JS -->
        </div>
      </div>

      <!-- Dev Dependencies Bloat -->
      <div class="glass-card rounded-2xl p-5 flex flex-col gap-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
          <h4 class="text-sm font-bold text-white flex items-center gap-2">
            <i class="fa-brands fa-node-js text-emerald-400"></i> Dev Dependency Footprint
          </h4>
          <span id="dev-bloat-sum" class="text-xs font-mono font-bold text-emerald-400">0 B</span>
        </div>
        <div id="dev-bloat-list" class="flex flex-col gap-2 max-h-80 overflow-y-auto pr-1">
          <!-- Rendered via JS -->
        </div>
      </div>

    </div>

    <!-- 3. Top Largest Files -->
    <div class="glass-card rounded-2xl p-5 flex flex-col gap-4">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <h4 class="text-sm font-bold text-white flex items-center gap-2">
          <i class="fa-solid fa-file-circle-exclamation text-rose-400"></i> Largest Stored Files (> 100MB)
        </h4>
        <span class="text-xs text-slate-400">Click arrow to reveal file in Windows Explorer</span>
      </div>
      <div id="large-files-table" class="flex flex-col gap-2 max-h-96 overflow-y-auto pr-1">
        <!-- Rendered via JS -->
      </div>
    </div>

  </main>

  <script>
    const OMNIVAULT_TOKEN = "{{OMNIVAULT_TOKEN}}";

    function esc(str) {
      if (str === null || str === undefined) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    let currentCategory = "";
    let debounceTimer = null;

    // View Switching
    const tabSearch = document.getElementById("tab-search");
    const tabStorage = document.getElementById("tab-storage");
    const viewSearch = document.getElementById("view-search");
    const viewStorage = document.getElementById("view-storage");

    tabSearch.addEventListener("click", () => {
      tabSearch.className = "px-4 py-1.5 rounded-lg text-xs font-semibold bg-cyan-600 text-white flex items-center gap-2 shadow transition-all";
      tabStorage.className = "px-4 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white flex items-center gap-2 transition-all";
      viewSearch.classList.remove("hidden");
      viewStorage.classList.add("hidden");
    });

    tabStorage.addEventListener("click", () => {
      tabStorage.className = "px-4 py-1.5 rounded-lg text-xs font-semibold bg-cyan-600 text-white flex items-center gap-2 shadow transition-all";
      tabSearch.className = "px-4 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white flex items-center gap-2 transition-all";
      viewStorage.classList.remove("hidden");
      viewSearch.classList.add("hidden");
      loadStorageReport();
    });

    // Search View Elements
    const searchInput = document.getElementById("search-input");
    const clearBtn = document.getElementById("clear-btn");
    const categoryPills = document.querySelectorAll(".cat-pill");
    const resultsGrid = document.getElementById("results-grid");
    const resultsCount = document.getElementById("results-count");
    const resultsSpeed = document.getElementById("results-speed");
    const emptyState = document.getElementById("empty-state");
    const statsSummary = document.getElementById("stats-summary");
    const volumesBar = document.getElementById("volumes-bar");

    // Storage View Elements
    const storageReclaimableTotal = document.getElementById("storage-reclaimable-total");
    const drivesGrid = document.getElementById("drives-grid");
    const cacheBloatList = document.getElementById("cache-bloat-list");
    const cacheBloatSum = document.getElementById("cache-bloat-sum");
    const devBloatList = document.getElementById("dev-bloat-list");
    const devBloatSum = document.getElementById("dev-bloat-sum");
    const largeFilesTable = document.getElementById("large-files-table");
    const btnRefreshStorage = document.getElementById("btn-refresh-storage");
    const btnCleanCache = document.getElementById("btn-clean-cache");

    async function loadStats() {
      try {
        const res = await fetch("/api/stats");
        const data = await res.json();
        statsSummary.innerText = `${data.total_files.toLocaleString()} indexed files (${data.total_size_formatted})`;

        volumesBar.innerHTML = '<span class="text-slate-400 mr-1"><i class="fa-solid fa-hard-drive"></i> Drives:</span>';
        data.volumes.forEach(v => {
          const badge = document.createElement("span");
          badge.className = `px-2.5 py-1 rounded-md text-xs font-mono flex items-center gap-1.5 ${
            v.is_online ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800' : 'bg-rose-950/60 text-rose-400 border border-rose-900/60 opacity-60'
          }`;
          badge.innerHTML = `<span class="w-1.5 h-1.5 rounded-full ${v.is_online ? 'bg-emerald-400' : 'bg-rose-400'}"></span> ${esc(v.label)} (${esc(v.mount_point)}) [${v.is_online ? 'ONLINE' : 'UNPLUGGED'}]`;
          volumesBar.appendChild(badge);
        });
      } catch (e) {
        console.error("Stats error", e);
      }
    }

    async function doSearch() {
      const q = searchInput.value.trim();
      clearBtn.classList.toggle("hidden", !q);

      try {
        const url = `/api/search?q=${encodeURIComponent(q)}&category=${encodeURIComponent(currentCategory)}&limit=80`;
        const res = await fetch(url);
        const data = await res.json();

        resultsCount.innerText = `${data.total.toLocaleString()} files found`;
        resultsSpeed.innerText = `Retrieved in ${data.duration_ms} ms`;

        resultsGrid.innerHTML = "";
        if (data.items.length === 0) {
          emptyState.classList.remove("hidden");
          emptyState.classList.add("flex");
          return;
        }

        emptyState.classList.add("hidden");
        emptyState.classList.remove("flex");

        data.items.forEach(item => {
          const card = document.createElement("div");
          card.className = "glass-card rounded-xl p-4 flex flex-col justify-between transition-all duration-200";

          let mediaHtml = '';
          if (item.has_thumbnail && item.blake3_hash) {
            mediaHtml = `<div class="w-full h-32 rounded-lg bg-slate-900 overflow-hidden mb-3 flex items-center justify-center">
              <img src="/api/thumb/${encodeURIComponent(item.blake3_hash)}" alt="${esc(item.filename)}" class="w-full h-full object-cover" loading="lazy" />
            </div>`;
          }

          let iconClass = "fa-file";
          if (item.category === "photos") iconClass = "fa-image text-cyan-400";
          else if (item.category === "videos") iconClass = "fa-video text-amber-400";
          else if (item.category === "documents") iconClass = "fa-file-lines text-indigo-400";
          else if (item.category === "audio") iconClass = "fa-music text-pink-400";
          else if (item.category === "archives") iconClass = "fa-file-zipper text-emerald-400";
          else if (item.category === "code") iconClass = "fa-code text-teal-400";

          const statusBadge = item.is_online
            ? `<span class="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-950 text-emerald-400 border border-emerald-800">ONLINE</span>`
            : `<span class="px-2 py-0.5 rounded text-[10px] font-mono bg-rose-950 text-rose-400 border border-rose-800" title="Drive unplugged">OFFLINE</span>`;

          card.innerHTML = `
            <div>
              ${mediaHtml}
              <div class="flex items-start justify-between gap-2 mb-1.5">
                <div class="flex items-center gap-2 overflow-hidden">
                  <i class="fa-solid ${iconClass} text-sm"></i>
                  <span class="font-semibold text-sm text-slate-100 truncate" title="${esc(item.filename)}">${esc(item.filename)}</span>
                </div>
                ${statusBadge}
              </div>
              <p class="text-[11px] text-slate-400 font-mono truncate mb-2" title="${esc(item.rel_path)}">
                <i class="fa-regular fa-folder text-slate-500 mr-1"></i>${esc(item.rel_path)}
              </p>
            </div>

            <div class="pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
              <span>${esc(item.size_formatted)}</span>
              <div class="flex items-center gap-2">
                <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">${esc(item.volume_label)}</span>
                ${item.is_online ? `
                  <button onclick="revealFile('${encodeURIComponent(item.abs_path)}')" class="hover:text-cyan-400 p-1" title="Reveal in Windows Explorer">
                    <i class="fa-solid fa-arrow-up-right-from-square"></i>
                  </button>
                ` : `
                  <span class="text-rose-400 text-[11px]" title="Drive unplugged"><i class="fa-solid fa-plug"></i></span>
                `}
              </div>
            </div>
          `;

          resultsGrid.appendChild(card);
        });

      } catch (err) {
        console.error("Search failed", err);
      }
    }

    async function revealFile(encodedPath) {
      const path = decodeURIComponent(encodedPath);
      try {
        const res = await fetch(`/api/open?path=${encodeURIComponent(path)}`, {
          method: "POST",
          headers: { "X-OmniVault-Token": OMNIVAULT_TOKEN },
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert("Cannot reveal file: " + (err.detail || res.statusText));
          return;
        }
      } catch (e) {
        alert("Cannot open file: " + e.message);
      }
    }

    // Storage Report Loader
    async function loadStorageReport() {
      storageReclaimableTotal.innerText = "Analyzing...";
      drivesGrid.innerHTML = '<div class="text-xs text-slate-500 animate-pulse">Profiling drive health...</div>';

      try {
        const res = await fetch("/api/storage/report");
        const report = await res.json();

        storageReclaimableTotal.innerText = report.total_reclaimable_formatted;

        // 1. Drives Grid
        drivesGrid.innerHTML = "";
        report.drives.forEach(d => {
          const card = document.createElement("div");
          card.className = "glass-card rounded-xl p-4 flex flex-col gap-2";
          const barColor = d.used_pct > 85 ? 'bg-rose-500' : (d.used_pct > 65 ? 'bg-amber-500' : 'bg-cyan-500');

          card.innerHTML = `
            <div class="flex items-center justify-between">
              <span class="font-bold text-sm text-white">${esc(d.letter)}: ${esc(d.label || 'Volume')}</span>
              <span class="text-xs font-mono text-slate-400">${esc(d.fs_type)}</span>
            </div>
            <div class="w-full bg-slate-900 rounded-full h-2 overflow-hidden mt-1">
              <div class="${barColor} h-2 rounded-full" style="width: ${d.used_pct}%"></div>
            </div>
            <div class="flex items-center justify-between text-xs text-slate-400 mt-1 font-mono">
              <span>Free: ${esc(d.free_formatted)}</span>
              <span>${d.used_pct}% (${esc(d.total_formatted)})</span>
            </div>
          `;
          drivesGrid.appendChild(card);
        });

        // 2. Cache Bloat
        cacheBloatSum.innerText = report.cache_bloat.total_formatted;
        cacheBloatList.innerHTML = "";
        report.cache_bloat.entries.forEach(c => {
          const item = document.createElement("div");
          item.className = "flex items-center justify-between p-2.5 rounded-lg bg-slate-900/60 border border-slate-800 text-xs";
          item.innerHTML = `
            <div class="flex flex-col overflow-hidden mr-2">
              <span class="font-semibold text-slate-200">${esc(c.label)}</span>
              <span class="text-[10px] text-slate-500 font-mono truncate" title="${esc(c.path)}">${esc(c.path)}</span>
            </div>
            <div class="text-right whitespace-nowrap">
              <span class="font-mono text-amber-400 font-bold">${esc(c.size_formatted)}</span>
              <div class="text-[10px] text-slate-500">${c.files} files</div>
            </div>
          `;
          cacheBloatList.appendChild(item);
        });

        // 3. Dev Bloat
        devBloatSum.innerText = report.dev_bloat.total_formatted;
        devBloatList.innerHTML = "";
        report.dev_bloat.entries.forEach(d => {
          const item = document.createElement("div");
          item.className = "flex items-center justify-between p-2.5 rounded-lg bg-slate-900/60 border border-slate-800 text-xs";
          item.innerHTML = `
            <div class="flex flex-col overflow-hidden mr-2">
              <span class="font-semibold text-slate-200">[${esc(d.name)}]</span>
              <span class="text-[10px] text-slate-500 font-mono truncate" title="${esc(d.path)}">${esc(d.project)}</span>
            </div>
            <span class="font-mono text-emerald-400 font-bold whitespace-nowrap">${esc(d.size_formatted)}</span>
          `;
          devBloatList.appendChild(item);
        });

        // 4. Large Files Table
        largeFilesTable.innerHTML = "";
        report.large_files.files.forEach(f => {
          const row = document.createElement("div");
          row.className = "flex items-center justify-between p-2.5 rounded-lg bg-slate-900/60 border border-slate-800 text-xs hover:border-slate-700";
          row.innerHTML = `
            <div class="flex items-center gap-2 overflow-hidden mr-3">
              <span class="px-1.5 py-0.5 rounded text-[10px] uppercase font-mono bg-slate-800 text-slate-300">${esc(f.category)}</span>
              <div class="flex flex-col overflow-hidden">
                <span class="font-semibold text-slate-200 truncate" title="${esc(f.filename)}">${esc(f.filename)}</span>
                <span class="text-[10px] text-slate-500 font-mono truncate" title="${esc(f.path)}">${esc(f.path)}</span>
              </div>
            </div>
            <div class="flex items-center gap-3 whitespace-nowrap">
              <span class="font-mono font-bold text-rose-400">${esc(f.size_formatted)}</span>
              <button onclick="revealFile('${encodeURIComponent(f.path)}')" class="hover:text-cyan-400 p-1" title="Reveal in Windows Explorer">
                <i class="fa-solid fa-arrow-up-right-from-square"></i>
              </button>
            </div>
          `;
          largeFilesTable.appendChild(row);
        });

      } catch (err) {
        console.error("Storage report failed", err);
        storageReclaimableTotal.innerText = "Error loading report";
      }
    }

    btnRefreshStorage.addEventListener("click", loadStorageReport);

    btnCleanCache.addEventListener("click", async () => {
      if (!confirm("This will safely purge temporary build caches (Gradle, npm, pip, Windows Temp). Are you sure?")) {
        return;
      }
      btnCleanCache.disabled = true;
      btnCleanCache.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Purging Caches...';
      try {
        const res = await fetch("/api/storage/clean-cache?execute=true", {
          method: "POST",
          headers: { "X-OmniVault-Token": OMNIVAULT_TOKEN },
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert("Cleanup rejected: " + (err.detail || res.statusText));
          return;
        }
        const data = await res.json();
        alert(`Successfully cleaned caches and reclaimed ${data.total_freed_formatted}!`);
        loadStorageReport();
      } catch (e) {
        alert("Cleanup failed: " + e.message);
      } finally {
        btnCleanCache.disabled = false;
        btnCleanCache.innerHTML = '<i class="fa-solid fa-broom"></i> Clean Reclaimable Caches';
      }
    });

    searchInput.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(doSearch, 150);
    });

    clearBtn.addEventListener("click", () => {
      searchInput.value = "";
      doSearch();
      searchInput.focus();
    });

    categoryPills.forEach(pill => {
      pill.addEventListener("click", () => {
        categoryPills.forEach(p => {
          p.classList.remove("bg-cyan-600", "text-white");
          p.classList.add("glass", "text-slate-300");
        });
        pill.classList.remove("glass", "text-slate-300");
        pill.classList.add("bg-cyan-600", "text-white");

        currentCategory = pill.dataset.cat;
        doSearch();
      });
    });

    // Initial boot
    loadStats();
    doSearch();
  </script>
</body>
</html>
"""


def run_server(host: str | None = None, port: int | None = None):
    h = host or SETTINGS.web_host
    p = port or SETTINGS.web_port
    uvicorn.run(app, host=h, port=p, log_level="info")


if __name__ == "__main__":
    run_server()
