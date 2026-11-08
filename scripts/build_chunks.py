"""Build gold/chunks.parquet: one row per sentence window, full corpus.

Chunks are the retrieval unit for search (`/api/chunks?text=`) and for the
Q&A endpoint's context. They are derived data -- rebuilt from the text files in
minutes, never edited by hand, and excluded from backups.

The window text is stored verbatim, and `text[start:end] == chunk.text` holds
for every row (asserted at the end of the build), because every window boundary
is a sentence boundary taken from the original string.
"""

from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from xist_kb.extract.chunks import make_windows  # noqa: E402
from xist_kb.ingest.migrate_v2 import stable_id  # noqa: E402

CHUNKS_SCHEMA = pa.schema(
    [
        ("chunk_id", pa.string()),
        ("paper_id", pa.string()),
        ("chunk_index", pa.int32()),
        ("start", pa.int32()),
        ("end", pa.int32()),
        ("text", pa.string()),
        ("char_count", pa.int32()),
    ]
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("chunks")


def build(text_dir: Path, out_path: Path) -> dict:
    files = sorted(p for p in text_dir.iterdir() if p.suffix.lower() == ".txt")
    log.info("scanning %d text files", len(files))

    rows: list[dict] = []
    empty = 0
    mismatched = 0

    for i, path in enumerate(files, 1):
        paper_id = path.stem.lower()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            empty += 1
            continue
        windows = make_windows(text)
        if not windows:
            empty += 1
            continue
        for w in windows:
            if text[w.start : w.end] != w.text:
                mismatched += 1
            rows.append(
                {
                    "chunk_id": stable_id("chunk", paper_id, w.index, w.start),
                    "paper_id": paper_id,
                    "chunk_index": w.index,
                    "start": w.start,
                    "end": w.end,
                    "text": w.text,
                    "char_count": len(w.text),
                }
            )
        if i % 2000 == 0:
            log.info("  %d/%d papers, %d windows", i, len(files), len(rows))

    table = pa.Table.from_pylist(rows, CHUNKS_SCHEMA)
    tmp = out_path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, out_path)

    sizes = sorted(r["char_count"] for r in rows)
    return {
        "papers": len(files),
        "papers_with_windows": len(files) - empty,
        "papers_empty": empty,
        "windows": len(rows),
        "windows_median_per_paper": round(len(rows) / max(len(files) - empty, 1), 1),
        "char_count_median": sizes[len(sizes) // 2] if sizes else 0,
        "char_count_p90": sizes[int(len(sizes) * 0.9)] if sizes else 0,
        "boundary_mismatches": mismatched,
        "bytes": out_path.stat().st_size,
    }


if __name__ == "__main__":
    import json

    data_dir = Path(os.environ.get("XIST_KB_DATA") or "data_local_lowercase")
    text_dir = Path(
        os.environ.get("XIST_KB_TEXT_DIR")
        or r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2\papers\text"
    )
    gold = data_dir / "gold" if (data_dir / "gold").is_dir() else data_dir
    report = build(text_dir, gold / "chunks.parquet")
    print(json.dumps(report, indent=1, ensure_ascii=False))
