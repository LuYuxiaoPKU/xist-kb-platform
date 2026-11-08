# 远程新增文献与证据：给 agent 的操作 prompt

复制下面整段作为任务 prompt。把 `<...>` 换成你要加的论文。

---

## 任务

把一篇（或几篇）新文献加入 XIST 知识库，并在实验室服务器上重建可查询层。

服务器 `162.105.248.197`，用户 **`luyx`**（普通账号）。全程不得使用 root、
`sudo`、`su root`。所有路径写绝对路径。

## 关键前提：三个位置各有什么

先读这一节再动手，否则会改错地方。

| 位置 | 内容 | 能不能跑 V2 代码 |
|---|---|---|
| 本地 `C:/00_Data/实验室/实验室/MetaAnalysis/XIST_Project_V2` | V2 全量源数据 + `src/xist_v2` 代码 + `templates/` + `claude` CLI | **能**。注释、claims 抽取、证据表、SQLite 都只在这里做 |
| 本地 `.../MetaAnalysis/xist-kb-platform` | 平台代码（git 仓库） | 能，但只做开发测试 |
| 服务器 `/Data7/luyx/XIST-KB/data/v2src` | V2 源数据的副本（`metadata/`、`notes/`、`papers→`、`xist_knowledge.db`） | **不能**。没有 `src/xist_v2`，没有 `claude` CLI |
| 服务器 `/Data7/luyx/XIST-KB/app` | git clone 的平台代码 + `.venv` + `.env` | 能跑 `xist migrate-v2` 和 `scripts/rebuild_derived.py` |

结论：**注释和派生表在本地做完，只把产物同步到服务器，然后在服务器重建。**

## 第 1 步：确认论文不在库中

在本地 V2 目录：

```bash
cd "C:/00_Data/实验室/实验室/MetaAnalysis/XIST_Project_V2"
grep -i "<doi 或标题关键词>" metadata/papers.csv
```

有结果就停下，报告已存在的那一行。不要重复添加。

## 第 2 步：写三样东西（都在本地 V2 目录）

### 2.1 `metadata/papers.csv` 加一行

表头固定 10 字段：`paper_id,title,year,journal,doi,pmid,species,taxonomic_group,first_author,status`

`paper_id` 规则：`{第一作者姓氏}{年份}_{DOI 中非字母数字字符替换为下划线}`，
姓氏首字母大写。例：DOI `10.1038/ng.986`、2011 年、第一作者 Deng →
`Deng2011_10_1038_ng_986`。

库里 88% 的论文并不用这种 DOI 风格，而是 `{Author}{Year}_{keyword}`，例如
`Balaton2016_escape`、`Lee2005_regulation`、`Deng2011_evidence`。两种风格并存是
历史事实。**新论文跟随该论文在 V2 里已有的命名**——如果 PDF 已经叫某个名字，
就用那个名字，不要按 DOI 规则重命名。只有全新加入、毫无既有命名的论文才用 DOI 风格。

下面四个文件用**同一个** `paper_id`：
- `metadata/papers.csv` 里的 `paper_id`
- `notes/json/{paper_id}.json`
- `notes/claims/{paper_id}_claims.csv`
- `papers/text/{paper_id}.txt`

**大小写不必完全一致**——平台在读取时统一小写（`vocab.py:normalize_paper_id`），
并通过 `silver/paper_id_map.parquet` 映射回磁盘上的真实文件名。实测：注册表用
`balaton2016_escape`、三个文件用 `Balaton2016_Escape`，迁移后 claims 与全文都能
正确关联。但**拼写必须一致**：`Deng2011_evidence` 与 `Deng2011_expression` 会被
当成两篇论文，前者有全文、后者变成孤儿 claim。

`status` 填 `text_downloaded`（有全文）或 `abstract_only`（只有题录）。
查不到的字段留空，不要填空格或 `NA`。

### 2.2 `notes/json/{paper_id}.json` 精注

模板见 `templates/xist_paper.yaml`（226 行）。最小结构：

