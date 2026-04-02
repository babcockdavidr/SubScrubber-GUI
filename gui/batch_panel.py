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
    QListWidget, QListWidgetItem, QTextEdit, QTextBrowser, QProgressBar,
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
        self._lbl_folder.setStyleSheet(f"color: {FG2}; font-size: 10pt;")
        self._lbl_folder.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Preferred)

        self._btn_folder = QPushButton("Select Base Folder…")
        self._btn_folder.setObjectName("btn_clean_all")
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
        thresh_title.setStyleSheet(f"color: {FG}; font-size: 10pt; font-weight: bold;")

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(1)
        self._slider.setMaximum(5)
        self._slider.setValue(3)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(1)
        self._slider.setFixedWidth(200)

        self._lbl_threshold = QLabel(THRESHOLD_LABELS[3])
        self._lbl_threshold.setStyleSheet(f"color: {YELLOW}; font-size: 9pt;")

        # Endpoint labels
        lbl_aggressive = QLabel("More aggressive")
        lbl_aggressive.setStyleSheet(f"color: {RED}; font-size: 8pt;")
        lbl_conservative = QLabel("More conservative")
        lbl_conservative.setStyleSheet(f"color: {GREEN}; font-size: 8pt;")

        thresh_layout.addWidget(thresh_title)
        thresh_layout.addWidget(lbl_aggressive)
        thresh_layout.addWidget(self._slider)
        thresh_layout.addWidget(lbl_conservative)
        thresh_layout.addSpacing(16)
        thresh_layout.addWidget(self._lbl_threshold, stretch=1)

        # ── Action row ────────────────────────────────────────────────────
        action_row = QHBoxLayout()

        self._chk_warnings = QCheckBox("Also remove warnings (one level below threshold)")
        self._chk_warnings.setStyleSheet(f"color: {FG2}; font-size: 10pt;")

        self._btn_scan = QPushButton("Scan All")
        self._btn_scan.setObjectName("btn_clean_all")
        self._btn_scan.setEnabled(False)

        self._btn_save = QPushButton("Clean && Save All")
        self._btn_save.setObjectName("btn_save")
        self._btn_save.setEnabled(False)

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

        self._btn_open_in_review = QPushButton("Open in Single File Tab")
        self._btn_open_in_review.setEnabled(False)
        self._btn_full_report = QPushButton("Show Full Report")
        self._btn_full_report.setEnabled(False)
        self._btn_full_report.setToolTip("Restore the full batch summary report.")

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

        lbl_report = QLabel("BATCH REPORT")
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
        self._btn_full_report.clicked.connect(self._show_full_report)

    # ── Folder selection ──────────────────────────────────────────────────

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
        self._btn_full_report.setEnabled(False)
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
        self._btn_full_report.setEnabled(True)

        self._result_list.clear()
        for fr in result.results:
            self._result_list.addItem(ResultRow(fr, self._threshold))

        self._update_summary_counts()
        self._report_text.setHtml(self._build_report())

    def _build_report(self) -> str:
        """Build a rich HTML summary report for the full batch."""
        if not self._batch_result:
            return ""
        t = self._threshold
        flagged, clean, errors = [], [], []
        for r in self._batch_result.results:
            if r.error:
                errors.append(r)
                continue
            ads, warns = _classify(r.subtitle, t) if r.subtitle else (0, 0)
            if ads > 0 or (warns > 0 and self._chk_warnings.isChecked()):
                flagged.append((r, ads, warns))
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
<div class="section">BATCH SUMMARY</div>
<div class="stat-row"><span class="stat-label">Threshold: </span>
  <span class="stat-val">regex_matches ≥ {t}</span></div>
<div class="stat-row"><span class="stat-label">Files scanned: </span>
  <span class="stat-val">{self._batch_result.total}</span></div>
<div class="stat-row"><span class="stat-label">Files to clean: </span>
  <span class="stat-val" style="color:#f38ba8">{len(flagged)}</span></div>
<div class="stat-row"><span class="stat-label">Clean files: </span>
  <span class="stat-val" style="color:#a6e3a1">{len(clean)}</span></div>
<div class="stat-row"><span class="stat-label">Errors: </span>
  <span class="stat-val">{len(errors)}</span></div>
