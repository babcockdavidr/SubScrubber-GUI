# SubScrubber — Beta 2

**Remove ads, watermarks, and distributor junk from subtitle files.**

Supports `.srt` · `.ass` · `.ssa` · `.vtt` · embedded subtitles inside `.mkv` `.mp4` and more

Built on the detection engine from [KBlixt/subcleaner](https://github.com/KBlixt/subcleaner), extended with multi-format support, a full GUI, batch processing, and embedded subtitle scanning.

---

## Requirements

- Python 3.10 or newer
- FFmpeg (optional — only needed for the Video Scan feature)

```bash
pip install -r requirements.txt
```

`requirements.txt` installs: `PyQt6`

---

## Launching

```bash
# Open the GUI
python subcleaner.py --gui

# Open the GUI with a file pre-loaded
python subcleaner.py movie.en.srt --gui

# CLI only — no GUI needed
python subcleaner.py movie.en.srt
```

---

## GUI — Review Tab

The Review tab is for inspecting and cleaning one file at a time.

**Workflow:**
1. Drop one or more subtitle files onto the drop zone, or click **Browse** / **Open Folder**
2. Files are analysed automatically in the background — the file queue on the left turns red for files with ads, orange for warnings, green for clean
3. Each subtitle block is listed with its timestamp, confidence score, and a colour indicator (red = ad, orange = warning, grey = clean)
4. Click any block to see its full text and exactly which detection patterns fired
5. Use **✕ Mark as Ad** or **✓ Keep Block** to override any decision — or use the keyboard shortcuts **Delete** and **Space**
6. Click **⚡ Clean & Save** (or **Ctrl+S**) to write the cleaned file — a confirmation dialog shows how many blocks will be removed
7. Use **← Prev File** / **Next File →** to move through the queue

The **Report** tab shows a full per-file analysis report with every flagged block and its reasons.

---

## GUI — Batch Tab

The Batch tab is for cleaning an entire media library in one pass — including libraries where each movie or show is in its own subfolder.

**Workflow:**
1. Click **📂 Select Base Folder** and choose your top-level movies or shows folder — SubScrubber scans all subfolders recursively
2. The file count is shown immediately so you know what was found
3. Click **⚡ Scan All** — all files are analysed in the background with a live progress bar
4. Results appear in the file list, colour-coded red / orange / green. Each row shows `MovieFolder/subtitle.srt` so you can tell which film it belongs to
5. Click any file to see a detailed HTML report for that file in the panel on the right — ad blocks are shown in red cards, warnings in orange, with reason tags underneath each one
6. Adjust the **Sensitivity slider** (1–5) to tune how aggressively blocks are flagged:
   - **1 — Very Aggressive**: catches almost everything, higher false-positive risk
   - **2 — Aggressive**: catches most ad patterns plus borderline cases
   - **3 — Balanced** *(default)*: matches subcleaner's standard behaviour
   - **4 — Conservative**: only removes blocks with strong multiple matches
   - **5 — Very Conservative**: only the most obvious, unambiguous ads
   
   Moving the slider instantly re-colours all rows and updates counts — no rescan needed.
7. Optionally check **Also remove warnings** to include borderline blocks one level below the threshold
8. Click **🗑 Clean & Save All** — a confirmation dialog shows exactly how many blocks from how many files will be removed, then writes everything in one shot

---

## GUI — Video Scan Tab

The Video Scan tab inspects subtitle tracks that are embedded directly inside video container files, without modifying the video.

**Requires FFmpeg** installed and available on your system PATH.

**Workflow:**
1. Drop video files onto the drop zone, or click **Add Folder** to scan a directory
2. Click **⚡ Scan Videos** — SubScrubber uses `ffprobe` to list all subtitle tracks, then extracts each text-based track with `ffmpeg` and runs the full detection engine on it
3. Results appear as a tree: each video file is a root node, its subtitle tracks are children, colour-coded by status
4. Click any track to see its codec, language, forced/default flags, block counts, and up to 5 sample flagged lines
5. Image-based subtitle formats (Blu-ray PGS, DVD VOBSUB, DVB) are detected and listed but marked as unscannable — text extraction requires OCR which is not supported

> **Note:** SubScrubber does not modify video files. To clean embedded subtitles, extract the track with FFmpeg, clean it with SubScrubber, then remux with MKVToolNix.

---

## CLI Reference

```bash
# Clean a single file (writes in place)
python subcleaner.py movie.en.srt

# Detect only — print report, do not write anything
python subcleaner.py movie.en.srt --dry-run

# Scan an entire folder recursively, ask before saving
python subcleaner.py /media/shows -r

# Scan and print report only, never prompt to save
python subcleaner.py /media/shows -r --report-only

# Include verbose output (list clean files too)
python subcleaner.py /media/shows -r --report-only -v

# Only process files tagged with a specific language
python subcleaner.py /media/shows -r --language en

# Also remove warning-level (uncertain) blocks
python subcleaner.py movie.en.srt --remove-warnings

# Skip confirmation prompt (for scripting / automation)
python subcleaner.py /media/shows -r -y

# Scan embedded subtitle tracks inside video files
python subcleaner.py movie.mkv --scan-video
python subcleaner.py /media/movies -r --scan-video
```

---

## What Gets Detected

Detection uses the regex profile system from subcleaner. Profiles are stored as `.conf` files in `regex_profiles/default/` and can be edited or extended without touching any Python code.

| Category | Examples |
|---|---|
| Distributor watermarks | OpenSubtitles, YTS/YIFY, Addic7ed, Subscene, SubDivX, podnapisi, titlovi… |
| Named watermark accounts | Hundreds of known subtitle group names and handles |
| Credit lines | "Subtitles by", "Sync and corrected by", "Downloaded from", "Ripped by"… |
| URLs | `http://`, `www.`, `.com` / `.net` / `.tv` / `.xyz` domains |
| Encoded release info | BluRay, WEB-DL, x264, HEVC, 1080p in subtitle text |
| Promotional text | "Watch Movies & Series", "Become a VIP member", "Support us at"… |
| Language-specific patterns | English, Dutch, Spanish, Portuguese, Swedish, Hebrew, Indonesian profiles included |

**Scoring model:** each PURGE pattern match adds 3 points, each WARNING pattern adds 1. Contextual punishers add 1 point each for factors like being in the first or last 3 blocks, being adjacent to a confirmed ad, or having identical content elsewhere in the file. The threshold (default: 3 points) is adjustable in the Batch tab slider.

---

## Folder Structure

```
subcleaner_gui/
├── subcleaner.py          ← entry point (CLI + --gui flag)
├── requirements.txt
├── README.md
├── core/
│   ├── __init__.py
│   ├── subtitle.py        ← SRT / ASS / VTT parsers
│   ├── cleaner.py         ← detection engine + regex profile loader
│   ├── batch.py           ← batch scan and save engine
│   └── ffprobe.py         ← video container probing and track extraction
├── gui/
│   ├── __init__.py
│   ├── app.py             ← main window + Review tab
│   ├── batch_panel.py     ← Batch tab
│   ├── video_panel.py     ← Video Scan tab
│   └── colors.py          ← shared colour palette
└── regex_profiles/
    └── default/
        ├── global.conf    ← applies to all languages
        ├── english.conf
        ├── no_profile.conf
        ├── dutch.conf
        ├── hebrew.conf
        ├── indonesian.conf
        ├── portuguese.conf
        ├── spanish.conf
        └── svenska.conf
```

---

## Adding Custom Regex Profiles

Create a new `.conf` file in `regex_profiles/default/` following this structure:

```ini
[META]
language_codes = fr, fre, french

[PURGE_REGEX]
my_purge1: some\.website\.com
my_purge2: \b(SomeWatermark|AnotherGroup)\b

[WARNING_REGEX]
my_warn1: \b(subtitles|captions)\b
```

Any match in `PURGE_REGEX` immediately flags the block for removal. `WARNING_REGEX` matches add 1 point each toward the threshold. Restart SubScrubber for new profiles to take effect.

---

*SubScrubber Beta 2 — built on [subcleaner](https://github.com/KBlixt/subcleaner) by KBlixt (MIT licence)*
