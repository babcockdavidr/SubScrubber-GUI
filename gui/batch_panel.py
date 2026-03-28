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

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QProgressBar,
    QFileDialog, QMessageBox, QCheckBox, QAbstractItemView,
    QSplitter, QSlider, QFrame, QSizePolicy,
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import collect_files, run_batch, save_batch, BatchResult, FileResult, SUPPORTED_EXTENSIONS
from core.subtitle import ParsedSubtitle
from .colors import BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW


# ---------------------------------------------------------------------------
# Threshold helpers
# ---------------------------------------------------------------------------

# Slider maps 1–5 to a regex_matches threshold.
# Lower = more aggressive (catches more, higher false-positive risk)
# Higher = more conservative (only removes obvious ads)
THRESHOLD_LABELS = {
    1: "Very Aggressive  (rm ≥ 1)",
    2: "Aggressive       (rm ≥ 2)",
    3: "Balanced         (rm ≥ 3)  ← default",
    4: "Conservative     (rm ≥ 4)",
    5: "Very Conservative(rm ≥ 5)",
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
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)          # BatchResult

    def __init__(self, paths: List[Path]):
        super().__init__()
        self.paths = paths

    def run(self):
        def cb(i, total, path):
            self.progress.emit(i, total, path.name)
        result = run_batch(self.paths, progress_cb=cb)
        self.finished.emit(result)


# ---------------------------------------------------------------------------
# Result row
# ---------------------------------------------------------------------------

