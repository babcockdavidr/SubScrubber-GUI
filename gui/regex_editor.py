"""
Regex Profile Editor
====================
GUI panel for viewing, editing, adding, and deleting regex patterns
across all loaded .conf profile files.

Also provides:
  - AddPatternDialog: the "Always Mark as Ad" workflow — takes a subtitle
    block's text, proposes a smart regex, lets the user edit it, choose
    the target profile and level (PURGE/WARNING), then saves and hot-reloads.
  - reload_engine(): hot-reloads the cleaner's pattern tables without restart.
"""
from __future__ import annotations

import configparser
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QSplitter,
    QDialog, QDialogButtonBox, QComboBox, QLineEdit,
    QRadioButton, QButtonGroup, QFrame, QMessageBox,
    QAbstractItemView, QGroupBox,
)

import sys
# sys.path managed by subforge.py entry point — do not insert __file__-relative paths here

from .colors import BG, BG2, BG3, BORDER, FG, FG2, ACCENT, RED, ORANGE, GREEN, YELLOW
from .strings import STRINGS

from core.paths import list_profile_dirs, ensure_user_profiles_dir, USER_PROFILES_DIR


# ---------------------------------------------------------------------------
# Hot-reload the cleaner engine
# ---------------------------------------------------------------------------

def reload_engine() -> None:
    """Clear and re-run the profile loader in core.cleaner."""
    import core.cleaner as eng
    eng._purge_regex.clear()
    eng._warning_regex.clear()
    eng._global_purge.clear()
    eng._global_warning.clear()
    eng._global_excluded.clear()
    eng._load_profiles()


# ---------------------------------------------------------------------------
# Profile file helpers
# ---------------------------------------------------------------------------

def list_profiles() -> List[Path]:
    profiles = []
    seen = set()
    for d in list_profile_dirs():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix == ".conf" and p.name not in seen:
                seen.add(p.name)
                profiles.append(p)
    return profiles


