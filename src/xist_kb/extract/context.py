"""Build a claim's context: quote spans or section body.

Reads paper text from the V2 tree and answers the question the UI asks when the
reviewer clicks "show me where this came from". The two branches mirror the
tier definitions in the plan:

* the quote is found in the text -> return every character interval where it
  occurs (a quote appearing twice is ambiguity the caller must display, not
  hide); or
* there is no locatable quote but the annotation named a section -> return that
  section's body, honestly labelled with its size.

No fuzzy matching here. Fuzzy spans are a separate provenance tier computed at
migration time and stored on the claim; this module only serves what it can
prove from the text.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import duckdb

from xist_kb.extract.sections import CLAIM_SECTIONS, find_sections
from xist_kb.models_context import (
    ClaimContext,
    ContextKind,
    QuoteSpan,
    SectionBody,
)

# The median renderable section is 18k characters; anything past this cap is a
# boundary-detection failure (a section that swallowed the rest of the paper),
# not a section a human will read in a panel.
MAX_SECTION_CHARS = 60_000


@dataclass(frozen=True)
class NormalizedText:
    """A whitespace-collapsed, lowercased copy plus the offset of every char.

    PDF extraction reflows lines, so a quote from the annotation never matches
    byte-for-byte: the same sentence may be split across lines with a hyphen or
    extra spaces. Matching on a normalized copy and mapping the hit back through
    `orig_offsets` gives exact character intervals without fuzzy scoring.
    """

    text: str
    orig_offsets: tuple[int, ...]

    def span(self, start: int, end: int) -> tuple[int, int]:
        """Map a normalized [start, end) back to original offsets."""
        return self.orig_offsets[start], self.orig_offsets[end - 1] + 1


@lru_cache(maxsize=256)
def normalize_text(text: str) -> NormalizedText:
    chars: list[str] = []
    offsets: list[int] = []
    prev_space = True  # leading whitespace is dropped
    for index, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            chars.append(" ")
            offsets.append(index)
            prev_space = True
        else:
            # str.lower() usually maps one character to one, but a few (İ, ẞ)
            # expand; appending the index once per resulting character keeps
            # `offsets` aligned with `chars`.
            lowered = ch.lower()
            chars.extend(lowered)
            offsets.extend([index] * len(lowered))
            prev_space = False
    # trailing space, if any, is harmless: quotes are stripped before lookup
    return NormalizedText("".join(chars), tuple(offsets))


def normalize_quote(quote: str) -> str:
    return " ".join(quote.split()).lower()


class TextStore:
    """Paper text by lowercased stem.

    On the lab server the filesystem is case sensitive and 864 text files
    contain uppercase in their names, so a naive `<paper_id>.txt` lookup fails
    for those papers there while working on Windows. Indexing by lowercased
    stem is what makes the two platforms agree. When a `paper_id_map` table is
    available (`from_map`), the exact on-disk name comes from there instead.
    """

    def __init__(self, text_dir: Path | str, names: dict[str, str] | None = None):
        self.text_dir = Path(text_dir)
        self._names = names  # canonical id -> on-disk stem, when known
        self._index: dict[str, Path] | None = None

    @classmethod
    def from_map(
        cls, text_dir: Path | str, conn: duckdb.DuckDBPyConnection
    ) -> TextStore:
        """Build a store whose file names come from gold/paper_id_map.parquet."""
        try:
            rows = conn.execute(
                "SELECT paper_id, text_file FROM paper_id_map WHERE text_file IS NOT NULL"
            ).fetchall()
        except duckdb.CatalogException:
            return cls(text_dir)
        return cls(text_dir, {pid: stem for pid, stem in rows})

    def _build(self) -> dict[str, Path]:
        index: dict[str, Path] = {}
        if self.text_dir.is_dir():
            for path in self.text_dir.iterdir():
                if path.suffix.lower() == ".txt":
                    index[path.stem.lower()] = path
        return index

    def get(self, paper_id: str) -> str | None:
        key = paper_id.lower()
        path: Path | None = None
        if self._names is not None:
            stem = self._names.get(key)
            if stem is not None:
                path = self.text_dir / f"{stem}.txt"
                if not path.exists():
                    path = None
        if path is None:
            if self._index is None:
                self._index = self._build()
            path = self._index.get(key)
        if path is None:
            return None
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None


def find_quote_spans(text: str, quote: str) -> list[QuoteSpan]:
    """Every exact occurrence of `quote`, matched whitespace-insensitively.

    An empty list means "not found", not "no such claim": the caller decides
    whether to fall back to the section. Quotes shorter than 20 characters are
    refused outright -- a two-word quote matches everywhere and would produce
    dozens of meaningless highlights.
    """
    normalized_quote = normalize_quote(quote)
    if len(normalized_quote) < 20:
        return []

    haystack = normalize_text(text)
    spans: list[QuoteSpan] = []
    pos = 0
    while True:
        at = haystack.text.find(normalized_quote, pos)
        if at < 0:
            break
        start, end = haystack.span(at, at + len(normalized_quote))
        spans.append(QuoteSpan(start=start, end=end, text=text[start:end]))
        pos = at + len(normalized_quote)
    return spans


def build_context(
    claim_id: str,
    paper_id: str,
    quote: str | None,
    section: str | None,
    text: str | None,
) -> ClaimContext:
    """Resolve one claim to a quote span, a section body, or nothing."""
    if text is None:
        return ClaimContext(
            claim_id=claim_id,
            paper_id=paper_id,
            kind=ContextKind.NONE,
            reason="full text not available for this paper",
        )

    if quote:
        spans = find_quote_spans(text, quote)
        if spans:
            return ClaimContext(
                claim_id=claim_id, paper_id=paper_id, kind=ContextKind.QUOTE, spans=spans
            )

    wanted = (section or "").lower()
    if wanted in CLAIM_SECTIONS:
        matching = [s for s in find_sections(text) if s.name == wanted]
        if matching:
            body = "\n\n".join(text[s.body_start : s.body_end].strip() for s in matching)
            char_count = len(body)
            truncated = char_count > MAX_SECTION_CHARS
            if truncated:
                body = body[:MAX_SECTION_CHARS]
            return ClaimContext(
                claim_id=claim_id,
                paper_id=paper_id,
                kind=ContextKind.SECTION,
                section=SectionBody(
                    name=wanted,
                    heading=matching[0].heading,
                    text=body,
                    char_count=char_count,
                    truncated=truncated,
                    fraction_of_paper=round(
                        sum(s.char_count for s in matching) / max(len(text), 1), 3
                    ),
                ),
            )
        reason = f"annotation says {wanted!r} but the text has no such heading"
    elif quote:
        reason = "quote not found in the paper text, and no section to fall back to"
    else:
        reason = "the annotation recorded neither a locatable quote nor a section"

    return ClaimContext(
        claim_id=claim_id, paper_id=paper_id, kind=ContextKind.NONE, reason=reason
    )
