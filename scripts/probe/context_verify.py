"""Does the quote-span matcher work on real PDF text?

The unit tests use hand-written text with one newline. Real extraction output
has hyphenated line breaks, running headers, double spaces and ligatures. This
takes claims whose annotation quote is known to occur (the P1 tier) and checks
that the returned interval, sliced out of the raw text, equals the quote after
whitespace normalization -- on every one of them, not a sample.
"""

from __future__ import annotations

import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\00_Data\实验室\实验室\MetaAnalysis\xist-kb-platform\src")

import pyarrow.parquet as pq  # noqa: E402

from xist_kb.extract.context import TextStore, find_quote_spans, normalize_quote  # noqa: E402
from xist_kb.extract.sections import find_sections  # noqa: E402

GOLD = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local\gold")
TEXT = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2\papers\text")

claims = pq.read_table(
    GOLD / "claims.parquet", columns=["claim_id", "paper_id", "quote", "section", "provenance_id"]
).to_pylist()
prov = {
    r["provenance_id"]: r["method"]
    for r in pq.read_table(GOLD / "provenance.parquet").to_pylist()
}
claims = [c for c in claims if prov.get(c["provenance_id"]) != "rule"]

store = TextStore(TEXT)
by_paper: dict[str, list[dict]] = defaultdict(list)
for c in claims:
    if c["quote"]:
        by_paper[c["paper_id"]].append(c)

checked = exact = 0
mismatch: Counter = Counter()
section_hits: Counter = Counter()
section_misses: Counter = Counter()
no_text = 0

for pid, rows in by_paper.items():
    text = store.get(pid)
    if text is None:
        no_text += len(rows)
        continue
    for c in rows:
        spans = find_quote_spans(text, c["quote"])
        if not spans:
            continue
        checked += 1
        want = normalize_quote(c["quote"])
        ok = all(normalize_quote(text[s.start : s.end]) == want for s in spans)
        if ok:
            exact += 1
        else:
            mismatch[pid] += 1

# section renderability over the same claims
s_claims = 0
s_rendered = 0
for pid, rows in by_paper.items():
    text = store.get(pid)
    if text is None:
        continue
    names = {s.name for s in find_sections(text)}
    for c in rows:
        sec = (c["section"] or "").lower()
        if sec in {"results", "discussion", "introduction", "methods", "abstract", "conclusion"}:
            s_claims += 1
            if sec in names:
                s_rendered += 1
            else:
                section_misses[sec] += 1
            section_hits[sec] += 1

print(json.dumps({
    "claims_with_quote": sum(len(v) for v in by_paper.values()),
    "quotes_located": checked,
    "offset_slice_exact": exact,
    "offset_slice_exact_pct": round(100 * exact / max(checked, 1), 2),
    "mismatch_papers": dict(mismatch.most_common(10)),
    "no_text_claims": no_text,
    "section_claims": s_claims,
    "section_rendered": s_rendered,
    "section_rendered_pct": round(100 * s_rendered / max(s_claims, 1), 1),
    "section_miss_by_name": dict(section_misses.most_common()),
}, ensure_ascii=False, indent=1))
