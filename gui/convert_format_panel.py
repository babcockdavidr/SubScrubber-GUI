"""
gui/convert_format_panel.py — Subtitle format conversion tab.

Lets users convert subtitle files between the six supported text-based formats
(SRT, ASS, SSA, VTT, TTML, SAMI) individually or in bulk across a folder.
Conversion is delegated entirely to core/converter.py (pysubs2 backend).

Layout
------
  Top:    drop zone (collapses when file loaded) + single-file control bar
  Middle: results area (QTextBrowser — log of conversions run)
  Bottom: batch section — folder path + target format + Convert All button

Lossy warnings are shown inline as orange labels when the selected
source→target path is known to degrade styling.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QFrame, QFileDialog, QComboBox, QCheckBox,
)

from core.converter import (
    FORMATS, INPUT_EXTENSIONS, convert_file, convert_folder,
    is_lossy, lossy_reason,
)
from gui.strings import STRINGS
from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, ORANGE, GREEN, RED
from .settings_dialog import get_font_pt as _get_fp, get_font_pt_small as _get_fps, get_font_pt_tiny as _get_fpt


# ---------------------------------------------------------------------------
# Drop zone
# ---------------------------------------------------------------------------

class ConvertDropZone(QFrame):
    file_dropped = pyqtSignal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(max(90, round(90 * _get_fp() / 11)))

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("⇄")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 18pt;")

        msg = QLabel(STRINGS["cv_drop_label"])
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {FG2}; font-size: {_get_fp()}pt;")

        fmt = QLabel(STRINGS["cv_drop_formats"])
        fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fmt.setStyleSheet(f"color: {FG2}; font-size: {_get_fps()}pt;")

        browse = QPushButton(STRINGS["cv_btn_browse"])
        browse.setMaximumWidth(100)
        browse.clicked.connect(self._browse)

        layout.addWidget(icon)
        layout.addWidget(msg)
        layout.addWidget(fmt)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)

    def _browse(self):
        exts = " ".join(f"*{e}" for e in sorted(INPUT_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(
            self, STRINGS["cv_drop_label"], "",
            f"Subtitle Files ({exts});;All Files (*)"
        )
        if path:
            self.file_dropped.emit(Path(path))

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file() and p.suffix.lower() in INPUT_EXTENSIONS:
                self.file_dropped.emit(p)
                return


# ---------------------------------------------------------------------------
# Worker signals — marshal results from threading.Thread to main thread
# ---------------------------------------------------------------------------

class _WorkerSignals(QObject):
    """Tiny QObject just for holding signals."""
    single_done = pyqtSignal(object)   # ConvertResult
    batch_done  = pyqtSignal(object)   # BatchConvertResult


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class ConvertFormatPanel(QWidget):
    """Convert Format tab — subtitle format conversion pipeline."""
    status_updated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._src_path: Optional[Path] = None
        self._status_text: str = STRINGS["cv_status_ready"]
        self._signals = _WorkerSignals()
        self._signals.single_done.connect(self._on_single_done)
        self._signals.batch_done.connect(self._on_batch_done)
        self._build_ui()

    # ── Build UI ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Single-file section label ─────────────────────────────────────
        lbl_single = QLabel(STRINGS["cv_lbl_single"])
        lbl_single.setObjectName("section_label")

        # ── Drop zone ─────────────────────────────────────────────────────
        self._drop_zone = ConvertDropZone()
        self._drop_zone.file_dropped.connect(self._load_file)

        # ── Single-file control bar ───────────────────────────────────────
        sf_bar = QHBoxLayout()

        self._btn_clear = QPushButton(STRINGS["cv_btn_clear"])
        self._btn_clear.setEnabled(False)
        self._btn_clear.clicked.connect(self._clear)

        self._lbl_file = QLabel(STRINGS["cv_no_file"])
        self._lbl_file.setObjectName("file_status")
        self._lbl_file.setStyleSheet(f"color: {FG2};")

        lbl_fmt = QLabel(STRINGS["cv_lbl_output_format"])
        lbl_fmt.setStyleSheet(f"color: {FG2}; font-size: {_get_fp()}pt;")

        self._fmt_combo = QComboBox()
        self._fmt_combo.setStyleSheet(
            f"QComboBox {{ background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 3px 6px; min-width: 230px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG2}; color: {FG}; "
            f"selection-background-color: {BG3}; selection-color: {FG}; "
            f"border: 1px solid {BORDER}; }}"
        )
        self._fmt_combo.setAccessibleName(STRINGS["cv_lbl_output_format"])
        for fmt in FORMATS:
            self._fmt_combo.addItem(fmt.display_name, userData=fmt.identifier)
        self._fmt_combo.currentIndexChanged.connect(self._on_format_changed)

        self._btn_convert = QPushButton(STRINGS["cv_btn_convert"])
        self._btn_convert.setObjectName("btn_clean_all")
        self._btn_convert.setEnabled(False)
        self._btn_convert.clicked.connect(self._convert_single)

        self._chk_backup = QCheckBox(STRINGS["cv_chk_backup"])
        self._chk_backup.setStyleSheet(f"color: {FG};")

        sf_bar.addWidget(self._btn_clear)
        sf_bar.addWidget(self._lbl_file, stretch=1)
        sf_bar.addWidget(self._chk_backup)
        sf_bar.addWidget(lbl_fmt)
        sf_bar.addWidget(self._fmt_combo)
        sf_bar.addWidget(self._btn_convert)

        # ── Lossy warning (single file) ───────────────────────────────────
        self._lbl_lossy = QLabel()
        self._lbl_lossy.setWordWrap(True)
        self._lbl_lossy.setStyleSheet(
            f"color: {ORANGE}; background: transparent; "
            f"border: 1px solid {ORANGE}55; border-radius: 4px; "
            f"padding: 5px 10px; font-size: {_get_fp()}pt;"
        )
        self._lbl_lossy.setVisible(False)

        # ── Results area ──────────────────────────────────────────────────
        lbl_results = QLabel(STRINGS["cv_lbl_results"])
        lbl_results.setObjectName("section_label")

        self._results = QTextBrowser()
        self._results.setOpenLinks(False)
        self._results.setStyleSheet(
            f"background: {BG2}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        self._results.setPlaceholderText(STRINGS["cv_lbl_no_result"])

        # ── Batch section ─────────────────────────────────────────────────
        lbl_batch = QLabel(STRINGS["cv_lbl_batch"])
        lbl_batch.setObjectName("section_label")

        batch_bar = QHBoxLayout()

        lbl_folder = QLabel(STRINGS["cv_lbl_folder"])
        lbl_folder.setStyleSheet(f"color: {FG2}; font-size: {_get_fp()}pt;")

        self._lbl_folder = QLabel(STRINGS["cv_no_folder"])
        self._lbl_folder.setObjectName("file_status")
        self._lbl_folder.setStyleSheet(f"color: {FG2};")

        self._btn_browse_folder = QPushButton(STRINGS["cv_btn_browse_folder"])
        self._btn_browse_folder.clicked.connect(self._browse_folder)

        lbl_tgt = QLabel(STRINGS["cv_lbl_target_format"])
        lbl_tgt.setStyleSheet(f"color: {FG2}; font-size: {_get_fp()}pt;")

        self._batch_fmt_combo = QComboBox()
        self._batch_fmt_combo.setStyleSheet(
            f"QComboBox {{ background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 3px 6px; min-width: 230px; }}"
            f"QComboBox QAbstractItemView {{ background: {BG2}; color: {FG}; "
            f"selection-background-color: {BG3}; selection-color: {FG}; "
            f"border: 1px solid {BORDER}; }}"
        )
        self._batch_fmt_combo.setAccessibleName(STRINGS["cv_lbl_target_format"])
        for fmt in FORMATS:
            self._batch_fmt_combo.addItem(fmt.display_name, userData=fmt.identifier)

        self._btn_convert_batch = QPushButton(STRINGS["cv_btn_convert_batch"])
        self._btn_convert_batch.setObjectName("btn_clean_all")
        self._btn_convert_batch.setEnabled(False)
        self._btn_convert_batch.clicked.connect(self._convert_batch)

        self._chk_backup_batch = QCheckBox(STRINGS["cv_chk_backup"])
        self._chk_backup_batch.setStyleSheet(f"color: {FG};")

        batch_bar.addWidget(lbl_folder)
        batch_bar.addWidget(self._lbl_folder, stretch=1)
        batch_bar.addWidget(self._btn_browse_folder)
        batch_bar.addWidget(self._chk_backup_batch)
        batch_bar.addWidget(lbl_tgt)
        batch_bar.addWidget(self._batch_fmt_combo)
        batch_bar.addWidget(self._btn_convert_batch)

        # ── Assemble root ─────────────────────────────────────────────────
        root.addWidget(lbl_single)
        root.addWidget(self._drop_zone)
        root.addLayout(sf_bar)
        root.addWidget(self._lbl_lossy)
        root.addWidget(lbl_results)
        root.addWidget(self._results, stretch=1)
        root.addWidget(lbl_batch)
        root.addLayout(batch_bar)

        # Tab order
        self.setTabOrder(self._btn_clear,        self._fmt_combo)
        self.setTabOrder(self._fmt_combo,         self._chk_backup)
        self.setTabOrder(self._chk_backup,        self._btn_convert)
        self.setTabOrder(self._btn_convert,       self._btn_browse_folder)
        self.setTabOrder(self._btn_browse_folder, self._batch_fmt_combo)
        self.setTabOrder(self._batch_fmt_combo,   self._chk_backup_batch)
        self.setTabOrder(self._chk_backup_batch,  self._btn_convert_batch)

    # ── Status helper ─────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_text = msg
        self.status_updated.emit(msg)

    def get_status(self) -> str:
        return self._status_text

    # ── File loading ─────────────────────────────────────────────────────

    def _load_file(self, path: Path):
        self._src_path = path
        self._lbl_file.setText(path.name)
        self._lbl_file.setStyleSheet(f"color: {FG};")
        self._btn_clear.setEnabled(True)
        self._btn_convert.setEnabled(True)
        self._drop_zone.setVisible(False)
        self._update_lossy_warning()
        self._set_status(STRINGS["cv_status_ready"])

    def _clear(self):
        self._src_path = None
        self._lbl_file.setText(STRINGS["cv_no_file"])
        self._lbl_file.setStyleSheet(f"color: {FG2};")
        self._btn_clear.setEnabled(False)
        self._btn_convert.setEnabled(False)
        self._drop_zone.setVisible(True)
        self._lbl_lossy.setVisible(False)
        self._set_status(STRINGS["cv_status_ready"])

    # ── Lossy warning ─────────────────────────────────────────────────────

    def _update_lossy_warning(self):
        if self._src_path is None:
            self._lbl_lossy.setVisible(False)
            return
        from core.converter import format_by_ext
        src_fmt = format_by_ext(self._src_path.suffix)
        src_id  = src_fmt.identifier if src_fmt else "unknown"
        tgt_id  = self._fmt_combo.currentData()
        if not tgt_id:
            self._lbl_lossy.setVisible(False)
            return
        reason_key = lossy_reason(src_id, tgt_id)
        if reason_key and STRINGS.get(reason_key):
            self._lbl_lossy.setText(STRINGS[reason_key])
            self._lbl_lossy.setVisible(True)
        else:
            self._lbl_lossy.setVisible(False)

    def _on_format_changed(self, _index: int):
        self._update_lossy_warning()

    # ── Single-file conversion ────────────────────────────────────────────

    def _convert_single(self):
        if self._src_path is None:
            self._log(STRINGS["cv_err_no_file"], color=ORANGE)
            return
        tgt_id = self._fmt_combo.currentData()
        if not tgt_id:
            return

        self._btn_convert.setEnabled(False)
        self._set_status(STRINGS["cv_status_converting"])

        src = self._src_path
        backup = self._chk_backup.isChecked()

        def _run():
            result = convert_file(src, tgt_id, keep_backup=backup)
            self._signals.single_done.emit(result)

        threading.Thread(target=_run, daemon=True).start()

    def _on_single_done(self, result):
        self._btn_convert.setEnabled(True)
        if result.success:
            msg = STRINGS["cv_status_done"].format(name=result.output.name)
            self._set_status(msg)
            color = ORANGE if result.was_lossy else GREEN
            self._log(f"✓  {result.output.name}", color=color)
            if result.was_lossy:
                self._log(f"   {STRINGS['cv_hint_lossy']}", color=ORANGE)
        else:
            self._set_status(STRINGS["cv_status_error"])
            self._log(f"✕  {STRINGS['cv_dlg_failed']}: {result.error}", color=RED)

    # ── Batch conversion ──────────────────────────────────────────────────

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, STRINGS["cv_lbl_batch"], ""
        )
        if folder:
            self._folder_path = Path(folder)
            self._lbl_folder.setText(str(self._folder_path))
            self._lbl_folder.setStyleSheet(f"color: {FG};")
            self._btn_convert_batch.setEnabled(True)

    def _convert_batch(self):
        folder = getattr(self, "_folder_path", None)
        if folder is None:
            self._log(STRINGS["cv_err_no_folder"], color=ORANGE)
            return
        tgt_id = self._batch_fmt_combo.currentData()
        if not tgt_id:
            return

        self._btn_convert_batch.setEnabled(False)
        self._set_status(STRINGS["cv_status_converting"])
        backup = self._chk_backup_batch.isChecked()

        def _run():
            result = convert_folder(folder, tgt_id, keep_backup=backup)
            self._signals.batch_done.emit(result)

        threading.Thread(target=_run, daemon=True).start()

    def _on_batch_done(self, result):
        self._btn_convert_batch.setEnabled(True)
        msg = STRINGS["cv_status_batch_done"].format(
            converted=result.converted,
            skipped=result.skipped,
            failed=result.failed,
        )
        self._set_status(msg)
        self._log(f"── {msg}", color=ACCENT)
        if result.errors:
            self._log(STRINGS["cv_batch_errors_title"], color=ORANGE)
            for path, err in result.errors:
                name = Path(path).name if not isinstance(path, str) else path
                self._log(f"   ✕  {name}: {err}", color=RED)

    # ── Log helper ────────────────────────────────────────────────────────

    def _log(self, text: str, color: str = FG):
        self._results.append(
            f'<span style="color:{color}; font-family:Consolas,monospace; '
            f'font-size:10pt;">{text}</span>'
        )
