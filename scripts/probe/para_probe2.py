import sys, io, re, random, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""Paragraph location re-measured with sentence-window segmentation.

V2's text has few blank-line paragraph marks (median 7 per paper, p90 block
9082 chars), so blank-line splitting produces one giant blob. Split into
sentence windows of ~700 chars instead, and compare against the baseline of
guessing the most common window index.
"""
from pathlib import Path
from collections import Counter
import pyarrow.parquet as pq

GOLD = Path("data_local/gold"); V2 = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2")
WS = re.compile(r"\s+"); TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")
SENT = re.compile(r"(?<=[.!?])\s+")
STOP = set("""the and for with that this from were was are has have been not but its can may
also than then into within using used use such more most other both each which their these
those there here when where while during after before between under over about above
thus therefore however moreover furthermore although because since whether either neither
study studies result results data show shows showed shown found indicate indicates observed
levels level higher lower increased decreased expression activity role function effect
cells cell gene genes protein proteins xist chromosome chromosomes inactivation""".split())
def norm(s): return WS.sub(" ", s).strip()
def windows(text, size=700, overlap=0.0):
    sents = [s for s in SENT.split(norm(text)) if s]
    out, cur, start, pos = [], [], 0, 0
    for s in sents:
        if cur and sum(len(x)+1 for x in cur) + len(s) > size:
            out.append((start, pos, " ".join(cur)))
            cur, start = [], pos
        cur.append(s); pos += len(s) + 1
    if cur: out.append((start, pos, " ".join(cur)))
    return out
def terms(s): return {t.lower() for t in TOKEN.findall(s) if t.lower() not in STOP and len(t)>=3}

claims = pq.read_table(GOLD/"claims.parquet", columns=["claim_id","paper_id","quote","claim","section","provenance_id"]).to_pylist()
prov = {r["provenance_id"]: r["method"] for r in pq.read_table(GOLD/"provenance.parquet").to_pylist()}
nr = [c for c in claims if prov.get(c["provenance_id"]) != "rule"]
by = {}
for c in nr: by.setdefault(c["paper_id"], []).append(c)

random.seed(21)
sample = random.sample(sorted(by), min(400, len(by)))
rows = []; wlens = []; nwin = []
for pid in sample:
    tp = V2/"papers"/"text"/f"{pid}.txt"
    if not tp.exists(): continue
    text = tp.read_text(encoding="utf-8", errors="replace")
    wins = windows(text)
    if len(wins) < 5: continue
    nwin.append(len(wins))
    wlens += [len(w[2]) for w in wins]
    for c in by[pid]:
        q = norm(c["quote"] or "")
        if len(q) < 25 or text.count(q) != 1: continue
        pos = text.find(q)
        true_idx = next((i for i,(s,e,_) in enumerate(wins) if s <= pos < e), None)
        if true_idx is None: continue
        ct = terms(c["claim"] or "")
        if not ct: continue
        scores = [len(ct & set(TOKEN.findall(w[2].lower())))/len(ct) for w in wins]
        pred = max(range(len(scores)), key=lambda i: scores[i])
        if scores[pred] <= 0: continue
        rows.append((len(wins), true_idx, pred, scores[pred]))

if not rows:
    print("no rows"); sys.exit()

n = len(rows)
hit = sum(1 for _,t,p,_ in rows if t == p)
within1 = sum(1 for _,t,p,_ in rows if abs(t-p) <= 1)
pop = Counter(t for _,t,_,_ in rows).most_common(1)[0][0]
always_pop = sum(1 for _,t,_,_ in rows if t == pop)
mean_chance = sum(1.0/nw for nw,_,_,_ in rows)/n

print(f"claims evaluated: {n}")
print(f"windows per paper: median {sorted(nwin)[len(nwin)//2]}")
print(f"window length: median {sorted(wlens)[len(wlens)//2]} chars")
print()
print(f"  always guess window {pop:<3}: {100*always_pop/n:5.1f}%")
print(f"  random within paper    : {100*mean_chance:5.1f}%")
print(f"  term-overlap method    : {100*hit/n:5.1f}%  (within +-1: {100*within1/n:.1f}%)")
print(f"  lift over best naive   : {100*(hit-always_pop)/n:+.1f} pts")
print()
print("window length chars: p50", sorted(wlens)[len(wlens)//2], "p90", sorted(wlens)[int(len(wlens)*.9)])
print("true window index top:", Counter(t for _,t,_,_ in rows).most_common(6))
