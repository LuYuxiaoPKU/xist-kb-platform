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
| `deploy/` | systemd / nginx / docker-compose |
| `data/` | 运行期数据，不入库 |

## 数据来源

- 文献元数据：OpenAlex、Crossref、PubMed E-utilities、Europe PMC
- 开放获取全文：PMC OA、Europe PMC fullTextXML
- 引文：OpenCitations
- LLM 注释：Claude (Anthropic)

## 许可

代码 MIT。数据由各原始来源的许可决定，不随本仓库分发。

## 当前进度

阶段 1（数据层）与阶段 2（溯源重建）已完成，阶段 3（服务化）可用：

- Gold 层 10 张 Parquet；索引库 `index/xist.duckdb` 1.4 GB 带 BM25 全文索引
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
