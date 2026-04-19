"""
Subtitle parsing — SRT, ASS/SSA, VTT.

SRT parsing logic is ported directly from KBlixt/subcleaner's SubBlock /
Subtitle implementation (MIT licence). ASS and VTT support is original.

Key design decisions carried over from subcleaner:
  - SubBlock stores real timedelta objects, not strings.
  - `regex_matches` is an int counter (warn=2, ad>=3), matching subcleaner's
    scoring thresholds exactly so punisher/detector logic ports cleanly.
  - `clean_content` strips whitespace/punctuation for duplicate detection.
  - `hints` list accumulates human-readable reasons shown in the GUI.
"""
from __future__ import annotations

import datetime
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Time helpers (from subcleaner's sub_block.py)
# ---------------------------------------------------------------------------

def time_string_to_timedelta(time_string: str) -> datetime.timedelta:
    time = time_string.replace(",", ".").replace(" ", "")
    split = time.split(":")
    hours = float(split[0])
    minutes = float(split[1])
    seconds_raw = split[2][:6]
    seconds_clean = ""
    found_dot = False
    for ch in seconds_raw:
        if ch.isnumeric():
            seconds_clean += ch
        if ch == ".":
            if not found_dot:
                found_dot = True
                seconds_clean += ch
    seconds = float(seconds_clean)
    if seconds >= 60 or minutes >= 60:
        raise ValueError(f"Invalid time: {time_string}")
    return datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)


def timedelta_to_srt_string(td: datetime.timedelta) -> str:
    s = str(td)
    if "." in s:
        s = s[:-3].replace(".", ",").zfill(12)
    else:
        s = f"{s},000".zfill(12)
    return s


def timedelta_to_ass_string(td: datetime.timedelta) -> str:
    total = int(td.total_seconds() * 100)
    cs = total % 100
    total //= 100
    secs = total % 60
    total //= 60
    mins = total % 60
    hrs = total // 60
    return f"{hrs}:{mins:02}:{secs:02}.{cs:02}"


# ---------------------------------------------------------------------------
# ParsingException
# ---------------------------------------------------------------------------

class ParsingException(Exception):
    def __init__(self, block_index, reason):
        self.block_index = block_index
        self.reason = reason
        self.subtitle_file = ""
        self.file_line = None

    def __str__(self):
        return (f"Parsing error at block {self.block_index} in "
                f'"{self.subtitle_file}" line {self.file_line}. reason: {self.reason}')


# ---------------------------------------------------------------------------
# SubBlock
# ---------------------------------------------------------------------------

