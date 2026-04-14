"""
gui/setup_wizard.py
First-run setup wizard for SubForge.

Fires once on first launch. Checks FFmpeg and MKVToolNix availability,
shows green/red status per tool with download links, and records completion
in settings.json so it never shows again.
"""

import json
from pathlib import Path

from PyQt6.QtCore    import Qt, QUrl
from PyQt6.QtGui     import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QComboBox,
)

from .colors  import BG, BG2, FG, FG2, ACCENT, GREEN, RED, ORANGE
from .strings import STRINGS

from core.paths import SETTINGS_FILE as _SETTINGS_FILE


def _load_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(data: dict) -> None:
    try:
        _SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def is_setup_complete() -> bool:
    """Return True if the wizard has already been shown and dismissed."""
    return _load_settings().get("setup_complete", False)


def mark_setup_complete() -> None:
    """Record that the wizard has been completed."""
    data = _load_settings()
    data["setup_complete"] = True
    _save_settings(data)


# ---------------------------------------------------------------------------
# Tool row widget
# ---------------------------------------------------------------------------

class _ToolRow(QFrame):
    """A single tool status row: icon + name + status + download link."""

    def __init__(self, name: str, found: bool, detail: str, url: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # Status icon
        icon = QLabel("✓" if found else "✕")
        icon.setFixedWidth(20)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"color: {GREEN}; font-size: 14pt; font-weight: bold;"
            if found else
            f"color: {RED}; font-size: 14pt; font-weight: bold;"
        )
        layout.addWidget(icon)

        # Tool name + detail
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        lbl_name = QLabel(name)
        lbl_name.setStyleSheet(f"color: {FG}; font-size: 10pt; font-weight: bold;")
        text_col.addWidget(lbl_name)

        lbl_detail = QLabel(detail)
        lbl_detail.setStyleSheet(f"color: {FG2}; font-size: 9pt;")
        lbl_detail.setWordWrap(True)
        text_col.addWidget(lbl_detail)

        layout.addLayout(text_col, stretch=1)

        # Download link (only shown when tool is missing)
        if not found and url:
            btn_link = QPushButton(STRINGS["wizard_download"])
            btn_link.setStyleSheet(
                f"QPushButton {{"
                f"  color: {ACCENT}; background: transparent;"
                f"  border: 1px solid {ACCENT}; border-radius: 4px;"
                f"  padding: 4px 10px; font-size: 9pt;"
                f"}}"
                f"QPushButton:hover {{ background: {ACCENT}22; }}"
            )
            btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            layout.addWidget(btn_link)

        self.setStyleSheet(
            f"background: {BG2}; border-radius: 6px;"
        )


# ---------------------------------------------------------------------------
# Wizard dialog
# ---------------------------------------------------------------------------

