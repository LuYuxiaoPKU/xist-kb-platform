"""Assign every claim a provenance tier by trying to locate it, not by guessing.

The tier is a statement about what the system can *prove*, so the order of
attempts matters: locate first, classify the residue second. An earlier design
classified quotes as "looks like a sentence" vs "looks like a label" before
searching, and that classifier was unmeasurable -- two implementations of it
disagreed on 1.3 million claims' worth of tiers.

Tiers (measured on the full corpus):

    P1  quote found exactly once           "the paper says this sentence"
    P2  quote found several times          "the paper says this N times"
    P3  fuzzy match, high score + overlap  "close to this sentence"
    S   no locatable quote, section known  "annotated as Results, not located"
    C   neither                            "not located"
    K   rule-extraction keyword tag        not a claim at all

`S` is split for the UI only by whether the section body can be rendered
(`section_renderable`); it is one tier, because jumping into a section that
spans 30% of the paper is not locating anything.

Writes `gold/claim_provenance.parquet`. `claims.parquet` stays untouched: its
schema is a frozen contract, and provenance is derived data that can be rebuilt
whenever the matcher improves.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rapidfuzz import fuzz  # noqa: E402

from xist_kb.extract.context import (  # noqa: E402
    TextStore,
    find_quote_spans,
    normalize_text,
)
from xist_kb.extract.sections import CLAIM_SECTIONS, find_sections  # noqa: E402

log = logging.getLogger("tiers")

CLAIM_PROVENANCE_SCHEMA = pa.schema(
    [
        ("claim_id", pa.string()),
        ("paper_id", pa.string()),
        ("tier", pa.string()),
        ("span_start", pa.int32()),  # first located occurrence, P1/P2/P3
        ("span_end", pa.int32()),
        ("span_count", pa.int32()),  # how many occurrences were found
        ("fuzzy_score", pa.int32()),  # P3 only, 0-100
        ("section_renderable", pa.bool_()),  # S only: can the UI show the section
        ("chunk_index", pa.int32()),  # window containing span_start, when known
    ]
)

FUZZY_MIN_SCORE = 90
FUZZY_MIN_OVERLAP = 0.8
# Quotes shorter than this are not quotes: "Results", "Fig 2", "not shown".
# find_quote_spans refuses them for the same reason -- they match everywhere --
# and fuzzy-matching them would be worse, so they fall straight to the section
# tier.
MIN_QUOTE_CHARS = 20
_WORD = re.compile(r"[A-Za-z]{4,}")


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def fuzzy_locate(text: str, quote: str, window: int = 400) -> tuple[int, int, int]:
    """Best fuzzy match: (score, start, end) in ORIGINAL text offsets.

    Scoring runs on the whitespace-normalized copy (PDF line breaks would
    otherwise cap every score), and the resulting interval is mapped back
    through `normalize_text` so the offsets index the real string.

    The interval is the *alignment*, not the whole window: `partial_ratio`
    only scores a window, and returning that window as the span would highlight
    800 characters where the match is 70. Measured: window-sized P3 spans had a
    median of 812 chars, vs 59 for a P1 quote.
    """
    tokens = _WORD.findall(_norm(quote))
    if not tokens:
        return 0, 0, 0
    anchor = max(tokens, key=len)
    haystack = normalize_text(text)
    best_score, best_span = 0, (0, 0)
    pos = 0
    while True:
        i = haystack.text.find(anchor, pos)
        if i < 0:
            break
        lo, hi = max(0, i - window), min(len(haystack.text), i + len(anchor) + window)
        candidate = haystack.text[lo:hi]
        score = fuzz.partial_ratio(_norm(quote), candidate)
        if score > best_score:
            overlap_pool = set(_WORD.findall(candidate))
            overlap = len(set(tokens) & overlap_pool) / len(set(tokens))
            if score >= FUZZY_MIN_SCORE and overlap >= FUZZY_MIN_OVERLAP:
                best_score = int(score)
                alignment = fuzz.partial_ratio_alignment(_norm(quote), candidate)
                if alignment is not None and alignment.dest_end > alignment.dest_start:
                    best_span = haystack.span(
                        lo + alignment.dest_start, lo + alignment.dest_end
                    )
                else:
                    best_span = haystack.span(lo, hi)
        pos = i + len(anchor)
        if best_score >= 99:
            break
    return best_score, best_span[0], best_span[1]


def build(claims_path: Path, provenance_path: Path, text_dir: Path, out_path: Path) -> dict:
    claims = pq.read_table(
        claims_path,
        columns=["claim_id", "paper_id", "claim", "quote", "section", "provenance_id"],
    ).to_pylist()
    methods = {
        r["provenance_id"]: r["method"]
        for r in pq.read_table(provenance_path, columns=["provenance_id", "method"]).to_pylist()
    }

    store = TextStore(text_dir)
    by_paper: dict[str, list[dict]] = defaultdict(list)
    for c in claims:
        by_paper[c["paper_id"]].append(c)

    rows: list[dict] = []
    tiers: Counter = Counter()
    text_cache: dict[str, str | None] = {}

    for paper_id, paper_claims in by_paper.items():
        text = text_cache.get(paper_id, store.get(paper_id))
        text_cache[paper_id] = text
        sections = find_sections(text) if text else []
        section_names = {s.name for s in sections}

        for c in paper_claims:
            is_rule = methods.get(c["provenance_id"]) == "rule"
            base = {
                "claim_id": c["claim_id"],
                "paper_id": paper_id,
                "span_start": None,
                "span_end": None,
                "span_count": None,
                "fuzzy_score": None,
                "section_renderable": None,
                "chunk_index": None,
            }

            if is_rule:
                tiers["K"] += 1
                rows.append({**base, "tier": "K"})
                continue

            if text is None:
                tiers["C_no_text"] += 1
                rows.append({**base, "tier": "C_no_text"})
                continue

            quote = c["quote"]
            if quote:
                spans = find_quote_spans(text, quote)
                if len(spans) == 1:
                    tiers["P1"] += 1
                    rows.append(
                        {
                            **base,
                            "tier": "P1",
                            "span_start": spans[0].start,
                            "span_end": spans[0].end,
                            "span_count": 1,
                        }
                    )
                    continue
                if len(spans) > 1:
                    tiers["P2"] += 1
                    rows.append(
                        {
                            **base,
                            "tier": "P2",
                            "span_start": spans[0].start,
                            "span_end": spans[0].end,
                            "span_count": len(spans),
                        }
                    )
                    continue
                score, fstart, fend = fuzzy_locate(text, quote)
                if score and len(_norm(quote)) >= MIN_QUOTE_CHARS:
                    tiers["P3"] += 1
                    rows.append(
                        {
                            **base,
                            "tier": "P3",
                            "span_start": fstart,
                            "span_end": fend,
                            "span_count": 1,
                            "fuzzy_score": score,
                        }
                    )
                    continue

            section = (c["section"] or "").lower()
            if section in CLAIM_SECTIONS:
                renderable = section in section_names
                tiers["S"] += 1
                rows.append({**base, "tier": "S", "section_renderable": renderable})
            else:
                tiers["C_no_section"] += 1
                rows.append({**base, "tier": "C_no_section"})

    # attach the chunk that contains the located span
    chunks_path = out_path.parent / "chunks.parquet"
    if chunks_path.exists():
        windows: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
        for r in pq.read_table(
            chunks_path, columns=["paper_id", "chunk_index", "start", "end"]
        ).to_pylist():
            windows[r["paper_id"]].append((r["start"], r["end"], r["chunk_index"]))
        for row in rows:
            if row["span_start"] is None:
                continue
            for start, end, index in windows.get(row["paper_id"], []):
                if start <= row["span_start"] < end:
                    row["chunk_index"] = index
                    break

    table = pa.Table.from_pylist(rows, CLAIM_PROVENANCE_SCHEMA)
    tmp = out_path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, out_path)

    total = sum(tiers.values())
    located = tiers["P1"] + tiers["P2"] + tiers["P3"]
    return {
        "claims": total,
        "tiers": dict(tiers.most_common()),
        "tiers_pct": {k: round(100 * v / total, 1) for k, v in tiers.most_common()},
        "located": located,
        "located_pct": round(100 * located / total, 1),
        "s_renderable": sum(1 for r in rows if r["tier"] == "S" and r["section_renderable"]),
        "chunk_linked": sum(1 for r in rows if r["chunk_index"] is not None),
        "bytes": out_path.stat().st_size,
    }


if __name__ == "__main__":
    import json

    data = Path(os.environ["XIST_KB_DATA"])
    gold = data / "gold" if (data / "gold").is_dir() else data
    text_dir = Path(os.environ["XIST_KB_TEXT_DIR"])
    report = build(
        gold / "claims.parquet", gold / "provenance.parquet", text_dir, gold / "claim_provenance.parquet"
    )
    print(json.dumps(report, indent=1, ensure_ascii=False))
