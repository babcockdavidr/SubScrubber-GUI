"""
Video scan panel — probe embedded subtitle tracks, scan for ads,
optionally clean and remux via MKVToolNix or extract as standalone files.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QProgressBar, QFileDialog, QFrame, QSplitter,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QSlider,
    QDialog, QDialogButtonBox, QCheckBox, QLineEdit, QGroupBox,
    QSizePolicy, QApplication,
)

import sys
# sys.path managed by subforge.py entry point — do not insert __file__-relative paths here

from core import (
    collect_video_files, scan_video, ffprobe_available, ffmpeg_available,
    mkvmerge_available, get_mkvmerge_path, set_mkvmerge_path,
    extract_and_clean_track, remux_with_cleaned_tracks, remux_video,
    VideoScanResult, SubtitleTrack, VIDEO_EXTENSIONS,
    CleanedTrack, apply_cleaning_options,
)
from gui.settings_dialog import load_cleaning_options, load_default_sensitivity
from gui.strings import STRINGS
from core import block_will_be_removed
from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW

THRESHOLD_LABELS = {
    1: STRINGS["thresh_1"],
    2: STRINGS["thresh_2"],
    3: STRINGS["thresh_3"],
    4: STRINGS["thresh_4"],
    5: STRINGS["thresh_5"],
}

STATUS_COLORS = {
    "ADS":   RED,
    "WARN":  ORANGE,
    "CLEAN": GREEN,
    "IMAGE": FG2,
    "SKIP":  FG2,
    "ERROR": "#888888",
}


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

HTML_STYLE = f"""<style>
  body {{ background:{BG2}; color:{FG}; font-family:Consolas,monospace;
          font-size:13px; margin:8px; }}
  .section  {{ color:{ACCENT}; font-size:11px; text-transform:uppercase;
               letter-spacing:1px; margin-top:16px; margin-bottom:6px;
               border-bottom:1px solid {BORDER}; padding-bottom:3px; }}
  .meta-row {{ margin:3px 0; }}
  .meta-lbl {{ color:{FG2}; }}
  .meta-val {{ color:{FG}; font-weight:bold; }}
  .block-ad {{ margin:3px 0 3px 0px; padding:5px 10px; background:#2a1a22;
               border-left:4px solid {RED}; }}
  .block-opt{{ margin:3px 0 3px 0px; padding:5px 10px; background:#1a1f2e;
               border-left:4px solid {ACCENT}; }}
  .block-warn{{ margin:3px 0 3px 0px; padding:5px 10px; background:#231f15;
               border-left:4px solid {ORANGE}; }}
  .block-kept{{ margin:3px 0 3px 0px; padding:5px 10px; background:#1e2535;
               border-left:4px solid {FG2}; }}
  .block-img {{ margin:3px 0 3px 12px; padding:5px 10px; background:{BG3};
               border-left:2px solid {FG2}; color:{FG2}; }}
  .block-err {{ margin:3px 0 3px 12px; padding:5px 10px; background:{BG3};
               border-left:2px solid #888; color:#888; }}
  .tag-ad   {{ color:#ff9eb5; font-weight:bold; }}
  .tag-warn {{ color:#ffc990; font-weight:bold; }}
  .tag-kept {{ color:{FG2}; font-style:italic; }}
  .tag-clean{{ color:{GREEN}; font-weight:bold; }}
  .tag-img  {{ color:{FG2}; }}
  .ts       {{ color:#7dcfff; font-size:12px; }}
  .ad-text  {{ color:#ff9eb5; font-weight:bold; }}
  .opt-text {{ color:#89b4fa; }}
  .warn-text{{ color:#ffc990; font-weight:bold; }}
  .kept-text{{ color:{FG2}; font-style:italic; text-decoration:line-through; }}
  .reason   {{ color:#565f89; font-size:11px; margin-right:8px; }}
  .clean-msg{{ color:{GREEN}; margin-top:10px; }}
  .err-msg  {{ color:#888; margin-top:10px; }}
  .keep-btn {{ color:{FG2}; font-size:10px; float:right; cursor:pointer;
               border:1px solid {BORDER}; padding:1px 6px; border-radius:3px; }}
  .keep-btn:hover {{ color:{FG}; border-color:{ACCENT}; }}
  .note     {{ color:{FG2}; font-size:11px; font-style:italic; margin-top:8px; }}
</style>"""


def _track_html(result: VideoScanResult, track: SubtitleTrack,
                threshold: int = 3) -> str:
    """
    Full interactive detail view for a subtitle track.
    Uses stored subtitle blocks for threshold-aware display.
    Each flagged block gets a sendPrompt link so the user can mark it as kept.
    """
    parts = [HTML_STYLE,
             f'<div class="meta-lbl">{_esc(result.path.name)}</div>',
             f'<div class="section">' + STRINGS["rpt_video_subtitle_track"] + '</div>']

    def row(lbl, val, color=None):
        vs = f' style="color:{color}"' if color else ''
        parts.append(
            f'<div class="meta-row"><span class="meta-lbl">{lbl}&nbsp;</span>'
            f'<span class="meta-val"{vs}>{_esc(val)}</span></div>'
        )

    row(STRINGS["rpt_video_track"], f'{track.track_num}  (' + STRINGS["rpt_video_stream_index"].format(index=track.index) + ')')
    row(STRINGS["rpt_video_codec"], track.codec)
    row(STRINGS["rpt_video_language"], track.language)
    if track.title:
        row("Title:", track.title)
    row(STRINGS["rpt_video_forced"], STRINGS["rpt_video_yes"] if track.forced else STRINGS["rpt_video_no"])
    row(STRINGS["rpt_video_default"], STRINGS["rpt_video_yes"] if track.default else STRINGS["rpt_video_no"])

    if not track.is_text:
        parts.append('<div class="section">' + STRINGS["rpt_video_status"] + '</div>')
        if track.is_image:
            parts.append(
                f'<div class="block-img"><span class="tag-img">IMAGE</span>&nbsp;'
                + STRINGS["rpt_video_image_track"] + '</div>'
            )
        else:
            parts.append(
                f'<div class="block-err">' + STRINGS["rpt_video_scan_error"].format(error=_esc(track.scan_error or STRINGS["rpt_video_unsupported"])) + '</div>'
            )
        return "\n".join(parts)

    if track.scan_error:
        parts.append('<div class="section">' + STRINGS["rpt_video_status"] + '</div>')
        parts.append(f'<div class="block-err">' + STRINGS["rpt_video_scan_error"].format(error=_esc(track.scan_error)) + '</div>')
        return "\n".join(parts)

    # Use stored subtitle for threshold-aware counts
    cleaning_opts = load_cleaning_options()
    sub = track.subtitle
    if sub is not None:
        ads   = [b for b in sub.blocks if b.regex_matches >= threshold]
        warns = [b for b in sub.blocks
                 if b.regex_matches == threshold - 1 and threshold > 1]
        kept  = [b for b in sub.blocks if getattr(b, '_kept', False)]
        clean_opt_blocks = [
            b for b in sub.blocks
            if b.regex_matches < threshold
            and not getattr(b, '_kept', False)
            and block_will_be_removed(b.content, cleaning_opts)
        ]
    else:
        ads, warns, kept, clean_opt_blocks = [], [], [], []

    parts.append('<div class="section">' + STRINGS["rpt_video_results"] + '</div>')
    row(STRINGS["rpt_video_blocks"], str(track.total_blocks))
    row(STRINGS["rpt_video_ads"], str(len(ads)),
        color="#ff9eb5" if ads else GREEN)
    if clean_opt_blocks:
        row(STRINGS["rpt_video_cleaning"], str(len(clean_opt_blocks)),
            color="#ff9eb5")
    row(STRINGS["rpt_video_warns"], str(len(warns)),
        color="#ffc990" if warns else None)
    if kept:
        row("Manually kept (won't be removed):", str(len(kept)),
            color=FG2)

    if sub is not None and (ads or warns or clean_opt_blocks):
        parts.append(
            '<div class="note">' + STRINGS["rpt_video_keep_note"] + '</div>'
        )
        parts.append('<div class="section">' + STRINGS["rpt_video_flagged"] + '</div>')
        for b in ads + clean_opt_blocks + warns:
            is_kept = getattr(b, '_kept', False)
            is_ad   = b.regex_matches >= threshold
            is_clean_opt = b in clean_opt_blocks
            reasons_html = " ".join(
                f'<span class="reason">{_esc(h)}</span>'
                for h in dict.fromkeys(b.hints)
            ) if hasattr(b, 'hints') else ""
            if is_clean_opt and not is_ad:
                reasons_html += '<span class="reason" style="color:#4e9eff">' + STRINGS["rpt_lbl_cleaning_opts"] + '</span>'
            if is_kept:
                div_class = "block-kept"
                tag = '<span class="tag-kept">' + STRINGS["rpt_tag_kept"] + '</span>'
                text_class = "kept-text"
                btn_label = STRINGS["rpt_btn_kept"]
                btn_color = FG2
                btn_border = BORDER
            elif is_clean_opt and not is_ad:
                div_class = "block-opt"
                tag = '<span style="color:#4e9eff;font-weight:bold">' + STRINGS["rpt_tag_clean_opt"] + '</span>'
                text_class = "opt-text"
                btn_label = STRINGS["rpt_btn_keep"]
                btn_color = FG2
                btn_border = BORDER
            elif is_ad:
                div_class = "block-ad"
                tag = '<span class="tag-ad">' + STRINGS["rpt_tag_ad"] + '</span>'
                text_class = "ad-text"
                btn_label = STRINGS["rpt_btn_keep"]
                btn_color = FG2
                btn_border = BORDER
            else:
                div_class = "block-warn"
                tag = '<span class="tag-warn">' + STRINGS["rpt_tag_warn"] + '</span>'
                text_class = "warn-text"
                btn_label = STRINGS["rpt_btn_keep"]
                btn_color = FG2
                btn_border = BORDER

            # Use a table for reliable left/right alignment in QTextBrowser
            parts.append(
                f'<div class="{div_class}">'
                f'<table width="100%" cellpadding="0" cellspacing="0">'
                f'<tr>'
                f'<td>{tag}&nbsp;<span class="ts">[{_esc(b.start)}]</span>'
                f'&nbsp;<span style="color:{FG2};font-size:10pt;">'
                f'rm={b.regex_matches}</span></td>'
                f'<td align="right">'
                f'<a href="keep:{id(b)}" style="'
                f'color:{btn_color};font-size:10pt;'
                f'border:1px solid {btn_border};'
                f'padding:2px 10px;border-radius:3px;'
                f'text-decoration:none;white-space:nowrap;">'
                f'{btn_label}</a>'
                f'</td>'
                f'</tr>'
                f'</table>'
                f'<span class="{text_class}">{_esc(b.text[:120])}</span><br>'
                f'{reasons_html}'
                f'</div>'
            )
    elif sub is not None:
        parts.append('<div class="clean-msg">' + STRINGS["rpt_video_no_issues"] + '</div>')

    return "\n".join(parts)


def _video_html(result: VideoScanResult, threshold: int = 3) -> str:
    parts = [HTML_STYLE,
             f'<div style="color:{FG};font-weight:bold;font-size:14px">'
             f'{_esc(result.path.name)}</div>',
             f'<div class="meta-lbl" style="font-size:11px">'
             f'{_esc(str(result.path.parent))}</div>']

    if result.error:
        parts.append('<div class="section">' + STRINGS["rpt_video_status"] + '</div>')
        parts.append(f'<div class="err-msg">{_esc(result.error)}</div>')
        return "\n".join(parts)

    total_ads  = sum(t.ads_at_threshold(threshold) for t in result.tracks)
    total_warn = sum(t.warnings_at_threshold(threshold) for t in result.tracks)
    parts.append('<div class="section">' + STRINGS["rpt_video_summary"] + '</div>')
    parts.append(f'<div class="meta-row"><span class="meta-lbl">Tracks:&nbsp;</span>'
                 f'<span class="meta-val">{len(result.tracks)}</span></div>')
    parts.append(
        f'<div class="meta-row"><span class="meta-lbl">Ad blocks (threshold {threshold}):&nbsp;</span>'
        f'<span class="meta-val" style="color:{"#ff9eb5" if total_ads else GREEN}">'
        f'{total_ads}</span></div>'
    )
    parts.append(
        f'<div class="meta-row"><span class="meta-lbl">Warnings:&nbsp;</span>'
        f'<span class="meta-val" style="color:{"#ffc990" if total_warn else FG2}">'
        f'{total_warn}</span></div>'
    )

    parts.append('<div class="section">' + STRINGS["rpt_video_tracks"] + '</div>')
    for t in result.tracks:
        status = t.status_at_threshold(threshold)
        tags = {"ADS":   '<span class="tag-ad">' + STRINGS["rpt_tag_ad"] + '</span>',
                "WARN":  '<span class="tag-warn">' + STRINGS["rpt_tag_warn"] + '</span>',
                "CLEAN": '<span class="tag-clean">' + STRINGS["rpt_tag_clean"] + '</span>',
                "IMAGE": f'<span class="tag-img">IMAGE</span>'}
        tag = tags.get(status, f'<span style="color:#888">ERROR</span>')
        ads_n = t.ads_at_threshold(threshold)
        warn_n = t.warnings_at_threshold(threshold)
        detail = ""
        if ads_n:          detail = f'&nbsp;&mdash; {ads_n} ad block(s)'
        elif warn_n:       detail = f'&nbsp;&mdash; {warn_n} warning(s)'
        elif t.scan_error: detail = f'&nbsp;&mdash; {_esc(t.scan_error[:60])}'
        parts.append(
            f'<div class="meta-row">{tag}&nbsp;&nbsp;'
            f'{_esc(t.display_name)}{detail}</div>'
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class VideoScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        results = []
        for i, path in enumerate(self.paths):
            self.progress.emit(i, len(self.paths), path.name)
            try:
                result = scan_video(path)
            except Exception as e:
                from core.ffprobe import VideoScanResult
                result = VideoScanResult(path=path)
                result.error = f"unhandled error: {e}"
            results.append(result)
        self.finished.emit(results)


class RemuxWorker(QThread):
    status_update = pyqtSignal(str)
    finished      = pyqtSignal(object)

    def __init__(self, video_path, all_tracks, tracks_to_clean,
                 make_backup, remove_warnings):
        super().__init__()
        self.video_path      = video_path
        self.all_tracks      = all_tracks
        self.tracks_to_clean = tracks_to_clean
        self.make_backup     = make_backup
        self.remove_warnings = remove_warnings

    def run(self):
        import tempfile
        from core.mkvtoolnix import RemuxResult
        tmpdir_obj = tempfile.TemporaryDirectory()
        tmpdir = Path(tmpdir_obj.name)
        cleaned = []
        for track in self.tracks_to_clean:
            self.status_update.emit(
                f"Extracting & cleaning track {track.track_num} ({track.language})…"
            )
            ct, err = extract_and_clean_track(
                self.video_path, track, tmpdir,
                remove_warnings=self.remove_warnings,
                progress_cb=lambda msg: self.status_update.emit(msg),
            )
            if err:
                self.status_update.emit(f"  Warning: track {track.track_num} — {err}")
                continue
            cleaned.append(ct)
        if not cleaned:
            self.finished.emit(RemuxResult(
                success=False, error="No tracks were successfully cleaned."))
            return
        self.status_update.emit("Remuxing…")
        result = remux_video(
            self.video_path, self.all_tracks, cleaned,
            make_backup=self.make_backup,
            progress_cb=lambda msg: self.status_update.emit(msg),
        )
        tmpdir_obj.cleanup()
        self.finished.emit(result)


# ---------------------------------------------------------------------------
# Progress dialog
# ---------------------------------------------------------------------------

class RemuxProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cleaning & Remuxing…")
        self.setMinimumWidth(500)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background: {BG}; color: {FG}; }}")
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        self._lbl = QLabel(STRINGS["video_starting"])
        self._lbl.setWordWrap(True)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setMaximumHeight(6)
        self._log = QTextBrowser()
        self._log.setFont(QFont("Consolas", 10))
        self._log.setMaximumHeight(160)
        self._log.setStyleSheet(
            f"background: {BG2}; color: {FG2}; border: 1px solid {BORDER};"
        )
        layout.addWidget(self._lbl)
        layout.addWidget(self._bar)
        layout.addWidget(self._log)

    def update_status(self, msg):
        self._lbl.setText(msg)
        self._log.append(msg)

    def done_ok(self):
        self._bar.setRange(0, 1)
        self._bar.setValue(1)

    def done_fail(self):
        self._bar.setRange(0, 1)
        self._bar.setValue(0)


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class VideoSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Video Scan Settings")
        self.setMinimumWidth(520)
        self.setStyleSheet(f"QDialog {{ background: {BG}; color: {FG}; }}")
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        grp = QGroupBox("MKVToolNix")
        grp.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px;"
            f"color: {FG2}; margin-top: 8px; padding-top: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        gl = QVBoxLayout(grp)
        info = QLabel(
            "mkvmerge is used to rebuild MKV files with cleaned subtitle tracks. "
            "If it is not on your system PATH, specify the full path to mkvmerge.exe below."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {FG2}; font-size: 10pt;")
        path_row = QHBoxLayout()
        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText(r"e.g. C:\Program Files\MKVToolNix\mkvmerge.exe")
        self._path_input.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER};"
            f"border-radius: 3px; padding: 4px;"
        )
        current = get_mkvmerge_path()
        if current:
            self._path_input.setText(current)
        btn_browse = QPushButton(STRINGS["sf_browse"])
        btn_browse.clicked.connect(self._browse)
        path_row.addWidget(self._path_input, stretch=1)
        path_row.addWidget(btn_browse)
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(f"font-size: 10pt;")
        self._check_status()
        gl.addWidget(info)
        gl.addLayout(path_row)
        gl.addWidget(self._lbl_status)
        layout.addWidget(grp)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        self._path_input.textChanged.connect(self._check_status)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Find mkvmerge.exe", "",
            "mkvmerge (mkvmerge.exe);;All Files (*)"
        )
        if path:
            self._path_input.setText(path)

    def _check_status(self):
        path = self._path_input.text().strip()
        if path and Path(path).is_file():
            self._lbl_status.setText("✓ File found.")
            self._lbl_status.setStyleSheet(f"color: {GREEN}; font-size: 10pt;")
        elif path:
            self._lbl_status.setText("✕ File not found at that path.")
            self._lbl_status.setStyleSheet(f"color: {RED}; font-size: 10pt;")
        elif mkvmerge_available():
            self._lbl_status.setText(f"✓ mkvmerge found on PATH: {get_mkvmerge_path()}")
            self._lbl_status.setStyleSheet(f"color: {GREEN}; font-size: 10pt;")
        else:
            self._lbl_status.setText(
                "mkvmerge not found. Install MKVToolNix from https://mkvtoolnix.download/"
            )
            self._lbl_status.setStyleSheet(f"color: {ORANGE}; font-size: 10pt;")

    def _save(self):
        path = self._path_input.text().strip()
        if path:
            set_mkvmerge_path(path)
        self.accept()


# ---------------------------------------------------------------------------
# Drop zone
# ---------------------------------------------------------------------------

class VideoDropZone(QFrame):
    files_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("🎬")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 18pt;")
        msg = QLabel(STRINGS["video_drop_label"])
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {FG2}; font-size: 10pt;")
        browse = QPushButton("Browse…")
        browse.setMaximumWidth(100)
        browse.clicked.connect(self._browse)
        layout.addWidget(icon)
        layout.addWidget(msg)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)

    def _browse(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open Video Files", "", f"Video Files ({exts});;All Files (*)"
        )
        if paths:
            self.files_dropped.emit([Path(p) for p in paths])

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        paths = []
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                paths.append(p)
            elif p.is_dir():
                paths.extend(collect_video_files([p]))
        if paths:
            self.files_dropped.emit(paths)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class VideoScanPanel(QWidget):
    open_in_image_subs = pyqtSignal(Path)   # emitted when user clicks "Open in Image Subs"
    def __init__(self, parent=None):
        super().__init__(parent)
        self._results:  List[VideoScanResult] = []
        self._worker:   Optional[VideoScanWorker] = None
        self._queued:       List[Path] = []
        self._last_folder:  str = ""
        self._threshold: int = load_default_sensitivity()
        self._checked_tracks: Dict = {}
        self._current_result: Optional[VideoScanResult] = None
        self._current_track:  Optional[SubtitleTrack]   = None
        self._build_ui()
        self._check_tools()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Notices ───────────────────────────────────────────────────
        self._ffmpeg_notice = QLabel()
        self._ffmpeg_notice.setStyleSheet(
            f"color: {ORANGE}; background: transparent; border: 1px solid {ORANGE}55;"
            f"border-radius: 4px; padding: 6px 10px; font-size: 10pt;"
        )
        self._ffmpeg_notice.setWordWrap(True)
        self._ffmpeg_notice.setVisible(False)

        self._mkv_notice = QLabel()
        self._mkv_notice.setStyleSheet(
            f"color: {ORANGE}; background: transparent; border: 1px solid {ORANGE}55;"
            f"border-radius: 4px; padding: 6px 10px; font-size: 10pt;"
        )
        self._mkv_notice.setWordWrap(True)
        self._mkv_notice.setVisible(False)

        # ── Top controls ──────────────────────────────────────────────
        ctrl = QHBoxLayout()
        self._btn_add_folder = QPushButton(STRINGS["video_btn_add_folder"])
        self._btn_clear      = QPushButton(STRINGS["video_btn_clear"])
        self._btn_scan       = QPushButton(STRINGS["video_btn_scan"])
        self._btn_scan.setObjectName("btn_clean_all")
        self._btn_scan.setEnabled(False)

        self._lbl_folder = QLabel(STRINGS["video_no_folder"])
        self._lbl_folder.setStyleSheet(f"color: {FG2}; font-size: 10pt;")

        ctrl.addWidget(self._btn_add_folder)
        ctrl.addWidget(self._btn_clear)
        ctrl.addWidget(self._lbl_folder, stretch=1)
        ctrl.addWidget(self._btn_scan)

        # ── Sensitivity slider ────────────────────────────────────────
        thresh_frame = QFrame()
        thresh_frame.setStyleSheet(
            f"background: {BG2}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        tl = QHBoxLayout(thresh_frame)
        tl.setContentsMargins(12, 6, 12, 6)
        lbl_s = QLabel(STRINGS["sens_label"])
        lbl_s.setStyleSheet(f"color: {FG}; font-weight: bold;")
        lbl_agg = QLabel(STRINGS["sens_more_aggressive"])
        lbl_agg.setStyleSheet(f"color: {RED}; font-size: 9pt;")
        lbl_con = QLabel(STRINGS["sens_more_conservative"])
        lbl_con.setStyleSheet(f"color: {GREEN}; font-size: 9pt;")
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(1)
        self._slider.setMaximum(5)
        self._slider.setValue(load_default_sensitivity())
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(1)
        self._slider.setFixedWidth(180)
        self._lbl_threshold = QLabel(THRESHOLD_LABELS[3])
        self._lbl_threshold.setStyleSheet(f"color: {YELLOW}; font-size: 9pt;")
        tl.addWidget(lbl_s)
        tl.addWidget(lbl_agg)
        tl.addWidget(self._slider)
        tl.addWidget(lbl_con)
        tl.addSpacing(12)
        tl.addWidget(self._lbl_threshold, stretch=1)

        # ── Progress / status ─────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(6)
        self._lbl_status = QLabel(STRINGS["video_status_begin"])
        self._lbl_status.setObjectName("file_status")

        # ── Drop zone ─────────────────────────────────────────────────
        self._drop_zone = VideoDropZone()

        # ── Splitter ──────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: tree + action bar
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        lbl_tree = QLabel(STRINGS["video_lbl_files"])
        lbl_tree.setObjectName("section_label")

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setFont(QFont("Consolas", 11))
        self._tree.setIndentation(16)

        self._lbl_selected = QLabel(STRINGS["video_lbl_selected"])
        self._lbl_selected.setStyleSheet(f"color: {FG2}; font-size: 9pt;")
        self._lbl_selected.setWordWrap(True)

        remux_bar = QHBoxLayout()
        self._chk_backup   = QCheckBox(STRINGS["video_chk_backup"])
        self._chk_backup.setChecked(True)
        self._chk_warnings = QCheckBox(STRINGS["video_chk_warnings"])

        # "Clean & Remux" — replaces subtitle tracks inside MKV or MP4/M4V
        self._btn_remux = QPushButton(STRINGS["video_btn_remux"])
        self._btn_remux.setObjectName("btn_save")
        self._btn_remux.setEnabled(False)
        self._btn_remux.setToolTip(
            "Cleans the selected subtitle tracks and rebuilds the video file with\n"
            "the cleaned tracks replacing the originals.\n\n"
            "MKV: requires MKVToolNix (mkvmerge).\n"
            "MP4/M4V: uses ffmpeg (already required for scanning).\n"
            "A backup file is created unless 'Keep backup' is unchecked."
        )

        # "Extract & Save" — pulls subtitle out as standalone file
        self._btn_extract = QPushButton(STRINGS["video_btn_extract"])
        self._btn_extract.setObjectName("btn_keep")
        self._btn_extract.setEnabled(False)
        self._btn_extract.setToolTip(
            "Extracts the selected subtitle tracks from the video, cleans them,\n"
            "and saves them as standalone .srt or .ass files next to the video.\n\n"
            "Works with any video format. Does not modify the video file.\n"
            "Most media players will automatically use external subtitle files."
        )

        remux_bar.addWidget(self._chk_backup)
        remux_bar.addWidget(self._chk_warnings)
        remux_bar.addStretch()
        remux_bar.addWidget(self._btn_extract)
        remux_bar.addWidget(self._btn_remux)

        ll.addWidget(lbl_tree)
        ll.addWidget(self._tree, stretch=1)
        ll.addWidget(self._lbl_selected)
        ll.addLayout(remux_bar)

        # Right: HTML detail
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        lbl_detail = QLabel(STRINGS["video_lbl_detail"])
        lbl_detail.setObjectName("section_label")

        # "Open in Image Subs" button — shown only when an image track is selected
        self._btn_open_image_subs = QPushButton(STRINGS["img_btn_open_image_subs"])
        self._btn_open_image_subs.setObjectName("btn_clean_all")
        self._btn_open_image_subs.setVisible(False)
        self._btn_open_image_subs.setToolTip(
            "Send this video file to the Image Subs tab to scan "
            "its image-based subtitle tracks with Tesseract OCR."
        )
        self._btn_open_image_subs.clicked.connect(self._open_current_in_image_subs)

        self._detail_text = QTextBrowser()
        self._detail_text.setFont(QFont("Consolas", 11))
        self._detail_text.setOpenExternalLinks(False)
        self._detail_text.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        rl.addWidget(lbl_detail)
        rl.addWidget(self._btn_open_image_subs)
        rl.addWidget(self._detail_text)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([380, 460])

        root.addWidget(self._ffmpeg_notice)
        root.addWidget(self._mkv_notice)
        root.addLayout(ctrl)
        root.addWidget(thresh_frame)
        root.addWidget(self._drop_zone)
        root.addWidget(self._progress)
        root.addWidget(self._lbl_status)
        root.addWidget(splitter, stretch=1)

        # ── Connect ───────────────────────────────────────────────────
        self._drop_zone.files_dropped.connect(self._add_files)
        self._btn_add_folder.clicked.connect(self._browse_folder)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_scan.clicked.connect(self._scan)
        self._btn_remux.clicked.connect(self._remux_selected)
        self._btn_extract.clicked.connect(self._extract_selected)
        self._slider.valueChanged.connect(self._on_threshold_changed)
        self._tree.currentItemChanged.connect(self._on_tree_selection)
        self._tree.itemChanged.connect(self._on_item_checked)
        self._detail_text.anchorClicked.connect(self._on_detail_link)

    # ── Tool checks ───────────────────────────────────────────────────

    def _check_tools(self):
        missing_ff = []
        if not ffprobe_available(): missing_ff.append("ffprobe")
        if not ffmpeg_available():  missing_ff.append("ffmpeg")
        if missing_ff:
            self._ffmpeg_notice.setText(STRINGS["video_ffmpeg_notice"])
            self._ffmpeg_notice.setVisible(True)
        if not mkvmerge_available():
            self._mkv_notice.setText(STRINGS["video_mkv_notice"])
            self._mkv_notice.setVisible(True)

    def _open_settings(self):
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()
        if mkvmerge_available():
            self._mkv_notice.setVisible(False)
            self._refresh_remux_button()
        else:
            self._mkv_notice.setVisible(True)

    # ── File collection ───────────────────────────────────────────────

    # ------------------------------------------------------------------
    # Public session-memory API
    # ------------------------------------------------------------------

    def get_folder(self) -> str:
        """Return last folder added via the browse button, or '' if none."""
        return self._last_folder

    def set_folder(self, path: str) -> None:
        """Restore a previously saved folder and populate the file list."""
        if not path:
            return
        p = Path(path)
        if p.is_dir():
            self._last_folder = str(p)
            self._lbl_folder.setText(str(p))
            self._add_files(collect_video_files([p]))

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add Video Folder")
        if folder:
            p = Path(folder)
            self._last_folder = str(p)
            self._lbl_folder.setText(str(p))
            self._add_files(collect_video_files([p]))

    def _add_files(self, paths):
        existing = set(self._queued)
        new = [p for p in paths if p not in existing]
        self._queued.extend(new)
        self._lbl_status.setText(STRINGS["video_files_queued"].format(n=len(self._queued)))
        self._btn_scan.setEnabled(bool(self._queued))

    def _clear(self):
        self._queued.clear()
        self._results.clear()
        self._checked_tracks.clear()
        self._current_result = None
        self._current_track  = None
        self._tree.clear()
        self._detail_text.clear()
        self._btn_remux.setEnabled(False)
        self._btn_extract.setEnabled(False)
        self._lbl_selected.setText(STRINGS["video_lbl_selected"])
        self._lbl_folder.setText(STRINGS["video_no_folder"])
        self._lbl_status.setText(STRINGS["video_status_begin"])
        self._btn_scan.setEnabled(False)

    # ── Threshold ─────────────────────────────────────────────────────

    def _on_threshold_changed(self, value: int):
        self._threshold = value
        self._lbl_threshold.setText(THRESHOLD_LABELS.get(value, str(value)))
        # Refresh tree colors and icons
        if self._results:
            self._refresh_tree_colors()
        # Refresh detail pane
        current = self._tree.currentItem()
        if current:
            self._on_tree_selection(current, None)

    def _refresh_tree_colors(self):
        """Re-color tree items based on current threshold without rebuilding."""
        self._tree.blockSignals(True)
        t = self._threshold
        for i in range(self._tree.topLevelItemCount()):
            root_item = self._tree.topLevelItem(i)
            data = root_item.data(0, Qt.ItemDataRole.UserRole)
            if not data or data[0] != "video":
                continue
            result: VideoScanResult = data[1]
            if result.error:
                continue

            has_ads  = any(tr.ads_at_threshold(t) > 0 for tr in result.tracks)
            has_warn = any(tr.warnings_at_threshold(t) > 0 for tr in result.tracks)
            cleaning_opts_refresh = load_cleaning_options()
            has_opts = (
                cleaning_opts_refresh.any_enabled() and
                any(
                    tr.subtitle is not None and
                    any(block_will_be_removed(b.content, cleaning_opts_refresh)
                        for b in tr.subtitle.blocks)
                    for tr in result.tracks
                )
            )
            color = RED if has_ads else (ORANGE if has_warn else (ACCENT if has_opts else FG2))
            root_item.setForeground(0, QColor(color))

            for j in range(root_item.childCount()):
                child = root_item.child(j)
                cdata = child.data(0, Qt.ItemDataRole.UserRole)
                if not cdata or cdata[0] != "track":
                    continue
                track: SubtitleTrack = cdata[2]
                status = track.status_at_threshold(t)
                tc     = STATUS_COLORS.get(status, FG2)
                # Override color to blue if track has opts but no ads
                if status == "CLEAN" and cleaning_opts_refresh.any_enabled() and track.subtitle:
                    if any(block_will_be_removed(b.content, cleaning_opts_refresh)
                           for b in track.subtitle.blocks):
                        tc = ACCENT
                icon   = {"ADS":"✕","WARN":"⚠","CLEAN":"✓","IMAGE":"◻"}.get(status,"·")
                # Preserve checkbox state, just update text and color
                old_text = child.text(0)
                display  = track.display_name
                child.setText(0, f"{icon}  {display}")
                child.setForeground(0, QColor(tc))

        self._tree.blockSignals(False)

    # ── Scanning ──────────────────────────────────────────────────────

    def _scan(self):
        if not self._queued:
            return
        if not ffprobe_available():
            QMessageBox.warning(self, STRINGS["dlg_ffprobe_title"], STRINGS["dlg_ffprobe_msg"])
            return
        self._tree.clear()
        self._results.clear()
        self._checked_tracks.clear()
        self._btn_remux.setEnabled(False)
        self._btn_extract.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._queued))
        self._progress.setValue(0)
        self._btn_scan.setEnabled(False)
        self._worker = VideoScanWorker(self._queued)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_progress(self, current, total, name):
        self._progress.setValue(current)
        self._lbl_status.setText(STRINGS["video_status_scanning"].format(current=current, total=total, name=name))

    def _on_scan_done(self, results):
        self._results = results
        self._progress.setVisible(False)
        self._btn_scan.setEnabled(True)
        self._populate_tree(results)
        total_ads = sum(t.ads_at_threshold(self._threshold)
                        for r in results for t in r.tracks)
        self._lbl_status.setText(
            f"Scan complete — {len(results)} video(s) · "
            f"{total_ads} ad block(s) found in embedded subtitles"
        )

    # ── Tree ──────────────────────────────────────────────────────────

    def _populate_tree(self, results):
        self._tree.blockSignals(True)
        self._tree.clear()
        t = self._threshold
        for result in results:
            root_item = QTreeWidgetItem([result.path.name])
            root_item.setData(0, Qt.ItemDataRole.UserRole, ("video", result))
            if result.error:
                root_item.setForeground(0, QColor("#888888"))
                root_item.setText(0, f"✕  {result.path.name}  — {result.error}")
            else:
                has_ads  = any(tr.ads_at_threshold(t) > 0 for tr in result.tracks)
                has_warn = any(tr.warnings_at_threshold(t) > 0 for tr in result.tracks)
                cleaning_opts = load_cleaning_options()
                has_opts_root = (
                    cleaning_opts.any_enabled() and
                    any(
                        tr.subtitle is not None and
                        any(block_will_be_removed(b.content, cleaning_opts)
                            for b in tr.subtitle.blocks)
                        for tr in result.tracks
                    )
                )
                color = RED if has_ads else (ORANGE if has_warn else (ACCENT if has_opts_root else FG2))
                root_item.setForeground(0, QColor(color))
                for track in result.tracks:
                    status = track.status_at_threshold(t)
                    tc     = STATUS_COLORS.get(status, FG2)
                    icon   = {"ADS":"✕","WARN":"⚠","CLEAN":"✓","IMAGE":"◻"}.get(status,"·")
                    track_item = QTreeWidgetItem([f"{icon}  {track.display_name}"])
                    # Override color to blue if track has opts but no ads/warns
                    if status == "CLEAN" and cleaning_opts.any_enabled() and track.subtitle:
                        if any(block_will_be_removed(b.content, cleaning_opts)
                               for b in track.subtitle.blocks):
                            tc = ACCENT
                    track_item.setForeground(0, QColor(tc))
                    track_item.setData(0, Qt.ItemDataRole.UserRole,
                                       ("track", result, track))
                    # Checkbox on flagged tracks or tracks with cleaning opt hits
                    has_opts = (
                        track.subtitle is not None and
                        cleaning_opts.any_enabled() and
                        any(block_will_be_removed(b.content, cleaning_opts)
                            for b in track.subtitle.blocks)
                    )
                    if (track.is_text and not track.scan_error and
                            (track.ads_at_threshold(t) > 0 or
                             track.warnings_at_threshold(t) > 0 or
                             has_opts)):
                        track_item.setCheckState(0, Qt.CheckState.Unchecked)
                    root_item.addChild(track_item)
            self._tree.addTopLevelItem(root_item)
            root_item.setExpanded(True)
        self._tree.blockSignals(False)

    def _on_item_checked(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "track":
            return
        result: VideoScanResult = data[1]
        track:  SubtitleTrack   = data[2]
        key = (id(result), track.track_num)
        if item.checkState(0) == Qt.CheckState.Checked:
            self._checked_tracks[key] = (result, track)
        else:
            self._checked_tracks.pop(key, None)
        self._refresh_remux_button()

    def _refresh_remux_button(self):
        n = len(self._checked_tracks)
        if n == 0:
            self._lbl_selected.setText("Check boxes on flagged tracks to select for cleaning")
            self._btn_remux.setEnabled(False)
            self._btn_extract.setEnabled(False)
            return
        mkv_count = sum(
            1 for r, _ in self._checked_tracks.values()
            if r.path.suffix.lower() == ".mkv"
        )
        mp4_count = sum(
            1 for r, _ in self._checked_tracks.values()
            if r.path.suffix.lower() in (".mp4", ".m4v")
        )
        remuxable = mkv_count + mp4_count
        self._lbl_selected.setText(
            f"{n} track(s) selected  ·  "
            f"{mkv_count} MKV  ·  {mp4_count} MP4  ·  "
            f"{n - remuxable} other (extract only)"
        )
        self._btn_extract.setEnabled(ffmpeg_available() and n > 0)
        # MKV needs mkvmerge; MP4 only needs ffmpeg (already required)
        can_remux = (mkv_count > 0 and mkvmerge_available()) or                     (mp4_count > 0 and ffmpeg_available())
        self._btn_remux.setEnabled(can_remux)

    # ── Detail pane ───────────────────────────────────────────────────

    def _on_tree_selection(self, current, previous):
        if current is None:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data[0] == "video":
            self._current_result = data[1]
            self._current_track  = None
            self._detail_text.setHtml(_video_html(data[1], self._threshold))
            # Show button if this video has any image tracks
            has_image = any(t.is_image for t in data[1].tracks)
            self._btn_open_image_subs.setVisible(has_image)
        elif data[0] == "track":
            self._current_result = data[1]
            self._current_track  = data[2]
            self._detail_text.setHtml(
                _track_html(data[1], data[2], self._threshold)
            )
            # Show button whenever the selected track is image-based
            self._btn_open_image_subs.setVisible(data[2].is_image)

    def _open_current_in_image_subs(self):
        if self._current_result:
            self.open_in_image_subs.emit(self._current_result.path)

    def _on_detail_link(self, url):
        """Handle 'keep:block_id' links from the detail pane."""
        url_str = url.toString()
        if not url_str.startswith("keep:"):
            return
        block_id = int(url_str[5:])
        # Find the block by id() and toggle its _kept flag
        if self._current_track and self._current_track.subtitle:
            for b in self._current_track.subtitle.blocks:
                if id(b) == block_id:
                    b._kept = not getattr(b, '_kept', False)
                    break
        # Refresh detail pane
        if self._current_result and self._current_track:
            self._detail_text.setHtml(
                _track_html(self._current_result, self._current_track,
                            self._threshold)
            )

    # ── Extract & Save ────────────────────────────────────────────────

    def _extract_selected(self):
        if not self._checked_tracks:
            return
        errors = []
        saved  = 0
        for result, track in self._checked_tracks.values():
            dest_dir = result.path.parent
            ct, err = extract_and_clean_track(
                result.path, track, dest_dir,
                remove_warnings=self._chk_warnings.isChecked(),
            )
            if err:
                errors.append(f"{result.path.name} track {track.track_num}: {err}")
            else:
                # Apply global cleaning options to extracted subtitle
                if ct and ct.cleaned_path.exists():
                    from core import load_subtitle, write_subtitle
                    opts = load_cleaning_options()
                    if opts.any_enabled():
                        sub = load_subtitle(ct.cleaned_path)
                        apply_cleaning_options(sub, opts)  # report not shown for extract
                        write_subtitle(sub, dest=ct.cleaned_path)
                saved += 1

        if errors:
            QMessageBox.warning(self, STRINGS["dlg_extractions_failed"],
                                f"{saved} succeeded.\n\n" + "\n".join(errors))
        else:
            QMessageBox.information(
                self, "Done",
                f"{saved} subtitle file(s) extracted and saved next to their video files.\n\n"
                f"Most media players will automatically detect external subtitle files."
            )

    # ── Clean & Remux ─────────────────────────────────────────────────

    def _remux_selected(self):
        if not self._checked_tracks:
            return
        if not mkvmerge_available():
            QMessageBox.warning(self, STRINGS["dlg_mkvmerge_missing"], STRINGS["dlg_mkvmerge_missing_msg"])
            return

        by_video: Dict[Path, tuple] = {}
        skipped = []
        for result, track in self._checked_tracks.values():
            suffix = result.path.suffix.lower()
            if suffix == ".mkv" and not mkvmerge_available():
                skipped.append(f"{result.path.name} (MKV — mkvmerge not found)")
                continue
            if suffix not in (".mkv", ".mp4", ".m4v"):
                skipped.append(f"{result.path.name} (unsupported format: {suffix})")
                continue
            if result.path not in by_video:
                by_video[result.path] = (result, [])
            by_video[result.path][1].append(track)

        if skipped and not by_video:
            QMessageBox.warning(self, "Nothing to remux",
                                "No supported files selected.\n\n" + "\n".join(skipped))
            return

        track_count = sum(len(tracks) for _, tracks in by_video.values())
        backup_note = ("A backup file will be created for each video."
                       if self._chk_backup.isChecked()
                       else "The original file will be OVERWRITTEN with no backup.")
        answer = QMessageBox.question(
            self, "Confirm Clean & Remux",
            f"Clean and remux {track_count} track(s) across {len(by_video)} video file(s).\n\n"
            f"{backup_note}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        errors = []
        successes = 0
        for video_path, (result, tracks) in by_video.items():
            prog_dlg = RemuxProgressDialog(self)
            prog_dlg.show()
            self._remux_worker = RemuxWorker(
                video_path=video_path,
                all_tracks=result.tracks,
                tracks_to_clean=tracks,
                make_backup=self._chk_backup.isChecked(),
                remove_warnings=self._chk_warnings.isChecked(),
            )
            self._remux_worker.status_update.connect(prog_dlg.update_status)
            result_holder = [None]

            def on_done(r, dlg=prog_dlg, holder=result_holder):
                holder[0] = r
                dlg.done_ok() if r.success else dlg.done_fail()
                dlg.accept()

            self._remux_worker.finished.connect(on_done)
            self._remux_worker.start()
            prog_dlg.exec()
            remux_result = result_holder[0]
            if remux_result and remux_result.success:
                successes += 1
            elif remux_result:
                errors.append(f"{video_path.name}: {remux_result.error}")

        if errors:
            QMessageBox.warning(self, "Some remuxes failed",
                                f"{successes} succeeded.\n\n" + "\n".join(errors))
        else:
            QMessageBox.information(
                self, "Done",
                f"{successes} MKV file(s) cleaned and remuxed successfully."
            )

        # Clear checkboxes
        self._checked_tracks.clear()
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            for j in range(root.childCount()):
                child = root.child(j)
                if child.checkState(0) != Qt.CheckState.Unchecked:
                    child.setCheckState(0, Qt.CheckState.Unchecked)
        self._tree.blockSignals(False)
        self._refresh_remux_button()

    # ── Public API ────────────────────────────────────────────────────

    def load_paths(self, paths):
        video_paths = [p for p in paths if p.suffix.lower() in VIDEO_EXTENSIONS]
        if video_paths:
            self._add_files(video_paths)
