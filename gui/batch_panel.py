"""
Batch panel — select a root folder, scan all subtitle files recursively,
review the summary, then clean everything in one click.

Key improvements over v1:
  - Always recursive by default, no hidden checkbox
  - Confidence threshold slider (1–5) controls regex_matches cutoff
    so the user can tune aggressiveness without re-scanning
  - Live re-filtering when the slider moves (no rescan needed)
  - Clean All button is prominent and always visible
  - Shows full subfolder path so user knows which movie each file belongs to
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QTextEdit, QTextBrowser, QProgressBar,
    QFileDialog, QMessageBox, QCheckBox, QAbstractItemView,
    QSplitter, QSlider, QFrame, QSizePolicy,
)

import sys
# sys.path managed by subforge.py entry point — do not insert __file__-relative paths here

from core import collect_files, run_batch, save_batch, BatchResult, FileResult, SUPPORTED_EXTENSIONS
from core import apply_cleaning_options, block_will_be_removed
from gui.settings_dialog import load_cleaning_options, load_default_sensitivity
from gui.strings import STRINGS
from core.subtitle import ParsedSubtitle
from .colors import BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW


# ---------------------------------------------------------------------------
# Threshold helpers
# ---------------------------------------------------------------------------

# Slider maps 1–5 to a regex_matches threshold.
# Lower = more aggressive (catches more, higher false-positive risk)
# Higher = more conservative (only removes obvious ads)
THRESHOLD_LABELS = {
    1: STRINGS["thresh_1"],
    2: STRINGS["thresh_2"],
    3: STRINGS["thresh_3"],
    4: STRINGS["thresh_4"],
    5: STRINGS["thresh_5"],
}


def _classify(subtitle: ParsedSubtitle, threshold: int):
    """Re-classify blocks using a custom threshold without re-running analysis."""
    ads = warns = 0
    for block in subtitle.blocks:
        rm = block.regex_matches
        if rm >= threshold:
            ads += 1
        elif rm == threshold - 1 and threshold > 1:
            warns += 1
    return ads, warns


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class BatchWorker(QThread):
    progress   = pyqtSignal(int, int, str)
    finished   = pyqtSignal(object)   # BatchResult (complete)
    cancelled  = pyqtSignal(object)   # BatchResult (partial, scan was stopped)

    def __init__(self, paths: List[Path]):
        super().__init__()
        self.paths = paths
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from core.batch import FileResult, BatchResult
        from core.subtitle import load_subtitle
        from core.cleaner import analyze as _analyze

        t0 = time.time()
        total = len(self.paths)
        results_map: dict = {}   # original index -> FileResult
        done_count = 0
        done_lock = threading.Lock()

        def _scan_one(i_path):
            i, path = i_path
            # Check cancel before doing any work
            if self._stop.is_set():
                return i, None
            fr = FileResult(path=path)
            try:
                sub = load_subtitle(path)
                _analyze(sub)
                fr.subtitle = sub
                fr.total_blocks = len(sub.blocks)
                fr.ad_count = sum(1 for b in sub.blocks if b.is_ad)
                fr.warning_count = sum(1 for b in sub.blocks if b.is_warning)
            except Exception as e:
                fr.error = str(e)
            return i, fr

        n_workers = min(4, total) if total > 0 else 1
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(_scan_one, (i, path)): i
                for i, path in enumerate(self.paths)
            }
            for fut in as_completed(futures):
                i, fr = fut.result()
                with done_lock:
                    done_count += 1
                    count_snap = done_count

                if fr is None:
                    # Task was cancelled — drain remaining futures and emit partial
                    for f in futures:
                        f.cancel()
                    ordered = [results_map[k] for k in sorted(results_map)]
                    self.cancelled.emit(BatchResult(results=ordered, elapsed=time.time() - t0))
                    return

                results_map[i] = fr
                self.progress.emit(count_snap, total, fr.path.name)

        # Reassemble in original file order
        ordered = [results_map[k] for k in sorted(results_map)]
        self.finished.emit(BatchResult(results=ordered, elapsed=time.time() - t0))


# ---------------------------------------------------------------------------
# Result row
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Numeric sort helper
# ---------------------------------------------------------------------------

class NumericTableItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically rather than lexicographically."""
    def __lt__(self, other):
        try:
            return int(self.text() or 0) < int(other.text() or 0)
        except (ValueError, AttributeError):
            return super().__lt__(other)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class BatchPanel(QWidget):
    open_file_requested = pyqtSignal(Path)
    status_updated      = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._batch_result: Optional[BatchResult] = None
        self._current_fr = None
        self._worker: Optional[BatchWorker] = None
        self._all_paths: List[Path] = []
        self._root_folder: Optional[Path] = None
        self._threshold: int = load_default_sensitivity()
        self._status_text: str = STRINGS["batch_status_begin"]
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Folder selection row ──────────────────────────────────────────
        folder_row = QHBoxLayout()

        self._lbl_folder = QLabel(STRINGS["batch_no_folder"])
        self._lbl_folder.setStyleSheet(f"color: {FG2}; font-size: 10pt;")
        self._lbl_folder.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Preferred)

        self._btn_folder = QPushButton(STRINGS["batch_btn_select_folder"])
        self._btn_folder.setObjectName("btn_clean_all")
        self._btn_folder.setToolTip(STRINGS["tip_batch_select_folder"])
        self._btn_clear = QPushButton(STRINGS["batch_btn_clear"])
        self._btn_clear.setToolTip(STRINGS["tip_batch_clear"])

        folder_row.addWidget(self._btn_folder)
        folder_row.addWidget(self._lbl_folder, stretch=1)
        folder_row.addWidget(self._btn_clear)

        # ── Threshold slider row ──────────────────────────────────────────
        thresh_frame = QFrame()
        thresh_frame.setStyleSheet(
            f"background: {BG2}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        thresh_layout = QHBoxLayout(thresh_frame)
        thresh_layout.setContentsMargins(12, 8, 12, 8)

        thresh_title = QLabel(STRINGS["sens_label"])
        thresh_title.setStyleSheet(f"color: {FG}; font-size: 10pt; font-weight: bold;")

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(1)
        self._slider.setMaximum(5)
        self._slider.setValue(load_default_sensitivity())
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(1)
        self._slider.setFixedWidth(200)

        self._lbl_threshold = QLabel(THRESHOLD_LABELS[3])
        self._lbl_threshold.setStyleSheet(f"color: {YELLOW}; font-size: 9pt;")

        # Endpoint labels
        lbl_aggressive = QLabel(STRINGS["sens_more_aggressive"])
        lbl_aggressive.setStyleSheet(f"color: {RED}; font-size: 8pt;")
        lbl_conservative = QLabel(STRINGS["sens_more_conservative"])
        lbl_conservative.setStyleSheet(f"color: {GREEN}; font-size: 8pt;")

        thresh_layout.addWidget(thresh_title)
        thresh_layout.addWidget(lbl_aggressive)
        thresh_layout.addWidget(self._slider)
        thresh_layout.addWidget(lbl_conservative)
        thresh_layout.addSpacing(16)
        thresh_layout.addWidget(self._lbl_threshold, stretch=1)

        # ── Action row ────────────────────────────────────────────────────
        action_row = QHBoxLayout()

        self._chk_warnings = QCheckBox(STRINGS["batch_chk_warnings"])
        self._chk_warnings.setStyleSheet(f"color: {FG2}; font-size: 10pt;")

        self._btn_scan = QPushButton(STRINGS["batch_btn_scan_all"])
        self._btn_scan.setObjectName("btn_clean_all")
        self._btn_scan.setEnabled(False)
        self._btn_scan.setToolTip(STRINGS["tip_batch_scan"])

        self._btn_stop_scan = QPushButton(STRINGS["batch_btn_stop_scan"])
        self._btn_stop_scan.setObjectName("btn_save")
        self._btn_stop_scan.setVisible(False)
        self._btn_stop_scan.setToolTip(STRINGS["tip_batch_stop_scan"])

        self._btn_save = QPushButton(STRINGS["batch_btn_clean_save_all"])
        self._btn_save.setObjectName("btn_save")
        self._btn_save.setEnabled(False)
        self._btn_save.setToolTip(STRINGS["tip_batch_save_all"])

        action_row.addWidget(self._chk_warnings)
        action_row.addStretch()
        action_row.addWidget(self._btn_scan)
        action_row.addWidget(self._btn_stop_scan)
        action_row.addWidget(self._btn_save)

        # ── Progress / status ─────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(6)

        # ── Splitter: file list | detail ──────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: result list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        lbl_files = QLabel(STRINGS["batch_lbl_scanned"])
        lbl_files.setObjectName("section_label")

        self._result_list = QTableWidget()
        self._result_list.setColumnCount(4)
        self._result_list.setHorizontalHeaderLabels(["File", "Ads", "Opts", "Warns"])
        self._result_list.setFont(QFont("Consolas", 11))
        self._result_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._result_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._result_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._result_list.setShowGrid(False)
        self._result_list.verticalHeader().setVisible(False)
        self._result_list.horizontalHeader().setSortIndicatorShown(True)
        self._result_list.horizontalHeader().setSectionsClickable(True)
        self._result_list.setSortingEnabled(True)
        self._result_list.horizontalHeader().setStretchLastSection(False)
        self._result_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._result_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._result_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._result_list.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._result_list.setColumnWidth(1, 64)
        self._result_list.setColumnWidth(2, 64)
        self._result_list.setColumnWidth(3, 64)
        self._result_list.setStyleSheet(
            f'QTableWidget {{ background: {BG2}; border: 1px solid {BORDER}; border-radius: 4px; }}'
            f'QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {BORDER}; }}'
            f'QTableWidget::item:selected {{ background: #2a3f5f; color: #ffffff; }}'
            f'QHeaderView::section {{ background: {BG2}; color: {FG2}; border: none; '
            f'border-bottom: 1px solid {BORDER}; padding: 4px 8px; font-size: 9pt; }}'
        )

        self._btn_open_in_review = QPushButton(STRINGS["batch_btn_open_review"])
        self._btn_open_in_review.setEnabled(False)
        self._btn_open_in_review.setToolTip(STRINGS["tip_batch_open_review"])
        self._btn_full_report = QPushButton(STRINGS["batch_btn_full_report"])
        self._btn_full_report.setEnabled(False)
        self._btn_full_report.setToolTip(STRINGS["batch_tip_full_report"])

        file_btns = QHBoxLayout()
        file_btns.addWidget(self._btn_open_in_review)
        file_btns.addWidget(self._btn_full_report)

        ll.addWidget(lbl_files)
        ll.addWidget(self._result_list, stretch=1)
        ll.addLayout(file_btns)

        # Right: detail report
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        lbl_report = QLabel(STRINGS["batch_lbl_report"])
        lbl_report.setObjectName("section_label")

        self._report_text = QTextBrowser()
        self._report_text.setFont(QFont("Consolas", 11))
        self._report_text.setOpenExternalLinks(False)
        self._report_text.anchorClicked.connect(self._on_report_link)
        self._report_text.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; border-radius: 4px;"
        )

        rl.addWidget(lbl_report)
        rl.addWidget(self._report_text)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([400, 440])

        # ── Assemble ──────────────────────────────────────────────────────
        root.addLayout(folder_row)
        root.addWidget(thresh_frame)
        root.addLayout(action_row)
        root.addWidget(self._progress)
        root.addWidget(splitter, stretch=1)

        # ── Connect ───────────────────────────────────────────────────────
        self._btn_folder.clicked.connect(self._select_folder)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_scan.clicked.connect(self._scan)
        self._btn_stop_scan.clicked.connect(self._stop_scan)
        self._btn_save.clicked.connect(self._save_all)
        self._slider.valueChanged.connect(self._on_threshold_changed)
        self._result_list.itemSelectionChanged.connect(self._on_selection_changed)
        self._btn_open_in_review.clicked.connect(self._open_in_review)

        self._btn_full_report.clicked.connect(self._show_full_report)

    # ── Status helper ─────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        """Emit status to the app-level bar via signal."""
        self._status_text = msg
        self.status_updated.emit(msg)

    def get_status(self) -> str:
        """Return the current status text (used by MainWindow on tab switch)."""
        return self._status_text

    # ── Table helpers ────────────────────────────────────────────────────

    def _counts_for(self, fr, threshold):
        if fr.subtitle:
            ads, warns = _classify(fr.subtitle, threshold)
            cleaning_opts = load_cleaning_options()
            opts = sum(
                1 for b in fr.subtitle.blocks
                if b.regex_matches < threshold
                and block_will_be_removed(b.content, cleaning_opts)
            ) if cleaning_opts.any_enabled() else 0
        else:
            ads, warns = fr.ad_count, fr.warning_count
            opts = 0
        return ads, warns, opts

    def _row_color(self, ads, warns, opts):
        if ads > 0:   return QColor(RED)
        if warns > 0: return QColor(ORANGE)
        if opts > 0:  return QColor(ACCENT)
        return QColor(GREEN)

    def _populate_row(self, row, fr, threshold):
        if fr.error:
            display = str(fr.path.parent.name) + "/" + fr.path.name
            item = QTableWidgetItem(display)
            item.setForeground(QColor("#888888"))
            item.setData(Qt.ItemDataRole.UserRole, fr)
            self._result_list.setItem(row, 0, item)
            for col in (1, 2, 3):
                cell = QTableWidgetItem("")
                cell.setForeground(QColor("#888888"))
                self._result_list.setItem(row, col, cell)
            return

        ads, warns, opts = self._counts_for(fr, threshold)
        color = self._row_color(ads, warns, opts)
        try:
            display = str(fr.path.parent.name) + "/" + fr.path.name
        except Exception:
            display = fr.path.name

        item0 = QTableWidgetItem(display)
        item0.setForeground(color)
        item0.setData(Qt.ItemDataRole.UserRole, fr)
        item1 = NumericTableItem(str(ads) if ads else "")
        item1.setForeground(color)
        item1.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item2 = NumericTableItem(str(opts) if opts else "")
        item2.setForeground(color)
        item2.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item3 = NumericTableItem(str(warns) if warns else "")
        item3.setForeground(color)
        item3.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        self._result_list.setItem(row, 0, item0)
        self._result_list.setItem(row, 1, item1)
        self._result_list.setItem(row, 2, item2)
        self._result_list.setItem(row, 3, item3)

    def _on_selection_changed(self):
        rows = self._result_list.selectedItems()
        if not rows:
            self._on_row_selected(-1)
            return
        row = self._result_list.row(rows[0])
        self._on_row_selected(row)

    # ── Folder selection ──────────────────────────────────────────────────

    # ------------------------------------------------------------------
    # Public session-memory API
    # ------------------------------------------------------------------

    def get_folder(self) -> str:
        """Return current root folder as a string, or '' if none selected."""
        return str(self._root_folder) if self._root_folder else ""

    def set_folder(self, path: str) -> None:
        """Restore a previously saved folder and kick off a scan."""
        if not path:
            return
        p = Path(path)
        if p.is_dir():
            self._root_folder = p
            self._lbl_folder.setText(str(p))
            self._scan()

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Base Folder")
        if not folder:
            return
        self._root_folder = Path(folder)
        self._lbl_folder.setText(str(self._root_folder))
        # Always recursive — scan all subtitle files under the root
        paths = collect_files([self._root_folder], recursive=True)
        self._all_paths = paths
        if paths:
            self._set_status(
                f"Found {len(paths)} subtitle file(s) under {self._root_folder.name}. "
                f"Click Scan All to analyse."
            )
            self._btn_scan.setEnabled(True)
        else:
            self._set_status(STRINGS["batch_no_files"])
            self._btn_scan.setEnabled(False)

    def _clear(self):
        self._all_paths.clear()
        self._root_folder = None
        self._batch_result = None
        self._result_list.setSortingEnabled(False)
        self._result_list.setRowCount(0)
        self._report_text.clear()
        self._btn_scan.setEnabled(False)
        self._btn_save.setEnabled(False)
        self._btn_full_report.setEnabled(False)
        self._lbl_folder.setText("No folder selected")
        self._set_status(STRINGS["batch_status_begin"])

    # ── Threshold slider ──────────────────────────────────────────────────

    def _on_threshold_changed(self, value: int):
        self._threshold = value
        self._lbl_threshold.setText(THRESHOLD_LABELS.get(value, str(value)))
        if self._batch_result:
            self._refresh_rows()
            self._update_summary_counts()
            # Re-render whichever view is currently shown
            if self._current_fr is not None:
                sel = self._result_list.selectedItems()
                if sel:
                    self._on_row_selected(self._result_list.row(sel[0]))
            else:
                self._report_text.setHtml(self._build_report())

    def _refresh_rows(self):
        self._result_list.setSortingEnabled(False)
        for row in range(self._result_list.rowCount()):
            item = self._result_list.item(row, 0)
            if item is None:
                continue
            fr = item.data(Qt.ItemDataRole.UserRole)
            if fr is not None:
                self._populate_row(row, fr, self._threshold)
        self._result_list.setSortingEnabled(True)

    def _update_summary_counts(self):
        if not self._batch_result:
            return
        total_ads = sum(
            _classify(r.subtitle, self._threshold)[0]
            for r in self._batch_result.results if r.subtitle
        )
        total_warns = sum(
            _classify(r.subtitle, self._threshold)[1]
            for r in self._batch_result.results if r.subtitle
        )
        files_with_ads = sum(
            1 for r in self._batch_result.results
            if r.subtitle and _classify(r.subtitle, self._threshold)[0] > 0
        )
        self._set_status(
            f"Scan complete — {self._batch_result.total} files · "
            f"{files_with_ads} with ads ({total_ads} blocks) · "
            f"{total_warns} warnings · threshold: rm≥{self._threshold}"
        )
        self._btn_save.setEnabled(files_with_ads > 0)

    # ── Scanning ──────────────────────────────────────────────────────────

    def _scan(self):
        if not self._all_paths:
            return
        self._result_list.setSortingEnabled(False)
        self._result_list.setRowCount(0)
        self._report_text.clear()
        self._batch_result = None
        self._btn_save.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._all_paths))
        self._progress.setValue(0)
        self._btn_scan.setEnabled(False)
        self._btn_stop_scan.setVisible(True)

        self._worker = BatchWorker(self._all_paths)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.cancelled.connect(self._on_scan_cancelled)
        self._worker.start()

    def _stop_scan(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()

    def _on_scan_cancelled(self, result: BatchResult):
        done = result.total
        total = len(self._all_paths)
        self._progress.setVisible(False)
        self._btn_stop_scan.setVisible(False)
        self._btn_scan.setEnabled(True)
        self._btn_full_report.setEnabled(bool(result.results))

        if result.results:
            self._batch_result = result
            self._result_list.setSortingEnabled(False)
            self._result_list.setRowCount(len(result.results))
            for row, fr in enumerate(result.results):
                self._populate_row(row, fr, self._threshold)
            self._result_list.setSortingEnabled(True)
            self._report_text.setHtml(self._build_report())

        self._set_status(
            STRINGS["batch_status_cancelled"].format(done=done, total=total)
        )

    def _on_progress(self, current: int, total: int, name: str):
        self._progress.setValue(current)
        self._set_status(STRINGS["batch_status_scanning"].format(current=current, total=total, name=name))

    def _on_scan_done(self, result: BatchResult):
        self._batch_result = result
        self._progress.setVisible(False)
        self._btn_stop_scan.setVisible(False)
        self._btn_scan.setEnabled(True)
        self._btn_full_report.setEnabled(True)

        self._result_list.setSortingEnabled(False)
        self._result_list.setRowCount(len(result.results))
        for row, fr in enumerate(result.results):
            self._populate_row(row, fr, self._threshold)
        self._result_list.setSortingEnabled(True)

        self._update_summary_counts()
        self._report_text.setHtml(self._build_report())

    def _build_report(self) -> str:
        """Build a rich HTML summary report for the full batch."""
        if not self._batch_result:
            return ""
        t = self._threshold
        cleaning_opts = load_cleaning_options()
        flagged, clean, errors = [], [], []
        for r in self._batch_result.results:
            if r.error:
                errors.append(r)
                continue
            ads, warns = _classify(r.subtitle, t) if r.subtitle else (0, 0)
            opts_count = sum(
                1 for b in r.subtitle.blocks
                if b.regex_matches < t
                and block_will_be_removed(b.content, cleaning_opts)
            ) if (r.subtitle and cleaning_opts.any_enabled()) else 0
            if ads > 0 or opts_count > 0 or (warns > 0 and self._chk_warnings.isChecked()):
                flagged.append((r, ads, warns, opts_count))
            else:
                clean.append(r)

        def esc(s): 
            return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

        html = [f"""
<style>
  body {{ background:#161b26; color:#cdd6f4; font-family:Consolas,monospace; font-size:13px; margin:8px; }}
  .section {{ color:#4e9eff; font-size:11px; letter-spacing:1px; text-transform:uppercase;
              margin-top:16px; margin-bottom:6px; border-bottom:1px solid #2a3347;
              padding-bottom:3px; }}
  .stat-row {{ margin:3px 0; font-size:13px; }}
  .stat-label {{ color:#6c7a96; }}
  .stat-val {{ color:#cdd6f4; font-weight:bold; }}
  .file-header {{ margin-top:14px; margin-bottom:2px; padding:5px 10px;
                  background:#1e2535; border-left:3px solid #f38ba8; color:#cdd6f4; }}
  .file-warn   {{ border-left-color:#fab387; }}
  .block-ad    {{ margin:2px 0 2px 0px; padding:5px 10px; background:#2a1a22;
                  border-left:4px solid #f38ba8; }}
  .block-opt   {{ margin:2px 0 2px 0px; padding:5px 10px; background:#1a1f2e;
                  border-left:4px solid #4e9eff; }}
  .block-warn  {{ margin:2px 0 2px 0px; padding:5px 10px; background:#231f15;
                  border-left:4px solid #fab387; }}
  .block-text  {{ color:#ff9eb5; font-weight:bold; font-size:13px; }}
  .block-text-warn {{ color:#ffc990; font-weight:bold; font-size:13px; }}
  .block-ts    {{ color:#7dcfff; font-size:12px; }}
  .block-meta  {{ color:#6c7a96; font-size:11px; margin-top:3px; }}
  .tag-ad      {{ color:#ff9eb5; font-weight:bold; }}
  .tag-warn    {{ color:#ffc990; font-weight:bold; }}
  .tag-clean   {{ color:#9ece6a; font-weight:bold; }}
  .reason      {{ color:#565f89; font-size:11px; margin-right:6px; }}
  .divider     {{ color:#2a3347; }}
</style>
<div class="section">{STRINGS["rpt_batch_summary"]}</div>
<div class="stat-row"><span class="stat-label">{STRINGS["rpt_batch_threshold"]} </span>
  <span class="stat-val">regex_matches ≥ {t}</span></div>
<div class="stat-row"><span class="stat-label">{STRINGS["rpt_batch_scanned"]} </span>
  <span class="stat-val">{self._batch_result.total}</span></div>
<div class="stat-row"><span class="stat-label">{STRINGS["rpt_batch_to_clean"]} </span>
  <span class="stat-val" style="color:#f38ba8">{len(flagged)}</span></div>
<div class="stat-row"><span class="stat-label">{STRINGS["rpt_batch_clean"]} </span>
  <span class="stat-val" style="color:#a6e3a1">{len(clean)}</span></div>
<div class="stat-row"><span class="stat-label">{STRINGS["rpt_batch_errors"]} </span>
  <span class="stat-val">{len(errors)}</span></div>
"""]

        if flagged:
            html.append('<div class="section">' + STRINGS["rpt_batch_flagged"] + '</div>')
            for r, ads, warns, opts_count in flagged:
                ad_tag = f'<span class="tag-ad">{ads} ' + STRINGS["rpt_lbl_ads"] + '</span>' if ads else ''
                opt_tag = (f'<span style="color:#4e9eff;font-weight:bold">{opts_count} ' + STRINGS["rpt_lbl_opts"] + '</span>'
                           if opts_count else '')
                sep = ' + ' if ad_tag and opt_tag else ''
                wn_tag = f'<span class="tag-warn">{warns} ' + STRINGS["rpt_lbl_warns"] + '</span>' if warns else ''
                html.append(f'<div class="file-header">'
                            f'&nbsp;{ad_tag}{sep}{opt_tag} {wn_tag}&nbsp;&nbsp;'
                            f'<span style="color:#cdd6f4">{esc(r.path.parent.name)}/</span>'
                            f'<span style="color:#fff;font-weight:bold">{esc(r.path.name)}</span>'
                            f'</div>')
                if r.subtitle:
                    for b in r.subtitle.blocks:
                        will_clean = block_will_be_removed(b.content, cleaning_opts)
                        reasons_html = " ".join(
                            f'<span class="reason-tag">{esc(h)}</span>'
                            for h in dict.fromkeys(b.hints)
                        )
                        if b.regex_matches >= t:
                            html.append(
                                f'<div class="block-ad">'
                                f'<span class="tag-ad">' + STRINGS["rpt_tag_ad"] + '</span>&nbsp;'
                                f'<span class="block-ts">[{esc(b.start)}]</span>&nbsp;'
                                f'<span class="block-text">{esc(b.text[:80])}</span>'
                                f'<div class="block-meta">{reasons_html}</div>'
                                f'</div>'
                            )
                        elif will_clean:
                            html.append(
                                f'<div class="block-opt">'
                                f'<span style="color:#4e9eff;font-weight:bold">' + STRINGS["rpt_tag_clean_opt"] + '</span>&nbsp;'
                                f'<span class="block-ts">[{esc(b.start)}]</span>&nbsp;'
                                f'<span style="color:#89b4fa">{esc(b.text[:80])}</span>'
                                f'<div class="block-meta" style="color:#4e9eff">'
                                + STRINGS["rpt_lbl_cleaning_opts"] + '</div>'
                                f'</div>'
                            )
                        elif b.regex_matches == t - 1 and t > 1:
                            html.append(
                                f'<div class="block-warn">'
                                f'<span class="tag-warn">' + STRINGS["rpt_tag_warn"] + '</span>&nbsp;'
                                f'<span class="block-ts">[{esc(b.start)}]</span>&nbsp;'
                                f'<span class="block-text-warn">{esc(b.text[:80])}</span>'
                                f'<div class="block-meta">{reasons_html}</div>'
                                f'</div>'
                            )

        if errors:
            html.append('<div class="section">' + STRINGS["rpt_batch_errors_section"] + '</div>')
            for r in errors:
                html.append(f'<div style="color:#888;margin:2px 0">'
                            f'✕ {esc(r.path.name)} — {esc(r.error)}</div>')

        if clean:
            html.append('<div class="section">' + STRINGS["rpt_batch_clean_section"] + '</div>')
            for r in clean:
                html.append(f'<div style="color:#6c7a96;margin:1px 0">'
                            f'<span class="tag-clean">' + STRINGS["rpt_tag_clean"] + '</span>&nbsp;'
                            f'{esc(r.path.parent.name)}/{esc(r.path.name)}</div>')

        return "\n".join(html)

    # ── Detail on row click ───────────────────────────────────────────────

    def _on_row_selected(self, row: int):
        if row < 0 or not self._batch_result:
            self._btn_open_in_review.setEnabled(False)
            self._current_fr = None
            return
        item = self._result_list.item(row, 0)
        if item is None:
            self._btn_open_in_review.setEnabled(False)
            self._current_fr = None
            return
        fr = item.data(Qt.ItemDataRole.UserRole)
        self._current_fr = fr
        self._btn_open_in_review.setEnabled(fr.ok)

        if not fr.subtitle:
            msg = f"Error: {fr.error}" if fr.error else "No data."
            self._report_text.setHtml(f"<p style='color:#888;font-family:Consolas'>{msg}</p>")
            return

        def esc(s):
            return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

        t = self._threshold
        cleaning_opts = load_cleaning_options()
        ads, warns = _classify(fr.subtitle, t)

        html = [f"""<style>
  body {{ background:#161b26; color:#cdd6f4; font-family:Consolas,monospace;
          font-size:13px; margin:8px; }}
  .file-path {{ color:#6c7a96; font-size:12px; word-break:break-all; }}
  .file-name {{ color:#ffffff; font-weight:bold; font-size:14px; }}
  .summary   {{ margin:6px 0 12px 0; color:#6c7a96; font-size:12px;
                border-bottom:1px solid #2a3347; padding-bottom:6px; }}
  .block-ad  {{ margin:4px 0; padding:6px 12px; background:#2a1a22;
                border-left:4px solid #f38ba8; }}
  .block-opt {{ margin:4px 0; padding:6px 12px; background:#1a1f2e;
                border-left:4px solid #4e9eff; }}
  .block-warn{{ margin:4px 0; padding:6px 12px; background:#231f15;
                border-left:4px solid #fab387; }}
  .block-kept{{ margin:4px 0; padding:6px 12px; background:#1e2535;
                border-left:4px solid #6c7a96; }}
  .tag-kept  {{ color:#6c7a96; font-style:italic; }}
  .kept-text {{ color:#6c7a96; font-style:italic; text-decoration:line-through; }}
  .tag-ad    {{ color:#ff9eb5; font-weight:bold; }}
  .tag-warn  {{ color:#ffc990; font-weight:bold; }}
  .ts        {{ color:#7dcfff; font-size:12px; }}
  .ad-text   {{ color:#ff9eb5; font-weight:bold; font-size:13px; }}
  .opt-text  {{ color:#89b4fa; font-size:13px; }}
  .warn-text {{ color:#ffc990; font-weight:bold; font-size:13px; }}
  .rm        {{ color:#565f89; font-size:11px; }}
  .reason    {{ color:#565f89; font-size:11px; margin-right:8px; }}
  .clean-msg {{ color:#9ece6a; margin-top:12px; font-size:13px; }}
</style>
<div class="file-path">{esc(fr.path.parent)}/</div>
<div class="file-name">{esc(fr.path.name)}</div>
<div class="summary">
  {STRINGS["rpt_batch_threshold"]} rm≥{t} &nbsp;|&nbsp;
  {len(fr.subtitle.blocks)} {STRINGS["rpt_video_blocks"][:-1].lower()} &nbsp;|&nbsp;
  <span style="color:#f38ba8">{ads} {STRINGS["rpt_lbl_ads"]}</span> &nbsp;|&nbsp;
  <span style="color:#fab387">{warns} {STRINGS["rpt_lbl_warns"]}</span>
</div>"""]

        found_any = False
        BRD = '#2a3347'
        FG2 = '#6c7a96'
        for b in fr.subtitle.blocks:
            is_kept = getattr(b, '_kept', False)
            will_clean = block_will_be_removed(b.content, cleaning_opts)
            if b.regex_matches >= t or will_clean or (b.regex_matches == t - 1 and t > 1):
                found_any = True
                is_ad = b.regex_matches >= t
                reasons_html = " ".join(
                    f'<span class="reason">{esc(h)}</span>'
                    for h in dict.fromkeys(b.hints)
                )
                if will_clean and b.regex_matches < t:
                    reasons_html += '<span class="reason" style="color:#4e9eff">' + STRINGS["rpt_lbl_cleaning_opts"] + '</span>'
                if is_kept:
                    div_cls  = "block-kept"
                    tag      = '<span class="tag-kept">' + STRINGS["rpt_tag_kept"] + '</span>'
                    txt_cls  = "kept-text"
                    btn_lbl  = STRINGS["rpt_btn_kept"]
                    btn_col  = FG2
                elif will_clean and b.regex_matches < t:
                    div_cls  = "block-opt"
                    tag      = '<span style="color:#4e9eff;font-weight:bold">' + STRINGS["rpt_tag_clean_opt"] + '</span>'
                    txt_cls  = "opt-text"
                    btn_lbl  = STRINGS["rpt_btn_keep"]
                    btn_col  = FG2
                elif is_ad:
                    div_cls  = "block-ad"
                    tag      = '<span class="tag-ad">' + STRINGS["rpt_tag_ad"] + '</span>'
                    txt_cls  = "ad-text"
                    btn_lbl  = STRINGS["rpt_btn_keep"]
                    btn_col  = FG2
                else:
                    div_cls  = "block-warn"
                    tag      = '<span class="tag-warn">' + STRINGS["rpt_tag_warn"] + '</span>'
                    txt_cls  = "warn-text"
                    btn_lbl  = STRINGS["rpt_btn_keep"]
                    btn_col  = FG2
                html.append(
                    f'<div class="{div_cls}">'
                    f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
                    f'<td>{tag}&nbsp;<span class="rm">rm={b.regex_matches}</span>'
                    f'&nbsp;&nbsp;<span class="ts">[{esc(b.start)}]</span></td>'
                    f'<td align="right">'
                    f'<a href="keep:{id(b)}" style="color:{btn_col};font-size:10pt;'
                    f'border:1px solid {BRD};padding:2px 10px;'
                    f'border-radius:3px;text-decoration:none;white-space:nowrap;">'
                    f'{btn_lbl}</a>'
                    f'</td></tr></table>'
                    f'<span class="{txt_cls}">{esc(b.text[:120])}</span><br>'
                    f'<span>{reasons_html}</span>'
                    f'</div>'
                )

        if not found_any:
            html.append('<div class="clean-msg">' + STRINGS["rpt_batch_no_issues"] + '</div>')

        # Append cleaning options report if any changes were made
        cr = getattr(fr, 'cleaning_report', None)
        if cr and cr.any_changes:
            html.append('<div class="section">' + STRINGS["rpt_batch_cleaning_section"] + '</div>')
            if cr.removals():
                html.append(f'<div class="meta-row" style="color:#f38ba8">')
                html.append(f'Removed {len(cr.removals())} block(s):</div>')
                for a in cr.removals():
                    html.append(
                        f'<div class="block-ad">'
                        f'<span class="tag-ad">' + STRINGS["rpt_tag_removed"] + '</span>&nbsp;'
                        f'<span class="block-ts">[{esc(a.timestamp)}]</span>&nbsp;'
                        f'<span style="color:#f38ba8">{esc(a.reason)}</span><br>'
                        f'<span style="color:#888;text-decoration:line-through">'
                        f'{esc(a.original)}</span></div>'
                    )
            if cr.modifications():
                html.append(f'<div class="meta-row" style="color:#ffc990">')
                html.append(f'Modified {len(cr.modifications())} block(s):</div>')
                for a in cr.modifications():
                    html.append(
                        f'<div class="block-warn">'
                        f'<span class="tag-warn">' + STRINGS["rpt_tag_modified"] + '</span>&nbsp;'
                        f'<span class="block-ts">[{esc(a.timestamp)}]</span>&nbsp;'
                        f'<span style="color:#ffc990">{esc(a.reason)}</span><br>'
                        f'<span style="color:#888;text-decoration:line-through">'
                        f'{esc(a.original)}</span></div>'
                    )
            if cr.duplicates_merged:
                html.append(
                    f'<div class="meta-row" style="color:#a6e3a1">'
                    f'Merged {cr.duplicates_merged} duplicate cue(s).</div>'
                )

        self._report_text.setHtml("\n".join(html))

    def _on_report_link(self, url):
        """Handle Keep/undo links in the per-file detail report."""
        url_str = url.toString()
        if not url_str.startswith("keep:"):
            return
        block_id = int(url_str[5:])
        if self._batch_result:
            for fr in self._batch_result.results:
                if fr.subtitle:
                    for b in fr.subtitle.blocks:
                        if id(b) == block_id:
                            b._kept = not getattr(b, '_kept', False)
                            sel = self._result_list.selectedItems()
                            if sel:
                                self._on_row_selected(self._result_list.row(sel[0]))
                            return

    def _show_full_report(self):
        if self._batch_result:
            self._result_list.clearSelection()
            self._current_fr = None
            self._btn_full_report.setEnabled(True)
            self._report_text.setHtml(self._build_report())
            self._btn_open_in_review.setEnabled(False)

    def _open_in_review(self):
        if not self._batch_result:
            return
        sel = self._result_list.selectedItems()
        if not sel:
            return
        item = self._result_list.item(self._result_list.row(sel[0]), 0)
        if item is None:
            return
        fr = item.data(Qt.ItemDataRole.UserRole)
        self.open_file_requested.emit(fr.path)

    # ── Save all ──────────────────────────────────────────────────────────

    def _save_all(self):
        if not self._batch_result:
            return

        t = self._threshold
        inc_warns = self._chk_warnings.isChecked()

        # Build list of (FileResult, blocks_to_remove) using current threshold
        to_clean = []
        for r in self._batch_result.results:
            if not r.ok or not r.subtitle:
                continue
            remove = [b for b in r.subtitle.blocks
                      if b.regex_matches >= t and not getattr(b, '_kept', False)]
            if inc_warns:
                remove += [b for b in r.subtitle.blocks
                           if b.regex_matches == t - 1 and t > 1
                           and id(b) not in {id(x) for x in remove}
                           and not getattr(b, '_kept', False)]
            if remove:
                to_clean.append((r, remove))

        if not to_clean:
            QMessageBox.information(self, STRINGS["dlg_nothing_to_clean"], STRINGS["dlg_nothing_to_clean_msg"])
            return

        total_blocks = sum(len(blocks) for _, blocks in to_clean)
        answer = QMessageBox.question(
            self, STRINGS["dlg_confirm_batch"],
            STRINGS["dlg_confirm_batch_msg"].format(blocks=total_blocks, files=len(to_clean), thresh=t),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._progress.setVisible(True)
        self._progress.setRange(0, len(to_clean))
        errors = []

        for i, (r, remove_blocks) in enumerate(to_clean):
            self._progress.setValue(i)
            self._set_status(STRINGS["batch_saving"].format(i=i+1, total=len(to_clean), name=r.path.name))
            QApplication_processEvents()

            remove_ids = {id(b) for b in remove_blocks}
            r.subtitle.blocks = [b for b in r.subtitle.blocks
                                  if id(b) not in remove_ids]
            for idx, b in enumerate(r.subtitle.blocks, 1):
                b.current_index = idx

            # Apply global cleaning options
            opts = load_cleaning_options()
            if opts.any_enabled():
                _, _cr = apply_cleaning_options(r.subtitle, opts)
                r.cleaning_report = _cr

            try:
                from core.subtitle import write_subtitle
                write_subtitle(r.subtitle)
                r.saved = True
            except Exception as e:
                errors.append(f"{r.path.name}: {e}")

        self._progress.setVisible(False)

        if errors:
            QMessageBox.warning(self, STRINGS["dlg_saves_failed"], "\n".join(errors))
        else:
            saved = len(to_clean)
            self._set_status(STRINGS["batch_done_status"].format(saved=saved, thresh=t))
            QMessageBox.information(self, STRINGS["dlg_done"], STRINGS["dlg_done_msg"].format(saved=saved))

        # Refresh list colours
        self._refresh_rows()
        self._update_summary_counts()

    # ── Public API ────────────────────────────────────────────────────────

    def load_paths(self, paths: List[Path]):
        subtitle_paths = collect_files(paths, recursive=True)
        self._all_paths = subtitle_paths
        if subtitle_paths:
            self._btn_scan.setEnabled(True)
            self._set_status(STRINGS["batch_files_queued"].format(n=len(subtitle_paths)))


def QApplication_processEvents():
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
