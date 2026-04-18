"""
ffprobe / ffmpeg integration.
Detects embedded subtitle tracks inside video containers (MKV, MP4, AVI, etc.),
extracts text-based tracks to temp files, runs ad detection on them, and
reports findings — without modifying the video file.

Image-based formats (PGS, VOBSUB, DVB) are detected but skipped with a note.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .subtitle import load_subtitle, SUPPORTED_EXTENSIONS
from .cleaner import analyze

# On Windows, suppress the console window that pops up for each subprocess call.
# CREATE_NO_WINDOW = 0x08000000 — only defined on Windows, so guard with sys.
import sys as _sys
_SUBPROCESS_FLAGS: dict = (
    {"creationflags": 0x08000000} if _sys.platform == "win32" else {}
)


# ---------------------------------------------------------------------------
# Settings persistence  (ffmpeg / ffprobe paths)
# ---------------------------------------------------------------------------

from .paths import load_settings as _load_settings, save_settings as _save_settings


_ffmpeg_path_cache:  Optional[str] = None
_ffprobe_path_cache: Optional[str] = None


def get_ffmpeg_path() -> Optional[str]:
    global _ffmpeg_path_cache
    if _ffmpeg_path_cache is not None:
        return _ffmpeg_path_cache
    saved = _load_settings().get("ffmpeg_path", "")
    if saved and Path(saved).is_file():
        _ffmpeg_path_cache = saved
        return _ffmpeg_path_cache
    _ffmpeg_path_cache = shutil.which("ffmpeg")
    return _ffmpeg_path_cache


def set_ffmpeg_path(path: str) -> None:
    global _ffmpeg_path_cache
    s = dict(_load_settings())
    s["ffmpeg_path"] = path
    _save_settings(s)
    _ffmpeg_path_cache = None


def get_ffprobe_path() -> Optional[str]:
    global _ffprobe_path_cache
    if _ffprobe_path_cache is not None:
        return _ffprobe_path_cache
    saved = _load_settings().get("ffprobe_path", "")
    if saved and Path(saved).is_file():
        _ffprobe_path_cache = saved
        return _ffprobe_path_cache
    _ffprobe_path_cache = shutil.which("ffprobe")
    return _ffprobe_path_cache


def set_ffprobe_path(path: str) -> None:
    global _ffprobe_path_cache
    s = dict(_load_settings())
    s["ffprobe_path"] = path
    _save_settings(s)
    _ffprobe_path_cache = None


def _find_ffprobe() -> Optional[str]:
    return get_ffprobe_path()


def _find_ffmpeg() -> Optional[str]:
    return get_ffmpeg_path()


def ffprobe_available() -> bool:
    return get_ffprobe_path() is not None


def ffmpeg_available() -> bool:
    return get_ffmpeg_path() is not None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv",
    ".ts", ".m2ts", ".webm", ".ogv",
}

# Codec → file extension mapping for extraction
# Codecs not in this map are image-based and cannot be scanned
TEXT_CODEC_EXT: dict[str, str] = {
    "subrip":           ".srt",
    "srt":              ".srt",
    "ass":              ".ass",
    "ssa":              ".ssa",
    "webvtt":           ".vtt",
    "mov_text":         ".srt",   # MP4 text tracks — ffmpeg extracts as SRT
    "text":             ".srt",
    "microdvd":         ".srt",
    "mpl2":             ".srt",
    "realtext":         ".srt",
    "sami":             ".srt",
    "stl":              ".srt",
    "teletext":         ".srt",
}

IMAGE_CODECS = {
    "hdmv_pgs_subtitle", "pgssub",   # Blu-ray PGS
    "dvd_subtitle", "dvdsub",         # DVD VOBSUB
    "dvb_subtitle", "dvb_teletext",   # DVB
    "xsub",                           # DivX XSUB
    "dvb_teletext",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SubtitleTrack:
    index: int           # stream index within the file (ffprobe "index")
    track_num: int       # subtitle track number (0-based within subtitle streams)
    codec: str
    language: str        # ISO 639-2 or "und"
    title: str
    forced: bool
    default: bool
    is_text: bool        # can we extract and scan it?
    is_image: bool       # image-based, can't scan text
    ad_count: int = 0
    warning_count: int = 0
    total_blocks: int = 0
    scan_error: str = ""
    flagged_samples: List[str] = field(default_factory=list)  # up to 5 samples
    subtitle: Any = None  # ParsedSubtitle — stored for re-thresholding in GUI

    @property
    def codec_display(self) -> str:
        """Human-readable codec name."""
        return {
            "hdmv_pgs_subtitle": "PGS",
            "pgssub":            "PGS",
            "dvd_subtitle":      "VOBSUB",
            "dvdsub":            "VOBSUB",
            "dvb_subtitle":      "DVB",
            "dvb_teletext":      "DVB Teletext",
            "xsub":              "XSUB",
        }.get(self.codec, self.codec)

    @property
    def display_name(self) -> str:
        parts = [f"Track {self.track_num}"]
        if self.language and self.language != "und":
            parts.append(f"[{self.language}]")
        if self.title:
            parts.append(self.title)
        parts.append(f"({self.codec_display})")
        if self.forced:
            parts.append("FORCED")
        if self.default:
            parts.append("DEFAULT")
        return "  ".join(parts)

    @property
    def status_label(self) -> str:
        return self.status_at_threshold(3)

    def status_at_threshold(self, threshold: int = 3) -> str:
        if self.scan_error:
            return "ERROR"
        if not self.is_text:
            return "IMAGE" if self.is_image else "SKIP"
        if self.subtitle is not None:
            ads   = sum(1 for b in self.subtitle.blocks if b.regex_matches >= threshold)
            warns = sum(1 for b in self.subtitle.blocks
                        if b.regex_matches == threshold - 1 and threshold > 1)
            if ads > 0:   return "ADS"
            if warns > 0: return "WARN"
            return "CLEAN"
        # Fall back to stored counts (threshold=3 was used at scan time)
        if self.ad_count > 0:    return "ADS"
        if self.warning_count > 0: return "WARN"
        return "CLEAN"

    def ads_at_threshold(self, threshold: int = 3) -> int:
        if self.subtitle is not None:
            return sum(1 for b in self.subtitle.blocks if b.regex_matches >= threshold)
        return self.ad_count if threshold <= 3 else 0

    def warnings_at_threshold(self, threshold: int = 3) -> int:
        if self.subtitle is not None:
            return sum(1 for b in self.subtitle.blocks
                       if b.regex_matches == threshold - 1 and threshold > 1)
        return self.warning_count if threshold == 3 else 0


@dataclass
class VideoScanResult:
    path: Path
    tracks: List[SubtitleTrack] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def has_ads(self) -> bool:
        return any(t.ad_count > 0 for t in self.tracks)

    @property
    def text_tracks(self) -> List[SubtitleTrack]:
        return [t for t in self.tracks if t.is_text]

    @property
    def image_tracks(self) -> List[SubtitleTrack]:
        return [t for t in self.tracks if t.is_image]

    def summary_lines(self) -> List[str]:
        lines = []
        for t in self.tracks:
            status = t.status_label
            line = f"  [{status:5}]  {t.display_name}"
            if t.ad_count:
                line += f"  — {t.ad_count} ad block(s)"
            elif t.warning_count:
                line += f"  — {t.warning_count} warning(s)"
            elif t.scan_error:
                line += f"  — {t.scan_error}"
            lines.append(line)
            for sample in t.flagged_samples[:3]:
                lines.append(f"            ↳ {sample[:80]}")
        return lines


# ---------------------------------------------------------------------------
# ffprobe / ffmpeg helpers
# ---------------------------------------------------------------------------


def probe_video(path: Path) -> Tuple[List[SubtitleTrack], str]:
    """
    Run ffprobe on a video file and return (tracks, error).
    error is empty string on success.
    """
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return [], "ffprobe not found — install FFmpeg and ensure it's on PATH"

    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30, **_SUBPROCESS_FLAGS)
    except subprocess.TimeoutExpired:
        return [], "ffprobe timed out"
    except Exception as e:
        return [], f"ffprobe failed: {e}"

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()[:200]
        return [], f"ffprobe error: {err}"

    try:
        stdout = proc.stdout.decode("utf-8", errors="replace")
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        return [], f"Could not parse ffprobe output: {e}"

    streams = data.get("streams", [])
    tracks: List[SubtitleTrack] = []
    sub_track_num = 0

    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue

        codec = stream.get("codec_name", "unknown").lower()
        tags = stream.get("tags", {})
        lang = tags.get("language", "und")
        title = tags.get("title", "")
        disposition = stream.get("disposition", {})
        forced = bool(disposition.get("forced", 0))
        default = bool(disposition.get("default", 0))
        is_text = codec in TEXT_CODEC_EXT
        is_image = codec in IMAGE_CODECS

        tracks.append(SubtitleTrack(
            index=stream.get("index", -1),
            track_num=sub_track_num,
            codec=codec,
            language=lang,
            title=title,
            forced=forced,
            default=default,
            is_text=is_text,
            is_image=is_image,
        ))
        sub_track_num += 1

    return tracks, ""


def extract_and_scan_track(
    video_path: Path,
    track: SubtitleTrack,
) -> None:
    """
    Extract a single text subtitle track from the video to a temp file,
    run ad analysis on it, and populate track.ad_count / warning_count / flagged_samples.
    Modifies track in-place.
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        track.scan_error = "ffmpeg not found"
        return

    if not track.is_text:
        track.scan_error = "image-based format — cannot scan text"
        return

    ext = TEXT_CODEC_EXT.get(track.codec, ".srt")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / f"track_{track.track_num}{ext}"

        # Extract with ffmpeg: -map 0:s:<track_num> selects the Nth subtitle stream
        cmd = [
            ffmpeg,
            "-v", "error",
            "-i", str(video_path),
            "-map", f"0:s:{track.track_num}",
            "-c:s", "copy" if ext in (".ass", ".ssa") else "srt",
            str(out_path),
            "-y",
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60, **_SUBPROCESS_FLAGS)
        except subprocess.TimeoutExpired:
            track.scan_error = "ffmpeg extraction timed out"
            return
        except Exception as e:
            track.scan_error = f"ffmpeg error: {e}"
            return

        if not out_path.exists() or out_path.stat().st_size == 0:
            track.scan_error = "extraction produced empty file"
            return

        # Override path language to match the track's declared language
        # so the cleaner picks up language-specific patterns
        try:
            sub = load_subtitle(out_path)
            # Patch in the declared language from the container
            sub.path = sub.path.with_name(
                f"track_{track.track_num}.{track.language}{ext}"
            )
            analyze(sub)
        except Exception as e:
            track.scan_error = f"parse error: {e}"
            return

        track.total_blocks = len(sub.blocks)
        track.ad_count = sum(1 for b in sub.blocks if b.is_ad)
        track.warning_count = sum(1 for b in sub.blocks if b.is_warning)
        track.subtitle = sub   # store for re-thresholding and per-block editing

        # Collect up to 5 sample flagged lines for reporting
        for b in sub.blocks:
            if b.is_ad or b.is_warning:
                sample = f"[{b.start}] {b.text[:70]}"
                if b.matched_patterns:
                    sample += f"  ({', '.join(b.matched_patterns)})"
                track.flagged_samples.append(sample)
                if len(track.flagged_samples) >= 5:
                    break


