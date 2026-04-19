"""
core/scheduler.py
Scheduled folder scanning for SubForge.

The user configures one or more folders, each with a flexible scan interval:
  - Every X minutes
  - Every X hours
  - Every X days at a specific HH:MM time (local time)

Design rules:
- QTimer lives on the main thread (it is a QObject).
- Actual scanning runs in ScheduledScanWorker (QThread) — UI never blocks.
- Results are marshalled back to the main thread via pyqtSignal, never
  QTimer.singleShot from a plain Python thread.
- Schedule config is persisted in settings.json under "schedules".
- Works identically in the frozen .exe and from source.
- The scheduler will not fire while a manual Batch or Embedded Subs scan
  is running — the main app sets a lock via set_scan_active().
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from core.paths import load_settings, save_settings
from core.subtitle import SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ScheduleConfig:
    folder:         str
    interval_type:  str   # "minutes" | "hours" | "days"
    interval_value: int   # e.g. 30, 2, 1
    time_of_day:    str   # "HH:MM" — only used when interval_type == "days"
    last_run:       str = ""  # ISO-8601 UTC string, empty = never run

    # ── Legacy migration map ───────────────────────────────────────────────
    # Old schedules stored interval as "hourly"/"nightly"/"weekly".
    # from_dict() converts them automatically.
    _LEGACY = {
        "hourly":  ("hours",   1,  ""),
        "nightly": ("days",    1,  "02:00"),
        "weekly":  ("days",    7,  "02:00"),
    }

    def interval_seconds(self) -> float:
        """Return the interval as a number of seconds."""
        if self.interval_type == "minutes":
            return self.interval_value * 60.0
        if self.interval_type == "hours":
            return self.interval_value * 3600.0
        # days — time_of_day aware
        return self.interval_value * 86400.0

    def is_due(self) -> bool:
        if not self.last_run:
            return True
        try:
            last = datetime.datetime.fromisoformat(self.last_run)
        except ValueError:
            return True

        now = datetime.datetime.utcnow()

        if self.interval_type == "days" and self.time_of_day:
            # For day-based schedules with a time of day, check whether the
            # scheduled wall-clock time has passed since the last run.
            try:
                hh, mm = self.time_of_day.split(":")
                target_local = datetime.datetime.now().replace(
                    hour=int(hh), minute=int(mm), second=0, microsecond=0
                )
                # How far ahead of last_run (UTC) are we?
                elapsed = (now - last).total_seconds()
                interval = self.interval_seconds()
                return elapsed >= interval and datetime.datetime.now() >= target_local
            except (ValueError, AttributeError):
                pass

        return (now - last).total_seconds() >= self.interval_seconds()

    def mark_run(self) -> None:
        self.last_run = datetime.datetime.utcnow().isoformat()

    def display_label(self) -> str:
        """Human-readable interval string for the list widget."""
        if self.interval_type == "minutes":
            return f"Every {self.interval_value} min"
        if self.interval_type == "hours":
            return f"Every {self.interval_value} hr"
        # days
        suffix = f" at {self.time_of_day}" if self.time_of_day else ""
        every = "day" if self.interval_value == 1 else f"{self.interval_value} days"
        return f"Every {every}{suffix}"

    def to_dict(self) -> dict:
        return {
            "folder":         self.folder,
            "interval_type":  self.interval_type,
            "interval_value": self.interval_value,
            "time_of_day":    self.time_of_day,
            "last_run":       self.last_run,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduleConfig":
        # New-style config
        if "interval_type" in d:
            return cls(
                folder=d.get("folder", ""),
                interval_type=d.get("interval_type", "hours"),
                interval_value=int(d.get("interval_value", 1)),
                time_of_day=d.get("time_of_day", ""),
                last_run=d.get("last_run", ""),
            )
        # Legacy config ("hourly" / "nightly" / "weekly")
        legacy_key = d.get("interval", "nightly")
        itype, ival, tod = cls._LEGACY.get(legacy_key, ("hours", 1, ""))
        return cls(
            folder=d.get("folder", ""),
            interval_type=itype,
            interval_value=ival,
            time_of_day=tod,
            last_run=d.get("last_run", ""),
        )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_schedules() -> List[ScheduleConfig]:
    """Return the list of ScheduleConfig objects from settings.json."""
    raw = load_settings().get("schedules", [])
    return [ScheduleConfig.from_dict(d) for d in raw]


def save_schedules(schedules: List[ScheduleConfig]) -> None:
    """Persist the list of ScheduleConfig objects to settings.json."""
    s = dict(load_settings())
    s["schedules"] = [sc.to_dict() for sc in schedules]
    save_settings(s)


# ---------------------------------------------------------------------------
# Background scan worker
# ---------------------------------------------------------------------------

class ScheduledScanWorker(QThread):
    """
    Scans a single folder recursively, cleans all ad-flagged subtitle files,
    and emits a summary on the main thread when done.

    Signals
    -------
    finished(folder, cleaned_count, error_count, total_count)
    """
    finished = pyqtSignal(str, int, int, int)   # folder, cleaned, errors, total

    def __init__(self, folder: str, threshold: int,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._folder    = folder
        self._threshold = threshold

    def run(self):
        folder = Path(self._folder)
        if not folder.is_dir():
            self.finished.emit(self._folder, 0, 0, 0)
            return

        from core.subtitle import load_subtitle, write_subtitle
        from core.cleaner import analyze
        from gui.settings_dialog import load_cleaning_options
        from core.cleaner_options import apply_cleaning_options

        opts = load_cleaning_options()
        paths = [p for p in folder.rglob("*")
                 if p.suffix.lower() in SUPPORTED_EXTENSIONS]
        cleaned = 0
        errors  = 0

        for path in paths:
            try:
                sub = load_subtitle(path)
                analyze(sub)
                ad_ids = {id(b) for b in sub.blocks
                          if b.regex_matches >= self._threshold}
                if not ad_ids:
                    continue
                sub.blocks = [b for b in sub.blocks if id(b) not in ad_ids]
                for i, b in enumerate(sub.blocks, 1):
                    b.current_index = i
                if opts.any_enabled():
                    apply_cleaning_options(sub, opts)
                write_subtitle(sub)
                cleaned += 1
            except Exception:
                errors += 1

        self.finished.emit(self._folder, cleaned, errors, len(paths))


# ---------------------------------------------------------------------------
# SchedulerManager
# ---------------------------------------------------------------------------

class SchedulerManager(QObject):
    """
    Owns the list of ScheduleConfig objects and the QTimer that fires
    every 60 seconds to check for overdue jobs.

    Signals
    -------
    scan_started(folder)
        Emitted on the main thread when a scheduled scan begins.
    scan_finished(folder, cleaned, errors, total)
        Emitted on the main thread when a scheduled scan completes.
    """

    scan_started  = pyqtSignal(str)              # folder
    scan_finished = pyqtSignal(str, int, int, int)  # folder, cleaned, errors, total

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._schedules: List[ScheduleConfig] = []
        self._workers:   List[ScheduledScanWorker] = []
        self._threshold: int = 3
        self._scan_active: bool = False   # set by app when manual scan runs

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)   # check every 60 seconds
        self._timer.timeout.connect(self._check_schedules)

    # ── Public API ────────────────────────────────────────────────────────

    def set_threshold(self, threshold: int) -> None:
        self._threshold = threshold

    def set_scan_active(self, active: bool) -> None:
        """Called by the app to pause scheduled jobs during manual scans."""
        self._scan_active = active

    def set_schedules(self, schedules: List[ScheduleConfig]) -> None:
        """Replace the full schedule list and restart the timer if non-empty."""
        self._schedules = schedules
        if schedules:
            if not self._timer.isActive():
                self._timer.start()
            # Run any overdue jobs immediately
            self._check_schedules()
        else:
            self._timer.stop()

    def schedules(self) -> List[ScheduleConfig]:
        return list(self._schedules)

    def is_active(self) -> bool:
        return bool(self._schedules)

    # ── Internal ──────────────────────────────────────────────────────────

    def _check_schedules(self) -> None:
        if self._scan_active:
            return
        for sc in self._schedules:
            if not Path(sc.folder).is_dir():
                continue
            if sc.is_due():
                sc.mark_run()
                # Persist updated last_run immediately so a crash doesn't re-run
                save_schedules(self._schedules)
                self._launch_worker(sc.folder)

    def _launch_worker(self, folder: str) -> None:
        worker = ScheduledScanWorker(folder, self._threshold, parent=self)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(
            lambda *_: self._workers.remove(worker)
            if worker in self._workers else None
        )
        self._workers.append(worker)
        self.scan_started.emit(folder)
        worker.start()

    def _on_worker_finished(self, folder: str, cleaned: int,
                             errors: int, total: int) -> None:
        self.scan_finished.emit(folder, cleaned, errors, total)
