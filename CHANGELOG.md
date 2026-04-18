# SubForge — Release Notes

## v0.16.0 — Scan Control, Workflow Helpers & Transcribe Redesign

- **"Open in Transcribe →" button** — when a video in the Embedded Subs tab has no subtitle tracks of any kind and no external subtitle file sitting next to it, a new button appears in the detail pane alongside the existing "Open in Image Subs →" button. One click loads the video directly into the Transcribe tab. The button is never shown when any subtitle track or external file is present, to avoid directing the user to transcribe something that already has subs.
- **Subtitle warning banner on Transcribe tab** — whenever a video is loaded into the Transcribe tab (via drop, Browse, or the new handoff button), SubForge probes it in the background for existing embedded and external subtitle tracks. If any are found, an orange warning banner appears naming exactly what was detected (e.g. "28 embedded text tracks, 1 image-based track, external subtitle file(s)") so the user can make an informed decision before transcribing.
- **Clearer status for videos with external subtitles** — in the Embedded Subs tab, videos that have no embedded tracks but do have an external subtitle file sitting next to them now show "no embedded subtitle tracks — external subtitle file(s) detected" in both the tree label and the detail pane, instead of the generic "no subtitle tracks found." The label and "Open in Transcribe →" button only appear together on videos that truly have nothing.
- **Transcribe tab redesigned** — the Options panel that occupied the entire left half of the screen for a single checkbox has been removed. The Transcription Results table now spans the full width of the tab. All controls (SDH mode, Keep backup, Save as .srt, Remux into video) are in a compact horizontal bar at the bottom of the tab. The SDH accessibility warning is now a tooltip on the checkbox rather than an inline label.
- **14 language packs updated** — all new strings for this release are fully translated across all 14 supported interface languages.

---

## v0.15.0 — Performance, Rename & Polish

- **App startup dramatically faster** — the app previously took up to 10 seconds to open. The culprit was importing `faster-whisper` (and its `ctranslate2` + `transformers` dependencies) synchronously at startup. The check is now deferred to a background thread with a cached result. Startup is near-instant from both source and the frozen executable.
- **Batch scanning ~3.5x faster** — replaced `ThreadPoolExecutor` (GIL-bound for CPU work) with `ProcessPoolExecutor`, so subtitle files are parsed and analyzed in true parallel across up to 4 subprocesses. 200 files now complete in ~11 seconds instead of ~39 seconds.
- **Embedded Subs scanning ~5x faster** — three compounding improvements: tool path resolution is now cached (previously called `shutil.which` once per track from multiple threads); file-level concurrency raised from 2 to 4; work submission changed from bulk to bounded incremental, preventing throughput collapse mid-scan. 101 files now complete in ~1:14 instead of ~6:05.
- **Scan elapsed timer** — a timer appears in the status bar whenever a Batch or Embedded Subs scan is running, showing elapsed time in m:ss format. Stays visible for 5 seconds after the scan completes.
- **"Video Scan" tab renamed to "Embedded Subs"** — the tab label is updated in all 14 supported languages. Internal code names are unchanged.
- **Inline editing — Embedded Subs tab** — after scanning, clicking a text track switches the detail pane to an editable table showing every subtitle block. Double-click any text cell to correct it. Edits apply immediately — Save as .srt and Clean & Remux both use the corrected output.
- **Inline editing — Image Subs tab** — the same editable table appears as soon as OCR completes on a track. Especially useful since OCR output is imperfect by nature.
- **Track deletion before remux** — every track row in the Embedded Subs tree now has an inline ✕ button. Click it to mark that track for permanent removal from the video on the next remux. The Clean & Remux button shows a count when multiple videos are involved (e.g. "Clean & Remux (4)"). Works alongside cleaning — you can clean some tracks and delete others in the same operation.
- **About tab tagline updated** — now reads "Clean, scan, and create subtitle files — all in one place, all on your machine." Updated in all 14 languages.
- **CLI cleaned up** — `python subforge.py --help` is now documented as the CLI entry point. The stale `--gui` flag is removed from examples. A note explains which features are GUI-only.
- **README updated** — all "Video Scan" references updated to "Embedded Subs" throughout. CLI reference corrected.

---

## v0.14.0 — Performance & Polish

