"""
core/logger.py — Centralised error logging for SubForge.

Log path follows the same frozen/source logic as core/paths.USER_DIR:
  - Frozen (installer): %APPDATA%\\SubForge\\subforge_errors.log  (Windows)
                        ~/.SubForge/subforge_errors.log           (macOS/Linux)
  - Source:             <repo_root>/subforge_errors.log

Entries are APPENDED, never overwritten, so multiple errors in a session
accumulate.  Each entry is delimited and includes a UTC timestamp, the
originating tab/module, and the full traceback.

Public API
----------
  get_log_path() -> Path
  append_error(source: str, traceback_text: str) -> None
  read_log() -> str          # returns full log text, or "" if absent/empty
  clear_log() -> None
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


_FILENAME = "subforge_errors.log"
_SEP      = "=" * 72


def get_log_path() -> Path:
    """Return the writable log path — works in both source and frozen modes."""
    from .paths import USER_DIR
    return USER_DIR / _FILENAME


def append_error(source: str, traceback_text: str) -> None:
    """
    Append a timestamped error entry to the log.

    Parameters
    ----------
    source : str
        Short identifier for where the error came from, e.g. "Batch",
        "Video Scan", "Settings", "launch".
    traceback_text : str
        The full traceback string, typically from traceback.format_exc().
    """
    try:
        log_path = get_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = (
            f"\n{_SEP}\n"
            f"Time   : {ts}\n"
            f"Source : {source}\n"
            f"{_SEP}\n"
            f"{traceback_text.strip()}\n"
        )
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        # Never let the logger itself crash the app
        pass


def read_log() -> str:
    """Return full log contents, or empty string if absent or empty."""
    try:
        p = get_log_path()
        if p.exists():
            text = p.read_text(encoding="utf-8").strip()
            return text
    except Exception:
        pass
    return ""


def clear_log() -> None:
    """Delete the log file if it exists."""
    try:
        p = get_log_path()
        if p.exists():
            p.unlink()
    except Exception:
        pass
