"""
LocalSend Staging Folder Watcher for OmniVault
Uses watchdog to detect new incoming files from LocalSend and automatically ingest them.
Waits for file-write stability and exclusive access before initiating ingestion.
"""

from __future__ import annotations

import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from omnivault.config import INCOMING_LOCALSEND
from omnivault.staging import ensure_staging_dirs, ingest_file_to_staging


def wait_for_file_stability(
    path: Path,
    interval: float = 1.0,
    consecutive_matches: int = 2,
    timeout: float = 600.0,
) -> bool:
    """
    Waits until a file's size remains unchanged for consecutive checks
    and can be opened for reading, ensuring the transfer is complete.
    """
    start_time = time.time()
    last_size = -1
    stable_count = 0

    while time.time() - start_time < timeout:
        if not path.exists():
            return False

        try:
            current_size = path.stat().st_size
            if current_size == last_size and current_size > 0:
                # Try opening file to verify exclusive lock is released
                with open(path, "rb"):
                    pass
                stable_count += 1
                if stable_count >= consecutive_matches:
                    return True
            else:
                last_size = current_size
                stable_count = 0
        except (OSError, PermissionError):
            stable_count = 0

        time.sleep(interval)

    return False


class LocalSendHandler(FileSystemEventHandler):
    """Event handler that triggers ingestion on new incoming files."""

    def _handle_path(self, file_path: str):
        path = Path(file_path)
        if (
            path.is_file()
            and not path.name.endswith((".tmp", ".partial", ".crdownload"))
            and not path.name.startswith(".")
        ):
            print(f"\n[LocalSend Watcher] Detected new incoming file: {path.name}")
            if wait_for_file_stability(path):
                print(f"[LocalSend Ingest] File write complete. Ingesting {path.name}...")
                res = ingest_file_to_staging(path, stream="localsend")
                if res:
                    print(f"[LocalSend Ingest] Indexed {path.name} into Staging catalog.")
            else:
                print(f"[LocalSend Watcher] Timed out waiting for {path.name} to stabilize.")

    def on_created(self, event):
        if not event.is_directory:
            self._handle_path(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle_path(event.dest_path)


def start_localsend_watcher():
    """Starts watching the incoming LocalSend staging folder."""
    ensure_staging_dirs()
    event_handler = LocalSendHandler()
    observer = Observer()
    observer.schedule(event_handler, str(INCOMING_LOCALSEND), recursive=False)
    observer.start()
    print(f"[OmniVault] Watching for incoming LocalSend files at: {INCOMING_LOCALSEND}")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
