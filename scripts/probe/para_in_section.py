import sys, io, re, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""Locate a paragraph within the section the annotation already names.

For claims with a quote (ground truth known), hide the quote, restrict the
search to the named section, and rank sentence windows by claim-term overlap.
If this beats whole-paper search, then the ~63k section-only claims can get
paragraph-level highlighting within their section.
"""
from pathlib import Path
from collections import Counter
import pyarrow.parquet as pq

GOLD = Path("data_local/gold"); V2 = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2")
WS = re.compile(r"\s+"); TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")
SENT = re.compile(r"(?<=[.!?])\s+")
HEAD = re.compile(r"^\s*((?:abstract|introduction|results|discussion|materials and methods|methods|conclusion|conclusions)s?)\s*$", re.I)
STOP = set("""the and for with that this from were was are has have been not but its can may
also than then into within using used use such more most other both each which their these
those there here when where while during after before between under over about above
thus therefore however moreover furthermore although because since whether either neither
study studies result results data show shows showed shown found indicate indicates observed
levels level higher lower increased decreased expression activity role function effect
cells cell gene genes protein proteins xist chromosome chromosomes inactivation""".split())
def norm(s): return WS.sub(" ", s).strip()
def terms(s): return {t.lower() for t in TOKEN.findall(s) if t.lower() not in STOP and len(t)>=3}
def windows(text, size=700):
    sents=[s for s in SENT.split(norm(text)) if s]
    out,cur,start,pos=[],[],0,0
    for s in sents:
        if cur and sum(len(x)+1 for x in cur)+len(s)>size:
            out.append((start,pos," ".join(cur))); cur,start=[],pos
        cur.append(s); pos+=len(s)+1
    if cur: out.append((start,pos," ".join(cur)))
    return out

claims = pq.read_table(GOLD/"claims.parquet", columns=["paper_id","quote","claim","section","provenance_id"]).to_pylist()
prov = {r["provenance_id"]: r["method"] for r in pq.read_table(GOLD/"provenance.parquet").to_pylist()}
nr = [c for c in claims if prov.get(c["provenance_id"]) != "rule"]
by = {}
for c in nr: by.setdefault(c["paper_id"], []).append(c)

random.seed(21)
sample = random.sample(sorted(by), min(400, len(by)))
whole=[0,0,0]; within=[0,0,0]; within_n=0; found_sec=0

for pid in sample:
    tp = V2/"papers"/"text"/f"{pid}.txt"
    if not tp.exists(): continue
    text = tp.read_text(encoding="utf-8", errors="replace")
    wins = windows(text)
    if len(wins) < 10: continue

    # section boundaries
    lines = text.splitlines()
    marks=[]; pos=0
    for ln in lines:
        m = HEAD.match(ln)
        if m: marks.append((m.group(1).lower(), pos))
        pos += len(ln)+1
    total = max(pos,1)
    sec_range={}
    for i,(name,st) in enumerate(marks):
        end = marks[i+1][1] if i+1<len(marks) else total
        sec_range.setdefault(name, (st,end))

    for c in by[pid]:
        q = norm(c["quote"] or "")
        if len(q) < 25 or text.count(q) != 1: continue
        qpos = text.find(q)
        true_idx = next((i for i,(s,e,_) in enumerate(wins) if s <= qpos < e), None)
        if true_idx is None: continue
        ct = terms(c["claim"] or "")
        if not ct: continue

        # whole-paper
        sc=[len(ct & set(TOKEN.findall(w[2].lower())))/len(ct) for w in wins]
        pred=max(range(len(sc)), key=lambda i: sc[i])
        if sc[pred] <= 0: continue
        whole[0]+=1; whole[1]+= (pred==true_idx); whole[2]+= (abs(pred-true_idx)<=1)

        # within named section
        sec=(c["section"] or "").lower()
        if sec in sec_range:
            lo,hi = sec_range[sec]
            cands=[(i,w) for i,w in enumerate(wins) if lo <= w[0] < hi]
            if len(cands) >= 3:
                scores=[(len(ct & set(TOKEN.findall(w[2].lower())))/len(ct), i) for i,w in cands]
                best=max(scores)
                if best[0] > 0:
                    found_sec+=1
                    within[0]+=1
                    within[1]+= (best[1]==true_idx)
                    within[2]+= (abs(best[1]-true_idx)<=1)

def rep(name, arr, denom):
    if denom==0: print(f'{name}: no data'); return
    print(f'{name:22} n={denom:5d}  exact={100*arr[1]/denom:5.1f}%  within±1={100*arr[2]/denom:5.1f}%')

rep('whole paper', whole, whole[0])
rep('within named section', within, within[0])
print(f'\nclaims whose named section was found in text: {found_sec}')
