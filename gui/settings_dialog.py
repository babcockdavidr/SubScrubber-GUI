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
from core.whisper import get_model_dir, set_model_dir, clear_model_dir
from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW, get_theme
from .strings import STRINGS

from core.paths import load_settings as _load_settings, save_settings as _save_settings


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------



def load_font_size() -> str:
    """Load saved font size from settings.json. Returns 'medium' if not set."""
    return _load_settings().get("font_size", "medium")


def save_font_size(size: str) -> None:
    """Persist font size to settings.json."""
    s = dict(_load_settings())
    s["font_size"] = size
    _save_settings(s)


def get_font_pt() -> int:
    """Return the current base font size in points (body text)."""
    return {"small": 9, "medium": 11, "large": 14}.get(load_font_size(), 11)


def get_font_pt_small() -> int:
    """Return the current small font size in points (secondary text)."""
    return get_font_pt() - 1


def get_font_pt_tiny() -> int:
    """Return the current tiny font size in points (labels, badges)."""
    return max(get_font_pt() - 2, 7)


def load_default_sensitivity() -> int:
    """Load default sensitivity from settings.json. Returns 3 if not set."""
    return _load_settings().get("default_sensitivity", 3)


def save_default_sensitivity(value: int) -> None:
    """Persist default sensitivity to settings.json."""
    s = dict(_load_settings())
    s["default_sensitivity"] = value
    _save_settings(s)


def load_language() -> str:
    """Load saved language code from settings.json. Returns 'en' if not set."""
    return _load_settings().get("language", "en")


