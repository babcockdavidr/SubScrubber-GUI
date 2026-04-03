"""
Ad detection engine — ported from KBlixt/subcleaner with multi-format support.

Scoring model (faithful to original):
  regex_matches is an int on each SubBlock:
    PURGE_REGEX match:    +3 per unique match
    WARNING_REGEX match:  +1 per unique match
  Contextual punishers each add +1:
    quick_start, close_to_start/end, nearby_ad, adjacent_ad, similar_content
  Thresholds (from SubBlock properties):
    regex_matches >= 3  → is_ad    (remove)
    regex_matches == 2  → is_warning (flag)

  Detectors run after initial thresholding and promote blocks by setting
  regex_matches directly to 3 (ad) or 2 (warning).

GUI extras attached to each block after analysis:
  block.matched_patterns  List[str]  — pattern keys that fired
  block.ad_score          float      — 0.0–1.0 normalised for progress bars
"""
from __future__ import annotations

import configparser
import re
import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

from .subtitle import ParsedSubtitle, SubBlock


# ---------------------------------------------------------------------------
# Regex profile loader
# ---------------------------------------------------------------------------

_PROFILES_DIR = Path(__file__).parent.parent / "regex_profiles" / "default"

_purge_regex:   Dict[str, List[Tuple[str, re.Pattern]]] = {}
_warning_regex: Dict[str, List[Tuple[str, re.Pattern]]] = {}

_global_purge:    List[Tuple[str, re.Pattern]] = []
_global_warning:  List[Tuple[str, re.Pattern]] = []
_global_excluded: List[str] = []


def _compile(value: str) -> re.Pattern:
    return re.compile(f"({value})", flags=re.IGNORECASE | re.UNICODE)


def _load_profiles() -> None:
    if not _PROFILES_DIR.exists():
        return

    # Pass 1: global profiles first (no language_codes, or has excluded_language_codes)
    # Pass 2: language-specific profiles
    for pass_num in (1, 2):
        for conf in sorted(_PROFILES_DIR.iterdir()):
            if not conf.is_file() or conf.suffix != ".conf":
                continue
            parser = configparser.ConfigParser()
            parser.read(conf, encoding="utf-8")
            if "META" not in parser:
                continue

            meta       = parser["META"]
            lang_codes = meta.get("language_codes", "").replace(" ", "")
            excluded   = [x for x in
                          meta.get("excluded_language_codes", "")
                          .replace(" ", "").split(",") if x]
            is_global  = (not lang_codes or
                          "excluded_language_codes" in meta)

            purge_items   = list(parser["PURGE_REGEX"].items())   if "PURGE_REGEX"   in parser else []
            warning_items = list(parser["WARNING_REGEX"].items()) if "WARNING_REGEX" in parser else []
            purge_compiled   = [(k, _compile(v)) for k, v in purge_items]
            warning_compiled = [(k, _compile(v)) for k, v in warning_items]

            if is_global and pass_num == 1:
                _global_purge.extend(purge_compiled)
                _global_warning.extend(warning_compiled)
                _global_excluded.extend(excluded)
                # Retroactively seed already-registered languages
                for lang in _purge_regex:
                    if lang not in excluded:
                        _purge_regex[lang].extend(purge_compiled)
                        _warning_regex[lang].extend(warning_compiled)

            elif not is_global and pass_num == 2:
                for lang in lang_codes.split(","):
                    if not lang:
                        continue
                    if lang not in _purge_regex:
                        # Seed from globals
                        _purge_regex[lang]   = [p for p in _global_purge
                                                 if lang not in _global_excluded]
                        _warning_regex[lang] = [p for p in _global_warning
                                                 if lang not in _global_excluded]
                    _purge_regex[lang].extend(purge_compiled)
                    _warning_regex[lang].extend(warning_compiled)


_load_profiles()


def _get_purge(language: str) -> List[Tuple[str, re.Pattern]]:
    if language in _purge_regex:
        return _purge_regex[language]
    return _purge_regex.get("no_profile", list(_global_purge))


def _get_warning(language: str) -> List[Tuple[str, re.Pattern]]:
    if language in _warning_regex:
        return _warning_regex[language]
    return _warning_regex.get("no_profile", list(_global_warning))


# ---------------------------------------------------------------------------
# GUI extras — attached to blocks as plain attributes after analysis
# ---------------------------------------------------------------------------

def _ensure_extras(block: SubBlock) -> None:
    if not hasattr(block, "matched_patterns"):
        block.matched_patterns = []
    if not hasattr(block, "ad_score"):
        block.ad_score = 0.0


def _reset_block(block: SubBlock) -> None:
    block.regex_matches = 0
    block.hints = []
    block.matched_patterns = []
    block.ad_score = 0.0


