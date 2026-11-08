"""Stress-test the section splitter and pick the guards that keep it honest.

Two pathologies found on the full corpus:

* headings repeat ("Results" twice is legitimate; "Methods" reappearing at 99%
  of the document is a stray), and
* reference lists sometimes sit mid-document, so whatever heading precedes them
  swallows the whole front matter (one paper's "Abstract" was 23,158 chars).

This measures each pathology and what a span guard would cost, so the plan can
quote the post-guard number rather than the optimistic one.
"""

from __future__ import annotations

import io
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\00_Data\实验室\实验室\MetaAnalysis\xist-kb-platform\src")

from xist_kb.extract.sections import find_sections  # noqa: E402

TEXT = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2\papers\text")

dupe = Counter()
backwards = 0  # references/acknowledgements appearing before content headings
abstract_huge = 0
abstract_total = 0
span_before: dict[str, list[float]] = defaultdict(list)
span_after: dict[str, list[float]] = defaultdict(list)

for p in TEXT.glob("*.txt"):
    raw = p.read_text(encoding="utf-8", errors="replace")
    total = max(len(raw), 1)
    sections = find_sections(raw)
    if len(sections) < 2:
        continue

    names = [s.name for s in sections]
    for name, count in Counter(names).items():
        if count > 1:
            dupe[name] += 1

    # a reference list in the first 40% with content headings after it
    tail = {"references", "acknowledgements"}
    for i, s in enumerate(sections):
        if s.name in tail and s.heading_start / total < 0.4:
            if any(t.name not in tail for t in sections[i + 1 :]):
                backwards += 1
                break

    for s in sections:
        frac = s.char_count / total
        span_before[s.name].append(frac)
        if s.name == "abstract":
            abstract_total += 1
            if frac > 0.10:
                abstract_huge += 1
        # guard: a section larger than half the paper has no usable boundary
        if frac <= 0.50:
            span_after[s.name].append(frac)

print(json.dumps({
    "papers_with_duplicate_headings": dict(dupe.most_common()),
    "papers_with_middocument_reference_list": backwards,
    "abstract_over_10pct": abstract_huge,
    "abstract_total": abstract_total,
    "span_median_pct_before_guard": {
        k: round(100 * statistics.median(v), 1) for k, v in span_before.items() if v
    },
    "span_median_pct_after_guard": {
        k: round(100 * statistics.median(v), 1) for k, v in span_after.items() if v
    },
    "sections_dropped_by_guard": {
        k: len(span_before[k]) - len(span_after[k]) for k in span_before
    },
}, ensure_ascii=False, indent=1))
