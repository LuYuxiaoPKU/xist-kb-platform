"""Full-corpus measurement for the "view this section" button.

Answers three questions the plan needs numbers for:
  1. what fraction of papers have a detectable heading at all
  2. for each section, how many claims can actually get its full text
  3. how long is that text (the honest UI label)

Runs over every text file, not a sample -- the plan's own discipline says a
computation that finishes in minutes is never estimated.
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

from xist_kb.extract.sections import CANONICAL, find_sections  # noqa: E402

V2 = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2")
TEXT = V2 / "papers" / "text"

# claims by paper, from the already-migrated Gold layer
import duckdb  # noqa: E402

GOLD = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local\gold")
con = duckdb.connect()
con.execute(f"CREATE VIEW claims AS SELECT * FROM read_parquet('{GOLD / 'claims.parquet'}')")
rows = con.execute("SELECT paper_id, section FROM claims").fetchall()

claims_by_paper: dict[str, Counter] = defaultdict(Counter)
for pid, section in rows:
    claims_by_paper[pid][str(section).lower()] += 1

# text lookup, case-insensitive on purpose: Windows hides the mismatch the
# server will hit, so match on lowercased stems and report the count.
texts: dict[str, Path] = {}
for p in TEXT.iterdir():
    if p.suffix.lower() == ".txt":
        texts[p.stem.lower()] = p

no_heading = 0
heading_counts = Counter()
papers_scanned = 0
section_span_frac: dict[str, list[float]] = defaultdict(list)
claims_total = 0
claims_resolvable = 0
claims_by_section: Counter = Counter()
unresolvable_by_section: Counter = Counter()
text_chars: list[int] = []

for pid, counter in claims_by_paper.items():
    for sec, n in counter.items():
        claims_by_section[sec] += n
        claims_total += n

    text_path = texts.get(pid.lower())
    if text_path is None:
        unresolvable_by_section.update(counter)
        continue

    try:
        text = text_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        unresolvable_by_section.update(counter)
        continue

    papers_scanned += 1
    text_chars.append(len(text))
    sections = find_sections(text)
    if len(sections) < 2:
        no_heading += 1
        unresolvable_by_section.update(counter)
        continue

    for s in sections:
        heading_counts[s.name] += 1
        section_span_frac[s.name].append(s.char_count / max(len(text), 1))

    have = {s.name for s in sections}
    for sec, n in counter.items():
        if sec in have:
            claims_resolvable += n
        else:
            unresolvable_by_section[sec] += n

print(json.dumps({
    "papers_with_claims": len(claims_by_paper),
    "papers_scanned": papers_scanned,
    "papers_with_lt2_headings": no_heading,
    "papers_with_lt2_headings_pct": round(100 * no_heading / max(papers_scanned, 1), 1),
    "text_chars_median": statistics.median(text_chars) if text_chars else 0,
    "claims_total": claims_total,
    "claims_with_section_text": claims_resolvable,
    "claims_with_section_text_pct": round(100 * claims_resolvable / max(claims_total, 1), 1),
    "papers_per_heading": dict(heading_counts.most_common()),
    "section_median_span_pct": {
        k: round(100 * statistics.median(v), 1) for k, v in section_span_frac.items() if v
    },
    "claims_by_section": dict(claims_by_section.most_common()),
    "unresolvable_by_section": dict(unresolvable_by_section.most_common()),
    "canonical_keys": sorted(CANONICAL),
}, ensure_ascii=False, indent=1))
