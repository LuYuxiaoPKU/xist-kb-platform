# XIST Knowledge Base 重构企划书（V2 → V3）

> 起草日期：2026-11-08
> 状态：规划阶段，未动工
> 现有项目：`C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V2`
> 本文件位置：临时规划目录，不属于现有仓库

---

## 1. 现状诊断（基于 2026-11-08 实测）

### 1.1 数据规模

| 项目 | 数量 | 体积 |
|---|---|---|
| 注册文献（`papers` 表 / `metadata/papers.csv`） | 296,835 篇 | 57 MB CSV |
| 有全文文本（`papers/text/*.txt`） | 13,502 篇 | 681 MB |
| 本地 PDF（`papers/pdf/*.pdf`） | 2,847 篇 | 6.7 GB |
| 注释 JSON（`notes/json/*.json`） | 13,469 个 | 279 MB |
| Claims CSV（`notes/claims/*_claims.csv`） | 12,127 篇 | 97 MB |
| SQLite KB（`xist_knowledge.db`） | 217 MB, 6 张表 | — |
| 证据表（`reviews/evidence_tables/*.csv`） | 11 张 | 122 MB |
| Git 仓库 | 28 commits | 746 MB |

KB 各表行数：`papers` 296,835 / `claims` 115,674 / `regulations` 3,425 / `interactors` 5,362 / `xci_status` 9,984 / `species_xist` 13,469。

### 1.2 诊断出的结构性问题

以下全部为本次勘探实测，不是推测。

**P1 — 注册库与有效数据严重失衡。** 296,835 篇中 283,360 篇 `status=abstract_only`（95.5%），仅 2,431 篇 `ingested`。claims 只覆盖 12,123 篇（4.1%）。也就是说 96% 的注册记录目前只是空壳，但它们在库里与有证据的文献以同样权重出现。

**P2 — 证据溯源不可靠。** 抽样 200 篇有全文的 claims（2,053 条带 `paragraph` 字段），归一化后只有 1,078 条能在对应 `papers/text` 中精确匹配，命中率 **52.5%**。其余要么是模型改写而非原文引用，要么指向错误位置。这意味着「点击 claim 跳转原文」这个最核心的可信度功能目前无法实现。

**P3 — 注释来源不可追溯。** 13,469 个注释 JSON 中**没有任何一个**记录注释方法（LLM 模型/版本/prompt 模板/时间）。只能靠 claims 的 `evidence_type='rule_extraction'`（6,599 条）间接反推哪些是规则提取。无法回答「这条 claim 是哪个模型在什么时候按哪版模板生成的」。

**P4 — 受控词表污染。** `claims.confidence` 里混着 `['high']`（559 条）、`['medium']`（299 条）、`['low']`（87 条）这类列表字符串残留；`section` 同时存在 `not_reported` 和 `not reported` 两种写法（共 15,425 条）；`evidence_type` 混有 `not reported` 与 `rule_inference`、`review_inference` 等未登记值。`papers.year` 是**文本类型**且含 `'not reported'`；295,559 篇 `species` 为空字符串；70 组 DOI 重复。

**P5 — 文件层与数据库层不一致。** JSON 13,469 / text 13,502 / claims 12,127 / PDF 2,847 四个集合两两不等：765 个 JSON 无对应 text、11,896 个 JSON 无 PDF、798 个 text 无 JSON。没有单一事实来源（single source of truth）。

**P6 — 代码结构崩塌。** `src/xist_v2/` 只有 3,184 行、6 步管线；`scripts/` 堆了 **302 个**一次性脚本（大量 `*_20260927.py`、`fix_*`、`audit_*`、`batch_*`），无测试（`tests/` 为空），无 CLI 统一入口。任何增量更新都靠手写新脚本，无法复用、无法回归验证。

**P7 — 主题分类退化。** `other` 占 35,108 条（30.3%），是第一大「主题」；`chromatin` 17,263 条过于宽泛。主题体系无法支撑按主题的证据聚合。

**P8 — 引文层只有裸表。** `xist_citations.csv` 296,387 行，只有 8 列（paper_id, doi, pmid, year, journal, title, first_author, species），没有引用方向、被引/施引区分、DOI 归一，无法做引文网络分析或影响力加权。

### 1.3 与参考资料（`docs/ref_20261108/`）的差距

用户提供的三张图给出的是一个五层参考架构：

