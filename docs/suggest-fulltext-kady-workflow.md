# 建议：把「全文获取」章节改写为 Kady 原生工作流

> **处置结论（2026-11-09，Claude Code）：已采纳，全部合入 `README.md` 第 3 节。**
> 第 5 节四个问题的答复：
> 1. 合入 README，不另立文档——本文保留为提出记录。
> 2. 是，`vocab.py:395` 的 docstring 一并改为 `gold/`，已提交。
> 3. 是，已改为「全库 82.7% 是 DOI 风格、已精注的 13,469 篇里 92.5% 是关键词风格」。
> 4. 批量规矩压缩成四条写进 README（串行间隔 / 先建档再取正文 / 失败分类 / 不用
>    Sci-Hub），详细操作留在本文。
>
> 采纳前逐条实测复核：abstract 全空、35 篇有全文未精注、oa.fcgi 404、
> PMC3535588 与 PMC5468617 的 eFetch 无 `<body>`、EPMC fullTextXML 返 500、
> NCBI BioC 对两篇各返 6,140 字节错误页——全部成立。另补一条本文没提到的判定
> 陷阱：字节数不能当成功标准，两篇错误页长度完全相同。
>
> 一条无法验证：`paper-lookup` 技能的 `jats_to_text.py` 不在本仓库，也不在本机
> 任何位置，README 里写成条件式路径并注明「别按图索骥去找」。

> 提出日期：2026-11-09
> 对象：`README.md` 第 3 节「全文：`papers/text/{paper_id}.txt`」及相关段落
> 依据：2026-11-09 在本地与实验服务器上的实测，以及 Kady `paper-lookup` 技能的既有能力

---

## 1. 为什么改

现有 README 第 3 节只写了一条路：

```bash
cd /path/to/XIST_Project_V2
py scripts/run_pipeline.py --parse
```

`--parse` 的前提是 `papers/pdf/` 里**已经有 PDF**。对 `abstract_only` 的 283,366 篇，
这一步什么也不做——它不会去取任何东西。README 因此没有回答「没有 PDF 时怎么办」，
而 `papers.csv` 里确实有一整类状态叫 `abstract_only`。

对 Kady 来说更关键的是：**Kady 已有经过验证的全文获取工具链**，也在本机可用；
让 agent 去重新手写 HTTP + 解析，是重复劳动且会重犯已知的陷阱。本文把这条路写成
README 可以接受的操作说明。

---

## 2. 实测得到的关键事实（全部为本次验证）

### 2.1 无精注池的真实构成

用平台自己的字段（`papers.has_text` / `has_annotation`）查索引库：

| 指标 | 数值 |
|---|---|
| `papers` 总数 | 296,835 |
| `has_annotation` | 13,469 |
| `has_text` | 13,431 |
| **有全文但无精注** | **27** |
| **有 PDF 但无精注** | **34** |
| **有全文或 PDF 且无精注** | **35** |
| 无精注总数 | 283,366 |

同时：`SELECT count(*) FROM papers WHERE abstract IS NOT NULL` → **0**。
**全库 abstract 字段 100% 为空**，无精注论文只有题录（DOI 283,352 篇 / 有期刊 25,517 篇 /
PMID 仅 145 / PMCID 0）。

结论：想给 `abstract_only` 做精注，**必须先把全文取回来**，没有第二条路。
`paragraph` 字段要求逐字复制原文，没有全文只能写 `not reported`，全部落到溯源 S/C 档。

### 2.2 全文可得率（抽样实测）

在「无精注 + 有 DOI」池中随机抽 20 篇，走 EuropePMC 查 PMCID → NCBI eutils 取 JATS：

| 结果 | 篇数 | 占比 |
|---|---|---|
| 无 PMCID（EuropePMC 查不到） | 11 | 55% |
| 有 PMCID 但只有元数据（非 OA） | 3 | 15% |
| **拿到 `<body>` 全文** | **6** | **30%** |

在**有 PMCID 的 9 篇里，6 篇能取到全文（67%）**。

即：`abstract_only` 池子按 DOI 全量尝试，**约 30% 能补到全文**（283,366 × 30% ≈ 8.5 万篇）。
上限不高，但绝对值可观。

### 2.3 三个已经踩过的坑

**坑 1：PMC OA Web Service 已于 2026-08-25 退役。**
`https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC...` 现在返回 **404**，
不能再用来做 OA 预检或取 FTP 包。实测对已知 OA 论文同样 404。

