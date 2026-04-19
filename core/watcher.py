"""
core/watcher.py
Watch Folder manager for SubForge.

Monitors one or more folders for new subtitle files using QFileSystemWatcher
(OS-level notifications — no polling).  When a new subtitle file appears it is
automatically cleaned using the current global cleaning options and the current
default sensitivity threshold.

Design rules:
- QFileSystemWatcher lives on the main thread (it is a QObject).
- File cleaning runs in a WatchCleanWorker (QThread) so the UI never blocks.
- Results are marshalled back to the main thread via pyqtSignal — never
  QTimer.singleShot from a plain Python thread.
- Folder list is persisted in settings.json under the "watch_folders" key.
- Works identically in the frozen .exe and from source.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, QFileSystemWatcher

from core.paths import load_settings, save_settings
from core.subtitle import SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_watch_folders() -> List[str]:
    """Return the list of watched folder paths from settings.json."""
    return load_settings().get("watch_folders", [])


def save_watch_folders(folders: List[str]) -> None:
    """Persist the list of watched folder paths to settings.json."""
    s = dict(load_settings())
    s["watch_folders"] = folders
    save_settings(s)


# ---------------------------------------------------------------------------
# Background cleaning worker
# ---------------------------------------------------------------------------

class WatchCleanWorker(QThread):
    """
    Cleans a single subtitle file in a background thread.
    Emits finished(path, ads_removed, error_msg) on the main thread.
    """
    finished = pyqtSignal(str, int, str)   # path, ads_removed, error

    def __init__(self, path: Path, threshold: int, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._path      = path
        self._threshold = threshold

    def run(self):
        path = self._path
        import time as _time
        import os as _os

        # Wait until the file size stops changing before attempting to read it.
        # This handles Windows Explorer copies, which create the file immediately
        # but hold the handle open until writing is complete.
        # Poll every 250 ms; give up after 10 seconds (40 polls).
        try:
            prev_size = -1
            for _ in range(40):
                try:
                    cur_size = _os.path.getsize(path)
                except OSError:
                    cur_size = -1
                if cur_size == prev_size and cur_size >= 0:
                    break   # size stable — file write is complete
                prev_size = cur_size
                _time.sleep(0.25)
            else:
                self.finished.emit(str(path), 0,
                                   f"Timed out waiting for file to finish writing: {path.name}")
                return
        except Exception as exc:
            self.finished.emit(str(path), 0, str(exc))
            return

        self._clean(path)

    def _clean(self, path: Path) -> None:
        """Perform the actual clean. Called only after file-size stability confirmed."""
        try:
            from core.subtitle import load_subtitle, write_subtitle
            from core.cleaner import analyze
            from gui.settings_dialog import load_cleaning_options
            from core.cleaner_options import apply_cleaning_options

            sub = load_subtitle(path)
            analyze(sub)

            ad_ids = {id(b) for b in sub.blocks
                      if b.regex_matches >= self._threshold}
            if not ad_ids:
                self.finished.emit(str(path), 0, "")
                return

            ads_count = len(ad_ids)
            sub.blocks = [b for b in sub.blocks if id(b) not in ad_ids]
            for i, b in enumerate(sub.blocks, 1):
                b.current_index = i

            opts = load_cleaning_options()
            if opts.any_enabled():
                apply_cleaning_options(sub, opts)

            write_subtitle(sub)
            self.finished.emit(str(path), ads_count, "")

        except Exception as exc:
            self.finished.emit(str(path), 0, str(exc))


# ---------------------------------------------------------------------------
# WatchFolderManager
# ---------------------------------------------------------------------------

class WatchFolderManager(QObject):
    """
    Manages the set of watched folders and reacts to new subtitle files.

    Signals
    -------
    file_cleaned(path, ads_removed)
        Emitted on the main thread when a file was cleaned successfully.
    file_error(path, error)
        Emitted on the main thread when cleaning a new file failed.
    status_changed(is_active)
        Emitted whenever the active/inactive state changes (folders added /
        removed so the status bar badge can update).
    """

    file_cleaned   = pyqtSignal(str, int)   # path, ads_removed
    file_error     = pyqtSignal(str, str)   # path, error_message
    status_changed = pyqtSignal(bool)        # is_active

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._watcher   = QFileSystemWatcher(self)
        self._folders:  List[str] = []
        self._workers:  List[WatchCleanWorker] = []
        # Track files we've already seen so we don't double-process on
        # spurious directoryChanged signals (QFileSystemWatcher fires on
        # any change including metadata writes).
        self._seen: set = set()
        self._threshold: int = 3

        self._watcher.directoryChanged.connect(self._on_dir_changed)

    # ── Public API ────────────────────────────────────────────────────────

    def set_threshold(self, threshold: int) -> None:
        """Update the sensitivity threshold used for auto-cleaning."""
        self._threshold = threshold

    def set_folders(self, folders: List[str]) -> None:
        """
        Replace the full watched folder list.
        Removes old watches and adds new ones atomically.
        Adds subdirectories to the watcher so new files in subfolders
        are also detected via QFileSystemWatcher directory notifications.
        """
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        self._folders = [f for f in folders if Path(f).is_dir()]
        self._seen.clear()
        if self._folders:
            # Watch the top-level folders AND all existing subdirectories so
            # QFileSystemWatcher fires directoryChanged for any depth.
            all_dirs_to_watch = []
            for folder in self._folders:
                all_dirs_to_watch.append(folder)
                for sub in Path(folder).rglob("*"):
                    if sub.is_dir():
                        all_dirs_to_watch.append(str(sub))
            self._watcher.addPaths(all_dirs_to_watch)
            # Snapshot all existing subtitle files so we only react to new ones
            for folder in self._folders:
                for p in Path(folder).rglob("*"):
                    if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                        self._seen.add(str(p))
        self.status_changed.emit(bool(self._folders))

    def clean_existing_recursive(self, folder: str) -> None:
        """
        Immediately queue all existing subtitle files in folder (recursively)
        for cleaning.  Called after the user confirms the warning dialog when
        adding a new watch folder that already contains files.
        """
        for p in Path(folder).rglob("*"):
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            key = str(p)
            # Add to seen so the watcher doesn't double-process them later
            self._seen.add(key)
            self._launch_worker(p)

    def folders(self) -> List[str]:
        return list(self._folders)

    def is_active(self) -> bool:
        return bool(self._folders)

    # ── Internal ──────────────────────────────────────────────────────────

    def _on_dir_changed(self, directory: str) -> None:
        """Called by QFileSystemWatcher on the main thread when a dir changes."""
        folder = Path(directory)
        if not folder.is_dir():
            return
        # If a new subdirectory was created, add it to the watcher too
        for sub in folder.iterdir():
            if sub.is_dir() and str(sub) not in self._watcher.directories():
                self._watcher.addPath(str(sub))
        # Check for new subtitle files in this directory only (subdirs get
        # their own directoryChanged signal once watched above)
        for p in folder.iterdir():
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            key = str(p)
            if key in self._seen:
                continue
            self._seen.add(key)
            self._launch_worker(p)

    def _launch_worker(self, path: Path) -> None:
        worker = WatchCleanWorker(path, self._threshold, parent=self)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(lambda *_: self._workers.remove(worker)
                                if worker in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _on_worker_finished(self, path: str, ads_removed: int, error: str) -> None:
        if error:
            self.file_error.emit(path, error)
        else:
            self.file_cleaned.emit(path, ads_removed)
