"""
core/ocr.py — Image subtitle OCR pipeline.

Handles:
  - Tesseract path resolution (settings.json + system PATH)
  - PGS/VOBSUB frame extraction via ffmpeg (one PNG per subtitle event)
  - OCR via pytesseract
  - Assembly of OCR output into SubtitleTrack / ParsedSubtitle compatible
    structures so the existing detection engine runs unchanged

Public API mirrors extract_and_scan_track() in ffprobe.py:
  ocr_track(video_path, track, progress_cb=None)  — modifies track in-place

Tool availability:
  tesseract_available()
  get_tesseract_path() / set_tesseract_path()

ffmpeg / ffprobe path resolution lives in core/ffprobe.py.
mkvmerge path resolution lives in core/mkvtoolnix.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import sys as _sys

_SUBPROCESS_FLAGS: dict = (
    {"creationflags": 0x08000000} if _sys.platform == "win32" else {}
)

# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

from .paths import load_settings as _load_settings, save_settings as _save_settings


# ---------------------------------------------------------------------------
# Tesseract path resolution
# ---------------------------------------------------------------------------

def get_tesseract_path() -> Optional[str]:
    """
    Return path to tesseract executable, checking in order:
      1. Saved path in settings.json
      2. System PATH
      3. Default Windows install locations
    """
    settings = _load_settings()
    saved = settings.get("tesseract_path", "")
    if saved and Path(saved).is_file():
        return saved

    on_path = shutil.which("tesseract")
    if on_path:
        return on_path

    # Common Windows install locations
    for candidate in (
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ):
        if candidate.is_file():
            return str(candidate)

    return None


def set_tesseract_path(path: str) -> None:
    """Persist a custom tesseract path to settings.json."""
    s = dict(_load_settings())
    s["tesseract_path"] = path
    _save_settings(s)


def tesseract_available() -> bool:
    return get_tesseract_path() is not None


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------

# ffmpeg / ffprobe path resolution lives in ffprobe.py where those tools belong.
from .ffprobe import _find_ffmpeg, get_ffprobe_path


def _probe_video_resolution(video_path: Path) -> Tuple[int, int]:
    """Return (width, height) of the first video stream. Falls back to 1920x1080."""
    ffprobe = get_ffprobe_path()
    if not ffprobe:
        return 1920, 1080
    cmd = [
        ffprobe, "-v", "quiet",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-print_format", "json",
        str(video_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30, **_SUBPROCESS_FLAGS)
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
        stream = data.get("streams", [{}])[0]
        w = int(stream.get("width", 1920))
        h = int(stream.get("height", 1080))
        return (w, h) if w > 0 and h > 0 else (1920, 1080)
    except Exception:
        return 1920, 1080


def _probe_subtitle_resolution(video_path: Path, track_index: int) -> Tuple[int, int]:
    """
    Return the native canvas size of a VOBSUB subtitle stream.
    VOBSUB .idx files store a 'size' field (typically 720x480 NTSC or 720x576 PAL).
    ffprobe exposes this as coded_width/coded_height on the subtitle stream.
    Falls back to 720x480 if not available.
    """
    ffprobe = get_ffprobe_path()
    if not ffprobe:
        return 720, 480
    cmd = [
        ffprobe, "-v", "quiet",
        "-select_streams", f"s:{track_index}",
        "-show_entries", "stream=codec_tag_string,width,height,coded_width,coded_height",
        "-print_format", "json",
        str(video_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30, **_SUBPROCESS_FLAGS)
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
        stream = data.get("streams", [{}])[0]
        # Try coded dimensions first, then width/height
        w = int(stream.get("coded_width") or stream.get("width") or 0)
        h = int(stream.get("coded_height") or stream.get("height") or 0)
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 720, 480  # NTSC DVD default


def extract_subtitle_frames(
    video_path: Path,
    track_index: int,
    out_dir: Path,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Tuple[List[Path], str]:
    """
    VOBSUB fallback: overlay at 1fps onto lavfi black canvas.
    Only used when PGS direct parsing is not applicable.
    Returns (sorted PNG paths, error).
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return [], "ffmpeg not found — install FFmpeg and ensure it's on PATH"

    if progress_cb:
        progress_cb(f"Extracting subtitle frames from track {track_index}…")

    width, height = _probe_subtitle_resolution(video_path, track_index)
    frame_pattern = str(out_dir / "frame_%05d.png")

    filter_complex = (
        f"color=black:size={width}x{height}:rate=1[v];"
        f"[v][1:s:{track_index}]overlay=shortest=1"
    )

    cmd = [
        ffmpeg,
        "-v", "error",
        "-f", "lavfi", "-i", f"color=black:size={width}x{height}:rate=1",
        "-i", str(video_path),
        "-filter_complex", filter_complex,
        "-r", "1",
        "-vcodec", "png",
        "-f", "image2",
        frame_pattern,
        "-y",
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=600, **_SUBPROCESS_FLAGS
        )
    except subprocess.TimeoutExpired:
        return [], "ffmpeg frame extraction timed out (10 min limit)"
    except Exception as e:
        return [], f"ffmpeg error: {e}"

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()[:300]
        return [], f"ffmpeg error (rc={proc.returncode}): {stderr}"

    frames = sorted(out_dir.glob("frame_*.png"))
    if not frames:
        return [], "ffmpeg produced no frames — track may be empty or unsupported"

    return frames, ""


