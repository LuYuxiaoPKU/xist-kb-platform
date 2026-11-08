import sys, io, re, random, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""Baselines for the paragraph-location probe: is 67.7% better than guessing?"""
from pathlib import Path
from collections import Counter
import pyarrow.parquet as pq

GOLD = Path("data_local/gold"); V2 = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2")
WS = re.compile(r"\s+"); TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")
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
        if len(seg.strip()) >= 40: out.append((norm(seg), pos))
        pos = m.end()
    seg = text[pos:]
    if len(seg.strip()) >= 40: out.append((norm(seg), pos))
    return out
def terms(s): return {t.lower() for t in TOKEN.findall(s) if t.lower() not in STOP and len(t)>=3}

claims = pq.read_table(GOLD/"claims.parquet", columns=["claim_id","paper_id","quote","claim","section","provenance_id"]).to_pylist()
prov = {r["provenance_id"]: r["method"] for r in pq.read_table(GOLD/"provenance.parquet").to_pylist()}
nr = [c for c in claims if prov.get(c["provenance_id"]) != "rule"]
by = {}
for c in nr: by.setdefault(c["paper_id"], []).append(c)

random.seed(21)
sample = random.sample(sorted(by), min(400, len(by)))
rows = []      # (n_paras, true_idx, pred_idx, best_scores)
para_lens = []
for pid in sample:
    tp = V2/"papers"/"text"/f"{pid}.txt"
    if not tp.exists(): continue
    text = tp.read_text(encoding="utf-8", errors="replace")
    paras = paragraphs(text)
    if len(paras) < 3: continue
    for pn,_ in paras: para_lens.append(len(pn))
    for c in by[pid]:
        q = norm(c["quote"] or "")
        if len(q) < 25 or text.count(q) != 1: continue
        pos = text.find(q)
        true_idx = None
        for i,(pn,ppos) in enumerate(paras):
            if ppos <= pos < ppos+len(pn)+50: true_idx=i; break
        if true_idx is None: continue
        ct = terms(c["claim"] or "")
        if not ct: continue
        scores = [len(ct & set(TOKEN.findall(pn.lower())))/len(ct) for pn,_ in paras]
        pred = max(range(len(scores)), key=lambda i: scores[i])
        if scores[pred] <= 0: continue
        rows.append((len(paras), true_idx, pred))

# baselines
always0 = sum(1 for _,t,_ in rows if t == 0)
pop = Counter(t for _,t,_ in rows).most_common(1)[0][0]
always_pop = sum(1 for _,t,_ in rows if t == pop)
hit = sum(1 for _,t,p in rows if t == p)
chance = sum(1 for n,t,p in rows if True) # placeholder
mean_chance = sum(1.0/n for n,_,_ in rows)/len(rows)

print(f"claims evaluated: {len(rows)}")
print(f"paragraphs per paper: median {sorted(n for n,_,_ in rows)[len(rows)//2]}")
print()
print(f"  always guess paragraph 0 : {100*always0/len(rows):5.1f}%")
print(f"  always guess paragraph {pop}   : {100*always_pop/len(rows):5.1f}%")
print(f"  random within paper      : {100*mean_chance:5.1f}%")
print(f"  term-overlap method      : {100*hit/len(rows):5.1f}%")
print()
print(f"=> lift over best naive baseline: {100*(hit-always_pop)/len(rows):+.1f} pts")
print()
print("true paragraph index distribution (top 6):", Counter(t for _,t,_ in rows).most_common(6))
print(f"paragraph length chars: median {sorted(para_lens)[len(para_lens)//2]}, p90 {sorted(para_lens)[int(len(para_lens)*.9)]}")
