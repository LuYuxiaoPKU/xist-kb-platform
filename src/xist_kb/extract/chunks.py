"""Sentence windows: the retrieval unit for search and Q&A.

V2's text has no usable paragraphs -- PDF extraction drops most blank lines, so
the median paper has 7 "paragraphs" and the 90th-percentile block is 9,082
characters (one block routinely swallows half the Results). Measured in review
round 5.

The replacement is fixed-size windows cut on sentence boundaries: split after
terminal punctuation, then merge consecutive sentences until the window reaches
~700 characters. Measured on the full corpus this gives a median of 74 windows
per paper and a median window of 626 characters -- small enough that a search
hit is readable, large enough that a sentence is not orphaned from its setup.

Windows are derived data: they can be rebuilt from the text files at any time and
are never the source of truth for a claim's provenance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TARGET_CHARS = 700

# A sentence ends at . ! ? followed by whitespace. Abbreviations ("et al.",
# "Fig.", "i.e.") would split too early; the merge step below repairs that by
# gluing short fragments onto their neighbour, so no abbreviation list is
# needed -- which matters because the corpus spans 50 years of style.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Windows shorter than this are merged into the previous one rather than kept:
# a 40-character window is a reference fragment or a stray caption line and
# matches nothing useful on its own.
MIN_CHARS = 200


@dataclass(frozen=True)
class Window:
    index: int  # ordinal within the paper, 0-based
    start: int  # character offset into the paper text
    end: int
    text: str


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) offsets of sentences, whitespace-trimmed."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for match in _SENTENCE_END.finditer(text):
        spans.append((pos, match.start()))
        pos = match.end()
    spans.append((pos, len(text)))

    out: list[tuple[int, int]] = []
    for start, end in spans:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            out.append((start, end))
    return out


def make_windows(text: str, target: int = TARGET_CHARS) -> list[Window]:
    """Cut the text into ~`target`-character windows on sentence boundaries.

    A single sentence longer than `target` becomes its own window rather than
    being truncated: cutting mid-sentence would produce a span whose text no
    longer appears in the paper, which the provenance layer forbids.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []

    windows: list[Window] = []
    start: int | None = None
    end = 0
    for sent_start, sent_end in sentences:
        if start is None:
            start, end = sent_start, sent_end
            continue
        if end - start >= target:
            windows.append(Window(len(windows), start, end, text[start:end]))
            start, end = sent_start, sent_end
        else:
            end = sent_end

    if start is not None:
        if windows and end - start < MIN_CHARS:
            # fold a trailing fragment into the previous window
            prev = windows.pop()
            windows.append(Window(prev.index, prev.start, end, text[prev.start:end]))
        else:
            windows.append(Window(len(windows), start, end, text[start:end]))
    return windows


def window_for_offset(windows: list[Window], offset: int) -> Window | None:
    """The window containing a character offset, if any.

    Used to attach a located quote to the search unit that contains it, so a
    search result and a claim quote point at the same piece of text.
    """
    for window in windows:
        if window.start <= offset < window.end:
            return window
    return None
