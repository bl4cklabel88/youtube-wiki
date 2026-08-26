"""Transcript cleaning: remove VTT/timing artifacts and normalize text.

Operates purely deterministically (regex-based) before any LLM pass.
"""
from __future__ import annotations

import re
from typing import Optional

# Common caption artifacts
TIMING_RE = re.compile(
    r"\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?\s*(?:-->|->)\s*\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?"
)
WEBVTT_HEADER_RE = re.compile(r"^\s*(WEBVTT|NOTE|Kind:|Language:)", re.MULTILINE | re.IGNORECASE)
CUE_INDEX_RE = re.compile(r"^\s*\d+\s*$", re.MULTILINE)
BRACKET_NOISE_RE = re.compile(r"\[(?:music|applause|laughter|noise|inaudible|silence|crosstalk|foreign|sound)\][^\]]*\]?", re.IGNORECASE)
PAREN_NOISE_RE = re.compile(r"\((?:music|applause|laughter|noise|inaudible|silence|crosstalk|foreign)\)", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
TIMESTAMP_INLINE_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
REPEATED_CHAR_RE = re.compile(r"(.)\1{3,}")  # "aaaahhhh" -> collapse
MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# Known auto-caption transcription quirks -> fixes
COMMON_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bvoltage crop\b", re.IGNORECASE), "voltage drop"),
    (re.compile(r"\boscilla scope\b", re.IGNORECASE), "oscilloscope"),
    (re.compile(r"\boscillascope\b", re.IGNORECASE), "oscilloscope"),
    (re.compile(r"\bP\s*300\b", re.IGNORECASE), "P0300"),
    (re.compile(r"\bP\s*301\b", re.IGNORECASE), "P0301"),
    (re.compile(r"\bP\s*302\b", re.IGNORECASE), "P0302"),
    (re.compile(r"\bP\s*303\b", re.IGNORECASE), "P0303"),
    (re.compile(r"\bP\s*304\b", re.IGNORECASE), "P0304"),
    (re.compile(r"\bP\s*305\b", re.IGNORECASE), "P0305"),
    (re.compile(r"\bP\s*306\b", re.IGNORECASE), "P0306"),
    (re.compile(r"\bP\s*307\b", re.IGNORECASE), "P0307"),
    (re.compile(r"\bP\s*308\b", re.IGNORECASE), "P0308"),
    (re.compile(r"\bP\s*309\b", re.IGNORECASE), "P0309"),
    (re.compile(r"\bP\s*310\b", re.IGNORECASE), "P0310"),
    (re.compile(r"\bDTC\s*code\s*s?\b", re.IGNORECASE), "DTC"),
    (re.compile(r"\bOBD\s*II\b", re.IGNORECASE), "OBD-II"),
    (re.compile(r"\bOBD\s*2\b", re.IGNORECASE), "OBD-II"),
    (re.compile(r"\bCAN\s*bus\b", re.IGNORECASE), "CAN bus"),
    (re.compile(r"\bground\s*side\b", re.IGNORECASE), "ground-side"),
    (re.compile(r"\bpower\s*supply\b", re.IGNORECASE), "power supply"),
    (re.compile(r"\bmulti\s*meter\b", re.IGNORECASE), "multimeter"),
    (re.compile(r"\bwire\s*harness\b", re.IGNORECASE), "wire harness"),
    (re.compile(r"\bblown\s*fuse\b", re.IGNORECASE), "blown fuse"),
    (re.compile(r"\bair\s*fuel\s*ratio\b", re.IGNORECASE), "air-fuel ratio"),
    (re.compile(r"\bmass\s*air\s*flow\b", re.IGNORECASE), "mass air flow"),
    (re.compile(r"\bthrottle\s*body\b", re.IGNORECASE), "throttle body"),
    (re.compile(r"\bintake\s*manifold\b", re.IGNORECASE), "intake manifold"),
    (re.compile(r"\bexhaust\s*gas\s*recirculation\b", re.IGNORECASE), "exhaust gas recirculation"),
    (re.compile(r"\bvariable\s*valve\s*timing\b", re.IGNORECASE), "variable valve timing"),
]


def clean_transcript(text: str, *, apply_common_fixes: bool = True) -> str:
    """Clean raw transcript text into readable prose.

    Steps:
      1. Strip WEBVTT headers, cue indices, timing arrows.
      2. Remove bracketed/parenthesized noise cues and HTML tags.
      3. Collapse repeated characters, whitespace, blank lines.
      4. Apply common auto-caption term fixes.
    """
    if not text:
        return ""

    cleaned = text
    cleaned = WEBVTT_HEADER_RE.sub("", cleaned)
    cleaned = TIMING_RE.sub(" ", cleaned)
    cleaned = CUE_INDEX_RE.sub(" ", cleaned)
    cleaned = BRACKET_NOISE_RE.sub(" ", cleaned)
    cleaned = PAREN_NOISE_RE.sub(" ", cleaned)
    cleaned = HTML_TAG_RE.sub(" ", cleaned)
    cleaned = TIMESTAMP_INLINE_RE.sub(" ", cleaned)
    cleaned = REPEATED_CHAR_RE.sub(lambda m: m.group(1) * 2, cleaned)

    if apply_common_fixes:
        for pattern, replacement in COMMON_FIXES:
            cleaned = pattern.sub(replacement, cleaned)

    cleaned = MULTI_SPACE_RE.sub(" ", cleaned)
    cleaned = MULTI_NEWLINE_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def join_segments(segments: list[dict], *, max_line_len: int = 140) -> str:
    """Join timestamped segments into flowing paragraphs (~sentence-length lines)."""
    lines: list[str] = []
    buf = ""
    for seg in segments:
        piece = (seg.get("text") or "").strip()
        if not piece:
            continue
        if buf:
            buf += " " + piece
        else:
            buf = piece
        if len(buf) >= max_line_len:
            lines.append(buf)
            buf = ""
    if buf:
        lines.append(buf)
    return "\n".join(lines)


def extract_dtc_codes(text: str) -> list[str]:
    """Find OBD-II DTC codes like P0300, C1234, B1234, U0100."""
    pattern = re.compile(
        r"\b(?P<body>[PCBU])\s*(?P<digits>\d{4})\b", re.IGNORECASE
    )
    codes: list[str] = []
    seen: set[str] = set()
    for m in pattern.finditer(text):
        code = f"{m.group('body').upper()}{m.group('digits')}"
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes
