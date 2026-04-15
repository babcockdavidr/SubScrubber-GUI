"""
core/whisper.py — Whisper audio transcription pipeline.

Handles:
  - faster-whisper path/availability resolution (settings.json + auto-detect)
  - Model management (download on first use, stored in USER_DIR/whisper_models/)
  - Transcription of a video file's audio track to subtitle blocks
  - SDH mode: wraps non-speech segments in [brackets]
  - Output as a ParsedSubtitle-compatible structure for Save as .srt / remux

Public API:
  faster_whisper_available()          — bool
  get_model_dir() / set_model_dir()   — model storage path
  clear_model_dir()                   — revert to default model storage path
  list_downloaded_models()            — List[str] of model names on disk
  transcribe(video_path, model, language, sdh, progress_cb, segment_cb)
                                      — TranscribeResult

ffmpeg / ffprobe path resolution lives in core/ffprobe.py.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import sys as _sys

_SUBPROCESS_FLAGS: dict = (
    {"creationflags": 0x08000000} if _sys.platform == "win32" else {}
)

# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

from .paths import load_settings as _load_settings, save_settings as _save_settings, USER_DIR


# ---------------------------------------------------------------------------
# Model directory
# ---------------------------------------------------------------------------

_DEFAULT_MODEL_DIR = USER_DIR / "whisper_models"


def get_model_dir() -> Path:
    """Return the directory where Whisper models are stored."""
    saved = _load_settings().get("whisper_model_dir", "")
    if saved and Path(saved).is_dir():
        return Path(saved)
    return _DEFAULT_MODEL_DIR


def set_model_dir(path: str) -> None:
    s = dict(_load_settings())
    s["whisper_model_dir"] = path
    _save_settings(s)


def clear_model_dir() -> None:
    """Remove any custom model directory, reverting to the default location."""
    s = dict(_load_settings())
    s.pop("whisper_model_dir", None)
    _save_settings(s)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def faster_whisper_available() -> bool:
    """Return True if faster-whisper is importable and its dependencies load cleanly.

    When SubForge runs as a windowed app (double-click / PyInstaller), sys.stderr
    is None because there is no console. faster_whisper pulls in ctranslate2 →
    transformers, which does `sys.stderr.flush` at module level and crashes with
    AttributeError. We temporarily substitute a no-op stream so the import can
    proceed, then restore the original value regardless of outcome.
    """
    import io
    _saved_stderr = _sys.stderr
    _saved_stdout = _sys.stdout
    try:
        if _sys.stderr is None:
            _sys.stderr = io.StringIO()
        if _sys.stdout is None:
            _sys.stdout = io.StringIO()
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False
    finally:
        _sys.stderr = _saved_stderr
        _sys.stdout = _saved_stdout


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------

MODELS = {
    "tiny":   "Fastest, least accurate. Good for quick previews.",
    "base":   "Fast, reasonable accuracy for clear audio.",
    "small":  "Good balance of speed and accuracy.",
    "medium": "High accuracy, slower. Recommended for most use.",
    "large":  "Best accuracy, slowest. Use for difficult audio.",
}


def list_downloaded_models() -> List[str]:
    """Return list of model names that are already downloaded to model_dir."""
    model_dir = get_model_dir()
    if not model_dir.exists():
        return []
    downloaded = []
    for name in MODELS:
        # New flat layout: whisper_models/small/model.bin
        if (model_dir / name / "model.bin").exists():
            downloaded.append(name)
            continue
        # Legacy HF cache layout: whisper_models/models--Systran--faster-whisper-small/snapshots/...
        for entry in model_dir.iterdir():
            if entry.is_dir() and entry.name.startswith(f"models--Systran--faster-whisper-{name}"):
                downloaded.append(name)
                break
    return downloaded


def model_is_downloaded(name: str) -> bool:
    return name in list_downloaded_models()


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class TranscribeSegment:
    start_ms: int
    end_ms:   int
    text:     str
    is_sdh:   bool = False   # True if this is a non-speech annotation


@dataclass
class TranscribeResult:
    success:   bool
    segments:  List[TranscribeSegment] = field(default_factory=list)
    language:  str = ""
    model:     str = ""
    error:     str = ""


# ---------------------------------------------------------------------------
# Transcription — runs in an isolated subprocess to prevent CTranslate2/Qt
# native library conflicts from crashing the main process.
# ---------------------------------------------------------------------------

def transcribe(
    video_path: Path,
    model:       str = "small",
    language:    Optional[str] = None,
    sdh:         bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
    segment_cb:  Optional[Callable[[int, int], None]] = None,
) -> "TranscribeResult":
    """
    Transcribe audio by launching an isolated subprocess.
    Passes a result JSON path via environment; polls for progress lines on stdout.
    Never raises — all errors are returned in TranscribeResult.error.
    """
    if not faster_whisper_available():
        return TranscribeResult(
            success=False,
            error="faster-whisper is not installed. Run: pip install faster-whisper"
        )

    import tempfile, os

    with tempfile.TemporaryDirectory() as tmpdir:
        result_path  = Path(tmpdir) / "result.json"
        worker_path  = Path(tmpdir) / "whisper_worker.py"

        # The worker script is fully self-contained — it imports nothing from
        # SubForge's core package. This means it runs correctly in any Python
        # environment that has faster-whisper installed, regardless of where
        # SubForge itself is installed or what _MEIPASS paths exist.
        model_dir_str = str(get_model_dir())
        appdata = str(Path.home() / "AppData" / "Roaming" / "SubForge") if _sys.platform == "win32" else str(Path.home() / "SubForge")
        worker_script = f"""