**坑 2：eFetch 对非 OA 论文返回 HTTP 200 + 无 `<body>`。**
这是最危险的失败——响应看起来成功，解析后只有标题/作者。
实测 PMCID 1500000 的 XML 里带一行注释：
`<!--The publisher of this article does not allow downloading of the full text in XML form.-->`
标准解析器会丢掉这行注释，agent 于是报「已获取全文」。

**坑 3：Europe PMC `fullTextXML` 对非 OA 返回 500，且有限速。**
实测同一 PMC 连续请求会 500，间隔约 30 秒后恢复。它比 eFetch 诚实（失败就是失败），
但**不适合批量爬**——容易把限速误判成「没有全文」。

### 2.4 Kady 原生工具已验证可用

`paper-lookup` 技能自带 `scripts/jats_to_text.py`，专门处理坑 2：

```bash
# 有全文：正常输出，exit 0
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=10700137&retmode=xml" \
  | py scripts/jats_to_text.py - --text-only -o "$OUT"

# 非 OA：exit 2，stderr 明确指出是出版方限制
# error: no <body> element: this document is metadata only, not full text
#        -- The publisher of this article does not allow downloading of the full text in XML form.
```

实测输出（PMC10700137，95,077 字节纯文本）：

```
MSL2 ensures biallelic gene expression in mammals

Main
Main Sexually reproducing organisms inherit one copy of each chromosome ...
```

**Windows 上必须用 `-o` 写文件，不要用 stdout。** 直接 stdout 会因 GBK 编码遇到
`\u2212`（减号）、`\u2013`（en dash）等字符崩掉：

```
UnicodeEncodeError: 'gbk' codec can't encode character '\u2212'
```

用 `-o` 写文件，或 `PYTHONIOENCODING=utf-8`，两者都实测可用；`-o` 更稳。

---

## 3. 建议的 README 改写

### 3.1 替换第 3 节全文

建议把「### 3. 全文：`papers/text/{paper_id}.txt`」整节替换为下面内容：

```markdown
### 3. 全文：`papers/text/{paper_id}.txt`

纯文本，UTF-8。缺了不阻塞入库，但该论文的所有 claim 都没有字符区间溯源，也不能在
全文检索页里定位。

#### 3.1 已有 PDF 的

```bash
cd /path/to/XIST_Project_V2
py scripts/run_pipeline.py --parse
```

`--parse` 只处理 `papers/pdf/` 里有、`papers/text/` 里没有的论文，可重复跑。
**它不会去下载任何东西**——没有 PDF 就什么也不做。

#### 3.2 没有 PDF 的：按可得性取开放获取全文

`papers.csv` 里 `status=abstract_only` 的 28 万余篇只有题录，`abstract` 字段在库里
全部为空。要给它们做精注，必须先把全文取回来。抽样实测：按 DOI 全量尝试，约 **30%**
能从开放获取渠道拿到结构化全文；有 PMCID 的论文里约 **67%** 能拿到。

获取顺序（每一层失败都往下一层走，**不要跳过判定直接解析**）：

| 顺序 | 来源 | 判定成功 | 说明 |
|---|---|---|---|
| 1 | EuropePMC `search` → 拿 PMCID | 有 `pmcid` 字段 | `resultType=core`，按 DOI 精确查 |
| 2 | NCBI eutils `efetch` `db=pmc` | XML 里**有 `<body>`** | 非 OA 会返回 200 但无 `<body>`，必须显式判 |
| 3 | Unpaywall `best_oa_location` | `url_for_pdf` 非空 | 拿 PDF 走 `--parse` |
| 4 | Europe PMC `fullTextXML` | HTTP 200 | 非 OA 返回 404/500，且有限速 |

**三条硬约束：**

1. **PMC OA Web Service（`oa.fcgi`）已于 2026-08-25 退役**，返回 404。不要再用它做
   OA 预检，也不要指望它给 FTP 包地址。
2. **eFetch 对非 OA 论文返回 HTTP 200 + 无 `<body>`**，只有一行被标准解析器丢弃的
   XML 注释说明出版方限制。**必须解析后确认 `<body>` 存在**，否则会把「只有标题和作者」
   当成「已获取全文」。
3. **Europe PMC `fullTextXML` 有限速**，连续请求会 500，间隔约 30 秒恢复。批量跑
   容易把限速误判成「该文没有全文」。

#### 3.3 在 Kady 里执行

Kady 的 `paper-lookup` 技能已经封装了上述判定，`scripts/jats_to_text.py` 会在
无 `<body>` 时 **exit 2** 并在 stderr 说明原因，不会把元数据当全文：

```bash
# 逐篇：DOI -> PMCID -> JATS -> 纯文本
PMCID=10700137
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=$PMCID&retmode=xml" \
  | py .pi/skills/paper-lookup/scripts/jats_to_text.py - --text-only -o "papers/text/${PAPER_ID}.txt"
