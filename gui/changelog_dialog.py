"""
gui/changelog_dialog.py
What's New dialog — displays CHANGELOG.md in a scrollable window.
"""
from PyQt6.QtCore    import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextBrowser, QLabel,
)

from .colors  import BG, BG2, FG, FG2, ACCENT, BORDER
from .strings import STRINGS
from core.paths import CHANGELOG_FILE


def _md_to_html(text: str) -> str:
    """
    Minimal Markdown → HTML converter for the changelog format.
    Handles: ## headings, - bullets, --- dividers, **bold**, blank lines.
    """
    lines = text.splitlines()
    html_parts = [
        f"<html><body style='background:{BG}; color:{FG}; "
        f"font-family:sans-serif; font-size:10pt; margin:12px;'>"
    ]
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Close list if we hit a non-bullet
        if in_list and not stripped.startswith("- "):
            html_parts.append("</ul>")
            in_list = False

        if stripped.startswith("## "):
            heading = stripped[3:]
            html_parts.append(
                f"<h2 style='color:{ACCENT}; font-size:12pt; "
                f"margin-top:16px; margin-bottom:4px;'>{heading}</h2>"
            )
        elif stripped.startswith("# "):
            heading = stripped[2:]
            html_parts.append(
                f"<h1 style='color:{ACCENT}; font-size:14pt; "
                f"margin-top:8px; margin-bottom:8px;'>{heading}</h1>"
            )
        elif stripped == "---":
            html_parts.append(f"<hr style='border:none; border-top:1px solid {BORDER}; margin:12px 0;'>")
        elif stripped.startswith("- "):
            if not in_list:
                html_parts.append(f"<ul style='margin:4px 0 4px 16px; padding:0; color:{FG};'>")
                in_list = True
            content = stripped[2:]
            # Handle **bold**
            import re
            content = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', content)
            html_parts.append(f"<li style='margin:2px 0;'>{content}</li>")
        elif stripped == "":
            html_parts.append("<br>")
        else:
            import re
            line_html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', stripped)
            html_parts.append(f"<p style='margin:2px 0;'>{line_html}</p>")

    if in_list:
        html_parts.append("</ul>")

    html_parts.append("</body></html>")
    return "\n".join(html_parts)


class ChangelogDialog(QDialog):
    """Scrollable What's New dialog reading from CHANGELOG.md."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(STRINGS["settings_btn_whats_new"])
        self.setMinimumSize(560, 500)
        self.setStyleSheet(f"background: {BG}; color: {FG};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Title
        lbl = QLabel(STRINGS["settings_btn_whats_new"])
        lbl.setStyleSheet(
            f"color: {ACCENT}; font-size: 14pt; font-weight: bold;"
        )
        layout.addWidget(lbl)

        # Content
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setStyleSheet(
            f"background: {BG2}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 4px;"
        )

        try:
            md_text = CHANGELOG_FILE.read_text(encoding="utf-8")
            browser.setHtml(_md_to_html(md_text))
        except Exception:
            browser.setPlainText("CHANGELOG.md not found.")

        layout.addWidget(browser, stretch=1)

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton(STRINGS.get("dlg_close", "Close"))
        btn_close.setStyleSheet(
            f"font-size: 10pt; padding: 6px 20px; color: {FG2}; "
            f"border: 1px solid {BORDER}; border-radius: 3px; background: {BG2};"
        )
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)