import sys, os, json, argparse, traceback
from pathlib import Path

os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"]  = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

APPDATA_DIR = Path({repr(appdata)})
APPDATA_DIR.mkdir(parents=True, exist_ok=True)

def _write_crash_log(text):
    try:
        (APPDATA_DIR / "whisper_crash.log").write_text(text, encoding="utf-8")
    except Exception:
        pass

parser = argparse.ArgumentParser()
parser.add_argument("--video",    required=True)
parser.add_argument("--model",    required=True)
parser.add_argument("--result",   required=True)
parser.add_argument("--language", default=None)
parser.add_argument("--sdh",      action="store_true")
args = parser.parse_args()

video_path  = Path(args.video)
model_name  = args.model
language    = args.language or None
sdh         = args.sdh
result_path = Path(args.result)
model_dir   = Path({repr(model_dir_str)})

# Flat model dir — no HF Hub cache structure, no symlinks.
# output_dir causes download_model to copy files directly into the folder,
# bypassing the blobs/snapshots structure that breaks on Windows without
# Developer Mode.
flat_model_dir = model_dir / model_name
flat_model_dir.mkdir(parents=True, exist_ok=True)

def _looks_like_sdh(text):
    t = text.strip()
    if (t.startswith("[") and t.endswith("]")) or (t.startswith("(") and t.endswith(")")):
        return True
    stripped = t.replace("\\u266a", "").replace("\\u266b", "").replace("*", "").strip()
    if not stripped:
        return True
    import re as _re
    bracket_content = _re.findall(r'\\[.*?\\]|\\(.*?\\)', t)
    if bracket_content:
        bracket_chars = sum(len(b) for b in bracket_content)
        if bracket_chars / len(t) > 0.5:
            return True
    return False

def _detect_device():
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"

try:
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    device, compute_type = _detect_device()

    print(f"PROGRESS:Loading Whisper model '{{model_name}}'\\u2026", flush=True)

    # Use output_dir so files are stored flat (no symlinks, no blobs/snapshots).
    # This works on Windows without Developer Mode.
    local_model_path = download_model(model_name, output_dir=str(flat_model_dir))

    whisper_model = WhisperModel(
        local_model_path,
        device=device,
        compute_type=compute_type,
    )

    lang_label = language if language else "auto-detect"
    print(f"PROGRESS:Transcribing [{{lang_label}}] using {{model_name}} model\\u2026", flush=True)

    segments_gen, info = whisper_model.transcribe(
        str(video_path),
        language=language,
        word_timestamps=False,
        vad_filter=not sdh,
        condition_on_previous_text=True,
        initial_prompt=("[Music] [Applause] [Laughter] [Silence] " if sdh else None),
        suppress_tokens=([] if sdh else [-1]),
    )

    detected_language = info.language or language or ""
    result_segments = []
    count = 0

    for seg in segments_gen:
        text = seg.text.strip()
        if not text:
            continue
        start_ms = int(seg.start * 1000)
        end_ms   = int(seg.end   * 1000)
        is_sdh_seg = _looks_like_sdh(text)
        if is_sdh_seg:
            if sdh:
                if not (text.startswith("[") and text.endswith("]")):
                    text = f"[{{text}}]"
                result_segments.append({{"start_ms": start_ms, "end_ms": end_ms, "text": text, "is_sdh": True}})
        else:
            result_segments.append({{"start_ms": start_ms, "end_ms": end_ms, "text": text, "is_sdh": False}})
        count += 1
        print(f"SEGMENT:{{count}}", flush=True)
        if count % 50 == 0:
            print(f"PROGRESS:Transcribed {{count}} segments\\u2026", flush=True)

    result = {{"success": True, "segments": result_segments, "language": detected_language, "model": model_name}}

