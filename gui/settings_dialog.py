"""
SubScrubber Settings dialog.

Two tabs:
  - Cleaning Options — global content cleaning settings applied at save time
    across Single File, Batch, and Video Scan tabs
  - Paths — external tool paths (mkvmerge)

Settings persist to settings.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QCheckBox, QPushButton, QLineEdit, QFileDialog,
    QDialogButtonBox, QGroupBox, QScrollArea, QFrame,
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.cleaner_options import CleaningOptions
from core.mkvtoolnix import get_mkvmerge_path, set_mkvmerge_path, mkvmerge_available
from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN

_SETTINGS_FILE = Path(__file__).parent.parent / "settings.json"


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_settings() -> dict:
    try:
        if _SETTINGS_FILE.exists():
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_settings(data: dict) -> None:
    try:
        _SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_cleaning_options() -> CleaningOptions:
    """Load CleaningOptions from settings.json."""
    s = _load_settings()
    c = s.get("cleaning_options", {})
    return CleaningOptions(
        remove_music_cues=c.get("remove_music_cues", False),
        remove_sdh_annotations=c.get("remove_sdh_annotations", False),
        remove_speaker_labels=c.get("remove_speaker_labels", False),
        remove_formatting_tags=c.get("remove_formatting_tags", False),
        preserve_italic=c.get("preserve_italic", True),
        preserve_bold=c.get("preserve_bold", True),
        remove_curly_brackets=c.get("remove_curly_brackets", False),
        remove_square_brackets=c.get("remove_square_brackets", False),
        remove_parentheses=c.get("remove_parentheses", False),
        remove_asterisk_content=c.get("remove_asterisk_content", False),
        remove_hash_content=c.get("remove_hash_content", False),
        normalize_case=c.get("normalize_case", False),
        merge_duplicate_cues=c.get("merge_duplicate_cues", False),
    )


def save_cleaning_options(opts: CleaningOptions) -> None:
    """Persist CleaningOptions to settings.json."""
    s = _load_settings()
    s["cleaning_options"] = {
        "remove_music_cues": opts.remove_music_cues,
        "remove_sdh_annotations": opts.remove_sdh_annotations,
        "remove_speaker_labels": opts.remove_speaker_labels,
        "remove_formatting_tags": opts.remove_formatting_tags,
        "preserve_italic": opts.preserve_italic,
        "preserve_bold": opts.preserve_bold,
        "remove_curly_brackets": opts.remove_curly_brackets,
        "remove_square_brackets": opts.remove_square_brackets,
        "remove_parentheses": opts.remove_parentheses,
        "remove_asterisk_content": opts.remove_asterisk_content,
        "remove_hash_content": opts.remove_hash_content,
        "normalize_case": opts.normalize_case,
        "merge_duplicate_cues": opts.merge_duplicate_cues,
    }
    _save_settings(s)


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SubScrubber Settings")
        self.setMinimumWidth(580)
        self.setMinimumHeight(520)
        self.setStyleSheet(f"QDialog {{ background: {BG}; color: {FG}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: none; background: {BG}; }}"
        )
        layout.addWidget(self._tabs, stretch=1)

        # Build tabs
        self._build_cleaning_tab()
        self._build_paths_tab()

        # Dialog buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.setContentsMargins(12, 0, 12, 0)
        btn_box.accepted.connect(self._save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # Load current values
        self._load_current_values()

    # ── Cleaning Options tab ──────────────────────────────────────────────

    def _build_cleaning_tab(self):
        tab = QWidget()
        tab.setStyleSheet(f"background: {BG};")
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(16, 16, 16, 8)
        outer.setSpacing(12)

        desc = QLabel(
            "These options modify subtitle content at clean time. They apply "
            "globally — the same settings are used in Single File, Batch, and "
            "Video Scan. All options are off by default."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {FG2}; font-size: 10pt;")
        outer.addWidget(desc)

        # SDH accessibility warning — shown when SDH checkbox is ticked
        self._lbl_sdh_warn = QLabel(
            "Warning: Removing SDH content reduces accessibility "
            "for deaf and hard of hearing viewers."
        )
        self._lbl_sdh_warn.setWordWrap(True)
        self._lbl_sdh_warn.setStyleSheet(
            f"color: {ORANGE}; font-size: 9pt; font-style: italic; "
            f"background: transparent; padding: 4px 0;"
        )
        self._lbl_sdh_warn.setVisible(False)
        outer.addWidget(self._lbl_sdh_warn)

        # Scrollable area for checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background: {BG};")

        inner_widget = QWidget()
        inner_widget.setStyleSheet(f"background: {BG};")
        inner = QVBoxLayout(inner_widget)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(6)

        def chk(label, tooltip=""):
            c = QCheckBox(label)
            c.setStyleSheet(f"color: {FG}; font-size: 10pt;")
            if tooltip:
                c.setToolTip(tooltip)
            return c

        def sub_chk(label, tooltip=""):
            c = QCheckBox(label)
            c.setStyleSheet(f"color: {FG2}; font-size: 10pt; margin-left: 22px;")
            if tooltip:
                c.setToolTip(tooltip)
            return c

        def section_label(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {ACCENT}; font-size: 10pt; font-weight: bold; "
                f"margin-top: 6px;"
            )
            return lbl

        # Content removal
        inner.addWidget(section_label("Content Removal"))
        self._chk_music    = chk("Remove music cues",
            "Removes lines consisting entirely of ♪ ♫ music symbols.")
        self._chk_sdh      = chk("Remove SDH annotations",
            "Removes sound descriptions like [DOOR SLAMS] and (LAUGHING).")
        self._chk_speakers = chk("Remove speaker labels",
            "Removes speaker prefixes like JOHN: or - MARY: at the start of lines.")
        inner.addWidget(self._chk_music)
        inner.addWidget(self._chk_sdh)
        inner.addWidget(self._chk_speakers)

        # Formatting
        inner.addWidget(section_label("Formatting"))
        self._chk_tags       = chk("Remove text formatting tags",
            "Removes <font> and other HTML tags. Italic and bold can be preserved below.")
        self._chk_tag_italic = sub_chk("Preserve italic  <i>")
        self._chk_tag_bold   = sub_chk("Preserve bold  <b>")
        self._chk_tag_italic.setChecked(True)
        self._chk_tag_bold.setChecked(True)
        self._chk_tag_italic.setVisible(False)
        self._chk_tag_bold.setVisible(False)
        inner.addWidget(self._chk_tags)
        inner.addWidget(self._chk_tag_italic)
        inner.addWidget(self._chk_tag_bold)

        # Bracket removal
        inner.addWidget(section_label("Remove Content Between"))
        self._chk_br_curly    = sub_chk("Curly brackets  { }")
        self._chk_br_square   = sub_chk("Square brackets  [ ]")
        self._chk_br_parens   = sub_chk("Parentheses  ( )")
        self._chk_br_asterisk = sub_chk("Asterisks  * ... *")
        self._chk_br_hash     = sub_chk("Hashtags  # ... #")
        for c in [self._chk_br_curly, self._chk_br_square, self._chk_br_parens,
                  self._chk_br_asterisk, self._chk_br_hash]:
            inner.addWidget(c)

        # Other
        inner.addWidget(section_label("Other"))
        self._chk_norm_case  = chk("Convert uppercase text to sentence case")
        self._chk_merge_dupe = chk("Merge consecutive duplicate cues")
        inner.addWidget(self._chk_norm_case)
        inner.addWidget(self._chk_merge_dupe)

        inner.addStretch()
        scroll.setWidget(inner_widget)
        outer.addWidget(scroll, stretch=1)

        # Wire SDH and tags toggles
        self._chk_sdh.toggled.connect(self._lbl_sdh_warn.setVisible)
        self._chk_tags.toggled.connect(self._chk_tag_italic.setVisible)
        self._chk_tags.toggled.connect(self._chk_tag_bold.setVisible)

        self._tabs.addTab(tab, "Cleaning Options")

    # ── Paths tab ────────────────────────────────────────────────────────

    def _build_paths_tab(self):
        tab = QWidget()
        tab.setStyleSheet(f"background: {BG};")
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(16, 16, 16, 8)
        outer.setSpacing(16)

        # MKVToolNix
        grp = QGroupBox("MKVToolNix")
        grp.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; "
            f"color: {FG2}; margin-top: 8px; padding-top: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        gl = QVBoxLayout(grp)

        info = QLabel(
            "mkvmerge is used to rebuild MKV files with cleaned subtitle tracks. "
            "If it is not on your system PATH, specify the full path to mkvmerge.exe below. "
            "Not required for MP4 and M4V files."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {FG2}; font-size: 10pt;")

        path_row = QHBoxLayout()
        self._mkv_path_input = QLineEdit()
        self._mkv_path_input.setPlaceholderText(
            r"e.g. C:\Program Files\MKVToolNix\mkvmerge.exe"
        )
        self._mkv_path_input.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 4px;"
        )
        current = get_mkvmerge_path()
        if current:
            self._mkv_path_input.setText(current)

        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._browse_mkvmerge)
        path_row.addWidget(self._mkv_path_input, stretch=1)
        path_row.addWidget(btn_browse)

        self._lbl_mkv_status = QLabel("")
        self._lbl_mkv_status.setStyleSheet("font-size: 10pt;")
        self._update_mkv_status()

        gl.addWidget(info)
        gl.addLayout(path_row)
        gl.addWidget(self._lbl_mkv_status)
        outer.addWidget(grp)
        outer.addStretch()

        self._mkv_path_input.textChanged.connect(self._update_mkv_status)
        self._tabs.addTab(tab, "Paths")

    def _browse_mkvmerge(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Find mkvmerge.exe", "",
            "mkvmerge (mkvmerge.exe);;All Files (*)"
        )
        if path:
            self._mkv_path_input.setText(path)

    def _update_mkv_status(self):
        path = self._mkv_path_input.text().strip()
        if path and Path(path).is_file():
            self._lbl_mkv_status.setText("✓ File found.")
            self._lbl_mkv_status.setStyleSheet(f"color: {GREEN}; font-size: 10pt;")
        elif path:
            self._lbl_mkv_status.setText("✕ File not found at that path.")
            self._lbl_mkv_status.setStyleSheet(f"color: {RED}; font-size: 10pt;")
        elif mkvmerge_available():
            self._lbl_mkv_status.setText(
                f"✓ mkvmerge found on PATH: {get_mkvmerge_path()}"
            )
            self._lbl_mkv_status.setStyleSheet(f"color: {GREEN}; font-size: 10pt;")
        else:
            self._lbl_mkv_status.setText(
                "mkvmerge not found. Install from https://mkvtoolnix.download/"
            )
            self._lbl_mkv_status.setStyleSheet(f"color: {ORANGE}; font-size: 10pt;")

    # ── Load / Save ───────────────────────────────────────────────────────

    def _load_current_values(self):
        opts = load_cleaning_options()
        self._chk_music.setChecked(opts.remove_music_cues)
        self._chk_sdh.setChecked(opts.remove_sdh_annotations)
        self._chk_speakers.setChecked(opts.remove_speaker_labels)
        self._chk_tags.setChecked(opts.remove_formatting_tags)
        self._chk_tag_italic.setChecked(opts.preserve_italic)
        self._chk_tag_bold.setChecked(opts.preserve_bold)
        self._chk_tag_italic.setVisible(opts.remove_formatting_tags)
        self._chk_tag_bold.setVisible(opts.remove_formatting_tags)
        self._chk_br_curly.setChecked(opts.remove_curly_brackets)
        self._chk_br_square.setChecked(opts.remove_square_brackets)
        self._chk_br_parens.setChecked(opts.remove_parentheses)
        self._chk_br_asterisk.setChecked(opts.remove_asterisk_content)
        self._chk_br_hash.setChecked(opts.remove_hash_content)
        self._chk_norm_case.setChecked(opts.normalize_case)
        self._chk_merge_dupe.setChecked(opts.merge_duplicate_cues)
        self._lbl_sdh_warn.setVisible(opts.remove_sdh_annotations)

    def _save(self):
        opts = CleaningOptions(
            remove_music_cues=self._chk_music.isChecked(),
            remove_sdh_annotations=self._chk_sdh.isChecked(),
            remove_speaker_labels=self._chk_speakers.isChecked(),
            remove_formatting_tags=self._chk_tags.isChecked(),
            preserve_italic=self._chk_tag_italic.isChecked(),
            preserve_bold=self._chk_tag_bold.isChecked(),
            remove_curly_brackets=self._chk_br_curly.isChecked(),
            remove_square_brackets=self._chk_br_square.isChecked(),
            remove_parentheses=self._chk_br_parens.isChecked(),
            remove_asterisk_content=self._chk_br_asterisk.isChecked(),
            remove_hash_content=self._chk_br_hash.isChecked(),
            normalize_case=self._chk_norm_case.isChecked(),
            merge_duplicate_cues=self._chk_merge_dupe.isChecked(),
        )
        save_cleaning_options(opts)

        path = self._mkv_path_input.text().strip()
        if path:
            set_mkvmerge_path(path)

        self.accept()