class SubBlock:
    original_index: int
    current_index: int
    content: str
    clean_content: str
    start_time: datetime.timedelta
    end_time: datetime.timedelta
    regex_matches: int
    hints: List[str]
    _ass_raw_line: Optional[str]
    _vtt_raw_lines: Optional[List[str]]

    def __init__(self, block_content: str, original_index_actual: int):
        lines = block_content.strip().split("\n")

        if self.is_sub_block_header(lines[0]) and len(lines) > 1 and not self.is_sub_block_header(lines[1]):
            lines = [""] + lines

        if lines[0].isnumeric():
            self.original_index = int(lines[0])
        else:
            number = ""
            for ch in lines[0]:
                if ch.isnumeric():
                    number += ch
                else:
                    break
            self.original_index = int(number) if number else original_index_actual

        if len(lines) < 2 or not self.is_sub_block_header(lines[1]):
            raise ParsingException(self.original_index, "incorrectly formatted subtitle block")

        times = lines[1].replace(" ", "").split("-->")
        try:
            self.start_time = time_string_to_timedelta(times[0])
            self.end_time = time_string_to_timedelta(times[1])
        except (ValueError, IndexError):
            raise ParsingException(self.original_index, "failed to parse timeframe.")

        self.content = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        self.content = self.content.replace("</br>", "\n")
        self.clean_content = re.sub(r"[\s.,:_-]", "", self.content)
        self.regex_matches = 0
        self.hints = []
        self._ass_raw_line = None
        self._vtt_raw_lines = None

    @classmethod
    def is_sub_block_header(cls, line: str) -> bool:
        if "\n" in line:
            return False
        times = line.replace(" ", "").split("-->")
        if len(times) < 2:
            return False
        try:
            time_string_to_timedelta(times[0])
            time_string_to_timedelta(times[1])
            return True
        except (ValueError, IndexError):
            return False

    def equal_content(self, other: "SubBlock") -> bool:
        t = re.sub(r"[\s.,:_-]", "", self.content)
        o = re.sub(r"[\s.,:_-]", "", other.content)
        return t == o

    @property
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    @property
    def is_ad(self) -> bool:
        return self.regex_matches >= 3

    @property
    def is_warning(self) -> bool:
        return self.regex_matches == 2


    # ── GUI adapter properties ───────────────────────────────────────────
    # These map the old SubtitleBlock attribute names the GUI/batch/ffprobe
    # code uses onto the real SubBlock fields, so no GUI rewrite is needed.

    @property
    def text(self) -> str:
        """Plain text content (strips nothing — content already has no tags for SRT)."""
        return self.content

    @property
    def start(self) -> str:
        """Start timestamp as formatted string."""
        return timedelta_to_srt_string(self.start_time)

    @property
    def end(self) -> str:
        """End timestamp as formatted string."""
        return timedelta_to_srt_string(self.end_time)

    @property
    def display_text(self) -> str:
        """Content ready for display (same as content for SRT; raw line for ASS)."""
        if self._ass_raw_line is not None:
            return self._ass_raw_line.replace("\\N", "\n")
        if self._vtt_raw_lines is not None:
            return "\n".join(self._vtt_raw_lines)
        return self.content

    def __str__(self) -> str:
        return (f"{timedelta_to_srt_string(self.start_time)} --> "
                f"{timedelta_to_srt_string(self.end_time)}\n{self.content}")


# ---------------------------------------------------------------------------
# Format enum + constants
# ---------------------------------------------------------------------------

class SubtitleFormat(Enum):
    SRT      = "srt"
    ASS      = "ass"
    SSA      = "ssa"
    VTT      = "vtt"
    TTML     = "ttml"
    SAMI     = "sami"
    MICRODVD = "microdvd"
    UNKNOWN  = "unknown"


SUPPORTED_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".ttml", ".sami", ".smi", ".sub"}


def detect_format(path: Path) -> SubtitleFormat:
    return {
        ".srt":  SubtitleFormat.SRT,
        ".ass":  SubtitleFormat.ASS,
        ".ssa":  SubtitleFormat.SSA,
        ".vtt":  SubtitleFormat.VTT,
        ".ttml": SubtitleFormat.TTML,
        ".sami": SubtitleFormat.SAMI,
        ".smi":  SubtitleFormat.SAMI,
        ".sub":  SubtitleFormat.MICRODVD,
    }.get(path.suffix.lower(), SubtitleFormat.UNKNOWN)


# ---------------------------------------------------------------------------
# ParsedSubtitle container
# ---------------------------------------------------------------------------

class ParsedSubtitle:
    def __init__(self, path: Path, fmt: SubtitleFormat):
        self.path = path
        self.fmt = fmt
        self.blocks: List[SubBlock] = []
        self.ad_blocks: Set[SubBlock] = set()
        self.warning_blocks: Set[SubBlock] = set()
        self.pre_content_artifact: str = ""
        self.ass_header: str = ""
        self.vtt_header: str = "WEBVTT"
        self.encoding: str = "utf-8"

    @property
    def language(self) -> str:
        suffixes = self.path.suffixes
        for s in suffixes[max(-3, -len(suffixes)):-1]:
            candidate = s.replace(":", "-").replace("_", "-").split("-")[0][1:].lower()
            if 2 <= len(candidate) <= 3 and candidate.isalpha():
                return candidate
        return "und"

    def ad(self, block: SubBlock):
        self.warning_blocks.discard(block)
        self.ad_blocks.add(block)

    def warn(self, block: SubBlock):
        if block not in self.ad_blocks:
            self.warning_blocks.add(block)

    def reindex(self):
        idx = 1
        for block in self.blocks:
            block.current_index = idx
            idx += 1
        for block in self.ad_blocks:
            block.current_index = None

    def __len__(self):
        return len(self.blocks)

    def __bool__(self):
        return any(b.content for b in self.blocks)


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def _read_file(path: Path) -> tuple:
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            content = path.read_text(encoding=enc)
            if "-->" in content or "[Script Info]" in content or "WEBVTT" in content:
                return content, enc
        except (UnicodeDecodeError, LookupError):
            continue
    try:
        content = path.read_text(encoding="utf-16")
        return content, "utf-16"
    except (UnicodeDecodeError, LookupError):
        pass
    content = path.read_text(encoding="latin-1")
    return content, "latin-1"


