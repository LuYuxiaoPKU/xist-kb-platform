"""What does making paper_id lowercase actually cost?

The decision is to use a lowercase canonical paper_id. Before writing any code
this measures the three things that could make that decision wrong:

  1. **Collisions.** Two distinct ids that differ only by case would merge into
     one paper and one of them would lose its claims. On Windows the
     filesystem hides this (one file, two spellings); in Parquet it does not.
  2. **Resolution.** How many claims currently fail to find a text file, and
     how many of those start working once both sides are lowercased.
  3. **Renames.** How many files on disk have an uppercase stem, i.e. how much
     renaming the plan's v7 text assumed.

Every number is a full count over the corpus.
"""

from __future__ import annotations

import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pyarrow.parquet as pq  # noqa: E402

GOLD = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local\gold")
V2 = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2")

papers = pq.read_table(GOLD / "papers.parquet", columns=["paper_id"]).column("paper_id").to_pylist()
claims = (
    pq.read_table(GOLD / "claims.parquet", columns=["paper_id"]).column("paper_id").to_pylist()
)

paper_ids = set(papers)
claim_ids = set(claims)


def collisions(ids: set[str]) -> dict[str, list[str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for pid in ids:
        groups[pid.lower()].add(pid)
    return {low: sorted(group) for low, group in groups.items() if len(group) > 1}


paper_collisions = collisions(paper_ids)
claim_collisions = collisions(claim_ids)
union_collisions = collisions(paper_ids | claim_ids)


def stems(directory: Path, suffix: str) -> set[str]:
    if not directory.is_dir():
        return set()
    return {p.stem for p in directory.iterdir() if p.suffix.lower() == suffix}


json_stems = stems(V2 / "notes" / "json", ".json")
text_stems = stems(V2 / "papers" / "text", ".txt")
pdf_stems = stems(V2 / "papers" / "pdf", ".pdf")

# how many claims find their text file, before and after lowercasing
text_exact = {s.lower(): s for s in text_stems}
before = sum(1 for pid in claim_ids if pid in text_stems)
after = sum(1 for pid in claim_ids if pid.lower() in text_exact)

# claims whose paper is in the registry
orphans_before = sum(1 for pid in claim_ids if pid not in paper_ids)
paper_lower = {pid.lower() for pid in paper_ids}
orphans_after = sum(1 for pid in claim_ids if pid.lower() not in paper_lower)

# the other direction: registry papers that would now collide with each other
upper_papers = sorted(pid for pid in paper_ids if pid != pid.lower())
upper_claims = sorted(pid for pid in claim_ids if pid != pid.lower())
upper_json = sorted(s for s in json_stems if s != s.lower())
upper_text = sorted(s for s in text_stems if s != s.lower())
upper_pdf = sorted(s for s in pdf_stems if s != s.lower())

report = {
    "papers_total": len(paper_ids),
    "papers_with_uppercase": len(upper_papers),
    "papers_uppercase_share_pct": round(100 * len(upper_papers) / max(len(paper_ids), 1), 2),
    "claims_distinct_paper_ids": len(claim_ids),
    "claims_with_uppercase_paper_id": len(upper_claims),
    "json_stems": len(json_stems),
    "json_stems_with_uppercase": len(upper_json),
    "text_stems": len(text_stems),
    "text_stems_with_uppercase": len(upper_text),
    "pdf_stems": len(pdf_stems),
    "pdf_stems_with_uppercase": len(upper_pdf),
    "collisions_in_papers": paper_collisions,
    "collisions_in_claims": claim_collisions,
    "collisions_in_union": union_collisions,
    "collision_count_union": len(union_collisions),
    "claims_text_resolved_before": before,
    "claims_text_resolved_after": after,
    "claims_text_gained": after - before,
    "claims_still_unresolved": len(claim_ids) - after,
    "claims_orphan_before": orphans_before,
    "claims_orphan_after": orphans_after,
    "claims_orphan_resolved_by_lower": orphans_before - orphans_after,
    "sample_uppercase_papers": upper_papers[:10],
    "sample_uppercase_claims": upper_claims[:10],
    "sample_uppercase_json": upper_json[:10],
}

print(json.dumps(report, ensure_ascii=False, indent=1))
