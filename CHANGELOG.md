# SubForge — Release Notes

## v0.12.0 — Inline Editing & Diagnostics

- **Transcribe tab: inline editing** — after transcription completes, all subtitle blocks are displayed in a full editable table (index, timestamp, text). Click any text cell to correct it. Edits sync immediately to the subtitle data — Save as .srt and Remux both use the corrected output, not the raw Whisper result.
- **Error log viewer** — "View Error Log" button in Settings > About opens a scrollable dialog showing every error SubForge has logged. Each entry includes the originating tab, a UTC timestamp, and the full traceback. A "Clear Log" button lets you reset it.
- **Unified error logging** — all error catch sites across the app now append to a single persistent log (`subforge_errors.log`) instead of overwriting it. Multiple errors in a session accumulate rather than replacing each other.
- **Log path** — installer mode: `%APPDATA%\SubForge\subforge_errors.log`. Source mode: `<repo_root>/subforge_errors.log`. Same path logic as all other SubForge user data.
- **14 language packs updated** — all new strings for both features are fully translated.

---

## v0.11.0 — Whisper Audio Transcription

- **Transcribe tab** — generate subtitles directly from a video's audio track using Whisper AI. Runs fully offline — no API keys, no cloud, no internet required after the model is downloaded.
- **Model selection** — choose from tiny, base, small, medium, or large. Each model is described in plain language with its speed vs. accuracy tradeoff. Downloaded models are marked with ✓.
- **Language selection** — auto-detect or manually specify an ISO language code for more reliable results on known-language content.
- **SDH mode** — on by default. Includes sound descriptions and non-speech annotations for deaf and hard of hearing viewers. Disabling it shows an accessibility warning.
- **Ad-detection on transcription output** — the same engine used on subtitle files and OCR output runs on the Whisper result. Flagged blocks are shown in the detail pane.
- **Save as .srt** — saves the transcribed subtitle as `[stem].[lang].srt` next to the video file.
- **Remux into video** — adds the transcribed subtitle as a new track in MKV (via mkvmerge) or MP4 (via ffmpeg) alongside existing tracks.
- **Settings > Paths: Whisper model directory** — optionally redirect where models are cached. Leave blank to use the default location inside SubForge's data folder.
- **GPU acceleration** — automatically uses CUDA float16 when a compatible GPU and torch are available; falls back to CPU int8 silently.

---

## v0.10.0 — Image Subs

- **Image Subs tab** — scan PGS (Blu-ray) and VOBSUB (DVD) image-based subtitle tracks using Tesseract OCR. The same ad-detection engine used on text tracks runs on the OCR output.
- **Save as .srt** — save the OCR'd subtitle as a standalone `.srt` file next to the video.
- **Remux into video** — replace or keep the original image track alongside the new text track. Supports MKV (via mkvmerge) and MP4 (via ffmpeg).
- **Sensitivity slider** — the Image Subs tab now has a sensitivity slider matching the other tabs, respecting your default from Settings.
- **Open in Image Subs** — the Video Scan tab shows a handoff button when an image track is selected.
- **Settings > Paths expanded** — ffmpeg, ffprobe, and Tesseract now each have their own path entry.
- **First-run wizard updated** — Tesseract now appears alongside FFmpeg and MKVToolNix, with language selector right in the wizard.
- **System language auto-detection** — on first launch, SubForge detects your OS locale and selects the matching language pack.
- **What's New** — a new button in Settings > About opens a scrollable release notes dialog.
- **Translation fixes** — Settings Save/Cancel buttons and sensitivity slider labels are now fully translated in all 14 language packs.

---

## v0.9.0 — Packaging & Distribution

- **Windows installer** — SubForge now ships as a double-clickable Windows installer. No Python required.
- **GitHub Actions** — every tagged release automatically builds and publishes the Windows installer.
- **First-run setup wizard** — checks for FFmpeg and MKVToolNix on first launch with download links.
- **Session memory** — SubForge remembers your last Batch folder, last Video Scan folder, and window size across restarts.
- **14 language packs** — English, Spanish, Dutch, Hebrew, Indonesian, Portuguese, Swedish, French, Arabic, Chinese, Hindi, Russian, Turkish, and Polish.

---

## v0.8.0 — Settings Expansion & Polish

- **App renamed to SubForge.**
- **Settings dialog expanded** — four tabs: General, Cleaning Options, Paths, and About.
- **Default sensitivity** — set your sensitivity once in Settings and it applies to all tabs on every launch.
- **Language support** — SubForge shipped in English and Spanish, with a one-click restart to apply language changes.
- **Column sort on Batch** — click any column header to sort by File, Ads, Opts, or Warns.

---

## v0.7.0 — Subtitle Cleaning Options

- **Cleaning options** — strip forced italics, normalize ellipses, remove hearing-impaired annotations, and more. Configurable per-option in Settings.
- **Track title normalization** — encoder credits in subtitle track titles are stripped on remux.
- **CLEAN OPT indicators** — blue badges in Single File, Batch, and Video Scan show when cleaning options will act on a track.

---

## v0.6.0 — Interface Overhaul

- **Single File tab redesigned** — review and report merged into one tab with a file queue.
- **Sensitivity slider added** to Single File tab.
- **Extract & Save filename** format: `[video].[lang].srt`, SDH auto-detected.

---

## v0.5.0 — MP4 Remux

- **MP4 and M4V remuxing** via ffmpeg — no extra dependencies.
- **Check for Updates** button in status bar (opt-in).

---

## v0.4.0 — MKVToolNix Integration

- **MKV Clean & Remux** via mkvmerge.
- **Sensitivity slider** added to Video Scan.
- **HTML detail reports** in Video Scan and Batch.