# ---------------------------------------------------------------------------
# SRT parser (ported from subcleaner)
# ---------------------------------------------------------------------------

def _parse_srt(subtitle: ParsedSubtitle, content: str) -> None:
    content = content.replace("—>", "-->")
    line_lookup: Dict[str, int] = {}
    for i, line in enumerate(content.split("\n"), 1):
        if "-->" in line:
            line_lookup[line] = i
    content = re.sub(r'\n\s*\n', '\n', content).strip()
    lines = content.split("\n")
    lines.append("")
    _srt_breakup(subtitle, lines, line_lookup)


def _srt_breakup(subtitle: ParsedSubtitle, lines: List[str], line_lookup: Dict[str, int]) -> None:
    last_break = 0
    start_index = 0

    for i in range(len(lines)):
        line = lines[i]
        if not SubBlock.is_sub_block_header(line) or i == len(lines) - 1 or SubBlock.is_sub_block_header(lines[i + 1]):
            continue
        start_index = i + 1
        if i == 0:
            last_break = i
            break
        prev = lines[i - 1]
        last_break = (i - 1) if (prev and prev[0].isnumeric()) else i
        break

    if last_break > 1:
        for line in lines[:last_break]:
            subtitle.pre_content_artifact += line + "\n"

    for i in range(start_index, len(lines)):
        line = lines[i]
        if not SubBlock.is_sub_block_header(line) or i == len(lines) - 1 or SubBlock.is_sub_block_header(lines[i + 1]):
            continue
        prev = lines[i - 1]
        next_break = (i - 1) if (prev and prev[0].isnumeric()) else i
        try:
            block = SubBlock("\n".join(lines[last_break:next_break]), len(subtitle.blocks) + 1)
        except ParsingException as e:
            e.subtitle_file = str(subtitle.path)
            e.file_line = line_lookup.get(lines[last_break])
            logger.warning(e)
            if not subtitle.blocks:
                subtitle.pre_content_artifact += "\n" + "\n".join(lines[last_break:next_break]) + "\n"
            elif subtitle.blocks:
                subtitle.blocks[-1].content += "\n\n" + "\n".join(lines[last_break:next_break])
            last_break = next_break
            continue
        if block.content:
            subtitle.blocks.append(block)
        if "-->" in block.content:
            subtitle.warn(block)
            block.hints.append("malformed_block")
        last_break = next_break

    try:
        block = SubBlock("\n".join(lines[last_break:]), len(subtitle.blocks) + 1)
    except ParsingException as e:
        e.subtitle_file = str(subtitle.path)
        logger.warning(e)
        if subtitle.blocks:
            subtitle.blocks[-1].content += "\n\n" + "\n".join(lines[last_break:])
        return
    if block.content:
        subtitle.blocks.append(block)
    if "-->" in block.content:
        subtitle.warn(block)
        block.hints.append("malformed_block")

    for i, b in enumerate(subtitle.blocks):
        b.current_index = i + 1

    # Merge adjacent identical frames (subcleaner duplicate merging)
    if len(subtitle.blocks) > 1:
        prev = subtitle.blocks[0]
        to_remove: Set[SubBlock] = set()
        for block in subtitle.blocks[1:]:
            if (block.content == prev.content and
                    (block.start_time - prev.end_time).total_seconds() < 1 / 31):
                prev.end_time = block.end_time
                to_remove.add(block)
            else:
                prev = block
        for b in to_remove:
            subtitle.blocks.remove(b)


def _write_srt(subtitle: ParsedSubtitle) -> str:
    parts = []
    if subtitle.pre_content_artifact:
        parts.append(subtitle.pre_content_artifact)
    for block in subtitle.blocks:
        parts.append(f"{block.current_index}\n{block}\n")
    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# ASS/SSA parser
