# Architecture

## Layer model

The platform is organized as five layers, bottom-up. Each layer is a directory
of Parquet/JSONL files on disk; nothing is held only in memory, so a stage can
be re-run in isolation and its output inspected with DuckDB.

```
5  service     FastAPI routes, React app, SSE Q&A
4  storage     DuckDB views over Gold Parquet + FTS index
3  knowledge   papers / claims / chunks / interactors / regulations /
               xci_status / species_xist / citations / provenance
2  identity    paper_id normalization, external-ID mapping
               (DOI / PMID / PMCID / OpenAlex ID)
1  raw         gzipped JSONL of upstream API responses, with
               source + retrieved_at + version on every record
```

## Data flow

```
upstream APIs ──► bronze (JSONL.gz, one file per source per run)
                     │
                     ▼
              silver (normalized entity tables, Parquet)
                     │  join on canonical paper_id
                     ▼
               gold (query-ready: claims + chunks + offsets)
                     │
                     ▼
             index (DuckDB views, FTS)
                     │
                     ▼
                  API / web
```

## Why Parquet + DuckDB

- **Columnar reads.** A query that touches `topic, year, confidence` reads those
  three columns, not 115k full claim rows. On the current 217 MB SQLite the
  difference is seconds vs milliseconds.
- **One format for two consumers.** The server queries Gold Parquet through
  DuckDB; a future static export can ship the same files to DuckDB-WASM without
  a conversion step.
- **No server process.** DuckDB opens a file; there is no daemon to keep alive,
  no vacuum, no lock contention on reads. Writes go to a new Parquet file and
  the view is reloaded atomically.
- **Typed.** Arrow schemas catch a `confidence` value of `['high']` at write
  time instead of leaking it into queries.

## Provenance

Every claim carries a `provenance_id` pointing at a row that records how it was
produced: method (llm / rule / manual), model and prompt template when
applicable, a hash of that prompt, the runtime, and a checksum of the input
text. The checksum is what makes staleness detectable — if the source text
changes, the hash no longer matches and the claim is flagged for re-annotation.

This directly addresses a defect in V2, where 13,469 annotation JSON files
recorded no method at all.

## Character-offset provenance

`chunks.parquet` holds the source text split into paragraphs, each with its
character range in the original `.txt`. A claim's `chunk_id` plus
`quote_offset_start` / `quote_offset_end` locates the exact quoted span, which
the web UI highlights. Claims that cannot be aligned to a chunk are kept with
`chunk_id = null` and surfaced for review rather than silently dropped.

V2's equivalent field matched the source text only 52.5% of the time on a
200-paper sample, so this layer is rebuilt rather than migrated.

## Status vocabulary

`papers.status` moves forward only:

| status | meaning |
|---|---|
| `registered` | metadata exists, no full text |
| `text_available` | full text extracted to `papers/text/` |
| `annotated` | claims extracted |
| `reviewed` | a human has checked the claims |

The web UI defaults to `annotated` and above; the registry stays complete but
does not drown the evidence in empty records.

## Deployment

Code lives in this repository; data lives on the lab server at
`/Data7/luyx/XIST-KB/data` (set `XIST_KB_DATA` to point elsewhere). The server
runs the FastAPI process under systemd and serves the built React app through
nginx. GitHub is source control only — no data is committed.

## paper_id 规范值：小写

2026-11-08 决策。V2 里同一篇论文有三种拼写：registry 原值、claims CSV 的副本、
磁盘文件名。小写化是唯一的规范形式，映射表 `gold/paper_id_map.parquet`
记录 `paper_id -> json_file / text_file / pdf_file / claims_file`。

**不改磁盘文件名。** 881 个 JSON、864 个 text、1,891 个 PDF stem 含大写，
重命名是没有收益的操作——所有查找都经过映射表。

实测（全量迁移 `data_local_lowercase`）：

| 不变量 | 结果 |
|---|---|
| papers 含大写 id | 0 |
| claims 含大写 paper_id | 0 |
| claims.paper_id 不在 papers 中 | **0**（原 815） |
| 标注无对应论文 | **0**（原 815） |
| 有全文的论文 | **13,431**（原 12,730，+701） |

修复计数：`paper_id_lowercased` 1,822（registry）+ `claim_paper_id_lowercased` 9,933（claims）。

**碰撞为零。** 论文表与 claims 表内部各自没有「仅大小写不同」的两个 id；
跨表出现的 815 组大小写差异全部是同一篇论文，不是两篇。