def scan_video(path: Path) -> VideoScanResult:
    """
    Full pipeline: probe → extract each text track → analyze.
    Returns a VideoScanResult. Never raises — errors are captured in result.error.
    """
    result = VideoScanResult(path=path)
    try:
        return _scan_video_inner(path, result)
    except Exception as e:
        result.error = f"unexpected error: {e}"
        return result


def _scan_video_inner(path: Path, result: VideoScanResult) -> VideoScanResult:
    tracks, error = probe_video(path)
    if error:
        result.error = error
        return result

    if not tracks:
        result.error = "no subtitle tracks found"
        return result

    result.tracks = tracks

    # Extract and scan all text tracks in parallel — each spawns its own ffmpeg
    # subprocess and writes to its own tempdir, so there is no shared state.
    # Track objects are modified in-place; the thread pool waits for all to finish
    # before returning so result.tracks is fully populated on exit.
    text_tracks = [t for t in tracks if t.is_text]
    if text_tracks:
        n_workers = min(2, len(text_tracks))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [pool.submit(extract_and_scan_track, path, t) for t in text_tracks]
            wait(futures)  # block until all tracks done; errors captured inside each track

    return result


# ---------------------------------------------------------------------------
# Batch video scan
# ---------------------------------------------------------------------------

def collect_video_files(roots: List[Path], recursive: bool = True) -> List[Path]:
    found: List[Path] = []

    def _walk(d: Path):
        for item in sorted(d.iterdir()):
            if item.name.startswith("."):
                continue
            if item.is_dir() and not item.is_symlink() and recursive:
                _walk(item)
            elif item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                found.append(item)

    for root in roots:
        if root.is_file() and root.suffix.lower() in VIDEO_EXTENSIONS:
            found.append(root)
        elif root.is_dir():
            _walk(root)

    return found
