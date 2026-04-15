"""
MKVToolNix integration — mkvmerge-based subtitle track replacement.

Pipeline:
  1. ffmpeg extracts each text subtitle track to a temp .srt/.ass file
  2. SubForge cleans the extracted file (removes ad blocks)
  3. mkvmerge rebuilds the MKV:
       - all original video + audio streams kept via --no-subtitles + re-add
       - original subtitle tracks kept EXCEPT the ones being replaced
       - cleaned subtitle files added in their place with full metadata
  4. Atomic swap: write to a temp file first, rename over original only on success
  5. Optional backup: rename original to filename.backup.mkv before overwriting

Supports MKV (via mkvmerge) and MP4/M4V (via ffmpeg).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .ffprobe import SubtitleTrack, TEXT_CODEC_EXT, _find_ffmpeg
from .cleaner_options import language_display_name
from .subtitle import load_subtitle, write_subtitle
from .cleaner import clean as cleaner_clean


# ---------------------------------------------------------------------------
# Settings persistence  (stores mkvmerge path if not on system PATH)
# ---------------------------------------------------------------------------

from .paths import load_settings as _load_settings, save_settings as _save_settings

import sys as _sys
_SUBPROCESS_FLAGS: dict = (
    {"creationflags": 0x08000000} if _sys.platform == "win32" else {}
)


def get_mkvmerge_path() -> Optional[str]:
    """
    Return path to mkvmerge executable, checking in order:
      1. Saved path in settings.json
      2. System PATH
      3. Default Windows install location
    """
    settings = _load_settings()
    saved = settings.get("mkvmerge_path", "")
    if saved and Path(saved).is_file():
        return saved

    on_path = shutil.which("mkvmerge")
    if on_path:
        return on_path

    # Default Windows install location
    default = Path(r"C:\Program Files\MKVToolNix\mkvmerge.exe")
    if default.is_file():
        return str(default)

    return None


def set_mkvmerge_path(path: str) -> None:
    """Persist a custom mkvmerge path to settings.json."""
    s = dict(_load_settings())
    s["mkvmerge_path"] = path
    _save_settings(s)


def mkvmerge_available() -> bool:
    return get_mkvmerge_path() is not None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CleanedTrack:
    """Represents a subtitle track that has been extracted and cleaned."""
    track: SubtitleTrack          # original track metadata
    cleaned_path: Path            # path to the cleaned subtitle file
    original_blocks: int = 0
    removed_blocks: int = 0

    @property
    def language(self) -> str:
        return self.track.language

    @property
    def title(self) -> str:
        return self.track.title

    @property
    def forced(self) -> bool:
        return self.track.forced

    @property
    def default(self) -> bool:
        return self.track.default

    @property
    def ext(self) -> str:
        return self.cleaned_path.suffix


@dataclass
class RemuxResult:
    success: bool
    output_path: Optional[Path] = None
    backup_path: Optional[Path] = None
    error: str = ""
    cleaned_tracks: List[CleanedTrack] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction + cleaning
# ---------------------------------------------------------------------------

def extract_and_clean_track(
    video_path: Path,
    track: SubtitleTrack,
    dest_dir: Path,
    remove_warnings: bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Tuple[Optional[CleanedTrack], str]:
    """
    Extract a single subtitle track from the video, clean it, write to dest_dir.
    Returns (CleanedTrack, "") on success or (None, error_message) on failure.
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None, "ffmpeg not found"

    if not track.is_text:
        return None, "image-based track — cannot clean"

    ext = TEXT_CODEC_EXT.get(track.codec, ".srt")
    lang = track.language if track.language and track.language != "und" else "und"

    # Detect SDH from track title (case-insensitive)
    title_lower = (track.title or "").lower()
    is_sdh = any(kw in title_lower for kw in ("sdh", "hearing impaired", "hi", "cc"))

    # Build filename: [video_stem].[lang][.sdh].[ext]
    # Falls back to track-based name if no video_path stem is usable
    video_stem = video_path.stem if video_path else None
    if video_stem:
        lang_suffix = f".{lang}" if lang != "und" else ""
        sdh_suffix  = ".sdh" if is_sdh else ""
        out_filename = f"{video_stem}{lang_suffix}{sdh_suffix}{ext}"
    else:
        out_filename = f"track{track.track_num}.{lang}{'.sdh' if is_sdh else ''}{ext}"

    out_path = dest_dir / out_filename

    # Handle filename collisions (e.g. two English tracks)
    if out_path.exists():
        stem = out_path.stem
        counter = 2
        while out_path.exists():
            out_path = dest_dir / f"{stem}.{counter}{ext}"
            counter += 1

    if progress_cb:
        progress_cb(f"Extracting track {track.track_num} ({lang})…")

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
        proc = subprocess.run(cmd, capture_output=True, timeout=120, **_SUBPROCESS_FLAGS)
    except subprocess.TimeoutExpired:
        return None, "ffmpeg extraction timed out"
    except Exception as e:
        return None, f"ffmpeg error: {e}"

    if not out_path.exists() or out_path.stat().st_size == 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")[:200]
        return None, f"extraction produced empty file: {stderr}"

    if progress_cb:
        progress_cb(f"Cleaning track {track.track_num} ({lang})…")

    try:
        # If the track has a stored subtitle with per-block _kept flags
        # (set by the user in the GUI), use those blocks directly rather
        # than re-extracting and re-analyzing.
        if (track.subtitle is not None and
                any(getattr(b, '_kept', False) for b in track.subtitle.blocks)):
            subtitle = track.subtitle
            original_blocks = len(subtitle.blocks)
            # Remove blocks marked as ads that are NOT kept by the user
            remove_ids = {
                id(b) for b in subtitle.blocks
                if (b.is_ad or (remove_warnings and b.is_warning))
                and not getattr(b, '_kept', False)
            }
            subtitle.blocks = [b for b in subtitle.blocks
                                if id(b) not in remove_ids]
            for idx, b in enumerate(subtitle.blocks, 1):
                b.current_index = idx
            removed = original_blocks - len(subtitle.blocks)
            write_subtitle(subtitle, dest=out_path)
        else:
            subtitle = load_subtitle(out_path)
            subtitle.path = subtitle.path.with_name(
                f"track{track.track_num}.{lang}{ext}"
            )
            original_blocks = len(subtitle.blocks)
            subtitle, removed = cleaner_clean(
                subtitle, dry_run=False, remove_warnings=remove_warnings
            )
            write_subtitle(subtitle, dest=out_path)
    except Exception as e:
        return None, f"cleaning error: {e}"

    return CleanedTrack(
        track=track,
        cleaned_path=out_path,
        original_blocks=original_blocks,
        removed_blocks=removed,
    ), ""


