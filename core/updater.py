"""
Update checker for SubScrubber.
Compares current version against latest GitHub release tag using semantic versioning.
Entirely opt-in — only runs when the user clicks "Check for Updates".
Makes one GET request to the GitHub releases API and nothing else.
"""
from __future__ import annotations

import re
import urllib.request
import json
from typing import Optional, Tuple

CURRENT_VERSION = "v0.6.0"
GITHUB_API_URL  = "https://api.github.com/repos/babcockdavidr/SubScrubber-GUI/releases/latest"
RELEASES_URL    = "https://github.com/babcockdavidr/SubScrubber-GUI/releases"


def _parse_version(tag: str) -> Tuple:
    """
    Parse a version tag into a comparable tuple.
    Handles both stable (v1.2.3) and beta (v0.4.0) tags.
    Strips leading 'v' before parsing.
    Returns a tuple of ints for comparison, e.g. (1, 2, 3) or (0, 4, 0).
    """
    tag = tag.strip().lstrip("v").lower()
    # Extract all numeric groups
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
            headers={"User-Agent": f"SubScrubber/{CURRENT_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag  = data.get("tag_name", "").strip()
        name = data.get("name", tag).strip()
        if not tag:
            return None, None, "No release tag found in API response."
        return tag, name, None
    except urllib.error.URLError as e:
        return None, None, f"Network error: {e.reason}"
    except json.JSONDecodeError:
        return None, None, "Could not parse response from GitHub."
    except Exception as e:
        return None, None, f"Unexpected error: {e}"
