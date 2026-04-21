"""
Update checker for SubForge.
Compares current version against latest GitHub release tag using semantic versioning.
Entirely opt-in — only runs when the user clicks "Check for Updates".

v1.1.0 adds in-app download with SHA-256 checksum verification for Windows.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import urllib.request
import json
from pathlib import Path
from typing import Callable, Optional, Tuple

CURRENT_VERSION = "v1.1.0"
GITHUB_API_URL  = "https://api.github.com/repos/babcockdavidr/SubForge/releases/latest"
RELEASES_URL    = "https://github.com/babcockdavidr/SubForge/releases"

# Expected installer asset pattern
_INSTALLER_RE  = re.compile(r"SubForge-[\d.]+-setup\.exe$", re.IGNORECASE)


def _parse_version(tag: str) -> Tuple:
    """
    Parse a version tag into a comparable tuple.
    Handles both stable (v1.2.3) and beta (v0.4.0) tags.
    Strips leading 'v' before parsing.
    Returns a tuple of ints for comparison, e.g. (1, 2, 3) or (0, 4, 0).
    """
    tag = tag.strip().lstrip("v").lower()
    parts = re.findall(r'\d+', tag)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def is_newer(remote_tag: str, current_tag: str = CURRENT_VERSION) -> bool:
    """Return True if remote_tag represents a version newer than current_tag."""
    return _parse_version(remote_tag) > _parse_version(current_tag)


def fetch_latest_release(timeout: int = 8) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Fetch the latest release from GitHub.
    Returns (tag, release_name, error_message).
    tag and release_name are None on failure; error_message is None on success.
    """
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"User-Agent": f"SubForge/{CURRENT_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag  = data.get("tag_name", "").strip()
        name = data.get("name", tag).strip()
        if not tag:
            return None, None, "No release tag found in API response."
        return tag, name, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None, "No releases found. Check back after the next release is published."
        return None, None, f"GitHub returned HTTP {e.code}."
    except urllib.error.URLError as e:
        return None, None, f"Network error: {e.reason}"
    except json.JSONDecodeError:
        return None, None, "Could not parse response from GitHub."
    except Exception as e:
        return None, None, f"Unexpected error: {e}"


def fetch_release_details(timeout: int = 10) -> Tuple[Optional[dict], Optional[str]]:
    """
    Fetch full release details including assets and release body.
    Returns (release_dict, error_message).
    release_dict keys: tag_name, name, body, assets (list of {name, browser_download_url, size}).
    """
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"User-Agent": f"SubForge/{CURRENT_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name", "").strip()
        if not tag:
            return None, "No release tag found in API response."
        assets = [
            {
                "name":   a.get("name", ""),
                "url":    a.get("browser_download_url", ""),
                "size":   a.get("size", 0),
                # GitHub exposes the digest inline as "sha256:<hex>" — no
                # separate download needed.  Strip the "sha256:" prefix so
                # we always store a plain hex string (or "" if absent).
                "digest": a.get("digest", "").removeprefix("sha256:").lower(),
            }
            for a in data.get("assets", [])
        ]
        return {
            "tag_name": tag,
            "name":     data.get("name", tag).strip(),
            "body":     data.get("body", "").strip(),
            "assets":   assets,
        }, None
    except Exception as e:
        return None, str(e)


def find_installer_asset(assets: list) -> Tuple[Optional[dict], Optional[str]]:
    """
    Scan asset list for the Windows installer.
    Returns (installer_asset, expected_sha256_hex).
    The digest comes directly from the asset's `digest` field in the GitHub
    API response — no separate .sha256 file needed.
    expected_sha256_hex is "" if GitHub didn't supply one.
    """
    installer = next((a for a in assets if _INSTALLER_RE.search(a["name"])), None)
    if installer is None:
        return None, ""
    return installer, installer.get("digest", "")


def download_file(
    url: str,
    dest: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout: int = 60,
) -> Optional[str]:
    """
    Stream-download url to dest.
    Calls progress_cb(bytes_downloaded, total_bytes) periodically.
    Returns None on success, error string on failure.
    """
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": f"SubForge/{CURRENT_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 65536  # 64 KB
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)
        return None
    except Exception as e:
        # Clean up partial download
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        return str(e)


def verify_sha256(file_path: Path, expected_hex: str) -> Tuple[bool, str]:
    """
    Verify file_path against a known SHA-256 hex digest string.
    expected_hex comes directly from the GitHub asset metadata.
    Returns (ok, message).
    """
    if not expected_hex:
        return False, "No checksum available to verify against."
    try:
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        actual = sha.hexdigest().lower()
    except Exception as e:
        return False, f"Could not hash file: {e}"

    if actual == expected_hex.lower():
        return True, "SHA-256 verified."
    return False, f"SHA-256 mismatch.\nExpected: {expected_hex.lower()}\nActual:   {actual}"


def launch_installer_and_exit(installer_path: Path) -> Optional[str]:
    """
    Launch the Inno Setup installer silently and signal the app to exit.
    /SILENT    — shows progress, no confirmation pages
    /CLOSEAPPLICATIONS — asks running SubForge instances to close first
    Returns None on success, error string on failure.
    Only meaningful on Windows.
    """
    if sys.platform != "win32":
        return "In-app install is only supported on Windows."
    try:
        import subprocess
        subprocess.Popen(
            [str(installer_path), "/SILENT", "/CLOSEAPPLICATIONS"],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        return None
    except Exception as e:
        return str(e)

