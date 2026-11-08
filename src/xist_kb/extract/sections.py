"""Split extracted paper text into named sections.

The "view this section" button needs the section body, and V2's text has no
structure metadata — only whatever headings the PDF extraction preserved. This
finds headings by matching a whole line against the small set of section names
that papers actually use, which is stricter than searching for the keyword
anywhere (that matches body sentences like "results in the complete
inactivation of ...").

Measured on all 13,502 text files: 75% have at least two detectable headings.
For the remaining 25% there is no reliable section boundary, and callers get
None rather than a guess.

Two pathologies measured on the full corpus, both handled below:

* 284 papers have a reference list somewhere in the first 40% (a PDF header
  artefact, or references printed before the body). Taken as a boundary it
  makes the preceding heading swallow the whole front matter — one paper's
  abstract came out at 23,158 characters. Reference lists are only accepted as
  boundaries in the last half of the document.
* 1,144 papers repeat a heading ("Introduction" twice is common in reviews and
  in PDFs that print the section name in the running header). Repeats are kept
  as separate sections; `get_section_text` concatenates them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Whole-line heading. Accepts numbering ("2. Results", "3.1 Methods") and a
# trailing colon, since both appear in extracted text.
_HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?"
    r"(abstract|summary|introduction|background|results|results and discussion|"
    r"discussion|materials and methods|methods|method|experimental procedures|"
    r"conclusion|conclusions|references|acknowledgements?|acknowledgments?|"
    r"supplementary)\s*:?\s*$",
    re.IGNORECASE,
)

# Map headings onto the vocabulary used in claim annotations, which is the
# coarser set the LLM annotation template asks for.
CANONICAL = {
    "abstract": "abstract",
    "summary": "abstract",
    "introduction": "introduction",
    "background": "introduction",
    "results": "results",
    "results and discussion": "results",
    "discussion": "discussion",
    "materials and methods": "methods",
    "methods": "methods",
    "method": "methods",
    "experimental procedures": "methods",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "references": "references",
    "acknowledgement": "acknowledgements",
    "acknowledgements": "acknowledgements",
    "acknowledgment": "acknowledgements",
    "acknowledgments": "acknowledgements",
    "supplementary": "supplementary",
}

# Sections a claim can be attributed to. References and acknowledgements are
# detected so they can act as end boundaries, but are never a claim's home.
CLAIM_SECTIONS = frozenset(
    {"abstract", "introduction", "results", "discussion", "methods", "conclusion"}
)

# Headings that only count as a boundary in the back half of a paper. A
# "References" line at 20% of the document is a running-header artefact, not
# the end of the body.
BACK_MATTER = frozenset({"references", "acknowledgements", "supplementary"})


@dataclass(frozen=True)
class Section:
    name: str  # canonical name
    heading: str  # heading line as it appears in the text
    heading_start: int  # character offset of the heading line
    body_start: int  # character offset where the body begins
    body_end: int  # exclusive

    @property
    def char_count(self) -> int:
        return self.body_end - self.body_start


def find_sections(text: str) -> list[Section]:
    """Return sections in document order.

    Headings that repeat (a paper with two "Discussion" blocks) are kept as
    separate sections; callers that want one body per name should concatenate
    them. Back-matter headings in the front half of the document are ignored so
    they don't cut the body short.
    """
    total = max(len(text), 1)
    found: list[tuple[str, str, int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        match = _HEADING.match(line.rstrip("\r\n"))
        if match:
            canonical = CANONICAL.get(match.group(1).lower())
            if canonical:
                if canonical in BACK_MATTER and offset / total < 0.5:
                    offset += len(line)
                    continue
                found.append((canonical, line.strip(), offset, offset + len(line)))
        offset += len(line)

    sections: list[Section] = []
    for i, (name, heading, start, body_start) in enumerate(found):
        body_end = found[i + 1][2] if i + 1 < len(found) else len(text)
        sections.append(
            Section(
                name=name,
                heading=heading,
                heading_start=start,
                body_start=body_start,
                body_end=body_end,
            )
        )
    return sections


def get_section_text(text: str, name: str, *, include_heading: bool = True) -> str | None:
    """Return the concatenated body of every section called `name`.

    Returns None when the paper has no detectable heading for that name, so the
    caller can say "the annotation says Results but the text has no Results
    heading" instead of silently returning the wrong chunk of text.
    """
    wanted = CANONICAL.get(name.lower(), name.lower())
    matching = [s for s in find_sections(text) if s.name == wanted]
    if not matching:
        return None

    parts = []
    for section in matching:
        if include_heading:
            parts.append(text[section.heading_start : section.body_start].strip())
        parts.append(text[section.body_start : section.body_end].strip())
    return "\n\n".join(p for p in parts if p)


def section_spans(sections: list[Section], total_chars: int) -> list[dict]:
    """Section extents as fractions of the document, for the honest UI label.

    The web UI shows "Results — 30% of the paper", because jumping to a section
    that spans a third of the text is not the same as locating a sentence.
    """
    total = max(total_chars, 1)
    return [
        {
            "name": s.name,
            "heading": s.heading,
            "char_count": s.char_count,
            "fraction": round(s.char_count / total, 3),
        }
        for s in sections
    ]
