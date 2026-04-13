"""
core/paths.py
Centralised path resolution for SubForge.

When running from source:
    BASE_DIR          = repo root
    USER_DIR          = repo root (settings.json lives here)
    PROFILES_DIR      = repo root / regex_profiles / default
    USER_PROFILES_DIR = same as PROFILES_DIR

When running as a PyInstaller bundle on Windows:
    BASE_DIR          = sys._MEIPASS  (read-only extracted bundle)
    USER_DIR          = %APPDATA%/SubForge  (writable, persists)
    PROFILES_DIR      = _MEIPASS / regex_profiles / default  (read-only)
    USER_PROFILES_DIR = %APPDATA%/SubForge / regex_profiles / default  (writable)

When running as a PyInstaller bundle on macOS/Linux:
    USER_DIR          = ~/.SubForge
"""

import os
import sys
from pathlib import Path


def _frozen() -> bool:
    return getattr(sys, "frozen", False)


def _get_base_dir() -> Path:
    """Read-only root — where bundled assets live."""
    if _frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def _get_user_dir() -> Path:
    """
    Writable root — where settings.json and user profiles live.
    Must never be inside Program Files or the bundle's temp dir.
    """
    if _frozen():
        if sys.platform == "win32":
            # %APPDATA%\SubForge  e.g. C:\Users\dave\AppData\Roaming\SubForge
            base = Path(os.environ.get("APPDATA", Path.home()))
        else:
            # ~/.SubForge on macOS / Linux
            base = Path.home()
        user_dir = base / "SubForge"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    # Running from source — repo root, same as always
    return Path(__file__).parent.parent


BASE_DIR: Path       = _get_base_dir()
USER_DIR: Path       = _get_user_dir()

SETTINGS_FILE: Path      = USER_DIR / "settings.json"
PROFILES_DIR: Path       = BASE_DIR / "regex_profiles" / "default"
USER_PROFILES_DIR: Path  = USER_DIR / "regex_profiles" / "default"
CHANGELOG_FILE: Path     = BASE_DIR / "CHANGELOG.md"


def list_profile_dirs() -> list:
    """Return all profile dirs that exist, deduplicated."""
    seen = set()
    result = []
    for d in [PROFILES_DIR, USER_PROFILES_DIR]:
        if d not in seen:
            seen.add(d)
            if d.exists():
                result.append(d)
    return result


def ensure_user_profiles_dir() -> Path:
    """Create USER_PROFILES_DIR if needed and return it."""
    USER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return USER_PROFILES_DIR
