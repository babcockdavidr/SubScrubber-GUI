"""
SubScrubber GUI — PyQt6
Dark industrial theme. Diff review workflow: flag → approve/deny per block.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import List, Optional

# Allow running standalone
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QMimeData, QUrl,
                           QSize, QTimer)
from PyQt6.QtGui import (QColor, QFont, QIcon, QPalette, QDragEnterEvent,
                          QDropEvent, QKeySequence, QShortcut, QTextCharFormat,
                          QSyntaxHighlighter, QTextDocument)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QSplitter,
    QTextEdit, QFrame, QScrollArea, QFileDialog, QMessageBox,
    QProgressBar, QStatusBar, QToolBar, QCheckBox, QTabWidget,
    QSizePolicy, QAbstractItemView, QGroupBox,
)

from core import load_subtitle, write_subtitle, analyze, clean, SUPPORTED_EXTENSIONS
from core import VIDEO_EXTENSIONS
from core.subtitle import ParsedSubtitle, SubBlock
from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW


STYLESHEET = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {FG};
    font-family: 'Consolas', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 13px;
}}

/* ── Toolbar ── */
QToolBar {{
    background: {BG2};
    border-bottom: 1px solid {BORDER};
    spacing: 6px;
    padding: 4px 8px;
}}
QToolBar QLabel {{
    font-size: 16px;
    font-weight: bold;
    color: {ACCENT};
    letter-spacing: 2px;
    padding-right: 16px;
}}

/* ── Buttons ── */
QPushButton {{
    background: {BG3};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 12px;
}}
QPushButton:hover  {{ background: {ACCENT}22; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT}44; }}
QPushButton:disabled {{ color: {FG2}; border-color: {BORDER}; }}

QPushButton#btn_remove {{
    color: {RED};
    border-color: {RED}55;
}}
QPushButton#btn_remove:hover {{ background: {RED}22; border-color: {RED}; }}

QPushButton#btn_keep {{
    color: {GREEN};
    border-color: {GREEN}55;
}}
QPushButton#btn_keep:hover {{ background: {GREEN}22; border-color: {GREEN}; }}

QPushButton#btn_clean_all {{
    background: {ACCENT}22;
    color: {ACCENT};
    border-color: {ACCENT};
    font-weight: bold;
    padding: 7px 20px;
}}
QPushButton#btn_clean_all:hover {{ background: {ACCENT}44; }}

/* ── Lists ── */
QListWidget {{
    background: {BG2};
    border: 1px solid {BORDER};
    border-radius: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {BORDER};
}}
QListWidget::item:selected {{
    background: {ACCENT}33;
    color: {FG};
}}
QListWidget::item:hover {{
    background: {BG3};
}}

/* ── Text areas ── */
QTextEdit {{
    background: {BG2};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 8px;
    line-height: 1.5;
    selection-background-color: {ACCENT}55;
}}

/* ── Labels ── */
QLabel#section_label {{
    color: {FG2};
    font-size: 10px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    padding: 4px 0 2px 0;
}}
QLabel#file_status {{
    color: {FG2};
    font-size: 12px;
    padding: 2px 4px;
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: {BORDER};
    width: 2px;
    height: 2px;
}}

/* ── Progress ── */
QProgressBar {{
    background: {BG3};
    border: 1px solid {BORDER};
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 3px;
}}

/* ── Status bar ── */
QStatusBar {{
    background: {BG2};
    border-top: 1px solid {BORDER};
    color: {FG2};
    font-size: 11px;
    padding: 2px 8px;
}}

/* ── Checkbox ── */
QCheckBox {{
    color: {FG2};
    font-size: 12px;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {BG3};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* ── Tabs ── */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 4px;
}}
QTabBar::tab {{
    background: {BG2};
    color: {FG2};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 5px 14px;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background: {BG3};
    color: {FG};
    border-bottom: 2px solid {ACCENT};
}}

/* ── Group box ── */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 8px;
    font-size: 11px;
    color: {FG2};
    padding-top: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}

/* ── Scrollbar ── */
QScrollBar:vertical {{
    background: {BG};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {FG2}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/* ── Drop zone ── */
QFrame#drop_zone {{
    border: 2px dashed {BORDER};
    border-radius: 8px;
    background: {BG2};
}}
QFrame#drop_zone:hover {{
    border-color: {ACCENT};
    background: {ACCENT}0a;
}}
"""


