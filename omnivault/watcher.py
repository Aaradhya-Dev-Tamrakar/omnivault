"""
LocalSend Staging Folder Watcher for OmniVault
Uses watchdog to detect new incoming files from LocalSend and automatically ingest them.
"""

import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from omnivault.config import INCOMING_LOCALSEND
from omnivault.staging import ingest_file_to_staging, ensure_staging_dirs


class LocalSendHandler(FileSystemEventHandler):
    """Event handler that triggers ingestion on new incoming files."""

    def on_created(self, event):
        if event.is_directory:
            return
        # Wait a split second for write completion
        time.sleep(0.5)
        path = Path(event.src_path)
        if path.is_file() and not path.name.endswith(".tmp") and not path.name.startswith("."):
            print(f"\n[LocalSend Ingest] Detected new incoming file: {path.name}")
            res = ingest_file_to_staging(path, stream="localsend")
            if res:
                print(f"[LocalSend Ingest] Indexed {path.name} into Staging catalog.")


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