# ---------------------------------------------------------------------------

_ASS_DIALOGUE_RE = re.compile(
    r"^Dialogue\s*:\s*(?P<layer>[^,]*),(?P<start>[^,]*),(?P<end>[^,]*),"
    r"(?P<style>[^,]*),(?P<actor>[^,]*),(?P<ml>[^,]*),(?P<mr>[^,]*),"
    r"(?P<mv>[^,]*),(?P<effect>[^,]*),(?P<text>.*)$",
    re.IGNORECASE,
)
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")
_ASS_DRAWING_RE = re.compile(r"\{[^}]*\\p[1-9]")


def _strip_ass_tags(text: str) -> str:
    if _ASS_DRAWING_RE.search(text):
        return ""
    return _ASS_TAG_RE.sub("", text).replace("\\N", "\n").replace("\\n", "\n").strip()


def _parse_ass(subtitle: ParsedSubtitle, content: str) -> None:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = content.split("\n")
    header_lines: List[str] = []
    in_events = False

    for line in lines:
        stripped = line.strip()
        if stripped.lower() == "[events]":
            in_events = True
            header_lines.append(line)
            continue
        if stripped.startswith("[") and stripped.lower() != "[events]":
            in_events = False

        if not in_events:
            header_lines.append(line)
            continue
        if stripped.lower().startswith("format:"):
            header_lines.append(line)
            continue

        m = _ASS_DIALOGUE_RE.match(stripped)
        if not m:
            header_lines.append(line)
            continue

        raw_text = m.group("text")
        clean_text = _strip_ass_tags(raw_text)
        if not clean_text:
            continue

        try:
            start = time_string_to_timedelta(m.group("start").strip())
            end = time_string_to_timedelta(m.group("end").strip())
        except (ValueError, IndexError):
            header_lines.append(line)
            continue

        idx = len(subtitle.blocks) + 1
        block = SubBlock.__new__(SubBlock)
        block.original_index = idx
        block.current_index = idx
        block.start_time = start
        block.end_time = end
        block.content = clean_text
        block.clean_content = re.sub(r"[\s.,:_-]", "", clean_text)
        block.regex_matches = 0
        block.hints = []
        block._ass_raw_line = line
        block._vtt_raw_lines = None
        subtitle.blocks.append(block)

    subtitle.ass_header = "\n".join(header_lines)


def _write_ass(subtitle: ParsedSubtitle) -> str:
    lines = [subtitle.ass_header, ""]
    for block in subtitle.blocks:
        if block._ass_raw_line:
            lines.append(block._ass_raw_line)
        else:
            t = timedelta_to_ass_string(block.start_time)
            e = timedelta_to_ass_string(block.end_time)
            lines.append(f"Dialogue: 0,{t},{e},Default,,0,0,0,,{block.content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# VTT parser
# ---------------------------------------------------------------------------

_VTT_TS_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})"
    r"\s+-->\s+"
    r"(\d{2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})"
)
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def _parse_vtt(subtitle: ParsedSubtitle, content: str) -> None:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if not content.startswith("WEBVTT"):
        raise ValueError("Not a valid WebVTT file")
    header_end = content.find("\n\n")
    subtitle.vtt_header = content[:header_end] if header_end != -1 else "WEBVTT"
    body = content[header_end:].strip() if header_end != -1 else ""

    for cue in re.split(r"\n{2,}", body):
        cue = cue.strip()
        if not cue:
            continue
        cue_lines = cue.split("\n")
        ts_idx = 0
        if not _VTT_TS_RE.match(cue_lines[0]):
            ts_idx = 1
        if ts_idx >= len(cue_lines):
            continue
        m = _VTT_TS_RE.match(cue_lines[ts_idx])
        if not m:
            continue
        try:
            start = time_string_to_timedelta(m.group(1))
            end = time_string_to_timedelta(m.group(2))
        except (ValueError, IndexError):
            continue

        raw_lines = cue_lines[ts_idx + 1:]
        clean_text = "\n".join(_VTT_TAG_RE.sub("", l) for l in raw_lines).strip()
        if not clean_text:
            continue

        idx = len(subtitle.blocks) + 1
        block = SubBlock.__new__(SubBlock)
        block.original_index = idx
        block.current_index = idx
        block.start_time = start
        block.end_time = end
        block.content = clean_text
        block.clean_content = re.sub(r"[\s.,:_-]", "", clean_text)
        block.regex_matches = 0
        block.hints = []
        block._ass_raw_line = None
        block._vtt_raw_lines = raw_lines
        subtitle.blocks.append(block)


