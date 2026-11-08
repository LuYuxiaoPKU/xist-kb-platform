# xist-kb-platform

XIST / X 染色体失活 (XCI) 文献知识库与检索平台。

面向 296,835 篇注册文献、115,674 条结构化 claims 的分层数据平台：Parquet 分层存储 + DuckDB 查询 + FastAPI/React 服务化，支持字符区间级证据溯源。

## 状态

可用。数据层、溯源层、查询层、API 与前端六个页面均已实现并通过测试（227 项）。

## 架构

```
原始层      ID 与溯源层      知识层         存储层            服务层
OpenAlex    DOI/PMID/PMCID   papers         Bronze JSONL.gz   FastAPI REST
Crossref    OpenAlex ID      claims         Silver Parquet    DuckDB 查询
Europe PMC  source+date      chunks         Gold Parquet      React 前端
Unpaywall   provenance       citations      索引              SSE 问答
```

详细设计见 [docs/architecture.md](docs/architecture.md)；溯源分级的实测结论见
[docs/provenance-context.md](docs/provenance-context.md)。

## 快速开始

```bash
git clone https://github.com/LuYuxiaoPKU/xist-kb-platform.git
cd xist-kb-platform
uv sync
uv run xist --help
```

前端：

```bash
cd web
npm install
npm run dev      # 开发，Vite 5173，/api 代理到 8420
npm run build    # 生产，产物由 uvicorn 直接托管在 /
```

## 本地运行

数据（Parquet / DuckDB / 论文全文）不入库，用环境变量指向：

```bash
export XIST_KB_DATA=/path/to/data_local_lowercase
export XIST_KB_TEXT_DIR=/path/to/papers/text
python -m xist_kb.api.serve            # 默认 127.0.0.1:8420
```

端口 **8420**，不是 8000 —— 8000 是常见默认值，本机和实验室服务器上都已被别的服务占用。
`XIST_KB_PORT` 或 `--port` 可覆盖，`--host 0.0.0.0` 供服务器部署使用。前端 Vite 代理读同一个
`XIST_KB_PORT`，两处不会漂移。

认证：`XIST_KB_API_KEY` 设置后请求需带 `X-API-Key`；`XIST_KB_ALLOWED_NETS` 限制来源网段。

## 目录

| 路径 | 用途 |
|---|---|
| `src/xist_kb/ingest/` | 原始层 → ID 层：多源抓取、检索式、ID 消歧 |
| `src/xist_kb/extract/` | 文本提取、JATS 解析、段落切分 |
| `src/xist_kb/annotate/` | LLM 精注、规则提取、注释溯源 |
| `src/xist_kb/build/` | 知识层 → Parquet，claim/chunk 对齐 |
| `src/xist_kb/query/` | DuckDB 查询引擎、检索、导出、paper scope |
| `src/xist_kb/api/` | FastAPI 路由与认证 |
| `web/` | React 前端（概览/检索/全文/审阅/图表/提问） |
| `deploy/` | `serve.sh` 启停脚本（带重启循环、日志轮转） |
| `data/` | 运行期数据，不入库 |

## 数据来源

- 文献元数据：OpenAlex、Crossref、PubMed E-utilities、Europe PMC
- 开放获取全文：PMC OA、Europe PMC fullTextXML
- 引文：OpenCitations
- LLM 注释：Claude (Anthropic)

## 新增证据

本仓库**只读**：注释与全文都在 V2 checkout 里做，这里只负责把它们变成可查询的层。
新增一篇论文需要动 V2 侧的三处，然后在本仓库重建。

### 1. 在 V2 侧写三样东西

| 改什么 | 在哪 | 是否必须 |
|---|---|---|
| 注册条目 | `metadata/papers.csv` 加一行（10 字段） | 是 |
| 精注 JSON | `notes/json/{paper_id}.json` | 是，这是唯一的证据来源 |
| 全文 | `papers/text/{paper_id}.txt` | 否，但缺了就没有字符区间溯源 |

`paper_id` 格式 `{first_author_lowercase}{year}_{doi_underscored}`，例
`deng2011_10_1038_nature09898`。PDF 文件名必须与之一致。

精注模板是 V2 的 `templates/xist_paper.yaml`（226 行），四条硬约束：

1. **字段名与枚举值不能改。** 自创字段（把 `paragraph` 写成 `quote_text`）会被
   静默丢弃，该 claim 的溯源掉到 S 档。
2. **`paragraph` 存原文引句，不是段号。** 它是 `claims.quote` 的来源，也是
   P1/P2/P3 分级的唯一依据。
3. **`topic` 只能是模板里那 20 个值。** 其他值会被归一化到 `other`，不报错。
4. **查不到的写 `"not reported"`，不要补。** 这个库出过编造 Addgene 编号的事故。

除 `claims` 数组外，还有四个段落写进各自的表。空着不会报错，只会让图表少一块：
`xist_identification` → `species_xist`，`xist_expression_regulation` →
`regulations`，`xist_protein_interactions` → `interactors`，
`x_chromosome_inactivation` → `xci_status`。

### 2. 在本仓库重建

```bash
export XIST_KB_DATA=/path/to/XIST-KB/data
xist migrate-v2 /path/to/XIST_Project_V2
python scripts/rebuild_derived.py
```

`rebuild_derived.py` 固化了两者之间的全部顺序依赖，不要手动分步跑。

改完必查两个不变式，都应为 0：

```bash
python -c "import duckdb;c=duckdb.connect('$XIST_KB_DATA/index/xist.duckdb',read_only=True);print('dup',c.execute('SELECT count(*)-count(DISTINCT claim_id) FROM claims').fetchone()[0],'orphan',c.execute('SELECT count(*) FROM claims WHERE paper_id NOT IN (SELECT paper_id FROM papers)').fetchone()[0])"
```

### 3. 不要改的东西

`gold/*.parquet` 和 `index/xist.duckdb` 是生成物，每次重建都会被覆盖。手写
`claim_id` 尤其危险——它是内容哈希，手写的 id 会让审阅标注对不上。

多人协作时只回传新增的 JSON，不要整目录覆盖：`data/silver/annotations.parquet`
里的人工审阅结论会跟着丢失。

## 许可

代码 MIT。数据由各原始来源的许可决定，不随本仓库分发。

## 当前进度

阶段 1（数据层）与阶段 2（溯源重建）已完成，阶段 3（服务化）可用：

- Gold 层 13 张 Parquet；索引库 `index/xist.duckdb` 1.6 GB 带 BM25 全文索引
- 296,835 篇 papers、115,674 条 claims、799,316 个句窗口
- 字符区间溯源：33.3% 的非规则 claim 能定位到原文语句，其余带诚实的章节/未定位标记
- 论文级 scope：16.4% 的 claim 来自全文从不提 XIST/XCI 的论文，检索与问答默认排除
- DuckDB 查询层与 CLI：`xist stats`、`xist search`、`xist paper`、`xist context`
- FastAPI + React：概览、检索、全文检索、审阅（标注持久化）、图表、问答

```bash
xist stats
xist search --text DDX39A --limit 5
xist search --topic xci --species "Mus musculus"
xist paper deng2011_abc
```