# ---------------------------------------------------------------------------
# Punishers
# ---------------------------------------------------------------------------

def _punish_regex(subtitle: ParsedSubtitle) -> None:
    purge   = _get_purge(subtitle.language)
    warning = _get_warning(subtitle.language)

    for block in subtitle.blocks:
        text = " ".join(block.content.replace("-\n", "-").split())

        for key, pat in purge:
            try:
                results = re.findall(pat, text)
            except re.error:
                continue
            if results:
                # Deduplicate matches the same way subcleaner does
                if results and isinstance(results[0], str):
                    unique = set(r.lower() for r in results)
                else:
                    unique = set(r[0].lower() for r in results)
                block.regex_matches += 3 * len(unique)
                for _ in unique:
                    block.hints.append(key)
                    block.matched_patterns.append(key)

        for key, pat in warning:
            try:
                results = re.findall(pat, text)
            except re.error:
                continue
            if results:
                if results and isinstance(results[0], str):
                    unique = set(r.lower() for r in results)
                else:
                    unique = set(r[0].lower() for r in results)
                block.regex_matches += 1 * len(unique)
                for _ in unique:
                    block.hints.append(key)
                    if key not in block.matched_patterns:
                        block.matched_patterns.append(key)


def _punish_quick_first_block(subtitle: ParsedSubtitle) -> None:
    if not subtitle.blocks:
        return
    block = subtitle.blocks[0]
    if block.start_time < datetime.timedelta(seconds=1):
        block.regex_matches += 1
        block.hints.append("quick_start")


def _punish_ad_adjacency(subtitle: ParsedSubtitle) -> None:
    blocks = subtitle.blocks
    n = len(blocks)
    nearby:   Set[int] = set()
    adjacent: Set[int] = set()

    for i, block in enumerate(blocks):
        if i < 3:
            block.regex_matches += 1
            block.hints.append("close_to_start")
            continue
        if i >= n - 3:
            block.regex_matches += 1
            block.hints.append("close_to_end")
            continue
        window = blocks[max(0, i - 15): min(i + 16, n)]
        for other in window:
            if other is not block and other.regex_matches >= 3:
                nearby.add(i)
                block.hints.append("nearby_ad")
                break

    for i, block in enumerate(blocks):
        window = blocks[max(0, i - 1): min(i + 2, n)]
        for other in window:
            if other is not block and other.regex_matches >= 2:
                word_count = re.sub(" +", " ",
                                    block.content.replace("\n", " ").strip()).count(" ")
                if word_count <= 4:
                    adjacent.add(i)
                    break

    for i in nearby:
        blocks[i].regex_matches += 1

    for i in adjacent:
        blocks[i].regex_matches += 1
        blocks[i].hints.append("adjacent_ad")


def _punish_clone_blocks(subtitle: ParsedSubtitle) -> None:
    content_map: Dict[str, List[SubBlock]] = {}
    for block in subtitle.blocks:
        key = re.sub(r"[\s.,:_-]", "", block.content)
        content_map.setdefault(key, []).append(block)

    for group in content_map.values():
        if len(group) <= 1:
            continue
        for block in group:
            if "♪" in block.content:
                continue
            block.regex_matches += 1
            block.hints.append("similar_content")


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def _detect_wedged(subtitle: ParsedSubtitle) -> None:
    """
    Promote blocks wedged between confirmed ads.
    Uses the same logic as detectors/wedged.py but drives regex_matches
    instead of setting is_ad/is_warning directly.
    """
    blocks = subtitle.blocks
    n = len(blocks)
    if n < 3:
        return

    for i, block in enumerate(blocks):
        b_start = block.start_time
        b_end   = block.end_time

        if i == 0:
            post = blocks[i + 1]
            if post.regex_matches >= 3:
                gap = post.start_time - b_end
                if gap < datetime.timedelta(seconds=1):
                    # warn→ad or clean→warn
                    if block.regex_matches == 2:
                        block.regex_matches = 3
                    else:
                        block.regex_matches = max(block.regex_matches, 2)
                else:
                    block.regex_matches = max(block.regex_matches, 2)
                block.hints.append("wedged_block")
            continue

        if i == n - 1:
            pre = blocks[i - 1]
            if pre.regex_matches < 3:
                continue
            block.hints.append("wedged_block")
            gap = b_start - pre.end_time
            if gap > datetime.timedelta(seconds=1):
                block.regex_matches = max(block.regex_matches, 2)
                continue
            if block.regex_matches == 2:
                block.regex_matches = 3
            else:
                block.regex_matches = max(block.regex_matches, 2)
            continue

        pre  = blocks[i - 1]
        post = blocks[i + 1]
        if pre.regex_matches >= 3 and post.regex_matches >= 3:
            gap_before = b_start - pre.end_time
            gap_after  = post.start_time - b_end
            if (gap_after  < datetime.timedelta(seconds=1) and
                    gap_before < datetime.timedelta(seconds=1)):
                block.regex_matches = 3
                block.hints.append("wedged_block")
                continue
            if block.regex_matches == 2:
                block.regex_matches = 3
            else:
                block.regex_matches = max(block.regex_matches, 2)
            block.hints.append("wedged_block")


