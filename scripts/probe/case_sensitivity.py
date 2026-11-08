import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
import pyarrow.parquet as pq

V2=Path(r'C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2')
text_dir=V2/'papers/text'

# exact-case set vs filesystem exists()
stems={p.stem for p in text_dir.glob('*.txt')}
stems_lower={s.lower() for s in stems}
print('text stems:', len(stems))

claims=pq.read_table('data_local/gold/claims.parquet',columns=['paper_id']).to_pylist()
pids={c['paper_id'] for c in claims}
print('distinct claim paper_ids:', len(pids))

exact_hit={p for p in pids if p in stems}
lower_hit={p for p in pids if p.lower() in stems_lower}
exists_hit={p for p in pids if (text_dir/f'{p}.txt').exists()}

print(f'matched by exact case      : {len(exact_hit)}')
print(f'matched case-insensitively : {len(lower_hit)}')
print(f'matched by path.exists()   : {len(exists_hit)}   <- Windows FS is case-insensitive')

missing_strict={p for p in pids if p not in stems}
print(f'\nclaims paper_ids with NO exact-case text file: {len(missing_strict)}')
print('  sample:', sorted(missing_strict)[:6])
# how many of those actually exist with different case?
recoverable=[p for p in missing_strict if (text_dir/f'{p}.txt').exists()]
print(f'  ... but path.exists() finds them anyway (Windows): {len(recoverable)}')
print(f'  ... would FAIL on Linux: {len(missing_strict)-len(recoverable)}')

# same for JSON files
json_stems={p.stem for p in (V2/'notes/json').glob('*.json')}
miss_json={p for p in pids if p not in json_stems}
print(f'\nclaims paper_ids with no exact-case JSON: {len(miss_json)}')