```json
{
  "paper": {
    "title": "...", "year": 2026, "journal": "...",
    "doi": "...", "pmid": "not reported",
    "species": "mouse", "taxonomic_group": "Rodent",
    "model_system": "...", "data_type": "...", "full_text_available": true
  },
  "claims": [
    {
      "claim": "一句话结论，主张句式，不是主题描述",
      "topic": ["xist_rna_function"],
      "evidence": "具体证据：Figure 2B 的 RNA-seq，n=3，p=0.01",
      "evidence_type": "direct_experimental",
      "section": "results",
      "paragraph": "从论文里逐字复制的原句，不是段号",
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

四条硬约束（违反其一，数据会静默劣化）：

1. **字段名不能自创。** JSON 的 `claims[]` 里有 **12 个字段**，对应 claims CSV
   的 13 列——第 13 列 `paper_id` 由文件名注入，不需要也不应该写在 JSON 里。
   写成 `quote_text` 会被丢弃，该 claim 的溯源降级。
2. **`paragraph` 必须是从全文逐字复制的原句。** 写成 `"Results section 2"`
   会让该 claim 无法在全文里定位（溯源 S 档）。**先读 `papers/text/{paper_id}.txt`，
   从里面复制原句。**
3. **`topic` 只能用代码里那 22 个值**（`vocab.py:STANDARD_TOPICS`）。
   **不要照抄 `templates/xist_paper.yaml:190`——模板只有 20 个，缺两个**：
   `polycomb` 和 `xist_expression_regulation`。后者尤其危险：模板里写成
   `xist_expression`，而那是另一个真实存在的 topic，照抄会静默归错类而不报错。

   完整 22 个：
   `xist_identification`, `xist_expression`, `xist_expression_regulation`,
   `xist_rna_function`, `xist_protein_interactions`, `xci`, `early_embryo`,
   `totipotency`, `dosage_compensation`, `gene_silencing`, `cancer_biology`,
   `chromatin`, `lncrna`, `nuclear_organization`, `phase_separation`, `m6a`,
   `xist_evolution`, `sex_chromosome_biology`, `methods`, `polycomb`, `ddx39`,
   `other`。

   `polycomb` 在库里 3,572 条，是第 9 大 topic；`xist_expression_regulation`
   3,526 条排第 10。写错不会报错，只会被归一化到 `other`——而 `other` 已经是
   35,108 条的最大类，混进去就再也分不出来了。
4. **查不到的写 `"not reported"`，绝不推测。** 这个库出过编造 Addgene 编号的事故。

可选段落（各自成表，空着不报错）：

| JSON 键 | 进哪张表 | 是否额外生成 claim |
|---|---|---|
| `xist_identification` | `species_xist` | 否 |
| `xist_expression_regulation.regulators[]` | `regulations` | **是**，自动生成 `"{name} {direction} XIST expression"` |
| `xist_protein_interactions.interactors[]` | `interactors` | **是**，自动生成 `"{protein} interacts with XIST ({function})"` |
| `x_chromosome_inactivation` | `xci_status` | 否 |

同一个发现有 `regulators`/`interactors` 就够了就别再在 `claims` 里手写一遍，否则检索里出现两条。

### 2.3 `papers/text/{paper_id}.txt` 全文

有 PDF 就放 `papers/pdf/{paper_id}.pdf`，然后：

```bash
cd "C:/00_Data/实验室/实验室/MetaAnalysis/XIST_Project_V2"
py scripts/run_pipeline.py --parse
```

`--parse` 只处理有 PDF 没 text 的，可重复跑。没有全文也能入库，只是溯源区间为空、全文检索搜不到。

## 第 3 步：本地抽派生层（**这一步最容易漏**）

平台读的是 `notes/claims/*_claims.csv`，**不是 JSON**。

```bash
cd "C:/00_Data/实验室/实验室/MetaAnalysis/XIST_Project_V2"
py scripts/run_pipeline.py --claims
py scripts/run_pipeline.py --evidence --kb --rebuild
```

三条陷阱：

- **`--claims` 幂等跳过已存在的 CSV。** 改了一篇已有论文的 JSON 后，必须先删旧 CSV，
  否则新内容不会生效，而且不报错：
  ```bash
  rm notes/claims/{paper_id}_claims.csv
  ```
- **`--evidence` 每次全量重写** `reviews/evidence_tables/*.csv`（`_save_csv` 用
  `open(..., "w")`），不需要手动删。
- **`--kb` 必须带 `--rebuild`。** 不带时走 `create_tables` 而非 `rebuild_schema`，
  然后无条件 `INSERT INTO claims`，同一批数据写两遍。**实测：115,674 → 231,348，
  正好翻倍。** 绝不并发跑两个 `--kb --rebuild`（同样是 DROP/INSERT 交错翻倍）。

验证（改完立刻查，别等部署时才发现）：

```bash
py -c "import sqlite3;c=sqlite3.connect('xist_knowledge.db');print('dup',c.execute('SELECT count(*)-count(DISTINCT id) FROM claims').fetchone()[0])"
grep -c "<paper_id>" notes/claims/<paper_id>_claims.csv
```

## 第 4 步：同步到服务器

只传变化的部分，不要整目录覆盖。`papers/text` 在服务器上是软链到 `data/v2/papers`，
所以传 `notes/` 和 `xist_knowledge.db` 就够（加上新论文的 text）。

```bash
# 单篇：只传三个文件
scp notes/json/<paper_id>.json luyx@162.105.248.197:/Data7/luyx/XIST-KB/data/v2src/notes/json/
scp notes/claims/<paper_id>_claims.csv luyx@162.105.248.197:/Data7/luyx/XIST-KB/data/v2src/notes/claims/
scp papers/text/<paper_id>.txt luyx@162.105.248.197:/Data7/luyx/XIST-KB/data/v2/papers/text/

# papers.csv 有新增行、或 SQLite 变了，才需要传这两个
scp metadata/papers.csv luyx@162.105.248.197:/Data7/luyx/XIST-KB/data/v2src/metadata/
scp xist_knowledge.db luyx@162.105.248.197:/Data7/luyx/XIST-KB/data/v2src/
```

`xist_knowledge.db` 是 217 MB。只有当你新增了 `regulators` / `interactors` /
`xist_identification` / `xci_status` 段落时才必须传；只加 claims 时不用。

## 第 5 步：服务器重建

```bash
ssh luyx@162.105.248.197
cd /Data7/luyx/XIST-KB/app
./deploy/serve.sh stop          # 必须：服务锁住 DuckDB，不停会替换失败
.venv/bin/xist migrate-v2 /Data7/luyx/XIST-KB/data/v2src
.venv/bin/python scripts/rebuild_derived.py
./deploy/serve.sh start
```

`rebuild_derived.py` 里的顺序不能手动拆开跑（scope / species_fill / regulators
必须早于索引构建）。

## 第 6 步：验收

```bash
cd /Data7/luyx/XIST-KB/app
.venv/bin/python -c "
import duckdb
c=duckdb.connect('/Data7/luyx/XIST-KB/data/index/xist.duckdb',read_only=True)
print('dup:',c.execute('SELECT count(*)-count(DISTINCT claim_id) FROM claims').fetchone()[0])
print('orphan:',c.execute('SELECT count(*) FROM claims WHERE paper_id NOT IN (SELECT paper_id FROM papers)').fetchone()[0])
print('new paper claims:',c.execute(\"SELECT count(*) FROM claims WHERE paper_id='<paper_id>'\").fetchone()[0])
print('total claims:',c.execute('SELECT count(*) FROM claims').fetchone()[0])
"
./deploy/serve.sh status
```

`dup` 和 `orphan` 都必须是 **0**。`new paper claims` 应该等于你写的 claims 条数
加上自动生成的 regulators/interactors 条数。

`total claims` 与原值比较：只加不减。比原值多出的条数应等于新论文的贡献。

**必须直接查这张 SQL，不要相信迁移日志里 `claims_without_paper` 那个字段——它恒为 0。**
`MigrationStats.claims_without_paper` 只声明从未赋值（`migrate_v2.py:245`），实测
`papers.csv` 用 `balaton2016_different`、三个文件用 `Balaton2016_escape` 时它报 0，
而实际孤儿是 1。孤儿是拼写不一致的唯一信号，漏看就会在检索里看到一条没有出处的 claim。

## 报告格式

做完后按这个结构报告，不要只写"已完成"：

- `paper_id`：实际用的值
- claims 条数：手写 N 条 + 自动生成 M 条
- 有引句的条数 / 无引句的条数
- 服务器的 `dup` / `orphan` / `total claims` / `new paper claims` 四个数字
- 服务状态
- 任何你**没做**或**不确定**的地方

## 绝对不要做

- 不要改 `gold/*.parquet` 或 `index/xist.duckdb`——生成物，每次重建被覆盖
- 不要手写 `claim_id`——它是内容哈希，手写的会让审阅标注错位
- 不要猜测论文里没有的内容（编造 accession、Figure 号、p 值）
- 服务器上不要用 root 或 sudo
- 不要在 `--kb --rebuild` 跑完前启动第二个写库进程
- 不要把 `private/` 下的未发表数据写进 claims 或上传