- **OCR pipeline performance** — Image Subs scanning is significantly faster. The brightness heuristic in preprocessing now samples 500 random pixels instead of materializing the entire pixel array. The PGS RLE decoder was rewritten using a pre-allocated `bytearray` with a write cursor, eliminating per-pixel Python object overhead. The palette lookup in `build_image()` was replaced with a NumPy vectorized LUT operation. Both the PGS and VOBSUB OCR loops now run in a `ThreadPoolExecutor` (up to 4 workers), and the panel's frame progress signal is throttled to at most one emission per 100ms to prevent UI jank on high frame-count tracks.
- **Parallel subtitle scanning** — Batch processing and Video Scan now run in thread pools. Batch files are scanned up to 4 at a time. Within Video Scan, all text tracks in a single video are extracted in parallel (up to 4 concurrent ffmpeg processes), and multiple video files are processed 2 at a time to avoid over-saturating disk I/O.
- **Settings cache** — `settings.json` was previously read from disk and JSON-parsed on every call to resolve tool paths (ffmpeg, ffprobe, mkvmerge, Tesseract). This happened once per subtitle track, from multiple threads simultaneously. A shared in-memory cache in `core/paths.py` now reads the file once and serves all subsequent requests from memory, invalidating only on write.
- **Tesseract OCR character corrections** — a post-processing step corrects common Tesseract misreads in subtitle OCR output. Music note substitutions corrected: `~`, `¢`, `£`, `#`, `Py`, `JJ`, `fF`, `ff`, `IS`, `Ss`, `J`, `f`, and `I` at line end are all mapped back to ♪ in the appropriate context. Dialogue character fixes: `|` used as capital `I`, `[` before lowercase (e.g. `['m` → `I'm`), and `/` before lowercase (e.g. `/ma` → `I'ma`) are all corrected.

---

## v0.13.0 — Stability, Scan Control & Tooltip Audit

- **Stop Scan button** — Batch and Video Scan both now have a Stop Scan button that appears during an active scan. Clicking it stops the scan immediately and preserves all results collected so far — nothing is lost and no files are corrupted. The Clear button was never designed for this, so Stop Scan fills the gap properly.
- **Status bar unification** — the status bar at the bottom of the window now reflects the active tab at all times. Previously it only updated on the Single File tab; Batch, Video Scan, Image Subs, and Transcribe all managed their own internal status labels. Now switching tabs syncs the bar to that tab's last message, and all activity updates it live.
- **Image Subs sensitivity slider now recolors all tracks** — moving the slider previously updated the detail pane for the selected track but left all other track colors in the tree stale. All scanned tracks now recolor correctly at the new threshold when the slider moves.
- **Language change dialog button translation** — the Yes/No buttons in the restart prompt after changing language were always in the OS language, regardless of what language you had just selected. The dialog now uses SubForge's own translated button labels, so the prompt appears correctly in the newly selected language.
- **Tooltip audit** — every button in the app now has a tooltip. All tooltip text goes through the translation system and is available in all 14 supported languages.
- **Startup crash fix (faster-whisper)** — SubForge would crash on launch when faster-whisper was installed, because the `transformers` library it depends on tries to access `sys.stderr` at import time, which is `None` in a windowed application. The availability check now temporarily stubs out the null streams before importing so the check completes cleanly.
- **14 language packs updated** — all new strings for this release are fully translated.

---

## v0.12.0 — Inline Editing & Diagnostics

- **Transcribe tab: inline editing** — after transcription completes, all subtitle blocks are displayed in a full editable table (index, timestamp, text). Click any text cell to correct it. Edits sync immediately to the subtitle data — Save as .srt and Remux both use the corrected output, not the raw Whisper result.
- **Error log viewer** — "View Error Log" button in Settings > About opens a scrollable dialog showing every error SubForge has logged. Each entry includes the originating tab, a UTC timestamp, and the full traceback. A "Clear Log" button lets you reset it.
- **Unified error logging** — all error catch sites across the app now append to a single persistent log (`subforge_errors.log`) instead of overwriting it. Multiple errors in a session accumulate rather than replacing each other.
- **Log path** — installer mode: `%APPDATA%\SubForge\subforge_errors.log`. Source mode: `<repo_root>/subforge_errors.log`. Same path logic as all other SubForge user data.
- **14 language packs updated** — all new strings for both features are fully translated.

---

## v0.11.0 — Whisper Audio Transcription

