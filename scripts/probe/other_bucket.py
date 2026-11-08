"""Why are 35k claims in `other`, and can any of them be classified?

The plan's B10 says "clean `other` from 35,108 to under 15%". That target
assumed the bucket was full of misclassified XIST claims. Before writing a
classifier, read what is in the bucket.

Two things are measured:

1. **Does the claim mention XIST/XCI at all?** A claim that never mentions the
   topic is background material from the paper's introduction, not a
   misclassified XIST claim. Those are not reclassifiable -- there is nothing
   to reclassify them into.
2. **Of those that do mention it, do keyword patterns reach the existing
   topic vocabulary?** That subset is the real target.
"""

from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import duckdb  # noqa: E402

DB = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local_lowercase\index\xist.duckdb")

XIST_TERMS = re.compile(
    r"\b(xist|x-chromosome inactivation|chromosome inactivation|inactive x|"
    r"dosage compensation|xci|x-inactivation)\b",
    re.IGNORECASE,
)

# Patterns for the topics that exist in the vocabulary. A claim matching one of
# these and mentioning XIST is a plausible reclassification; a claim matching
# none is not.
TOPIC_PATTERNS = {
    "xist_protein_interactions": re.compile(
        r"\b(interact\w*|binds?|binding|pulls? down|co-?ip|immunoprecipitat\w*|"
        r"co-?purif\w*|recruits?)\b",
        re.I,
    ),
    "chromatin": re.compile(
        r"\b(chromatin|histone|h3k\d+\w*|h2ak\d+\w*|methylation|acetylation|"
        r"nucleosome|prc[12]|ezh2|polycomb|macroh2a)\b",
        re.I,
    ),
    "nuclear_organization": re.compile(
        r"\b(nuclear (speck|domain|body|lamina|matrix)|compartment|territor\w*|"
        r"looping|topolog\w*|phase separat\w*|condensate)\b",
        re.I,
    ),
    "cancer_biology": re.compile(
        r"\b(tumou?r|cancer|carcinoma|oncogen\w*|metasta\w*|prognos\w*|"
        r"malignan\w*|leukemi\w*|glioma)\b",
        re.I,
    ),
    "early_embryo": re.compile(
        r"\b(blastocyst|blastomere|morula|preimplantation|epiblast|"
        r"inner cell mass|2-cell|8-cell|zygot\w*|oocyte)\b",
        re.I,
    ),
    "m6a": re.compile(r"\b(m6a|n6-methyladenosine|mettl\w*|ythdf\w*|alkbh5)\b", re.I),
    "lncrna": re.compile(
        r"\b(lncrna|long non-?coding|non-?coding rna|ncrna|mirna|sirna|"
        r"antisense|ribozyme|circrna)\b",
        re.I,
    ),
    "xist_evolution": re.compile(
        r"\b(evolution\w*|conserv\w*|ortholog\w*|homolog\w*|phylogen\w*|"
        r"divergen\w*|species-specific)\b",
        re.I,
    ),
}


def main() -> None:
    conn = duckdb.connect(str(DB), read_only=True)
    rows = conn.execute("SELECT claim FROM claims WHERE topic = 'other'").fetchall()
    total = len(rows)

    mentions = 0
    matched_by: Counter = Counter()
    no_match = 0
    examples: dict[str, list[str]] = {}

    for (claim,) in rows:
        if not claim:
            continue
        if not XIST_TERMS.search(claim):
            continue
        mentions += 1
        hits = [topic for topic, pat in TOPIC_PATTERNS.items() if pat.search(claim)]
        if not hits:
            no_match += 1
            continue
        for topic in hits:
            matched_by[topic] += 1
        top = hits[0]
        bucket = examples.setdefault(top, [])
        if len(bucket) < 3:
            bucket.append(claim[:150])

    print(
        json.dumps(
            {
                "other_total": total,
                "mentions_xist": mentions,
                "mentions_xist_pct": round(100 * mentions / max(total, 1), 1),
                "no_xist_mention": total - mentions,
                "no_xist_mention_pct": round(100 * (total - mentions) / max(total, 1), 1),
                # Of the claims that mention XIST, only those that also match a
                # topic pattern are candidates for reclassification.
                "classifiable": mentions - no_match,
                "classifiable_pct_of_all": round(100 * (mentions - no_match) / max(total, 1), 2),
                "matched_by_topic": dict(matched_by.most_common()),
                "mentions_but_no_topic_match": no_match,
                "examples": examples,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
