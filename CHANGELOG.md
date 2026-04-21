# SubForge — Release Notes

## v1.1.0 — Find & Replace, Audio Sync & Auto-Update

- **Undo / Redo** — every block state change in the Single File tab (Mark as Ad, Keep Block) is pushed onto a `QUndoStack`. Find & Replace edits are also tracked individually. **Ctrl+Z** undoes the last action; **Ctrl+Y** redoes it. The stack is cleared when a new file is loaded. The status bar reports `"Undone: <action>"` / `"Redone: <action>"` after each operation. Implemented as a `BlockStateCommand` and `TextEditCommand` class pair, both subclassing `QUndoCommand`, holding weakrefs to the affected `BlockRow` to avoid preventing garbage collection when the block list is cleared.

- **Find & Replace** — new **Find & Replace…** button in the Single File action bar (**Ctrl+H**). Opens a modeless `QDialog` (stays open while you work). Fields: Find, Replace, Regex checkbox, Match case checkbox. Status label shows live match count as you type, then "Match 2 of 7" feedback as you step through. Matching blocks are highlighted with a blue tint in the block list. **Find Next** steps through matches with wrap-around. **Replace** replaces the current match, pushes a `TextEditCommand` onto the undo stack, and advances. **Replace All** replaces every match in a single pass, pushing one command per replacement, and reports the total count. Highlights cleared on dialog close and on file load.