```

退出码含义：

| exit | 含义 | 处置 |
|---|---|---|
| 0 | 拿到正文 | 继续 |
| 2 | 只有元数据，非 OA | 换 Unpaywall / 期刊 OA，或标 `abstract_only` |

**Windows 上必须用 `-o` 写文件**（或设 `PYTHONIOENCODING=utf-8`）。直接写 stdout
会因 GBK 编码遇到 `–`、`−` 等字符而 `UnicodeEncodeError`。

写入后做最小验收——正文应当远大于摘要，且含章节标题：

```bash
wc -c "papers/text/${PAPER_ID}.txt"          # 一般 > 10,000 字节
head -40 "papers/text/${PAPER_ID}.txt"       # 应见 Main / Results / Methods 等
```

低于 2,000 字节的，基本是拿错了内容，回到上一步重新判定，不要直接进库。
```

### 3.2 顺带修正两处事实错误

**（1）`silver/` 应改为 `gold/`**

README 第 111 行附近与 `docs/agent-prompt-add-paper.md` 都写：
> …再经 `silver/paper_id_map.parquet` 映射回真实文件名

实测 `paper_id_map.parquet` **在 `data/gold/`**，`data/silver/` 是空目录。证据：

- 文件实际位置：`/Data7/luyx/XIST-KB/data/gold/paper_id_map.parquet`（13,576 行）
- `migrate_v2.py:296`：`self.out_dir = out_dir or ensure_layer("gold")`；`write()` 写入 `self.out_dir`
- `extract/context.py:105` 的 docstring 写的正是 `gold/paper_id_map.parquet`（正确）
- 只有 `vocab.py:395` 的 docstring 写 `silver/`，是过期注释

不影响执行（无需手工打开该文件），但指错了目录。建议连同 `vocab.py:395` 一起改。

**（2）「88% 是 `{Author}{Year}_{keyword}`」口径不明**

实测两个口径结论相反：

| 口径 | `{Author}{Year}_{keyword}` | DOI 下划线化 |
|---|---|---|
| 全库 296,835 篇 | 12.2% | **86.9%** |
| 已精注 13,469 篇 | **83.1%** | 10.7% |

正文写「88% 的既有论文」读起来像全库，而全库正好相反。建议明确写成
「**已精注的 13,469 篇里** 83% 是 `{Author}{Year}_{keyword}`」，或直接说
「两种风格并存，新论文跟随该篇已有命名」。

### 3.3 可选：给「新增证据」加一节批量补全文

README 现在只覆盖「一篇一篇加」。既然 ~30% 的池子可得全文，值得说明批量作业的边界：

- **串行 + 间隔**：Europe PMC 有限速，实测需 ~0.4 秒/请求且偶发 500。并发会更快失败。
- **先建档再取正文**：先跑一遍 PMCID 解析，把「有 PMCID / 无 PMCID」分别落盘，
  再只对有 PMCID 的取正文。避免对 55% 注定失败的论文反复请求。
- **失败要记录，不要静默跳过**：每篇记 `ok / meta_only / no_pmcid / http_error`，
  汇总成 CSV。否则「补了 8.5 万篇」和「尝试了 8.5 万篇、成功 6 千」在报告里长得一样。
- **不要用 Sci-Hub**。V2 的 `download_papers.py` 里有这个分支，但本仓库的定位是
  可公开发布的知识库，绕版权的内容会让整份数据无法分发。

---

## 4. 建议不做的

- **不要写「免费全文都能拿到」**。实测只有 30%，如实写比例比给人错误预期好。
- **不要把 `abstract` 为空当成 bug**。全库为 0 是既有事实（原始层没抓），
  这不是全文获取能修的，属于另一个数据缺口。
- **不要用 `--parse` 代替下载**。`--parse` 只做 PDF→文本，没有 PDF 时它是空操作，
  这一点值得在 README 里写死，避免 agent 以为跑完就有全文。

---

## 5. 需要 Claude Code 确认的点

1. 上述第 3.1 节改写是否合入 README，还是只保留一份独立文档？
2. `silver/` → `gold/` 是否连同 `src/xist_kb/vocab.py:395` 的 docstring 一起修？
3. 「88%」口径是否按 3.2（2）改写？
4. 批量补全文那一节（3.3）要不要进 README，还是留在本文档作为操作备忘？

本文档只给建议，未修改 README 正文，也未改动任何代码。