def _write_vtt(subtitle: ParsedSubtitle) -> str:
    parts = [subtitle.vtt_header, ""]
    for i, block in enumerate(subtitle.blocks, 1):
        parts.append(str(i))
        ts = (f"{timedelta_to_srt_string(block.start_time).replace(',', '.')} --> "
              f"{timedelta_to_srt_string(block.end_time).replace(',', '.')}")
        parts.append(ts)
        if block._vtt_raw_lines:
            parts.extend(block._vtt_raw_lines)
        else:
            parts.append(block.content)
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_subtitle(path: Path) -> ParsedSubtitle:
    fmt = detect_format(path)
    if fmt == SubtitleFormat.UNKNOWN:
        raise ValueError(f"Unsupported subtitle format: {path.suffix}")

    # TTML, SAMI, and MicroDVD are parsed via pysubs2 then bridged into our model
    if fmt in (SubtitleFormat.TTML, SubtitleFormat.SAMI, SubtitleFormat.MICRODVD):
        return _load_via_pysubs2(path, fmt)

    content, encoding = _read_file(path)
    subtitle = ParsedSubtitle(path=path, fmt=fmt)
    subtitle.encoding = encoding
    if fmt == SubtitleFormat.SRT:
        _parse_srt(subtitle, content)
    elif fmt in (SubtitleFormat.ASS, SubtitleFormat.SSA):
        _parse_ass(subtitle, content)
    elif fmt == SubtitleFormat.VTT:
        _parse_vtt(subtitle, content)
    return subtitle


def _load_via_pysubs2(path: Path, fmt: SubtitleFormat) -> ParsedSubtitle:
    """Load TTML, SAMI, or MicroDVD via pysubs2 and bridge into SubForge's model."""
    import pysubs2
    ssa = pysubs2.load(str(path))
    subtitle = ParsedSubtitle(path=path, fmt=fmt)
    subtitle.encoding = "utf-8"
    for i, event in enumerate(ssa, 1):
        if event.is_comment:
            continue
        text = event.plaintext.strip()
        if not text:
            continue
        start = datetime.timedelta(milliseconds=event.start)
        end   = datetime.timedelta(milliseconds=event.end)
        block = SubBlock.__new__(SubBlock)
        block.original_index  = i
        block.current_index   = i
        block.start_time      = start
        block.end_time        = end
        block.content         = text
        block.clean_content   = re.sub(r"[\s.,:_-]", "", text)
        block.regex_matches   = 0
        block.hints           = []
        block._ass_raw_line   = None
        block._vtt_raw_lines  = None
        subtitle.blocks.append(block)
    return subtitle


def write_subtitle(subtitle: ParsedSubtitle, dest: Optional[Path] = None) -> None:
    out = dest or subtitle.path
    if subtitle.fmt == SubtitleFormat.SRT:
        content = _write_srt(subtitle)
        out.write_text(content, encoding="utf-8")
    elif subtitle.fmt in (SubtitleFormat.ASS, SubtitleFormat.SSA):
        content = _write_ass(subtitle)
        out.write_text(content, encoding="utf-8")
    elif subtitle.fmt == SubtitleFormat.VTT:
        content = _write_vtt(subtitle)
        out.write_text(content, encoding="utf-8")
    elif subtitle.fmt in (SubtitleFormat.TTML, SubtitleFormat.SAMI, SubtitleFormat.MICRODVD):
        _write_via_pysubs2(subtitle, out)
    else:
        raise ValueError(f"Cannot write format: {subtitle.fmt}")


# ---------------------------------------------------------------------------
# Timing manipulation
# ---------------------------------------------------------------------------

