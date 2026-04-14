# subforge.spec
import sys
from pathlib import Path

HERE = Path(SPECPATH)

added_data = [
    (str(HERE / "regex_profiles" / "default"), "regex_profiles/default"),
    (str(HERE / "CHANGELOG.md"), "."),
]

a = Analysis(
    [str(HERE / "subforge.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=added_data,
    hiddenimports=[
        # PyQt6
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.sip",
        # pysubs2 parsers loaded by name at runtime
        "pysubs2",
        "pysubs2.formats",
        "pysubs2.formats.subrip",
        "pysubs2.formats.advanced_substation_alpha",
        "pysubs2.formats.substation_alpha",
        "pysubs2.formats.webvtt",
        "pysubs2.formats.microdvd",
        "pysubs2.formats.mpl2",
        "pysubs2.formats.tmp",
        # Pillow — imported inside functions, static analysis misses it
        "PIL",
        "PIL.Image",
        "PIL.ImageOps",
        "PIL.ImageFilter",
        "PIL.ImageDraw",
        "PIL._imaging",
        "PIL._imagingft",
        "PIL._imagingmath",
        "PIL._imagingmorph",
        "PIL.BmpImagePlugin",
        "PIL.PngImagePlugin",
        "PIL.JpegImagePlugin",
        "PIL.GifImagePlugin",
        "PIL.TiffImagePlugin",
        # pytesseract — single-file module, imported inside functions
        "pytesseract",
        "pytesseract.pytesseract",
        "pytesseract.output",
        # GUI lazy imports
        "gui.changelog_dialog",
        "gui.image_subs_panel",
        "gui.transcribe_panel",
        # core.whisper — imported inside functions
        # Note: faster-whisper itself is NOT bundled. The Transcribe tab
        # requires faster-whisper to be installed separately via pip.
        # core.whisper is included so the availability check works correctly.
        "core.whisper",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SubForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SubForge",
)

app = BUNDLE(
    coll,
    name="SubForge.app",
    bundle_identifier="com.babcockdavidr.subforge",
    info_plist={
        "CFBundleShortVersionString": "0.11.0",
        "CFBundleVersion":            "0.11.0",
        "NSHighResolutionCapable":    True,
        "LSMinimumSystemVersion":     "10.15",
    },
)
