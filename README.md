# SubScrubber - GUI

Remove ads, watermarks, and junk from subtitle files.

Supports **.srt**, **.ass**, **.ssa**, **.vtt**

Inspired by [KBlixt/subcleaner](https://github.com/KBlixt/subcleaner), extended with multi-format support and a full GUI.

---

## Setup

```
pip install -r requirements.txt
```

Python 3.10+ required.

---

## GUI

```
python subcleaner.py --gui
```

Or pre-load files:
```
python subcleaner.py movie.en.srt --gui
```

**Workflow:**
1. Drop subtitle files onto the drop zone (or use Browse / Open Folder)
2. Each file is analyzed automatically — ad blocks are highlighted red, warnings in orange
3. Click a block to review its content and which patterns triggered
4. Use **✕ Mark as Ad** / **✓ Keep Block** (or Delete/Space keys) to adjust decisions
5. Click **⚡ Clean & Save** to write the cleaned file

---

## CLI

```bash
# Clean a single file
python subcleaner.py movie.en.srt

# Dry run (detect only, don't write)
python subcleaner.py movie.en.srt --dry-run

# Recursive folder
python subcleaner.py /media/subtitles -r

# Only English files
python subcleaner.py /media/subtitles -r --language en

# Also remove uncertain/warning blocks
python subcleaner.py movie.en.ass --remove-warnings
```

---

## What gets detected

| Category | Examples |
|---|---|
| Distributor watermarks | OpenSubtitles, YTS/YIFY, Addic7ed, Subscene, SubDivX… |
| Credit lines | "Subtitles by", "Sync and corrected by", "Downloaded from"… |
| URLs | Any http/www/domain.com pattern |
| Release tags | BluRay, WEB-DL, x264, HEVC… |
| Language-specific | English donation asks, promo text, visit-us patterns |

Detection uses **confidence scoring** — blocks above 85% are auto-flagged as ads, 45–85% as warnings. The GUI lets you review and override every decision before saving.

---

## Coming in Phase 3–4

- Batch folder mode with summary report
- `ffprobe` integration to scan subtitles embedded inside MKV/MP4
- Regex profile editor in the GUI
- Windows `.exe` via PyInstaller
