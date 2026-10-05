"""
Search and Query Engine for OmniVault
Provides instant lookups, location-aware status resolution, and result formatting.
"""

from omnivault.db import (
    check_all_volumes_online_status,
    search,
)


def find_files(
    query: str,
    category: str | None = None,
    volume_label: str | None = None,
    extension: str | None = None,
    limit: int = 50,
) -> dict:
    """
    High-level search API.
    Checks live volume mount statuses and returns enriched, location-aware results.
    """
    # Refresh live hardware presence
    check_all_volumes_online_status()

    # Execute FTS5 query
    return search(
        query=query,
        category=category,
        volume_label=volume_label,
        extension=extension,
        limit=limit,
    )


def print_search_results(results: dict) -> None:
    """Prints beautiful formatted search results to terminal."""
    total = results["total"]
    duration = results["duration_ms"]
    items = results["items"]
    query = results["query"]

    print(f"\nFound {total} results for '{query}' in {duration} ms:\n")

    if not items:
        print("  No matching files found.")
        return

    for idx, item in enumerate(items, 1):
        status = item["status"]
        if status == "COLD_ONLINE":
            status_tag = "\033[92m[COLD-ONLINE]\033[0m"
        elif status == "COLD_OFFLINE":
            status_tag = "\033[93m[COLD-OFFLINE]\033[0m"
        else:
            status_tag = "\033[96m[WARM-LAPTOP]\033[0m"

        has_thumb = " [img]" if item["has_thumbnail"] else ""
        print(
            f" {idx:2d}. {status_tag}{has_thumb} \033[1m{item['filename']}\033[0m ({item['size_formatted']})"
        )
        print(
            f"     Volume: {item['volume_label']} | Category: {item['category']} | Path: {item['rel_path']}"
        )
        print(f"     Exact: {item['abs_path']}")
        if item["blake3_hash"]:
            print(f"     BLAKE3: {item['blake3_hash'][:16]}...")
        print()