- **Transcribe tab** — a dedicated tab for generating subtitle files directly from a video's audio track using faster-whisper AI. Runs fully offline on your own machine — no cloud, no API keys, no internet required after model download.
- **Model selection** — choose from tiny, base, small, medium, or large Whisper models. Plain-language speed vs. accuracy descriptions are shown for each. Models you've already downloaded are marked with ✓.
- **Language selection** — auto-detect the spoken language, or manually specify any of 19 supported languages from the dropdown.
- **SDH mode** — when enabled, non-speech audio annotations such as `[Music]`, `[Laughs]`, and `[Applause]` are included in the transcription output. When disabled, they are stripped.
- **Save as .srt** — write the transcribed output as a standalone `.srt` file next to the video, following the same `[stem].[lang].srt` naming convention as Video Scan.
- **Remux into video** — add the transcribed subtitle track to an MKV (via mkvmerge) or MP4 (via ffmpeg) file alongside all existing tracks.
- **Settings > Paths** — a new Whisper model directory entry lets you control where downloaded models are stored. Leave blank to use the default SubForge data directory.
- **GPU acceleration** — SubForge automatically uses CUDA float16 if a compatible NVIDIA GPU and torch are available, falling back to CPU int8 otherwise.
- **14 language packs updated** — all new Transcribe tab strings are fully translated across all 14 supported interface languages.

---

## v0.10.0 — Image Subs

- **Image Subs tab** — a dedicated tab for scanning PGS (Blu-ray) and VOBSUB (DVD) image-based subtitle tracks using Tesseract OCR. The same ad-detection engine used on text tracks runs on the OCR output, closing the last remaining gap in video subtitle coverage.
- **Tesseract OCR integration** — SubForge extracts one bitmap per subtitle event, runs Tesseract on each frame, assembles the result into a proper subtitle, and feeds it through the detection engine unchanged.
- **Save as .srt** — OCR'd subtitles can be saved as standalone `.srt` files next to the video, following the same `[stem].[lang].srt` naming convention as Video Scan.
- **Remux into video** — OCR'd text tracks can be remuxed back into MKV or MP4 files, either replacing the original image track or kept alongside it on MKV (user's choice via checkbox).
- **Sensitivity slider** — Image Subs has its own sensitivity slider that auto-refreshes the detail pane, respecting your default from Settings.
- **Open in Image Subs** — Video Scan now shows an "Open in Image Subs →" button in the detail pane whenever a video has image tracks, handing the file off directly.
- **Settings > Paths expanded** — ffmpeg, ffprobe, and Tesseract now each have their own path entry in Settings > Paths. All four tools show live found/not-found status.
- **First-run wizard updated** — Tesseract now appears alongside FFmpeg and MKVToolNix, with a language selector right in the wizard that restarts the app to apply immediately.
- **What's New in Settings** — a new button in Settings > About opens a scrollable release notes dialog reading from the bundled `CHANGELOG.md`.
- **System language auto-detection** — on first launch, SubForge detects the OS locale and automatically selects the matching language pack, falling back to English.
- **Translation fixes** — Settings Save/Cancel buttons and all five sensitivity slider labels are now fully translated across all 14 language packs.

---

## v0.9.0 — Packaging & Distribution

- **Standalone executable** — SubForge now ships as a double-clickable Windows installer. No Python installation required. macOS and Linux binaries are planned for a future release.
- **Windows installer** — a proper installer puts SubForge in Program Files, creates a Start Menu shortcut, and includes an uninstaller. Optional file associations for `.srt`, `.ass`, and `.vtt`.
- **GitHub Actions** — every tagged release automatically builds the Windows installer and attaches it to the GitHub release. No manual uploads needed.
- **First-run setup wizard** — on first launch, SubForge checks for FFmpeg and MKVToolNix, shows a green/red status for each, and provides download links for anything missing.
- **Session memory** — SubForge now remembers your last Batch folder, last Video Scan folder, and window size and position across restarts.
- **14 language packs** — the UI is now available in English, Spanish, Dutch, Hebrew, Indonesian, Portuguese, Swedish, French, Arabic, Chinese, Hindi, Russian, Turkish, and Polish. Select your language in Settings > General. (These are AI generated translations and should be context specific, but if you are using a language other than English and see a button with a bad translation, please let me know!)
- **HTML report strings** — all text in the Batch and Video Scan detail reports is now fully translatable and covered by all 14 language packs.

---

## v0.8.0 — Settings Expansion & Polish

- **App renamed to SubForge** — the app is now SubForge. Entry point is `subforge.py`, GitHub repository is `babcockdavidr/SubForge`, and all internal references are updated.
- **Settings dialog expanded** — the Settings dialog now has four tabs: General, Cleaning Options, Paths, and About.
- **General tab** — set your default sensitivity level once and it applies across Single File, Batch, and Video Scan on every launch. Changing it in Settings updates all three sliders immediately.
- **Language support** — SubForge now ships in English and Spanish. Select your language in Settings > General. A one-click restart prompt applies the change.
- **About tab** — version number, creator credit, GitHub link, MIT license, and a Report an Issue button that opens GitHub Issues directly.
- **String extraction** — all user-facing strings live in `gui/strings.py`. Adding a new language requires only a new dictionary in that file. Missing translation keys fall back to English automatically, with a visible placeholder if the key is missing from English too.
- **Column sort on Batch** — the scanned files list is now a proper table with File, Ads, Opts, and Warns columns. Click any column header to sort. Numeric columns sort numerically.
- **Threshold labels unified** — sensitivity labels are now identical across all three tabs. The old `rm≥N` annotations and TV/Movies recommendations are gone.
- **Updater improved** — the Check for Updates error dialog now distinguishes between a network failure and a 404 (no releases published yet), with a cleaner message for each.

