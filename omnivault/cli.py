"""
Command-Line Interface for OmniVault
Provides commands for scanning, querying, status checking, and launching the Web UI.
"""

import argparse
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from omnivault.config import SETTINGS
from omnivault.db import (
    check_all_volumes_online_status,
    get_stats,
    init_db,
)
from omnivault.indexer import index_volume
from omnivault.search import find_files, print_search_results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omnivault",
        description="OmniVault: Tri-Tier Archival & Instant Retrieval Engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Scan and index a directory or drive")
    scan_parser.add_argument("path", help="Directory or drive root to index (e.g. 'I:/' or 'H:/')")
    scan_parser.add_argument("--label", "-l", help="Volume label name (e.g. 'Main', 'Mini')")
    scan_parser.add_argument(
        "--role", "-r", default="VAULT", help="Role (PRIMARY_VAULT, SECONDARY_VAULT, STAGING)"
    )
    scan_parser.add_argument("--disk", "-d", help="Hardware disk descriptor")
    scan_parser.add_argument("--no-hash", action="store_true", help="Skip BLAKE3 hash computation")
    scan_parser.add_argument("--no-thumb", action="store_true", help="Skip thumbnail generation")

    # find command
    find_parser = subparsers.add_parser("find", help="Instant search across the archive")
    find_parser.add_argument("query", help="Keywords or search query")
    find_parser.add_argument(
        "--category", "-c", help="Filter by category (photos, videos, documents, code, etc.)"
    )
    find_parser.add_argument("--volume", "-v", help="Filter by volume label (Main, Mini, etc.)")
    find_parser.add_argument("--ext", "-e", help="Filter by file extension (e.g. pdf, mp4)")
    find_parser.add_argument(
        "--limit", "-n", type=int, default=25, help="Maximum number of results to display"
    )

    # status command
    subparsers.add_parser("status", help="Display overview of indexed volumes and categories")

    # verify-vault command
    verify_parser = subparsers.add_parser(
        "verify-vault",
        help="Cryptographically audit vault files against catalog hashes for corruption or loss",
    )
    verify_parser.add_argument(
        "--volume", "-v", help="Filter verification to specific volume label or mount"
    )
    verify_parser.add_argument(
        "--sample", "-s", type=float, help="Sample percentage of files to check (e.g. 5.0 for 5%%)"
    )
    verify_parser.add_argument(
        "--json", action="store_true", help="Output verification report as JSON"
    )

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Launch the instant search Web UI")
    serve_parser.add_argument(
        "--host",
        default=SETTINGS.web_host,
        help=f"Host interface (default: {SETTINGS.web_host})",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=SETTINGS.web_port,
        help=f"Port to listen on (default: {SETTINGS.web_port})",
    )

    # import-wired command
    wired_parser = subparsers.add_parser(
        "import-wired", help="Import files from a wired phone folder or drive"
    )
    wired_parser.add_argument("source", help="Path to connected phone folder or drive")
    wired_parser.add_argument("--no-skip", action="store_true", help="Do not skip existing files")

    # offload command
    default_vault = SETTINGS.default_vault_mount or "I:/"
    default_label = SETTINGS.default_vault_label or "Main"
    offload_parser = subparsers.add_parser(
        "offload", help="Offload staged files to external cold vault"
    )
    offload_parser.add_argument(
        "--vault",
        default=default_vault,
        help=f"External vault mount point (default: {default_vault})",
    )
    offload_parser.add_argument(
        "--label",
        default=default_label,
        help=f"Vault label name (default: {default_label})",
    )
    offload_parser.add_argument(
        "--dry-run", action="store_true", help="Preview offload without modifying disk"
    )

    # watch-localsend command
    subparsers.add_parser(
        "watch-localsend", help="Continuously watch incoming LocalSend staging folder"
    )

    # ── Storage Management Commands ─────────────────────────────────────
    # storage-report
    subparsers.add_parser(
        "storage-report",
        help="Full system storage health report (drives, caches, bloat, duplicates, large files)",
    )

    # duplicates
    dup_parser = subparsers.add_parser(
        "duplicates", help="Detect duplicate files across indexed volumes"
    )
    dup_parser.add_argument(
        "--min-size",
        type=int,
        default=1024,
        help="Minimum file size in bytes to consider (default: 1024)",
    )
    dup_parser.add_argument("--limit", "-n", type=int, default=20, help="Max groups to display")

    # large-files
    large_parser = subparsers.add_parser("large-files", help="Find largest files under a directory")
    large_parser.add_argument(
        "--root", default="C:\\Users", help="Root directory to scan (default: C:\\Users)"
    )
    large_parser.add_argument(
        "--min-mb", type=float, default=100.0, help="Minimum file size in MB (default: 100)"
    )
    large_parser.add_argument("--limit", "-n", type=int, default=25, help="Max results to display")

    # clean-cache
    clean_cache_parser = subparsers.add_parser(
        "clean-cache", help="Scan and optionally purge system/dev caches"
    )
    clean_cache_parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete cache contents (default: dry-run preview)",
    )

    # clean-dev
    clean_dev_parser = subparsers.add_parser(
        "clean-dev",
        help="Scan and optionally remove regenerable dev dependencies (node_modules, .venv)",
    )
    clean_dev_parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete directories (default: dry-run preview)",
    )
    clean_dev_parser.add_argument(
        "--min-mb",
        type=float,
        default=30.0,
        help="Minimum directory size in MB to show (default: 30)",
    )

    # ── Cloud Archival & Packaging Command ──────────────────────────────
    pack_parser = subparsers.add_parser(
        "pack",
        help="Package large directories/repacks for cloud cold storage (split volumes, parity, store mode)",
    )
    pack_parser.add_argument("source", help="Source directory or file to package")
    pack_parser.add_argument("--staging", help="Staging output directory (default: auto-picked drive)")
    pack_parser.add_argument("--name", help="Archive name")
    pack_parser.add_argument(
        "--split", default="10g", help="Volume split size (e.g. '10g', '5g', default: 10g)"
    )
    pack_parser.add_argument(
        "--parity", type=int, default=3, help="Recovery record percentage (default: 3%%)"
    )
    pack_parser.add_argument("--password", "-p", help="Optional encryption password")
    pack_parser.add_argument(
        "--cloud", default="Google Drive (5TB)", help="Cloud provider name for catalog descriptor"
    )
    pack_parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the packaging command immediately (default: preview analysis and command)",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    init_db()

    if args.command == "scan":
        label = args.label or args.path.rstrip("/\\").replace(":", "")
        print(f"[OmniVault] Starting scan of '{args.path}' under volume label '{label}'...")
        res = index_volume(
            mount_point=args.path,
            label=label,
            role=args.role,
            disk_name=args.disk,
            compute_hash=not args.no_hash,
            make_thumbnails=not args.no_thumb,
            verbose=True,
        )
        print(
            f"[OmniVault] Indexing complete: {res['total_files']} files ({res['total_size_formatted']})."
        )

    elif args.command == "find":
        results = find_files(
            query=args.query,
            category=args.category,
            volume_label=args.volume,
            extension=args.ext,
            limit=args.limit,
        )
        print_search_results(results)

    elif args.command == "status":
        check_all_volumes_online_status()
        stats = get_stats()
        print("\n==================== OMNIVAULT STATUS ====================")
        print(f"Total Indexed Files: {stats['total_files']:,}")
        print(f"Total Indexed Volume Size: {stats['total_size_formatted']}")
        print("\nVolumes:")
        for v in stats["volumes"]:
            online_str = (
                "\033[92mONLINE\033[0m" if v["is_online"] else "\033[91mOFFLINE (Unplugged)\033[0m"
            )
            print(
                f"  * [{v['label']}] {v['mount_point']} ({v['role']}) -> {v['file_count']:,} files ({v['total_size_formatted']}) [{online_str}]"
            )

        print("\nCategories:")
        for c in stats["categories"]:
            print(f"  * {c['name']:<12}: {c['count']:>6} files ({c['size_formatted']})")
        print("==========================================================\n")

    elif args.command == "verify-vault":
        import json

        from omnivault.verify import print_verify_report, verify_vault_integrity

        def progress(curr, tot, name):
            print(
                f"\r[OmniVault Verify] Auditing {curr}/{tot} files ({name[:30]})...",
                end="",
                flush=True,
            )

        if not args.json:
            print("[OmniVault] Initiating cryptographic vault verification...")

        res = verify_vault_integrity(
            volume_identifier=args.volume,
            sample_pct=args.sample,
            progress_callback=None if args.json else progress,
        )
        if not args.json:
            print()  # Clear line after progress

        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print_verify_report(res)

    elif args.command == "import-wired":
        from omnivault.staging import import_wired_folder

        print(f"[OmniVault] Importing files from wired source: {args.source}...")
        res = import_wired_folder(args.source, skip_existing=not args.no_skip, verbose=True)
        print(
            f"[OmniVault] Wired import finished: {res['imported']} new files imported ({res['total_formatted']}), {res['skipped']} duplicates skipped."
        )

    elif args.command == "offload":
        from omnivault.staging import offload_staging_to_vault

        print(f"[OmniVault] Offloading staged files to {args.vault}...")
        res = offload_staging_to_vault(
            vault_mount=args.vault, vault_label=args.label, dry_run=args.dry_run, verbose=True
        )
        print(
            f"[OmniVault] Offload completed: {res['offloaded']} files moved ({res['formatted']})."
        )

    elif args.command == "watch-localsend":
        from omnivault.watcher import start_localsend_watcher

        start_localsend_watcher()

    elif args.command == "serve":
        from omnivault.web import run_server

        print(f"[OmniVault] Launching instant search Web UI on http://{args.host}:{args.port}...")
        run_server(host=args.host, port=args.port)

    elif args.command == "storage-report":
        from omnivault.storage import generate_full_report

        print("\n[OmniVault] Generating system storage health & optimization report...")
        report = generate_full_report()

        print("\n" + "=" * 70)
        print("                  SYSTEM STORAGE HEALTH REPORT")
        print("=" * 70)

        print("\n1. DRIVE VOLUMES:")
        print(f"  {'Drive':<6} {'Label':<14} {'Total':<10} {'Free':<10} {'Used %':<8} {'Status'}")
        print("  " + "-" * 60)
        for d in report["drives"]:
            status = "HEALTHY" if d["used_pct"] < 85 else "\033[91mWARNING (HIGH)\033[0m"
            print(
                f"  {d['letter'] + ':':<6} {d['label'][:13]:<14} {d['total_formatted']:<10} {d['free_formatted']:<10} {d['used_pct']:>5.1f}%   {status}"
            )

        print("\n2. CACHE & TEMP BLOAT (Safely Purgeable):")
        cache = report.get("cache_bloat", {})
        for c in cache.get("entries", []):
            print(f"  * {c['label']:<28} -> {c['size_formatted']:>9} ({c['files']} files)")
        print(
            f"  --> Total Reclaimable Cache Space: \033[92m{cache.get('total_formatted', '0 B')}\033[0m"
        )

        print("\n3. DEV DEPENDENCY BLOAT (node_modules, .venv):")
        dev = report.get("dev_bloat", {})
        for d in dev.get("entries", [])[:10]:
            print(f"  * [{d['name']}] {d['project']} -> {d['size_formatted']}")
        print(
            f"  --> Total Dev Dependency Footprint: \033[93m{dev.get('total_formatted', '0 B')}\033[0m"
        )

        dups = report.get("duplicates", {})
        print("\n4. CONTENT DEDUPLICATION:")
        print(f"  * Found {dups.get('total_groups', 0)} duplicate groups across indexed files.")
        print(
            f"  --> Wasted Duplicate Storage: \033[96m{dups.get('wasted_formatted', '0 B')}\033[0m"
        )

        large = report.get("large_files", {})
        print("\n5. LARGEST FILES (> 100MB):")
        for lf in large.get("files", [])[:8]:
            print(f"  * {lf['size_formatted']:>9} | [{lf['category']:<9}] {lf['filename']}")
            print(f"    {lf['path']}")

        print("\n" + "=" * 70)
        print(
            f"  ESTIMATED TOTAL RECLAIMABLE SPACE: \033[1m\033[92m{report['total_reclaimable_formatted']}\033[0m"
        )
        print("  Run 'omnivault clean-cache' to safely purge cache bloat.")
        print("=" * 70 + "\n")

    elif args.command == "duplicates":
        from omnivault.storage import find_duplicates

        dups = find_duplicates(min_size=args.min_size)
        print(f"\nFound {len(dups)} duplicate groups (min size: {args.min_size} bytes):\n")
        wasted_sum = sum(d["wasted_bytes"] for d in dups)
        for idx, g in enumerate(dups[: args.limit], 1):
            print(
                f" Group {idx}: {g['count']} copies of {g['each_size_formatted']} each (Wasted: {g['wasted_formatted']})"
            )
            print(f" BLAKE3: {g['blake3_hash']}")
            for f in g["files"]:
                print(f"   - [{f['volume_label']}] {f['abs_path']}")
            print()
        print(f"Total potential savings across all duplicates: {wasted_sum} bytes.")

    elif args.command == "large-files":
        from omnivault.storage import find_large_files

        print(f"[OmniVault] Scanning for files >= {args.min_mb}MB under {args.root}...")
        large = find_large_files(root=args.root, min_size_mb=args.min_mb, limit=args.limit)
        print(f"\nFound {len(large)} large files:\n")
        for idx, f in enumerate(large, 1):
            print(f" {idx:2d}. {f['size_formatted']:>10} | [{f['category']:<9}] {f['filename']}")
            print(f"     {f['path']}")
        print()

    elif args.command == "clean-cache":
        from omnivault.storage import clean_cache_dir, scan_cache_bloat

        caches = scan_cache_bloat()
        if not caches:
            print("[OmniVault] No cache bloat detected.")
            return

        dry_run = not args.execute
        mode_str = "DRY-RUN PREVIEW" if dry_run else "EXECUTING PURGE"
        print(f"\n[OmniVault] Cache Cleaner ({mode_str}):\n")
        total_freed = 0
        for c in caches:
            if not c.safe_to_delete:
                continue
            res = clean_cache_dir(c.path, dry_run=dry_run)
            action_tag = "[WOULD FREE]" if dry_run else "[FREED]"
            print(
                f"  {action_tag} {res['freed_formatted']:>9} ({res['files_deleted']} files) from {c.label}"
            )
            print(f"               Path: {c.path}")
            total_freed += res["freed_bytes"]

        from omnivault.db import format_bytes

        formatted = format_bytes(total_freed)
        if dry_run:
            print(f"\n[OmniVault] Dry-run complete. Would reclaim: \033[92m{formatted}\033[0m.")
            print("To execute real cleanup, run: omnivault clean-cache --execute")
        else:
            print(
                f"\n[OmniVault] Cleanup complete! Successfully reclaimed: \033[92m{formatted}\033[0m."
            )

    elif args.command == "clean-dev":
        from omnivault.storage import scan_dev_bloat

        dev_items = scan_dev_bloat(min_size_mb=args.min_mb)
        if not dev_items:
            print("[OmniVault] No regenerable dev dependencies found above threshold.")
            return

        dry_run = not args.execute
        mode_str = "DRY-RUN PREVIEW" if dry_run else "EXECUTING PURGE"
        print(f"\n[OmniVault] Dev Dependency Cleaner ({mode_str}):\n")
        for idx, item in enumerate(dev_items, 1):
            action_tag = "[WOULD REMOVE]" if dry_run else "[REMOVED]"
            print(
                f" {idx:2d}. {action_tag} {item.size_formatted:>9} | [{item.name}] {item.parent_project}"
            )
            print(f"     Path: {item.path}")

        total_bytes = sum(i.size_bytes for i in dev_items)
        from omnivault.db import format_bytes

        formatted = format_bytes(total_bytes)
        if dry_run:
            print(
                f"\n[OmniVault] Dry-run complete. Would reclaim: \033[92m{formatted}\033[0m across {len(dev_items)} directories."
            )
            print(
                "Note: To remove specific directories, target them manually or pass --execute with caution."
            )
        else:
            print("\n[OmniVault] Ready for targeted removal.")

    elif args.command == "pack":
        from omnivault.cloud_pack import run_cloud_pack

        print(f"\n[OmniVault Pack] Inspecting payload: {args.source}...")
        try:
            res = run_cloud_pack(
                source_dir=args.source,
                staging_dir=args.staging,
                archive_name=args.name,
                split_size=args.split,
                parity_pct=args.parity,
                password=args.password,
                cloud_provider=args.cloud,
                execute=args.execute,
            )
        except Exception as e:
            print(f"\033[91m[OmniVault Error]\033[0m {e}")
            sys.exit(1)

        print("\n==================== OMNIVAULT CLOUD PACK ====================")
        print(f" Source Payload      : {res['source']}")
        print(f" Total Payload Size  : {res['total_formatted']} ({res['total_files']} files)")
        pre_str = f"YES ({res['precompressed_pct']}% pre-compressed)" if res['is_precompressed'] else "NO"
        print(f" Pre-Compressed      : {pre_str}")
        print(f" Compression Mode    : {res['recommended_mode'].upper()} (Store Mode - zero CPU bottleneck)")
        print(f" Staging Target      : {res['staging_dir']}")
        print(f" Staging Free Headroom: Drive {res['staging_drive']}: with {res['staging_free']} free")
        print(f" Archiver Engine     : {res['tool_type'].upper()}")
        print(f" Generated Command   : {res['command_str']}")
        print("==============================================================")

        if not args.execute:
            print("\n\033[93m[PREVIEW MODE]\033[0m No files were packaged yet.")
            print("To execute this stream at hardware drive speed and register in catalog, run:")
            print(f"  omnivault pack \"{args.source}\" --execute" + (f" --split {args.split}" if args.split != "10g" else ""))
        else:
            print("\n\033[92m[SUCCESS]\033[0m Packaging complete!")
            print(f" Elapsed Time        : {res.get('elapsed_seconds', 0)} seconds")
            print(f" Volumes Generated   : {len(res['volume_parts'])} parts")
            print(f" Catalog Registered  : Volume #{res['catalog_volume_id']} in ~/.omnivault/catalog.db")
            print("\nYou can now safely upload these volumes to Google Drive.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