class SetupWizard(QDialog):
    """First-run setup wizard dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            # No close button — user must click Get Started
        )
        self.setStyleSheet(f"background: {BG}; color: {FG};")
        self._build_ui()

    def _build_ui(self):
        from core.ffprobe    import ffprobe_available, ffmpeg_available
        from core.mkvtoolnix import mkvmerge_available, get_mkvmerge_path
        from core.ocr        import tesseract_available, get_tesseract_path
        from .strings        import LANGUAGES, LANGUAGE_NAMES, get_language

        self.setWindowTitle(STRINGS["wizard_title"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)

        # ── Language selector ─────────────────────────────────────────────
        lang_row = QHBoxLayout()
        lang_lbl = QLabel(STRINGS["settings_lbl_language"])
        lang_lbl.setStyleSheet(f"color: {FG}; font-size: 10pt;")
        self._lang_combo = QComboBox()
        self._lang_codes = list(LANGUAGES.keys())
        for code in self._lang_codes:
            self._lang_combo.addItem(LANGUAGE_NAMES[code])
        current_lang = get_language()
        if current_lang in self._lang_codes:
            self._lang_combo.setCurrentIndex(self._lang_codes.index(current_lang))
        self._lang_combo.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid #444; "
            f"border-radius: 3px; padding: 3px 8px; font-size: 10pt;"
        )
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row.addWidget(lang_lbl)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        # ── Divider ───────────────────────────────────────────────────────
        line0 = QFrame()
        line0.setFrameShape(QFrame.Shape.HLine)
        line0.setStyleSheet(f"color: {BG2};")
        layout.addWidget(line0)

        # ── Header ────────────────────────────────────────────────────────
        lbl_title = QLabel(STRINGS["wizard_heading"])
        lbl_title.setStyleSheet(f"color: {FG}; font-size: 14pt; font-weight: bold;")
        lbl_title.setWordWrap(True)
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(STRINGS["wizard_subheading"])
        lbl_sub.setStyleSheet(f"color: {FG2}; font-size: 9pt;")
        lbl_sub.setWordWrap(True)
        layout.addWidget(lbl_sub)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {BG2};")
        layout.addWidget(line)

        # ── Tool rows ─────────────────────────────────────────────────────
        has_ffprobe = ffprobe_available()
        has_ffmpeg  = ffmpeg_available()
        has_mkv     = mkvmerge_available()
        has_tess    = tesseract_available()
        from core.whisper import faster_whisper_available
        has_whisper = faster_whisper_available()

        ffmpeg_ok = has_ffprobe and has_ffmpeg
        if ffmpeg_ok:
            detail = STRINGS["wizard_ffmpeg_ok"]
        elif has_ffprobe or has_ffmpeg:
            detail = STRINGS["wizard_ffmpeg_partial"]
        else:
            detail = STRINGS["wizard_ffmpeg_missing"]

        layout.addWidget(_ToolRow(
            name   = "FFmpeg",
            found  = ffmpeg_ok,
            detail = detail,
            url    = "https://ffmpeg.org/download.html",
        ))

        if has_mkv:
            mkv_detail = STRINGS["wizard_mkv_ok"].format(path=get_mkvmerge_path())
        else:
            mkv_detail = STRINGS["wizard_mkv_missing"]

        layout.addWidget(_ToolRow(
            name   = "MKVToolNix",
            found  = has_mkv,
            detail = mkv_detail,
            url    = "https://mkvtoolnix.download/",
        ))

        if has_tess:
            tess_detail = STRINGS["wizard_tesseract_ok"].format(path=get_tesseract_path())
        else:
            tess_detail = STRINGS["wizard_tesseract_missing"]

        layout.addWidget(_ToolRow(
            name   = "Tesseract OCR",
            found  = has_tess,
            detail = tess_detail,
            url    = "https://github.com/UB-Mannheim/tesseract/wiki",
        ))

        layout.addWidget(_ToolRow(
            name   = "faster-whisper",
            found  = has_whisper,
            detail = STRINGS["wizard_whisper_ok"] if has_whisper else STRINGS["wizard_whisper_missing"],
            url    = "https://github.com/SYSTRAN/faster-whisper",
        ))

        # ── Footer ────────────────────────────────────────────────────────
        lbl_note = QLabel(STRINGS["wizard_note"])
        lbl_note.setStyleSheet(f"color: {FG2}; font-size: 8pt;")
        lbl_note.setWordWrap(True)
        layout.addWidget(lbl_note)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton(STRINGS["wizard_btn_start"])
        btn_ok.setMinimumWidth(120)
        btn_ok.setStyleSheet(
            f"QPushButton {{"
            f"  background: {ACCENT}; color: {BG};"
            f"  border: none; border-radius: 5px;"
            f"  padding: 8px 20px; font-size: 10pt; font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{ background: {ACCENT}cc; }}"
        )
        btn_ok.clicked.connect(self._finish)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def _on_language_changed(self, index: int):
        """Save language and restart the app to apply it fully."""
        import sys, subprocess
        from .strings import set_language
        from gui.settings_dialog import save_language

        lang_code = self._lang_codes[index]
        save_language(lang_code)
        set_language(lang_code)

        # Restart immediately — wizard is still open so main window hasn't
        # been interacted with. Mark setup NOT complete so wizard re-shows
        # in the new language after restart.
        frozen = getattr(sys, "frozen", False)
        args = [sys.executable] if frozen else [sys.executable] + sys.argv

        creationflags = 0
        if sys.platform == "win32":
            DETACHED_PROCESS     = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

        subprocess.Popen(args, close_fds=True, creationflags=creationflags)

        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.quit()
        sys.exit(0)

    def _finish(self):
        mark_setup_complete()
        self.accept()

    def closeEvent(self, event):
        mark_setup_complete()
        super().closeEvent(event)
