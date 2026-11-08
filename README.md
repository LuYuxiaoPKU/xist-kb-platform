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
新增一篇论文是「V2 侧写三样 → V2 侧跑两步 → 本仓库重建」的顺序，跳步会因为幂等跳过
而静默不生效。

```
metadata/papers.csv  ─┐
notes/json/*.json    ─┼─→ --claims ─→ notes/claims/*_claims.csv ─┐
papers/text/*.txt    ─┘                                          ├─→ migrate-v2 ─→ 平台
xist_knowledge.db    ────────── (--evidence --kb --rebuild) ─────┘
```

### 1. 注册条目：`metadata/papers.csv`

10 个字段，顺序固定，第一行是表头：

```
paper_id,title,year,journal,doi,pmid,species,taxonomic_group,first_author,status
```

一篇真实行的样子（字段少就用空值，不要填空格）：

```csv
deng2011_10_1038_nature09898,Evidence for compensatory upregulation of expressed X-linked genes,2011,Nature Genetics,10.1038/ng.986,22019772,Mus musculus,Rodent,Jun Deng,text_downloaded
```

`paper_id` 规则是 `{第一作者姓氏小写}{年份}_{DOI 下划线化}`。**四处必须完全一致**：
CSV 的 `paper_id`、`notes/json/{paper_id}.json`、`notes/claims/{paper_id}_claims.csv`、
`papers/text/{paper_id}.txt`。大小写不一致不会报错，只会变成两篇不同的论文。
平台在读取时统一小写，但不要让源数据依赖这一步。

`status` 有以下取值，含义是处理进度而非内容判断：

| 值 | 含义 | 平台是否收录 |
|---|---|---|
| `abstract_only` | 只有题录，无全文 | 是 |
| `text_downloaded` | 有全文 | 是 |
| `ingested` | 已完整纳入 | 是 |
| `duplicate_of_<paper_id>` | 判定为重复，指向正主 | 是 |
| `metadata_error` | 题录有问题 | 是 |

`species` 和 `taxonomic_group` 可留空——填了也不会自动推导到每条 claim（见
`docs/provenance-context.md` 的实测结论）。`doi` 不要带 `https://doi.org/` 前缀。

### 2. 精注 JSON：`notes/json/{paper_id}.json`

这是**唯一的人工证据来源**。模板 `templates/xist_paper.yaml`（226 行）定义了完整
schema，但只有 `claims` 数组是必填的——其余空着不会报错，只会让图表少一块。

最小可用文件：

```json
{
  "paper": {
    "title": "全文标题",
    "year": 2011,
    "journal": "Nature Genetics",
    "doi": "10.1038/ng.986",
    "pmid": "22019772",
    "species": "mouse",
    "taxonomic_group": "Rodent",
    "model_system": "mouse ESC",
    "data_type": "RNA-seq",
    "full_text_available": true
  },
  "claims": [
    {
      "claim": "Xist 缺失导致 X 连锁基因剂量补偿失败。",
      "topic": ["xist_rna_function"],
      "evidence": "Figure 2 的等位基因特异 RNA-seq",
      "evidence_type": "direct_experimental",
      "section": "results",
      "paragraph": "Deletion of Xist resulted in failure to establish dosage compensation...",
      "figure_or_table": "Figure 2B",
      "species": "Mus musculus",
      "cell_type": "mouse ESC",
      "confidence": "high",
      "directness": "direct",
      "caveat": "仅测了两个基因"
    }
  ]
}
```

`claims` 里 13 个字段逐条对应 `notes/claims/*_claims.csv` 的列，**改字段名会被静默丢弃**：

| JSON 字段 | 写入数据库的列 | 约束 |
|---|---|---|
| `claim` | `claim` | 必填。为空则该条被丢弃 |
| `topic` | `topic` | 字符串或数组。只认模板里那 20 个值，其他归一化到 `other`，不报错 |
| `evidence` | `evidence` | 自由文本 |
| `evidence_type` | `evidence_type` | 6 个枚举值之一 |
| `directness` | `directness` | `direct` / `indirect` / `speculative` |
| `section` | `section` | `abstract` / `introduction` / `methods` / `results` / `discussion` / `figure_legend` / `not_found` |
| `paragraph` | `quote` + 溯源区间 | **存原文引句，不是段号**。这是 P1/P2/P3 分级的唯一依据 |
| `figure_or_table` | `figure_or_table` | |
| `species` | `species` | 逗号或分号分隔多个物种，平台会归一化到拉丁名 |
| `cell_type` | `cell_type` | |
| `confidence` | `confidence` | `high` / `medium` / `low` |
| `caveat` | `caveat` | |