def read_profile(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    return parser


def write_profile(path: Path, parser: configparser.ConfigParser) -> None:
    with open(path, "w", encoding="utf-8") as f:
        parser.write(f)


def next_key(parser: configparser.ConfigParser, section: str, prefix: str) -> str:
    """Generate the next available key like en_purge7, global_warn3 etc."""
    existing = set(parser[section].keys()) if section in parser else set()
    i = 1
    while True:
        key = f"{prefix}{i}"
        if key not in existing:
            return key
        i += 1


def profile_display_name(path: Path) -> str:
    parser = read_profile(path)
    lang = parser["META"].get("language_codes", "").strip() if "META" in parser else ""
    excl = parser["META"].get("excluded_language_codes", "").strip() if "META" in parser else ""
    if excl:
        return f"{path.stem}  [global, excl: {excl}]"
    if not lang:
        return f"{path.stem}  [global]"
    return f"{path.stem}  [{lang}]"


# ---------------------------------------------------------------------------
# Smart regex generator
# ---------------------------------------------------------------------------

def suggest_regex(text: str) -> str:
    """
    Given raw subtitle block text, propose a useful regex pattern.

    Strategy:
      1. If it looks like a URL/domain → extract and escape the domain
      2. If it contains a proper noun (Capitalised word >= 4 chars not at
         sentence start) → wrap it in \\b word boundary
      3. Otherwise → escape the whole line and wrap in \\b..\\b
    """
    text = text.strip().replace("\n", " ")

    # URL / domain
    url_match = re.search(r'(https?://|www\.)\S+', text, re.IGNORECASE)
    if url_match:
        domain = re.sub(r'https?://', '', url_match.group())
        domain = domain.split('/')[0]
        return re.escape(domain)

    bare_domain = re.search(
        r'\b([a-z0-9\-]{3,})\.(com|net|org|tv|io|xyz|info|app)\b',
        text, re.IGNORECASE)
    if bare_domain:
        return re.escape(bare_domain.group())

    # Proper nouns — capitalised words >= 4 chars that aren't the first word
    words = text.split()
    proper = [w for w in words[1:] if len(w) >= 4 and w[0].isupper()
              and w.isalpha()]
    if proper:
        # Use the longest one
        noun = max(proper, key=len)
        return rf"\b{re.escape(noun)}\b"

    # Full line escape, trimmed to 60 chars
    trimmed = text[:60].rstrip()
    return rf"\b{re.escape(trimmed)}\b"


# ---------------------------------------------------------------------------
# Regex syntax highlighter for the editor pane
# ---------------------------------------------------------------------------

class RegexHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self._key_fmt = QTextCharFormat()
        self._key_fmt.setForeground(QColor(ACCENT))

        self._val_fmt = QTextCharFormat()
        self._val_fmt.setForeground(QColor(GREEN))

        self._comment_fmt = QTextCharFormat()
        self._comment_fmt.setForeground(QColor(FG2))

        self._section_fmt = QTextCharFormat()
        self._section_fmt.setForeground(QColor(YELLOW))
        self._section_fmt.setFontWeight(700)

    def highlightBlock(self, text: str):
        stripped = text.strip()
        if stripped.startswith("#"):
            self.setFormat(0, len(text), self._comment_fmt)
        elif stripped.startswith("[") and stripped.endswith("]"):
            self.setFormat(0, len(text), self._section_fmt)
        elif "=" in text or ":" in text:
            sep = text.find("=") if "=" in text else text.find(":")
            self.setFormat(0, sep, self._key_fmt)
            self.setFormat(sep + 1, len(text) - sep - 1, self._val_fmt)


# ---------------------------------------------------------------------------
# Add Pattern Dialog  ("Always Mark as Ad" workflow)
# ---------------------------------------------------------------------------

class AddPatternDialog(QDialog):
    """
    Shown when the user clicks "Always Mark as Ad".
    Proposes a regex, lets the user edit it, pick a profile and level,
    then saves and hot-reloads.
    """

    def __init__(self, block_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(STRINGS["addpattern_title"])
        self.setMinimumWidth(620)
        self.setMinimumHeight(420)
        self.setStyleSheet(f"""
            QDialog {{ background: {BG}; color: {FG}; }}
            QLineEdit, QTextEdit {{
                background: {BG2}; color: {FG}; border: 1px solid {BORDER};
                border-radius: 3px; padding: 4px;
            }}
            QComboBox {{
                background: {BG2}; color: {FG}; border: 1px solid {BORDER};
                border-radius: 3px; padding: 4px;
            }}
            QComboBox QAbstractItemView {{ background: {BG2}; color: {FG}; }}
            QRadioButton {{ color: {FG}; spacing: 6px; }}
            QRadioButton::indicator {{ width: 14px; height: 14px;
                border: 1px solid {BORDER}; border-radius: 7px; background: {BG3}; }}
            QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
            QPushButton {{
                background: {BG3}; color: {FG}; border: 1px solid {BORDER};
                border-radius: 4px; padding: 5px 14px;
            }}
            QPushButton:hover {{ background: {ACCENT}22; border-color: {ACCENT}; }}
            QGroupBox {{
                border: 1px solid {BORDER}; border-radius: 4px;
                margin-top: 8px; color: {FG2}; padding-top: 6px;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
        """)

        self._saved = False
        self._block_text = block_text
        self._suggested = suggest_regex(block_text)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── Original text ──────────────────────────────────────────────
        grp_orig = QGroupBox(STRINGS["addpattern_grp_orig"])
        gl = QVBoxLayout(grp_orig)
        self._orig_text = QTextEdit()
        self._orig_text.setPlainText(block_text)
        self._orig_text.setReadOnly(True)
        self._orig_text.setMaximumHeight(80)
        self._orig_text.setStyleSheet(f"color: {ORANGE};")
        gl.addWidget(self._orig_text)
        layout.addWidget(grp_orig)

        # ── Regex input ────────────────────────────────────────────────
        grp_regex = QGroupBox(STRINGS["addpattern_grp_regex"])
        rl = QVBoxLayout(grp_regex)

        hint = QLabel(STRINGS["addpattern_hint"])
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {FG2}; font-size: 9pt;")

        self._regex_input = QLineEdit()
        self._regex_input.setText(self._suggested)
        self._regex_input.setFont(QFont("Consolas", 12))

        self._lbl_valid = QLabel("")
        self._lbl_valid.setFont(QFont("Consolas", 11))

        self._regex_input.textChanged.connect(self._validate_regex)

        rl.addWidget(hint)
        rl.addWidget(self._regex_input)
        rl.addWidget(self._lbl_valid)
        layout.addWidget(grp_regex)

        # ── Profile + level ────────────────────────────────────────────
        settings_row = QHBoxLayout()

        grp_profile = QGroupBox(STRINGS["addpattern_grp_profile"])
        pl = QVBoxLayout(grp_profile)
        self._combo_profile = QComboBox()
        self._profiles: List[Path] = list_profiles()
        for p in self._profiles:
            self._combo_profile.addItem(profile_display_name(p), userData=p)
        # Default to global.conf
        for i, p in enumerate(self._profiles):
            if p.stem == "global":
                self._combo_profile.setCurrentIndex(i)
                break
        pl.addWidget(self._combo_profile)
        settings_row.addWidget(grp_profile, stretch=2)

        grp_level = QGroupBox(STRINGS["addpattern_grp_level"])
        ll2 = QVBoxLayout(grp_level)
        self._radio_purge = QRadioButton(STRINGS["addpattern_purge"])
        self._radio_warn  = QRadioButton(STRINGS["addpattern_warn"])
        self._radio_purge.setChecked(True)
        self._btn_group = QButtonGroup()
        self._btn_group.addButton(self._radio_purge)
        self._btn_group.addButton(self._radio_warn)
        ll2.addWidget(self._radio_purge)
        ll2.addWidget(self._radio_warn)
        settings_row.addWidget(grp_level, stretch=3)

        layout.addLayout(settings_row)

        # ── Test match ─────────────────────────────────────────────────
        self._btn_test = QPushButton(STRINGS["addpattern_btn_test"])
        self._btn_test.clicked.connect(self._test_match)
        layout.addWidget(self._btn_test)

        self._lbl_test_result = QLabel("")
        self._lbl_test_result.setFont(QFont("Consolas", 11))
        self._lbl_test_result.setWordWrap(True)
        layout.addWidget(self._lbl_test_result)

        # ── Buttons ────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._validate_regex(self._suggested)

    def _validate_regex(self, text: str):
        try:
            re.compile(text, re.IGNORECASE)
            self._lbl_valid.setText(STRINGS["regex_valid"])
            self._lbl_valid.setStyleSheet(f"color: {GREEN};")
        except re.error as e:
            self._lbl_valid.setText(f"✕ Invalid: {e}")
            self._lbl_valid.setStyleSheet(f"color: {RED};")

    def _test_match(self):
        pattern = self._regex_input.text().strip()
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            if compiled.search(self._block_text):
                self._lbl_test_result.setText(STRINGS["addpattern_match"])
                self._lbl_test_result.setStyleSheet(f"color: {GREEN};")
            else:
                self._lbl_test_result.setText(STRINGS["addpattern_no_match"])
                self._lbl_test_result.setStyleSheet(f"color: {ORANGE};")
        except re.error as e:
            self._lbl_test_result.setText(STRINGS["addpattern_regex_error"].format(error=e))
            self._lbl_test_result.setStyleSheet(f"color: {RED};")

    def _save(self):
        pattern = self._regex_input.text().strip()
        if not pattern:
            QMessageBox.warning(self, "Empty pattern", "Please enter a regex pattern.")
            return
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            QMessageBox.critical(self, STRINGS["dlg_invalid_regex"], str(e))
            return

        profile_path: Path = self._combo_profile.currentData()
        section = "PURGE_REGEX" if self._radio_purge.isChecked() else "WARNING_REGEX"

        parser = read_profile(profile_path)

        # Ensure sections exist
        if "META" not in parser:
            parser["META"] = {}
        if "PURGE_REGEX" not in parser:
            parser["PURGE_REGEX"] = {}
        if "WARNING_REGEX" not in parser:
            parser["WARNING_REGEX"] = {}

        # Derive key prefix from profile stem + section
        stem = profile_path.stem.split(".")[0]  # e.g. "global", "english"
        kind = "purge" if section == "PURGE_REGEX" else "warn"
        prefix = f"{stem}_{kind}"
        key = next_key(parser, section, prefix)

        parser[section][key] = pattern
        write_profile(profile_path, parser)

        # Hot-reload engine
        try:
            reload_engine()
        except Exception as e:
            QMessageBox.warning(
                self, "Reload warning",
                f"Pattern saved but engine reload failed: {e}\n"
                f"Restart SubForge to apply changes."
            )

        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


# ---------------------------------------------------------------------------
# Regex Editor Panel (full tab)
# ---------------------------------------------------------------------------

class RegexEditorPanel(QWidget):
    """
    Full tab showing all loaded .conf profile files.
    Left: profile list. Right: raw .conf editor with syntax highlighting.
    Supports add pattern, delete selected pattern, save.
    """

    pattern_saved = pyqtSignal()   # emitted after any save so Review tab can re-analyse

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: Optional[Path] = None
        self._dirty = False
        self._build_ui()
        self._load_profile_list()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Top bar ───────────────────────────────────────────────────────
        top = QHBoxLayout()
        lbl = QLabel(
            STRINGS["regex_desc"]
        )
        lbl.setStyleSheet(f"color: {FG2}; font-size: 9pt;")
        self._btn_new_profile = QPushButton(STRINGS["regex_btn_new_profile"])
        self._btn_reload = QPushButton(STRINGS["regex_btn_reload"])
        top.addWidget(lbl, stretch=1)
        top.addWidget(self._btn_new_profile)
        top.addWidget(self._btn_reload)
        root.addLayout(top)

        # ── Splitter ──────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: profile list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        lbl_profiles = QLabel(STRINGS["regex_lbl_profiles"])
        lbl_profiles.setObjectName("section_label")

        self._profile_list = QListWidget()
        self._profile_list.setFont(QFont("Consolas", 11))
        self._profile_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)

        ll.addWidget(lbl_profiles)
        ll.addWidget(self._profile_list, stretch=1)

        # Right: editor
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        lbl_editor = QLabel(STRINGS["regex_lbl_editor"])
        lbl_editor.setObjectName("section_label")

        self._editor = QTextEdit()
        self._editor.setFont(QFont("Consolas", 11))
        self._editor.setPlaceholderText(STRINGS["regex_placeholder"])
        self._highlighter = RegexHighlighter(self._editor.document())

        # Quick-add row
        add_row = QHBoxLayout()
        self._quick_key = QLineEdit()
        self._quick_key.setPlaceholderText(STRINGS["regex_key_placeholder"])
        self._quick_key.setMaximumWidth(160)
        self._quick_key.setFont(QFont("Consolas", 11))

        self._quick_val = QLineEdit()
        self._quick_val.setPlaceholderText(r"regex value (e.g. \bMyWatermark\b)")
        self._quick_val.setFont(QFont("Consolas", 11))

        self._quick_section = QComboBox()
        self._quick_section.addItems(["PURGE_REGEX", "WARNING_REGEX"])
        self._quick_section.setFixedWidth(150)

        self._btn_quick_add = QPushButton(STRINGS["regex_btn_add"])
        self._btn_quick_add.setObjectName("btn_keep")

        add_row.addWidget(self._quick_section)
        add_row.addWidget(self._quick_key)
        add_row.addWidget(QLabel("="))
        add_row.addWidget(self._quick_val, stretch=1)
        add_row.addWidget(self._btn_quick_add)

        # Save / discard row
        save_row = QHBoxLayout()
        self._lbl_dirty = QLabel("")
        self._lbl_dirty.setStyleSheet(f"color: {ORANGE}; font-size: 9pt;")
        self._btn_save = QPushButton(STRINGS["regex_btn_save"])
        self._btn_save.setObjectName("btn_clean_all")
        self._btn_save.setEnabled(False)
        self._btn_discard = QPushButton(STRINGS["regex_btn_discard"])
        self._btn_discard.setObjectName("btn_remove")
        self._btn_discard.setEnabled(False)

        save_row.addWidget(self._lbl_dirty, stretch=1)
        save_row.addWidget(self._btn_discard)
        save_row.addWidget(self._btn_save)

        rl.addWidget(lbl_editor)
        rl.addWidget(self._editor, stretch=1)
        rl.addLayout(add_row)
        rl.addLayout(save_row)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([220, 620])

        root.addWidget(splitter, stretch=1)

        # ── Connect ───────────────────────────────────────────────────────
        self._profile_list.currentRowChanged.connect(self._on_profile_selected)
        self._editor.textChanged.connect(self._on_editor_changed)
        self._btn_save.clicked.connect(self._save_profile)
        self._btn_discard.clicked.connect(self._discard_changes)
        self._btn_quick_add.clicked.connect(self._quick_add)
        self._btn_new_profile.clicked.connect(self._new_profile)
        self._btn_reload.clicked.connect(self._reload)

    # ── Profile list ──────────────────────────────────────────────────────

    def _load_profile_list(self):
        self._profile_list.clear()
        for path in list_profiles():
            item = QListWidgetItem(profile_display_name(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setForeground(QColor(FG))
            self._profile_list.addItem(item)

    def _on_profile_selected(self, row: int):
        if self._dirty:
            ans = QMessageBox.question(
                self, STRINGS["regex_unsaved_title"],
                STRINGS["regex_unsaved_msg"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        if row < 0:
            return
        item = self._profile_list.item(row)
        path: Path = item.data(Qt.ItemDataRole.UserRole)
        self._current_path = path

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, STRINGS["dlg_read_error"], str(e))
            return

        self._editor.blockSignals(True)
        self._editor.setPlainText(text)
        self._editor.blockSignals(False)
        self._dirty = False
        self._btn_save.setEnabled(False)
        self._btn_discard.setEnabled(False)
        self._lbl_dirty.setText("")

    def _on_editor_changed(self):
        if not self._dirty:
            self._dirty = True
            self._btn_save.setEnabled(True)
            self._btn_discard.setEnabled(True)
            self._lbl_dirty.setText(STRINGS["regex_dirty"])

    # ── Save / discard ────────────────────────────────────────────────────

    def _save_profile(self):
        if not self._current_path:
            return
        text = self._editor.toPlainText()

        # Validate it's parseable before writing
        parser = configparser.ConfigParser()
        try:
            parser.read_string(text)
        except configparser.Error as e:
            QMessageBox.critical(self, STRINGS["dlg_invalid_config"], str(e))
            return

        try:
            self._current_path.write_text(text, encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, STRINGS["dlg_write_error_regex"], str(e))
            return

        self._dirty = False
        self._btn_save.setEnabled(False)
        self._btn_discard.setEnabled(False)
        self._lbl_dirty.setText(f"Saved — reloading engine…")

        try:
            reload_engine()
            self._lbl_dirty.setText(STRINGS["regex_saved"])
            self._lbl_dirty.setStyleSheet(f"color: {GREEN}; font-size: 9pt;")
        except Exception as e:
            self._lbl_dirty.setText(f"Saved, but reload failed: {e}")
            self._lbl_dirty.setStyleSheet(f"color: {ORANGE}; font-size: 9pt;")

        self.pattern_saved.emit()

    def _discard_changes(self):
        if self._current_path:
            self._on_profile_selected(self._profile_list.currentRow())
        self._dirty = False
        self._lbl_dirty.setText("")

    # ── Quick add ─────────────────────────────────────────────────────────

    def _quick_add(self):
        if not self._current_path:
            QMessageBox.warning(self, "No profile selected",
                                "Select a profile first.")
            return
        key = self._quick_key.text().strip()
        val = self._quick_val.text().strip()
        section = self._quick_section.currentText()

        if not val:
            QMessageBox.warning(self, "Empty value", "Enter a regex value.")
            return
        try:
            re.compile(val, re.IGNORECASE)
        except re.error as e:
            QMessageBox.critical(self, "Invalid regex", str(e))
            return

        # Load current editor text as parser
        parser = configparser.ConfigParser()
        try:
            parser.read_string(self._editor.toPlainText())
        except configparser.Error as e:
            QMessageBox.critical(self, "Profile parse error", str(e))
            return

        if section not in parser:
            parser[section] = {}
        if not key:
            stem = self._current_path.stem
            kind = "purge" if "PURGE" in section else "warn"
            key = next_key(parser, section, f"{stem}_{kind}")

        if key in parser[section]:
            QMessageBox.warning(self, "Duplicate key",
                                f"Key '{key}' already exists in {section}.")
            return

        parser[section][key] = val

        # Re-render to editor
        import io
        buf = io.StringIO()
        parser.write(buf)
        self._editor.blockSignals(True)
        self._editor.setPlainText(buf.getvalue())
        self._editor.blockSignals(False)
        self._dirty = True
        self._btn_save.setEnabled(True)
        self._btn_discard.setEnabled(True)
        self._lbl_dirty.setText("● Unsaved changes")
        self._quick_key.clear()
        self._quick_val.clear()

    # ── New profile ───────────────────────────────────────────────────────

    def _new_profile(self):
        import traceback
        from core.paths import USER_DIR
        try:
            from PyQt6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(
                self, "New Profile", "Profile filename (without .conf):")
            if not ok or not name.strip():
                return
            name = name.strip().lower().replace(" ", "_")
            path = ensure_user_profiles_dir() / f"{name}.conf"
            if path.exists():
                QMessageBox.warning(self, "Already exists",
                                    f"{path.name} already exists.")
                return
            template = (
                "[META]\n"
                f"# Custom profile: {name}\n"
                "language_codes = \n\n"
                "[PURGE_REGEX]\n"
                f"# {name}_purge1: \\bYourPatternHere\\b\n\n"
                "[WARNING_REGEX]\n"
                f"# {name}_warn1: \\bYourPatternHere\\b\n"
            )
            path.write_text(template, encoding="utf-8")
            self._load_profile_list()
            for i in range(self._profile_list.count()):
                item = self._profile_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == path:
                    self._profile_list.setCurrentRow(i)
                    break
        except Exception:
            import traceback
            from core.logger import append_error
            err = traceback.format_exc()
            append_error("Regex Editor", err)
            QMessageBox.critical(self, "Error", f"New profile crashed:\n\n{err}")

    # ── Reload ────────────────────────────────────────────────────────────

    def _reload(self):
        try:
            reload_engine()
            self._lbl_dirty.setText("✓ Engine reloaded.")
            self._lbl_dirty.setStyleSheet(f"color: {GREEN}; font-size: 9pt;")
        except Exception as e:
            QMessageBox.critical(self, "Reload failed", str(e))

    # ── Public: open a profile directly ──────────────────────────────────

    def select_profile(self, path: Path):
        for i in range(self._profile_list.count()):
            item = self._profile_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                self._profile_list.setCurrentRow(i)
                return
