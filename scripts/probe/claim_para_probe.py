import sys, io, re, random, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""Can a claim WITHOUT a quote still be located to a paragraph?

Ground truth: P1 claims have a quote that occurs exactly once in the paper,
so we know which paragraph it sits in. Hide the quote, retrieve a paragraph
from the claim text alone, and measure how often we land on that paragraph.
"""
from pathlib import Path
import pyarrow.parquet as pq

GOLD = Path("data_local/gold")
V2 = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2")
WS = re.compile(r"\s+")
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")
STOP = set("""the and for with that this from were was are has have been not but its can may
also than then into within using used use such more most other both each which their these
those there here when where while during after before between under over about above
thus therefore however moreover furthermore although because since whether either neither
study studies result results data show shows showed shown found indicate indicates observed
levels level higher lower increased decreased expression activity role function effect
cells cell gene genes protein proteins xist chromosome chromosomes inactivation""".split())

def norm(s): return WS.sub(" ", s).strip()

def paragraphs(text):
    out, pos = [], 0
    for m in re.finditer(r"\n\s*\n", text):
        seg = text[pos:m.start()]
        if len(seg.strip()) >= 40:
            out.append((norm(seg), pos))
        pos = m.end()
    seg = text[pos:]
    if len(seg.strip()) >= 40:
        out.append((norm(seg), pos))
    return out

def terms(s):
    return {t.lower() for t in TOKEN.findall(s) if t.lower() not in STOP and len(t) >= 3}

def score_para(claim_terms, para_norm):
    if not claim_terms: return 0.0
    pset = set(TOKEN.findall(para_norm.lower()))
    return len(claim_terms & pset) / len(claim_terms)

claims = pq.read_table(GOLD / "claims.parquet",
    columns=["claim_id", "paper_id", "claim", "quote", "section", "provenance_id"]).to_pylist()
prov = {r["provenance_id"]: r["method"] for r in pq.read_table(GOLD / "provenance.parquet").to_pylist()}
nr = [c for c in claims if prov.get(c["provenance_id"]) != "rule"]

by = {}
for c in nr: by.setdefault(c["paper_id"], []).append(c)

random.seed(21)
papers = sorted(by)
sample = random.sample(papers, min(400, len(papers)))

stats = {"papers": 0, "claims": 0, "exact_para": 0, "within1": 0, "within2": 0, "same_section": 0}
by_terms = {}
samples = []

for pid in sample:
    tp = V2 / "papers" / "text" / f"{pid}.txt"
    if not tp.exists(): continue
    text = tp.read_text(encoding="utf-8", errors="replace")
    paras = paragraphs(text)
    if len(paras) < 3: continue
    stats["papers"] += 1

    # ground truth for P1 claims
    for c in by[pid]:
        q = norm(c["quote"] or "")
        if len(q) < 25: continue
        if text.count(q) != 1: continue
        pos = text.find(q)
        true_idx = None
        for i, (pnorm, ppos) in enumerate(paras):
            if ppos <= pos < ppos + len(pnorm) + 50:
                true_idx = i; break
        if true_idx is None: continue

        ct = terms(c["claim"] or "")
        if not ct: continue
        scores = [score_para(ct, pn) for pn, _ in paras]
        best = max(range(len(scores)), key=lambda i: scores[i])
        if scores[best] <= 0: continue

        stats["claims"] += 1
        d = abs(best - true_idx) if best >= 0 else 999
        if d == 0: stats["exact_para"] += 1
        if d <= 1: stats["within1"] += 1
        if d <= 2: stats["within2"] += 1

        bucket = min(len(ct), 12)
        b = by_terms.setdefault(bucket, [0, 0])
        b[1] += 1
        if d == 0: b[0] += 1

        if d == 0 and len(samples) < 6:
            samples.append({"claim": c["claim"][:150], "para": paras[true_idx][0][:200], "n_terms": len(ct)})

n = max(stats["claims"], 1)
print(json.dumps({**stats,
    "exact_para_pct": round(100*stats["exact_para"]/n, 1),
    "within1_pct": round(100*stats["within1"]/n, 1),
    "within2_pct": round(100*stats["within2"]/n, 1)}, indent=2))
print("\naccuracy vs number of distinctive terms in the claim:")
for k in sorted(by_terms):
    hit, tot = by_terms[k]
    print(f"  {k:2d} terms: {100*hit/max(tot,1):5.1f}% exact  (n={tot})")
print("\ncorrect examples:")
for s in samples: print(json.dumps(s, indent=2, ensure_ascii=False))
