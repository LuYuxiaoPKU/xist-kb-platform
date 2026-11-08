"""How long is the text the "view section" button would render?

The plan's earlier span figure ("results median 30% of the document") is a
fraction; what the button actually renders is characters, and the reviewer
cares whether 5k (scannable) or 90k (unusable) opens. Measures the per-claim
size distribution so the API truncation limit is chosen from data.
"""

from __future__ import annotations

import io
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\00_Data\实验室\实验室\MetaAnalysis\xist-kb-platform\src")

import pyarrow.parquet as pq  # noqa: E402

from xist_kb.extract.sections import find_sections  # noqa: E402

GOLD = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local\gold")
TEXT = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2\papers\text")

claims = pq.read_table(
    GOLD / "claims.parquet", columns=["paper_id", "quote", "section", "provenance_id"]
).to_pylist()
prov = {
    r["provenance_id"]: r["method"]
    for r in pq.read_table(GOLD / "provenance.parquet").to_pylist()
}
claims = [c for c in claims if prov.get(c["provenance_id"]) != "rule"]

by_paper: dict[str, list[dict]] = defaultdict(list)
for c in claims:
    by_paper[c["paper_id"]].append(c)

texts = {p.stem.lower(): p for p in TEXT.glob("*.txt")}

sizes: list[tuple[str, int, int]] = []  # (section, chars, doc_chars)
no_text = no_heading = 0

for pid, rows in by_paper.items():
    path = texts.get(pid.lower())
    if path is None:
        no_text += len(rows)
        continue
    raw = path.read_text(encoding="utf-8", errors="replace")
    doc = max(len(raw), 1)
    sections = find_sections(raw)
    size = defaultdict(int)
    for s in sections:
        size[s.name] += s.char_count

    for c in rows:
        sec = (c["section"] or "").lower()
        if sec not in {"results", "discussion", "introduction", "methods", "abstract", "conclusion"}:
            continue
        if size.get(sec):
            sizes.append((sec, size[sec], doc))
        else:
            no_heading += 1


def pct(sorted_vals: list[int], q: float) -> int:
    if not sorted_vals:
        return 0
    return sorted_vals[min(int(len(sorted_vals) * q), len(sorted_vals) - 1)]


by_section: dict[str, list[int]] = defaultdict(list)
for sec, n, _ in sizes:
    by_section[sec].append(n)

overall = sorted(n for _, n, _ in sizes)

summary = {
    "claims_with_renderable_section": len(sizes),
    "claims_in_section_with_no_heading": no_heading,
    "claims_no_text": no_text,
    "overall_chars": {
        "median": pct(overall, 0.5),
        "p75": pct(overall, 0.75),
        "p90": pct(overall, 0.9),
        "p95": pct(overall, 0.95),
        "max": overall[-1] if overall else 0,
    },
    "over_limits": {
        str(limit): sum(1 for n in overall if n > limit) for limit in (10000, 20000, 30000, 50000)
    },
    "over_limits_pct": {
        str(limit): round(100 * sum(1 for n in overall if n > limit) / max(len(overall), 1), 1)
        for limit in (10000, 20000, 30000, 50000)
    },
    "by_section_median": {
        k: pct(sorted(v), 0.5) for k, v in sorted(by_section.items())
    },
    "by_section_p90": {k: pct(sorted(v), 0.9) for k, v in sorted(by_section.items())},
}

print(json.dumps(summary, ensure_ascii=False, indent=1))