# ---------------------------------------------------------------------------
# Worker thread for async analysis
# ---------------------------------------------------------------------------
class AnalyzeWorker(QThread):
    result_ready = pyqtSignal(object)   # ParsedSubtitle
    error        = pyqtSignal(str)

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            subtitle = load_subtitle(self.path)
            analyze(subtitle)
            self.result_ready.emit(subtitle)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Block row widget (used inside the review list)
# ---------------------------------------------------------------------------
class BlockRow(QListWidgetItem):
    AD_COLOR      = QColor(RED)
    WARN_COLOR    = QColor(ORANGE)
    NORMAL_COLOR  = QColor(FG2)

    def __init__(self, block: SubBlock):
        super().__init__()
        self.block = block
        self._update_display()

    def _update_display(self):
        b = self.block
        if b.is_ad:
            tag = "✕ AD"
            self.setForeground(self.AD_COLOR)
        elif b.is_warning:
            tag = "⚠ WARN"
            self.setForeground(self.WARN_COLOR)
        else:
            tag = "  "
            self.setForeground(self.NORMAL_COLOR)

        score_str = f"{b.ad_score:.0%}" if b.ad_score > 0 else ""
        preview = b.text[:60].replace("\n", " ")
        self.setText(f"{tag:8} {b.start:14}  {score_str:5}  {preview}")

    def toggle_ad(self):
        self.block.is_ad = not self.block.is_ad
        if self.block.is_ad:
            self.block.is_warning = False
        self._update_display()


