"""
Image Subs panel — OCR pipeline for PGS/VOBSUB subtitle tracks.

Accepts a video file (drag-drop, browse, or handed off from Video Scan),
lists image-based subtitle tracks, and lets the user scan them with
Tesseract OCR. Cleaned results can be saved as .srt or remuxed back into
the video replacing the original image track.

Phase 3: shell — file loading, track listing, Tesseract availability gating.
Phase 4: OCR wiring — QThread worker, per-track progress, results display.
Phase 5: output options (Save as .srt, Remux, keep-original checkbox).
Phase 6: wired from Video Scan via open_in_image_subs signal.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QProgressBar, QFileDialog, QFrame, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
    QTreeWidget, QTreeWidgetItem, QSizePolicy, QCheckBox, QSlider,
)

from core.ffprobe import probe_video, SubtitleTrack, VIDEO_EXTENSIONS
from core.ocr import tesseract_available, ocr_track
from gui.settings_dialog import load_default_sensitivity, load_cleaning_options
from gui.strings import STRINGS
from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW
from core import block_will_be_removed
from .settings_dialog import get_font_pt as _get_fp, get_font_pt_small as _get_fps, get_font_pt_tiny as _get_fpt

THRESHOLD_LABELS = {
    1: STRINGS["thresh_1"],
    2: STRINGS["thresh_2"],
    3: STRINGS["thresh_3"],
    4: STRINGS["thresh_4"],
    5: STRINGS["thresh_5"],
}


# ---------------------------------------------------------------------------
# HTML helpers  (mirrors video_panel.py style for consistency)
# ---------------------------------------------------------------------------

def _html_style() -> str:
    from .settings_dialog import get_font_pt as _fp
    fp  = _fp()
    body_px = round(fp * 1.3)
    sec_px  = round(fp * 1.1)
    ts_px   = round(fp * 1.2)
    return f"""<style>
  body {{ background:{BG2}; color:{FG}; font-family:Consolas,monospace;
          font-size:{body_px}px; margin:8px; }}
  .section  {{ color:{ACCENT}; font-size:{sec_px}px; text-transform:uppercase;
               letter-spacing:1px; margin-top:16px; margin-bottom:6px;
               border-bottom:1px solid {BORDER}; padding-bottom:3px; }}
  .meta-row {{ margin:3px 0; }}
  .meta-lbl {{ color:{FG2}; }}
  .meta-val {{ color:{FG}; font-weight:bold; }}
  .block-ad  {{ margin:3px 0; padding:5px 10px; background:#2a1a22;
                border-left:4px solid {RED}; }}
  .block-opt {{ margin:3px 0; padding:5px 10px; background:#1a1f2e;
                border-left:4px solid {ACCENT}; }}
  .block-warn{{ margin:3px 0; padding:5px 10px; background:#231f15;
                border-left:4px solid {ORANGE}; }}
  .tag-ad    {{ color:#ff9eb5; font-weight:bold; }}
  .tag-warn  {{ color:#ffc990; font-weight:bold; }}
  .ts        {{ color:#7dcfff; font-size:{ts_px}px; }}
  .ad-text   {{ color:#ff9eb5; }}
  .opt-text  {{ color:#89b4fa; }}
  .warn-text {{ color:#ffc990; }}
  .reason    {{ color:#565f89; font-size:{sec_px}px; margin-right:8px; }}
  .clean-msg {{ color:{GREEN}; margin-top:10px; }}
  .note      {{ color:{FG2}; font-size:{sec_px}px; font-style:italic; margin-top:8px; }}
  .warn-msg  {{ color:{ORANGE}; margin-top:8px; }}
  .ok        {{ color:{GREEN}; margin-top:8px; }}
  .scanning  {{ color:{ACCENT}; margin-top:8px; }}
</style>"""


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _track_meta_rows(track: SubtitleTrack) -> str:
    """Metadata rows shared between pre-scan and post-scan views."""
    parts = []

    def row(lbl, val, color=None):
        vs = f' style="color:{color}"' if color else ''
        parts.append(
            f'<div class="meta-row"><span class="meta-lbl">{lbl}&nbsp;</span>'
            f'<span class="meta-val"{vs}>{_esc(val)}</span></div>'
        )

    row("Codec:", track.codec_display)
    row("Language:", track.language if track.language != "und" else "Unknown")
    if track.title:
        row("Title:", track.title)
    row("Forced:", "Yes" if track.forced else "No")
    row("Default:", "Yes" if track.default else "No")
    row("Stream index:", str(track.index))
    return "\n".join(parts)


def _pre_scan_html(track: SubtitleTrack) -> str:
    parts = [_html_style(), '<div class="section">Image Subtitle Track</div>']
    parts.append(_track_meta_rows(track))
    if tesseract_available():
        parts.append(f'<div class="ok">{STRINGS["img_tess_ok"]}</div>')
    else:
        parts.append(
            f'<div class="warn-msg">{STRINGS["img_tess_missing_detail"]}</div>'
        )
    return "\n".join(parts)


def _scanning_html(track: SubtitleTrack, status: str) -> str:
    parts = [_html_style(), '<div class="section">Image Subtitle Track</div>']
    parts.append(_track_meta_rows(track))
    parts.append(f'<div class="scanning">⟳ {_esc(status)}</div>')
    return "\n".join(parts)


def _post_scan_html(track: SubtitleTrack, threshold: int = 3) -> str:
    parts = [_html_style(), '<div class="section">Image Subtitle Track</div>']
    parts.append(_track_meta_rows(track))

    if track.scan_error:
        parts.append(
            f'<div class="warn-msg">⚠ Scan error: {_esc(track.scan_error)}</div>'
        )
        return "\n".join(parts)

    sub = track.subtitle
    cleaning_opts = load_cleaning_options()

    if sub is not None:
        ads   = [b for b in sub.blocks if b.regex_matches >= threshold]
        warns = [b for b in sub.blocks
                 if b.regex_matches == threshold - 1 and threshold > 1]
        clean_opt_blocks = [
            b for b in sub.blocks
            if b.regex_matches < threshold
            and block_will_be_removed(b.content, cleaning_opts)
        ]
    else:
        ads, warns, clean_opt_blocks = [], [], []

    def row(lbl, val, color=None):
        vs = f' style="color:{color}"' if color else ''
        parts.append(
            f'<div class="meta-row"><span class="meta-lbl">{lbl}&nbsp;</span>'
            f'<span class="meta-val"{vs}>{_esc(val)}</span></div>'
        )

    parts.append(f'<div class="section">{STRINGS["img_ocr_results"]}</div>')
    row("Total blocks:", str(track.total_blocks))
    row("Ad blocks:", str(len(ads)), color="#ff9eb5" if ads else GREEN)
    if clean_opt_blocks:
        row("Cleaning opts:", str(len(clean_opt_blocks)), color="#ff9eb5")
    row("Warnings:", str(len(warns)), color="#ffc990" if warns else None)

    if sub is not None and (ads or warns or clean_opt_blocks):
        parts.append('<div class="section">Flagged Blocks</div>')
        for b in ads + clean_opt_blocks + warns:
            is_ad        = b.regex_matches >= threshold
            is_clean_opt = b in clean_opt_blocks
            reasons_html = " ".join(
                f'<span class="reason">{_esc(h)}</span>'
                for h in dict.fromkeys(getattr(b, 'hints', []))
            )
            if is_clean_opt and not is_ad:
                div_class  = "block-opt"
                tag        = '<span style="color:#4e9eff;font-weight:bold">✕ OPT</span>'
                text_class = "opt-text"
            elif is_ad:
                div_class  = "block-ad"
                tag        = '<span class="tag-ad">✕ AD</span>'
                text_class = "ad-text"
            else:
                div_class  = "block-warn"
                tag        = '<span class="tag-warn">⚠ WARN</span>'
                text_class = "warn-text"

            parts.append(
                f'<div class="{div_class}">'
                f'{tag}&nbsp;<span class="ts">[{_esc(b.start)}]</span>'
                f'&nbsp;{reasons_html}<br>'
                f'<span class="{text_class}">{_esc(b.text[:120])}</span>'
                f'</div>'
            )
    elif track.total_blocks > 0:
        parts.append(f'<div class="clean-msg">{STRINGS["img_no_ads"]}</div>')

    return "\n".join(parts)


def _welcome_html() -> str:
    return (
        _html_style() +
        f'<div class="section">{STRINGS["tab_image_subs"]}</div>'
        f'<div class="note">{STRINGS["img_welcome_note"]}</div>'
    )


def _no_image_tracks_html() -> str:
    return (
        _html_style() +
        f'<div class="section">{STRINGS["tab_image_subs"]}</div>'
        f'<div class="note">{STRINGS["img_no_tracks_note"]}</div>'
    )


# ---------------------------------------------------------------------------
# OCR worker
# ---------------------------------------------------------------------------

class OcrWorker(QThread):
    """
    Runs ocr_track() for each track sequentially in a background thread.
    Emits per-track progress and the completed track on each finish.
    Never raises — ocr_track() captures errors into track.scan_error.
    """
    progress      = pyqtSignal(str)      # status message
    frame_progress = pyqtSignal(int, int) # (frames_done, total_frames)
    track_done    = pyqtSignal(object)   # SubtitleTrack after OCR
    finished      = pyqtSignal(list)     # List[SubtitleTrack] all done

    def __init__(self, video_path: Path, tracks: List[SubtitleTrack]):
        super().__init__()
        self.video_path    = video_path
        self.tracks        = tracks
        self._active_track: Optional[SubtitleTrack] = None

    def run(self):
        import time
        done = []
        for i, track in enumerate(self.tracks):
            self._active_track = track
            self.progress.emit(
                STRINGS["img_ocr_progress"].format(current=i+1, total=len(self.tracks), lang=track.language, codec=track.codec_display)
            )

            # Throttle frame_progress signals to at most one per 0.1s.
            # The thread pool in ocr.py calls frame_cb from multiple worker
            # threads, potentially hundreds of times per second. Crossing the
            # thread boundary on every call causes UI jank and wastes cycles.
            _last_emit = [0.0]  # mutable cell for closure

            def _frame_cb(frames_done, total, _le=_last_emit):
                now = time.monotonic()
                if now - _le[0] >= 0.1 or frames_done == total:
                    self.frame_progress.emit(frames_done, total)
                    _le[0] = now

            ocr_track(
                self.video_path,
                track,
                progress_cb=lambda msg: self.progress.emit(msg),
                frame_cb=_frame_cb,
            )
            self.track_done.emit(track)
            done.append(track)
        self.finished.emit(done)


# ---------------------------------------------------------------------------
# Drop zone
# ---------------------------------------------------------------------------

class ImageSubsDropZone(QFrame):
    file_dropped = pyqtSignal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(max(90, round(90 * _get_fp() / 11)))
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("🎬")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 18pt;")
        msg = QLabel(STRINGS["img_drop_label"])
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {FG2}; font-size: {_get_fp()}pt;")
        browse = QPushButton(STRINGS["img_btn_browse"])
        browse.setMaximumWidth(100)
        browse.setToolTip(STRINGS["tip_img_browse"])
        browse.clicked.connect(self._browse)
        layout.addWidget(icon)
        layout.addWidget(msg)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)

    def _browse(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video File", "", f"Video Files ({exts});;All Files (*)"
        )
        if path:
            self.file_dropped.emit(Path(path))

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                self.file_dropped.emit(p)
                return


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class ImageSubsPanel(QWidget):
    status_updated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path:    Optional[Path]          = None
        self._tracks:        List[SubtitleTrack]     = []
        self._current_track: Optional[SubtitleTrack] = None
        self._worker:        Optional[OcrWorker]     = None
        self._threshold:     int                     = load_default_sensitivity()
        self._status_text:   str                     = STRINGS["img_status_load"]
        self._build_ui()
        self._check_tools()

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Notices ───────────────────────────────────────────────────────
        # Tesseract missing — conditionally visible
        self._tess_notice = QLabel()
        self._tess_notice.setStyleSheet(
            f"color: {ORANGE}; background: transparent; border: 1px solid {ORANGE}55;"
            f"border-radius: 4px; padding: 6px 10px; font-size: {_get_fp()}pt;"
        )
        self._tess_notice.setWordWrap(True)
        self._tess_notice.setVisible(False)

        # ── Top control bar ───────────────────────────────────────────────
        ctrl = QHBoxLayout()
        self._btn_clear = QPushButton(STRINGS["img_btn_clear"])
        self._btn_clear.clicked.connect(self._clear)
        self._btn_clear.setEnabled(False)
        self._btn_clear.setToolTip(STRINGS["tip_img_clear"])
        self._lbl_file = QLabel(STRINGS["img_no_file"])
        self._lbl_file.setObjectName("file_status")
        self._lbl_file.setStyleSheet(f"color: {FG2};")
        self._btn_scan = QPushButton(STRINGS["img_btn_scan"])
        self._btn_scan.setObjectName("btn_clean_all")
        self._btn_scan.setEnabled(False)
        self._btn_scan.setToolTip(STRINGS["tip_img_scan"])
        self._btn_scan.clicked.connect(self._scan)
        ctrl.addWidget(self._btn_clear)
        ctrl.addWidget(self._lbl_file, stretch=1)
        ctrl.addWidget(self._btn_scan)

        # ── Progress / status ─────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(6)
        self._progress.setRange(0, 0)
        self._progress.setAccessibleName(STRINGS["img_btn_scan"])

        # ── Drop zone ─────────────────────────────────────────────────────
        self._drop_zone = ImageSubsDropZone()
        self._drop_zone.file_dropped.connect(self.load_video)

        # ── Splitter ──────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        lbl_tree = QLabel(STRINGS["img_lbl_tracks"])
        lbl_tree.setObjectName("section_label")

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setFont(QFont("Consolas", 11))
        self._tree.setIndentation(0)
        self._tree.currentItemChanged.connect(self._on_track_selected)
        self._tree.setAccessibleName(STRINGS["img_lbl_tracks"])

        action_bar = QHBoxLayout()
        # ── Sensitivity slider ────────────────────────────────────────────
        slider_bar = QHBoxLayout()
        slider_bar.setSpacing(8)
        lbl_sens = QLabel(STRINGS["sens_label"])
        lbl_sens.setStyleSheet(f"color: {FG2}; font-size: {_get_fps()}pt;")
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(1)
        self._slider.setMaximum(5)
        self._slider.setValue(self._threshold)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(1)
        self._slider.setFixedWidth(180)
        self._slider.setAccessibleName(STRINGS["sens_label"])
        self._slider.setAccessibleDescription(STRINGS["settings_sens_desc"])
        self._lbl_threshold = QLabel(THRESHOLD_LABELS.get(self._threshold, ""))
        self._lbl_threshold.setStyleSheet(f"color: {YELLOW}; font-size: {_get_fps()}pt;")
        self._slider.valueChanged.connect(self._on_threshold_changed)
        slider_bar.addWidget(lbl_sens)
        slider_bar.addWidget(self._slider)
        slider_bar.addWidget(self._lbl_threshold)
        slider_bar.addStretch()

        self._chk_backup = QCheckBox(STRINGS["img_chk_backup"])
        self._chk_backup.setChecked(True)
        self._chk_keep_original = QCheckBox(STRINGS["img_chk_keep_original"])
        self._chk_keep_original.setChecked(False)
        self._chk_keep_original.setToolTip(STRINGS["tip_img_keep_original"])
        self._btn_save_srt = QPushButton(STRINGS["img_btn_save_srt"])
        self._btn_save_srt.setObjectName("btn_keep")
        self._btn_save_srt.setEnabled(False)
        self._btn_save_srt.setToolTip(STRINGS["tip_img_save_srt"])
        self._btn_save_srt.clicked.connect(self._save_srt)
        self._btn_remux = QPushButton(STRINGS["img_btn_remux"])
        self._btn_remux.setObjectName("btn_save")
        self._btn_remux.setEnabled(False)
        self._btn_remux.setToolTip(STRINGS["tip_img_remux"])
        self._btn_remux.clicked.connect(self._remux)
        action_bar.addWidget(self._chk_backup)
        action_bar.addWidget(self._chk_keep_original)
        action_bar.addStretch()
        action_bar.addWidget(self._btn_save_srt)
        action_bar.addWidget(self._btn_remux)

        ll.addWidget(lbl_tree)
        ll.addWidget(self._tree, stretch=1)
        ll.addLayout(slider_bar)
        ll.addLayout(action_bar)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        lbl_detail = QLabel(STRINGS["img_lbl_detail"])
        lbl_detail.setObjectName("section_label")
        self._detail_stack = QStackedWidget()

        # Page 0 — HTML report (default)
        self._detail = QTextBrowser()
        self._detail.setOpenLinks(False)
        self._detail.setStyleSheet(
            f"background: {BG2}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        self._detail.setHtml(_welcome_html())
        self._detail_stack.addWidget(self._detail)        # index 0

        # Page 1 — Inline edit table (shown after OCR completes)
        self._edit_table = QTableWidget()
        self._edit_table.setColumnCount(3)
        self._edit_table.setHorizontalHeaderLabels(
            [STRINGS["tr_col_index"], STRINGS["tr_col_timestamp"], STRINGS["tr_col_text"]]
        )
        self._edit_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self._edit_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed)
        self._edit_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._edit_table.setColumnWidth(0, 42)
        self._edit_table.setColumnWidth(1, 210)
        self._edit_table.verticalHeader().setVisible(False)
        self._edit_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._edit_table.setAlternatingRowColors(True)
        self._edit_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.SelectedClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._edit_table.setStyleSheet(
            f"QTableWidget {{ background: {BG2}; color: {FG}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; }}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
            f"QTableWidget::item:selected {{ background: #2a3f5f; color: #ffffff; }}"
            f"QHeaderView::section {{ background: {BG2}; color: {FG2}; "
            f"border: none; border-bottom: 1px solid {BORDER}; "
            f"padding: 4px 6px; font-size: {_get_fps()}pt; }}"
        )
        self._edit_table.itemChanged.connect(self._on_cell_edited)
        self._detail_stack.addWidget(self._edit_table)    # index 1

        self._lbl_edit_hint = QLabel(STRINGS["tr_hint_edit"])
        self._lbl_edit_hint.setStyleSheet(
            f"color: {FG2}; font-size: {_get_fps()}pt; font-style: italic; padding: 2px 0;"
        )
        self._lbl_edit_hint.setWordWrap(True)
        self._lbl_edit_hint.setVisible(False)

        rl.addWidget(lbl_detail)
        rl.addWidget(self._detail_stack, stretch=1)
        rl.addWidget(self._lbl_edit_hint)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([340, 660])

        root.addWidget(self._tess_notice)
        root.addLayout(ctrl)
        root.addWidget(self._drop_zone)
        root.addWidget(self._progress)
        root.addWidget(splitter, stretch=1)

        # Tab order
        self.setTabOrder(self._btn_clear,        self._btn_scan)
        self.setTabOrder(self._btn_scan,         self._tree)
        self.setTabOrder(self._tree,             self._slider)
        self.setTabOrder(self._slider,           self._chk_backup)
        self.setTabOrder(self._chk_backup,       self._chk_keep_original)
        self.setTabOrder(self._chk_keep_original, self._btn_save_srt)
        self.setTabOrder(self._btn_save_srt,     self._btn_remux)

    # ── Status helper ─────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        """Emit status to the app-level bar via signal."""
        self._status_text = msg
        self.status_updated.emit(msg)

    def get_status(self) -> str:
        """Return the current status text (used by MainWindow on tab switch)."""
        return self._status_text

    # ── Tool checks ───────────────────────────────────────────────────────

    def _check_tools(self):
        if not tesseract_available():
            self._tess_notice.setText(
                STRINGS["img_tess_notice"]
            )
            self._tess_notice.setVisible(True)

    # ── File loading ──────────────────────────────────────────────────────

    def load_video(self, path: Path):
        """Public entry point — called by browse, drop, or Video Scan handoff."""
        self._video_path = path
        self._lbl_file.setText(path.name)
        self._lbl_file.setStyleSheet(f"color: {FG};")
        self._btn_clear.setEnabled(True)
        self._set_status(STRINGS["img_status_probing"].format(name=path.name))
        self._tree.clear()
        self._detail.setHtml(_welcome_html())
        self._btn_scan.setEnabled(False)
        self._btn_save_srt.setEnabled(False)
        self._btn_remux.setEnabled(False)
        self._drop_zone.setVisible(False)

        # "Keep original" only works for MKV (mkvmerge can append tracks)
        is_mkv = path.suffix.lower() == ".mkv"
        self._chk_keep_original.setEnabled(is_mkv)
        if not is_mkv:
            self._chk_keep_original.setChecked(False)

        tracks, err = probe_video(path)
        if err:
            self._set_status(f"Error: {err}")
            return

        image_tracks = [t for t in tracks if t.is_image]
        self._tracks = image_tracks

        if not image_tracks:
            self._set_status(STRINGS["img_status_no_tracks"])
            self._detail.setHtml(_no_image_tracks_html())
            return

        self._set_status(
            STRINGS["img_status_found"].format(n=len(image_tracks))
            if tesseract_available() else
            STRINGS["img_status_no_tess"].format(n=len(image_tracks))
        )
        self._populate_tree(image_tracks)
        self._btn_scan.setEnabled(tesseract_available())

    def _populate_tree(self, tracks: List[SubtitleTrack]):
        self._tree.clear()
        for track in tracks:
            lang  = track.language if track.language != "und" else "?"
            label = f"Track {track.track_num}  [{lang}]  ({track.codec_display})"
            if track.forced:  label += "  FORCED"
            if track.default: label += "  DEFAULT"
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, track)
            item.setForeground(0, QColor(FG2))
            self._tree.addTopLevelItem(item)
        self._tree.setCurrentItem(self._tree.topLevelItem(0))

    def _update_tree_item_color(self, track: SubtitleTrack):
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) is track:
                if track.scan_error:
                    item.setForeground(0, QColor("#888888"))
                elif track.ad_count > 0:
                    item.setForeground(0, QColor(RED))
                elif track.warning_count > 0:
                    item.setForeground(0, QColor(ORANGE))
                else:
                    item.setForeground(0, QColor(GREEN))
                break

    def _refresh_tree_colors(self):
        """Recolor all tree items based on the current threshold.

        _update_tree_item_color() reads track.ad_count which is fixed at scan
        time. This method recomputes directly from block regex_matches so the
        tree reflects whichever threshold the slider is currently at.
        """
        t = self._threshold
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            track = item.data(0, Qt.ItemDataRole.UserRole)
            if track is None:
                continue
            if track.scan_error:
                item.setForeground(0, QColor("#888888"))
            elif track.subtitle is not None:
                sub = track.subtitle
                ads   = sum(1 for b in sub.blocks if b.regex_matches >= t)
                warns = sum(1 for b in sub.blocks
                            if b.regex_matches == t - 1 and t > 1)
                if ads > 0:
                    item.setForeground(0, QColor(RED))
                elif warns > 0:
                    item.setForeground(0, QColor(ORANGE))
                else:
                    item.setForeground(0, QColor(GREEN))
            # tracks that haven't been scanned yet keep their default FG2 color

    def _clear(self):
        self._video_path    = None
        self._tracks        = []
        self._current_track = None
        self._tree.clear()
        self._lbl_file.setText("No file loaded")
        self._lbl_file.setStyleSheet(f"color: {FG2};")
        self._set_status("Load a video file to begin.")
        self._detail.setHtml(_welcome_html())
        self._edit_table.setRowCount(0)
        self._detail_stack.setCurrentIndex(0)
        self._lbl_edit_hint.setVisible(False)
        self._btn_clear.setEnabled(False)
        self._btn_scan.setEnabled(False)
        self._btn_save_srt.setEnabled(False)
        self._btn_remux.setEnabled(False)
        self._drop_zone.setVisible(True)

    # ── Inline editing ───────────────────────────────────────────────────

    def _populate_edit_table(self, track):
        """Fill the edit table from a scanned track's subtitle blocks."""
        import re as _re
        blocks = track.subtitle.blocks if track.subtitle else []
        self._edit_table.blockSignals(True)
        self._edit_table.setRowCount(len(blocks))
        for row, block in enumerate(blocks):
            idx_item = QTableWidgetItem(str(getattr(block, 'original_index', row + 1)))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            idx_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            idx_item.setForeground(QColor(FG2))
            self._edit_table.setItem(row, 0, idx_item)

            ts = f"{block.start} → {block.end}"
            ts_item = QTableWidgetItem(ts)
            ts_item.setFlags(ts_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ts_item.setForeground(QColor("#7dcfff"))
            self._edit_table.setItem(row, 1, ts_item)

            txt_item = QTableWidgetItem(block.content)
            self._edit_table.setItem(row, 2, txt_item)

        self._edit_table.resizeRowsToContents()
        self._edit_table.blockSignals(False)
        self._detail_stack.setCurrentIndex(1)
        self._lbl_edit_hint.setVisible(True)

    def _on_cell_edited(self, item: QTableWidgetItem):
        """Sync an edited text cell back to the subtitle data model."""
        import re as _re
        if item.column() != 2:
            return
        if not self._current_track or not self._current_track.subtitle:
            return
        row = item.row()
        blocks = self._current_track.subtitle.blocks
        if row < 0 or row >= len(blocks):
            return
        block = blocks[row]
        new_text = item.text()
        block.content = new_text
        block.clean_content = _re.sub(r"[\s.,:_-]", "", new_text)

    # ── Track selection ───────────────────────────────────────────────────

    def _on_track_selected(self, current, previous):
        if current is None:
            return
        track = current.data(0, Qt.ItemDataRole.UserRole)
        if track is None:
            return
        self._current_track = track
        if track.subtitle is not None or track.scan_error:
            self._detail.setHtml(_post_scan_html(track, self._threshold))
            self._btn_save_srt.setEnabled(track.subtitle is not None)
            self._btn_remux.setEnabled(
                track.subtitle is not None
                and self._video_path is not None
                and self._video_path.suffix.lower() in (".mkv", ".mp4", ".m4v")
            )
            if track.subtitle is not None and track.subtitle.blocks:
                self._populate_edit_table(track)
            else:
                self._detail_stack.setCurrentIndex(0)
                self._lbl_edit_hint.setVisible(False)
        else:
            self._detail.setHtml(_pre_scan_html(track))
            self._detail_stack.setCurrentIndex(0)
            self._lbl_edit_hint.setVisible(False)

    # ── Scan ──────────────────────────────────────────────────────────────

    def _scan(self):
        if not self._current_track or not self._video_path:
            return
        if self._worker and self._worker.isRunning():
            return

        self._btn_scan.setEnabled(False)
        
        self._btn_clear.setEnabled(False)
        self._btn_save_srt.setEnabled(False)
        self._btn_remux.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)   # indeterminate until first frame arrives
        self._set_status(STRINGS["img_status_starting"])

        self._worker = OcrWorker(self._video_path, [self._current_track])
        self._worker.progress.connect(self._on_ocr_progress)
        self._worker.frame_progress.connect(self._on_frame_progress)
        self._worker.track_done.connect(self._on_track_done)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.start()

    def _on_frame_progress(self, done: int, total: int):
        if self._progress.maximum() != total:
            self._progress.setRange(0, total)
        self._progress.setValue(done)

    def _on_threshold_changed(self, value: int):
        self._threshold = value
        self._lbl_threshold.setText(THRESHOLD_LABELS.get(value, str(value)))
        # Re-render the HTML report for the current track if scanned.
        # The edit table (page 1) is unaffected — user edits are preserved.
        if self._current_track and self._current_track.subtitle is not None:
            self._detail.setHtml(_post_scan_html(self._current_track, self._threshold))
        # Recolor ALL scanned tree items at the new threshold
        self._refresh_tree_colors()

    def _on_ocr_progress(self, msg: str):
        self._set_status(msg)
        # Only update detail pane if the currently selected track has no
        # results yet — don't clobber a track that already finished
        if (self._current_track is not None
                and self._current_track.subtitle is None
                and not self._current_track.scan_error
                and self._worker is not None
                and self._worker._active_track is self._current_track):
            self._detail.setHtml(_scanning_html(self._current_track, msg))

    def _on_track_done(self, track: SubtitleTrack):
        self._update_tree_item_color(track)
        # Refresh detail pane if this is the currently selected track
        # Use track_num for comparison — object identity can be unreliable
        # across signal boundaries in some Qt/PyQt versions
        if (self._current_track is not None
                and self._current_track.track_num == track.track_num):
            self._detail.setHtml(_post_scan_html(track, self._threshold))
            self._btn_save_srt.setEnabled(track.subtitle is not None)
            self._btn_remux.setEnabled(
                track.subtitle is not None
                and self._video_path is not None
                and self._video_path.suffix.lower() in (".mkv", ".mp4", ".m4v")
            )
            if track.subtitle is not None and track.subtitle.blocks:
                self._populate_edit_table(track)

    def _on_scan_finished(self, tracks: List[SubtitleTrack]):
        self._progress.setVisible(False)
        self._btn_scan.setEnabled(tesseract_available())
        self._btn_clear.setEnabled(True)

        # Refresh detail pane with final results for selected track
        if self._current_track is not None:
            matched = next(
                (t for t in tracks if t.track_num == self._current_track.track_num),
                None
            )
            if matched is not None:
                self._detail.setHtml(_post_scan_html(matched, self._threshold))
                self._btn_save_srt.setEnabled(matched.subtitle is not None)
                self._btn_remux.setEnabled(
                    matched.subtitle is not None
                    and self._video_path is not None
                    and self._video_path.suffix.lower() in (".mkv", ".mp4", ".m4v")
                )
                if matched.subtitle is not None and matched.subtitle.blocks:
                    self._populate_edit_table(matched)

        scanned  = len(tracks)
        with_ads = sum(1 for t in tracks if t.ad_count > 0)
        errors   = sum(1 for t in tracks if t.scan_error)

        parts = [STRINGS["img_status_scanned"].format(n=scanned)]
        if with_ads:
            parts.append(STRINGS["img_status_with_ads"].format(n=with_ads))
        if errors:
            parts.append(STRINGS["img_status_errors"].format(n=errors))
        self._set_status("  ".join(parts))

    # ── Output (Phase 5) ─────────────────────────────────────────────────

    def _save_srt(self):
        """Write the OCR'd subtitle as a .srt file next to the video."""
        track = self._current_track
        if not track or not track.subtitle or not self._video_path:
            return

        lang = track.language if track.language and track.language != "und" else ""
        lang_suffix = f".{lang}" if lang else ""
        out_name = f"{self._video_path.stem}{lang_suffix}.srt"
        out_path = self._video_path.parent / out_name

        # Collision handling
        if out_path.exists():
            stem = out_path.stem
            counter = 2
            while out_path.exists():
                out_path = self._video_path.parent / f"{stem}.{counter}.srt"
                counter += 1

        try:
            from core.subtitle import write_subtitle, SubtitleFormat
            # Ensure the subtitle is marked as SRT before writing
            track.subtitle.fmt = SubtitleFormat.SRT
            write_subtitle(track.subtitle, dest=out_path)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, STRINGS["img_dlg_save_failed"], str(e))
            return

        self._set_status(STRINGS["img_status_saved"].format(name=out_path.name))

    def _remux(self):
        """Remux the OCR'd subtitle back into the video, replacing or alongside the image track."""
        from PyQt6.QtWidgets import QMessageBox
        import tempfile

        track = self._current_track
        if not track or not track.subtitle or not self._video_path:
            return

        suffix = self._video_path.suffix.lower()
        if suffix not in (".mkv", ".mp4", ".m4v"):
            QMessageBox.warning(self, STRINGS["img_dlg_unsupported"],
                                STRINGS["img_dlg_unsupported_msg"])
            return

        from core.mkvtoolnix import (
            mkvmerge_available, remux_with_cleaned_tracks,
            remux_mp4_with_ffmpeg, CleanedTrack, RemuxResult,
        )
        from core.ffprobe import probe_video, ffmpeg_available
        from core.subtitle import write_subtitle, SubtitleFormat

        is_mkv = suffix == ".mkv"
        is_mp4 = suffix in (".mp4", ".m4v")

        if is_mkv and not mkvmerge_available():
            QMessageBox.warning(self, STRINGS["img_dlg_mkv_missing"],
                                STRINGS["img_dlg_mkv_missing_msg"])
            return
        if is_mp4 and not ffmpeg_available():
            QMessageBox.warning(self, STRINGS["img_dlg_mkv_missing"],
                                "ffmpeg is required for MP4 remuxing. "
                                "Install FFmpeg or set its path in Settings → Paths.")
            return

        keep_original = self._chk_keep_original.isChecked() and is_mkv
        make_backup   = self._chk_backup.isChecked()

        all_tracks, err = probe_video(self._video_path)
        if err:
            QMessageBox.critical(self, STRINGS["img_dlg_probe_failed"], err)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_srt = Path(tmpdir) / f"ocr_track{track.track_num}.srt"
            track.subtitle.fmt = SubtitleFormat.SRT
            try:
                write_subtitle(track.subtitle, dest=tmp_srt)
            except Exception as e:
                QMessageBox.critical(self, STRINGS["img_dlg_write_failed"], str(e))
                return

            if not tmp_srt.exists() or tmp_srt.stat().st_size == 0:
                QMessageBox.critical(self, STRINGS["img_dlg_write_failed"],
                                     STRINGS["img_dlg_empty_srt"])
                return

            cleaned_track = CleanedTrack(
                track=track,
                cleaned_path=tmp_srt,
                original_blocks=track.total_blocks,
                removed_blocks=track.ad_count,
            )

            self._btn_remux.setEnabled(False)
            self._btn_save_srt.setEnabled(False)
            self._btn_scan.setEnabled(False)
            self._progress.setVisible(True)
            self._set_status(STRINGS["img_status_remuxing"])

            if keep_original:
                result = self._remux_keep_original(
                    all_tracks, cleaned_track, make_backup, tmp_srt
                )
            elif is_mkv:
                result = remux_with_cleaned_tracks(
                    self._video_path,
                    all_tracks,
                    [cleaned_track],
                    make_backup=make_backup,
                    progress_cb=lambda msg: self._set_status(msg),
                )
            else:
                # MP4/M4V — use ffmpeg
                result = remux_mp4_with_ffmpeg(
                    self._video_path,
                    all_tracks,
                    [cleaned_track],
                    make_backup=make_backup,
                    progress_cb=lambda msg: self._set_status(msg),
                )

        self._progress.setVisible(False)
        self._btn_remux.setEnabled(True)
        self._btn_save_srt.setEnabled(True)
        self._btn_scan.setEnabled(tesseract_available())

        if result.success:
            backup_msg = f"  Backup: {result.backup_path.name}" if result.backup_path else ""
            self._set_status((STRINGS["img_status_remux_backup"].format(name=result.backup_path.name) if result.backup_path else STRINGS["img_status_remux_ok"]))
        else:
            QMessageBox.critical(self, STRINGS["img_dlg_remux_failed"], result.error)
            self._set_status(STRINGS["img_status_remux_fail"])

    def _remux_keep_original(self, all_tracks, cleaned_track, make_backup, srt_path):
        """
        Remux keeping the original image track AND adding the new SRT alongside it.
        Passes --subtitle-tracks with ALL original indices so nothing is dropped,
        then appends the new SRT as an extra input.
        """
        import subprocess
        import shutil
        import tempfile
        from core.mkvtoolnix import (
            get_mkvmerge_path, RemuxResult,
            _SUBPROCESS_FLAGS,
        )
        from core.cleaner_options import language_display_name

        mkvmerge = get_mkvmerge_path()
        track    = cleaned_track.track

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_out = Path(tmpdir) / f"_remux_{self._video_path.name}"

            cmd = [mkvmerge, "-o", str(tmp_out)]

            # Keep everything from original including all subtitle tracks
            cmd += [str(self._video_path)]

            # Append new SRT with metadata
            lang = track.language
            if lang and lang != "und":
                cmd += ["--language", f"0:{lang}"]
            from core.cleaner_options import language_display_name
            clean_title = language_display_name(lang) if lang else ""
            if clean_title:
                cmd += ["--track-name", f"0:{clean_title} (OCR)"]
            cmd += ["--forced-display-flag", "0:0"]
            cmd += ["--default-track-flag",  "0:0"]
            cmd.append(str(srt_path))

            try:
                proc = subprocess.run(
                    cmd, capture_output=True, timeout=600, **_SUBPROCESS_FLAGS
                )
            except subprocess.TimeoutExpired:
                return RemuxResult(success=False, error="mkvmerge timed out")
            except Exception as e:
                return RemuxResult(success=False, error=f"mkvmerge failed: {e}")

            if proc.returncode == 2:
                err = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")[:400]
                return RemuxResult(success=False, error=f"mkvmerge error: {err}")

            if not tmp_out.exists() or tmp_out.stat().st_size == 0:
                return RemuxResult(success=False, error="mkvmerge produced empty output")

            # Atomic swap
            backup_path = None
            if make_backup:
                backup_path = self._video_path.with_suffix(".backup.mkv")
                counter = 1
                while backup_path.exists():
                    backup_path = self._video_path.with_name(
                        f"{self._video_path.stem}.backup{counter}.mkv"
                    )
                    counter += 1
                try:
                    self._video_path.rename(backup_path)
                except Exception as e:
                    return RemuxResult(success=False, error=f"Could not create backup: {e}")
            else:
                try:
                    self._video_path.unlink()
                except Exception as e:
                    return RemuxResult(success=False, error=f"Could not remove original: {e}")

            try:
                shutil.move(str(tmp_out), str(self._video_path))
            except Exception as e:
                if backup_path and backup_path.exists():
                    try:
                        backup_path.rename(self._video_path)
                    except Exception:
                        pass
                return RemuxResult(success=False, error=f"Could not move remuxed file: {e}")

        from core.mkvtoolnix import RemuxResult
        return RemuxResult(success=True, output_path=self._video_path, backup_path=backup_path)

    # ── Public API ────────────────────────────────────────────────────────

    def set_folder(self, folder: str):
        """Called by session restore — no-op for this panel."""
        pass
