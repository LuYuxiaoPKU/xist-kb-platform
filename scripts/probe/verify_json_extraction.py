import sys,io
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace')
# Actually run V2's extractor over the JSONs to see what it would produce now.
import json
from pathlib import Path
import re

V2=Path(r'C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2')
json_files=sorted((V2/'notes/json').glob('*.json'))
TM=re.compile(r'^(Paper discusses \w+|Mentions \w+ \(\d+ occurrences?\))')

n_files=len(json_files)
n_unparse=0
n_no_claims_key=0
n_empty_claims=0
n_tag_only=0
n_real=0
total_real_claims=0
bad_shape=[]

for f in json_files:
    try: d=json.loads(f.read_text(encoding='utf-8'))
    except Exception: n_unparse+=1; continue
    if not isinstance(d,dict): bad_shape.append(f.name); continue
    if 'claims' not in d: n_no_claims_key+=1; continue
    cs=d.get('claims')
    if not isinstance(cs,list): bad_shape.append(f.name); continue
    if not cs: n_empty_claims+=1; continue
    texts=[str(c.get('claim') or c.get('text') or '') for c in cs if isinstance(c,dict)]
    nontag=[t for t in texts if t and not TM.match(t.strip())]
    if nontag:
        n_real+=1; total_real_claims+=len(nontag)
    else:
        n_tag_only+=1

print(f'JSON files:              {n_files}')
print(f'  unparseable:           {n_unparse}')
print(f'  no "claims" key:       {n_no_claims_key}')
print(f'  claims == []:          {n_empty_claims}')
print(f'  only keyword tags:     {n_tag_only}')
print(f'  REAL claims present:   {n_real}  ({total_real_claims} claims)')
print(f'  bad shape:             {len(bad_shape)} {bad_shape[:3]}')
print()
print(f'=> claims.parquet currently has 107,563 LLM claims from 12,123 papers')
print(f'=> extra extractable now: {total_real_claims} from {n_real} papers')
