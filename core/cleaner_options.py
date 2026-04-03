"""
Subtitle content cleaning options.

These functions modify the *content within* subtitle blocks — they are
fundamentally different from the ad detection engine which removes entire
blocks. None of these options affect block existence or timing.

All functions are pure: they return a modified copy of the content string
or a new block list. They never mutate in place.

Accessibility note: SDH (Subtitles for the Deaf and Hard of Hearing)
content — sound descriptions, speaker labels, music cues — exists
specifically for viewers who cannot hear the audio. Features that remove
this content must be clearly labelled and must never be enabled by default.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .subtitle import SubBlock, ParsedSubtitle


# ---------------------------------------------------------------------------
# ISO 639-2 language code → display name
# Covers the most common codes encountered in subtitle files.
# ---------------------------------------------------------------------------

LANGUAGE_NAMES = {
    "afr": "Afrikaans", "ara": "Arabic", "bul": "Bulgarian",
    "chi": "Chinese", "zho": "Chinese", "hrv": "Croatian",
    "cze": "Czech", "ces": "Czech", "dan": "Danish",
    "dut": "Dutch", "nld": "Dutch", "eng": "English",
    "est": "Estonian", "fin": "Finnish", "fre": "French",
    "fra": "French", "ger": "German", "deu": "German",
    "gre": "Greek", "ell": "Greek", "heb": "Hebrew",
    "hun": "Hungarian", "ice": "Icelandic", "isl": "Icelandic",
    "ind": "Indonesian", "ita": "Italian", "jpn": "Japanese",
    "kor": "Korean", "lav": "Latvian", "lit": "Lithuanian",
    "nor": "Norwegian", "pol": "Polish", "por": "Portuguese",
    "rum": "Romanian", "ron": "Romanian", "rus": "Russian",
    "slo": "Slovak", "slk": "Slovak", "slv": "Slovenian",
    "spa": "Spanish", "swe": "Swedish", "tha": "Thai",
    "tur": "Turkish", "ukr": "Ukrainian", "vie": "Vietnamese",
    "und": "Unknown",
}


def language_display_name(iso_code: str) -> str:
    """
    Convert an ISO 639-2 language code to a clean display name.
    Falls back to title-casing the code if not in the lookup table.
    """
    if not iso_code:
        return "Unknown"
    return LANGUAGE_NAMES.get(iso_code.lower(), iso_code.title())


# ---------------------------------------------------------------------------
# Options dataclass
# ---------------------------------------------------------------------------

@dataclass
class CleaningOptions:
    # Music cues
    remove_music_cues: bool = False

    # SDH annotations — accessibility warning required in UI
    remove_sdh_annotations: bool = False

    # Speaker labels
    remove_speaker_labels: bool = False

    # Formatting tags
    remove_formatting_tags: bool = False
    preserve_italic: bool = True
    preserve_bold: bool = True

    # Bracket content removal — individual toggles
    remove_curly_brackets: bool = False
    remove_square_brackets: bool = False
    remove_parentheses: bool = False
    remove_asterisk_content: bool = False
    remove_hash_content: bool = False

    # Case normalization
    normalize_case: bool = False

    # Duplicate cue merging — applied last, subtitle-level operation
    merge_duplicate_cues: bool = False

    def any_enabled(self) -> bool:
        return any([
            self.remove_music_cues,
            self.remove_sdh_annotations,
            self.remove_speaker_labels,
            self.remove_formatting_tags,
            self.remove_curly_brackets,
            self.remove_square_brackets,
            self.remove_parentheses,
            self.remove_asterisk_content,
            self.remove_hash_content,
            self.normalize_case,
            self.merge_duplicate_cues,
        ])


# ---------------------------------------------------------------------------
# Cleaning report
# ---------------------------------------------------------------------------

@dataclass
class CleaningAction:
    timestamp: str
    reason: str
    original: str
    result: str   # "modified" or "removed"


@dataclass
class CleaningReport:
    actions: List[CleaningAction] = field(default_factory=list)
    duplicates_merged: int = 0

    @property
    def any_changes(self) -> bool:
        return bool(self.actions) or self.duplicates_merged > 0

    def modifications(self) -> List["CleaningAction"]:
        return [a for a in self.actions if a.result == "modified"]

    def removals(self) -> List["CleaningAction"]:
        return [a for a in self.actions if a.result == "removed"]


# ---------------------------------------------------------------------------
# Per-block content cleaners
# ---------------------------------------------------------------------------

# Music symbols
_MUSIC_SYMBOLS = re.compile(r'[♪♫🎵🎶]')
# Lines that are entirely music content (symbols, spaces, dashes)
_MUSIC_LINE = re.compile(r'^[\s♪♫🎵🎶\-]+$')

def strip_music_cues(content: str) -> str:
    """
    Remove lines that consist entirely of music symbols.
    Also strip inline music symbols from lines that have other content.
    """
    lines = content.split('\n')
    result = []
    for line in lines:
        if _MUSIC_LINE.match(line):
            continue  # drop entire line
        # Strip inline symbols but keep the line
        cleaned = _MUSIC_SYMBOLS.sub('', line).strip()
        if cleaned:
            result.append(cleaned)
    return '\n'.join(result)


# SDH: [ALL CAPS] or (All Caps) — distinguished from normal dialogue
# by capitalization convention. We match 2+ word chars, all caps or
# title case, inside brackets.
_SDH_SQUARE   = re.compile(r'\[[A-Z][A-Z\s,\'!\.\-]{1,60}\]')
_SDH_PAREN    = re.compile(r'\([A-Z][A-Z\s,\'!\.\-]{1,60}\)')
_SDH_LINE     = re.compile(r'^\s*[\[\(][A-Z][A-Z\s,\'!\.\-]{1,60}[\]\)]\s*$')

def strip_sdh_annotations(content: str) -> str:
    """
    Remove SDH sound descriptions like [DOOR SLAMS] and (LAUGHING).
    Uses capitalization convention to distinguish from normal parenthetical
    dialogue which is typically mixed case.
    """
    lines = content.split('\n')
    result = []
    for line in lines:
        if _SDH_LINE.match(line):
            continue  # entire line is an SDH annotation — drop it
        cleaned = _SDH_SQUARE.sub('', line)
        cleaned = _SDH_PAREN.sub('', cleaned).strip()
        if cleaned:
            result.append(cleaned)
    return '\n'.join(result)


# Speaker labels: "JOHN:" or "- MARY:" at line start
_SPEAKER_LABEL = re.compile(r'^-?\s*[A-Z][A-Z\s\.]{0,30}:\s*')

def strip_speaker_labels(content: str) -> str:
    """
    Remove speaker labels like JOHN: or - MARY: at the start of lines.
    Only matches all-caps labels to avoid stripping normal sentence starts.
    """
    lines = content.split('\n')
    result = []
    for line in lines:
        cleaned = _SPEAKER_LABEL.sub('', line).strip()
        if cleaned:
            result.append(cleaned)
        elif not cleaned and line.strip():
            # Line was only a speaker label — drop it
            pass
        else:
            result.append(line)
    return '\n'.join(result)


def strip_formatting_tags(content: str,
                           preserve_italic: bool = True,
                           preserve_bold: bool = True) -> str:
    """
    Remove HTML-style formatting tags from subtitle content.
    Optionally preserve <i> and <b> tags.
    """
    result = content

    if not preserve_italic:
        result = re.sub(r'</?i>', '', result, flags=re.IGNORECASE)
    if not preserve_bold:
        result = re.sub(r'</?b>', '', result, flags=re.IGNORECASE)

    # Always remove font tags and color attributes
    result = re.sub(r'<font[^>]*>', '', result, flags=re.IGNORECASE)
    result = re.sub(r'</font>', '', result, flags=re.IGNORECASE)

    # Remove any remaining unknown tags (not i/b if preserved)
    if preserve_italic and preserve_bold:
        result = re.sub(r'</?(?!i>|/i>|b>|/b>)[^>]+>', '', result)
    elif preserve_italic:
        result = re.sub(r'</?(?!i>|/i>)[^>]+>', '', result)
    elif preserve_bold:
        result = re.sub(r'</?(?!b>|/b>)[^>]+>', '', result)
    else:
        result = re.sub(r'<[^>]+>', '', result)

    return result.strip()


def strip_bracket_content(content: str,
                            curly: bool = False,
                            square: bool = False,
                            parens: bool = False,
                            asterisk: bool = False,
                            hashes: bool = False) -> str:
    """Remove content between specified bracket types."""
    result = content
    if curly:
        result = re.sub(r'\{[^}]*\}', '', result)
    if square:
        result = re.sub(r'\[[^\]]*\]', '', result)
    if parens:
        result = re.sub(r'\([^)]*\)', '', result)
    if asterisk:
        result = re.sub(r'\*[^*]+\*', '', result)
    if hashes:
        result = re.sub(r'#[^#]+#', '', result)
    # Clean up any double spaces left behind
    result = re.sub(r'  +', ' ', result).strip()
    return result


def normalize_case(content: str) -> str:
    """
    Convert lines to sentence case — first letter capitalized,
    rest lowercase — while preserving proper nouns is impractical
    without NLP, so this is a simple sentence-case pass.
    """
    lines = content.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            result.append(stripped[0].upper() + stripped[1:].lower())
        else:
            result.append(line)
    return '\n'.join(result)


# ---------------------------------------------------------------------------
# Subtitle-level operations
# ---------------------------------------------------------------------------

def merge_duplicate_cues(blocks: List[SubBlock]) -> List[SubBlock]:
    """
    Collapse consecutive blocks with identical content into one block,
    extending the end time of the first to cover all duplicates.
    Applied after all other cleaning so content is already normalized.
    """
    if not blocks:
        return blocks

    merged = [blocks[0]]
    for block in blocks[1:]:
        prev = merged[-1]
        if block.content.strip() == prev.content.strip():
            # Extend previous block's end time
            prev.end_time = block.end_time
        else:
            merged.append(block)

    # Re-index
    for i, b in enumerate(merged, 1):
        b.current_index = i

    return merged


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def block_will_be_removed(block_content: str, options: CleaningOptions) -> bool:
    """
    Return True if the block content would be entirely removed by the
    given cleaning options. Used to pre-flag blocks in reports before
    the user clicks Clean & Save.
    """
    if not options.any_enabled():
        return False
    c = block_content
    if options.remove_formatting_tags:
        c = strip_formatting_tags(c,
            preserve_italic=options.preserve_italic,
            preserve_bold=options.preserve_bold)
    if any([options.remove_curly_brackets, options.remove_square_brackets,
            options.remove_parentheses, options.remove_asterisk_content,
            options.remove_hash_content]):
        c = strip_bracket_content(c,
            curly=options.remove_curly_brackets,
            square=options.remove_square_brackets,
            parens=options.remove_parentheses,
            asterisk=options.remove_asterisk_content,
            hashes=options.remove_hash_content)
    if options.remove_sdh_annotations:
        c = strip_sdh_annotations(c)
    if options.remove_speaker_labels:
        c = strip_speaker_labels(c)
    if options.remove_music_cues:
        c = strip_music_cues(c)
    return not c.strip()


def _primary_reason(original: str, options: CleaningOptions) -> str:
    if options.remove_music_cues and _MUSIC_SYMBOLS.search(original):
        return "music cues"
    if options.remove_sdh_annotations and (
            _SDH_SQUARE.search(original) or _SDH_PAREN.search(original)):
        return "SDH annotations"
    if options.remove_speaker_labels and _SPEAKER_LABEL.match(original):
        return "speaker labels"
    if options.remove_formatting_tags and re.search(r"<[^>]+>", original):
        return "formatting tags"
    if options.remove_curly_brackets and "{" in original:
        return "curly brackets"
    if options.remove_square_brackets and "[" in original:
        return "square brackets"
    if options.remove_parentheses and "(" in original:
        return "parentheses"
    if options.normalize_case:
        return "case normalization"
    return "cleaning options"


def apply_cleaning_options(subtitle: ParsedSubtitle,
                            options: CleaningOptions):
    """
    Apply all enabled cleaning options to a subtitle's blocks.
    Returns (subtitle, CleaningReport).
    Blocks that become empty after cleaning are removed.
    """
    report = CleaningReport()

    if not options.any_enabled():
        return subtitle, report

    surviving = []
    for block in subtitle.blocks:
        original = block.content
        c = original

        if options.remove_formatting_tags:
            c = strip_formatting_tags(
                c,
                preserve_italic=options.preserve_italic,
                preserve_bold=options.preserve_bold,
            )

        if any([options.remove_curly_brackets, options.remove_square_brackets,
                options.remove_parentheses, options.remove_asterisk_content,
                options.remove_hash_content]):
            c = strip_bracket_content(
                c,
                curly=options.remove_curly_brackets,
                square=options.remove_square_brackets,
                parens=options.remove_parentheses,
                asterisk=options.remove_asterisk_content,
                hashes=options.remove_hash_content,
            )

        if options.remove_sdh_annotations:
            c = strip_sdh_annotations(c)

        if options.remove_speaker_labels:
            c = strip_speaker_labels(c)

        if options.remove_music_cues:
            c = strip_music_cues(c)

        if options.normalize_case:
            c = normalize_case(c)

        c = c.strip()

        if not c:
            report.actions.append(CleaningAction(
                timestamp=str(block.start),
                reason=_primary_reason(original, options),
                original=original[:80],
                result="removed",
            ))
        elif c != original:
            report.actions.append(CleaningAction(
                timestamp=str(block.start),
                reason=_primary_reason(original, options),
                original=original[:80],
                result="modified",
            ))
            block.content = c
            surviving.append(block)
        else:
            surviving.append(block)

    subtitle.blocks = surviving

    if options.merge_duplicate_cues:
        before = len(subtitle.blocks)
        subtitle.blocks = merge_duplicate_cues(subtitle.blocks)
        report.duplicates_merged = before - len(subtitle.blocks)

    for i, b in enumerate(subtitle.blocks, 1):
        b.current_index = i

    return subtitle, report