# ---------------------------------------------------------------------------
# mkvmerge remux
# ---------------------------------------------------------------------------

def remux_with_cleaned_tracks(
    video_path: Path,
    all_tracks: List[SubtitleTrack],
    cleaned: List[CleanedTrack],
    make_backup: bool = True,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> RemuxResult:
    """
    Rebuild an MKV file replacing specified subtitle tracks with cleaned versions.
    This function specifically uses mkvmerge and only supports MKV.
    For MP4/M4V, use remux_mp4_with_ffmpeg() or the remux_video() router.

    Strategy:
      - Pass original MKV with --no-subtitles to drop all subtitle streams
      - Re-add subtitle streams we are NOT cleaning using --subtitle-tracks
      - Append cleaned subtitle files as additional inputs with full metadata
      - Write to a temp file first; atomic rename on success
    """
    mkvmerge = get_mkvmerge_path()
    if not mkvmerge:
        return RemuxResult(
            success=False,
            error="mkvmerge not found. Install MKVToolNix or set the path in Settings."
        )

    if not video_path.suffix.lower() == ".mkv":
        return RemuxResult(
            success=False,
            error=f"Internal routing error: remux_with_cleaned_tracks received a '{video_path.suffix}' file. Only MKV is supported by mkvmerge — MP4/M4V should be routed to remux_mp4_with_ffmpeg()."
        )

    cleaned_track_nums = {ct.track.track_num for ct in cleaned}

    # Subtitle stream indices to KEEP from the original (not being replaced)
    keep_indices = [
        t.index for t in all_tracks
        if t.track_num not in cleaned_track_nums
    ]

    if progress_cb:
        progress_cb("Building mkvmerge command…")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_out = Path(tmpdir) / f"_remux_{video_path.name}"

        cmd = [mkvmerge, "-o", str(tmp_out)]

        # Input 0: original MKV — all streams except subtitles
        cmd += ["--no-subtitles", str(video_path)]

        # Re-add subtitle streams we're keeping (by stream index)
        if keep_indices:
            indices_str = ",".join(str(i) for i in keep_indices)
            cmd += [
                "--subtitle-tracks", indices_str,
                "--no-video", "--no-audio", "--no-attachments", "--no-chapters",
                str(video_path),
            ]

        # Add each cleaned subtitle file as a new input with full metadata
        for ct in cleaned:
            t = ct.track

            if t.language and t.language != "und":
                cmd += ["--language", f"0:{t.language}"]

            # Normalize track title to language name only — strips encoder credits
            clean_title = language_display_name(t.language) if t.language else t.title
            if clean_title:
                cmd += ["--track-name", f"0:{clean_title}"]

            # Forced / default flags
            cmd += ["--forced-display-flag", f"0:{'1' if t.forced else '0'}"]
            cmd += ["--default-track-flag",  f"0:{'1' if t.default else '0'}"]

            cmd.append(str(ct.cleaned_path))

        if progress_cb:
            progress_cb(f"Running mkvmerge on {video_path.name}…")

        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=600, **_SUBPROCESS_FLAGS
            )
        except subprocess.TimeoutExpired:
            return RemuxResult(success=False, error="mkvmerge timed out (10 min limit)")
        except Exception as e:
            return RemuxResult(success=False, error=f"mkvmerge failed to start: {e}")

        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")

        # mkvmerge exits 0 = success, 1 = warnings (still ok), 2 = error
        if proc.returncode == 2:
            return RemuxResult(
                success=False,
                error=f"mkvmerge error: {(stdout + stderr)[:400]}"
            )

        if not tmp_out.exists() or tmp_out.stat().st_size == 0:
            return RemuxResult(success=False, error="mkvmerge produced empty output")

        # ── Atomic swap ──────────────────────────────────────────────
        if progress_cb:
            progress_cb("Saving output…")

        backup_path: Optional[Path] = None

        if make_backup:
            backup_path = video_path.with_suffix(".backup.mkv")
            # If backup already exists, add a number
            counter = 1
            while backup_path.exists():
                backup_path = video_path.with_name(
                    f"{video_path.stem}.backup{counter}.mkv"
                )
                counter += 1
            try:
                video_path.rename(backup_path)
            except Exception as e:
                return RemuxResult(
                    success=False,
                    error=f"Could not create backup: {e}"
                )
        else:
            try:
                video_path.unlink()
            except Exception as e:
                return RemuxResult(
                    success=False,
                    error=f"Could not remove original for replacement: {e}"
                )

        try:
            shutil.move(str(tmp_out), str(video_path))
        except Exception as e:
            # Attempt to restore backup
            if backup_path and backup_path.exists():
                try:
                    backup_path.rename(video_path)
                except Exception:
                    pass
            return RemuxResult(
                success=False,
                error=f"Could not move remuxed file into place: {e}"
            )

    return RemuxResult(
        success=True,
        output_path=video_path,
        backup_path=backup_path,
        cleaned_tracks=cleaned,
    )


