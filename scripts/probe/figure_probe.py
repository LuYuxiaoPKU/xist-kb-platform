import sys, io, re, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""The ~29.6k 'label' quotes are mostly figure/table numbers ('3.6, 3.7', 'Table 2').
A figure number is a locator. Can the referenced figure be found in the text?"""
from pathlib import Path
from collections import Counter
import pyarrow.parquet as pq

GOLD = Path("data_local/gold"); V2 = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2")
NUMQ = re.compile(r"^\s*[\d.,\s;:()\-–]+\s*$")
FIGQ = re.compile(r"^\s*(table|fig|figure|supplementary|data|panel)\b", re.I)
START = re.compile(r"\b(?:table|fig|figure|figs|tables)\s*([0-9]+[A-Za-z]?(?:\.[0-9]+)?)", re.I)

claims = pq.read_table(GOLD/"claims.parquet", columns=["paper_id","quote","provenance_id"]).to_pylist()
prov = {r["provenance_id"]: r["method"] for r in pq.read_table(GOLD/"provenance.parquet").to_pylist()}
nr = [c for c in claims if prov.get(c["provenance_id"]) != "rule"]

label = [c for c in nr if c["quote"] and (NUMQ.match(c["quote"]) or FIGQ.match(c["quote"]))]
print(f"label-type quotes: {len(label):,}")

by = {}
for c in label: by.setdefault(c["paper_id"], []).append(c)

random.seed(4)
papers = random.sample(sorted(by), min(400, len(by)))
found = miss = noparse = 0
samples = []
for pid in papers:
    tp = V2/"papers"/"text"/f"{pid}.txt"
    if not tp.exists(): continue
    text = tp.read_text(encoding="utf-8", errors="replace")
    nums = {m.group(1).lower() for m in START.finditer(text)}
    for c in by[pid]:
        q = c["quote"].strip()
        cs = [m.group(1).lower() for m in START.finditer(q)]
        if not cs and NUMQ.match(q):
            cs = [x for x in re.findall(r"\d+(?:\.\d+)?", q)]
        if not cs:
            noparse += 1; continue
        # does the text mention any of these figure/table numbers?
        if any(x in nums for x in cs):
            found += 1
            if len(samples) < 4: samples.append((q, sorted(nums)[:6]))
        else:
            miss += 1

tot = found + miss
print(f"claims with a parseable figure/table number: {tot:,} (unparseable: {noparse})")
if tot:
    print(f"  the referenced figure/table appears in the text: {found:,} ({100*found/tot:.1f}%)")
    print(f"  not found                                      : {miss:,} ({100*miss/tot:.1f}%)")
print("\nsamples (quote -> figure numbers present in text):")
for q, nums in samples: print(f"  {q!r:30} -> {nums}")
