"""
Shared colour palette — imported by all GUI panels.

Four themes are supported:
  dark         — original dark industrial palette (default)
  light        — light palette
  high_contrast — high-contrast monochrome palette
  amoled       — true black AMOLED palette

Call apply_theme(name) to switch at runtime. All module-level names (BG, FG,
etc.) are updated in place so existing imports keep working after the switch,
provided callers reference the module-level names rather than caching them
in local variables at import time.
"""
from __future__ import annotations
from core.paths import load_settings as _load_settings, save_settings as _save_settings

# ---------------------------------------------------------------------------
# Palette definitions
# ---------------------------------------------------------------------------

_DARK = {
    "BG":     "#0f1117",
    "BG2":    "#161b26",
    "BG3":    "#1e2535",
    "BORDER": "#2a3347",
    "FG":     "#cdd6f4",
    "FG2":    "#6c7a96",
    "ACCENT": "#4e9eff",
    "RED":    "#f38ba8",
    "ORANGE": "#fab387",
    "GREEN":  "#a6e3a1",
    "YELLOW": "#f9e2af",
}

_LIGHT = {
    "BG":     "#f5f7fa",
    "BG2":    "#ffffff",
    "BG3":    "#e8ecf2",
    "BORDER": "#c5cdd8",
    "FG":     "#1e2535",
    "FG2":    "#5a6478",
    "ACCENT": "#1a6fd4",
    "RED":    "#c0392b",
    "ORANGE": "#d35400",
    "GREEN":  "#27ae60",
    "YELLOW": "#c07a00",
}

_HIGH_CONTRAST = {
    "BG":     "#000000",
    "BG2":    "#0a0a0a",
    "BG3":    "#1a1a1a",
    "BORDER": "#ffffff",
    "FG":     "#ffffff",
    "FG2":    "#cccccc",
    "ACCENT": "#ffff00",
    "RED":    "#ff4444",
    "ORANGE": "#ff8800",
    "GREEN":  "#00ff00",
    "YELLOW": "#ffff00",
}

_AMOLED = {
    "BG":     "#000000",
    "BG2":    "#0a0a0a",
    "BG3":    "#111111",
    "BORDER": "#1f1f1f",
    "FG":     "#e0e0e0",
    "FG2":    "#666666",
    "ACCENT": "#4e9eff",
    "RED":    "#f38ba8",
    "ORANGE": "#fab387",
    "GREEN":  "#a6e3a1",
    "YELLOW": "#f9e2af",
}

_PALETTES = {
    "dark":          _DARK,
    "light":         _LIGHT,
    "high_contrast": _HIGH_CONTRAST,
    "amoled":        _AMOLED,
}

# ---------------------------------------------------------------------------
# Module-level colour names — populated by _apply(palette)
# ---------------------------------------------------------------------------

BG     = _DARK["BG"]
BG2    = _DARK["BG2"]
BG3    = _DARK["BG3"]
BORDER = _DARK["BORDER"]
FG     = _DARK["FG"]
FG2    = _DARK["FG2"]
ACCENT = _DARK["ACCENT"]
RED    = _DARK["RED"]
ORANGE = _DARK["ORANGE"]
GREEN  = _DARK["GREEN"]
YELLOW = _DARK["YELLOW"]

_current_theme: str = "dark"


def _apply(palette: dict) -> None:
    """Update all module-level colour names from *palette*."""
    import sys
    mod = sys.modules[__name__]
    for name, value in palette.items():
        setattr(mod, name, value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_theme() -> str:
    """Return the name of the currently active theme."""
    return _current_theme


def apply_theme(name: str) -> None:
    """
    Switch the active theme to *name* ('dark', 'light', or 'high_contrast').
    Updates all module-level colour names in place.
    Does NOT rebuild or reapply the Qt stylesheet — the caller must do that.
    """
    global _current_theme
    palette = _PALETTES.get(name)
    if palette is None:
        return
    _apply(palette)
    _current_theme = name


def load_theme() -> str:
    """Load saved theme name from settings.json. Returns 'dark' if not set."""
    return _load_settings().get("theme", "dark")


def save_theme(name: str) -> None:
    """Persist theme name to settings.json."""
    s = dict(_load_settings())
    s["theme"] = name
    _save_settings(s)


# Apply the saved theme immediately at import time so the first stylesheet
# build picks up the right colours.
apply_theme(load_theme())