```
原始层   → ID 与溯源层 → 知识层 → 存储层 → 服务层
PubMed/EPMC  DOI/PMID/PMCID/  引文即一等实体  Bronze/Silver/Gold  REST/SPARQL/
Crossref     OpenAlex ID/     作者/机构消歧    CSV/Parquet/SQLite  FTS5+向量/
OpenAlex     OMID/OCI         facet JSON       RDF/GraphML        NetworkX/RAG
S2/OpenCitations  ROR/ORCID    概念/模型/疾病/
Unpaywall/PMC OA  source+date   证据等级
```

对照现状：

| 参考层 | 现状 | 差距 |
|---|---|---|
| 原始层 | 有 PDF + text，但只有 XIST 主题 | 无原始 API 响应留存（Bronze），抓取结果直接落成加工态 |
| ID 与溯源层 | 有 DOI/PMID，paper_id 自造 | 无 PMCID/OpenAlex ID/OMID/OCI；无 source + retrieval_date + version；无 ROR/ORCID |
| 知识层 | 有 claims/interactors/regulations | 引文不是一等实体；无作者/机构消歧；无 facet JSON；无证据等级体系 |
| 存储层 | 单文件 SQLite | 无分层（Bronze/Silver/Gold）；无 Parquet；无 RDF/GraphML 导出 |
| 服务层 | 无 | 无 REST、无 FTS5、无向量检索、无可视化接口 |

参考图 3 还给出了检索式设计：MeSH/字段检索 → ESearch/Post with `usehistory=y` → WebEnv+QueryKey → retstart 每批 ≤100 → EFetch 分批 → OpenAlex/S2/OC 扩展与归并 → 去重/证据/许可证 → 冲突人工裁定。现状的抓取是一次性脚本 + Crossref/OpenAlex 直查，没有 History Server 增量机制。

### 1.4 与 k-dense-desktop 的关系

用户已明确：**本次重构暂不引入 k-dense-desktop**。但架构上为其留接口——V3 的服务层应暴露标准 MCP server，使 k-dense 或任何 agent 客户端可挂载。这一点写入第 8 节「后续扩展点」，不在本期范围。

---

## 2. 重构目标

用户确认的四类优先问题（全选）：

1. **服务化，全组可访问** — 部署在实验室 Linux 服务器，随时启动与访问
2. **数据质量与证据可信度** — 溯源、置信度、可验证性
3. **检索与总结能力** — 语义检索、跨论文证据聚合、自动综述草稿
4. **工程可维护性** — 统一 CLI、测试、增量更新

用户确认的交付形态与存储：

- **部署**：实验室 Linux 服务器（有 SSH、可装软件），GitHub 只托管代码，数据留在服务器
- **存储**：Parquet 分层 + DuckDB
- **前端功能**（全选）：检索与浏览 / 证据审阅与标注 / 导出与可视化 / 问答式检索
- **数据迁移**：保留现有 claims，另建 chunk 索引重建溯源，不重跑 LLM 注释
- **溯源粒度**：字符区间级（网页可高亮跳转）
- **访问控制**：简单密码 / 内网 IP 限制，不建用户体系
- **技术栈**：Python (FastAPI) + React
- **注释预算**：本期先不决定，但需预留作业队列的设计

---

## 3. 目标架构

### 3.1 分层设计（对齐参考资料五层）