def shift_timestamps(subtitle: ParsedSubtitle, offset_ms: int) -> None:
    """
    Shift every block's start and end time by offset_ms milliseconds (in-place).
    Negative values shift earlier; positive values shift later.
    Blocks whose start time would go below zero are clamped to zero.
    The end time is clamped so it is never less than the (clamped) start time.
    """
    delta = datetime.timedelta(milliseconds=offset_ms)
    zero  = datetime.timedelta(0)
    for block in subtitle.blocks:
        new_start = block.start_time + delta
        new_end   = block.end_time   + delta
        if new_start < zero:
            new_start = zero
        if new_end < new_start:
            new_end = new_start
        block.start_time = new_start
        block.end_time   = new_end
        # Keep _ass_raw_line in sync for ASS/SSA — update inline timing fields.
        if block._ass_raw_line is not None:
            _patch_ass_timestamps(block)


def stretch_timestamps(subtitle: ParsedSubtitle,
                       t1_ms: int, t2_ms: int,
                       new_t1_ms: int, new_t2_ms: int) -> None:
    """
    Linearly scale all timestamps so that what was at t1_ms lands at new_t1_ms
    and what was at t2_ms lands at new_t2_ms (in-place).

    All other timestamps are interpolated proportionally between those two
    anchor points.  Blocks outside the anchor range are extrapolated using the
    same scale factor, which keeps the file internally consistent.

    Use this to correct subtitle drift caused by a framerate mismatch: set t1
    to a timestamp near the start that is currently correct, set t2 to a
    timestamp near the end that you know the subtitle should hit, enter what
    those timestamps should actually be, and SubForge rescales everything in
    between.

    Raises ValueError if the anchor span is zero (t1_ms == t2_ms or
    new_t1_ms == new_t2_ms would produce a degenerate scale).
    """
    span_in  = t2_ms - t1_ms
    span_out = new_t2_ms - new_t1_ms
    if span_in == 0:
        raise ValueError("t1 and t2 must be different timestamps.")
    if span_out == 0:
        raise ValueError("new_t1 and new_t2 must be different timestamps.")

    scale = span_out / span_in
    zero  = datetime.timedelta(0)

    def _remap(ms: float) -> datetime.timedelta:
        remapped = new_t1_ms + (ms - t1_ms) * scale
        result = datetime.timedelta(milliseconds=max(remapped, 0.0))
        return result

    for block in subtitle.blocks:
        orig_start_ms = block.start_time.total_seconds() * 1000
        orig_end_ms   = block.end_time.total_seconds()   * 1000
        new_start = _remap(orig_start_ms)
        new_end   = _remap(orig_end_ms)
        if new_end < new_start:
            new_end = new_start
        block.start_time = new_start
        block.end_time   = new_end
        if block._ass_raw_line is not None:
            _patch_ass_timestamps(block)


def _patch_ass_timestamps(block: "SubBlock") -> None:
    """Rewrite the start/end timestamps in a stored ASS Dialogue line."""
    import re as _re
    line = block._ass_raw_line
    if line is None:
        return
    # ASS Dialogue: Layer, Start, End, ...
    # Replace the 2nd and 3rd comma-delimited fields (Start and End)
    parts = line.split(",")
    if len(parts) < 3:
        return
    parts[1] = timedelta_to_ass_string(block.start_time)
    parts[2] = timedelta_to_ass_string(block.end_time)
    block._ass_raw_line = ",".join(parts)


def _write_via_pysubs2(subtitle: ParsedSubtitle, dest: Path) -> None:
    """Write TTML, SAMI, or MicroDVD via pysubs2."""
    import pysubs2
    ssa = pysubs2.SSAFile()
    for block in subtitle.blocks:
        event = pysubs2.SSAEvent(
            start=int(block.start_time.total_seconds() * 1000),
            end=int(block.end_time.total_seconds() * 1000),
            text=block.content.replace("\n", "\\N"),
        )
        ssa.append(event)
    if subtitle.fmt == SubtitleFormat.TTML:
        fmt_id = "ttml"
    elif subtitle.fmt == SubtitleFormat.MICRODVD:
        fmt_id = "microdvd"
    else:
        fmt_id = "sami"
    ssa.save(str(dest), format_=fmt_id)
