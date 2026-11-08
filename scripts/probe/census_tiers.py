"""Full census: assign every non-rule claim to a provenance tier, exactly.

v3's tier counts were estimated by multiplying sample rates and they do not
sum to the claim total. This computes the partition directly over the whole
corpus, one pass over papers/text.

Tiers:
  A   textual quote located in the paper's text (exact or fuzzy >= 90)
  B1  not A, has a real section, and that section heading is detectable in
      the paper's own text
  B2  not A, has a real section, but no detectable heading for it
  C   everything else (no section, empty quote, label-only quote)

Outputs JSON to stdout and the fuzzy-match samples for manual inspection.
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
from rapidfuzz import fuzz

GOLD = Path("data_local/gold")
V2 = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2")

WS = re.compile(r"\s+")
WORD = re.compile(r"[A-Za-z]{4,}")
HEAD = re.compile(
    r"^\s*((?:abstract|introduction|results|discussion|materials and methods|methods|"
    r"conclusion|conclusions)s?)\s*$",
    re.I,
)
REAL_SECTIONS = {
    "results", "discussion", "introduction", "methods", "abstract",
    "figure_legend", "conclusion",
}


def norm(s: str) -> str:
    return WS.sub(" ", s).strip().lower()


def is_textual(q: str | None) -> bool:
    """Strict classifier (the one v3 recommends)."""
    if not q:
        return False
    s = q.strip()
    if re.search(r"\bsections?\s*$", s, re.I):
        return False
    if re.fullmatch(r"[\d.,\s;:()\-–]+", s):
        return False
    if re.match(r"^\s*(table|fig|figure|supplementary|data|panel)\b", s, re.I):
        return False
    if len(s.split()) < 8 and not any(p in s for p in ".!?;:"):
        return False
    return True


def fuzzy_score(text_norm: str, quote_norm: str, window: int = 400) -> tuple[float, int, str]:
    tokens = WORD.findall(quote_norm)
    if not tokens:
        return 0.0, -1, ""
    anchor = max(tokens, key=len)
    best, best_pos, best_win, start = 0.0, -1, "", 0
    while True:
        idx = text_norm.find(anchor, start)
        if idx < 0:
            break
        lo = max(0, idx - window)
        hi = min(len(text_norm), idx + len(anchor) + window)
        win = text_norm[lo:hi]
        score = fuzz.partial_ratio(quote_norm, win)
        if score > best:
            best, best_pos, best_win = score, lo, win
        start = idx + len(anchor)
        if best >= 95:
            break
    return best, best_pos, best_win


def token_overlap(quote_norm: str, window: str) -> float:
    """Fraction of the quote's content words present in the matched window.

    `partial_ratio` alone produces false matches: a quote about Malat1 scores
    92 against a statistics paragraph because both share generic words. A real
    match shares nearly all its content words. Calibration on 400 candidates:
    score >= 90 with overlap >= 0.8 is right 94-100% of the time; score >= 90
    with overlap < 0.6 is a false match.
    """
    qw = set(WORD.findall(quote_norm))
    if not qw:
        return 0.0
    return len(qw & set(WORD.findall(window))) / len(qw)


def main() -> None:
    t0 = time.time()
    claims = pq.read_table(
        GOLD / "claims.parquet",
        columns=["claim_id", "paper_id", "quote", "section", "provenance_id"],
    ).to_pylist()
    prov = {
        r["provenance_id"]: r["method"]
        for r in pq.read_table(GOLD / "provenance.parquet").to_pylist()
    }
    for c in claims:
        c["method"] = prov.get(c["provenance_id"], "?")
        c["textual"] = is_textual(c["quote"])

    non_rule = [c for c in claims if c["method"] != "rule"]
    rule = [c for c in claims if c["method"] == "rule"]

    by_paper: dict[str, list[dict]] = {}
    for c in non_rule:
        by_paper.setdefault(c["paper_id"], []).append(c)

    tiers: Counter[str] = Counter()
    fuzzy_samples: list[dict] = []
    rng = random.Random(11)

    text_dir = V2 / "papers" / "text"
    have_files = {p.stem for p in text_dir.glob("*.txt")}

    for paper_id, rows in by_paper.items():
        path = text_dir / f"{paper_id}.txt"
        text_norm = None
        headings: set[str] = set()
        if path.exists():
            raw = path.read_text(encoding="utf-8", errors="replace")
            text_norm = norm(raw)
            for line in raw.splitlines():
                m = HEAD.match(line)
                if m:
                    headings.add(m.group(1).lower())

        for c in rows:
            quote = c["quote"]
            if c["textual"] and text_norm is not None:
                q = norm(quote)
                if text_norm.find(q) >= 0:
                    tiers["A_exact"] += 1
                    continue
                score, pos, win = fuzzy_score(text_norm, q)
                overlap = token_overlap(q, win)
                # Both conditions must hold: partial_ratio alone admits
                # false matches that share only generic words.
                if score >= 90 and overlap >= 0.8:
                    tiers["A_fuzzy"] += 1
                    if len(fuzzy_samples) < 40:
                        lo = max(0, pos - 40)
                        fuzzy_samples.append(
                            {
                                "claim_id": c["claim_id"],
                                "score": round(score, 1),
                                "overlap": round(overlap, 2),
                                "quote": quote[:160],
                                "window": text_norm[lo : pos + 260][:300],
                            }
                        )
                    continue
            elif c["textual"] and text_norm is None:
                # Paper has no extracted text at all: no tier can be assigned
                # from offsets. Count it once, here, and do not fall through
                # to the section branches (that would double-count).
                tiers["textual_no_text"] += 1
                continue

            section = (c["section"] or "").lower()
            if section in REAL_SECTIONS:
                if text_norm is not None and (
                    section in headings
                    or (section == "figure_legend" and "figure" in text_norm)
                ):
                    tiers["B1"] += 1
                else:
                    tiers["B2"] += 1
            else:
                tiers["C"] += 1

    total = len(non_rule)
    summary = {
        "claims_total": len(claims),
        "rule_claims": len(rule),
        "non_rule": total,
        "tiers": dict(tiers),
        "partition_sums_to": sum(tiers.values()),
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(json.dumps(summary, indent=2))
    print("\n=== fuzzy samples for manual inspection ===")
    print(json.dumps(fuzzy_samples[:40], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