```
┌─────────────────────────────────────────────────────────────────┐
│ 服务层  (V3/api)                                                │
│   FastAPI REST  ·  DuckDB 查询  ·  FTS/向量检索  ·  SSE 流式问答  │
│   React 前端（检索/审阅/导出/可视化/问答）                        │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│ 存储层  (V3/data, 不入 git)                                      │
│   Gold:   Parquet — claims.parquet / papers.parquet / ...        │
│   Silver: Parquet — 规范化后的实体表 + chunk 表                  │
│   Bronze: JSONL.gz — 原始 API 响应（OpenAlex/Crossref/EPMC）     │
│   索引:   DuckDB 视图 + FTS5 索引 + 向量索引（可选）              │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│ 知识层  (V3/kb)                                                  │
│   实体: papers / claims / chunks / interactors / regulations /   │
│         xci_status / species_xist / citations / provenance       │
│   关系: claim → chunk(字符区间) / claim → paper / paper → citation │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│ ID 与溯源层  (V3/ingest)                                         │
│   paper_id 规范化  ·  外部 ID 映射表（DOI/PMID/PMCID/OpenAlex）   │
│   每条记录携带 source + retrieval_date + version                │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│ 原始层  (V3/ingest/bronze)                                       │
│   OpenAlex / Crossref / Europe PMC / PubMed E-utilities /        │
│   Unpaywall / PMC OA  — 带 History Server 增量抓取               │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 目录结构

```
XIST_Project_V3/                      # 独立仓库 xist-kb-platform（public，已定，见 9.1）
├── src/xist/
│   ├── ingest/                       # 原始层 → ID 层
│   │   ├── sources/                  # openalex.py crossref.py epmc.py pubmed.py
│   │   ├── search.py                 # MeSH/字段检索式构造
│   │   ├── fetch.py                  # History Server 分桶增量
│   │   └── normalize.py              # ID 消歧、版本合并
│   ├── extract/                      # 原始层 → 文本/PDF
│   │   ├── parse.py                  # pymupdf/pdfplumber 双引擎（复用现有）
│   │   ├── xml.py                    # JATS 解析（Europe PMC fullTextXML）
│   │   └── chunk.py                  # 段落/句子切分，产出 chunk 表
│   ├── annotate/                     # 知识层 ETL
│   │   ├── llm.py                    # Claude 调用（复用 claude_agent.py）
│   │   ├── rule.py                   # 规则提取（复用 rule_extract.py）
│   │   ├── schema.py                 # Pydantic 模型 + JSON Schema
│   │   └── provenance.py             # 记录模型/prompt 版本/时间
│   ├── build/                        # 知识层 → 存储层
│   │   ├── claims.py                 # claims 扁平化（复用 claims.py）
│   │   ├── evidence.py               # 证据表（复用 evidence.py）
│   │   ├── link.py                   # claim → chunk 字符区间对齐（新增）
│   │   └── publish.py                # 写 Parquet + DuckDB 视图
│   ├── query/                        # 存储层 → 服务层
│   │   ├── engine.py                 # DuckDB 连接与 SQL 模板
│   │   ├── search.py                 # 关键词 + 结构化过滤 + 向量（可选）
│   │   └── export.py                 # CSV/Excel/BibTeX/GraphML
│   ├── api/                          # FastAPI
│   │   ├── main.py
│   │   ├── routes/
│   │   └── auth.py                   # 简单密码 / IP 白名单
│   └── cli.py                        # 统一 CLI（typer），替代 302 个脚本
├── web/                              # React（Vite + React Router + TanStack Query）
├── templates/                        # YAML 注释模板（复用现有）
├── tests/                            # pytest，覆盖 ingest/extract/annotate/build
├── data/                             # 运行期数据（.gitignore）
├── deploy/                           # systemd unit / docker-compose / nginx
├── config.yaml
└── pyproject.toml
```

### 3.3 关键数据表（Parquet schema）

**papers.parquet**

```python
paper_id: string          # 主键，规范化后的稳定 ID
doi: string | null
pmid: string | null
pmcid: string | null
openalex_id: string | null
title: string
abstract: string | null
year: int | null
journal: string | null
first_author: string | null
authors: list<string>
species: list<string>     # 归一化后的 Latin binomial
taxonomic_group: string | null
status: string            # registered / text_available / annotated / reviewed
has_text: bool
has_pdf: bool
source: string            # openalex / crossref / pmc_oa / manual
retrieved_at: timestamp
```

**chunks.parquet**（新增，支撑字符区间溯源）

```python
chunk_id: string          # {paper_id}:{offset_start}
paper_id: string
text: string
offset_start: int
offset_end: int
section: string | null    # 从正则/标题推断
paragraph_index: int
```

**claims.parquet**

```python
claim_id: string          # 稳定 hash，便于人工标注引用
paper_id: string
chunk_id: string | null   # 关联到 chunk
quote: string | null      # 原文精确引用（重建溯源后填充）
quote_offset_start: int | null
quote_offset_end: int | null
claim: string             # 归一化后的一句话
topic: string             # 受控词表
evidence_type: string
directness: string
section: string
species: list<string>
cell_type: string | null
confidence: string
caveat: string | null
provenance_id: string     # 外键 → provenance.parquet
```

**provenance.parquet**（新增，解决 P3）

```python
provenance_id: string
paper_id: string
method: string            # llm / rule / manual
model: string | null      # claude-sonnet-4-5 等
prompt_template: string | null
prompt_hash: string | null
runtime_seconds: float | null
created_at: timestamp
source_checksum: string   # 输入文本的 sha256，防止文本变更后注释失效
```

**citations.parquet**（升级 P8）

```python
source_paper_id: string
target_paper_id: string | null
target_doi: string | null
direction: string         # cites / cited_by
source_db: string         # opencitations / openalex / crossref
retrieved_at: timestamp
```

**interactors / regulations / xci_status / species_xist** 各一张 Parquet，字段沿用现有并补充 `claim_id` 反查外键与 `provenance_id`。

---

## 4. 分阶段实施计划

每阶段都有独立验收标准，可按可用时间分批推进。

### 阶段 0 — 基线与备份（1 天）

- 冻结 V2 当前状态：`git tag v2-final`，确认备份仓库 `LuYuxiaoPKU/xist-kb` 已同步
- 导出 V2 全量数据快照到 `data/snapshot_v2_20261108/`（papers.csv + JSON + claims CSV + DB）
- 建立 V3 仓库骨架与 CI（pytest + ruff + mypy）

**验收**：快照可完整重建 V2 的 KB；CI 通过空测试。

### 阶段 1 — 存储层与迁移（3–5 天）

- 实现 `build/publish.py`：从 V2 的 papers.csv / JSON / claims CSV / SQLite 抽取，写 Bronze/Silver/Gold Parquet
- 实现受控词表清洗：`not reported` 归一、`['high']` 解析、year 转 int、species 列表化
- 建立 DuckDB 视图，提供与 V2 SQLite 等价的查询接口
- 产出 `data/quality_report.md`：记录清洗前后的差异计数

**验收**：DuckDB 查询结果与 SQLite 在 claims 总数、topic 分布、paper 数上一致（允许清洗导致的已知差异，需逐条列出）；总 Parquet 体积 < 150 MB。

### 阶段 2 — 溯源重建（5–8 天）

这是本期最关键、也最容易低估的一阶段。

- 实现 `extract/chunk.py`：按段落 + 句子切分 text，产出 `chunks.parquet`
- 实现 `build/link.py`：把现有 claims 的 `paragraph` 字段与 chunks 做模糊对齐
  - 精确匹配（当前 52.5%）→ 直接记录字符区间
  - 模糊匹配（rapidfuzz，阈值可调）→ 记录区间 + `match_score`
  - 无法匹配 → `chunk_id=null`，标记 `needs_review`
- 对无法匹配的 47.5% 做归因分析：是模型改写、文本版本不同，还是 claim 本身来自摘要
- 可选：用 Claude 对 `needs_review` 的 claims 做一次「重定位」批量作业（只需定位，不需重新生成 claim）

**验收**：溯源覆盖率（含模糊匹配）≥ 85%；所有 `quote_offset` 能被独立脚本验证在原 text 中；`quality_report.md` 更新。

### 阶段 3 — 查询层与服务层（5–8 天）

- 实现 `query/engine.py`：DuckDB 查询封装，支持 topic/species/year/confidence/protein 组合过滤
- 实现 `query/search.py`：DuckDB FTS（`fts` 扩展）关键词检索；向量检索列为可选扩展
- FastAPI 路由：
  - `GET /api/papers`、`GET /api/papers/{id}`
  - `GET /api/claims`（分页 + 过滤）
  - `GET /api/claims/{id}/context`（返回原文片段 + 字符区间）
  - `GET /api/interactors`、`GET /api/regulations`、`GET /api/xci_status`
  - `GET /api/export`（CSV/Excel/BibTeX）
  - `GET /api/stats`（时间线、主题分布、物种分布）
- 简单认证：`X-API-Key` 或 HTTP Basic + IP 白名单（nginx 或 FastAPI middleware）

**验收**：所有端点有 OpenAPI 文档 + 集成测试；100 万次查询压测下 P95 < 200ms（DuckDB 本地文件）。

### 阶段 4 — React 前端（8–12 天）

四个页面，对应四个确认功能：

1. **检索与浏览** `/search`：组合过滤 + 结果列表 + 详情抽屉（显示 claim、原文高亮、来源论文）
2. **证据审阅** `/review`：逐条 claims 卡片，支持「正确 / 错误 / 存疑」三态标注，写入 `annotations.parquet`
3. **导出与可视化** `/explore`：时间线、主题分布、互作网络（vis-network 或 Cytoscape.js）、一键导出
4. **问答** `/ask`：自然语言输入 → 后端检索相关 claims → LLM 生成带引用的答案

**验收**：所有页面在 1366×768 与 1920×1080 下可用；导出文件可在 Excel 中正常打开；审阅标注持久化。

### 阶段 5 — 问答与总结（5–8 天，可与阶段 4 并行）

- 检索增强：query → 关键词/向量召回 top-k claims → 重排 → 送入 Claude 生成
- 每条论断强制带 `claim_id` 引用，前端可点击回原文
- 提供「综述草稿」模式：给定主题，聚合 top claims + 冲突 claim 检测，生成结构化综述

**验收**：10 个典型问题的答案中，引用可验证率 ≥ 95%；有明显冲突的 claim 点能被自动标出。

### 阶段 6 — 部署与运维（2–3 天）

- `deploy/`：systemd unit（API）+ nginx（静态前端 + 反代）+ 可选 docker-compose
- 数据更新流程：`xist ingest --since 2026-11-01` → `xist build` → 热重载 DuckDB 视图
- 日志与监控：结构化日志 + 简单健康检查端点
- 备份：Parquet 层定期打包到备份仓库（与 V2 备份策略一致）

**验收**：断电重启后服务自动恢复；更新流程可在不停机情况下完成。

---

## 5. 数据质量治理方案（对应 P1–P8）

| 问题 | 方案 | 阶段 |
|---|---|---|
| P1 注册库空壳 | `papers.status` 分级（registered/text_available/annotated/reviewed）；前端默认只看 annotated，可切换 | 1 |
| P2 溯源 52.5% | 重建 chunk 索引 + 模糊对齐；无法匹配的标 `needs_review` | 2 |
| P3 来源不可追溯 | 新增 `provenance.parquet`；所有新注释强制记录模型/prompt 版本/时间 | 1（schema）+ 后续注释 |
| P4 词表污染 | 一次性清洗脚本 + Pydantic 校验；写入 Parquet 前强制校验 | 1 |
| P5 文件不一致 | 以 Parquet 为唯一事实来源；文件层只是产物，可随时重建 | 1 |
| P6 代码崩塌 | 统一 CLI + 302 个脚本只保留可复用的约 20 个，其余归档到 `legacy/` | 全程 |
| P7 主题退化 | 重新设计 topic 体系（合并 chromatin 子类、拆分 other），建立映射表 | 1–2 |
| P8 引文裸表 | 升级 citations 表，补方向、来源、目标 ID；接入 OpenCitations | 1 |

---

## 6. 检索与问答设计要点

### 6.1 检索

- **结构化过滤优先**：先按 topic/species/year/confidence 缩小范围，再做关键词匹配，比纯语义检索更可控且可解释
- **FTS5/BM25**：DuckDB 的 `fts` 扩展可用；若无，回退到 SQLite FTS5 索引（与 Parquet 并行维护）
- **向量检索**（可选）：对 chunk 做 embedding，存储为 Parquet 列；本地模型（如 bge-m3）避免外发数据

### 6.2 问答

```
用户问题
   ↓