def _is_chain_link(a: SubBlock, b: SubBlock) -> bool:
    if a.start_time > b.start_time:
        a, b = b, a
    if b.start_time - a.end_time > datetime.timedelta(milliseconds=500):
        return False
    ac, bc = a.content, b.content
    la, lb = len(ac), len(bc)
    if la < lb <= la + 2:
        return bc.startswith(ac) or bc.endswith(ac)
    elif lb < la <= lb + 2:
        return ac.startswith(bc) or ac.endswith(bc)
    elif ac.strip() == bc.strip():
        return True
    return False


def _detect_chain(subtitle: ParsedSubtitle) -> None:
    blocks = subtitle.blocks
    chain: List[SubBlock] = []
    identical_count = 0

    def _flush():
        if len(chain) > 2 + identical_count or any(b.is_ad for b in chain):
            for b in chain:
                b.regex_matches = max(b.regex_matches, 3)
                b.hints.append("chain_block")

    for i in range(1, len(blocks)):
        block     = blocks[i]
        pre_block = blocks[i - 1]
        if _is_chain_link(pre_block, block):
            if pre_block.equal_content(block):
                identical_count += 1
            if not chain:
                chain.append(pre_block)
            chain.append(block)
        else:
            _flush()
            chain = []
            identical_count = 0

    _flush()


def _move_duplicated(subtitle: ParsedSubtitle) -> None:
    content_map: Dict[str, List[SubBlock]] = {}
    for block in subtitle.blocks:
        key = re.sub(r"[\s.,:_-]", "", block.content)
        content_map.setdefault(key, []).append(block)

    for block in list(subtitle.blocks):
        if "similar_content" not in block.hints:
            continue
        key = re.sub(r"[\s.,:_-]", "", block.content)
        if block.is_ad:
            for sibling in content_map.get(key, []):
                sibling.regex_matches = max(sibling.regex_matches, 3)
        elif block.is_warning:
            for sibling in content_map.get(key, []):
                sibling.regex_matches = max(sibling.regex_matches, 2)


# ---------------------------------------------------------------------------
# Duplicate-content merging (from subtitle.py __init__)
# ---------------------------------------------------------------------------

def _merge_adjacent_identical(subtitle: ParsedSubtitle) -> None:
    """
    Adjacent blocks with identical content within 1 frame of each other
    are merged (end time extended). Mirrors subcleaner's subtitle.__init__.
    """
    if len(subtitle.blocks) <= 1:
        return
    to_remove: List[SubBlock] = []
    prev = subtitle.blocks[0]
    for block in subtitle.blocks[1:]:
        if (block.content == prev.content and
                (block.start_time - prev.end_time).total_seconds() < 1 / 31):
            prev.end_time = block.end_time
            to_remove.append(block)
        else:
            prev = block
    for b in to_remove:
        subtitle.blocks.remove(b)


# ---------------------------------------------------------------------------
# Overlap fix (from cleaner/cleaner.py)
# ---------------------------------------------------------------------------