# ---------------------------------------------------------------------------
# ffmpeg-based MP4 remux
# ---------------------------------------------------------------------------

def remux_mp4_with_ffmpeg(
    video_path: Path,
    all_tracks: List[SubtitleTrack],
    cleaned: List[CleanedTrack],
    make_backup: bool = True,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> RemuxResult:
    """
    Rebuild an MP4 file replacing specified subtitle tracks with cleaned versions.

    Uses ffmpeg since mkvmerge does not support MP4.

    Strategy:
      - Map all streams from the original EXCEPT the subtitle streams being replaced
      - Add each cleaned subtitle file as an additional input
      - Copy all streams without re-encoding (-c copy)
      - Preserve metadata and disposition flags
      - Atomic swap with optional backup
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return RemuxResult(success=False, error="ffmpeg not found.")

    suffix = video_path.suffix.lower()
    if suffix not in (".mp4", ".m4v"):
        return RemuxResult(
            success=False,
            error=f"MP4 remux only supports .mp4 and .m4v files, not '{suffix}'."
        )

    if progress_cb:
        progress_cb("Building ffmpeg command for MP4 remux…")

    cleaned_stream_indices = {ct.track.index for ct in cleaned}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_out = Path(tmpdir) / f"_remux_{video_path.name}"

        cmd = [ffmpeg, "-v", "error"]

        # Input 0: original video
        cmd += ["-i", str(video_path)]

        # Additional inputs: one per cleaned subtitle file
        for ct in cleaned:
            cmd += ["-i", str(ct.cleaned_path)]

        # Map everything from the original EXCEPT the replaced subtitle streams
        # Video and audio streams
        cmd += ["-map", "0:v?", "-map", "0:a?"]

        # Keep original subtitle streams that are NOT being replaced
        for track in all_tracks:
            if track.index not in cleaned_stream_indices and track.is_text:
                cmd += ["-map", f"0:{track.index}"]

        # Image-based subs (PGS etc) — keep as-is
        for track in all_tracks:
            if track.index not in cleaned_stream_indices and track.is_image:
                cmd += ["-map", f"0:{track.index}"]

        # Map each cleaned subtitle input
        for i, ct in enumerate(cleaned, 1):
            cmd += ["-map", f"{i}:0"]

        # Copy video and audio without re-encoding
        cmd += ["-c:v", "copy", "-c:a", "copy"]

        # Kept subtitle streams from original — copy codec
        cmd += ["-c:s", "copy"]

        # Cleaned subtitle inputs — must be encoded as mov_text for MP4 containers.
        # External .srt files cannot be stream-copied into MP4; they must be encoded.
        # We override per-stream after the global -c:s copy using stream specifiers.
        # Count kept subtitle streams to know the output stream indices for cleaned ones.
        kept_sub_streams = sum(
            1 for t in all_tracks
            if t.index not in cleaned_stream_indices and (t.is_text or t.is_image)
        )
        for i in range(len(cleaned)):
            out_idx = kept_sub_streams + i
            cmd += [f"-c:s:{out_idx}", "mov_text"]

        # Apply metadata for cleaned tracks
        for i, ct in enumerate(cleaned):
            out_sub_idx = kept_sub_streams + i
            t = ct.track
            if t.language and t.language != "und":
                cmd += [f"-metadata:s:s:{out_sub_idx}", f"language={t.language}"]
            # Normalize track title to language name only — strips encoder credits
            clean_title = language_display_name(t.language) if t.language else t.title
            if clean_title:
                cmd += [f"-metadata:s:s:{out_sub_idx}", f"title={clean_title}"]
            # Disposition flags
            disposition = []
            if t.default: disposition.append("default")
            if t.forced:  disposition.append("forced")
            cmd += [f"-disposition:s:{out_sub_idx}",
                    "+".join(disposition) if disposition else "0"]

        # MP4 faststart for streaming compatibility
        cmd += ["-movflags", "+faststart"]
        cmd += [str(tmp_out), "-y"]

        if progress_cb:
            progress_cb(f"Running ffmpeg on {video_path.name}…")

        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=600, **_SUBPROCESS_FLAGS)
        except subprocess.TimeoutExpired:
            return RemuxResult(success=False, error="ffmpeg timed out (10 min limit)")
        except Exception as e:
            return RemuxResult(success=False, error=f"ffmpeg failed to start: {e}")

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")[:400]
            return RemuxResult(success=False, error=f"ffmpeg error: {stderr}")

        if not tmp_out.exists() or tmp_out.stat().st_size == 0:
            return RemuxResult(success=False, error="ffmpeg produced empty output")

        if progress_cb:
            progress_cb("Saving output…")

        backup_path: Optional[Path] = None

        if make_backup:
            backup_path = video_path.with_suffix(".backup.mp4")
            counter = 1
            while backup_path.exists():
                backup_path = video_path.with_name(
                    f"{video_path.stem}.backup{counter}.mp4"
                )
                counter += 1
            try:
                video_path.rename(backup_path)
            except Exception as e:
                return RemuxResult(success=False, error=f"Could not create backup: {e}")
        else:
            try:
                video_path.unlink()
            except Exception as e:
                return RemuxResult(success=False, error=f"Could not remove original: {e}")

        try:
            shutil.move(str(tmp_out), str(video_path))
        except Exception as e:
            if backup_path and backup_path.exists():
                try:
                    backup_path.rename(video_path)
                except Exception:
                    pass
            return RemuxResult(
                success=False,
                error=f"Could not move remuxed file into place: {e}"
            )

    return RemuxResult(
        success=True,
        output_path=video_path,
        backup_path=backup_path,
        cleaned_tracks=cleaned,
    )


def remux_video(
    video_path: Path,
    all_tracks: List[SubtitleTrack],
    cleaned: List[CleanedTrack],
    make_backup: bool = True,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> RemuxResult:
    """
    Route to the correct remux backend based on file type.
    MKV → mkvmerge. MP4/M4V → ffmpeg.
    """
    suffix = video_path.suffix.lower()
    if suffix == ".mkv":
        return remux_with_cleaned_tracks(
            video_path, all_tracks, cleaned, make_backup, progress_cb
        )
    elif suffix in (".mp4", ".m4v"):
        return remux_mp4_with_ffmpeg(
            video_path, all_tracks, cleaned, make_backup, progress_cb
        )
    else:
        return RemuxResult(
            success=False,
            error=f"Unsupported format for remux: '{suffix}'. Only MKV and MP4 are supported."
        )
