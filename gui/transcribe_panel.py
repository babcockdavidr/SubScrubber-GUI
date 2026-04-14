"""
gui/transcribe_panel.py — Whisper audio transcription tab.

Accepts a video file (drag-drop or browse), lets the user choose a Whisper
model and language, and transcribes the audio track to subtitle blocks using
faster-whisper.  The existing ad-detection engine runs on the output
unchanged.  Results can be saved as .srt or remuxed back into the video.

Layout mirrors image_subs_panel.py exactly:
  - Notices stack at top (faster-whisper missing first, experimental second)
  - Single ctrl bar: Clear | file label | Model | Language | Transcribe Audio
  - Drop zone collapses when file is loaded
  - Progress bar + status label
  - Splitter: left (options + action bar) | right (HTML detail)

Path/model-dir resolution → core/whisper.py
ffmpeg/ffprobe paths       → core/ffprobe.py
mkvmerge path              → core/mkvtoolnix.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QProgressBar, QFileDialog, QFrame, QSplitter,
    QComboBox, QCheckBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)

from core.ffprobe import VIDEO_EXTENSIONS
from core.whisper import (
    faster_whisper_available, MODELS, list_downloaded_models,
    transcribe, TranscribeResult, segments_to_srt,
)
from gui.strings import STRINGS
from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW


# ISO language codes for the language selector.
# Plain list of (code, display_name). "auto" label is filled from STRINGS
# at widget construction time to pick up the active language.
# Native language names are used for all others — language names don't need
# translation since users recognise their own language name.
_LANGUAGES = [
    ("auto", None),          # filled from STRINGS["tr_lang_auto"] at build time
    ("en",   "English"),
    ("es",   "Español"),
    ("fr",   "Français"),
    ("de",   "Deutsch"),
    ("it",   "Italiano"),
    ("pt",   "Português"),
    ("nl",   "Nederlands"),
    ("pl",   "Polski"),
    ("ru",   "Русский"),
    ("sv",   "Svenska"),
    ("ar",   "العربية"),
    ("zh",   "中文"),
    ("ja",   "日本語"),
    ("ko",   "한국어"),
    ("hi",   "हिन्दी"),
    ("tr",   "Türkçe"),
    ("he",   "עברית"),
    ("id",   "Bahasa Indonesia"),
]


# ---------------------------------------------------------------------------
# HTML helpers — identical style to image_subs_panel.py
# ---------------------------------------------------------------------------

HTML_STYLE = f"""<style>
  body {{ background:{BG2}; color:{FG}; font-family:Consolas,monospace;
          font-size:13px; margin:8px; }}
  .section  {{ color:{ACCENT}; font-size:11px; text-transform:uppercase;
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
  .ts        {{ color:#7dcfff; font-size:12px; }}
  .ad-text   {{ color:#ff9eb5; }}
  .opt-text  {{ color:#89b4fa; }}
  .warn-text {{ color:#ffc990; }}
  .reason    {{ color:#565f89; font-size:11px; margin-right:8px; }}
  .clean-msg {{ color:{GREEN}; margin-top:10px; }}
  .note      {{ color:{FG2}; font-size:11px; font-style:italic; margin-top:8px; }}
  .warn-msg  {{ color:{ORANGE}; margin-top:8px; }}
  .ok        {{ color:{GREEN}; margin-top:8px; }}
  .scanning  {{ color:{ACCENT}; margin-top:8px; }}
  code       {{ background:{BG3}; padding:1px 4px; border-radius:2px; color:{FG}; }}
</style>"""


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _welcome_html() -> str:
    return (
        HTML_STYLE
        + f'<div class="section">{_esc(STRINGS["tab_transcribe"])}</div>'
        + f'<div class="note">{STRINGS["tr_welcome_note"]}</div>'
    )


def _transcribing_html(status: str) -> str:
    return (
        HTML_STYLE
        + f'<div class="section">{_esc(STRINGS["tab_transcribe"])}</div>'
        + f'<div class="scanning">⟳ {_esc(status)}</div>'
    )




# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class TranscribeWorker(QThread):
    progress = pyqtSignal(str)
    segment  = pyqtSignal(int)
    finished = pyqtSignal()   # result stored on self.result — avoids cross-thread dataclass marshalling

    def __init__(self, video_path: Path, model: str, language: Optional[str], sdh: bool):
        super().__init__()
        self.video_path = video_path
        self.model      = model
        self.language   = language
        self.sdh        = sdh
        self.result: Optional[TranscribeResult] = None

    def run(self):
        import os, traceback
        from pathlib import Path as _Path

        # These are set in the subprocess too, but set here as well for safety
        os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

        def _progress(msg: str):
            try:
                self.progress.emit(msg)
            except Exception:
                pass

        def _segment(n: int, _t: int):
            try:
                self.segment.emit(n)
            except Exception:
                pass

        try:
            self.result = transcribe(
                video_path  = self.video_path,
                model       = self.model,
                language    = self.language,
                sdh         = self.sdh,
                progress_cb = _progress,
                segment_cb  = _segment,
            )
        except Exception as e:
            tb = traceback.format_exc()
            from core.whisper import TranscribeResult as _TR
            self.result = _TR(success=False, error=f"Worker error: {e}\n\n{tb}")

        try:
            self.finished.emit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Drop zone — same style as ImageSubsDropZone
# ---------------------------------------------------------------------------

class TranscribeDropZone(QFrame):
    file_dropped = pyqtSignal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("🎙")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 18pt;")

        msg = QLabel(STRINGS["tr_drop_label"])
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {FG2}; font-size: 10pt;")

        fmt = QLabel(STRINGS["tr_drop_formats"])
        fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fmt.setStyleSheet(f"color: {FG2}; font-size: 9pt;")

        browse = QPushButton(STRINGS["tr_btn_browse"])
        browse.setMaximumWidth(100)
        browse.setToolTip(STRINGS["tip_tr_browse"])
        browse.clicked.connect(self._browse)

        layout.addWidget(icon)
        layout.addWidget(msg)
        layout.addWidget(fmt)
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

class TranscribePanel(QWidget):
    """Transcribe tab — Whisper audio transcription pipeline."""
    status_updated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path: Optional[Path]             = None
        self._result:     Optional[TranscribeResult] = None
        self._subtitle    = None
        self._worker:     Optional[TranscribeWorker] = None
        self._status_text: str                       = STRINGS["tr_status_load"]
        self._build_ui()
        self._check_tools()

    # ── Build UI ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Notices ───────────────────────────────────────────────────────
        # faster-whisper missing — orange, conditionally visible, shown first
        self._whisper_notice = QLabel()
        self._whisper_notice.setStyleSheet(
            f"color: {ORANGE}; background: transparent; border: 1px solid {ORANGE}55;"
            f"border-radius: 4px; padding: 6px 10px; font-size: 10pt;"
        )
        self._whisper_notice.setWordWrap(True)
        self._whisper_notice.setVisible(False)

        # Experimental warning — yellow, always visible, same style as Image Subs
        self._experimental_notice = QLabel(STRINGS["tr_experimental"])
        self._experimental_notice.setStyleSheet(
            f"color: {YELLOW}; background: transparent; border: 1px solid {YELLOW}55;"
            f"border-radius: 4px; padding: 6px 10px; font-size: 10pt;"
        )
        self._experimental_notice.setWordWrap(True)

        # ── Top control bar ───────────────────────────────────────────────
        ctrl = QHBoxLayout()

        self._btn_clear = QPushButton(STRINGS["tr_btn_clear"])
        self._btn_clear.clicked.connect(self._clear)
        self._btn_clear.setEnabled(False)
        self._btn_clear.setToolTip(STRINGS["tip_tr_clear"])

        self._lbl_file = QLabel(STRINGS["tr_no_file"])
        self._lbl_file.setObjectName("file_status")
        self._lbl_file.setStyleSheet(f"color: {FG2};")

        lbl_model = QLabel(STRINGS["tr_lbl_model"])
        lbl_model.setStyleSheet(f"color: {FG2}; font-size: 10pt;")

        self._model_combo = QComboBox()
        self._model_combo.setStyleSheet(
            f"QComboBox {{ background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 3px 6px; min-width: 200px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG2}; color: {FG}; "
            f"selection-background-color: {BG3}; selection-color: {FG}; border: 1px solid {BORDER}; }}"
        )
        self._populate_model_combo()

        lbl_lang = QLabel(STRINGS["tr_lbl_language"])
        lbl_lang.setStyleSheet(f"color: {FG2}; font-size: 10pt;")

        self._lang_combo = QComboBox()
        self._lang_combo.setStyleSheet(
            f"QComboBox {{ background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 3px 6px; min-width: 120px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG2}; color: {FG}; "
            f"selection-background-color: {BG3}; selection-color: {FG}; border: 1px solid {BORDER}; }}"
        )
        for i, (code, name) in enumerate(_LANGUAGES):
            label = STRINGS["tr_lang_auto"] if code == "auto" else name
            self._lang_combo.addItem(label)
            self._lang_combo.setItemData(i, code, Qt.ItemDataRole.UserRole)

        self._btn_transcribe = QPushButton(STRINGS["tr_btn_transcribe"])
        self._btn_transcribe.setObjectName("btn_clean_all")
        self._btn_transcribe.setEnabled(False)
        self._btn_transcribe.setToolTip(STRINGS["tip_tr_transcribe"])
        self._btn_transcribe.clicked.connect(self._start_transcribe)

        ctrl.addWidget(self._btn_clear)
        ctrl.addWidget(self._lbl_file, stretch=1)
        ctrl.addWidget(lbl_model)
        ctrl.addWidget(self._model_combo)
        ctrl.addWidget(lbl_lang)
        ctrl.addWidget(self._lang_combo)
        ctrl.addWidget(self._btn_transcribe)

        # ── Progress / status ─────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(6)
        self._progress.setRange(0, 0)

        # ── Drop zone ─────────────────────────────────────────────────────
        self._drop_zone = TranscribeDropZone()
        self._drop_zone.file_dropped.connect(self.load_video)

        # ── Splitter ──────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: options + bottom action bar
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        lbl_opts = QLabel(STRINGS["tr_lbl_options"])
        lbl_opts.setObjectName("section_label")

        self._chk_sdh = QCheckBox(STRINGS["tr_chk_sdh"])
        self._chk_sdh.setChecked(True)
        self._chk_sdh.toggled.connect(self._on_sdh_toggled)

        self._lbl_sdh_warn = QLabel(STRINGS["tr_sdh_warn"])
        self._lbl_sdh_warn.setWordWrap(True)
        self._lbl_sdh_warn.setStyleSheet(
            f"color: {ORANGE}; font-size: 9pt; font-style: italic;"
        )
        self._lbl_sdh_warn.setVisible(False)

        ll.addWidget(lbl_opts)
        ll.addWidget(self._chk_sdh)
        ll.addWidget(self._lbl_sdh_warn)
        ll.addStretch()

        action_bar = QHBoxLayout()
        self._chk_backup = QCheckBox(STRINGS["tr_chk_backup"])
        self._chk_backup.setChecked(False)
        self._btn_save_srt = QPushButton(STRINGS["tr_btn_save_srt"])
        self._btn_save_srt.setObjectName("btn_keep")
        self._btn_save_srt.setEnabled(False)
        self._btn_save_srt.setToolTip(STRINGS["tip_tr_save_srt"])
        self._btn_save_srt.clicked.connect(self._save_srt)
        self._btn_remux = QPushButton(STRINGS["tr_btn_remux"])
        self._btn_remux.setObjectName("btn_save")
        self._btn_remux.setEnabled(False)
        self._btn_remux.setToolTip(STRINGS["tip_tr_remux"])
        self._btn_remux.clicked.connect(self._remux)
        action_bar.addWidget(self._chk_backup)
        action_bar.addStretch()
        action_bar.addWidget(self._btn_save_srt)
        action_bar.addWidget(self._btn_remux)
        ll.addLayout(action_bar)

        # Right: stacked pane — page 0: HTML browser (idle/progress/error)
        #                        page 1: editable table (results)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        lbl_detail = QLabel(STRINGS["tr_lbl_results"])
        lbl_detail.setObjectName("section_label")

        self._detail_stack = QStackedWidget()

        # Page 0 — HTML browser (unchanged states)
        self._detail = QTextBrowser()
        self._detail.setOpenLinks(False)
        self._detail.setStyleSheet(
            f"background: {BG2}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        self._detail.setHtml(_welcome_html())
        self._detail_stack.addWidget(self._detail)   # index 0

        # Page 1 — editable block table
        self._edit_table = QTableWidget()
        self._edit_table.setColumnCount(3)
        self._edit_table.setHorizontalHeaderLabels([
            STRINGS["tr_col_index"],
            STRINGS["tr_col_timestamp"],
            STRINGS["tr_col_text"],
        ])
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
            f"gridline-color: {BORDER}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; }}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
            f"QTableWidget::item:selected {{ background: {BG3}; color: {FG}; }}"
            f"QTableWidget::item:alternate {{ background: {BG}; }}"
            f"QHeaderView::section {{ background: {BG3}; color: {FG2}; "
            f"border: none; border-bottom: 1px solid {BORDER}; "
            f"padding: 4px 6px; }}"
        )
        self._edit_table.itemChanged.connect(self._on_cell_edited)
        self._detail_stack.addWidget(self._edit_table)   # index 1

        # Hint label below the table — visible only when table is shown
        self._lbl_edit_hint = QLabel(STRINGS["tr_hint_edit"])
        self._lbl_edit_hint.setStyleSheet(
            f"color: {FG2}; font-size: 9pt; font-style: italic;")
        self._lbl_edit_hint.setWordWrap(True)
        self._lbl_edit_hint.setVisible(False)

        rl.addWidget(lbl_detail)
        rl.addWidget(self._detail_stack, stretch=1)
        rl.addWidget(self._lbl_edit_hint)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([260, 740])

        # ── Assemble root ─────────────────────────────────────────────────
        root.addWidget(self._whisper_notice)
        root.addWidget(self._experimental_notice)
        root.addLayout(ctrl)
        root.addWidget(self._drop_zone)
        root.addWidget(self._progress)
        root.addWidget(splitter, stretch=1)

    # ── Status helper ─────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        """Emit status to the app-level bar via signal."""
        self._status_text = msg
        self.status_updated.emit(msg)

    def get_status(self) -> str:
        """Return the current status text (used by MainWindow on tab switch)."""
        return self._status_text

    # ── Tool check ────────────────────────────────────────────────────────

    def _check_tools(self):
        if not faster_whisper_available():
            self._whisper_notice.setText(STRINGS["tr_whisper_missing"])
            self._whisper_notice.setVisible(True)

    # ── Model combo ───────────────────────────────────────────────────────

    def _populate_model_combo(self):
        downloaded  = list_downloaded_models()
        current_val = self._model_combo.currentData(Qt.ItemDataRole.UserRole) if self._model_combo.count() else None
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for i, name in enumerate(MODELS):
            tick  = STRINGS["tr_model_downloaded"] if name in downloaded else "  "
            label = STRINGS[f"tr_model_{name}"]
            self._model_combo.addItem(f"{label}{tick}")
            self._model_combo.setItemData(i, name, Qt.ItemDataRole.UserRole)
        target = current_val or "small"
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i, Qt.ItemDataRole.UserRole) == target:
                self._model_combo.setCurrentIndex(i)
                break
        self._model_combo.blockSignals(False)

    def _selected_model(self) -> str:
        return self._model_combo.currentData(Qt.ItemDataRole.UserRole) or "small"

    def _selected_language(self) -> Optional[str]:
        code = self._lang_combo.currentData(Qt.ItemDataRole.UserRole)
        return None if (not code or code == "auto") else code

    # ── File loading ─────────────────────────────────────────────────────

    def load_video(self, path: Path):
        """Public — called by drop zone or Video Scan handoff."""
        self._video_path = path
        self._result     = None
        self._subtitle   = None
        self._lbl_file.setText(path.name)
        self._lbl_file.setStyleSheet(f"color: {FG};")
        self._btn_clear.setEnabled(True)
        self._btn_transcribe.setEnabled(faster_whisper_available())
        self._btn_save_srt.setEnabled(False)
        self._btn_remux.setEnabled(False)
        self._progress.setVisible(False)
        self._set_status(STRINGS["tr_status_load"])
        self._detail.setHtml(_welcome_html())
        self._detail_stack.setCurrentIndex(0)
        self._edit_table.setRowCount(0)
        self._lbl_edit_hint.setVisible(False)
        self._drop_zone.setVisible(False)

    def _clear(self):
        self._video_path = None
        self._result     = None
        self._subtitle   = None
        self._lbl_file.setText(STRINGS["tr_no_file"])
        self._lbl_file.setStyleSheet(f"color: {FG2};")
        self._btn_clear.setEnabled(False)
        self._btn_transcribe.setEnabled(False)
        self._btn_save_srt.setEnabled(False)
        self._btn_remux.setEnabled(False)
        self._progress.setVisible(False)
        self._set_status(STRINGS["tr_status_load"])
        self._detail.setHtml(_welcome_html())
        self._detail_stack.setCurrentIndex(0)
        self._edit_table.setRowCount(0)
        self._lbl_edit_hint.setVisible(False)
        self._drop_zone.setVisible(True)

    # ── Transcription ─────────────────────────────────────────────────────

    def _start_transcribe(self):
        if not self._video_path or not faster_whisper_available():
            return

        self._result   = None
        self._subtitle = None
        self._btn_transcribe.setEnabled(False)
        self._btn_save_srt.setEnabled(False)
        self._btn_remux.setEnabled(False)
        self._btn_clear.setEnabled(False)
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        self._set_status(STRINGS["tr_status_transcribing"])
        # Reset to browser page while transcription is in progress
        self._edit_table.setRowCount(0)
        self._lbl_edit_hint.setVisible(False)
        self._detail_stack.setCurrentIndex(0)
        self._detail.setHtml(_transcribing_html(STRINGS["tr_status_transcribing"]))

        self._worker = TranscribeWorker(
            video_path = self._video_path,
            model      = self._selected_model(),
            language   = self._selected_language(),
            sdh        = self._chk_sdh.isChecked(),
        )
        self._worker.progress.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        self._worker.segment.connect(self._on_segment, Qt.ConnectionType.QueuedConnection)
        self._worker.finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)
        self._worker.start()

    def _on_progress(self, msg: str):
        self._set_status(msg)
        self._detail.setHtml(_transcribing_html(msg))

    def _on_segment(self, n: int):
        self._set_status(STRINGS["tr_status_segments"].format(n=n))

    def _on_finished(self):
        result = self._worker.result
        if result is None:
            # Should not happen, but guard defensively
            self._progress.setVisible(False)
            self._btn_clear.setEnabled(True)
            self._btn_transcribe.setEnabled(faster_whisper_available())
            self._set_status(STRINGS["tr_status_error"])
            return
        self._progress.setVisible(False)
        self._btn_clear.setEnabled(True)
        self._btn_transcribe.setEnabled(faster_whisper_available())
        self._result = result

        if not result.success:
            self._set_status(STRINGS["tr_status_error"])
            self._detail.setHtml(
                HTML_STYLE
                + '<div class="section">Error</div>'
                + f'<div class="warn-msg">{_esc(result.error)}</div>'
            )
            return

        self._subtitle = self._build_subtitle(result)

        if self._subtitle is None:
            self._set_status(STRINGS["tr_dlg_empty_msg"])
            self._detail.setHtml(
                HTML_STYLE
                + '<div class="section">Result</div>'
                + f'<div class="warn-msg">{_esc(STRINGS["tr_dlg_empty_msg"])}</div>'
            )
            return

        self._set_status(
            STRINGS["tr_status_done"].format(
                n=len(result.segments), lang=result.language or "?"
            )
        )

        self._populate_edit_table()
        self._btn_save_srt.setEnabled(True)
        self._btn_remux.setEnabled(
            self._video_path is not None
            and self._video_path.suffix.lower() in (".mkv", ".mp4", ".m4v")
        )
        self._populate_model_combo()

    def _populate_edit_table(self):
        """Fill the edit table from self._subtitle.blocks and switch to page 1."""
        import re as _re
        blocks = self._subtitle.blocks if self._subtitle else []
        self._edit_table.blockSignals(True)
        self._edit_table.setRowCount(len(blocks))
        for row, block in enumerate(blocks):
            # Column 0 — index (read-only)
            idx_item = QTableWidgetItem(str(block.original_index))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            idx_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            idx_item.setForeground(QColor(FG2))
            self._edit_table.setItem(row, 0, idx_item)

            # Column 1 — timestamp (read-only)
            ts = f"{block.start} → {block.end}"
            ts_item = QTableWidgetItem(ts)
            ts_item.setFlags(ts_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ts_item.setForeground(QColor("#7dcfff"))
            self._edit_table.setItem(row, 1, ts_item)

            # Column 2 — text (editable)
            txt_item = QTableWidgetItem(block.content)
            self._edit_table.setItem(row, 2, txt_item)

        self._edit_table.resizeRowsToContents()
        self._edit_table.blockSignals(False)
        self._detail_stack.setCurrentIndex(1)
        self._lbl_edit_hint.setVisible(True)

    # ── Inline edit sync ─────────────────────────────────────────────────

    def _on_cell_edited(self, item: QTableWidgetItem):
        """Sync an edited text cell back to the subtitle data model."""
        if item.column() != 2:
            return
        if not self._subtitle:
            return
        row = item.row()
        if row < 0 or row >= len(self._subtitle.blocks):
            return
        import re as _re
        block = self._subtitle.blocks[row]
        new_text = item.text()
        block.content = new_text
        block.clean_content = _re.sub(r"[\s.,:_-]", "", new_text)

    def _build_subtitle(self, result: TranscribeResult):
        """Assemble a ParsedSubtitle from TranscribeResult via a synthetic SRT."""
        if not result.segments:
            return None
        import tempfile
        from core.subtitle import load_subtitle, SubtitleFormat
        srt_text = segments_to_srt(result.segments)
        if not srt_text.strip():
            return None
        lang     = result.language or ""
        lang_tag = f".{lang}" if lang else ""
        stem     = self._video_path.stem if self._video_path else "transcription"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / f"{stem}{lang_tag}.srt"
            tmp_path.write_text(srt_text, encoding="utf-8")
            try:
                sub = load_subtitle(tmp_path)
            except Exception:
                return None
        sub._whisper_source   = True
        sub._whisper_model    = result.model
        sub._whisper_language = result.language
        return sub

    # ── SDH toggle ────────────────────────────────────────────────────────

    def _on_sdh_toggled(self, checked: bool):
        self._lbl_sdh_warn.setVisible(not checked)

    # ── Save as .srt ──────────────────────────────────────────────────────

    def _save_srt(self):
        from PyQt6.QtWidgets import QMessageBox
        if not self._subtitle or not self._video_path:
            QMessageBox.warning(self, STRINGS["tr_dlg_no_result"],
                                STRINGS["tr_dlg_no_result_msg"])
            return

        lang        = getattr(self._subtitle, "_whisper_language", "") or ""
        lang_suffix = f".{lang}" if lang else ""
        out_path    = self._video_path.parent / f"{self._video_path.stem}{lang_suffix}.srt"

        if out_path.exists():
            stem, counter = out_path.stem, 2
            while out_path.exists():
                out_path = self._video_path.parent / f"{stem}.{counter}.srt"
                counter += 1

        try:
            from core.subtitle import write_subtitle, SubtitleFormat
            self._subtitle.fmt = SubtitleFormat.SRT
            write_subtitle(self._subtitle, dest=out_path)
        except Exception as e:
            QMessageBox.critical(self, STRINGS["tr_dlg_save_failed"], str(e))
            return

        self._set_status(STRINGS["tr_status_saved"].format(name=out_path.name))

    # ── Remux ─────────────────────────────────────────────────────────────

    def _remux(self):
        from PyQt6.QtWidgets import QMessageBox
        import tempfile

        if not self._subtitle or not self._video_path:
            QMessageBox.warning(self, STRINGS["tr_dlg_no_result"],
                                STRINGS["tr_dlg_no_result_msg"])
            return

        suffix = self._video_path.suffix.lower()
        if suffix not in (".mkv", ".mp4", ".m4v"):
            QMessageBox.warning(self, STRINGS["tr_dlg_unsupported"],
                                STRINGS["tr_dlg_unsupported_msg"])
            return

        from core.mkvtoolnix import mkvmerge_available
        from core.ffprobe import ffmpeg_available
        from core.subtitle import write_subtitle, SubtitleFormat

        is_mkv = suffix == ".mkv"
        is_mp4 = suffix in (".mp4", ".m4v")

        if is_mkv and not mkvmerge_available():
            QMessageBox.warning(self, STRINGS["tr_dlg_mkv_missing"],
                                STRINGS["tr_dlg_mkv_missing_msg"])
            return
        if is_mp4 and not ffmpeg_available():
            QMessageBox.warning(self, STRINGS["tr_dlg_ffmpeg_missing"],
                                STRINGS["tr_dlg_ffmpeg_missing_msg"])
            return

        lang        = getattr(self._subtitle, "_whisper_language", "") or ""
        lang_suffix = f".{lang}" if lang else ""
        srt_name    = f"{self._video_path.stem}{lang_suffix}.srt"

        self._btn_remux.setEnabled(False)
        self._btn_save_srt.setEnabled(False)
        self._btn_transcribe.setEnabled(False)
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        self._set_status(STRINGS["tr_status_remuxing"])

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_srt = Path(tmpdir) / srt_name
            self._subtitle.fmt = SubtitleFormat.SRT
            try:
                write_subtitle(self._subtitle, dest=tmp_srt)
            except Exception as e:
                self._progress.setVisible(False)
                self._btn_remux.setEnabled(True)
                self._btn_save_srt.setEnabled(True)
                self._btn_transcribe.setEnabled(faster_whisper_available())
                QMessageBox.critical(self, STRINGS["tr_dlg_save_failed"], str(e))
                return

            result = self._remux_mkv(tmp_srt, lang) if is_mkv else self._remux_mp4(tmp_srt, lang)

        self._progress.setVisible(False)
        self._btn_remux.setEnabled(True)
        self._btn_save_srt.setEnabled(True)
        self._btn_transcribe.setEnabled(faster_whisper_available())

        if result is None or result.success:
            self._set_status(STRINGS["tr_status_remux_ok"])
        else:
            QMessageBox.critical(self, STRINGS["tr_dlg_remux_failed"],
                                 getattr(result, "error", "Unknown error"))
            self._set_status(STRINGS["tr_status_remux_fail"])

    def _remux_mkv(self, tmp_srt: Path, lang: str):
        import subprocess, sys, shutil
        from dataclasses import dataclass
        from core.mkvtoolnix import get_mkvmerge_path

        @dataclass
        class _R:
            success: bool
            error: str = ""

        mkvmerge = get_mkvmerge_path()
        if not mkvmerge:
            return _R(success=False, error="mkvmerge not found")

        video    = self._video_path
        out      = video.with_stem(video.stem + "_transcribed")
        lang_arg = ["--language", f"0:{lang or 'und'}"] if lang else []
        cmd      = [mkvmerge, "-o", str(out), str(video)] + lang_arg + [str(tmp_srt)]
        flags    = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, **flags)
            if proc.returncode not in (0, 1):
                return _R(success=False, error=proc.stderr or proc.stdout)
        except Exception as e:
            return _R(success=False, error=str(e))

        if self._chk_backup.isChecked():
            shutil.copy2(video, video.with_suffix(".bak" + video.suffix))
        shutil.move(str(out), str(video))
        return _R(success=True)

    def _remux_mp4(self, tmp_srt: Path, lang: str):
        import subprocess, sys, shutil
        from dataclasses import dataclass
        from core.ffprobe import get_ffmpeg_path

        @dataclass
        class _R:
            success: bool
            error: str = ""

        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            return _R(success=False, error="ffmpeg not found")

        video     = self._video_path
        out       = video.with_stem(video.stem + "_transcribed")
        lang_meta = ["-metadata:s:s:0", f"language={lang or 'und'}"] if lang else []
        cmd = [
            ffmpeg, "-y", "-i", str(video), "-i", str(tmp_srt),
            "-c", "copy", "-c:s", "mov_text",
        ] + lang_meta + ["-map", "0", "-map", "1:0", str(out)]
        flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, **flags)
            if proc.returncode != 0:
                return _R(success=False, error=proc.stderr)
        except Exception as e:
            return _R(success=False, error=str(e))

        if self._chk_backup.isChecked():
            shutil.copy2(video, video.with_suffix(".bak" + video.suffix))
        shutil.move(str(out), str(video))
        return _R(success=True)