# ---------------------------------------------------------------------------
# Drop zone widget
# ---------------------------------------------------------------------------
class DropZone(QFrame):
    files_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("⬇")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: 28px; color: {FG2};")

        msg = QLabel("Drop subtitle files here\n.srt  .ass  .ssa  .vtt")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {FG2}; font-size: 12px; line-height: 1.8;")

        browse = QPushButton("Browse…")
        browse.setMaximumWidth(100)
        browse.clicked.connect(self._browse)

        layout.addWidget(icon)
        layout.addWidget(msg)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)

    def _browse(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open Subtitle Files", "",
            "Subtitle Files (*.srt *.ass *.ssa *.vtt);;All Files (*)"
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
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                paths.append(p)
        if paths:
            self.files_dropped.emit(paths)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, preload: List[Path] = None):
        super().__init__()
        self.setWindowTitle("SubScrubber")
        self.resize(1200, 750)
        self.setMinimumSize(900, 600)

        self._subtitle: Optional[ParsedSubtitle] = None
        self._worker: Optional[AnalyzeWorker] = None
        self._file_queue: List[Path] = []

        self._build_ui()
        self._connect_signals()

        if preload:
            self._enqueue_files(preload)

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        title = QLabel("SUBSCRUBBER")
        toolbar.addWidget(title)

        toolbar.addSeparator()
        self._chk_dry_run = QCheckBox("Dry run")
        self._chk_warnings = QCheckBox("Remove warnings")
        toolbar.addWidget(self._chk_dry_run)
        toolbar.addWidget(self._chk_warnings)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self._btn_open_folder = QPushButton("Open Folder…")
        toolbar.addWidget(self._btn_open_folder)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready — drop subtitle files to begin")
        self._version_label = QLabel("Beta 2")
        self._version_label.setStyleSheet(f"color: {FG2}; font-size: 11px; padding-right: 6px;")
        self._status.addPermanentWidget(self._version_label)

        # Central layout
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Left panel: file queue ──────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(240)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        lbl_queue = QLabel("FILE QUEUE")
        lbl_queue.setObjectName("section_label")

        self._file_list = QListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        drop = DropZone()
        drop.files_dropped.connect(self._enqueue_files)

        left_layout.addWidget(lbl_queue)
        left_layout.addWidget(self._file_list, stretch=1)
        left_layout.addWidget(drop)

        # ── Right panel: tabs ───────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # File info bar
        info_row = QHBoxLayout()
        self._lbl_file = QLabel("No file loaded")
        self._lbl_file.setObjectName("file_status")
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumWidth(200)
        self._progress.setMaximumHeight(6)
        info_row.addWidget(self._lbl_file, stretch=1)
        info_row.addWidget(self._progress)

        # Tabs
        self._tabs = QTabWidget()

        # Tab 1: Review
        review_tab = QWidget()
        review_layout = QVBoxLayout(review_tab)
        review_layout.setContentsMargins(6, 6, 6, 6)
        review_layout.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Block list (left of splitter)
        block_panel = QWidget()
        block_layout = QVBoxLayout(block_panel)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(4)

        lbl_blocks = QLabel("SUBTITLE BLOCKS")
        lbl_blocks.setObjectName("section_label")
        self._block_list = QListWidget()
        self._block_list.setFont(QFont("Consolas", 11))

        block_layout.addWidget(lbl_blocks)
        block_layout.addWidget(self._block_list)

        # Detail panel (right of splitter)
        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)

        lbl_detail = QLabel("BLOCK DETAIL")
        lbl_detail.setObjectName("section_label")

        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setFont(QFont("Consolas", 12))

        # Match reasons
        self._reasons_text = QTextEdit()
        self._reasons_text.setReadOnly(True)
        self._reasons_text.setMaximumHeight(80)
        self._reasons_text.setFont(QFont("Consolas", 11))
        self._reasons_text.setPlaceholderText("Matched patterns will appear here…")

        # Per-block action buttons
        btn_row = QHBoxLayout()
        self._btn_mark_ad = QPushButton("✕  Mark as Ad")
        self._btn_mark_ad.setObjectName("btn_remove")
        self._btn_keep = QPushButton("✓  Keep Block")
        self._btn_keep.setObjectName("btn_keep")
        btn_row.addWidget(self._btn_mark_ad)
        btn_row.addWidget(self._btn_keep)
        btn_row.addStretch()

        detail_layout.addWidget(lbl_detail)
        detail_layout.addWidget(self._detail_text, stretch=1)
        detail_layout.addWidget(self._reasons_text)
        detail_layout.addLayout(btn_row)

        splitter.addWidget(block_panel)
        splitter.addWidget(detail_panel)
        splitter.setSizes([420, 380])

        review_layout.addWidget(splitter)

        # Tab 2: Report
        report_tab = QWidget()
        report_layout = QVBoxLayout(report_tab)
        report_layout.setContentsMargins(6, 6, 6, 6)
        self._report_text = QTextEdit()
        self._report_text.setReadOnly(True)
        self._report_text.setFont(QFont("Consolas", 12))
        report_layout.addWidget(self._report_text)

        self._tabs.addTab(review_tab, "Review")
        self._tabs.addTab(report_tab, "Report")

        # Tab 3: Batch mode
        from .batch_panel import BatchPanel
        self._batch_panel = BatchPanel()
        self._tabs.addTab(self._batch_panel, "Batch")

        # Tab 4: Video / embedded subtitle scan
        from .video_panel import VideoScanPanel
        self._video_panel = VideoScanPanel()
        self._tabs.addTab(self._video_panel, "Video Scan")

        # Bottom action bar
        action_bar = QHBoxLayout()
        self._btn_prev = QPushButton("← Prev File")
        self._btn_next = QPushButton("Next File →")
        self._lbl_stats = QLabel("")
        self._lbl_stats.setObjectName("file_status")
        self._btn_clean_all = QPushButton("⚡  Clean && Save")
        self._btn_clean_all.setObjectName("btn_clean_all")
        self._btn_clean_all.setEnabled(False)

        action_bar.addWidget(self._btn_prev)
        action_bar.addWidget(self._btn_next)
        action_bar.addStretch()
        action_bar.addWidget(self._lbl_stats)
        action_bar.addWidget(self._btn_clean_all)

        right_layout.addLayout(info_row)
        right_layout.addWidget(self._tabs, stretch=1)
        right_layout.addLayout(action_bar)

        root.addWidget(left)
        root.addWidget(right, stretch=1)

    # ── Connect signals ───────────────────────────────────────────────────

    def _connect_signals(self):
        self._file_list.currentRowChanged.connect(self._on_file_selected)
        self._block_list.currentRowChanged.connect(self._on_block_selected)
        self._btn_mark_ad.clicked.connect(self._mark_current_as_ad)
        self._btn_keep.clicked.connect(self._keep_current)
        self._btn_clean_all.clicked.connect(self._save_current)
        self._btn_open_folder.clicked.connect(self._open_folder)
        self._btn_prev.clicked.connect(self._prev_file)
        self._btn_next.clicked.connect(self._next_file)

        # Cross-panel wiring
        self._batch_panel.open_file_requested.connect(self._open_file_in_review)

        # Keyboard shortcuts
        QShortcut(QKeySequence("Delete"), self, self._mark_current_as_ad)
        QShortcut(QKeySequence("Space"),  self, self._keep_current)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_current)

    # ── File queue management ─────────────────────────────────────────────

    def _enqueue_files(self, paths: List[Path]):
        for p in paths:
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            # Don't add duplicates
            existing = [self._file_list.item(i).data(Qt.ItemDataRole.UserRole)
                        for i in range(self._file_list.count())]
            if p in existing:
                continue
            item = QListWidgetItem(p.name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setForeground(QColor(FG2))
            self._file_list.addItem(item)

        if self._file_list.count() == 1:
            self._file_list.setCurrentRow(0)

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Subtitle Folder")
        if not folder:
            return
        paths = [p for p in Path(folder).rglob("*")
                 if p.suffix.lower() in SUPPORTED_EXTENSIONS]
        if not paths:
            self._status.showMessage("No subtitle files found in that folder.")
            return
        self._enqueue_files(sorted(paths))

    def _on_file_selected(self, row: int):
        if row < 0:
            return
        item = self._file_list.item(row)
        if item is None:
            return
        path: Path = item.data(Qt.ItemDataRole.UserRole)
        self._load_file(path)

    def _prev_file(self):
        row = self._file_list.currentRow()
        if row > 0:
            self._file_list.setCurrentRow(row - 1)

    def _next_file(self):
        row = self._file_list.currentRow()
        if row < self._file_list.count() - 1:
            self._file_list.setCurrentRow(row + 1)

    # ── File loading ──────────────────────────────────────────────────────

    def _load_file(self, path: Path):
        self._subtitle = None
        self._block_list.clear()
        self._detail_text.clear()
        self._reasons_text.clear()
        self._btn_clean_all.setEnabled(False)
        self._lbl_file.setText(f"Loading {path.name}…")
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # indeterminate

        if self._worker and self._worker.isRunning():
            self._worker.quit()

        self._worker = AnalyzeWorker(path)
        self._worker.result_ready.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

    def _on_analysis_done(self, subtitle: ParsedSubtitle):
        self._subtitle = subtitle
        self._progress.setVisible(False)

        fmt = subtitle.fmt.value.upper()
        lang = subtitle.language
        n = len(subtitle.blocks)
        ads = sum(1 for b in subtitle.blocks if b.is_ad)
        warns = sum(1 for b in subtitle.blocks if b.is_warning)

        self._lbl_file.setText(
            f"{subtitle.path.name}  ·  {fmt}  ·  lang:{lang}  ·  {n} blocks"
        )
        self._lbl_stats.setText(
            f"<font color='{RED}'>{ads} ads</font>  "
            f"<font color='{ORANGE}'>{warns} warnings</font>"
        )

        self._populate_block_list(subtitle)
        self._btn_clean_all.setEnabled(True)
        self._status.showMessage(
            f"Analysis complete — {ads} ad block(s) found, {warns} warning(s)"
        )

        # Mark file in queue
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == subtitle.path:
                if ads > 0:
                    item.setForeground(QColor(RED))
                    item.setText(f"[{ads}✕] {subtitle.path.name}")
                elif warns > 0:
                    item.setForeground(QColor(ORANGE))
                    item.setText(f"[{warns}⚠] {subtitle.path.name}")
                else:
                    item.setForeground(QColor(GREEN))
                    item.setText(f"[✓] {subtitle.path.name}")

        self._update_report()

    def _on_analysis_error(self, msg: str):
        self._progress.setVisible(False)
        self._lbl_file.setText("Error loading file")
        self._status.showMessage(f"Error: {msg}")

    # ── Block list ────────────────────────────────────────────────────────

    def _populate_block_list(self, subtitle: ParsedSubtitle):
        self._block_list.clear()
        for block in subtitle.blocks:
            row = BlockRow(block)
            self._block_list.addItem(row)

    def _on_block_selected(self, row: int):
        if row < 0 or self._subtitle is None:
            return
        item = self._block_list.item(row)
        if item is None or not isinstance(item, BlockRow):
            return
        block = item.block

        # Detail pane
        self._detail_text.clear()
        cursor = self._detail_text.textCursor()

        # Timestamp header
        fmt_h = QTextCharFormat()
        fmt_h.setForeground(QColor(ACCENT))
        cursor.setCharFormat(fmt_h)
        cursor.insertText(f"[{block.start}  →  {block.end}]\n\n")

        # Text content
        fmt_text = QTextCharFormat()
        if block.is_ad:
            fmt_text.setForeground(QColor(RED))
        elif block.is_warning:
            fmt_text.setForeground(QColor(ORANGE))
        else:
            fmt_text.setForeground(QColor(FG))
        cursor.setCharFormat(fmt_text)
        cursor.insertText(block.display_text)

        self._detail_text.setTextCursor(cursor)

        # Reasons pane
        if block.matched_patterns:
            score_pct = f"{block.ad_score:.0%}"
            reason_str = "  ·  ".join(block.matched_patterns)
            self._reasons_text.setText(f"Score: {score_pct}   Patterns: {reason_str}")
        else:
            self._reasons_text.setText("No ad patterns matched.")

    # ── Block actions ─────────────────────────────────────────────────────

    def _mark_current_as_ad(self):
        row = self._block_list.currentRow()
        if row < 0:
            return
        item = self._block_list.item(row)
        if isinstance(item, BlockRow):
            item.block.regex_matches = 3   # forces is_ad = True (computed property)
            item._update_display()
            self._refresh_stats()
            self._block_list.setCurrentRow(min(row + 1, self._block_list.count() - 1))

    def _keep_current(self):
        row = self._block_list.currentRow()
        if row < 0:
            return
        item = self._block_list.item(row)
        if isinstance(item, BlockRow):
            item.block.regex_matches = -1  # forces is_ad=False, is_warning=False
            item.block.ad_score = 0.0
            item._update_display()
            self._refresh_stats()
            self._block_list.setCurrentRow(min(row + 1, self._block_list.count() - 1))

    def _refresh_stats(self):
        if not self._subtitle:
            return
        ads = sum(1 for b in self._subtitle.blocks if b.is_ad)
        warns = sum(1 for b in self._subtitle.blocks if b.is_warning)
        self._lbl_stats.setText(
            f"<font color='{RED}'>{ads} ads</font>  "
            f"<font color='{ORANGE}'>{warns} warnings</font>"
        )

    # ── Save ──────────────────────────────────────────────────────────────

    def _save_current(self):
        if not self._subtitle:
            return

        dry = self._chk_dry_run.isChecked()
        inc_warnings = self._chk_warnings.isChecked()

        # Apply current block states to the subtitle
        if inc_warnings:
            remove_set = {id(b) for b in self._subtitle.blocks
                          if b.is_ad or b.is_warning}
        else:
            remove_set = {id(b) for b in self._subtitle.blocks if b.is_ad}

        removed = len(remove_set)

        if removed == 0:
            self._status.showMessage("No blocks flagged for removal.")
            return

        if dry:
            self._status.showMessage(
                f"Dry run: would remove {removed} block(s) — no file written."
            )
            return

        # Confirm
        answer = QMessageBox.question(
            self,
            "Confirm",
            f"Remove {removed} block(s) and save?\n\n{self._subtitle.path.name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._subtitle.blocks = [b for b in self._subtitle.blocks
                                  if id(b) not in remove_set]
        for i, b in enumerate(self._subtitle.blocks, 1):
            b.current_index = i

        try:
            write_subtitle(self._subtitle)
        except Exception as e:
            QMessageBox.critical(self, "Write Error", str(e))
            return

        self._status.showMessage(
            f"Saved — removed {removed} block(s) from {self._subtitle.path.name}"
        )
        self._populate_block_list(self._subtitle)
        self._refresh_stats()
        self._update_report()

        # Mark queue item green
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self._subtitle.path:
                item.setForeground(QColor(GREEN))
                item.setText(f"[✓] {self._subtitle.path.name}")

    # ── Cross-panel navigation ──────────────────────────────────────────────

    def _open_file_in_review(self, path: Path):
        """Called by batch panel — load a file into the review tab and switch to it."""
        # Add to queue if not already present
        self._enqueue_files([path])
        # Select it in the file list
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                self._file_list.setCurrentRow(i)
                break
        # Switch to Review tab (index 0)
        self._tabs.setCurrentIndex(0)

    # ── Report tab ────────────────────────────────────────────────────────

    def _update_report(self):
        if not self._subtitle:
            return
        from core.cleaner import generate_report
        self._report_text.setText(generate_report(self._subtitle))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def launch_gui(preload: List[Path] = None):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    win = MainWindow(preload=preload or [])
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_gui()