except Exception as e:
    tb = traceback.format_exc()
    _write_crash_log(tb)
    result = {{"success": False, "error": f"{{e}}\\n\\n{{tb}}"}}

result_path.write_text(json.dumps(result), encoding="utf-8")
"""
        worker_path.write_text(worker_script, encoding="utf-8")

        # Find a real Python interpreter. In source mode sys.executable is
        # already correct. In a frozen bundle it's SubForge.exe, so we search PATH.
        frozen = getattr(_sys, "frozen", False)
        if frozen:
            import shutil as _shutil
            python_exe = _shutil.which("python") or _shutil.which("python3")
            if not python_exe:
                return TranscribeResult(
                    success=False,
                    error=(
                        "Transcribe requires faster-whisper installed in a Python "
                        "environment. No Python interpreter found on PATH.\n\n"
                        "Install Python and faster-whisper, then ensure python.exe "
                        "is on your PATH."
                    )
                )
        else:
            python_exe = _sys.executable

        cmd = [
            python_exe, str(worker_path),
            "--video",  str(video_path),
            "--model",  model,
            "--result", str(result_path),
        ]
        if language:
            cmd += ["--language", language]
        if sdh:
            cmd += ["--sdh"]

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        flags = {"creationflags": 0x08000000} if _sys.platform == "win32" else {}

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                **flags,
            )
        except Exception as e:
            return TranscribeResult(success=False, error=f"Failed to start subprocess: {e}")

        seg_count = 0
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line.startswith("PROGRESS:") and progress_cb:
                    progress_cb(line[9:])
                elif line.startswith("SEGMENT:") and segment_cb:
                    try:
                        seg_count = int(line[8:])
                        segment_cb(seg_count, -1)
                    except ValueError:
                        pass
        except Exception:
            pass

        proc.wait()

        if not result_path.exists():
            stderr_out = ""
            try:
                stderr_out = proc.stderr.read()
            except Exception:
                pass
            return TranscribeResult(
                success=False,
                error=f"Subprocess exited with code {proc.returncode}.\n{stderr_out}"
            )

        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception as e:
            return TranscribeResult(success=False, error=f"Failed to read result: {e}")

        if not data.get("success"):
            return TranscribeResult(success=False, error=data.get("error", "Unknown error"))

        segments = [
            TranscribeSegment(
                start_ms=s["start_ms"],
                end_ms=s["end_ms"],
                text=s["text"],
                is_sdh=s.get("is_sdh", False),
            )
            for s in data.get("segments", [])
        ]
        return TranscribeResult(
            success=True,
            segments=segments,
            language=data.get("language", ""),
            model=data.get("model", model),
        )


def _run_subprocess_worker(args) -> None:
    """
    Entry point when this module is run as __main__.
    Performs the actual transcription and writes a JSON result file.
    Emits PROGRESS: and SEGMENT: lines to stdout for the parent to read.
    """
    import sys as _sys2

    video_path  = Path(args.video)
    model_name  = args.model
    language    = args.language or None
    sdh         = args.sdh
    result_path = Path(args.result)

    def _progress(msg: str):
        print(f"PROGRESS:{msg}", flush=True)

    def _segment(n: int, _t: int):
        print(f"SEGMENT:{n}", flush=True)

    try:
        from faster_whisper import WhisperModel

        model_dir = get_model_dir()
        model_dir.mkdir(parents=True, exist_ok=True)

        device, compute_type = _detect_device()

        _progress(f"Loading Whisper model '{model_name}'…")

        whisper_model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=str(model_dir),
        )

        lang_label = language if language else "auto-detect"
        _progress(f"Transcribing [{lang_label}] using {model_name} model…")

        segments_gen, info = whisper_model.transcribe(
            str(video_path),
            language=language,
            word_timestamps=False,
            vad_filter=not sdh,   # VAD strips non-speech; disable it when SDH is on
            condition_on_previous_text=True,
            initial_prompt=(
                "[Music] [Applause] [Laughter] [Silence] "
                if sdh else None
            ),
            suppress_tokens=[] if sdh else [-1],
        )

        detected_language = info.language or language or ""
        result_segments = []
        count = 0

        for seg in segments_gen:
            text = seg.text.strip()
            if not text:
                continue

            start_ms = int(seg.start * 1000)
            end_ms   = int(seg.end   * 1000)
            is_sdh_seg = _looks_like_sdh(text)

            if is_sdh_seg:
                if sdh:
                    if not (text.startswith("[") and text.endswith("]")):
                        text = f"[{text}]"
                    result_segments.append({
                        "start_ms": start_ms, "end_ms": end_ms,
                        "text": text, "is_sdh": True
                    })
            else:
                result_segments.append({
                    "start_ms": start_ms, "end_ms": end_ms,
                    "text": text, "is_sdh": False
                })

            count += 1
            _segment(count, -1)
            if count % 50 == 0:
                _progress(f"Transcribed {count} segments…")

        result = {
            "success": True,
            "segments": result_segments,
            "language": detected_language,
            "model": model_name,
        }
    except Exception as e:
        import traceback
        result = {
            "success": False,
            "error": f"{e}\n\n{traceback.format_exc()}",
        }

    result_path.write_text(json.dumps(result), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_device() -> Tuple[str, str]:
    """
    Return (device, compute_type) for faster-whisper.
    Prefers CUDA float16 if available, falls back to CPU int8.
    """
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


def _looks_like_sdh(text: str) -> bool:
    """
    Return True if the segment is primarily a non-speech annotation.
    Whisper outputs these as [Music], [LAUGHS], (applause), ♪ lyrics ♪, etc.
    """
    t = text.strip()
    # Fully bracketed — [Music], [LAUGHS], [INDISTINCT CHATTER], etc.
    if (t.startswith("[") and t.endswith("]")) or \
       (t.startswith("(") and t.endswith(")")):
        return True
    # Music notes — with or without surrounding text
    stripped = t.replace("♪", "").replace("♫", "").replace("*", "").strip()
    if not stripped:
        return True
    # Segments that are mostly a bracketed annotation with minimal surrounding text
    # e.g. "[Music] Yeah" or "(laughing) Okay"
    import re as _re
    bracket_content = _re.findall(r'\[.*?\]|\(.*?\)', t)
    if bracket_content:
        bracket_chars = sum(len(b) for b in bracket_content)
        if bracket_chars / len(t) > 0.5:
            return True
    return False


# ---------------------------------------------------------------------------
# SRT assembly
# ---------------------------------------------------------------------------

def segments_to_srt(segments: List[TranscribeSegment]) -> str:
    """Convert a list of TranscribeSegments to SRT format string."""
    lines = []
    idx = 1
    for seg in segments:
        lines.append(str(idx))
        lines.append(f"{_ms_to_srt(seg.start_ms)} --> {_ms_to_srt(seg.end_ms)}")
        lines.append(seg.text)
        lines.append("")
        idx += 1
    return "\n".join(lines)


def _ms_to_srt(ms: int) -> str:
    h  =  ms // 3_600_000; ms -= h * 3_600_000
    m  =  ms //    60_000; ms -= m *    60_000
    s  =  ms //     1_000; ms -= s *     1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Subprocess entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--video",    required=True)
    parser.add_argument("--model",    required=True)
    parser.add_argument("--result",   required=True)
    parser.add_argument("--language", default=None)
    parser.add_argument("--sdh",      action="store_true")
    _run_subprocess_worker(parser.parse_args())
