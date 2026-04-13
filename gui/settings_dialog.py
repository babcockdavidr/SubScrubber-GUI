"""
SubForge Settings dialog.

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
    QGroupBox, QScrollArea, QFrame,
)

import sys
import webbrowser
# sys.path managed by subforge.py entry point — do not insert __file__-relative paths here

from core.cleaner_options import CleaningOptions
from core.mkvtoolnix import get_mkvmerge_path, set_mkvmerge_path, mkvmerge_available
from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW
from .strings import STRINGS

from core.paths import SETTINGS_FILE as _SETTINGS_FILE


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


def load_default_sensitivity() -> int:
    """Load default sensitivity from settings.json. Returns 3 if not set."""
    return _load_settings().get("default_sensitivity", 3)


def save_default_sensitivity(value: int) -> None:
    """Persist default sensitivity to settings.json."""
    s = _load_settings()
    s["default_sensitivity"] = value
    _save_settings(s)


def load_language() -> str:
    """Load saved language code from settings.json. Returns 'en' if not set."""
    return _load_settings().get("language", "en")


def save_language(lang_code: str) -> None:
    """Persist language code to settings.json."""
    s = _load_settings()
    s["language"] = lang_code
    _save_settings(s)


def get_language() -> str:
    """Return currently active language code."""
    from .strings import get_language as _get
    return _get()


def detect_and_save_language() -> str:
    """
    Auto-detect OS locale on first launch and save it if no language is set.
    Returns the language code that was set (existing or newly detected).
    """
    s = _load_settings()
    if "language" in s:
        return s["language"]  # already set — don't override

    from PyQt6.QtCore import QLocale
    from .strings import LANGUAGES
    locale_name = QLocale.system().name()  # e.g. "es_ES", "fr_FR"
    lang_code = locale_name.split("_")[0].lower()  # e.g. "es", "fr"

    if lang_code not in LANGUAGES:
        lang_code = "en"

    s["language"] = lang_code
    _save_settings(s)
    return lang_code


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
        self.setWindowTitle(STRINGS["settings_title"])
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

        # Build tabs — General first, About last
        self._build_general_tab()
        self._build_cleaning_tab()
        self._build_paths_tab()
        self._build_about_tab()

        # Dialog buttons — manual buttons so text is translatable
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(12, 0, 12, 0)
        btn_bar.addStretch()
        self._btn_cancel = QPushButton(STRINGS["settings_btn_cancel"])
        self._btn_cancel.setStyleSheet(
            f"padding: 6px 18px; font-size: 10pt; color: {FG2}; "
            f"border: 1px solid {BORDER}; border-radius: 3px; background: {BG2};"
        )
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_save = QPushButton(STRINGS["settings_btn_save"])
        self._btn_save.setStyleSheet(
            f"padding: 6px 18px; font-size: 10pt; color: {BG}; "
            f"border: none; border-radius: 3px; background: {ACCENT};"
        )
        self._btn_save.clicked.connect(self._save)
        btn_bar.addWidget(self._btn_cancel)
        btn_bar.addWidget(self._btn_save)
        layout.addLayout(btn_bar)
        self._btn_bar_widget = (self._btn_save, self._btn_cancel)

        # Hide Save/Cancel when on About tab
        self._tabs.currentChanged.connect(
            lambda i: [w.setVisible(
                self._tabs.tabText(i) != STRINGS["settings_tab_about"]
            ) for w in self._btn_bar_widget]
        )

        # Load current values
        self._load_current_values()

    # ── General tab ───────────────────────────────────────────────────────

    def _build_general_tab(self):
        from PyQt6.QtWidgets import QSlider
        from PyQt6.QtCore import Qt
        tab = QWidget()
        tab.setStyleSheet(f"background: {BG};")
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(16, 16, 16, 8)
        outer.setSpacing(16)

        # ── Default sensitivity ───────────────────────────────────────────
        sens_grp = QGroupBox(STRINGS["settings_grp_sensitivity"])
        sens_grp.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; "
            f"color: {FG2}; margin-top: 8px; padding-top: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        sens_layout = QVBoxLayout(sens_grp)

        sens_desc = QLabel(STRINGS["settings_sens_desc"])
        sens_desc.setWordWrap(True)
        sens_desc.setStyleSheet(f"color: {FG2}; font-size: 10pt;")
        sens_layout.addWidget(sens_desc)

        slider_row = QHBoxLayout()
        lbl_agg = QLabel(STRINGS["sens_more_aggressive"])
        lbl_agg.setStyleSheet(f"color: {RED}; font-size: 9pt;")
        lbl_con = QLabel(STRINGS["sens_more_conservative"])
        lbl_con.setStyleSheet(f"color: {GREEN}; font-size: 9pt;")

        self._sens_slider = QSlider(Qt.Orientation.Horizontal)
        self._sens_slider.setMinimum(1)
        self._sens_slider.setMaximum(5)
        self._sens_slider.setValue(load_default_sensitivity())
        self._sens_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._sens_slider.setTickInterval(1)
        self._sens_slider.setFixedWidth(200)

        _labels = {
            1: STRINGS["thresh_1"],
            2: STRINGS["thresh_2"],
            3: STRINGS["thresh_3"],
            4: STRINGS["thresh_4"],
            5: STRINGS["thresh_5"],
        }
        self._lbl_sens_val = QLabel(_labels.get(self._sens_slider.value(), ""))
        self._lbl_sens_val.setStyleSheet(f"color: {YELLOW}; font-size: 10pt;")
        self._sens_slider.valueChanged.connect(
            lambda v: self._lbl_sens_val.setText(_labels.get(v, str(v)))
        )

        slider_row.addWidget(lbl_agg)
        slider_row.addWidget(self._sens_slider)
        slider_row.addWidget(lbl_con)
        slider_row.addSpacing(12)
        slider_row.addWidget(self._lbl_sens_val, stretch=1)
        sens_layout.addLayout(slider_row)
        outer.addWidget(sens_grp)

        # ── Placeholders (v1.0.0) ────────────────────────────────────────
        # ── Language selector ─────────────────────────────────────────────
        from PyQt6.QtWidgets import QComboBox
        from .strings import LANGUAGES, LANGUAGE_NAMES, get_language
        lang_grp = QGroupBox("Language")
        lang_grp.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; "
            f"color: {FG2}; margin-top: 8px; padding-top: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        lang_layout = QVBoxLayout(lang_grp)
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
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 3px 8px; font-size: 10pt;"
        )
        lang_row.addWidget(lang_lbl)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()
        lang_layout.addLayout(lang_row)
        outer.addWidget(lang_grp)

        future_grp = QGroupBox(STRINGS["settings_future_grp"])
        future_grp.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; "
            f"color: {FG2}; margin-top: 8px; padding-top: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        future_layout = QVBoxLayout(future_grp)
        for label in [STRINGS["settings_future_theme"], STRINGS["settings_future_font"], STRINGS["settings_future_lang"]]:
            lbl = QLabel(f"○  {label}")
            lbl.setStyleSheet(f"color: {FG2}; font-size: 10pt; padding: 2px 0;")
            future_layout.addWidget(lbl)
        outer.addWidget(future_grp)

        outer.addStretch()
        self._tabs.addTab(tab, STRINGS["settings_tab_general"])

    # ── Cleaning Options tab ──────────────────────────────────────────────

    def _build_cleaning_tab(self):
        tab = QWidget()
        tab.setStyleSheet(f"background: {BG};")
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(16, 16, 16, 8)
        outer.setSpacing(12)

        desc = QLabel(STRINGS["settings_cleaning_desc"])
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {FG2}; font-size: 10pt;")
        outer.addWidget(desc)

        # SDH accessibility warning — shown when SDH checkbox is ticked
        self._lbl_sdh_warn = QLabel(STRINGS["settings_sdh_warn"])
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
        inner.addWidget(section_label(STRINGS["settings_section_removal"]))
        self._chk_music    = chk(STRINGS["settings_chk_music"], STRINGS["settings_chk_music_tip"])
        self._chk_sdh      = chk(STRINGS["settings_chk_sdh"], STRINGS["settings_chk_sdh_tip"])
        self._chk_speakers = chk(STRINGS["settings_chk_speakers"], STRINGS["settings_chk_speakers_tip"])
        inner.addWidget(self._chk_music)
        inner.addWidget(self._chk_sdh)
        inner.addWidget(self._chk_speakers)

        # Formatting
        inner.addWidget(section_label(STRINGS["settings_section_formatting"]))
        self._chk_tags       = chk(STRINGS["settings_chk_tags"], STRINGS["settings_chk_tags_tip"])
        self._chk_tag_italic = sub_chk(STRINGS["settings_chk_italic"])
        self._chk_tag_bold   = sub_chk(STRINGS["settings_chk_bold"])
        self._chk_tag_italic.setChecked(True)
        self._chk_tag_bold.setChecked(True)
        self._chk_tag_italic.setVisible(False)
        self._chk_tag_bold.setVisible(False)
        inner.addWidget(self._chk_tags)
        inner.addWidget(self._chk_tag_italic)
        inner.addWidget(self._chk_tag_bold)

        # Bracket removal
        inner.addWidget(section_label(STRINGS["settings_section_between"]))
        self._chk_br_curly    = sub_chk(STRINGS["settings_chk_curly"])
        self._chk_br_square   = sub_chk(STRINGS["settings_chk_square"])
        self._chk_br_parens   = sub_chk(STRINGS["settings_chk_parens"])
        self._chk_br_asterisk = sub_chk(STRINGS["settings_chk_asterisk"])
        self._chk_br_hash     = sub_chk(STRINGS["settings_chk_hash"])
        for c in [self._chk_br_curly, self._chk_br_square, self._chk_br_parens,
                  self._chk_br_asterisk, self._chk_br_hash]:
            inner.addWidget(c)

        # Other
        inner.addWidget(section_label(STRINGS["settings_section_other"]))
        self._chk_norm_case  = chk(STRINGS["settings_chk_norm_case"])
        self._chk_merge_dupe = chk(STRINGS["settings_chk_merge_dupe"])
        inner.addWidget(self._chk_norm_case)
        inner.addWidget(self._chk_merge_dupe)

        inner.addStretch()
        scroll.setWidget(inner_widget)
        outer.addWidget(scroll, stretch=1)

        # Wire SDH and tags toggles
        self._chk_sdh.toggled.connect(self._lbl_sdh_warn.setVisible)
        self._chk_tags.toggled.connect(self._chk_tag_italic.setVisible)
        self._chk_tags.toggled.connect(self._chk_tag_bold.setVisible)

        self._tabs.addTab(tab, STRINGS["settings_tab_cleaning"])

    # ── About tab ────────────────────────────────────────────────────────

    def _build_about_tab(self):
        from core.updater import CURRENT_VERSION
        tab = QWidget()
        tab.setStyleSheet(f"background: {BG};")
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(32, 32, 32, 24)
        outer.setSpacing(0)

        # App name
        lbl_name = QLabel(STRINGS["app_title"])
        lbl_name.setStyleSheet(
            f"color: {ACCENT}; font-size: 22pt; font-weight: bold; letter-spacing: 2px;"
        )
        outer.addWidget(lbl_name)

        # Version
        lbl_version = QLabel(CURRENT_VERSION)
        lbl_version.setStyleSheet(f"color: {FG2}; font-size: 11pt; margin-bottom: 16px;")
        outer.addWidget(lbl_version)

        outer.addSpacing(12)

        # Tagline
        lbl_tag = QLabel(STRINGS["settings_about_tagline"])
        lbl_tag.setWordWrap(True)
        lbl_tag.setStyleSheet(f"color: {FG}; font-size: 10pt;")
        outer.addWidget(lbl_tag)

        outer.addSpacing(24)

        # Primary credit
        lbl_author = QLabel(STRINGS["settings_about_author"])
        lbl_author.setStyleSheet(f"color: {FG}; font-size: 11pt; font-weight: bold;")
        outer.addWidget(lbl_author)

        outer.addSpacing(4)

        # GitHub link
        lbl_github = QLabel(
            '<a href="https://github.com/babcockdavidr/SubForge" '
            f'style="color: {ACCENT};">github.com/babcockdavidr/SubForge</a>'
        )
        lbl_github.setOpenExternalLinks(True)
        lbl_github.setStyleSheet("font-size: 10pt;")
        outer.addWidget(lbl_github)

        outer.addSpacing(24)

        # License
        lbl_license = QLabel(STRINGS["settings_about_license"])
        lbl_license.setStyleSheet(f"color: {FG2}; font-size: 10pt;")
        outer.addWidget(lbl_license)

        outer.addSpacing(8)

        # Detection engine credit
        lbl_credit = QLabel(
            f'<a href="https://github.com/KBlixt/subcleaner" '
            f'style="color: {FG2};">subcleaner</a> — '
            + STRINGS["settings_about_credit"]
        )
        lbl_credit.setOpenExternalLinks(True)
        lbl_credit.setStyleSheet(f"color: {FG2}; font-size: 9pt;")
        outer.addWidget(lbl_credit)

        outer.addStretch()

        # Report an Issue button
        btn_issue = QPushButton(STRINGS["settings_btn_report_issue"])
        btn_issue.setStyleSheet(
            f"font-size: 10pt; padding: 6px 16px; color: {FG2}; "
            f"border: 1px solid {BORDER}; border-radius: 3px; background: {BG2};"
        )
        btn_issue.clicked.connect(lambda: webbrowser.open(
            "https://github.com/babcockdavidr/SubForge/issues/new"
        ))
        btn_whats_new = QPushButton(STRINGS["settings_btn_whats_new"])
        btn_whats_new.setStyleSheet(
            f"font-size: 10pt; padding: 6px 16px; color: {FG2}; "
            f"border: 1px solid {BORDER}; border-radius: 3px; background: {BG2};"
        )
        btn_whats_new.clicked.connect(self._show_changelog)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_whats_new)
        btn_row.addWidget(btn_issue)
        outer.addLayout(btn_row)

        self._tabs.addTab(tab, STRINGS["settings_tab_about"])

    # ── Paths tab ────────────────────────────────────────────────────────

    def _show_changelog(self):
        from gui.changelog_dialog import ChangelogDialog
        dlg = ChangelogDialog(self)
        dlg.exec()

    def _build_paths_tab(self):
        tab = QWidget()
        tab.setStyleSheet(f"background: {BG};")
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(16, 16, 16, 8)
        outer.setSpacing(16)

        # MKVToolNix
        grp = QGroupBox(STRINGS["settings_grp_mkv"])
        grp.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; "
            f"color: {FG2}; margin-top: 8px; padding-top: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        gl = QVBoxLayout(grp)

        info = QLabel(STRINGS["settings_mkv_info"])
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {FG2}; font-size: 10pt;")

        path_row = QHBoxLayout()
        self._mkv_path_input = QLineEdit()
        self._mkv_path_input.setPlaceholderText(STRINGS["settings_mkv_placeholder"])
        self._mkv_path_input.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 4px;"
        )
        current = get_mkvmerge_path()
        if current:
            self._mkv_path_input.setText(current)

        btn_browse = QPushButton(STRINGS["settings_browse"])
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
        self._tabs.addTab(tab, STRINGS["settings_tab_paths"])

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
            self._lbl_mkv_status.setText(STRINGS["settings_mkv_found"])
            self._lbl_mkv_status.setStyleSheet(f"color: {GREEN}; font-size: 10pt;")
        elif path:
            self._lbl_mkv_status.setText(STRINGS["settings_mkv_not_found"])
            self._lbl_mkv_status.setStyleSheet(f"color: {RED}; font-size: 10pt;")
        elif mkvmerge_available():
            self._lbl_mkv_status.setText(
                STRINGS["settings_mkv_on_path"].format(path=get_mkvmerge_path())
            )
            self._lbl_mkv_status.setStyleSheet(f"color: {GREEN}; font-size: 10pt;")
        else:
            self._lbl_mkv_status.setText(
                STRINGS["settings_mkv_missing"]
            )
            self._lbl_mkv_status.setStyleSheet(f"color: {ORANGE}; font-size: 10pt;")

    # ── Load / Save ───────────────────────────────────────────────────────

    def _load_current_values(self):
        self._sens_slider.setValue(load_default_sensitivity())
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
        save_default_sensitivity(self._sens_slider.value())
        # Save and apply language
        selected_idx = self._lang_combo.currentIndex()
        lang_code = self._lang_codes[selected_idx]
        prev_lang = get_language()
        save_language(lang_code)
        from .strings import set_language
        set_language(lang_code)
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

        # Offer restart if language changed
        if lang_code != prev_lang:
            import sys, os, subprocess
            from PyQt6.QtWidgets import QMessageBox, QApplication
            btn = QMessageBox.question(
                None,
                STRINGS["settings_btn_restart"],
                STRINGS["settings_restart_required"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if btn == QMessageBox.StandardButton.Yes:
                # Frozen bundle: relaunch exe directly.
                # Source: relaunch via Python interpreter.
                frozen = getattr(sys, "frozen", False)
                args = [sys.executable] if frozen else [sys.executable] + sys.argv

                # Spawn new instance then exit — os.execv unreliable in frozen apps
                creationflags = 0
                if sys.platform == "win32":
                    DETACHED_PROCESS    = 0x00000008
                    CREATE_NEW_PROCESS_GROUP = 0x00000200
                    creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

                subprocess.Popen(args, close_fds=True, creationflags=creationflags)
                app = QApplication.instance()
                if app:
                    app.quit()
                else:
                    sys.exit(0)


# ---------------------------------------------------------------------------
# Session memory
# ---------------------------------------------------------------------------

def load_session() -> dict:
    """Load session state from settings.json. Returns safe defaults if missing."""
    data = _load_settings()
    return {
        "last_batch_folder":  data.get("last_batch_folder", ""),
        "last_video_folder":  data.get("last_video_folder", ""),
        "window_geometry":    data.get("window_geometry", ""),
    }


def save_session(last_batch_folder: str, last_video_folder: str, window_geometry: str) -> None:
    """Persist session state to settings.json."""
    data = _load_settings()
    data["last_batch_folder"] = last_batch_folder
    data["last_video_folder"] = last_video_folder
    data["window_geometry"]   = window_geometry
    _save_settings(data)