def fix_overlap(subtitle: ParsedSubtitle) -> bool:
    if len(subtitle.blocks) < 2:
        return False
    changes = False
    prev = subtitle.blocks[0]
    for block in subtitle.blocks[1:]:
        if not (prev.start_time < block.start_time and
                prev.end_time < block.end_time):
            prev = block
            continue
        overlap = prev.end_time - block.start_time + datetime.timedelta(seconds=3 / 30)
        if (datetime.timedelta(milliseconds=3) < overlap and
                (len(block.content) + len(prev.content)) > 0):
            ratio = block.duration_seconds / (block.duration_seconds +
                                               prev.duration_seconds)
            block.start_time += ratio * overlap
            prev.end_time   += (ratio - 1) * overlap
            changes = True
        prev = block
    return changes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(subtitle: ParsedSubtitle) -> ParsedSubtitle:
    """
    Full detection pipeline. Mutates blocks in-place, returns subtitle.

    Pipeline (mirrors subcleaner's main.py clean_file + cleaner.find_ads):
      1. Reset block state
      2. Merge adjacent identical blocks
      3. Sort by time, remove negative-duration (unscramble)
      4. Regex punisher (purge +3, warning +1)
      5. Zero-match sentinel (-1 so adjacency ignores truly clean blocks)
      6. Quick-first-block punisher
      7. Adjacency / proximity punisher
      8. Clone-block punisher
      9. detect_wedged
      10. move_duplicated
      11. detect_chain
      12. Attach GUI extras (ad_score, matched_patterns already set)
    """
    if not subtitle.blocks:
        return subtitle

    # 1. Reset
    for block in subtitle.blocks:
        _reset_block(block)

    # 2. Merge adjacent identical
    _merge_adjacent_identical(subtitle)

    # 3. Sort + cull negative-duration (unscramble)
    subtitle.blocks.sort(key=lambda b: b.start_time)
    subtitle.blocks = [b for b in subtitle.blocks if b.duration_seconds > 0]
    for i, b in enumerate(subtitle.blocks, 1):
        b.current_index = i

    # 4. Regex punisher
    _punish_regex(subtitle)

    # 5. Zero-match sentinel
    for block in subtitle.blocks:
        if block.regex_matches == 0:
            block.regex_matches = -1

    # 6–8. Contextual punishers
    _punish_quick_first_block(subtitle)
    _punish_ad_adjacency(subtitle)
    _punish_clone_blocks(subtitle)

    # 9–11. Detectors
    _detect_wedged(subtitle)
    _move_duplicated(subtitle)
    _detect_chain(subtitle)

    # 12. Attach GUI ad_score (normalised view of regex_matches)
    for block in subtitle.blocks:
        _ensure_extras(block)
        block.ad_score = min(1.0, max(0.0, block.regex_matches / 5.0))

    return subtitle


def clean(subtitle: ParsedSubtitle, dry_run: bool = False,
          remove_warnings: bool = False):
    """Analyze then remove flagged blocks. Returns (subtitle, removed_count)."""
    analyze(subtitle)

    to_remove = [b for b in subtitle.blocks if b.is_ad]
    if remove_warnings:
        to_remove += [b for b in subtitle.blocks if b.is_warning]

    removed = len(to_remove)

    if not dry_run and to_remove:
        remove_ids = {id(b) for b in to_remove}
        subtitle.blocks = [b for b in subtitle.blocks
                           if id(b) not in remove_ids]
        for i, b in enumerate(subtitle.blocks, 1):
            b.current_index = i

    return subtitle, removed


def generate_report(subtitle: ParsedSubtitle, cleaning_options=None) -> str:
    from .cleaner_options import block_will_be_removed
    ad_blocks   = [b for b in subtitle.blocks if b.is_ad]
    warn_blocks = [b for b in subtitle.blocks if b.is_warning]
    clean_opt_blocks = []
    if cleaning_options and cleaning_options.any_enabled():
        clean_opt_blocks = [
            b for b in subtitle.blocks
            if not b.is_ad and block_will_be_removed(b.content, cleaning_options)
        ]
    lines = [
        f"File:     {subtitle.path.name}",
        f"Format:   {subtitle.fmt.value.upper()}",
        f"Language: {subtitle.language}",
        f"Blocks:   {len(subtitle.blocks)} total",
        f"Ads:      {len(ad_blocks)} flagged for removal",
        f"Warnings: {len(warn_blocks)} flagged as warnings",
    ]
    if clean_opt_blocks:
        lines.append(f"Cleaning: {len(clean_opt_blocks)} block(s) removed by cleaning options")
    if ad_blocks:
        lines.append("\nAd blocks:")
        for b in ad_blocks:
            reasons = ", ".join(dict.fromkeys(b.hints))
            lines.append(f"  [{timedelta_to_srt(b.start_time)}]  "
                         f"{b.content[:80].replace(chr(10), ' ')}")
            if reasons:
                lines.append(f"    reasons: {reasons}")
    if clean_opt_blocks:
        lines.append("\nRemoved by cleaning options:")
        for b in clean_opt_blocks:
            lines.append(f"  [{timedelta_to_srt(b.start_time)}]  "
                         f"{b.content[:80].replace(chr(10), ' ')}")
    if warn_blocks:
        lines.append("\nWarning blocks:")
        for b in warn_blocks:
            reasons = ", ".join(dict.fromkeys(b.hints))
            lines.append(f"  [{timedelta_to_srt(b.start_time)}]  "
                         f"{b.content[:80].replace(chr(10), ' ')}")
            if reasons:
                lines.append(f"    reasons: {reasons}")
    return "\n".join(lines)


def timedelta_to_srt(td: datetime.timedelta) -> str:
    from .subtitle import timedelta_to_srt_string
    return timedelta_to_srt_string(td)
