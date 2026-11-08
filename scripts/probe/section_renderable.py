"""Cross the tier partition with section-text availability.

The "view this section" button only exists for the S tier, so the number that
matters is not 53.5% of all claims -- it is how many of the S-tier claims can
actually render their section. Produces the per-tier table the plan quotes.
"""

from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\00_Data\实验室\实验室\MetaAnalysis\xist-kb-platform\src")

import pyarrow.parquet as pq  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

from xist_kb.extract.sections import find_sections  # noqa: E402

GOLD = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local\gold")
V2 = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2")

WS = re.compile(r"\s+")
WORD = re.compile(r"[A-Za-z]{4,}")


def norm(s: str) -> str:
    return WS.sub(" ", s).strip().lower()


claims = pq.read_table(
    GOLD / "claims.parquet",
    columns=["claim_id", "paper_id", "quote", "section", "provenance_id"],
).to_pylist()
prov = {
    r["provenance_id"]: r["method"]
    for r in pq.read_table(GOLD / "provenance.parquet").to_pylist()
}
real = [c for c in claims if prov.get(c["provenance_id"]) != "rule"]

by_paper: dict[str, list[dict]] = defaultdict(list)
for c in real:
    by_paper[c["paper_id"]].append(c)

# file lookup by lowercased stem, mirroring the server's case-sensitive reality
texts = {p.stem.lower(): p for p in (V2 / "papers" / "text").glob("*.txt")}


def fuzzy(text: str, quote: str, window: int = 400) -> tuple[float, str]:
    tokens = WORD.findall(quote)
    if not tokens:
        return 0.0, ""
    anchor = max(tokens, key=len)
    best, best_window, pos = 0.0, "", 0
    while True:
        i = text.find(anchor, pos)
        if i < 0:
            break
        lo, hi = max(0, i - window), min(len(text), i + len(anchor) + window)
        windowslice = text[lo:hi]
        score = fuzz.partial_ratio(quote, windowslice)
        if score > best:
            best, best_window = score, windowslice
        pos = i + len(anchor)
        if best >= 95:
            break
    return best, best_window


tier_counts: Counter = Counter()
# for each tier: how many claims could render their section text
renderable: Counter = Counter()
# S tier broken down by section, with renderability
s_by_section: dict[str, Counter] = defaultdict(Counter)
span_by_section: dict[str, list[float]] = defaultdict(list)

for pid, rows in by_paper.items():
    path = texts.get(pid.lower())
    if path is None:
        for c in rows:
            tier_counts["C_no_text"] += 1
        continue

    raw = path.read_text(encoding="utf-8", errors="replace")
    tn = norm(raw)
    sections = find_sections(raw)
    names = {s.name for s in sections}
    span = {s.name: s.char_count / max(len(raw), 1) for s in sections}

    for c in rows:
        quote = norm(c["quote"] or "")
        tier = None
        if quote and len(quote) >= 20:
            n = tn.count(quote)
            if n == 1:
                tier = "P1"
            elif n > 1:
                tier = "P2"
            else:
                score, win = fuzzy(tn, quote)
                qwords = set(WORD.findall(quote))
                overlap = len(qwords & set(WORD.findall(win))) / len(qwords) if qwords else 0
                if score >= 90 and overlap >= 0.8:
                    tier = "P3"

        if tier is None:
            sec = (c["section"] or "").lower()
            if sec in {"results", "discussion", "introduction", "methods", "abstract", "conclusion"}:
                if sec in names:
                    tier = "S_renderable"
                    renderable["S"] += 1
                    s_by_section[sec]["renderable"] += 1
                    span_by_section[sec].append(span[sec])
                else:
                    tier = "S_no_heading"
                    s_by_section[sec]["no_heading"] += 1
            else:
                tier = "C_no_section"

        tier_counts[tier] += 1
        if tier == "S_renderable":
            s_by_section[(c["section"] or "").lower()]["total"] += 1
        elif tier == "S_no_heading":
            s_by_section[(c["section"] or "").lower()]["total"] += 1

total = sum(tier_counts.values())
print(json.dumps({
    "total_non_rule_claims": total,
    "tiers": dict(tier_counts.most_common()),
    "tiers_pct": {k: round(100 * v / total, 1) for k, v in tier_counts.most_common()},
    "s_tier_total": tier_counts["S_renderable"] + tier_counts["S_no_heading"],
    "s_renderable": tier_counts["S_renderable"],
    "s_renderable_pct_of_s": round(
        100 * tier_counts["S_renderable"] / max(tier_counts["S_renderable"] + tier_counts["S_no_heading"], 1), 1
    ),
    "s_renderable_pct_of_all": round(100 * tier_counts["S_renderable"] / total, 1),
    "s_by_section": {k: dict(v) for k, v in s_by_section.items()},
    "s_span_median_pct": {
        k: round(100 * sorted(v)[len(v) // 2], 1) for k, v in span_by_section.items() if v
    },
}, ensure_ascii=False, indent=1))
