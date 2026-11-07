# xist-kb-platform

XIST / X 染色体失活 (XCI) 文献知识库与检索平台。

面向 296,835 篇注册文献、115,674 条结构化 claims 的分层数据平台：Parquet 分层存储 + DuckDB 查询 + FastAPI/React 服务化，支持字符区间级证据溯源。

## 状态

**规划阶段**。本仓库当前只有骨架，尚无可用功能。设计文档见 [docs/plan.md](docs/plan.md)。

## 架构

```
原始层      ID 与溯源层      知识层         存储层            服务层
OpenAlex    DOI/PMID/PMCID   papers         Bronze JSONL.gz   FastAPI REST
Crossref    OpenAlex ID      claims         Silver Parquet    DuckDB 查询
Europe PMC  source+date      chunks         Gold Parquet      React 前端
Unpaywall   provenance       citations      索引              SSE 问答
```

详细设计见 [docs/architecture.md](docs/architecture.md)。

## 快速开始

```bash
git clone https://github.com/LuYuxiaoPKU/xist-kb-platform.git
cd xist-kb-platform
uv sync
uv run xist --help
```

## 目录

| 路径 | 用途 |
|---|---|
| `src/xist_kb/ingest/` | 原始层 → ID 层：多源抓取、检索式、ID 消歧 |
| `src/xist_kb/extract/` | 文本提取、JATS 解析、段落切分 |
| `src/xist_kb/annotate/` | LLM 精注、规则提取、注释溯源 |
| `src/xist_kb/build/` | 知识层 → Parquet，claim/chunk 对齐 |
| `src/xist_kb/query/` | DuckDB 查询引擎、检索、导出 |
| `src/xist_kb/api/` | FastAPI 路由与认证 |
| `web/` | React 前端（待建） |
| `deploy/` | systemd / nginx / docker-compose |
| `data/` | 运行期数据，不入库 |

## 数据来源

- 文献元数据：OpenAlex、Crossref、PubMed E-utilities、Europe PMC
- 开放获取全文：PMC OA、Europe PMC fullTextXML
- 引文：OpenCitations
- LLM 注释：Claude (Anthropic)

## 许可

代码 MIT。数据由各原始来源的许可决定，不随本仓库分发。