# ---------------------------------------------------------------------------
# PGS direct parser
# ---------------------------------------------------------------------------

_PGS_MAGIC = b"PG"
_SEG_PCS  = 0x16
_SEG_WDS  = 0x17
_SEG_PDS  = 0x14
_SEG_ODS  = 0x15
_SEG_END  = 0x80


def _extract_sup(
    video_path: Path,
    track_index: int,
    sup_path: Path,
) -> str:
    """Extract raw PGS stream to .sup file. Returns error string or ''."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return "ffmpeg not found"
    cmd = [
        ffmpeg, "-v", "error",
        "-i", str(video_path),
        "-map", f"0:s:{track_index}",
        "-c:s", "copy",
        str(sup_path), "-y",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, **_SUBPROCESS_FLAGS)
    except Exception as e:
        return f"ffmpeg error: {e}"
    if proc.returncode != 0:
        return proc.stderr.decode("utf-8", errors="replace").strip()[:200]
    if not sup_path.exists() or sup_path.stat().st_size == 0:
        return "ffmpeg produced empty .sup file"
    return ""


def _parse_sup(sup_path: Path) -> List[Tuple[int, int, object]]:
    """
    Parse a PGS .sup file and return list of (start_ms, end_ms, PIL.Image).

    PGS structure: sequence of segments, each with a 13-byte header:
      2 bytes  magic "PG"
      4 bytes  PTS (presentation timestamp, 90kHz clock)
      4 bytes  DTS
      1 byte   segment type
      2 bytes  segment data length

    A "display set" is a group of segments ending with END (0x80).
    Each display set that contains an ODS (Object Definition Segment)
    has a bitmap. The PDS gives the palette. We composite them to get
    the subtitle image.
    """
    try:
        from PIL import Image
        import struct
    except ImportError:
        return []

    data = sup_path.read_bytes()
    pos = 0
    length = len(data)

    display_sets: List[Tuple[int, int, object]] = []  # (start_ms, end_ms, Image)

    current_pts_ms: int = 0
    current_palette: dict = {}   # index -> (R, G, B, A)
    current_ods_data: bytes = b""
    current_ods_w: int = 0
    current_ods_h: int = 0
    current_has_image: bool = False
    # Track start/end from PCS
    epoch_start_ms: int = 0
    last_start_ms: int = 0
    pending_images: List[Tuple[int, object]] = []  # (start_ms, Image) awaiting end

    def pts_to_ms(pts: int) -> int:
        return pts // 90

    def build_image() -> Optional[object]:
        if not current_ods_data or current_ods_w == 0 or current_ods_h == 0:
            return None
        try:
            import numpy as np
            pixels = _decode_pgs_rle(current_ods_data, current_ods_w, current_ods_h)
            # Build a 256x4 lookup table (RGBA) from the current palette dict.
            # Unmapped indices default to (0,0,0,0) — transparent black.
            lut = np.zeros((256, 4), dtype=np.uint8)
            for pal_idx, (r, g, b, a) in current_palette.items():
                lut[pal_idx] = (r, g, b, a)
            # pixels is a bytearray of palette indices — treat as uint8 array
            # and do a single vectorized lookup, avoiding any Python-level loop.
            indices = np.frombuffer(pixels, dtype=np.uint8)
            rgba = lut[indices].reshape(current_ods_h, current_ods_w, 4)
            return Image.fromarray(rgba, mode="RGBA")
        except ImportError:
            # NumPy not available — fall back to pure-Python palette loop
            try:
                pixels = _decode_pgs_rle(current_ods_data, current_ods_w, current_ods_h)
                img = Image.new("RGBA", (current_ods_w, current_ods_h))
                img_data = [current_palette.get(idx, (0, 0, 0, 0)) for idx in pixels]
                img.putdata(img_data)
                return img
            except Exception:
                return None
        except Exception:
            return None

    while pos + 13 <= length:
        if data[pos:pos+2] != _PGS_MAGIC:
            pos += 1
            continue

        pts  = struct.unpack(">I", data[pos+2:pos+6])[0]
        seg_type = data[pos+10]
        seg_len  = struct.unpack(">H", data[pos+11:pos+13])[0]
        seg_data = data[pos+13:pos+13+seg_len]
        pos += 13 + seg_len

        pts_ms = pts_to_ms(pts)

        if seg_type == _SEG_PCS and len(seg_data) >= 11:
            # Presentation Composition Segment
            state = seg_data[10]
            if state in (0x80, 0x40):
                # Epoch start or acquisition point — new subtitle card starts
                current_has_image = False
                current_ods_data = b""
                current_palette = {}
            last_start_ms = pts_ms

        elif seg_type == _SEG_PDS and len(seg_data) >= 2:
            # Palette Definition Segment
            # seg_data[0] = palette_id, seg_data[1] = version
            entries = seg_data[2:]
            i = 0
            while i + 4 < len(entries):
                idx_e = entries[i]
                y   = entries[i+1]
                cb  = entries[i+2]
                cr  = entries[i+3]
                a   = entries[i+4]
                # YCbCr (BT.601 limited range) -> RGB
                # Y: 16=black, 235=white. Cb/Cr: 16-240, 128=neutral
                yn  = (y  - 16)  * 255 / 219
                cbn = (cb - 128) * 255 / 224
                crn = (cr - 128) * 255 / 224
                r = int(max(0, min(255, yn + 1.402   * crn)))
                g = int(max(0, min(255, yn - 0.344136 * cbn - 0.714136 * crn)))
                b = int(max(0, min(255, yn + 1.772   * cbn)))
                current_palette[idx_e] = (r, g, b, a)
                i += 5

        elif seg_type == _SEG_ODS and len(seg_data) >= 7:
            # Object Definition Segment
            seq_flag = seg_data[3]
            if seq_flag & 0x80:  # first in sequence
                current_ods_w = struct.unpack(">H", seg_data[7:9])[0] if len(seg_data) >= 9 else 0
                current_ods_h = struct.unpack(">H", seg_data[9:11])[0] if len(seg_data) >= 11 else 0
                current_ods_data = seg_data[11:] if len(seg_data) >= 11 else b""
            else:
                current_ods_data += seg_data[4:]
            current_has_image = True

        elif seg_type == _SEG_END:
            # End of display set
            if current_has_image:
                img = build_image()
                if img is not None:
                    pending_images.append((last_start_ms, img))
            # Assign end time to previous pending image if we now have a new start
            if len(pending_images) >= 2:
                start_ms, img = pending_images[-2]
                end_ms = pending_images[-1][0]
                if end_ms > start_ms:
                    display_sets.append((start_ms, end_ms, img))
            elif len(pending_images) == 1 and not current_has_image:
                # This END without image = clear event — use as end time
                start_ms, img = pending_images[0]
                end_ms = last_start_ms
                if end_ms > start_ms:
                    display_sets.append((start_ms, end_ms, img))
                pending_images.clear()

    # Flush any remaining pending image with synthetic 3-second duration
    for start_ms, img in pending_images:
        if not any(ds[0] == start_ms for ds in display_sets):
            display_sets.append((start_ms, start_ms + 3000, img))

    return display_sets


def _decode_pgs_rle(data: bytes, width: int, height: int) -> bytearray:
    """
    Decode PGS RLE compressed bitmap. Returns flat bytearray of palette indices.

    Using bytearray instead of a list of ints avoids Python object overhead on
    every element — for a 1920x1080 frame this cuts memory allocation by ~8x
    and removes the final list-to-slice copy. The bytearray is pre-allocated
    and zero-filled, so index-0 runs and end-of-line padding need only advance
    the write cursor rather than writing anything.

    PGS RLE encoding:
      non-zero byte        → single pixel of that palette index
      0x00 0x00            → end of line (pad remainder with 0)
      0x00 b2 (b2 & 0xC0 == 0x00) → (b2 & 0x3F) pixels of index 0
      0x00 b2 (b2 & 0xC0 == 0x40) → ((b2&0x3F)<<8 | next) pixels of index 0
      0x00 b2 (b2 & 0xC0 == 0x80) → (b2 & 0x3F) pixels of index (next byte)
      0x00 b2 (b2 & 0xC0 == 0xC0) → ((b2&0x3F)<<8 | next) pixels of index (next byte)
    """
    total = width * height
    pixels = bytearray(total)  # pre-allocated, zero-filled — padding is free
    out = 0  # write cursor
    i = 0
    n = len(data)

    while i < n and out < total:
        b = data[i]; i += 1
        if b != 0:
            # Single pixel
            pixels[out] = b
            out += 1
        else:
            if i >= n:
                break
            b2 = data[i]; i += 1
            if b2 == 0:
                # End of line — advance cursor to next row boundary; zeros already there
                col = out % width
                if col > 0:
                    out += width - col
            elif (b2 & 0xC0) == 0x00:
                # Short run of index 0 — just advance cursor
                count = min(b2 & 0x3F, total - out)
                out += count
            elif (b2 & 0xC0) == 0x40:
                # Long run of index 0
                if i >= n: break
                count = min(((b2 & 0x3F) << 8) | data[i], total - out); i += 1
                out += count
            elif (b2 & 0xC0) == 0x80:
                # Short run of color
                count = b2 & 0x3F
                if i >= n: break
                color = data[i]; i += 1
                end = min(out + count, total)
                pixels[out:end] = bytes([color]) * (end - out)
                out = end
            else:  # 0xC0
                # Long run of color
                if i + 1 >= n: break
                count = ((b2 & 0x3F) << 8) | data[i]; i += 1
                color = data[i]; i += 1
                end = min(out + count, total)
                pixels[out:end] = bytes([color]) * (end - out)
                out = end

    return pixels


def _is_pgs(codec: str) -> bool:
    return codec.lower() in ("hdmv_pgs_subtitle", "pgssub")


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def _iso_to_tesseract_lang(iso: str) -> str:
    """
    Map ISO 639-2 language codes to Tesseract lang strings.
    Falls back to 'eng' for unknown codes.
    Tesseract uses 3-letter codes but not always identical to ISO 639-2.
    """
    _MAP = {
        "eng": "eng", "en":  "eng",
        "spa": "spa", "es":  "spa",
        "fra": "fra", "fr":  "fra",
        "deu": "deu", "de":  "deu",
        "nld": "nld", "nl":  "nld",
        "por": "por", "pt":  "por",
        "ita": "ita", "it":  "ita",
        "rus": "rus", "ru":  "rus",
        "zho": "chi_sim", "zh": "chi_sim",
        "jpn": "jpn", "ja":  "jpn",
        "kor": "kor", "ko":  "kor",
        "ara": "ara", "ar":  "ara",
        "hin": "hin", "hi":  "hin",
        "pol": "pol", "pl":  "pol",
        "tur": "tur", "tr":  "tur",
        "swe": "swe", "sv":  "swe",
        "heb": "heb", "he":  "heb",
        "ind": "ind", "id":  "ind",
    }
    return _MAP.get(iso.lower(), "eng")


def _fix_music_notes(text: str) -> str:
    """
    Tesseract has no glyph for ♪ and substitutes visually similar characters.
    Known substitutions observed in practice:

      ♪  →  J, JS, Jf, JJ          (hook of note misread as J variants)
      ♪  →  f, ff, fF               (curved top misread as f variants)
      ♪  →  ~                       (tilde — common for opening note)
      ♪  →  ¢                       (cent sign — visually similar curve)
      ♪  →  £                       (pound sign — common closing note)
      ♪  →  #                       (hash — closing note artifact)
      ♪  →  Ss, IS                  (serif noise artifacts)
      ♪  →  Py                      (whole-line substitution — standalone note)
      ♪  →  I  (at line end)        (closing note reads as capital I)

    Strategy: tokens that are unambiguously ♪ substitutes in any context
    (~, ¢, £, #, Py) are always replaced when isolated. Tokens that could be
    real characters (J, f, I, etc.) are only replaced at line boundaries unless
    a real ♪ already exists in the block.
    """
    import re

    if not text:
        return text

    # Tokens that are unambiguously ♪ in any isolated position —
    # none of these appear as real words in subtitle dialogue.
    _ALWAYS_NOTE = ("Py", "JJ", "fF", "ff", "JS", "Jf", "IS", "Ss", "¢", "£", "~", "#")
    _ALWAYS_PAT = re.compile(
        r'(?<!\w)(' + "|".join(re.escape(t) for t in _ALWAYS_NOTE) + r')(?!\w)'
    )

    # Tokens that are ambiguous — only replace at line boundaries or when
    # a real ♪ already exists in the block (music context confirmed).
    # "I" at line-end is a closing note; "J" and "f" are common substitutions.
    _AMBIG_TOKENS = ("J", "f", "I")
    _AMBIG_PAT = re.compile(
        r'(?<!\w)(' + "|".join(re.escape(t) for t in _AMBIG_TOKENS) + r')(?!\w)'
    )
    _AMBIG_BOUNDARY_PAT = re.compile(
        r'^(' + "|".join(re.escape(t) for t in _AMBIG_TOKENS) + r')(?!\w)'
        r'|'
        r'(?<!\w)(' + "|".join(re.escape(t) for t in _AMBIG_TOKENS) + r')$'
    )

    has_real_note = "♪" in text

    def _replace_line(line: str) -> str:
        # Always-note tokens replaced unconditionally
        line = _ALWAYS_PAT.sub("♪", line)
        # Ambiguous tokens: freely if real ♪ present, boundary-only otherwise
        if has_real_note:
            line = _AMBIG_PAT.sub("♪", line)
        else:
            line = _AMBIG_BOUNDARY_PAT.sub("♪", line)
        return line

    # Re-check for real note after always-replacements (Py etc. may have added ♪)
    first_pass = "\n".join(_replace_line(l) for l in text.split("\n"))
    if not has_real_note and "♪" in first_pass:
        # A previously-unambiguous substitution introduced ♪ — run ambiguous
        # replacements again now that we have music context
        has_real_note = True
        return "\n".join(_replace_line(l) for l in first_pass.split("\n"))
    return first_pass


def _fix_ocr_chars(text: str) -> str:
    """
    Fix common single-character OCR misreads that are not music notes.

    | → I  (pipe misread as capital I in dialogue)
        Rule: replace | when surrounded by word characters or spaces on either
        side — i.e. when it appears mid-sentence or at the start of a word.
        Do NOT replace | when it is the only content on a line that looks like
        a bracketed annotation boundary (handled separately by SRT parsers).

    [ → I  (open bracket misread as capital I at word start)
        Rule: only when followed immediately by a lowercase letter or apostrophe,
        indicating it's a word start, not an annotation like [APPLAUSE].

    / → I  (slash misread as capital I — common in "I'm", "I'ma")
        Rule: only when at the very start of a word followed by a lowercase
        letter or apostrophe (e.g. /ma → I'ma, /t → It).
    """
    import re

    if not text:
        return text

    lines = []
    for line in text.split("\n"):
        # | → I: pipe surrounded by word chars or at start of word before letters
        # Covers: "| know", "| said", "May | have", "| dont"
        # Avoids: "|" alone on a line (rare annotation artifact — leave for parser)
        line = re.sub(r'(?<=\s)\|(?=\w)', "I", line)   # space-pipe-word → space-I-word
        line = re.sub(r'(?<=\w)\|(?=\s)', "I", line)   # word-pipe-space → word-I-space  (rare)
        line = re.sub(r'^\|(?=\w)', "I", line)          # pipe at line start before word
        line = re.sub(r'(?<=\s)\|$', "I", line)         # pipe at line end after space
        line = re.sub(r'^\|$', "I", line)               # lone pipe on a line

        # [ → I: bracket at word start before lowercase or apostrophe
        # Covers: ['m-a → I'm-a
        # Avoids: [APPLAUSE], [MUSIC PLAYING] — uppercase after bracket = annotation
        line = re.sub(r'\[(?=[a-z\'])', "I", line)

        # / → I: slash at word start before lowercase or apostrophe
        # Covers: /ma → I'ma, /t → It
        line = re.sub(r'(?<!\w)/(?=[a-z\'])', "I", line)

        lines.append(line)

    return "\n".join(lines)


def _preprocess_subtitle_image(img: object) -> object:
    """
    Preprocess a subtitle bitmap for Tesseract.

    Handles two common PGS/VOBSUB styles:
      1. Colored text (white/yellow) on transparent background
         → composite onto black, invert → black text on white
      2. Black text with alpha-only anti-aliasing (no color)
         → composite onto white → black text on white (ready for Tesseract)
    """
    from PIL import Image, ImageOps
    import random

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # Determine if text is defined by alpha only (all pixels near-black RGB).
    # Sample up to 500 random pixel positions rather than materializing the
    # entire pixel array — for a 1920x1080 frame that avoids allocating ~2M
    # tuples in Python just for a brightness heuristic.
    w_img, h_img = img.size
    total_pixels = w_img * h_img
    r_ch, g_ch, b_ch, a_ch = img.split()
    r_data = r_ch.tobytes()
    g_data = g_ch.tobytes()
    b_data = b_ch.tobytes()
    a_data = a_ch.tobytes()

    sample_size = min(500, total_pixels)
    indices = random.sample(range(total_pixels), sample_size) if total_pixels > sample_size else range(total_pixels)

    brightness_sum = 0
    visible_count = 0
    for idx in indices:
        a = a_data[idx]
        if a > 32:
            brightness_sum += r_data[idx] + g_data[idx] + b_data[idx]
            visible_count += 1

    if visible_count:
        avg_brightness = brightness_sum / (visible_count * 3)
        alpha_only = avg_brightness < 30  # all visible pixels are near-black
    else:
        alpha_only = False

    if alpha_only:
        # Text is black with alpha anti-aliasing — composite onto white
        # Result: black text on white, ready for Tesseract directly
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        gray = bg.convert("L")
    else:
        # Colored text on transparent — composite onto black, then invert
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[3])
        gray = bg.convert("L")
        # Invert: colored text on black → black text on white
        gray = ImageOps.invert(gray)

    # Crop to non-white bounding box (remove empty margins)
    # For alpha-only: non-white = text. For colored: non-white after invert = text.
    binary = gray.point(lambda x: 0 if x < 240 else 255)
    bbox = binary.getbbox()
    if bbox:
        pad = 4
        w, h = gray.size
        bbox = (max(0, bbox[0]-pad), max(0, bbox[1]-pad),
                min(w, bbox[2]+pad), min(h, bbox[3]+pad))
        gray = gray.crop(bbox)

    # Upscale 3x
    w, h = gray.size
    if w > 0 and h > 0:
        gray = gray.resize((w * 3, h * 3), Image.LANCZOS)

    return gray


def ocr_frames(
    frames: List[Path],
    lang: str = "und",
    progress_cb: Optional[Callable[[str], None]] = None,
    frame_cb: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """
    Run Tesseract OCR on a list of PNG frames.

    progress_cb(msg) — text status updates (every 10 frames)
    frame_cb(done, total) — called after every frame for percentage progress

    Returns a list of text strings, one per frame.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise ImportError(
            "pytesseract and Pillow are required for image subtitle scanning. "
            f"Install with: pip install pytesseract pillow\n({e})"
        ) from e

    tess_path = get_tesseract_path()
    if not tess_path:
        raise RuntimeError(
            "Tesseract executable not found. Install Tesseract and set its "
            "path in Settings > Paths."
        )

    pytesseract.pytesseract.tesseract_cmd = tess_path
    tess_lang = _iso_to_tesseract_lang(lang)
    total = len(frames)
    tess_config = "--psm 6 --oem 1"
    _tess_garbage = {"[PIL]", "[PIL] ", "[pil]", "", ".", ",", "-", "--"}

    results_map: dict = {}  # index -> text
    done_count = 0
    done_lock = threading.Lock()

    def _ocr_one_frame(i_path):
        i, frame_path = i_path
        try:
            img = Image.open(frame_path)
            img = _preprocess_subtitle_image(img)
            text = pytesseract.image_to_string(img, lang=tess_lang, config=tess_config).strip()
            text = _fix_music_notes(text)
            text = _fix_ocr_chars(text)
            return i, text if text not in _tess_garbage else ""
        except Exception:
            return i, ""

    n_workers = min(4, total)
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(_ocr_one_frame, (i, fp)): i
            for i, fp in enumerate(frames)
        }
        for fut in as_completed(futures):
            i, text = fut.result()
            results_map[i] = text
            with done_lock:
                done_count += 1
                count_snap = done_count
            if frame_cb:
                frame_cb(count_snap, total)
            if progress_cb and count_snap % 10 == 0:
                progress_cb(f"OCR: {count_snap} of {total} frames done…")

    return [results_map.get(i, "") for i in range(total)]


# ---------------------------------------------------------------------------
# Timestamp extraction
# ---------------------------------------------------------------------------

def _extract_timestamps(
    video_path: Path,
    track_index: int,
) -> List[Tuple[int, int]]:
    """
    Use ffprobe to read the PTS (presentation timestamp) of each packet in
    the subtitle stream. Returns a list of (start_ms, end_ms) tuples in
    stream order.

    If ffprobe fails or returns no packets, returns an empty list — the caller
    falls back to generating synthetic evenly-spaced timestamps.
    """
    ffprobe = get_ffprobe_path()
    if not ffprobe:
        return []

    cmd = [
        ffprobe,
        "-v", "quiet",
        "-select_streams", f"s:{track_index}",
        "-show_packets",
        "-print_format", "json",
        str(video_path),
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=60, **_SUBPROCESS_FLAGS
        )
    except Exception:
        return []

    if proc.returncode != 0:
        return []

    try:
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []

    timestamps: List[Tuple[int, int]] = []
    for pkt in data.get("packets", []):
        try:
            # pts_time is in seconds as a float string
            start_s = float(pkt.get("pts_time", 0))
            dur_s   = float(pkt.get("duration_time", 2.0))
            start_ms = int(start_s * 1000)
            end_ms   = int((start_s + dur_s) * 1000)
            timestamps.append((start_ms, end_ms))
        except (TypeError, ValueError):
            continue

    return timestamps


# ---------------------------------------------------------------------------
# Assembly into ParsedSubtitle-compatible structure
# ---------------------------------------------------------------------------

def _ms_to_srt_timestamp(ms: int) -> str:
    """Convert milliseconds to SRT timestamp string HH:MM:SS,mmm."""
    h   =  ms // 3_600_000
    ms -=  h  * 3_600_000
    m   =  ms //    60_000
    ms -=  m  *    60_000
    s   =  ms //     1_000
    ms -=  s  *     1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_subtitle(
    texts: List[str],
    timestamps: List[Tuple[int, int]],
    video_path: Path,
    track_index: int,
    lang: str,
) -> object:
    """
    Assemble OCR text + timestamps into a ParsedSubtitle so the existing
    analyze() engine can run on it without modification.

    Blank frames (empty OCR output) are skipped — they represent subtitle
    cards that contained no readable text (e.g. pure graphics, chapter cards).

    Returns a ParsedSubtitle instance or None if no usable blocks.
    """
    from .subtitle import load_subtitle
    import tempfile, os

    # Build a synthetic SRT in memory, write to a temp file, parse it.
    # This reuses all existing SRT parsing logic including encoding detection.
    lines: List[str] = []
    idx = 1
    n_frames = min(len(texts), len(timestamps))

    for i in range(n_frames):
        text = texts[i].strip()
        if not text:
            continue
        start_ms, end_ms = timestamps[i]
        # Clamp: end must be after start
        if end_ms <= start_ms:
            end_ms = start_ms + 2000

        lines.append(str(idx))
        lines.append(
            f"{_ms_to_srt_timestamp(start_ms)} --> {_ms_to_srt_timestamp(end_ms)}"
        )
        lines.append(text)
        lines.append("")
        idx += 1

    if not lines:
        return None

    srt_text = "\n".join(lines)

    # Write to a temp file named so the language is visible to the parser
    ext = ".srt"
    lang_tag = f".{lang}" if lang and lang != "und" else ""
    tmp_name = f"ocr_track{track_index}{lang_tag}{ext}"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir) / tmp_name
        tmp_path.write_text(srt_text, encoding="utf-8")
        try:
            sub = load_subtitle(tmp_path)
        except Exception:
            return None

    # Tag the subtitle so downstream code knows it came from OCR
    sub._ocr_source = True
    return sub


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def ocr_track(
    video_path: Path,
    track,
    progress_cb: Optional[Callable[[str], None]] = None,
    frame_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """
    Full OCR pipeline for one image-based subtitle track.
    Populates track fields in-place. Never raises.

    progress_cb(msg)       — text status updates
    frame_cb(done, total)  — per-frame progress for percentage bar
    """
    from .cleaner import analyze

    if not tesseract_available():
        track.scan_error = (
            "Tesseract not found — install it and set its path in Settings > Paths"
        )
        return

    if not track.is_image:
        track.scan_error = "ocr_track called on a non-image track"
        return

    try:
        _ocr_track_inner(video_path, track, progress_cb, frame_cb)
    except ImportError as e:
        track.scan_error = f"Missing dependency: {e}"
    except Exception as e:
        track.scan_error = f"OCR error: {e}"


def _deduplicate_frames(frames: List[Path]) -> List[Path]:
    """
    Remove consecutive duplicate PNG frames using file size as a fast
    pre-filter, then pixel hash for confirmation. Returns one frame per
    unique subtitle card — typically reduces frame count by 20-50x.
    """
    if not frames:
        return frames
    try:
        from PIL import Image
        import hashlib
    except ImportError:
        return frames  # can't dedup without Pillow — proceed with all frames

    unique: List[Path] = []
    last_hash: Optional[str] = None
    last_size: int = -1

    for path in frames:
        size = path.stat().st_size
        if size == last_size:
            # Same file size — do full pixel hash
            try:
                img_bytes = path.read_bytes()
                h = hashlib.md5(img_bytes).hexdigest()
                if h == last_hash:
                    continue
                last_hash = h
            except Exception:
                pass
        else:
            try:
                img_bytes = path.read_bytes()
                last_hash = hashlib.md5(img_bytes).hexdigest()
            except Exception:
                last_hash = None
        last_size = size
        unique.append(path)

    return unique


def _ocr_track_inner(
    video_path: Path,
    track,
    progress_cb: Optional[Callable[[str], None]] = None,
    frame_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    from .cleaner import analyze

    if _is_pgs(track.codec):
        _ocr_track_pgs(video_path, track, progress_cb, frame_cb)
    else:
        _ocr_track_vobsub(video_path, track, progress_cb, frame_cb)


def _ocr_track_pgs(
    video_path: Path,
    track,
    progress_cb: Optional[Callable[[str], None]] = None,
    frame_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """PGS path: extract raw .sup, parse bitmaps directly, OCR in memory."""
    from .cleaner import analyze

    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        track.scan_error = f"Missing dependency: {e}"
        return

    tess_path = get_tesseract_path()
    if not tess_path:
        track.scan_error = "Tesseract not found"
        return
    pytesseract.pytesseract.tesseract_cmd = tess_path
    tess_lang = _iso_to_tesseract_lang(track.language)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        sup_path = Path(tmpdir) / "track.sup"

        if progress_cb:
            progress_cb(f"Extracting PGS stream from track {track.track_num}…")

        err = _extract_sup(video_path, track.track_num, sup_path)
        if err:
            track.scan_error = f"PGS extraction failed: {err}"
            return

        if progress_cb:
            from gui.strings import STRINGS as _S
            progress_cb(_S["img_status_parsing"])

        display_sets = _parse_sup(sup_path)

        if not display_sets:
            track.scan_error = "No subtitle frames found in PGS stream"
            return

        if progress_cb:
            progress_cb(f"Running OCR on {len(display_sets)} subtitle frames…")

        total = len(display_sets)
        tess_config = "--psm 6 --oem 1"
        _tess_garbage = {"[PIL]", "[PIL] ", "[pil]", "", ".", ",", "-", "--"}

        # OCR each frame in a thread pool — Tesseract releases the GIL during
        # its C-level processing, so multiple frames can be OCR'd concurrently.
        # Results dict keyed by original index so we can reassemble in order.
        done_count = 0
        done_lock = threading.Lock()
        results: dict = {}  # i -> text

        def _ocr_one(i_start_end_img):
            i, start_ms, end_ms, img = i_start_end_img
            try:
                processed = _preprocess_subtitle_image(img)
                text = pytesseract.image_to_string(
                    processed, lang=tess_lang, config=tess_config
                ).strip()
                text = _fix_music_notes(text)
                text = _fix_ocr_chars(text)
            except Exception:
                text = ""
            return i, start_ms, end_ms, text

        n_workers = min(4, total)
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(_ocr_one, (i, start_ms, end_ms, img)): i
                for i, (start_ms, end_ms, img) in enumerate(display_sets)
            }
            for fut in as_completed(futures):
                i, start_ms, end_ms, text = fut.result()
                results[i] = (start_ms, end_ms, text)
                with done_lock:
                    done_count += 1
                    count_snap = done_count
                if frame_cb:
                    frame_cb(count_snap, total)
                if progress_cb and count_snap % 20 == 0:
                    progress_cb(f"OCR: {count_snap} of {total} frames done…")

        # Reassemble in original order
        srt_lines: List[str] = []
        idx = 1
        for i in range(total):
            start_ms, end_ms, text = results.get(i, (0, 0, ""))
            if text and text not in _tess_garbage:
                srt_lines.append(str(idx))
                srt_lines.append(
                    f"{_ms_to_srt_timestamp(start_ms)} --> {_ms_to_srt_timestamp(end_ms)}"
                )
                srt_lines.append(text)
                srt_lines.append("")
                idx += 1

    _finish_ocr(track, srt_lines, progress_cb)


def _ocr_track_vobsub(
    video_path: Path,
    track,
    progress_cb: Optional[Callable[[str], None]] = None,
    frame_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """VOBSUB path: ffmpeg 1fps overlay, dedup, then OCR."""
    from .cleaner import analyze

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir)

        frames, err = extract_subtitle_frames(
            video_path, track.track_num, tmp_path, progress_cb
        )
        if err:
            track.scan_error = err
            return
        if not frames:
            track.scan_error = "No subtitle frames extracted"
            return

        if progress_cb:
            progress_cb(f"Deduplicating {len(frames)} frames…")
        frames = _deduplicate_frames(frames)

        timestamps = _extract_timestamps(video_path, track.track_num)
        if len(timestamps) < len(frames):
            synthetic_start = len(timestamps) * 2000
            for j in range(len(timestamps), len(frames)):
                start = synthetic_start + j * 2000
                timestamps.append((start, start + 2000))

        texts = ocr_frames(frames, lang=track.language, progress_cb=progress_cb, frame_cb=frame_cb)

        if progress_cb:
            progress_cb("Assembling OCR results…")

        n = min(len(texts), len(timestamps))
        srt_lines: List[str] = []
        idx = 1
        for i in range(n):
            text = texts[i].strip()
            if not text:
                continue
            start_ms, end_ms = timestamps[i]
            if end_ms <= start_ms:
                end_ms = start_ms + 2000
            srt_lines.append(str(idx))
            srt_lines.append(f"{_ms_to_srt_timestamp(start_ms)} --> {_ms_to_srt_timestamp(end_ms)}")
            srt_lines.append(text)
            srt_lines.append("")
            idx += 1

    _finish_ocr(track, srt_lines, progress_cb)


def _finish_ocr(track, srt_lines: List[str], progress_cb) -> None:
    """Common final step: parse SRT lines into subtitle, analyze, populate track."""
    from .cleaner import analyze
    from .subtitle import load_subtitle

    if not srt_lines:
        track.total_blocks = 0
        track.ad_count = 0
        track.warning_count = 0
        track.scan_error = "No readable text found in image track"
        return

    srt_text = "\n".join(srt_lines)
    lang = track.language if track.language and track.language != "und" else ""
    lang_tag = f".{lang}" if lang else ""
    tmp_name = f"ocr_track{track.track_num}{lang_tag}.srt"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir) / tmp_name
        tmp_path.write_text(srt_text, encoding="utf-8")
        try:
            sub = load_subtitle(tmp_path)
        except Exception as e:
            track.scan_error = f"SRT parse error: {e}"
            return

    sub._ocr_source = True

    if progress_cb:
        progress_cb("Scanning for ads…")
    analyze(sub)

    track.total_blocks  = len(sub.blocks)
    track.ad_count      = sum(1 for b in sub.blocks if b.is_ad)
    track.warning_count = sum(1 for b in sub.blocks if b.is_warning)
    track.subtitle      = sub

    for b in sub.blocks:
        if b.is_ad or b.is_warning:
            sample = f"[{b.start}] {b.text[:70]}"
            if b.matched_patterns:
                sample += f"  ({', '.join(b.matched_patterns)})"
            track.flagged_samples.append(sample)
            if len(track.flagged_samples) >= 5:
                break
