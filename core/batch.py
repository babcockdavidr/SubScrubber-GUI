"""
Batch processing engine.
Scans one or more directories for subtitle files, runs analysis on all of them,
and produces a structured summary report. Designed to feed both the CLI summary
and the GUI batch panel.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .subtitle import (
    ParsedSubtitle, SubtitleFormat, load_subtitle,
    write_subtitle, SUPPORTED_EXTENSIONS,
)
from .cleaner import analyze, clean, generate_report


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FileResult:
    path: Path
    subtitle: Optional[ParsedSubtitle] = None
    ad_count: int = 0
    warning_count: int = 0
    total_blocks: int = 0
    error: str = ""
    saved: bool = False
    cleaning_report: object = None  # CleaningReport if cleaning options were applied

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def clean(self) -> bool:
        return self.ok and self.ad_count == 0 and self.warning_count == 0

    @property
    def status_label(self) -> str:
        if self.error:
            return "ERROR"
        if self.ad_count > 0:
            return "ADS"
        if self.warning_count > 0:
            return "WARN"
        return "CLEAN"


@dataclass
class BatchResult:
    results: List[FileResult] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def errors(self) -> List[FileResult]:
        return [r for r in self.results if r.error]

    @property
    def with_ads(self) -> List[FileResult]:
        return [r for r in self.results if r.ad_count > 0]

    @property
    def with_warnings(self) -> List[FileResult]:
        return [r for r in self.results if r.warning_count > 0 and r.ad_count == 0]

    @property
    def clean(self) -> List[FileResult]:
        return [r for r in self.results if r.clean]

    @property
    def total_ads(self) -> int:
        return sum(r.ad_count for r in self.results)

    @property
    def total_warnings(self) -> int:
        return sum(r.warning_count for r in self.results)

    def summary_text(self, include_clean: bool = False) -> str:
        lines = [
            f"Batch scan complete — {self.total} file(s) in {self.elapsed:.1f}s",
            f"  {len(self.with_ads):>4}  files with ads    ({self.total_ads} blocks total)",
            f"  {len(self.with_warnings):>4}  files with warnings ({self.total_warnings} blocks total)",
            f"  {len(self.clean):>4}  clean files",
            f"  {len(self.errors):>4}  errors",
        ]
        lines.append("")

        if self.with_ads:
            lines.append("── Files with ads ──────────────────────────────────")
            for r in self.with_ads:
                lines.append(f"  [{r.ad_count:>2} ads]  {r.path}")
                if r.subtitle:
                    for b in r.subtitle.blocks:
                        if b.is_ad:
                            lines.append(
                                f"           {b.start}  {b.text[:60]}"
                                + (f"  [{', '.join(b.matched_patterns)}]" if b.matched_patterns else "")
                            )

        if self.with_warnings:
            lines.append("")
            lines.append("── Files with warnings ─────────────────────────────")
            for r in self.with_warnings:
                lines.append(f"  [{r.warning_count:>2} warn] {r.path}")

        if self.errors:
            lines.append("")
            lines.append("── Errors ──────────────────────────────────────────")
            for r in self.errors:
                lines.append(f"  ERROR  {r.path}")
                lines.append(f"         {r.error}")

        if include_clean and self.clean:
            lines.append("")
            lines.append("── Clean files ─────────────────────────────────────")
            for r in self.clean:
                lines.append(f"  [clean] {r.path}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level worker function — must be at module level (not a closure) so
# ProcessPoolExecutor can pickle it for the spawned subprocess on Windows.
# ---------------------------------------------------------------------------

def _scan_file(path: Path):
    """Load and analyze a single subtitle file. Returns a FileResult.
    Called in a subprocess — no Qt objects, no shared state."""
    fr = FileResult(path=path)
    try:
        sub = load_subtitle(path)
        analyze(sub)
        fr.subtitle = sub
        fr.total_blocks = len(sub.blocks)
        fr.ad_count = sum(1 for b in sub.blocks if b.is_ad)
        fr.warning_count = sum(1 for b in sub.blocks if b.is_warning)
    except Exception as e:
        fr.error = str(e)
    return fr


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def collect_files(
    roots: List[Path],
    recursive: bool = True,
    language: str = "",
    extensions: Optional[set] = None,
) -> List[Path]:
    """Walk roots and return all subtitle file paths matching criteria."""
    exts = extensions or SUPPORTED_EXTENSIONS
    found: List[Path] = []

    def _walk(directory: Path):
        for item in sorted(directory.iterdir()):
            if item.name.startswith("."):
                continue
            if item.is_dir() and not item.is_symlink() and recursive:
                _walk(item)
                continue
            if not item.is_file():
                continue
            if item.suffix.lower() not in exts:
                continue
            if language:
                suffixes = item.suffixes
                lang_tags = [
                    s.lstrip(".").split("-")[0].lower()
                    for s in suffixes[max(-3, -len(suffixes)):-1]
                ]
                if language not in lang_tags:
                    continue
            found.append(item)

    for root in roots:
        if root.is_file():
            if root.suffix.lower() in exts:
                found.append(root)
        elif root.is_dir():
            _walk(root)

    return found


def run_batch(
    paths: List[Path],
    progress_cb: Optional[Callable[[int, int, Path], None]] = None,
    remove_warnings: bool = False,
) -> BatchResult:
    """
    Analyze (but do NOT save) all subtitle files.
    progress_cb(current, total, path) is called for each file.
    Returns a BatchResult with all FileResults populated.
    """
    result = BatchResult()
    t0 = time.time()

    for i, path in enumerate(paths):
        if progress_cb:
            progress_cb(i, len(paths), path)

        fr = FileResult(path=path)
        try:
            subtitle = load_subtitle(path)
            analyze(subtitle)
            fr.subtitle = subtitle
            fr.total_blocks = len(subtitle.blocks)
            fr.ad_count = sum(1 for b in subtitle.blocks if b.is_ad)
            fr.warning_count = sum(1 for b in subtitle.blocks if b.is_warning)
        except Exception as e:
            fr.error = str(e)

        result.results.append(fr)

    result.elapsed = time.time() - t0
    return result


def save_batch(
    batch: BatchResult,
    remove_warnings: bool = False,
    dry_run: bool = False,
    progress_cb: Optional[Callable[[int, int, Path], None]] = None,
) -> Dict[Path, str]:
    """
    Write cleaned files for all results that have ads (and optionally warnings).
    Returns a dict of {path: error_message} for any failures; empty = all good.
    """
    to_save = [
        r for r in batch.results
        if r.ok and r.subtitle and (r.ad_count > 0 or (remove_warnings and r.warning_count > 0))
    ]
    errors: Dict[Path, str] = {}

    for i, r in enumerate(to_save):
        if progress_cb:
            progress_cb(i, len(to_save), r.path)

        if dry_run:
            r.saved = False
            continue

        # Apply decisions from subtitle.blocks (is_ad / is_warning flags)
        if remove_warnings:
            r.subtitle.blocks = [
                b for b in r.subtitle.blocks if not b.is_ad and not b.is_warning
            ]
        else:
            r.subtitle.blocks = [b for b in r.subtitle.blocks if not b.is_ad]

        # Re-index
        for idx, b in enumerate(r.subtitle.blocks, 1):
            b.current_index = idx

        try:
            write_subtitle(r.subtitle)
            r.saved = True
        except Exception as e:
            errors[r.path] = str(e)

    return errors
