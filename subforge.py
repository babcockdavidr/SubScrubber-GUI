#!/usr/bin/env python3
"""
SubForge CLI
Removes ads and watermarks from subtitle files (.srt, .ass, .ssa, .vtt).
Also scans subtitles embedded inside video files (requires ffprobe/ffmpeg).

Usage:
    subscrubber file.en.srt
    subscrubber file.en.ass --dry-run
    subscrubber /folder/of/subs -r
    subscrubber /folder/of/subs -r --report-only        # scan only, print report
    subscrubber movie.mkv --scan-video                  # probe embedded subs
    subscrubber /movies/ -r --scan-video                # scan a whole library
    subscrubber file.srt --gui                          # launch GUI pre-loaded
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import (
    load_subtitle, write_subtitle, clean, generate_report,
    SUPPORTED_EXTENSIONS, VIDEO_EXTENSIONS,
    collect_files, run_batch, save_batch,
    collect_video_files, scan_video,
    ffprobe_available, ffmpeg_available,
)


# ---------------------------------------------------------------------------
# Single-file helper
# ---------------------------------------------------------------------------

def process_file(path: Path, dry_run: bool, silent: bool,
                 remove_warnings: bool) -> bool:
    try:
        subtitle = load_subtitle(path)
    except Exception as e:
        print(f"  ERROR loading {path.name}: {e}", file=sys.stderr)
        return False

    subtitle, removed = clean(subtitle, dry_run=dry_run,
                              remove_warnings=remove_warnings)

    if not silent:
        print(generate_report(subtitle))
        if dry_run:
            print("  [DRY RUN - no files written]")

    if not dry_run and removed > 0:
        write_subtitle(subtitle)
        if not silent:
            print(f"  Written: {path}")

    return True


# ---------------------------------------------------------------------------
# Batch subtitle cleaning (Phase 3)
# ---------------------------------------------------------------------------

def cmd_batch(args) -> int:
    roots = args.paths
    paths = collect_files(
        roots,
        recursive=args.recursive,
        language=args.language or "",
    )

    if not paths:
        print("No subtitle files found.")
        return 1

    print(f"Found {len(paths)} subtitle file(s). Scanning...\n")

    def progress(i, total, path):
        if not args.silent:
            bar_w = 30
            filled = int(bar_w * i / max(total, 1))
            bar = "=" * filled + "-" * (bar_w - filled)
            print(f"\r  [{bar}] {i}/{total}  {path.name[:40]:<40}", end="", flush=True)

    result = run_batch(paths, progress_cb=progress, remove_warnings=args.remove_warnings)
    print()

    print(result.summary_text(include_clean=args.verbose))

    if args.report_only or args.dry_run:
        if args.dry_run:
            print("\n[DRY RUN - no files written]")
        return 0

    files_to_save = result.with_ads[:]
    if args.remove_warnings:
        files_to_save.extend(result.with_warnings)

    if not files_to_save:
        print("\nNo files need cleaning.")
        return 0

    if not args.yes:
        try:
            answer = input(f"\nSave {len(files_to_save)} cleaned file(s)? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if answer.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 1

    print("Saving...")
    errors = save_batch(result, remove_warnings=args.remove_warnings)

    if errors:
        for p, e in errors.items():
            print(f"  ERROR saving {p.name}: {e}", file=sys.stderr)
        saved = sum(1 for r in result.results if r.saved)
        print(f"Saved {saved}/{len(files_to_save)} file(s). {len(errors)} error(s).")
        return 1

    saved = sum(1 for r in result.results if r.saved)
    print(f"Done. {saved} file(s) cleaned and saved.")
    return 0


# ---------------------------------------------------------------------------
# Video embedded subtitle scanning (Phase 4)
# ---------------------------------------------------------------------------

def cmd_scan_video(args) -> int:
    if not ffprobe_available():
        print("ERROR: ffprobe not found. Install FFmpeg and ensure it's on PATH.",
              file=sys.stderr)
        return 1
    if not ffmpeg_available():
        print("WARNING: ffmpeg not found - track extraction will fail.",
              file=sys.stderr)

    roots = args.paths
    video_paths = collect_video_files(roots, recursive=args.recursive)

    if not video_paths:
        print("No video files found.")
        return 1

    print(f"Found {len(video_paths)} video file(s). Probing...\n")

    total_ads = 0
    any_error = False

    for i, vpath in enumerate(video_paths, 1):
        print(f"[{i}/{len(video_paths)}] {vpath.name}")
        result = scan_video(vpath)

        if result.error:
            print(f"  ERROR: {result.error}")
            any_error = True
            continue

        if not result.tracks:
            print("  No subtitle tracks found.")
            continue

        for line in result.summary_lines():
            print(line)

        file_ads = sum(t.ad_count for t in result.tracks)
        total_ads += file_ads
        print()

    print("=" * 60)
    print(f"Scan complete - {len(video_paths)} video(s), {total_ads} ad block(s) found.")
    if total_ads > 0:
        print("Note: to clean embedded subs, extract them first with ffmpeg,")
        print("      run subscrubber on the extracted file, then remux with mkvmerge.")

    return 1 if any_error else 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Required for ProcessPoolExecutor to work correctly in a PyInstaller
    # frozen executable on Windows. Must be called before any process is spawned.
    import multiprocessing
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(
        prog="subforge",
        description="SubForge — Clean, scan, and create subtitle files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
GUI:
  python subforge.py                          Launch the GUI (default, no flags needed)
  python subforge.py movie.en.srt            Launch GUI with file pre-loaded

CLI — subtitle cleaning:
  python subforge.py movie.en.srt            Clean a single subtitle file
  python subforge.py movie.en.srt --dry-run  Detect only, do not write
  python subforge.py /shows/ -r              Recursive folder clean
  python subforge.py /shows/ -r --report-only  Scan and report, do not clean

CLI — embedded subtitle scanning (requires ffprobe):
  python subforge.py movie.mkv --scan-video  Probe embedded subtitle tracks
  python subforge.py /movies/ -r --scan-video  Scan a whole library

Note: GUI-only features (Image Subs, Transcribe) are not available via CLI
as they require Tesseract OCR and Whisper respectively.
""",
    )

    parser.add_argument("paths", nargs="*", type=Path,
                        help="Subtitle or video file(s) / folder(s)")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Detect ads but do not write changes")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Recurse into subdirectories")
    parser.add_argument("-s", "--silent", action="store_true",
                        help="Suppress all output except errors")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Also list clean files in batch report")
    parser.add_argument("-l", "--language",
                        help="Only process files with this language tag (e.g. en)")
    parser.add_argument("-w", "--remove-warnings", action="store_true",
                        help="Also remove uncertain/warning-level blocks")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Skip confirmation prompt in batch mode")
    parser.add_argument("--report-only", action="store_true",
                        help="Scan and print report but do not write any files")
    parser.add_argument("--scan-video", action="store_true",
                        help="Probe embedded subtitle tracks in video files (requires ffprobe)")
    parser.add_argument("--gui", action="store_true",
                        help="Launch the GUI (pre-loads given paths if any)")

    args = parser.parse_args()

    if not args.paths and not args.gui:
        # No arguments — launch GUI (normal double-click behaviour)
        args.gui = True

    if args.gui:
        from gui.settings_dialog import load_language, detect_and_save_language
        from gui.strings import set_language
        detect_and_save_language()
        set_language(load_language())
        from gui.app import launch_gui
        launch_gui(preload=list(args.paths))
        return

    for p in args.paths:
        if not p.exists():
            print(f"ERROR: path not found: {p}", file=sys.stderr)
            sys.exit(1)

    if args.scan_video:
        sys.exit(cmd_scan_video(args))

    single_files = [p for p in args.paths if p.is_file()
                    and p.suffix.lower() in SUPPORTED_EXTENSIONS]
    dirs_or_mixed = [p for p in args.paths
                     if p.is_dir() or p.suffix.lower() not in SUPPORTED_EXTENSIONS]

    if single_files and not dirs_or_mixed and not args.report_only:
        total_ok = total_fail = 0
        for p in single_files:
            if not args.silent:
                print(f"\n{'─'*60}\nProcessing: {p.name}")
            ok = process_file(p, args.dry_run, args.silent, args.remove_warnings)
            if ok:
                total_ok += 1
            else:
                total_fail += 1
        if not args.silent:
            print(f"\n{'='*60}")
            print(f"Done. {total_ok} file(s) cleaned."
                  if total_fail == 0
                  else f"Done. {total_ok} succeeded, {total_fail} failed.")
        sys.exit(0 if total_fail == 0 else 1)

    sys.exit(cmd_batch(args))


if __name__ == "__main__":
    main()
