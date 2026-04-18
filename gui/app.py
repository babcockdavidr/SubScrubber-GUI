"""
SubForge GUI — PyQt6
Dark industrial theme. Diff review workflow: flag → approve/deny per block.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import List, Optional

# Allow running standalone
# sys.path managed by subforge.py entry point — do not insert __file__-relative paths here

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
    QSizePolicy, QAbstractItemView, QGroupBox, QSlider,
)

from core import load_subtitle, write_subtitle, analyze, clean, SUPPORTED_EXTENSIONS
from core import CleaningOptions, apply_cleaning_options
from .settings_dialog import SettingsDialog, load_cleaning_options, load_default_sensitivity, load_session, save_session
from .setup_wizard    import SetupWizard, is_setup_complete
from .strings import STRINGS
from core import block_will_be_removed
from core import VIDEO_EXTENSIONS
from core.subtitle import ParsedSubtitle, SubBlock
from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW


STYLESHEET = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {FG};
    font-family: 'Consolas', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 10pt;
}}

/* ── Toolbar ── */
QToolBar {{
    background: {BG2};
    border-bottom: 1px solid {BORDER};
    spacing: 6px;
    padding: 4px 8px;
}}
QToolBar QLabel {{
    font-size: 12pt;
    font-weight: bold;
    color: {ACCENT};
    letter-spacing: 2px;
}}

/* ── Buttons ── */
QPushButton {{
    background: {BG3};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 10pt;
}}
QPushButton:hover  {{ background: rgba(78, 158, 255, 0.1); border-color: {ACCENT}; }}
QPushButton:pressed {{ background: rgba(78, 158, 255, 0.2); }}
QPushButton:disabled {{ color: {FG2}; border-color: {BORDER}; background: {BG3}; }}

QPushButton#btn_remove {{
    color: {RED};
    border-color: {RED};
    background: {BG3};
    padding: 7px 20px;
}}
QPushButton#btn_remove:hover {{ background: rgba(243, 139, 168, 0.15); border-color: {RED}; }}
QPushButton#btn_remove:disabled {{ color: {FG2}; border-color: {BORDER}; background: {BG3}; }}

QPushButton#btn_keep {{
    color: {GREEN};
    border-color: {GREEN};
    background: {BG3};
    padding: 7px 20px;
}}
QPushButton#btn_keep:hover {{ background: rgba(166, 227, 161, 0.15); border-color: {GREEN}; }}

QPushButton#btn_clean_all {{
    background: rgba(78, 158, 255, 0.1);
    color: {ACCENT};
    border-color: {ACCENT};
    font-weight: bold;
    padding: 7px 20px;
}}
QPushButton#btn_clean_all:hover {{ background: rgba(78, 158, 255, 0.25); }}
QPushButton#btn_clean_all:disabled {{ color: {FG2}; border-color: {BORDER}; background: {BG3}; }}

QPushButton#btn_save {{
    color: {RED};
    border-color: {RED};
    background: {BG3};
    font-weight: bold;
    padding: 7px 20px;
}}
QPushButton#btn_save:hover {{ background: rgba(243, 139, 168, 0.15); border-color: {RED}; }}
QPushButton#btn_save:disabled {{ color: {FG2}; border-color: {BORDER}; background: {BG3}; }}

QPushButton#btn_save_green {{
    color: {GREEN};
    border-color: {GREEN};
    background: {BG3};
    font-weight: bold;
    padding: 7px 20px;
}}
QPushButton#btn_save_green:hover {{ background: rgba(166, 227, 161, 0.15); border-color: {GREEN}; }}
QPushButton#btn_save_green:disabled {{ color: {FG2}; border-color: {BORDER}; background: {BG3}; }}

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
    background: {BG3};
}}
QListWidget::item:selected:hover {{
    background: {BG3};
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
    font-size: 8pt;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    padding: 4px 0 2px 0;
}}
QLabel#file_status {{
    color: {FG2};
    font-size: 10pt;
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
    font-size: 9pt;
    padding: 2px 8px;
}}

/* ── Checkbox ── */
QCheckBox {{
    color: {FG2};
    font-size: 10pt;
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
    font-size: 10pt;
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
    font-size: 9pt;
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
    background: {BG2};
}}
QFrame#drop_zone QPushButton {{
    background: transparent;
    border: 1px solid {BORDER};
    color: {FG2};
    padding: 4px 12px;
    border-radius: 4px;
}}
QFrame#drop_zone QPushButton:hover {{
    border-color: {ACCENT};
    color: {FG};
    background: {BG3};
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
# Update check worker
# ---------------------------------------------------------------------------
class UpdateWorker(QThread):
    result_ready = pyqtSignal(str, str)   # tag, release_name
    error        = pyqtSignal(str)

    def run(self):
        from core.updater import fetch_latest_release
        tag, name, err = fetch_latest_release()
        if err:
            self.error.emit(err)
        else:
            self.result_ready.emit(tag, name)


# ---------------------------------------------------------------------------
# Block row widget (used inside the review list)
# ---------------------------------------------------------------------------
class BlockRow(QListWidgetItem):
    AD_COLOR      = QColor(RED)
    WARN_COLOR    = QColor(ORANGE)
    NORMAL_COLOR  = QColor(FG2)

    def __init__(self, block: SubBlock, threshold: int = 3):
        super().__init__()
        self.block = block
        self.threshold = threshold
        self._update_display()

class BlockRow(QListWidgetItem):
    AD_COLOR      = QColor(RED)
    WARN_COLOR    = QColor(ORANGE)
    NORMAL_COLOR  = QColor(FG2)
    OPT_COLOR     = QColor(ACCENT)

    def __init__(self, block: SubBlock, threshold: int = 3):
        super().__init__()
        self.block = block
        self.threshold = threshold
        self._update_display()

    def _update_display(self):
        b = self.block
        t = self.threshold
        is_ad   = b.regex_matches >= t
        is_warn = b.regex_matches == t - 1 and t > 1
        opts = load_cleaning_options()
        will_clean = block_will_be_removed(b.content, opts)
        if is_ad:
            tag = "✕ AD"
            self.setForeground(self.AD_COLOR)
        elif will_clean:
            tag = "✕ OPT"
            self.setForeground(self.OPT_COLOR)
        elif is_warn:
            tag = "⚠ WARN"
            self.setForeground(self.WARN_COLOR)
        else:
            tag = "  "
            self.setForeground(self.NORMAL_COLOR)

        score_str = f"{b.ad_score:.0%}" if b.ad_score > 0 else ""
        preview = b.text[:60].replace("\n", " ")
        self.setText(f"{tag:8} {b.start:14}  {score_str:5}  {preview}")

    def toggle_ad(self):
        self.block.regex_matches = 3 if self.block.regex_matches < 3 else -1
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
        icon.setStyleSheet(f"font-size: 18pt; color: {FG2};")

        msg = QLabel(STRINGS["sf_drop_label"] + "\n" + STRINGS["sf_drop_formats"])
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {FG2}; font-size: 10pt; line-height: 1.8;")

        browse = QPushButton(STRINGS["sf_browse"])
        browse.setMaximumWidth(100)
        browse.setToolTip(STRINGS["tip_sf_browse"])
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
        self.setWindowTitle(STRINGS["app_title"])
        self.resize(1200, 750)
        self.setMinimumSize(900, 600)

        self._subtitle: Optional[ParsedSubtitle] = None
        self._worker: Optional[AnalyzeWorker] = None
        self._file_queue: List[Path] = []

        self._build_ui()
        self._connect_signals()
        self._restore_session()

        if preload:
            self._enqueue_files(preload)

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        title = QLabel(STRINGS["app_toolbar_label"])
        toolbar.addWidget(title)

        tb_spacer = QWidget()
        tb_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(tb_spacer)

        self._btn_settings = QPushButton(STRINGS["app_btn_settings"])
        self._btn_settings.setStyleSheet(
            f"font-size: 9pt; padding: 2px 10px; color: {FG2};"
            f"border: 1px solid {BORDER}; border-radius: 3px; background: transparent;"
        )
        self._btn_settings.setToolTip(STRINGS["tip_btn_settings"])
        toolbar.addWidget(self._btn_settings)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(STRINGS["msg_ready"])
        from core.updater import CURRENT_VERSION
        self._version_label = QLabel(CURRENT_VERSION)
        self._version_label.setStyleSheet(f"color: {FG2}; font-size: 9pt; padding-right: 6px;")
        self._btn_check_updates = QPushButton(STRINGS["app_btn_check_updates"])
        self._btn_check_updates.setStyleSheet(
            f"font-size: 9pt; padding: 1px 8px; color: {FG2};"
            f"border: 1px solid {BORDER}; border-radius: 3px; background: transparent;"
        )
        self._btn_check_updates.setToolTip(STRINGS["tip_btn_check_updates"])
        self._btn_check_updates.clicked.connect(self._check_for_updates)

        # Scan elapsed timer — hidden until a scan is running
        self._scan_elapsed_label = QLabel()
        self._scan_elapsed_label.setStyleSheet(
            f"color: {ACCENT}; font-size: 9pt; padding-right: 10px; font-family: monospace;"
        )
        self._scan_elapsed_label.setVisible(False)
        self._scan_elapsed_secs = 0
        self._scan_qtimer = QTimer(self)
        self._scan_qtimer.setInterval(1000)
        self._scan_qtimer.timeout.connect(self._on_scan_timer_tick)

        self._status.addPermanentWidget(self._scan_elapsed_label)
        self._status.addPermanentWidget(self._btn_check_updates)
        self._status.addPermanentWidget(self._version_label)

        # Central layout
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Right panel: tabs ───────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # File info bar
        info_row = QHBoxLayout()
        self._lbl_file = QLabel(STRINGS["sf_no_file_loaded"])
        self._lbl_file.setObjectName("file_status")
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumWidth(200)
        self._progress.setMaximumHeight(6)
        info_row.addWidget(self._lbl_file, stretch=1)
        info_row.addWidget(self._progress)

        # Tabs
        self._tabs = QTabWidget()

        # Tab 1: Single File (formerly Review + Report merged)
        single_tab = QWidget()
        single_layout = QVBoxLayout(single_tab)
        single_layout.setContentsMargins(6, 6, 6, 6)
        single_layout.setSpacing(6)

        # ── Single File controls row ──────────────────────────────────────
        sf_controls = QHBoxLayout()

        self._chk_dry_run = QCheckBox(STRINGS["sf_chk_dry_run"])
        self._chk_warnings = QCheckBox(STRINGS["sf_chk_remove_warnings"])
        self._btn_open_folder = QPushButton(STRINGS["sf_btn_open_folder"])
        self._btn_open_folder.setToolTip(STRINGS["tip_sf_open_folder"])

        # Sensitivity slider for single file
        sf_thresh_frame = QFrame()
        sf_thresh_frame.setStyleSheet(
            f"background: {BG2}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        sf_thresh_layout = QHBoxLayout(sf_thresh_frame)
        sf_thresh_layout.setContentsMargins(10, 4, 10, 4)

        sf_thresh_lbl = QLabel(STRINGS["sens_label"])
        sf_thresh_lbl.setStyleSheet(f"color: {FG}; font-weight: bold;")
        lbl_agg = QLabel(STRINGS["sens_more_aggressive"])
        lbl_agg.setStyleSheet(f"color: {RED}; font-size: 8pt;")
        lbl_con = QLabel(STRINGS["sens_more_conservative"])
        lbl_con.setStyleSheet(f"color: {GREEN}; font-size: 8pt;")

        self._sf_slider = QSlider(Qt.Orientation.Horizontal)
        self._sf_slider.setMinimum(1)
        self._sf_slider.setMaximum(5)
        self._sf_slider.setValue(load_default_sensitivity())
        self._sf_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._sf_slider.setTickInterval(1)
        self._sf_slider.setFixedWidth(160)

        self._sf_lbl_threshold = QLabel(STRINGS["thresh_3"])
        self._sf_lbl_threshold.setStyleSheet(f"color: {YELLOW}; font-size: 9pt;")

        sf_thresh_layout.addWidget(sf_thresh_lbl)
        sf_thresh_layout.addWidget(lbl_agg)
        sf_thresh_layout.addWidget(self._sf_slider)
        sf_thresh_layout.addWidget(lbl_con)
        sf_thresh_layout.addSpacing(16)
        sf_thresh_layout.addWidget(self._sf_lbl_threshold, stretch=1)

        sf_controls.addWidget(self._chk_dry_run)
        sf_controls.addWidget(self._chk_warnings)
        sf_controls.addWidget(self._btn_open_folder)
        sf_controls.addStretch()

        # ── Main splitter: file queue | block list | detail+report ──────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # File queue (far left inside Single File tab)
        queue_panel = QWidget()
        queue_panel.setFixedWidth(220)
        queue_layout = QVBoxLayout(queue_panel)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(6)

        lbl_queue = QLabel(STRINGS["sf_lbl_file_queue"])
        lbl_queue.setObjectName("section_label")

        self._file_list = QListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Set palette so the persistent selection bar is a neutral color
        # regardless of item foreground (status colors bleed through transparent backgrounds)
        from PyQt6.QtGui import QPalette, QColor as _QColor
        _pal = self._file_list.palette()
        _pal.setColor(QPalette.ColorGroup.Active,   QPalette.ColorRole.Highlight, _QColor("#2a3f5f"))
        _pal.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight, _QColor("#2a3f5f"))
        _pal.setColor(QPalette.ColorGroup.Active,   QPalette.ColorRole.HighlightedText, _QColor("#ffffff"))
        _pal.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.HighlightedText, _QColor("#ffffff"))
        self._file_list.setPalette(_pal)

        drop = DropZone()
        drop.files_dropped.connect(self._enqueue_files)

        queue_layout.addWidget(lbl_queue)
        queue_layout.addWidget(self._file_list, stretch=1)
        queue_layout.addWidget(drop)

        # Block list (middle)
        block_panel = QWidget()
        block_layout = QVBoxLayout(block_panel)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(4)

        lbl_blocks = QLabel(STRINGS["sf_lbl_subtitle_blocks"])
        lbl_blocks.setObjectName("section_label")
        self._block_list = QListWidget()
        self._block_list.setFont(QFont("Consolas", 11))

        block_layout.addWidget(lbl_blocks)
        block_layout.addWidget(self._block_list)

        # Right side: detail + report stacked in a vertical splitter
        right_split = QSplitter(Qt.Orientation.Vertical)

        # Block detail panel (top right)
        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)

        lbl_detail = QLabel(STRINGS["sf_lbl_block_detail"])
        lbl_detail.setObjectName("section_label")

        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setFont(QFont("Consolas", 12))

        self._reasons_text = QTextEdit()
        self._reasons_text.setReadOnly(True)
        self._reasons_text.setMaximumHeight(80)
        self._reasons_text.setFont(QFont("Consolas", 11))
        self._reasons_text.setPlaceholderText(STRINGS["sf_patterns_placeholder"])

        btn_row = QHBoxLayout()
        self._btn_mark_ad = QPushButton(STRINGS["sf_btn_mark_ad"])
        self._btn_mark_ad.setObjectName("btn_remove")
        self._btn_mark_ad.setToolTip(STRINGS["tip_sf_mark_ad"])
        self._btn_keep = QPushButton(STRINGS["sf_btn_keep"])
        self._btn_keep.setObjectName("btn_keep")
        self._btn_keep.setToolTip(STRINGS["tip_sf_keep"])
        self._btn_always_ad = QPushButton(STRINGS["sf_btn_always_ad"])
        self._btn_always_ad.setObjectName("btn_remove")
        self._btn_always_ad.setToolTip(
            STRINGS["sf_btn_always_ad_tip"]
        )
        self._btn_always_ad.setEnabled(False)
        btn_row.addWidget(self._btn_mark_ad)
        btn_row.addWidget(self._btn_keep)
        btn_row.addWidget(self._btn_always_ad)
        btn_row.addStretch()

        detail_layout.addWidget(lbl_detail)
        detail_layout.addWidget(self._detail_text, stretch=1)
        detail_layout.addWidget(self._reasons_text)
        detail_layout.addLayout(btn_row)

        # Report panel (bottom right)
        report_panel = QWidget()
        report_layout = QVBoxLayout(report_panel)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.setSpacing(4)

        lbl_report = QLabel(STRINGS["sf_lbl_file_report"])
        lbl_report.setObjectName("section_label")
        self._report_text = QTextEdit()
        self._report_text.setReadOnly(True)
        self._report_text.setFont(QFont("Consolas", 12))

        report_layout.addWidget(lbl_report)
        report_layout.addWidget(self._report_text)

        right_split.addWidget(detail_panel)
        right_split.addWidget(report_panel)
        right_split.setSizes([350, 200])

        splitter.addWidget(queue_panel)
        splitter.addWidget(block_panel)
        splitter.addWidget(right_split)
        splitter.setSizes([220, 280, 680])

        # Action bar (Prev/Next/Clean & Save) — lives inside Single File tab
        action_bar = QHBoxLayout()
        self._btn_prev = QPushButton(STRINGS["sf_btn_prev"])
        self._btn_prev.setToolTip(STRINGS["tip_sf_prev"])
        self._btn_next = QPushButton(STRINGS["sf_btn_next"])
        self._btn_next.setToolTip(STRINGS["tip_sf_next"])
        self._lbl_stats = QLabel("")
        self._lbl_stats.setObjectName("file_status")
        self._btn_clean_all = QPushButton(STRINGS["sf_btn_clean_save"])
        self._btn_clean_all.setObjectName("btn_save_green")
        self._btn_clean_all.setToolTip(STRINGS["tip_sf_clean_save"])
        self._btn_clean_all.setEnabled(False)
        action_bar.addWidget(self._btn_prev)
        action_bar.addWidget(self._btn_next)
        action_bar.addStretch()
        action_bar.addWidget(self._lbl_stats)
        action_bar.addWidget(self._btn_clean_all)

        single_layout.addLayout(info_row)
        single_layout.addLayout(sf_controls)
        single_layout.addWidget(sf_thresh_frame)
        single_layout.addWidget(splitter, stretch=1)
        single_layout.addLayout(action_bar)

        self._tabs.addTab(single_tab, STRINGS["tab_single_file"])

        # Tab 3: Batch mode
        from .batch_panel import BatchPanel
        self._batch_panel = BatchPanel()
        self._tabs.addTab(self._batch_panel, STRINGS["tab_batch"])

        # Tab 4: Embedded Subs (formerly Video Scan)
        from .video_panel import VideoScanPanel
        self._video_panel = VideoScanPanel()
        self._tabs.addTab(self._video_panel, STRINGS["tab_video_scan"])

        # Tab 5: Image Subs (OCR pipeline for PGS/VOBSUB tracks)
        from .image_subs_panel import ImageSubsPanel
        self._image_subs_panel = ImageSubsPanel()
        self._tabs.addTab(self._image_subs_panel, STRINGS["tab_image_subs"])

        # Tab 6: Transcribe (Whisper audio transcription)
        from .transcribe_panel import TranscribePanel
        self._transcribe_panel = TranscribePanel()
        self._tabs.addTab(self._transcribe_panel, STRINGS["tab_transcribe"])

        # Tab 7: Regex profile editor
        from .regex_editor import RegexEditorPanel
        self._regex_editor = RegexEditorPanel()
        self._tabs.addTab(self._regex_editor, STRINGS["tab_regex_editor"])



        right_layout.addWidget(self._tabs, stretch=1)

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
        self._video_panel.open_in_image_subs.connect(self._open_in_image_subs)
        self._video_panel.open_in_transcribe.connect(self._open_in_transcribe)
        self._regex_editor.pattern_saved.connect(self._on_pattern_saved)
        self._btn_always_ad.clicked.connect(self._always_mark_as_ad)
        self._btn_settings.clicked.connect(self._open_settings)
        self._sf_slider.valueChanged.connect(self._on_sf_threshold_changed)

        # Status bar unification — forward each panel's status to the app bar
        self._batch_panel.status_updated.connect(self._on_panel_status)
        self._video_panel.status_updated.connect(self._on_panel_status)
        self._image_subs_panel.status_updated.connect(self._on_panel_status)
        self._transcribe_panel.status_updated.connect(self._on_panel_status)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Scan elapsed timer wiring
        self._batch_panel.scan_started.connect(self._on_scan_started)
        self._batch_panel.scan_finished.connect(self._on_scan_stopped)
        self._video_panel.scan_started.connect(self._on_scan_started)
        self._video_panel.scan_finished.connect(self._on_scan_stopped)
        # Keyboard shortcuts
        QShortcut(QKeySequence("Delete"), self, self._mark_current_as_ad)
        QShortcut(QKeySequence("Space"),  self, self._keep_current)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_current)

    # ── Status bar unification ────────────────────────────────────────────

    def _on_panel_status(self, msg: str):
        """Forward a panel's status message to the app-level bar, but only
        when that panel's tab is currently active. Messages from background
        tabs are silently ignored — the bar stays in sync with what the user
        is looking at. When the user switches tabs, _on_tab_changed picks up
        the panel's last known status instead."""
        # Identify which panel fired the signal
        sender = self.sender()
        active_widget = self._tabs.currentWidget()
        if sender is active_widget:
            self._status.showMessage(msg)

    def _on_tab_changed(self, index: int):
        """Sync the app-level status bar whenever the user switches tabs."""
        widget = self._tabs.widget(index)
        # Single File tab (index 0) manages the status bar directly via
        # self._status.showMessage(); nothing to do when switching to it.
        # For the four panels that own internal status labels, read the last
        # message via get_status() and push it to the app bar.
        if hasattr(widget, 'get_status'):
            self._status.showMessage(widget.get_status())
        elif widget is self._tabs.widget(0):
            # Switching back to Single File — leave the bar as-is; the last
            # Single File message is still showing.
            pass


    # ── Scan elapsed timer ────────────────────────────────────────────────────

    def _on_scan_started(self):
        self._scan_elapsed_secs = 0
        self._scan_elapsed_label.setText("⏱ 0:00")
        self._scan_elapsed_label.setVisible(True)
        self._scan_qtimer.start()

    def _on_scan_stopped(self):
        self._scan_qtimer.stop()
        # Leave the final time visible for 5 seconds so you can read it, then hide.
        QTimer.singleShot(5000, lambda: self._scan_elapsed_label.setVisible(False))

    def _on_scan_timer_tick(self):
        self._scan_elapsed_secs += 1
        s = self._scan_elapsed_secs
        mins, secs = divmod(s, 60)
        hrs, mins  = divmod(mins, 60)
        if hrs:
            text = f"⏱ {hrs}:{mins:02}:{secs:02}"
        else:
            text = f"⏱ {mins}:{secs:02}"
        self._scan_elapsed_label.setText(text)

    # ── Settings ─────────────────────────────────────────────────────────────

    # ------------------------------------------------------------------
    # Session memory
    # ------------------------------------------------------------------

    def _restore_session(self) -> None:
        """Restore window geometry and last-used folders from settings.json."""
        session = load_session()

        geom = session.get("window_geometry", "")
        if geom:
            try:
                from PyQt6.QtCore import QByteArray
                from PyQt6.QtWidgets import QApplication
                self.restoreGeometry(QByteArray.fromBase64(geom.encode("ascii")))
                # Validate the restored geometry fits within the available screen area.
                # If the window is mostly off-screen (e.g. saved on a 4K display, now
                # on 1080p) reset to the default size and centre on the current screen.
                screen = QApplication.primaryScreen().availableGeometry()
                frame  = self.frameGeometry()
                if (frame.width() > screen.width()
                        or frame.height() > screen.height()
                        or frame.right()  < screen.left() + 50
                        or frame.bottom() < screen.top()  + 50
                        or frame.left()   > screen.right()  - 50
                        or frame.top()    > screen.bottom() - 50):
                    self.resize(1200, 750)
                    self.move(screen.center() - self.rect().center())
            except Exception:
                pass  # malformed geometry — just use the default size

        self._batch_panel.set_folder(session.get("last_batch_folder", ""))
        self._video_panel.set_folder(session.get("last_video_folder", ""))

    def closeEvent(self, event) -> None:
        """Persist session state before the window closes."""
        try:
            geom_b64 = self.saveGeometry().toBase64().data().decode("ascii")
            save_session(
                last_batch_folder=self._batch_panel.get_folder(),
                last_video_folder=self._video_panel.get_folder(),
                window_geometry=geom_b64,
            )
        except Exception:
            pass  # never block shutdown due to a settings write error
        super().closeEvent(event)

    def _open_settings(self):
        import traceback
        from core.logger import append_error
        try:
            dlg = SettingsDialog(self)
            if dlg.exec():
                v = load_default_sensitivity()
                self._sf_slider.setValue(v)
                self._batch_panel._slider.setValue(v)
                self._video_panel._slider.setValue(v)
        except Exception:
            err = traceback.format_exc()
            append_error("Settings", err)
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Settings crashed:\n\n{err}")

    # ── Single File sensitivity ──────────────────────────────────────────────

    def _on_sf_threshold_changed(self, value: int):
        labels = {
            1: STRINGS["thresh_1"],
            2: STRINGS["thresh_2"],
            3: STRINGS["thresh_3"],
            4: STRINGS["thresh_4"],
            5: STRINGS["thresh_5"],
        }
        self._sf_lbl_threshold.setText(labels.get(value, str(value)))
        if self._subtitle is not None:
            self._populate_block_list(self._subtitle)
            self._refresh_stats()

    def _sf_threshold(self) -> int:
        return self._sf_slider.value()

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
        t = self._sf_threshold() if hasattr(self, '_sf_slider') else 3
        ads = sum(1 for b in subtitle.blocks if b.regex_matches >= t)
        warns = sum(1 for b in subtitle.blocks
                    if b.regex_matches == t - 1 and t > 1)

        self._lbl_file.setText(
            f"{subtitle.path.name}  ·  {fmt}  ·  lang:{lang}  ·  {n} blocks"
        )
        self._refresh_stats()
        opts_list = load_cleaning_options()
        opts = sum(1 for b in subtitle.blocks
                   if b.regex_matches < t
                   and block_will_be_removed(b.content, opts_list)
                   ) if opts_list.any_enabled() else 0
        self._populate_block_list(subtitle)
        self._btn_clean_all.setEnabled(True)
        status_parts = [f"{ads} ad block(s) found, {warns} warning(s)"]
        if opts:
            status_parts.append(f"{opts} opt(s)")
        self._status.showMessage(
            f"Analysis complete — {', '.join(status_parts)}"
        )

        # Mark file in queue — color only, no stale count badges
        _opts_list = load_cleaning_options()
        _opts = sum(1 for b in subtitle.blocks
                    if b.regex_matches < t
                    and block_will_be_removed(b.content, _opts_list)
                    ) if _opts_list.any_enabled() else 0
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == subtitle.path:
                if ads > 0:
                    item.setForeground(QColor(RED))
                elif warns > 0:
                    item.setForeground(QColor(ORANGE))
                elif _opts > 0:
                    item.setForeground(QColor(ACCENT))
                else:
                    item.setForeground(QColor(GREEN))
                item.setText(subtitle.path.name)

        self._update_report()

    def _on_analysis_error(self, msg: str):
        self._progress.setVisible(False)
        self._lbl_file.setText(STRINGS["msg_error_loading"])
        self._status.showMessage(f"Error: {msg}")

    # ── Block list ────────────────────────────────────────────────────────

    def _populate_block_list(self, subtitle: ParsedSubtitle):
        t = self._sf_threshold() if hasattr(self, '_sf_slider') else 3
        self._block_list.clear()
        for block in subtitle.blocks:
            row = BlockRow(block, threshold=t)
            self._block_list.addItem(row)

    def _on_block_selected(self, row: int):
        if row < 0 or self._subtitle is None:
            self._btn_always_ad.setEnabled(False)
            return
        item = self._block_list.item(row)
        if item is None or not isinstance(item, BlockRow):
            self._btn_always_ad.setEnabled(False)
            return
        self._btn_always_ad.setEnabled(True)
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
        t = self._sf_threshold() if hasattr(self, '_sf_slider') else 3
        if block.regex_matches >= t:
            fmt_text.setForeground(QColor(RED))
        elif block.regex_matches == t - 1 and t > 1:
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
        t = self._sf_threshold() if hasattr(self, '_sf_slider') else 3
        ads   = sum(1 for b in self._subtitle.blocks if b.regex_matches >= t)
        warns = sum(1 for b in self._subtitle.blocks
                    if b.regex_matches == t - 1 and t > 1)
        opts_list = load_cleaning_options()
        opts  = sum(1 for b in self._subtitle.blocks
                    if b.regex_matches < t
                    and block_will_be_removed(b.content, opts_list)
                    ) if opts_list.any_enabled() else 0
        parts = [
            f"<font color='{RED}'>{ads} ads</font>",
            f"<font color='{ORANGE}'>{warns} warnings</font>",
        ]
        if opts:
            parts.append(f"<font color='{ACCENT}'>{opts} opts</font>")
        self._lbl_stats.setText("  ".join(parts))

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
            self._status.showMessage(STRINGS["msg_no_blocks"])
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

        # Apply global cleaning options
        opts = load_cleaning_options()
        if opts.any_enabled():
            _, cleaning_report = apply_cleaning_options(self._subtitle, opts)
            if cleaning_report.any_changes:
                self._append_cleaning_report(cleaning_report)

        try:
            write_subtitle(self._subtitle)
        except Exception as e:
            QMessageBox.critical(self, STRINGS["dlg_write_error"], str(e))
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
                item.setText(self._subtitle.path.name)

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

    def _open_in_image_subs(self, path: Path):
        """Called by video panel — open a video file in the Image Subs tab."""
        self._image_subs_panel.load_video(path)
        # Image Subs is tab index 4 (0=Single File, 1=Batch, 2=Embedded Subs... wait,
        # use tab widget lookup so index never goes stale)
        for i in range(self._tabs.count()):
            if self._tabs.widget(i) is self._image_subs_panel:
                self._tabs.setCurrentIndex(i)
                break

    def _open_in_transcribe(self, path: Path):
        """Called by video panel — open a video file in the Transcribe tab."""
        self._transcribe_panel.load_video(path)
        for i in range(self._tabs.count()):
            if self._tabs.widget(i) is self._transcribe_panel:
                self._tabs.setCurrentIndex(i)
                break

    # ── Always Mark as Ad ────────────────────────────────────────────────────

    def _always_mark_as_ad(self):
        row = self._block_list.currentRow()
        if row < 0 or self._subtitle is None:
            return
        item = self._block_list.item(row)
        if not isinstance(item, BlockRow):
            return
        block = item.block

        from .regex_editor import AddPatternDialog
        dlg = AddPatternDialog(block.text, parent=self)
        dlg.exec()
        if dlg.was_saved:
            # Also mark this block as an ad in the current session
            block.regex_matches = 3
            item._update_display()
            self._refresh_stats()
            self._status.showMessage(
                "Pattern saved and engine reloaded — re-analysing current file…"
            )
            # Re-analyse the current file so the new pattern fires on it too
            self._on_pattern_saved()

    def _on_pattern_saved(self):
        """Called when regex editor saves — re-analyse the currently loaded file."""
        if self._subtitle is not None:
            from core.cleaner import analyze
            for block in self._subtitle.blocks:
                block.regex_matches = 0
                block.hints = []
                block.matched_patterns = []
                block.ad_score = 0.0
            analyze(self._subtitle)
            self._populate_block_list(self._subtitle)
            self._refresh_stats()
            self._update_report()
            self._status.showMessage(STRINGS["msg_engine_reloaded"])

    # ── Update check ─────────────────────────────────────────────────────────

    def _check_for_updates(self):
        from core.updater import CURRENT_VERSION, RELEASES_URL, is_newer
        self._btn_check_updates.setEnabled(False)
        self._btn_check_updates.setText(STRINGS["app_btn_checking"])
        self._status.showMessage(STRINGS["msg_checking_updates"])

        self._update_worker = UpdateWorker()
        self._update_worker.result_ready.connect(self._on_update_result)
        self._update_worker.error.connect(self._on_update_error)
        self._update_worker.start()

    def _on_update_result(self, tag: str, name: str):
        from core.updater import CURRENT_VERSION, RELEASES_URL, is_newer
        self._btn_check_updates.setEnabled(True)
        self._btn_check_updates.setText(STRINGS["app_btn_check_updates"])

        if is_newer(tag, CURRENT_VERSION):
            msg = (
                "A new version of SubForge is available.\n\n"
                f"Current version:  {CURRENT_VERSION}\n"
                f"Latest version:   {tag}  ({name})\n\n"
                "Visit the releases page to download the update."
            )
            answer = QMessageBox.information(
                self,
                STRINGS["dlg_update_available"],
                msg,
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Close,
            )
            if answer == QMessageBox.StandardButton.Open:
                import webbrowser
                webbrowser.open(RELEASES_URL)
            self._status.showMessage(f"Update available: {tag}")
        else:
            QMessageBox.information(
                self,
                STRINGS["dlg_up_to_date_title"],
                f"You are running the latest version of SubForge ({CURRENT_VERSION}).",
            )
            self._status.showMessage(STRINGS["msg_up_to_date"])

    def _on_update_error(self, msg: str):
        from core.updater import RELEASES_URL
        self._btn_check_updates.setEnabled(True)
        self._btn_check_updates.setText("Check for Updates")
        err_msg = (
            f"Could not check for updates.\n\n{msg}\n\n"
            "Check your internet connection or visit:\n"
            f"{RELEASES_URL}"
        )
        QMessageBox.warning(self, STRINGS["dlg_update_failed_title"], err_msg)
        self._status.showMessage(STRINGS["msg_update_failed"])

    def _append_cleaning_report(self, report):
        from core.cleaner_options import CleaningReport
        lines = ["", "── Cleaning Options Applied ──────────────────────────"]
        if report.removals():
            lines.append(f"Removed {len(report.removals())} block(s):")
            for a in report.removals():
                lines.append(f"  [{a.timestamp}]  {a.reason}  —  {a.original}")
        if report.modifications():
            lines.append(f"Modified {len(report.modifications())} block(s):")
            for a in report.modifications():
                lines.append(f"  [{a.timestamp}]  {a.reason}  —  {a.original}")
        if report.duplicates_merged:
            lines.append(f"Merged {report.duplicates_merged} duplicate cue(s).")
        self._report_text.append("\n".join(lines))

    # ── Report tab ────────────────────────────────────────────────────────

    def _update_report(self):
        if not self._subtitle:
            return
        from core.cleaner import generate_report
        opts = load_cleaning_options()
        self._report_text.setText(generate_report(self._subtitle, opts))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def launch_gui(preload: List[Path] = None):
    import traceback
    from core.logger import append_error

    try:
        app = QApplication.instance() or QApplication(sys.argv)
        app.setStyleSheet(STYLESHEET)
        win = MainWindow(preload=preload or [])
        win.show()
        if not is_setup_complete():
            wizard = SetupWizard(parent=win)
            wizard.exec()
        sys.exit(app.exec())
    except Exception:
        append_error("launch", traceback.format_exc())
        raise


if __name__ == "__main__":
    launch_gui()