结构化过滤（LLM 抽取 species/topic/year 约束）
   ↓
关键词 + 向量混合召回 top-50 claims
   ↓
重排（按 confidence、evidence_type、recency）
   ↓
Claude 生成答案（强制每条论断引用 claim_id）
   ↓
前端渲染：答案 + 可点击引用 + 冲突提示
```

关键约束：**不允许无引用论断**。若召回证据不足，答案应明确说「现有证据不支持」。

---

## 7. 部署方案

### 7.1 服务器

- Linux + SSH，可安装软件
- 依赖：Python 3.11+、Node 20+（仅构建期）、nginx（或 Caddy）、systemd
- 数据目录：`/srv/xist/data/`（Parquet + DuckDB 文件）
- 代码：`/srv/xist-kb-platform/app/`，由 GitHub 拉取

### 7.2 运行

```bash
# 首次
git clone https://github.com/LuYuxiaoPKU/xist-kb-platform.git /srv/xist-kb-platform/app
cd /srv/xist-kb-platform/app && uv sync
uv run xist build --from-snapshot data/snapshot_v2_20261108

# 日常
sudo systemctl start xist-api      # FastAPI
sudo systemctl start xist-web      # nginx 静态 + 反代
```

### 7.3 访问控制

- nginx `allow <内网网段>; deny all;`
- 或 FastAPI middleware 校验 `X-API-Key`
- 两者可叠加

---

## 8. 后续扩展点（不在本期）

1. **MCP server**：把 `query/` 层包装成 MCP server，供 k-dense-desktop、Claude Desktop 或其他 agent 客户端调用。这是与 k-dense 对接的自然切口，但用户已确认本期不引入。
2. **RDF/GraphML 导出**：claims → 三元组，供 Neo4j/SPARQL 查询。
3. **增量更新自动化**：`xist ingest --since` 挂到 cron，配合 History Server 增量抓取。
4. **多用户标注**：当前只做单机标注；若未来需要多人协作，再引入用户表与审计日志。
5. **跨主题泛化**：把 XIST 专用逻辑抽象成通用 lncRNA/表观遗传挖掘框架。

---

## 9. 待决问题（需用户确认）

### 9.1 仓库形态（已定）

**新建独立公开仓库 `LuYuxiaoPKU/xist-kb-platform`（public），V2 保留归档为 `v2-final`。** V2 的 302 个脚本与 746 MB git 历史对新架构无价值，不带入。数据通过阶段 1 的一次性快照迁移完成，迁移后 V3 不依赖 V2 的工作树。

### 9.2 数据迁移边界

- 现有 279 MB JSON 注释是否保留为 Bronze 层原始记录？（建议保留，作为可追溯性的一部分）
- 6.7 GB PDF 是否纳入服务器数据目录？（建议纳入，但单独分区，不进备份仓库）

### 9.3 阶段 2 的模糊匹配阈值

需要人工抽检确定可接受的 `match_score` 下限。建议先做 100 条样本，由用户确认哪些算「可接受」。

### 9.4 问答是否本期上线

阶段 5 依赖 Claude API 或本地模型。若服务器无外网访问 Claude API，需要改为本地模型（如 Qwen）或先只做检索不做问答。

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 溯源重建后仍有大量无法对齐 | 可信度目标打折 | 阶段 2 先做样本评估，再决定是否投入重跑 |
| DuckDB 并发写入 | 更新时服务不可用 | 写入新 Parquet → 原子替换 → 重载视图 |
| 服务器无外网 | 无法调用 Claude API | 问答改为本地模型或离线模式 |
| 前端工期超预期 | 阻塞交付 | 先交付只读检索页，审阅/可视化后续迭代 |
| 用户时间投入不足 | 项目停滞 | 每阶段独立可交付，不依赖全量完成 |

---

## 附录 A：现有代码资产盘点（可复用 vs 归档）

| 现有文件 | 行数 | 处置 |
|---|---|---|
| `src/xist_v2/pipeline/parse.py` | 125 | 复用为 `extract/parse.py` |
| `src/xist_v2/pipeline/annotate.py` | 153 | 重构为 `annotate/llm.py` |
| `src/xist_v2/pipeline/claims.py` | 461 | 复用为 `build/claims.py` |
| `src/xist_v2/pipeline/evidence.py` | 448 | 复用为 `build/evidence.py` |
| `src/xist_v2/pipeline/rule_extract.py` | 573 | 复用为 `annotate/rule.py` |
| `src/xist_v2/pipeline/review.py` | 416 | 重构为 `query/` + 前端 |
| `src/xist_v2/llm/claude_agent.py` | 285 | 复用，补 provenance 记录 |
| `src/xist_v2/db/engine.py` | 249 | 替换为 DuckDB 实现 |
| `src/xist_v2/db/schema.py` | 95 | 替换为 Parquet schema |
| `src/xist_v2/config.py` | 82 | 复用 |
| `src/xist_v2/utils/*` | 128 | 复用 |
| `scripts/` 302 个 | — | 仅保留约 20 个核心，其余移入 `legacy/` |

## 附录 B：参考资料清单

- `docs/ref_20261108/data_platform_scale.csv`：外部平台规模数据（OpenAlex 437M works、Crossref 188.9M、S2 241M 等）
- `docs/ref_20261108/fig_1_platform_scale.png`：平台规模对比
- `docs/ref_20261108/fig_2_architecture.png`：五层架构参考
- `docs/ref_20261108/fig_3_xist_retrieval.png`：检索式与增量抓取流程
- `docs/ref_20261108/ocr.txt`：上述图片的 OCR 文本