def save_language(lang_code: str) -> None:
    """Persist language code to settings.json."""
    s = dict(_load_settings())
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
    s = dict(_load_settings())
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
    s = dict(_load_settings())
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
    def __init__(self, parent=None, watcher_mgr=None):
        super().__init__(parent)
        self._watcher_mgr = watcher_mgr
        self.setWindowTitle(STRINGS["settings_title"])
        self.setMinimumWidth(740)
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
        self._build_watch_tab()
        self._build_scheduler_tab()
        self._build_about_tab()

        # Dialog buttons — manual buttons so text is translatable
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(12, 0, 12, 0)
        btn_bar.addStretch()
        self._btn_cancel = QPushButton(STRINGS["settings_btn_cancel"])
        self._btn_cancel.setToolTip(STRINGS["tip_settings_cancel"])
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_save = QPushButton(STRINGS["settings_btn_save"])
        self._btn_save.setObjectName("btn_settings_primary")
        self._btn_save.setToolTip(STRINGS["tip_settings_save"])
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

        # Tab order — General tab controls → cleaning checkboxes → path inputs → buttons
        self.setTabOrder(self._sens_slider,      self._lang_combo)
        self.setTabOrder(self._lang_combo,       self._theme_combo)
        self.setTabOrder(self._theme_combo,      self._font_combo)
        self.setTabOrder(self._font_combo,       self._chk_music)
        self.setTabOrder(self._chk_music,        self._chk_sdh)
        self.setTabOrder(self._chk_sdh,          self._chk_speakers)
        self.setTabOrder(self._chk_speakers,     self._chk_tags)
        self.setTabOrder(self._chk_tags,         self._chk_tag_italic)
        self.setTabOrder(self._chk_tag_italic,   self._chk_tag_bold)
        self.setTabOrder(self._chk_tag_bold,     self._chk_br_curly)
        self.setTabOrder(self._chk_br_curly,     self._chk_br_square)
        self.setTabOrder(self._chk_br_square,    self._chk_br_parens)
        self.setTabOrder(self._chk_br_parens,    self._chk_br_asterisk)
        self.setTabOrder(self._chk_br_asterisk,  self._chk_br_hash)
        self.setTabOrder(self._chk_br_hash,      self._chk_norm_case)
        self.setTabOrder(self._chk_norm_case,    self._chk_merge_dupe)
        self.setTabOrder(self._chk_merge_dupe,   self._mkv_path_input)
        self.setTabOrder(self._mkv_path_input,   self._ffmpeg_path_input)
        self.setTabOrder(self._ffmpeg_path_input, self._ffprobe_path_input)
        self.setTabOrder(self._ffprobe_path_input, self._tess_path_input)
        self.setTabOrder(self._tess_path_input,  self._whisper_dir_input)
        self.setTabOrder(self._whisper_dir_input, self._btn_cancel)
        self.setTabOrder(self._btn_cancel,       self._btn_save)

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
        sens_desc.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")
        sens_layout.addWidget(sens_desc)

        slider_row = QHBoxLayout()
        lbl_agg = QLabel(STRINGS["sens_more_aggressive"])
        lbl_agg.setStyleSheet(f"color: {RED}; font-size: {get_font_pt_small()}pt;")
        lbl_con = QLabel(STRINGS["sens_more_conservative"])
        lbl_con.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt_small()}pt;")

        self._sens_slider = QSlider(Qt.Orientation.Horizontal)
        self._sens_slider.setMinimum(1)
        self._sens_slider.setMaximum(5)
        self._sens_slider.setValue(load_default_sensitivity())
        self._sens_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._sens_slider.setTickInterval(1)
        self._sens_slider.setFixedWidth(200)
        self._sens_slider.setAccessibleName(STRINGS["settings_grp_sensitivity"])
        self._sens_slider.setAccessibleDescription(STRINGS["settings_sens_desc"])

        _labels = {
            1: STRINGS["thresh_1"],
            2: STRINGS["thresh_2"],
            3: STRINGS["thresh_3"],
            4: STRINGS["thresh_4"],
            5: STRINGS["thresh_5"],
        }
        self._lbl_sens_val = QLabel(_labels.get(self._sens_slider.value(), ""))
        self._lbl_sens_val.setStyleSheet(f"color: {YELLOW}; font-size: {get_font_pt()}pt;")
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
        lang_lbl.setStyleSheet(f"color: {FG}; font-size: {get_font_pt()}pt;")
        self._lang_combo = QComboBox()
        self._lang_codes = list(LANGUAGES.keys())
        for code in self._lang_codes:
            self._lang_combo.addItem(LANGUAGE_NAMES[code])
        current_lang = get_language()
        if current_lang in self._lang_codes:
            self._lang_combo.setCurrentIndex(self._lang_codes.index(current_lang))
        self._lang_combo.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 3px 8px; font-size: {get_font_pt()}pt;"
        )
        self._lang_combo.setAccessibleName(STRINGS["settings_lbl_language"])
        lang_row.addWidget(lang_lbl)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()
        lang_layout.addLayout(lang_row)
        outer.addWidget(lang_grp)

        # ── Appearance (Theme) ────────────────────────────────────────────
        from PyQt6.QtWidgets import QComboBox as _QComboBox
        appear_grp = QGroupBox(STRINGS["settings_grp_appearance"])
        appear_grp.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; "
            f"color: {FG2}; margin-top: 8px; padding-top: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        appear_layout = QVBoxLayout(appear_grp)
        theme_row = QHBoxLayout()
        theme_lbl = QLabel(STRINGS["settings_lbl_theme"])
        theme_lbl.setStyleSheet(f"color: {FG}; font-size: {get_font_pt()}pt;")
        self._theme_combo = _QComboBox()
        self._theme_names  = ["dark", "light", "high_contrast", "amoled"]
        self._theme_labels = [
            STRINGS["settings_theme_dark"],
            STRINGS["settings_theme_light"],
            STRINGS["settings_theme_hc"],
            STRINGS["settings_theme_amoled"],
        ]
        for label in self._theme_labels:
            self._theme_combo.addItem(label)
        current_theme = get_theme()
        if current_theme in self._theme_names:
            self._theme_combo.setCurrentIndex(self._theme_names.index(current_theme))
        self._theme_combo.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 3px 8px; font-size: {get_font_pt()}pt;"
        )
        self._theme_combo.setAccessibleName(STRINGS["settings_lbl_theme"])
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(self._theme_combo)
        theme_row.addStretch()
        appear_layout.addLayout(theme_row)

        # Font size row
        font_row = QHBoxLayout()
        font_lbl = QLabel(STRINGS["settings_lbl_font_size"])
        font_lbl.setStyleSheet(f"color: {FG}; font-size: {get_font_pt()}pt;")
        self._font_combo = _QComboBox()
        self._font_size_names  = ["small", "medium", "large"]
        self._font_size_labels = [
            STRINGS["settings_font_small"],
            STRINGS["settings_font_medium"],
            STRINGS["settings_font_large"],
        ]
        for label in self._font_size_labels:
            self._font_combo.addItem(label)
        current_font = load_font_size()
        if current_font in self._font_size_names:
            self._font_combo.setCurrentIndex(self._font_size_names.index(current_font))
        self._font_combo.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 3px 8px; font-size: {get_font_pt()}pt;"
        )
        self._font_combo.setAccessibleName(STRINGS["settings_lbl_font_size"])
        font_row.addWidget(font_lbl)
        font_row.addWidget(self._font_combo)
        font_row.addStretch()
        appear_layout.addLayout(font_row)

        outer.addWidget(appear_grp)

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
        desc.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")
        outer.addWidget(desc)

        # SDH accessibility warning — shown when SDH checkbox is ticked
        self._lbl_sdh_warn = QLabel(STRINGS["settings_sdh_warn"])
        self._lbl_sdh_warn.setWordWrap(True)
        self._lbl_sdh_warn.setStyleSheet(
            f"color: {ORANGE}; font-size: {get_font_pt_small()}pt; font-style: italic; "
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
            c.setStyleSheet(f"color: {FG}; font-size: {get_font_pt()}pt;")
            if tooltip:
                c.setToolTip(tooltip)
            return c

        def sub_chk(label, tooltip=""):
            c = QCheckBox(label)
            c.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt; margin-left: 22px;")
            if tooltip:
                c.setToolTip(tooltip)
            return c

        def section_label(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {ACCENT}; font-size: {get_font_pt()}pt; font-weight: bold; "
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
        lbl_tag.setStyleSheet(f"color: {FG}; font-size: {get_font_pt()}pt;")
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
        lbl_github.setStyleSheet("font-size: {get_font_pt()}pt;")
        outer.addWidget(lbl_github)

        outer.addSpacing(24)

        # License
        lbl_license = QLabel(STRINGS["settings_about_license"])
        lbl_license.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")
        outer.addWidget(lbl_license)

        outer.addSpacing(8)

        # Detection engine credit
        lbl_credit = QLabel(
            f'<a href="https://github.com/KBlixt/subcleaner" '
            f'style="color: {FG2};">subcleaner</a> — '
            + STRINGS["settings_about_credit"]
        )
        lbl_credit.setOpenExternalLinks(True)
        lbl_credit.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt_small()}pt;")
        outer.addWidget(lbl_credit)

        outer.addStretch()

        # Report an Issue button
        btn_issue = QPushButton(STRINGS["settings_btn_report_issue"])
        btn_issue.setToolTip(STRINGS["tip_settings_report_issue"])
        btn_issue.clicked.connect(lambda: webbrowser.open(
            "https://github.com/babcockdavidr/SubForge/issues/new"
        ))
        btn_whats_new = QPushButton(STRINGS["settings_btn_whats_new"])
        btn_whats_new.setToolTip(STRINGS["tip_settings_whats_new"])
        btn_whats_new.clicked.connect(self._show_changelog)
        btn_log = QPushButton(STRINGS["settings_btn_view_log"])
        btn_log.setToolTip(STRINGS["tip_settings_view_log"])
        btn_log.clicked.connect(self._show_error_log)

        btn_data = QPushButton(STRINGS["settings_btn_open_data_folder"])
        btn_data.setToolTip(STRINGS["tip_settings_open_data_folder"])
        btn_data.clicked.connect(self._open_data_folder)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_data)
        btn_row.addWidget(btn_log)
        btn_row.addWidget(btn_whats_new)
        btn_row.addWidget(btn_issue)
        outer.addLayout(btn_row)

        self._tabs.addTab(tab, STRINGS["settings_tab_about"])

    # ── Watch Folders tab ────────────────────────────────────────────────

    def _build_watch_tab(self):
        from core.watcher import load_watch_folders
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem

        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        intro = QLabel(STRINGS["settings_watch_intro"])
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")
        outer.addWidget(intro)

        # Folder list
        self._watch_list = QListWidget()
        self._watch_list.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; font-size: {get_font_pt()}pt;"
        )
        self._watch_list.setSelectionMode(
            self._watch_list.SelectionMode.SingleSelection
        )
        outer.addWidget(self._watch_list, stretch=1)

        # Empty-state label (shown when list is empty)
        self._watch_empty_lbl = QLabel(STRINGS["settings_watch_empty"])
        self._watch_empty_lbl.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")
        self._watch_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._watch_empty_lbl)

        # Populate from saved settings
        saved = load_watch_folders()
        for folder in saved:
            self._watch_list.addItem(folder)
        self._watch_empty_lbl.setVisible(self._watch_list.count() == 0)
        self._watch_list.setVisible(self._watch_list.count() > 0)

        # Button row
        btn_row = QHBoxLayout()
        btn_add = QPushButton(STRINGS["settings_watch_btn_add"])
        btn_add.setToolTip(STRINGS["tip_settings_watch_add"])
        btn_remove = QPushButton(STRINGS["settings_watch_btn_remove"])
        btn_remove.setToolTip(STRINGS["tip_settings_watch_remove"])
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        def _add_folder():
            from PyQt6.QtWidgets import QFileDialog, QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
            path = QFileDialog.getExistingDirectory(self, STRINGS["settings_watch_btn_add"])
            if not path:
                return
            # Deduplicate
            existing = [self._watch_list.item(i).text()
                        for i in range(self._watch_list.count())]
            if path in existing:
                return

            # Check if the folder already contains subtitle files
            from core.subtitle import SUPPORTED_EXTENSIONS as _EXTS
            existing_files = [p for p in Path(path).rglob("*")
                              if p.suffix.lower() in _EXTS]

            if existing_files:
                # Show warning dialog
                from gui.settings_dialog import load_default_sensitivity
                sensitivity = load_default_sensitivity()
                sensitivity_labels = {1: "Very Aggressive", 2: "Aggressive",
                                      3: "Balanced", 4: "Conservative",
                                      5: "Very Conservative"}
                sens_label = sensitivity_labels.get(sensitivity, str(sensitivity))

                warn_dlg = QDialog(self)
                warn_dlg.setWindowTitle(STRINGS["settings_watch_warn_title"])
                warn_dlg.setMinimumWidth(480)
                warn_layout = QVBoxLayout(warn_dlg)
                warn_layout.setContentsMargins(20, 20, 20, 20)
                warn_layout.setSpacing(12)

                lbl = QLabel(STRINGS["settings_watch_warn_msg"].format(
                    folder=path, sensitivity=sens_label
                ))
                lbl.setWordWrap(True)
                lbl.setStyleSheet(f"color: {FG}; font-size: {get_font_pt()}pt;")
                warn_layout.addWidget(lbl)

                file_count_lbl = QLabel(
                    f"{len(existing_files)} subtitle file(s) found in this folder."
                )
                file_count_lbl.setStyleSheet(f"color: {ORANGE}; font-size: {get_font_pt()}pt;")
                warn_layout.addWidget(file_count_lbl)

                btn_row = QHBoxLayout()
                btn_row.addStretch()
                btn_cancel_warn = QPushButton("Cancel")
                btn_confirm = QPushButton(STRINGS["settings_watch_warn_confirm"])
                btn_confirm.setObjectName("btn_settings_warn")
                btn_confirm.setDefault(True)
                btn_row.addWidget(btn_cancel_warn)
                btn_row.addWidget(btn_confirm)
                warn_layout.addLayout(btn_row)

                btn_cancel_warn.clicked.connect(warn_dlg.reject)
                btn_confirm.clicked.connect(warn_dlg.accept)

                if warn_dlg.exec() != QDialog.DialogCode.Accepted:
                    return

                # User confirmed — add folder and immediately clean existing files
                self._watch_list.addItem(path)
                self._watch_list.setVisible(True)
                self._watch_empty_lbl.setVisible(False)

                # Trigger immediate recursive clean of existing files if
                # watcher_mgr is available (it is when opened from the main app)
                if self._watcher_mgr is not None:
                    self._watcher_mgr.clean_existing_recursive(path)
            else:
                # No existing files — just add silently
                self._watch_list.addItem(path)
                self._watch_list.setVisible(True)
                self._watch_empty_lbl.setVisible(False)

        def _remove_folder():
            row = self._watch_list.currentRow()
            if row < 0:
                return
            self._watch_list.takeItem(row)
            if self._watch_list.count() == 0:
                self._watch_list.setVisible(False)
                self._watch_empty_lbl.setVisible(True)

        btn_add.clicked.connect(_add_folder)
        btn_remove.clicked.connect(_remove_folder)

        self._tabs.addTab(tab, STRINGS["settings_tab_watch"])

    # ── Scheduler tab ─────────────────────────────────────────────────────

    def _build_scheduler_tab(self):
        from core.scheduler import load_schedules
        from PyQt6.QtWidgets import (QListWidget, QListWidgetItem, QRadioButton,
                                      QButtonGroup, QDialog, QFormLayout,
                                      QDialogButtonBox, QFileDialog, QSpinBox)
        from PyQt6.QtCore import Qt as _Qt

        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        intro = QLabel(STRINGS["settings_sched_intro"])
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")
        outer.addWidget(intro)

        # Schedule list
        self._sched_list = QListWidget()
        self._sched_list.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; font-size: {get_font_pt()}pt;"
        )
        self._sched_list.setSelectionMode(
            self._sched_list.SelectionMode.SingleSelection
        )
        outer.addWidget(self._sched_list, stretch=1)

        self._sched_empty_lbl = QLabel(STRINGS["settings_sched_empty"])
        self._sched_empty_lbl.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")
        self._sched_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._sched_empty_lbl)

        # Populate from saved schedules
        saved = load_schedules()
        for sc in saved:
            last = sc.last_run[:16].replace("T", " ") if sc.last_run else STRINGS["settings_sched_never"]
            item_text = (f"{sc.folder}    [{sc.display_label()}]    "
                         f"{STRINGS['settings_sched_lbl_last_run']} {last}")
            item = QListWidgetItem(item_text)
            item.setData(_Qt.ItemDataRole.UserRole, sc)
            self._sched_list.addItem(item)

        self._sched_empty_lbl.setVisible(self._sched_list.count() == 0)
        self._sched_list.setVisible(self._sched_list.count() > 0)

        # Button row
        btn_row = QHBoxLayout()
        btn_add = QPushButton(STRINGS["settings_sched_btn_add"])
        btn_add.setToolTip(STRINGS["tip_settings_sched_add"])
        btn_remove = QPushButton(STRINGS["settings_sched_btn_remove"])
        btn_remove.setToolTip(STRINGS["tip_settings_sched_remove"])
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        def _add_schedule():
            from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
                                          QDialogButtonBox, QFileDialog,
                                          QHBoxLayout, QRadioButton,
                                          QButtonGroup, QSpinBox, QLabel,
                                          QWidget, QLineEdit, QSizePolicy)
            from core.scheduler import ScheduleConfig
            from PyQt6.QtCore import Qt as _Qt

            dlg = QDialog(self)
            dlg.setWindowTitle(STRINGS["settings_sched_btn_add"])
            dlg.setMinimumWidth(460)
            layout = QVBoxLayout(dlg)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(10)

            # ── Folder picker ─────────────────────────────────────────────
            folder_form = QFormLayout()
            folder_row = QHBoxLayout()
            folder_edit = QLineEdit()
            folder_edit.setPlaceholderText("/path/to/folder")
            btn_browse = QPushButton(STRINGS["settings_browse"])
            btn_browse.clicked.connect(lambda: (
                folder_edit.setText(p) if (p := QFileDialog.getExistingDirectory(
                    dlg, STRINGS["settings_sched_lbl_folder"])) else None
            ))
            folder_row.addWidget(folder_edit, stretch=1)
            folder_row.addWidget(btn_browse)
            folder_form.addRow(STRINGS["settings_sched_lbl_folder"], folder_row)
            layout.addLayout(folder_form)

            # ── Interval type — three radio rows ──────────────────────────
            interval_lbl = QLabel(STRINGS["settings_sched_lbl_interval"])
            interval_lbl.setStyleSheet(f"color: {FG}; font-size: {get_font_pt()}pt;")
            layout.addWidget(interval_lbl)

            # Wrap all three rows in a tight sub-layout so they sit flush
            radio_widget = QWidget()
            radio_container = QVBoxLayout(radio_widget)
            radio_container.setSpacing(4)
            radio_container.setContentsMargins(4, 0, 0, 0)

            grp = QButtonGroup(dlg)

            SPIN_W = 90  # wide enough for 4-digit numbers without clipping

            # Minutes row
            row_min = QHBoxLayout()
            row_min.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            radio_min = QRadioButton("Minutes")
            spin_min = QSpinBox()
            spin_min.setMinimum(1); spin_min.setMaximum(9999); spin_min.setValue(30)
            spin_min.setFixedWidth(SPIN_W)
            row_min.addWidget(radio_min)
            row_min.addWidget(spin_min)
            row_min.addStretch()

            # Hours row
            row_hr = QHBoxLayout()
            row_hr.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            radio_hr = QRadioButton("Hours")
            spin_hr = QSpinBox()
            spin_hr.setMinimum(1); spin_hr.setMaximum(9999); spin_hr.setValue(1)
            spin_hr.setFixedWidth(SPIN_W)
            row_hr.addWidget(radio_hr)
            row_hr.addWidget(spin_hr)
            row_hr.addStretch()

            # Days row
            row_day = QHBoxLayout()
            row_day.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            radio_day = QRadioButton("Days  at")
            spin_day = QSpinBox()
            spin_day.setMinimum(1); spin_day.setMaximum(9999); spin_day.setValue(1)
            spin_day.setFixedWidth(SPIN_W)
            time_edit = QLineEdit()
            time_edit.setPlaceholderText("02:00")
            time_edit.setFixedWidth(65)
            time_edit.setText("02:00")
            hint_lbl = QLabel(STRINGS["settings_sched_lbl_time_hint"])
            hint_lbl.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt_small()}pt;")
            row_day.addWidget(radio_day)
            row_day.addWidget(spin_day)
            row_day.addWidget(time_edit)
            row_day.addWidget(hint_lbl)
            row_day.addStretch()

            grp.addButton(radio_min)
            grp.addButton(radio_hr)
            grp.addButton(radio_day)
            radio_hr.setChecked(True)   # default: every 1 hour

            radio_container.addLayout(row_min)
            radio_container.addLayout(row_hr)
            radio_container.addLayout(row_day)
            layout.addWidget(radio_widget)

            # Error label
            lbl_error = QLabel()
            lbl_error.setStyleSheet(f"color: {RED};")
            lbl_error.setVisible(False)
            layout.addWidget(lbl_error)

            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok |
                QDialogButtonBox.StandardButton.Cancel
            )
            layout.addWidget(buttons)

            def _accept():
                lbl_error.setVisible(False)
                folder = folder_edit.text().strip()
                if not folder:
                    lbl_error.setText(STRINGS["settings_sched_lbl_folder"] + " required.")
                    lbl_error.setVisible(True)
                    return

                if radio_min.isChecked():
                    itype, ival, tod = "minutes", spin_min.value(), ""
                elif radio_hr.isChecked():
                    itype, ival, tod = "hours", spin_hr.value(), ""
                else:
                    itype, ival = "days", spin_day.value()
                    tod = time_edit.text().strip() if time_edit else ""
                    # Validate HH:MM
                    import re as _re
                    if tod and not _re.match(r"^\d{1,2}:\d{2}$", tod):
                        lbl_error.setText(STRINGS["settings_sched_invalid_time"])
                        lbl_error.setVisible(True)
                        return
                    # Normalise to HH:MM
                    if tod:
                        try:
                            hh, mm = tod.split(":")
                            tod = f"{int(hh):02d}:{int(mm):02d}"
                        except ValueError:
                            lbl_error.setText(STRINGS["settings_sched_invalid_time"])
                            lbl_error.setVisible(True)
                            return

                sc = ScheduleConfig(
                    folder=folder,
                    interval_type=itype,
                    interval_value=ival,
                    time_of_day=tod,
                )
                last = STRINGS["settings_sched_never"]
                item_text = (f"{folder}    [{sc.display_label()}]    "
                             f"{STRINGS['settings_sched_lbl_last_run']} {last}")
                item = QListWidgetItem(item_text)
                item.setData(_Qt.ItemDataRole.UserRole, sc)
                self._sched_list.addItem(item)
                self._sched_list.setVisible(True)
                self._sched_empty_lbl.setVisible(False)
                dlg.accept()

            buttons.button(QDialogButtonBox.StandardButton.Ok).clicked.connect(_accept)
            buttons.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(dlg.reject)
            dlg.exec()

        def _remove_schedule():
            row = self._sched_list.currentRow()
            if row < 0:
                return
            self._sched_list.takeItem(row)
            if self._sched_list.count() == 0:
                self._sched_list.setVisible(False)
                self._sched_empty_lbl.setVisible(True)

        btn_add.clicked.connect(_add_schedule)
        btn_remove.clicked.connect(_remove_schedule)

        self._tabs.addTab(tab, STRINGS["settings_tab_scheduler"])

    # ── Paths tab ────────────────────────────────────────────────────────

    def _show_changelog(self):
        from gui.changelog_dialog import ChangelogDialog
        dlg = ChangelogDialog(self)
        dlg.exec()

    def _show_error_log(self):
        from core.logger import read_log, clear_log, get_log_path
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(STRINGS["settings_log_title"])
        dlg.resize(700, 480)
        dlg.setStyleSheet(f"background: {BG}; color: {FG};")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Path label
        lbl_path = QLabel(str(get_log_path()))
        lbl_path.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt_small()}pt; font-family: Consolas, monospace;")
        lbl_path.setWordWrap(True)
        layout.addWidget(lbl_path)

        # Log content
        log_text = read_log()
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setStyleSheet(
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; font-family: Consolas, monospace; font-size: {get_font_pt_small()}pt;"
        )
        txt.setPlainText(log_text if log_text else STRINGS["settings_log_empty"])
        layout.addWidget(txt, stretch=1)

        # Button row
        btn_row = QHBoxLayout()
        btn_clear = QPushButton(STRINGS["settings_log_clear"])
        btn_close = QPushButton(STRINGS["settings_btn_cancel"])

        def _clear():
            clear_log()
            txt.setPlainText(STRINGS["settings_log_empty"])
            btn_clear.setEnabled(False)

        btn_clear.clicked.connect(_clear)
        btn_clear.setEnabled(bool(log_text))
        btn_close.clicked.connect(dlg.accept)

        btn_row.addStretch()
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        dlg.exec()

    def _open_data_folder(self):
        from core.paths import USER_DIR
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(USER_DIR)))

    def _build_paths_tab(self):
        from core.ffprobe import get_ffmpeg_path, get_ffprobe_path, ffmpeg_available, ffprobe_available
        from core.ocr import get_tesseract_path, tesseract_available

        tab = QWidget()
        tab.setStyleSheet(f"background: {BG};")

        # Scrollable so all groups fit on small screens — vertical only
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background: {BG};")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner_widget = QWidget()
        inner_widget.setStyleSheet(f"background: {BG};")
        outer = QVBoxLayout(inner_widget)
        outer.setContentsMargins(16, 16, 16, 8)
        outer.setSpacing(16)

        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        scroll.setWidget(inner_widget)

        _grp_style = (
            f"QGroupBox {{ border: 1px solid {BORDER}; border-radius: 4px; "
            f"color: {FG2}; margin-top: 8px; padding-top: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        _input_style = (
            f"background: {BG2}; color: {FG}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 4px;"
        )

        def _make_path_group(title, info_text, placeholder, current_val, browse_fn):
            """Build a standard tool path group. Returns (grp, input, status_lbl)."""
            from PyQt6.QtWidgets import QSizePolicy
            grp = QGroupBox(title)
            grp.setStyleSheet(_grp_style)
            gl = QVBoxLayout(grp)
            info = QLabel(info_text)
            info.setWordWrap(True)
            info.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")
            path_row = QHBoxLayout()
            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setStyleSheet(_input_style)
            if current_val:
                inp.setText(current_val)
            btn = QPushButton(STRINGS["settings_browse"])
            btn.setToolTip(STRINGS["tip_settings_browse"])
            btn.clicked.connect(browse_fn)
            path_row.addWidget(inp, stretch=1)
            path_row.addWidget(btn)
            lbl = QLabel("")
            lbl.setWordWrap(True)
            lbl.setStyleSheet("font-size: {get_font_pt()}pt;")
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            gl.addWidget(info)
            gl.addLayout(path_row)
            gl.addWidget(lbl)
            return grp, inp, lbl

        # ── MKVToolNix ────────────────────────────────────────────────────
        grp, self._mkv_path_input, self._lbl_mkv_status = _make_path_group(
            STRINGS["settings_grp_mkv"],
            STRINGS["settings_mkv_info"],
            STRINGS["settings_mkv_placeholder"],
            get_mkvmerge_path() or "",
            self._browse_mkvmerge,
        )
        outer.addWidget(grp)
        self._mkv_path_input.textChanged.connect(self._update_mkv_status)
        self._update_mkv_status()

        # ── FFmpeg ────────────────────────────────────────────────────────
        grp, self._ffmpeg_path_input, self._lbl_ffmpeg_status = _make_path_group(
            STRINGS["settings_grp_ffmpeg"],
            STRINGS["settings_ffmpeg_info"],
            STRINGS["settings_ffmpeg_placeholder"],
            get_ffmpeg_path() or "",
            self._browse_ffmpeg,
        )
        outer.addWidget(grp)
        self._ffmpeg_path_input.textChanged.connect(self._update_ffmpeg_status)
        self._update_ffmpeg_status()

        # ── FFprobe ───────────────────────────────────────────────────────
        grp, self._ffprobe_path_input, self._lbl_ffprobe_status = _make_path_group(
            STRINGS["settings_grp_ffprobe"],
            STRINGS["settings_ffprobe_info"],
            STRINGS["settings_ffprobe_placeholder"],
            get_ffprobe_path() or "",
            self._browse_ffprobe,
        )
        outer.addWidget(grp)
        self._ffprobe_path_input.textChanged.connect(self._update_ffprobe_status)
        self._update_ffprobe_status()

        # ── Tesseract OCR ─────────────────────────────────────────────────
        grp, self._tess_path_input, self._lbl_tess_status = _make_path_group(
            STRINGS["settings_grp_tesseract"],
            STRINGS["settings_tesseract_info"],
            STRINGS["settings_tesseract_placeholder"],
            get_tesseract_path() or "",
            self._browse_tesseract,
        )
        outer.addWidget(grp)
        self._tess_path_input.textChanged.connect(self._update_tess_status)
        self._update_tess_status()

        # ── Whisper Model Directory ───────────────────────────────────────
        from core.paths import USER_DIR
        _default_whisper = USER_DIR / "whisper_models"
        _current_whisper = get_model_dir()
        _whisper_display = str(_current_whisper) if _current_whisper != _default_whisper else ""

        wgrp = QGroupBox(STRINGS["settings_grp_whisper"])
        wgrp.setStyleSheet(_grp_style)
        wgl = QVBoxLayout(wgrp)
        winfo = QLabel(STRINGS["settings_whisper_info"])
        winfo.setWordWrap(True)
        winfo.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")
        wpath_row = QHBoxLayout()
        self._whisper_dir_input = QLineEdit()
        self._whisper_dir_input.setPlaceholderText(STRINGS["settings_whisper_placeholder"])
        self._whisper_dir_input.setStyleSheet(_input_style)
        if _whisper_display:
            self._whisper_dir_input.setText(_whisper_display)
        btn_browse_whisper = QPushButton(STRINGS["settings_browse"])
        btn_browse_whisper.setToolTip(STRINGS["tip_settings_browse"])
        btn_browse_whisper.clicked.connect(self._browse_whisper_dir)
        wpath_row.addWidget(self._whisper_dir_input, stretch=1)
        wpath_row.addWidget(btn_browse_whisper)
        self._lbl_whisper_status = QLabel("")
        self._lbl_whisper_status.setWordWrap(True)
        self._lbl_whisper_status.setStyleSheet("font-size: {get_font_pt()}pt;")
        wgl.addWidget(winfo)
        wgl.addLayout(wpath_row)
        wgl.addWidget(self._lbl_whisper_status)
        outer.addWidget(wgrp)
        self._whisper_dir_input.textChanged.connect(self._update_whisper_status)
        self._update_whisper_status()

        outer.addStretch()
        self._tabs.addTab(tab, STRINGS["settings_tab_paths"])

    def _browse_mkvmerge(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Find mkvmerge", "",
            "mkvmerge (mkvmerge mkvmerge.exe);;All Files (*)"
        )
        if path:
            self._mkv_path_input.setText(path)

    def _update_mkv_status(self):
        path = self._mkv_path_input.text().strip()
        if path and Path(path).is_file():
            self._lbl_mkv_status.setText(STRINGS["settings_mkv_found"])
            self._lbl_mkv_status.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt()}pt;")
        elif path:
            self._lbl_mkv_status.setText(STRINGS["settings_mkv_not_found"])
            self._lbl_mkv_status.setStyleSheet(f"color: {RED}; font-size: {get_font_pt()}pt;")
        elif mkvmerge_available():
            self._lbl_mkv_status.setText(
                STRINGS["settings_mkv_on_path"].format(path=get_mkvmerge_path())
            )
            self._lbl_mkv_status.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt()}pt;")
        else:
            self._lbl_mkv_status.setText(STRINGS["settings_mkv_missing"])
            self._lbl_mkv_status.setStyleSheet(f"color: {ORANGE}; font-size: {get_font_pt()}pt;")

    def _browse_ffmpeg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Find ffmpeg", "",
            "ffmpeg (ffmpeg ffmpeg.exe);;All Files (*)"
        )
        if path:
            self._ffmpeg_path_input.setText(path)

    def _update_ffmpeg_status(self):
        from core.ffprobe import get_ffmpeg_path, ffmpeg_available, set_ffmpeg_path
        path = self._ffmpeg_path_input.text().strip()
        if path and Path(path).is_file():
            self._lbl_ffmpeg_status.setText(STRINGS["settings_tool_found"])
            self._lbl_ffmpeg_status.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt()}pt;")
        elif path:
            self._lbl_ffmpeg_status.setText(STRINGS["settings_tool_not_found"])
            self._lbl_ffmpeg_status.setStyleSheet(f"color: {RED}; font-size: {get_font_pt()}pt;")
        elif ffmpeg_available():
            self._lbl_ffmpeg_status.setText(
                STRINGS["settings_tool_on_path"].format(path=get_ffmpeg_path())
            )
            self._lbl_ffmpeg_status.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt()}pt;")
        else:
            self._lbl_ffmpeg_status.setText(STRINGS["settings_tool_missing_ffmpeg"])
            self._lbl_ffmpeg_status.setStyleSheet(f"color: {ORANGE}; font-size: {get_font_pt()}pt;")

    def _browse_ffprobe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Find ffprobe", "",
            "ffprobe (ffprobe ffprobe.exe);;All Files (*)"
        )
        if path:
            self._ffprobe_path_input.setText(path)

    def _update_ffprobe_status(self):
        from core.ffprobe import get_ffprobe_path, ffprobe_available
        path = self._ffprobe_path_input.text().strip()
        if path and Path(path).is_file():
            self._lbl_ffprobe_status.setText(STRINGS["settings_tool_found"])
            self._lbl_ffprobe_status.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt()}pt;")
        elif path:
            self._lbl_ffprobe_status.setText(STRINGS["settings_tool_not_found"])
            self._lbl_ffprobe_status.setStyleSheet(f"color: {RED}; font-size: {get_font_pt()}pt;")
        elif ffprobe_available():
            self._lbl_ffprobe_status.setText(
                STRINGS["settings_tool_on_path"].format(path=get_ffprobe_path())
            )
            self._lbl_ffprobe_status.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt()}pt;")
        else:
            self._lbl_ffprobe_status.setText(STRINGS["settings_tool_missing_ffprobe"])
            self._lbl_ffprobe_status.setStyleSheet(f"color: {ORANGE}; font-size: {get_font_pt()}pt;")

    def _browse_tesseract(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Find Tesseract", "",
            "Tesseract (tesseract tesseract.exe);;All Files (*)"
        )
        if path:
            self._tess_path_input.setText(path)

    def _update_tess_status(self):
        from core.ocr import get_tesseract_path, tesseract_available, set_tesseract_path
        path = self._tess_path_input.text().strip()
        if path and Path(path).is_file():
            self._lbl_tess_status.setText(STRINGS["settings_tool_found"])
            self._lbl_tess_status.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt()}pt;")
        elif path:
            self._lbl_tess_status.setText(STRINGS["settings_tool_not_found"])
            self._lbl_tess_status.setStyleSheet(f"color: {RED}; font-size: {get_font_pt()}pt;")
        elif tesseract_available():
            self._lbl_tess_status.setText(
                STRINGS["settings_tool_on_path"].format(path=get_tesseract_path())
            )
            self._lbl_tess_status.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt()}pt;")
        else:
            self._lbl_tess_status.setText(STRINGS["settings_tesseract_missing"])
            self._lbl_tess_status.setStyleSheet(f"color: {ORANGE}; font-size: {get_font_pt()}pt;")

    def _browse_whisper_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Whisper Model Directory", ""
        )
        if path:
            self._whisper_dir_input.setText(path)

    def _update_whisper_status(self):
        from core.paths import USER_DIR
        from core.whisper import faster_whisper_available
        _default  = USER_DIR / "whisper_models"
        path_text = self._whisper_dir_input.text().strip()

        # faster-whisper not installed takes priority over path state
        if not faster_whisper_available():
            suffix = "  Install with: pip install faster-whisper"
            if path_text:
                p = Path(path_text)
                if p.is_dir():
                    self._lbl_whisper_status.setText(
                        STRINGS["settings_whisper_custom"].format(path=path_text) + suffix
                    )
                else:
                    self._lbl_whisper_status.setText(
                        STRINGS["settings_whisper_not_found"] + suffix
                    )
            else:
                self._lbl_whisper_status.setText(
                    STRINGS["settings_whisper_default"].format(path=str(_default)) + suffix
                )
            self._lbl_whisper_status.setStyleSheet(f"color: {ORANGE}; font-size: {get_font_pt()}pt;")
            return

        if path_text:
            p = Path(path_text)
            if p.is_dir():
                self._lbl_whisper_status.setText(
                    STRINGS["settings_whisper_custom"].format(path=path_text)
                )
                self._lbl_whisper_status.setStyleSheet(f"color: {GREEN}; font-size: {get_font_pt()}pt;")
            else:
                self._lbl_whisper_status.setText(STRINGS["settings_whisper_not_found"])
                self._lbl_whisper_status.setStyleSheet(f"color: {RED}; font-size: {get_font_pt()}pt;")
        else:
            self._lbl_whisper_status.setText(
                STRINGS["settings_whisper_default"].format(path=str(_default))
            )
            self._lbl_whisper_status.setStyleSheet(f"color: {FG2}; font-size: {get_font_pt()}pt;")

    # ── Load / Save ───────────────────────────────────────────────────────

    def _load_current_values(self):
        self._sens_slider.setValue(load_default_sensitivity())
        current_font = load_font_size()
        if current_font in self._font_size_names:
            self._font_combo.setCurrentIndex(self._font_size_names.index(current_font))
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

        from core.ffprobe import set_ffmpeg_path, set_ffprobe_path
        from core.ocr import set_tesseract_path

        ffmpeg_path = self._ffmpeg_path_input.text().strip()
        if ffmpeg_path:
            set_ffmpeg_path(ffmpeg_path)

        ffprobe_path = self._ffprobe_path_input.text().strip()
        if ffprobe_path:
            set_ffprobe_path(ffprobe_path)

        tess_path = self._tess_path_input.text().strip()
        if tess_path:
            set_tesseract_path(tess_path)

        whisper_dir = self._whisper_dir_input.text().strip()
        if whisper_dir:
            set_model_dir(whisper_dir)
        else:
            clear_model_dir()

        # Save theme
        selected_theme = self._theme_names[self._theme_combo.currentIndex()]
        prev_theme = get_theme()
        from .colors import save_theme as _save_theme
        _save_theme(selected_theme)

        # Save font size
        selected_font = self._font_size_names[self._font_combo.currentIndex()]
        prev_font = load_font_size()
        save_font_size(selected_font)

        # Save watch folders
        from core.watcher import save_watch_folders
        watch_folders = [
            self._watch_list.item(i).text()
            for i in range(self._watch_list.count())
        ]
        save_watch_folders(watch_folders)

        # Save schedules
        from core.scheduler import save_schedules, ScheduleConfig
        from PyQt6.QtCore import Qt as _Qt
        schedules = []
        for i in range(self._sched_list.count()):
            sc = self._sched_list.item(i).data(_Qt.ItemDataRole.UserRole)
            if isinstance(sc, ScheduleConfig):
                schedules.append(sc)
        save_schedules(schedules)

        self.accept()

        # Offer restart if language, theme, or font size changed
        need_restart = (lang_code != prev_lang) or (selected_theme != prev_theme) or (selected_font != prev_font)
        if need_restart:
            import sys, subprocess
            from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel,
                                         QHBoxLayout, QPushButton, QApplication)
            dlg = QDialog(None)
            dlg.setWindowTitle(STRINGS["settings_btn_restart"])
            dlg.setMinimumWidth(360)
            _layout = QVBoxLayout(dlg)
            _layout.setSpacing(16)
            _layout.setContentsMargins(20, 20, 20, 20)
            _lbl = QLabel(STRINGS["settings_restart_required"])
            _lbl.setWordWrap(True)
            _layout.addWidget(_lbl)
            _btn_row = QHBoxLayout()
            _btn_row.addStretch()
            _btn_later = QPushButton(STRINGS["settings_btn_restart_later"])
            _btn_now   = QPushButton(STRINGS["settings_btn_restart"])
            _btn_now.setDefault(True)
            _btn_later.clicked.connect(dlg.reject)
            _btn_now.clicked.connect(dlg.accept)
            _btn_row.addWidget(_btn_later)
            _btn_row.addWidget(_btn_now)
            _layout.addLayout(_btn_row)
            want_restart = dlg.exec() == QDialog.DialogCode.Accepted
            if want_restart:
                frozen = getattr(sys, "frozen", False)
                args = [sys.executable] if frozen else [sys.executable] + sys.argv

                creationflags = 0
                if sys.platform == "win32":
                    DETACHED_PROCESS    = 0x00000008
                    CREATE_NEW_PROCESS_GROUP = 0x00000200
                    creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

                subprocess.Popen(args, close_fds=True, creationflags=creationflags)
                import io
                sys.stderr = io.StringIO()
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
    data = dict(_load_settings())
    data["last_batch_folder"] = last_batch_folder
    data["last_video_folder"] = last_video_folder
    data["window_geometry"]   = window_geometry
    _save_settings(data)
