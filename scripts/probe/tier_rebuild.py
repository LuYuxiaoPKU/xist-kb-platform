import sys,io
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace')
"""Rebuild tiers matching-first: try to locate every claim, classify only what can't be located."""
import re
from pathlib import Path
from collections import Counter
import pyarrow.parquet as pq
from rapidfuzz import fuzz

GOLD=Path('data_local/gold'); V2=Path(r'C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2')
WS=re.compile(r'\s+'); WORD=re.compile(r'[A-Za-z]{4,}')
norm=lambda s: WS.sub(' ',s).strip().lower()
HEAD=re.compile(r'^\s*((?:abstract|introduction|results|discussion|materials and methods|methods|conclusion|conclusions)s?)\s*$',re.I)
REAL={'results','discussion','introduction','methods','abstract','figure_legend','conclusion'}

claims=pq.read_table(GOLD/'claims.parquet',columns=['claim_id','paper_id','quote','section','provenance_id']).to_pylist()
prov={r['provenance_id']:r['method'] for r in pq.read_table(GOLD/'provenance.parquet').to_pylist()}
nr=[c for c in claims if prov.get(c['provenance_id'])!='rule']
by={}
for c in nr: by.setdefault(c['paper_id'],[]).append(c)

def fuzzy(t,q,w=400):
    toks=WORD.findall(q)
    if not toks: return 0.0,""
    a=max(toks,key=len); best=0.0; win=""; s=0
    while True:
        i=t.find(a,s)
        if i<0: break
        lo=max(0,i-w); hi=min(len(t),i+len(a)+w)
        wd=t[lo:hi]; sc=fuzz.partial_ratio(q,wd)
        if sc>best: best,win=sc,wd
        s=i+len(a)
        if best>=95: break
    return best,win

tiers=Counter()
for pid,rows in by.items():
    tp=V2/'papers/text'/f'{pid}.txt'
    if not tp.exists():
        for c in rows: tiers['C_no_text']+=1
        continue
    raw=tp.read_text(encoding='utf-8',errors='replace'); tn=norm(raw)
    heads={m.group(1).lower() for m in (HEAD.match(l) for l in raw.splitlines()) if m}
    for c in rows:
        q=norm(c['quote'] or '')
        # 1) try to locate regardless of what the quote looks like
        if q and len(q)>=20:
            n=tn.count(q)
            if n==1: tiers['P1_unique']+=1; continue
            if n>1:  tiers['P2_ambiguous']+=1; continue
            sc,win=fuzzy(tn,q)
            qw=set(WORD.findall(q))
            ov=(len(qw&set(WORD.findall(win)))/len(qw)) if qw else 0
            if sc>=90 and ov>=0.8: tiers['P3_fuzzy']+=1; continue
        # 2) can't locate: fall back to section
        sec=(c['section'] or '').lower()
        if sec in REAL and sec in heads:
            tiers['S_check']+=1            # can jump to a section heading
        elif sec in REAL:
            tiers['S_label']+=1            # section known, heading absent
        else:
            tiers['C_none']+=1

tot=len(nr)
print(f'non-rule claims: {tot:,}\n')
order=['P1_unique','P2_ambiguous','P3_fuzzy','S_check','S_label','C_none','C_no_text']
for k in order:
    v=tiers.get(k,0)
    print(f'  {k:14} {v:>7,}  {100*v/tot:>5.1f}%')
print(f'\n  located (P1+P2+P3) : {sum(tiers.get(k,0) for k in ("P1_unique","P2_ambiguous","P3_fuzzy")):,}')
print(f'  section fallback   : {tiers.get("S_check",0)+tiers.get("S_label",0):,}')
print(f'  nothing            : {tiers.get("C_none",0)+tiers.get("C_no_text",0):,}')