---

## v0.7.0 — Subtitle Cleaning Options

- **Global Cleaning Options** — a new Settings dialog (⚙ Settings in the toolbar) provides content cleaning options that apply across Single File, Batch, and Video Scan. Options include removing music cues, SDH annotations, speaker labels, formatting tags, bracket content, case normalization, and duplicate cue merging. All options are off by default.
- **SDH accessibility warning** — the SDH annotation removal option carries a visible warning in Settings, as removing sound descriptions reduces accessibility for deaf and hard of hearing viewers. It is never a default.
- **CLEAN OPT indicators** — blocks that will be removed by cleaning options appear in blue throughout the interface: `✕ OPT` in the Single File block list, `CLEAN OPT` with a blue border in Batch and Video Scan reports, and blue file/track labels in the left panels.
- **Opts count in status bar** — the bottom bar now shows ads, warnings, and opts counts separately so you always know what will be touched before saving.
- **Track title normalization** — during any remux operation (MKV or MP4), embedded subtitle track titles are automatically normalized to the clean language name. "English - Encoded by Jackass" becomes "English". No option, always applied.
- **Global Settings dialog** — mkvmerge path has moved from the Video Scan tab into Settings > Paths. The Video Scan tab no longer has its own Settings button.
- **Cleaning actions in reports** — after a clean & save, the FILE REPORT in Single File and the detail pane in Batch show a summary of what cleaning options removed or modified, separate from the ad detection report.

---

## v0.6.0 — Interface Overhaul

**Single File tab**
Review and Report have been merged into a single tab. The file report now lives in a pane below the block detail — no more switching tabs to see why something was flagged. Controls that only apply to single file work (Dry run, Remove warnings, Open Folder) have been moved inside this tab where they belong and no longer bleed into Batch, Video Scan, or Regex Editor.

**Sensitivity slider in Single File**
The same 1–5 slider that Batch and Video Scan already had. Re-colors the block list instantly without rescanning.

**Layout stability**
The file queue now lives inside the Single File tab. Switching to any other tab gives it the full window width — no more layout shifting when you change tabs.

**File queue simplified**
The queue now shows filenames with color only (red/orange/green). The old count badges like `[2✕]` were computed at scan time and never updated when you moved the slider, so they were showing you stale information. Color is enough.

**Batch improvements**
- Show Full Report button restores the full batch summary after you've drilled into an individual file
- Open in Review Tab button correctly renamed to Open in Single File Tab

**Video Scan improvements**
- Selected folder path now displays next to the controls, matching Batch behavior
- MKVToolNix notice corrected — it previously said Clean & Remux was unavailable without mkvmerge, which is wrong. MP4 and M4V files remux via FFmpeg and don't need MKVToolNix at all

**Extract & Save filename format**
Extracted subtitle files now save as `[video filename].[language].[ext]` — for example `A Widow's Game (2025).eng.srt`. SDH tracks are detected automatically from the track title and saved as `Movie.eng.sdh.srt`.

**Visual fixes**
- Toolbar gap after SUBSCRUBBER label removed
- Button heights are now consistent across all tabs
- Sensitivity slider on Single File matches the layout style of Batch and Video Scan

---

## v0.5.0 — MP4 Remux

- **MP4 and M4V remuxing** — Clean & Remux now works on MP4 and M4V files using ffmpeg, with no additional dependencies beyond what Video Scan already requires. Backup files are created as `.backup.mp4` by default.
- **Check for Updates** — opt-in update check button in the status bar. Compares the current version against the latest GitHub release tag and opens the releases page in your browser if an update is available. Never runs automatically.
- **Semantic versioning** — version numbers now follow standard `v0.x.0` format for clear, predictable release tracking.
- **pysubs2 added to requirements** — explicitly listed as a required dependency.

---

## v0.4.0 — MKVToolNix Integration

- **MKV Clean & Remux** via mkvmerge.
- **Sensitivity slider** added to Video Scan.
- **HTML detail reports** in Video Scan and Batch.