- **Sync to Audio (Single File)** — new **Sync to Audio…** button in the Single File action bar. Runs [ffsubsync](https://github.com/smacke/ffsubsync) in a background `QThread` (`AudioSyncWorker`) to align subtitle timestamps to the audio track of a paired video file. The video is auto-detected by scanning for a matching filename stem + any supported video extension in the same directory; if none is found a file picker opens. Output is written as `filename.synced.srt` — the original is never modified. SubForge offers to load the synced result immediately on completion. The button is hidden (not just disabled) when ffsubsync is not installed — checked once at import time via `FFSUBSYNC_AVAILABLE`. Console windows suppressed on Windows via `CREATE_NO_WINDOW`.

- **Sync to Audio (Embedded Subs)** — **Sync to Audio…** button also appears in the Embedded Subs detail pane when a text track is selected and ffsubsync is installed. The scanned subtitle is written to a temp `.srt` in the system temp directory, synced against the parent video, and the result reported. Hidden at video-row level and on clear.

- **In-app auto-update (BETA)** — when **Check for Updates** detects a newer release, SubForge now opens an `UpdateAvailableDialog` showing the version, release name, and up to 1200 characters of the GitHub release body. The full release data (including assets and the SHA-256 digest GitHub publishes alongside each asset) is fetched from the GitHub Releases API in a second request after version detection. On Windows, a **Download & Install** button streams the installer via `DownloadWorker(QThread)` with a live `QProgressBar`. On completion, `verify_sha256()` hashes the local file and compares it against the `digest` field from the GitHub asset metadata — no separate `.sha256` file upload required; GitHub provides the digest inline. A mismatch deletes the download and shows an error. On success, `launch_installer_and_exit()` launches the Inno Setup installer with `/SILENT /CLOSEAPPLICATIONS` as a detached process and calls `QApplication.quit()`. On non-Windows platforms only the browser fallback is offered. If no installer asset is found in the release, or if the digest is absent, an orange warning is shown before download. The dialog blocks its own close event while a download is in progress. Marked BETA — full end-to-end testing requires a live GitHub release with the installer asset attached.

- **14 language packs updated** — all new strings for this release (undo/redo labels, Find & Replace dialog, audio sync dialogs, and auto-update dialog) are fully translated across all 14 supported interface languages: English, Spanish, Dutch, Hebrew, Indonesian, Portuguese, Swedish, French, Arabic, Chinese, Hindi, Russian, Turkish, and Polish.

---

## v1.0.1 — Scheduled Scanning & Timing Tools

- **Shift Timestamps** — new **Shift Timestamps…** button in the Single File action bar. Offsets every subtitle block by a fixed number of milliseconds (positive = later, negative = earlier). The offset is always applied relative to the original timestamps — so entering 0 restores the file to its original timing, and reopening the dialog on the same file retains the last value you entered. Live before/after preview reads from the originals so it stays accurate even after a prior shift. Non-destructive until you click Clean & Save.
- **Stretch Timing** — companion **Stretch Timing…** button in the Single File action bar. Corrects progressive subtitle drift caused by a framerate mismatch. Provide two anchor points (a timestamp near the start and one near the end); for each enter where the subtitle currently lands and where it should land. SubForge linearly rescales all timestamps between them. Live preview shows the before/after for the first and last blocks. Non-destructive until you click Clean & Save.
- **Watch Folders** — new **Watch Folders** tab in Settings. Add any number of folders across any drives for SubForge to monitor continuously while running. Any new subtitle file that appears is automatically cleaned in the background using the current global cleaning options and default sensitivity. Uses OS-level `QFileSystemWatcher` — no polling, zero idle overhead. Fully recursive: top-level folders and all subdirectories are registered, and new subdirectories are auto-added as they appear. New files are processed only after their size has been stable for two consecutive checks (handles Windows Explorer copy locks). When adding a folder that already contains subtitle files, a warning dialog shows the file count and current sensitivity and requires explicit confirmation before cleaning. Watch folder errors are written to the error log as well as shown in the status bar. A badge in the status bar shows the active folder count. Persists in `settings.json`.
- **Scheduled Scanning** — new **Scheduler** tab in Settings. Configure folders to scan automatically on a flexible schedule: every X minutes, every X hours, or every X days at a specific HH:MM wall-clock time. Enter any number you want — no fixed presets. On startup, any overdue schedules run immediately. Scans run in background threads and are deferred while a manual Batch or Embedded Subs scan is in progress. Each job's last-run timestamp is saved the moment it starts, so a crash during a scan will not cause it to re-run on the next launch. Results reported in the status bar. Persists in `settings.json`. Legacy schedules configured in earlier builds ("hourly"/"nightly"/"weekly") migrate automatically.
- **Settings dialog button hover states** — all buttons in the Settings dialog now respond to mouse hover and press with the same visual feedback as the rest of the app. Inline `setStyleSheet` calls were blocking the global app stylesheet from applying `:hover` and `:pressed` states. All button styles now flow from the global stylesheet. The Save button uses the accent blue style; the "I Understand" warning confirmation button uses an orange style. `QRadioButton` stylesheet added to the global app stylesheet — it was missing entirely, causing the selected state to be nearly invisible on dark backgrounds.
- **App icon — desktop and Start Menu fix** — the Windows installer now explicitly installs `subforge.ico` into the application directory via the `[Files]` section and references it directly via `IconFilename` in both the Start Menu and desktop shortcuts. The PyInstaller spec was also updated to include `subforge.ico` in `datas` so the runtime icon lookup finds it in `sys._MEIPASS`. Both fixes together ensure the correct ICO is used at every level regardless of Windows icon cache state.
- **14 language packs updated** — all new strings for this release are fully translated across all 14 supported interface languages.

---

## v1.0.0 — Accessibility, Themes & Release

- **Light, High Contrast, and AMOLED Black themes** — three new visual themes alongside the original dark theme. The theme selector lives in Settings > General and in the first-run setup wizard. Theme takes effect on restart and is stored in `settings.json`.
- **Font size setting** — Small (9pt), Medium (11pt), and Large (14pt) options in Settings > General. Scales all UI text globally via `QApplication.setFont` and per-widget stylesheet substitution. HTML report panels in the Batch, Image Subs, and Transcribe tabs scale via dynamic CSS `px` values. Drop zones expand proportionally at larger sizes.
- **Keep Backup on Convert tab** — the Convert Format tab now has a Keep backup checkbox for both single-file and batch modes, matching the behaviour of every other tab.
- **Keyboard navigation** — full `setTabOrder()` chains added to every panel and the Settings dialog. Every interactive element is reachable and operable without a mouse. Sliders respond to arrow keys; checkboxes and buttons to Space/Enter.
- **Screen reader support** — `setAccessibleName()` and `setAccessibleDescription()` added to all sliders, progress bars, list/tree/table widgets, format combos, model/language combos, and icon-only buttons (the ✕ delete buttons in Embedded Subs). Compatible with Windows Narrator.
- **Theme and font size selectors in setup wizard** — both options are available on first launch before the main window opens, with the same immediate-restart behaviour as the language selector.
- **Open data folder** — new button in Settings > About that opens the directory holding `settings.json`, logs, and the Whisper model cache in the system file manager. Uses `QDesktopServices.openUrl` — no subprocess, cross-platform.
- **App icon** — SubForge now ships with `subforge.ico`. The icon appears in the toolbar (24×24), the window title bar, taskbar, and Start Menu shortcut. Bundled with the frozen exe via PyInstaller datas.
- **Experimental banners removed** — the yellow "under active development" banners on the Transcribe and Image Subs tabs have been removed. Both features have been stable for several releases.
- **14 language packs updated** — all new strings for this release are fully translated across all 14 supported interface languages.

---

## v0.17.0 — Subtitle Format Conversion & Expanded Format Support

- **Convert Format tab** — a new dedicated tab for converting subtitle files between formats. Single-file mode: drop a file or click Browse, pick an output format from the dropdown, click Convert. The output is written next to the source file using the same stem and the new extension. Batch mode: point at a folder, choose a target format, and Convert All — SubForge processes every supported subtitle file in the folder and reports how many were converted, skipped, and failed. Both modes run in background threads so the UI stays responsive.
- **Lossy conversion warnings** — when a conversion path is known to degrade the output, SubForge shows an orange warning inline before you convert. ASS/SSA → any other format loses styling (colours, fonts, positioning). TTML and SAMI inputs carry a basic-parser advisory. MicroDVD always shows a framerate advisory (see below). Warnings appear automatically when you select a file or change the target format; they never block the conversion.
- **Seven supported formats everywhere** — SubForge now reads and writes SRT, ASS, SSA, WebVTT, TTML, SAMI, and MicroDVD across all tabs. Single File, Batch, and the Convert Format tab all accept `.srt`, `.ass`, `.ssa`, `.vtt`, `.ttml`, `.sami`, `.smi`, and `.sub`. The file picker filters, drop zones, and folder scanners all reflect the expanded list. TTML, SAMI, and MicroDVD are handled via pysubs2; the existing native parsers cover SRT, ASS/SSA, and VTT.
- **MicroDVD (.sub) support** — MicroDVD uses frame numbers instead of timestamps, so correct timing depends on knowing the source framerate. pysubs2 reads the framerate from the first line of the file when it is present (standard practice for well-formed `.sub` files) and falls back to 23.976 fps otherwise. An advisory is always shown whenever `.sub` is involved in a conversion so you know to verify timing if the source framerate is non-standard.
- **Transcribe tab: timestamp column fixed** — the Timestamp column in the transcription results table was too narrow after the v0.16.0 layout redesign, cutting off the end time. The column is now wider (280px default) and fully user-resizable by dragging the column header.
- **Transcribe tab: inline timestamp editing** — timestamp cells in the transcription results table are now editable, matching the existing behaviour for text cells. Double-click a timestamp to correct it. The expected format is `HH:MM:SS,mmm → HH:MM:SS,mmm`; invalid input is rejected and the original value is restored automatically.
- **14 language packs updated** — all new strings for this release are fully translated across all 14 supported interface languages.

---

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