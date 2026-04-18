"""
core/converter.py — Subtitle format conversion backend.

Converts between the seven supported text-based subtitle formats using pysubs2
as the conversion engine.  No GUI dependencies.

Supported formats
-----------------
  SRT      (.srt)  — SubRip. Full fidelity.
  ASS      (.ass)  — Advanced SubStation Alpha. Full fidelity.
  SSA      (.ssa)  — SubStation Alpha. Full fidelity.
  VTT      (.vtt)  — WebVTT. Timing preserved; style tags stripped.
  TTML     (.ttml) — W3C Timed Text. Basic parser; complex styling may be lossy.
  SAMI     (.sami) — Legacy HTML/CSS format. Rudimentary parser; may be lossy.
  MicroDVD (.sub)  — Frame-based format. pysubs2 auto-detects framerate from
                     the first subtitle line if present; falls back to 23.976fps.
                     Always show a framerate advisory when this format is involved.

Lossy paths
-----------
  ASS/SSA → anything:  styling (colours, fonts, positioning) is not preserved.
  TTML as input:       advanced TTML styling not decoded.
  SAMI as input:       complex SAMI markup not decoded.
  MicroDVD (any role): framerate-dependent — timing advisory always shown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Format registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FormatInfo:
    identifier: str          # pysubs2 format identifier
    display_name: str        # shown in UI dropdowns
    extensions: tuple        # canonical write extension is extensions[0]

    @property
    def ext(self) -> str:
        return self.extensions[0]


# Ordered list — determines dropdown order in the UI.
FORMATS: List[FormatInfo] = [
    FormatInfo("srt",      "SubRip (.srt)",                   (".srt",)),
    FormatInfo("ass",      "Advanced SubStation Alpha (.ass)", (".ass",)),
    FormatInfo("ssa",      "SubStation Alpha (.ssa)",          (".ssa",)),
    FormatInfo("vtt",      "WebVTT (.vtt)",                    (".vtt",)),
    FormatInfo("ttml",     "TTML (.ttml)",                     (".ttml",)),
    FormatInfo("sami",     "SAMI (.sami)",                     (".sami", ".smi")),
    FormatInfo("microdvd", "MicroDVD (.sub)",                  (".sub",)),
]

# All extensions that can be read as input
INPUT_EXTENSIONS: set = {
    ext for fmt in FORMATS for ext in fmt.extensions
}

# Map identifier → FormatInfo for quick lookup
_BY_ID  = {f.identifier: f for f in FORMATS}
# Map extension → FormatInfo
_BY_EXT = {ext: fmt for fmt in FORMATS for ext in fmt.extensions}


def format_by_id(identifier: str) -> Optional[FormatInfo]:
    return _BY_ID.get(identifier)

def format_by_ext(ext: str) -> Optional[FormatInfo]:
    return _BY_EXT.get(ext.lower())


# ---------------------------------------------------------------------------
# Lossy-path detection
# ---------------------------------------------------------------------------

# (source_id, target_id) pairs that are known lossy.
_LOSSY_PAIRS = {
    ("ass",  "srt"),  ("ass",  "ssa"),  ("ass",  "vtt"),
    ("ass",  "ttml"), ("ass",  "sami"), ("ass",  "microdvd"),
    ("ssa",  "srt"),  ("ssa",  "ass"),  ("ssa",  "vtt"),
    ("ssa",  "ttml"), ("ssa",  "sami"), ("ssa",  "microdvd"),
}
# Formats that are themselves advisory on input regardless of target.
# MicroDVD is always advisory (framerate-dependent timing).
_LOSSY_INPUT = {"ttml", "sami", "microdvd"}


def is_lossy(src_id: str, tgt_id: str) -> bool:
    """Return True if this conversion path warrants a warning."""
    return (src_id, tgt_id) in _LOSSY_PAIRS or src_id in _LOSSY_INPUT or tgt_id == "microdvd"


def lossy_reason(src_id: str, tgt_id: str) -> str:
    """Return the STRINGS key for the appropriate warning, or '' if none."""
    if src_id in ("ass", "ssa") and tgt_id not in ("ass", "ssa"):
        return "cv_warn_ass_styling"
    if src_id == "ttml":
        return "cv_warn_ttml_input"
    if src_id == "sami":
        return "cv_warn_sami_input"
    # MicroDVD advisory shown whenever .sub is source or target
    if src_id == "microdvd" or tgt_id == "microdvd":
        return "cv_warn_microdvd"
    return ""


# ---------------------------------------------------------------------------
# Conversion result
# ---------------------------------------------------------------------------

@dataclass
class ConvertResult:
    success:    bool
    output:     Optional[Path] = None
    error:      str            = ""
    was_lossy:  bool           = False


# ---------------------------------------------------------------------------
# Single-file conversion
# ---------------------------------------------------------------------------

def convert_file(src: Path, target_id: str) -> ConvertResult:
    """
    Convert *src* to the format identified by *target_id*.

    The output file is written next to the source using the same stem and the
    canonical extension for *target_id*.  If the source already has that
    extension, a ``_converted`` suffix is appended to the stem to avoid
    clobbering the original.

    Returns a ConvertResult with the output path on success.
    """
    import pysubs2

    tgt_fmt = format_by_id(target_id)
    if tgt_fmt is None:
        return ConvertResult(success=False, error=f"Unknown target format: {target_id!r}")

    src_fmt = format_by_ext(src.suffix)
    src_id  = src_fmt.identifier if src_fmt else "unknown"

    lossy = is_lossy(src_id, target_id)

    # Determine output path
    out_stem = src.stem
    if src.suffix.lower() == tgt_fmt.ext:
        out_stem = src.stem + "_converted"
    out_path = src.parent / (out_stem + tgt_fmt.ext)

    # Avoid silent clobber — bump with counter if it already exists
    if out_path.exists():
        counter = 2
        while out_path.exists():
            out_path = src.parent / f"{out_stem}.{counter}{tgt_fmt.ext}"
            counter += 1

    try:
        subs = pysubs2.load(str(src))
        subs.save(str(out_path), format_=target_id)
    except Exception as exc:
        return ConvertResult(success=False, error=str(exc))

    return ConvertResult(success=True, output=out_path, was_lossy=lossy)


# ---------------------------------------------------------------------------
# Batch conversion
# ---------------------------------------------------------------------------

@dataclass
class BatchConvertResult:
    converted: int                    = 0
    skipped:   int                    = 0
    failed:    int                    = 0
    errors:    List[tuple]            = field(default_factory=list)
    # errors: list of (path, error_message)


def convert_folder(folder: Path, target_id: str,
                   recursive: bool = False) -> BatchConvertResult:
    """
    Convert all supported subtitle files in *folder* to *target_id*.

    Files whose extension already matches the target are skipped.
    Errors are collected per-file; a single failure does not abort the batch.
    """
    tgt_fmt = format_by_id(target_id)
    if tgt_fmt is None:
        result = BatchConvertResult()
        result.errors.append((folder, f"Unknown target format: {target_id!r}"))
        result.failed = 1
        return result

    glob = "**/*" if recursive else "*"
    candidates = [
        p for p in folder.glob(glob)
        if p.is_file() and p.suffix.lower() in INPUT_EXTENSIONS
    ]

    result = BatchConvertResult()
    for src in candidates:
        if src.suffix.lower() == tgt_fmt.ext:
            result.skipped += 1
            continue
        r = convert_file(src, target_id)
        if r.success:
            result.converted += 1
        else:
            result.failed += 1
            result.errors.append((src, r.error))

    return result
