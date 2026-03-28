"""
Video scan panel — drop video files, probe embedded subtitle tracks via ffprobe,
extract text tracks and run ad detection, report findings.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QProgressBar,
    QFileDialog, QFrame, QSplitter, QAbstractItemView,
    QTreeWidget, QTreeWidgetItem, QMessageBox,
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import collect_video_files, scan_video, ffprobe_available, ffmpeg_available
from core.ffprobe import VideoScanResult, SubtitleTrack, VIDEO_EXTENSIONS
from .colors import BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class VideoScanWorker(QThread):
    progress = pyqtSignal(int, int, str)       # current, total, filename
    track_done = pyqtSignal(object, object)    # VideoScanResult, SubtitleTrack
    finished = pyqtSignal(list)                # List[VideoScanResult]

    def __init__(self, paths: List[Path]):
        super().__init__()
        self.paths = paths

    def run(self):
        results: List[VideoScanResult] = []
        for i, path in enumerate(self.paths):
            self.progress.emit(i, len(self.paths), path.name)
            result = scan_video(path)
            results.append(result)
        self.finished.emit(results)


# ---------------------------------------------------------------------------
# Drop zone for video files
# ---------------------------------------------------------------------------

class VideoDropZone(QFrame):
    files_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(100)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("🎬")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: 26px;")

        msg = QLabel("Drop video files here to scan embedded subtitles\n.mkv  .mp4  .m4v  .avi  .mov  .ts")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {FG2}; font-size: 12px;")

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
# Panel
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    "ADS":   RED,
    "WARN":  ORANGE,
    "CLEAN": GREEN,
    "IMAGE": FG2,
    "SKIP":  FG2,
    "ERROR": "#888888",
}


class VideoScanPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: List[VideoScanResult] = []
        self._worker: Optional[VideoScanWorker] = None
        self._queued: List[Path] = []
        self._build_ui()
        self._check_ffmpeg()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── ffmpeg availability notice ─────────────────────────────────
        self._ffmpeg_notice = QLabel()
        self._ffmpeg_notice.setStyleSheet(
            f"color: {ORANGE}; background: {ORANGE}15; border: 1px solid {ORANGE}44;"
            f"border-radius: 4px; padding: 6px 10px; font-size: 12px;"
        )
        self._ffmpeg_notice.setWordWrap(True)
        self._ffmpeg_notice.setVisible(False)

        # ── Top controls ──────────────────────────────────────────────
        ctrl = QHBoxLayout()
        self._btn_add_folder = QPushButton("Add Folder…")
        self._btn_clear = QPushButton("Clear")
        self._btn_scan = QPushButton("⚡  Scan Videos")
        self._btn_scan.setObjectName("btn_clean_all")
        self._btn_scan.setEnabled(False)

        ctrl.addWidget(self._btn_add_folder)
        ctrl.addWidget(self._btn_clear)
        ctrl.addStretch()
        ctrl.addWidget(self._btn_scan)

        # ── Progress / status ─────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(6)

        self._lbl_status = QLabel("Drop video files or add a folder to begin.")
        self._lbl_status.setObjectName("file_status")

        # ── Drop zone ─────────────────────────────────────────────────
        self._drop_zone = VideoDropZone()

        # ── Splitter: file tree | detail ──────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: tree view (video → tracks)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        lbl = QLabel("VIDEO FILES & TRACKS")
        lbl.setObjectName("section_label")

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setFont(QFont("Consolas", 11))
        self._tree.setIndentation(16)

        ll.addWidget(lbl)
        ll.addWidget(self._tree, stretch=1)

        # Right: detail report
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        lbl2 = QLabel("SCAN DETAIL")
        lbl2.setObjectName("section_label")

        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setFont(QFont("Consolas", 11))

        rl.addWidget(lbl2)
        rl.addWidget(self._detail_text)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([340, 500])

        root.addWidget(self._ffmpeg_notice)
        root.addLayout(ctrl)
        root.addWidget(self._drop_zone)
        root.addWidget(self._progress)
        root.addWidget(self._lbl_status)
        root.addWidget(splitter, stretch=1)

        # ── Connections ───────────────────────────────────────────────
        self._drop_zone.files_dropped.connect(self._add_files)
        self._btn_add_folder.clicked.connect(self._browse_folder)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_scan.clicked.connect(self._scan)
        self._tree.currentItemChanged.connect(self._on_tree_selection)

    def _check_ffmpeg(self):
        missing = []
        if not ffprobe_available():
            missing.append("ffprobe")
        if not ffmpeg_available():
            missing.append("ffmpeg")
        if missing:
            tools = " and ".join(missing)
            self._ffmpeg_notice.setText(
                f"⚠  {tools} not found on PATH. "
                f"Install FFmpeg (https://ffmpeg.org/download.html) and ensure it is accessible "
                f"to enable video scanning."
            )
            self._ffmpeg_notice.setVisible(True)

    # ── File collection ───────────────────────────────────────────────────

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add Video Folder")
        if folder:
            paths = collect_video_files([Path(folder)])
            self._add_files(paths)

    def _add_files(self, paths: List[Path]):
        existing = set(self._queued)
        new = [p for p in paths if p not in existing]
        self._queued.extend(new)
        self._lbl_status.setText(
            f"{len(self._queued)} video file(s) queued."
        )
        self._btn_scan.setEnabled(bool(self._queued))

    def _clear(self):
        self._queued.clear()
        self._results.clear()
        self._tree.clear()
        self._detail_text.clear()
        self._lbl_status.setText("Drop video files or add a folder to begin.")
        self._btn_scan.setEnabled(False)

    # ── Scanning ──────────────────────────────────────────────────────────

    def _scan(self):
        if not self._queued:
            return
        if not ffprobe_available():
            QMessageBox.warning(
                self, "ffprobe not found",
                "ffprobe is required for video scanning.\n"
                "Please install FFmpeg and ensure it is on your PATH."
            )
            return

        self._tree.clear()
        self._results.clear()
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._queued))
        self._progress.setValue(0)
        self._btn_scan.setEnabled(False)

        self._worker = VideoScanWorker(self._queued)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_progress(self, current: int, total: int, name: str):
        self._progress.setValue(current)
        self._lbl_status.setText(f"Scanning {current}/{total}: {name}")

    def _on_scan_done(self, results: List[VideoScanResult]):
        self._results = results
        self._progress.setVisible(False)
        self._btn_scan.setEnabled(True)
        self._populate_tree(results)

        total_ads = sum(
            t.ad_count for r in results for t in r.tracks
        )
        self._lbl_status.setText(
            f"Scan complete — {len(results)} video(s) · "
            f"{total_ads} ad block(s) found in embedded subtitles"
        )

    # ── Tree population ───────────────────────────────────────────────────

    def _populate_tree(self, results: List[VideoScanResult]):
        self._tree.clear()
        for result in results:
            # Root node = video file
            root_item = QTreeWidgetItem([result.path.name])
            root_item.setData(0, Qt.ItemDataRole.UserRole, ("video", result))

            if result.error:
                root_item.setForeground(0, QColor("#888888"))
                root_item.setText(0, f"✕  {result.path.name}  — {result.error}")
            else:
                has_ads = any(t.ad_count > 0 for t in result.tracks)
                has_warns = any(t.warning_count > 0 for t in result.tracks)
                if has_ads:
                    root_item.setForeground(0, QColor(RED))
                elif has_warns:
                    root_item.setForeground(0, QColor(ORANGE))
                else:
                    root_item.setForeground(0, QColor(FG2))

                for track in result.tracks:
                    status = track.status_label
                    color = STATUS_COLORS.get(status, FG2)

                    if status == "ADS":
                        icon = "✕"
                    elif status == "WARN":
                        icon = "⚠"
                    elif status == "CLEAN":
                        icon = "✓"
                    elif status == "IMAGE":
                        icon = "◻"
                    else:
                        icon = "·"

                    track_item = QTreeWidgetItem(
                        [f"{icon}  {track.display_name}"]
                    )
                    track_item.setForeground(0, QColor(color))
                    track_item.setData(0, Qt.ItemDataRole.UserRole, ("track", result, track))
                    root_item.addChild(track_item)

            self._tree.addTopLevelItem(root_item)
            root_item.setExpanded(True)

    # ── Selection detail ──────────────────────────────────────────────────

    def _on_tree_selection(self, current, previous):
        if current is None:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data[0] == "video":
            result: VideoScanResult = data[1]
            self._show_video_detail(result)
        elif data[0] == "track":
            result: VideoScanResult = data[1]
            track: SubtitleTrack = data[2]
            self._show_track_detail(result, track)

    def _show_video_detail(self, result: VideoScanResult):
        lines = [f"VIDEO FILE\n{'─'*50}", f"Path:  {result.path}", ""]
        if result.error:
            lines.append(f"Error: {result.error}")
        else:
            lines.append(f"{len(result.tracks)} subtitle track(s) found:\n")
            lines.extend(result.summary_lines())
        self._detail_text.setText("\n".join(lines))

    def _show_track_detail(self, result: VideoScanResult, track: SubtitleTrack):
        lines = [
            f"SUBTITLE TRACK\n{'─'*50}",
            f"Video:    {result.path.name}",
            f"Track:    {track.track_num}  (stream index {track.index})",
            f"Codec:    {track.codec}",
            f"Language: {track.language}",
        ]
        if track.title:
            lines.append(f"Title:    {track.title}")
        lines += [
            f"Forced:   {'Yes' if track.forced else 'No'}",
            f"Default:  {'Yes' if track.default else 'No'}",
            "",
        ]

        if not track.is_text:
            if track.is_image:
                lines.append(
                    "⚠  Image-based subtitle format (PGS/VOBSUB/DVB).\n"
                    "   Text extraction is not possible — OCR is required\n"
                    "   to scan image subtitles, which is not supported."
                )
            else:
                lines.append(f"⚠  Cannot scan: {track.scan_error or 'unsupported codec'}")
        elif track.scan_error:
            lines.append(f"✕  Scan error: {track.scan_error}")
        else:
            lines += [
                f"Blocks:   {track.total_blocks}",
                f"Ads:      {track.ad_count}",
                f"Warnings: {track.warning_count}",
            ]
            if track.flagged_samples:
                lines.append("\nFlagged blocks:")
                for s in track.flagged_samples:
                    lines.append(f"  {s}")

        self._detail_text.setText("\n".join(lines))

    # ── Public API ────────────────────────────────────────────────────────

    def load_paths(self, paths: List[Path]):
        video_paths = [p for p in paths if p.suffix.lower() in VIDEO_EXTENSIONS]
        if video_paths:
            self._add_files(video_paths)