第二条硬约束是 `paragraph`。写成 `"Results section 1"` 这种段号时，该 claim 的溯源
标记为未定位（S 档），字符区间为空，全文定位功能对它失效。写原文引句，哪怕只有一句。

另外四个段落不走 `claims` 数组，而是各自成表。空着不报错，只是对应图表为空：

| JSON 段落 | 平台表 | 每条需要的字段 |
|---|---|---|
| `xist_identification` | `species_xist` | `xist_reported`、`repeat_structure`、`genomic_coordinates` |
| `xist_expression_regulation.regulators[]` | `regulations` | `name`、`direction`、`species` |
| `xist_protein_interactions.interactors[]` | `interactors` | `protein`、`method`、`function` |
| `x_chromosome_inactivation` | `xci_status` | `xci_type`、`initiation`、`maintenance` |

这四张表通过 V2 的 SQLite 中转，所以要跑 `--evidence --kb --rebuild`（见第 4 步）。

**注意 `regulators` 和 `interactors` 还会各自额外生成一条 claim。** `--claims` 除了
转写 `claims` 数组，还会为每个 regulator 生成 `"{name} {direction} XIST expression"`、
为每个 interactor 生成 `"{protein} interacts with XIST ({function})"`，topic 分别是
`xist_expression_regulation` 和 `xist_protein_interactions`。这些自动行没有
`paragraph`，所以不进字符区间溯源，但**会出现在检索结果里**。同一个发现如果已在
`claims` 里手写过，就不要再在 `regulators`/`interactors` 里重复一遍，否则检索会看到两条。

`xist_identification` 和 `x_chromosome_inactivation` 不产生 claim，只进表。

**查不到的写 `"not reported"`。不要推测，不要补全。** 这个库出过编造 Addgene
编号的事故，事后靠人工逐条核对才发现。

### 3. 全文：`papers/text/{paper_id}.txt`

纯文本，UTF-8。缺了不阻塞入库，但该论文的所有 claim 都没有字符区间溯源，也不能在
全文检索页里定位。已有的 PDF 走 V2 的 `--parse` 生成：

```bash
cd /path/to/XIST_Project_V2
py scripts/run_pipeline.py --parse
```

`--parse` 只处理 `papers/pdf/` 里有、`papers/text/` 里没有的论文，可重复跑。

### 4. 在 V2 侧抽出派生层

```bash
cd /path/to/XIST_Project_V2
py scripts/run_pipeline.py --claims              # JSON → notes/claims/*_claims.csv
py scripts/run_pipeline.py --evidence --kb --rebuild   # JSON → evidence tables → SQLite
```

**`--claims` 是幂等跳过已存在 CSV 的。** 改了已有论文的 JSON 之后必须先删旧 CSV，
否则新内容不会生效：

```bash
rm notes/claims/{paper_id}_claims.csv
```

`--evidence` 相反，每次都全量覆盖重写 `reviews/evidence_tables/*.csv`，不需要手动删。

`--kb` 必须连 `--rebuild`。不带时是追加插入，同一批 claims 会被写第二遍，表直接翻倍。
**绝不要同时跑两个 `--kb --rebuild`**——DROP 与 INSERT 交错的结果同样是翻倍。

### 5. 在本仓库重建

```bash
export XIST_KB_DATA=/path/to/XIST-KB/data
xist migrate-v2 /path/to/XIST_Project_V2
python scripts/rebuild_derived.py
```

`migrate-v2` 读 V2 的 `papers.csv`、`notes/claims/*.csv`、`xist_knowledge.db` 三样，
缺任一样直接报错退出；`notes/json` 只用来标记 `has_annotation`。`papers/text/*.txt`
不在检查之列——完全没有它也能迁移，只是所有 claim 都没有字符区间溯源。
`rebuild_derived.py` 固化了两者之间的全部顺序依赖，不要手动分步跑。

重建前先停服务——服务进程会锁住 DuckDB 文件，原子替换会失败：

```bash
cd /path/to/XIST-KB/app && ./deploy/serve.sh stop
# ...迁移与重建...
./deploy/serve.sh start
```

改完必查两个不变式，都应为 0：

```bash
python -c "import duckdb;c=duckdb.connect('$XIST_KB_DATA/index/xist.duckdb',read_only=True);print('dup',c.execute('SELECT count(*)-count(DISTINCT claim_id) FROM claims').fetchone()[0],'orphan',c.execute('SELECT count(*) FROM claims WHERE paper_id NOT IN (SELECT paper_id FROM papers)').fetchone()[0])"
```

`dup` 不为 0 说明跑了两遍导入；`orphan` 不为 0 说明 claims CSV 的 `paper_id` 与
`papers.csv` 大小写或拼写不一致。

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