class ResultRow(QListWidgetItem):
    def __init__(self, fr: FileResult, threshold: int = 3):
        super().__init__()
        self.file_result = fr
        self.refresh(threshold)

    def refresh(self, threshold: int = 3):
        fr = self.file_result
        if fr.error:
            self.setText(f"[ ERROR  ]  {fr.path.name}")
            self.setForeground(QColor("#888888"))
            return

        if fr.subtitle:
            ads, warns = _classify(fr.subtitle, threshold)
        else:
            ads, warns = fr.ad_count, fr.warning_count

        # Show relative path (parent folder / filename) so user knows the movie
        try:
            display = str(fr.path.parent.name) + "/" + fr.path.name
        except Exception:
            display = fr.path.name

        if ads > 0:
            self.setText(f"[{ads:>2} ads  ]  {display}")
            self.setForeground(QColor(RED))
        elif warns > 0:
            self.setText(f"[{warns:>2} warns]  {display}")
            self.setForeground(QColor(ORANGE))
        else:
            self.setText(f"[  clean ]  {display}")
            self.setForeground(QColor(GREEN))


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class BatchPanel(QWidget):
    open_file_requested = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._batch_result: Optional[BatchResult] = None
        self._worker: Optional[BatchWorker] = None
        self._all_paths: List[Path] = []
        self._root_folder: Optional[Path] = None
        self._threshold: int = 3
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Folder selection row ──────────────────────────────────────────
        folder_row = QHBoxLayout()

        self._lbl_folder = QLabel("No folder selected")
        self._lbl_folder.setStyleSheet(f"color: {FG2}; font-size: 12px;")
        self._lbl_folder.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Preferred)

        self._btn_folder = QPushButton("📂  Select Movies Folder…")
        self._btn_folder.setStyleSheet(
            f"font-size: 13px; font-weight: bold; padding: 8px 18px;"
            f"background: {BG3}; border: 1px solid {ACCENT}; color: {ACCENT};"
            f"border-radius: 4px;"
        )
        self._btn_clear = QPushButton("Clear")

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

        thresh_title = QLabel("Sensitivity:")
        thresh_title.setStyleSheet(f"color: {FG}; font-size: 12px; font-weight: bold;")

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(1)
        self._slider.setMaximum(5)
        self._slider.setValue(3)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(1)
        self._slider.setFixedWidth(200)

        self._lbl_threshold = QLabel(THRESHOLD_LABELS[3])
        self._lbl_threshold.setStyleSheet(f"color: {YELLOW}; font-size: 11px;")

        # Endpoint labels
        lbl_aggressive = QLabel("More aggressive")
        lbl_aggressive.setStyleSheet(f"color: {RED}; font-size: 10px;")
        lbl_conservative = QLabel("More conservative")
        lbl_conservative.setStyleSheet(f"color: {GREEN}; font-size: 10px;")

        thresh_layout.addWidget(thresh_title)
        thresh_layout.addWidget(lbl_aggressive)
        thresh_layout.addWidget(self._slider)
        thresh_layout.addWidget(lbl_conservative)
        thresh_layout.addSpacing(16)
        thresh_layout.addWidget(self._lbl_threshold, stretch=1)

        # ── Action row ────────────────────────────────────────────────────
        action_row = QHBoxLayout()

        self._chk_warnings = QCheckBox("Also remove warnings (one level below threshold)")
        self._chk_warnings.setStyleSheet(f"color: {FG2}; font-size: 12px;")

        self._btn_scan = QPushButton("⚡  Scan All")
        self._btn_scan.setObjectName("btn_clean_all")
        self._btn_scan.setEnabled(False)

        self._btn_save = QPushButton("🗑  Clean && Save All")
        self._btn_save.setObjectName("btn_clean_all")
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(
            f"font-size: 13px; font-weight: bold; padding: 8px 20px;"
            f"background: {RED}22; color: {RED}; border: 1px solid {RED};"
            f"border-radius: 4px;"
        )

        action_row.addWidget(self._chk_warnings)
        action_row.addStretch()
        action_row.addWidget(self._btn_scan)
        action_row.addWidget(self._btn_save)

        # ── Progress / status ─────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(6)

        self._lbl_status = QLabel("Select a movies folder to begin.")
        self._lbl_status.setObjectName("file_status")

        # ── Splitter: file list | detail ──────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: result list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        lbl_files = QLabel("SCANNED FILES")
        lbl_files.setObjectName("section_label")

        self._result_list = QListWidget()
        self._result_list.setFont(QFont("Consolas", 11))
        self._result_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self._btn_open_in_review = QPushButton("Open in Review Tab →")
        self._btn_open_in_review.setEnabled(False)

        ll.addWidget(lbl_files)
        ll.addWidget(self._result_list, stretch=1)
        ll.addWidget(self._btn_open_in_review)

        # Right: detail report
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        lbl_report = QLabel("BATCH REPORT")
        lbl_report.setObjectName("section_label")

        self._report_text = QTextEdit()
        self._report_text.setReadOnly(True)
        self._report_text.setFont(QFont("Consolas", 11))

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
        root.addWidget(self._lbl_status)
        root.addWidget(splitter, stretch=1)

        # ── Connect ───────────────────────────────────────────────────────
        self._btn_folder.clicked.connect(self._select_folder)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_scan.clicked.connect(self._scan)
        self._btn_save.clicked.connect(self._save_all)
        self._slider.valueChanged.connect(self._on_threshold_changed)
        self._result_list.currentRowChanged.connect(self._on_row_selected)
        self._btn_open_in_review.clicked.connect(self._open_in_review)

    # ── Folder selection ──────────────────────────────────────────────────

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Movies / Shows Folder")
        if not folder:
            return
        self._root_folder = Path(folder)
        self._lbl_folder.setText(str(self._root_folder))
        # Always recursive — scan all subtitle files under the root
        paths = collect_files([self._root_folder], recursive=True)
        self._all_paths = paths
        if paths:
            self._lbl_status.setText(
                f"Found {len(paths)} subtitle file(s) under {self._root_folder.name}. "
                f"Click Scan All to analyse."
            )
            self._btn_scan.setEnabled(True)
        else:
            self._lbl_status.setText("No subtitle files found in that folder.")
            self._btn_scan.setEnabled(False)

    def _clear(self):
        self._all_paths.clear()
        self._root_folder = None
        self._batch_result = None
        self._result_list.clear()
        self._report_text.clear()
        self._btn_scan.setEnabled(False)
        self._btn_save.setEnabled(False)
        self._lbl_folder.setText("No folder selected")
        self._lbl_status.setText("Select a movies folder to begin.")

    # ── Threshold slider ──────────────────────────────────────────────────

    def _on_threshold_changed(self, value: int):
        self._threshold = value
        self._lbl_threshold.setText(THRESHOLD_LABELS.get(value, str(value)))
        # Re-classify and refresh all rows live without rescanning
        if self._batch_result:
            self._refresh_rows()
            self._update_summary_counts()

    def _refresh_rows(self):
        for i in range(self._result_list.count()):
            item = self._result_list.item(i)
            if isinstance(item, ResultRow):
                item.refresh(self._threshold)

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
        self._lbl_status.setText(
            f"Scan complete — {self._batch_result.total} files · "
            f"{files_with_ads} with ads ({total_ads} blocks) · "
            f"{total_warns} warnings · threshold: rm≥{self._threshold}"
        )
        self._btn_save.setEnabled(files_with_ads > 0)

    # ── Scanning ──────────────────────────────────────────────────────────

    def _scan(self):
        if not self._all_paths:
            return
        self._result_list.clear()
        self._report_text.clear()
        self._batch_result = None
        self._btn_save.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._all_paths))
        self._progress.setValue(0)
        self._btn_scan.setEnabled(False)

        self._worker = BatchWorker(self._all_paths)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_progress(self, current: int, total: int, name: str):
        self._progress.setValue(current)
        self._lbl_status.setText(f"Scanning {current}/{total}: {name}")

    def _on_scan_done(self, result: BatchResult):
        self._batch_result = result
        self._progress.setVisible(False)
        self._btn_scan.setEnabled(True)

        self._result_list.clear()
        for fr in result.results:
            self._result_list.addItem(ResultRow(fr, self._threshold))

        self._update_summary_counts()
        self._report_text.setText(self._build_report())

    def _build_report(self) -> str:
        if not self._batch_result:
            return ""
        t = self._threshold
        lines = [
            f"Batch scan — threshold: regex_matches ≥ {t}",
            f"{'─'*50}",
            f"Total files scanned: {self._batch_result.total}",
            f"Errors:              {len(self._batch_result.errors)}",
            "",
        ]
        flagged = []
        clean = []
        for r in self._batch_result.results:
            if r.error:
                continue
            if r.subtitle:
                ads, warns = _classify(r.subtitle, t)
            else:
                ads, warns = 0, 0
            if ads > 0 or (warns > 0 and self._chk_warnings.isChecked()):
                flagged.append((r, ads, warns))
            else:
                clean.append(r)

        lines.append(f"Files to clean:      {len(flagged)}")
        lines.append(f"Clean files:         {len(clean)}")
        lines.append("")

        if flagged:
            lines.append("── Files with issues ──────────────────────────────")
            for r, ads, warns in flagged:
                lines.append(f"  [{ads:>2} ads, {warns:>2} warns]  {r.path}")
                if r.subtitle:
                    for b in r.subtitle.blocks:
                        if b.regex_matches >= t:
                            reasons = ", ".join(dict.fromkeys(b.hints))
                            lines.append(f"    [{b.start}]  {b.text[:60]}")
                            if reasons:
                                lines.append(f"             {reasons}")
        return "\n".join(lines)

    # ── Detail on row click ───────────────────────────────────────────────

    def _on_row_selected(self, row: int):
        if row < 0 or not self._batch_result:
            self._btn_open_in_review.setEnabled(False)
            return
        fr = self._batch_result.results[row]
        self._btn_open_in_review.setEnabled(fr.ok)

        if not fr.subtitle:
            self._report_text.setText(f"Error: {fr.error}" if fr.error else "No data.")
            return

        t = self._threshold
        ads, warns = _classify(fr.subtitle, t)
        lines = [
            f"File: {fr.path}",
            f"Threshold: regex_matches ≥ {t}",
            f"Blocks: {len(fr.subtitle.blocks)} total  |  {ads} ads  |  {warns} warnings",
            "",
        ]
        for b in fr.subtitle.blocks:
            if b.regex_matches >= t:
                status = "AD  "
            elif b.regex_matches == t - 1 and t > 1:
                status = "WARN"
            else:
                continue
            reasons = ", ".join(dict.fromkeys(b.hints))
            lines.append(f"  [{status}] rm={b.regex_matches:>2}  [{b.start}]  {b.text[:60]}")
            if reasons:
                lines.append(f"           {reasons}")
        if ads == 0 and warns == 0:
            lines.append("  (no issues at this threshold)")
        self._report_text.setText("\n".join(lines))

    def _open_in_review(self):
        if not self._batch_result:
            return
        row = self._result_list.currentRow()
        if row < 0:
            return
        fr = self._batch_result.results[row]
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
            remove = [b for b in r.subtitle.blocks if b.regex_matches >= t]
            if inc_warns:
                remove += [b for b in r.subtitle.blocks
                           if b.regex_matches == t - 1 and t > 1
                           and id(b) not in {id(x) for x in remove}]
            if remove:
                to_clean.append((r, remove))

        if not to_clean:
            QMessageBox.information(self, "Nothing to clean",
                                    "No files have issues at the current threshold.")
            return

        total_blocks = sum(len(blocks) for _, blocks in to_clean)
        answer = QMessageBox.question(
            self, "Confirm batch clean",
            f"Remove {total_blocks} block(s) from {len(to_clean)} file(s) and save?\n\n"
            f"Threshold: regex_matches ≥ {t}\n"
            f"This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._progress.setVisible(True)
        self._progress.setRange(0, len(to_clean))
        errors = []

        for i, (r, remove_blocks) in enumerate(to_clean):
            self._progress.setValue(i)
            self._lbl_status.setText(f"Saving {i+1}/{len(to_clean)}: {r.path.name}")
            QApplication_processEvents()

            remove_ids = {id(b) for b in remove_blocks}
            r.subtitle.blocks = [b for b in r.subtitle.blocks
                                  if id(b) not in remove_ids]
            for idx, b in enumerate(r.subtitle.blocks, 1):
                b.current_index = idx
            try:
                from core.subtitle import write_subtitle
                write_subtitle(r.subtitle)
                r.saved = True
            except Exception as e:
                errors.append(f"{r.path.name}: {e}")

        self._progress.setVisible(False)

        if errors:
            QMessageBox.warning(self, "Some saves failed", "\n".join(errors))
        else:
            saved = len(to_clean)
            self._lbl_status.setText(
                f"Done — {saved} file(s) cleaned at threshold rm≥{t}.")
            QMessageBox.information(self, "Done",
                                    f"{saved} file(s) cleaned and saved.")

        # Refresh list colours
        self._refresh_rows()
        self._update_summary_counts()

    # ── Public API ────────────────────────────────────────────────────────

    def load_paths(self, paths: List[Path]):
        subtitle_paths = collect_files(paths, recursive=True)
        self._all_paths = subtitle_paths
        if subtitle_paths:
            self._btn_scan.setEnabled(True)
            self._lbl_status.setText(
                f"{len(subtitle_paths)} subtitle file(s) queued.")


def QApplication_processEvents():
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