"""]

        if flagged:
            html.append('<div class="section">FILES WITH ADS / WARNINGS</div>')
            for r, ads, warns in flagged:
                ad_tag = f'<span class="tag-ad">{ads} ads</span>' if ads else ''
                wn_tag = f'<span class="tag-warn">{warns} warns</span>' if warns else ''
                html.append(f'<div class="file-header">'
                            f'&nbsp;{ad_tag} {wn_tag}&nbsp;&nbsp;'
                            f'<span style="color:#cdd6f4">{esc(r.path.parent.name)}/</span>'
                            f'<span style="color:#fff;font-weight:bold">{esc(r.path.name)}</span>'
                            f'</div>')
                if r.subtitle:
                    for b in r.subtitle.blocks:
                        if b.regex_matches >= t:
                            reasons_html = " ".join(
                                f'<span class="reason-tag">{esc(h)}</span>'
                                for h in dict.fromkeys(b.hints)
                            )
                            html.append(
                                f'<div class="block-ad">'
                                f'<span class="tag-ad">AD</span>&nbsp;'
                                f'<span class="block-ts">[{esc(b.start)}]</span>&nbsp;'
                                f'<span class="block-text">{esc(b.text[:80])}</span>'
                                f'<div class="block-meta">{reasons_html}</div>'
                                f'</div>'
                            )
                        elif b.regex_matches == t - 1 and t > 1:
                            reasons_html = " ".join(
                                f'<span class="reason-tag">{esc(h)}</span>'
                                for h in dict.fromkeys(b.hints)
                            )
                            html.append(
                                f'<div class="block-warn">'
                                f'<span class="tag-warn">WARN</span>&nbsp;'
                                f'<span class="block-ts">[{esc(b.start)}]</span>&nbsp;'
                                f'<span class="block-text-warn">{esc(b.text[:80])}</span>'
                                f'<div class="block-meta">{reasons_html}</div>'
                                f'</div>'
                            )

        if errors:
            html.append('<div class="section">ERRORS</div>')
            for r in errors:
                html.append(f'<div style="color:#888;margin:2px 0">'
                            f'✕ {esc(r.path.name)} — {esc(r.error)}</div>')

        if clean:
            html.append('<div class="section">CLEAN FILES</div>')
            for r in clean:
                html.append(f'<div style="color:#6c7a96;margin:1px 0">'
                            f'<span class="tag-clean">✓</span>&nbsp;'
                            f'{esc(r.path.parent.name)}/{esc(r.path.name)}</div>')

        return "\n".join(html)

    # ── Detail on row click ───────────────────────────────────────────────

    def _on_row_selected(self, row: int):
        if row < 0 or not self._batch_result:
            self._btn_open_in_review.setEnabled(False)
            return
        fr = self._batch_result.results[row]
        self._btn_open_in_review.setEnabled(fr.ok)

        if not fr.subtitle:
            msg = f"Error: {fr.error}" if fr.error else "No data."
            self._report_text.setHtml(f"<p style='color:#888;font-family:Consolas'>{msg}</p>")
            return

        def esc(s):
            return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

        t = self._threshold
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
  .warn-text {{ color:#ffc990; font-weight:bold; font-size:13px; }}
  .rm        {{ color:#565f89; font-size:11px; }}
  .reason    {{ color:#565f89; font-size:11px; margin-right:8px; }}
  .clean-msg {{ color:#9ece6a; margin-top:12px; font-size:13px; }}
</style>
<div class="file-path">{esc(fr.path.parent)}/</div>
<div class="file-name">{esc(fr.path.name)}</div>
<div class="summary">
  Threshold: rm≥{t} &nbsp;|&nbsp;
  {len(fr.subtitle.blocks)} blocks total &nbsp;|&nbsp;
  <span style="color:#f38ba8">{ads} ads</span> &nbsp;|&nbsp;
  <span style="color:#fab387">{warns} warnings</span>
</div>"""]

        found_any = False
        BRD = '#2a3347'
        FG2 = '#6c7a96'
        for b in fr.subtitle.blocks:
            is_kept = getattr(b, '_kept', False)
            if b.regex_matches >= t or (b.regex_matches == t - 1 and t > 1):
                found_any = True
                is_ad = b.regex_matches >= t
                reasons_html = " ".join(
                    f'<span class="reason">{esc(h)}</span>'
                    for h in dict.fromkeys(b.hints)
                )
                if is_kept:
                    div_cls  = "block-kept"
                    tag      = '<span class="tag-kept">KEPT</span>'
                    txt_cls  = "kept-text"
                    btn_lbl  = "Kept — click to undo"
                    btn_col  = FG2
                elif is_ad:
                    div_cls  = "block-ad"
                    tag      = '<span class="tag-ad">AD</span>'
                    txt_cls  = "ad-text"
                    btn_lbl  = "Keep — not an ad"
                    btn_col  = FG2
                else:
                    div_cls  = "block-warn"
                    tag      = '<span class="tag-warn">WARN</span>'
                    txt_cls  = "warn-text"
                    btn_lbl  = "Keep — not an ad"
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
            html.append('<div class="clean-msg">No issues found at this threshold.</div>')

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
                            row = self._result_list.currentRow()
                            if row >= 0:
                                self._on_row_selected(row)
                            return

    def _show_full_report(self):
        if self._batch_result:
            self._result_list.clearSelection()
            self._report_text.setHtml(self._build_report())
            self._btn_open_in_review.setEnabled(False)

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
