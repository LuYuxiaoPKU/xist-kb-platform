"""The `/api/claims/{id}/context` contract.

A claim's context is one of two things, never a third:

* a **quote span** -- character offsets into the paper text, for the P tiers,
  where the annotation recorded a quote that was found in the text; or
* a **section body** -- the full text of the section the annotation named, for
  the S tier, because locating a sentence inside a section is not possible
  (measured: 11.6% accuracy, no better than chance in a 626-char window).

There is deliberately no "approximate paragraph" mode. The plan's fifth review
established that claim text cannot be located to a paragraph, and offering one
would put a 11.6%-accurate feature behind a green badge.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ContextKind(StrEnum):
    QUOTE = "quote"  # exact character interval
    SECTION = "section"  # whole section body
    NONE = "none"  # no text, or no heading for the claimed section


class QuoteSpan(BaseModel):
    start: int
    end: int
    text: str


class SectionBody(BaseModel):
    name: str
    heading: str | None = None
    text: str
    char_count: int
    truncated: bool = False
    # A Results section is ~18k characters at the median and 30% of the paper;
    # the UI shows this so the button does not read as "jump to the sentence".
    fraction_of_paper: float = Field(ge=0.0, le=1.0)


class ClaimContext(BaseModel):
    claim_id: str
    paper_id: str
    kind: ContextKind
    # populated for QUOTE
    spans: list[QuoteSpan] = Field(default_factory=list)
    # populated for SECTION
    section: SectionBody | None = None
    # why there is no context, when kind is NONE
    reason: str | None = None
