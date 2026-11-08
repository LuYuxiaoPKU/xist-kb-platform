# 溯源上下文：引文区间与「查看该节全文」

> 实现于 2026-11-08。对应 v6 计划 §2.4 与 §9.2 的决策。

## 决策

用户在第五轮审视后决定：**S 档提供「查看该节全文」按钮。**

本文件记录该决策的实现、实测数字，以及为什么它是这个项目里唯一诚实的做法。

## 两条路径

一条 claim 的上下文只有两种形态，没有第三种：

| 形态 | 触发条件 | 返回 |
|---|---|---|
| 引文区间 | 注释的 quote 能在原文中找到 | 每个精确出现位置的 `start`/`end` 与原文切片 |
| 节正文 | 找不到 quote，且注释标了 section 且原文有该标题 | 该节全文＋字符数＋占全文比例 |
| 无 | 以上都不成立 | 明确的原因字符串 |

**刻意不提供「近似段落」。** 第五轮审视实测：仅凭 claim 文本定位到 626 字符窗口的准确率是 11.6%（随机 1.3%，永远猜最常见的窗口 4.4%）。做成按钮就是给用户一个 11.6% 准确率的功能配绿色徽标。

## 实测数字（全量，非抽样）

### 引文区间：99.94% → 100%

| 项 | 数字 |
|---|---|
| 有 quote 的非规则 claims | 81,941 |
| 能在原文定位 | 30,817 |
| 切片与 quote 逐字一致 | 30,817（**100%**） |

最初测得 30,799/30,817，19 条切片错位。原因：`str.lower()` 对少数 Unicode 字符（`İ`、`ẞ`）产生两个字符，导致归一化文本与偏移表长度不一致，其后所有偏移整体漂移。修法是对每个展开后的字符重复记录同一个原索引。已在 `tests/test_context.py::test_lowercase_expanding_character_keeps_offsets_aligned` 固化。

### 节正文：S 档 56.6% 可渲染

| 档 | 条数 | 说明 |
|---|---|---|
| P1/P2/P3 | 34,345 | 引文可定位（与 v6 一致） |
| S 可渲染 | 35,626 | **有该节标题，按钮可点** |
| S 无标题 | 27,348 | 注释说在 Results，原文无该标题 |
| C | 10,244 | 无 section 或无全文 |

S 档共 62,974 条，**56.6% 能渲染该节全文**。

### 渲染体积：中位 18,218 字符

这是决定 UI 形态的关键数字——不是「占全文 30%」这种比例，而是用户点开之后实际看到多少字。

| 分位 | 字符数 |
|---|---|
| 中位 | 18,218 |
| p75 | 24,505 |
| p90 | 34,260 |
| p95 | 42,988 |
| 最大 | 238,337 |

| 节 | 中位 | p90 |
|---|---|---|
| results | 18,373 | 29,632 |
| introduction | 28,392 | 58,518 |
| discussion | 12,534 | 21,893 |
| methods | 13,444 | 29,272 |
| conclusion | 6,107 | 12,824 |
| abstract | 1,533 | 16,470 |

**84.7% 的 S 档 claim 所属节超过 10,000 字符。** 这不是「一段话」，是一整节。

因此 API 设 `MAX_SECTION_CHARS = 60,000`（覆盖 p95 以上），超出视为切分失败而非正常节，返回 `truncated: true`。

## 切分器的两个真实缺陷

### 中途参考文献（284 篇）

PDF 提取有时把 "References" 印在文档前 40%（running header，或参考文献真的排在正文前）。当作边界会让前一个标题吞掉整个前置部分——实测某篇的 Abstract 算出 23,158 字符。

**修法**：`BACK_MATTER = {references, acknowledgements, supplementary}` 只在文档后半段才算边界。

### 重复标题（3,947 篇）

`Introduction` 重复 1,144 篇、`Results` 1,104 篇。原因多为 PDF 页眉把节名重复印刷，以及综述的分节结构。**保留为独立 section**，`get_section_text` 拼接同名节，不丢弃。

### 节跨度分布（加守卫后）

| 节 | 中位 | p90 |
|---|---|---|
| abstract | 2.5% | 13.2% |
| introduction | 8.3% | 69.1% |
| methods | 16.2% | 32.7% |
| discussion | 25.6% | 41.1% |
| results | 30.2% | 48.1% |

introduction 的 p90 高达 69%，说明 10% 的论文里 "Introduction" 后面直到参考文献都没有其他标题——这类节渲染出来就是整篇论文。p90 与中位的巨大差距是「按钮有时会打开一整篇论文」的直接证据。

## 模块

| 文件 | 职责 |
|---|---|
| `src/xist_kb/extract/sections.py` | 按整行标题切分，返回带字符偏移的 `Section` |
| `src/xist_kb/extract/context.py` | `find_quote_spans` / `build_context` / `TextStore` |
| `src/xist_kb/models_context.py` | API 契约：`ClaimContext` / `QuoteSpan` / `SectionBody` |

`TextStore` 按小写 stem 建索引。服务器文件系统大小写敏感，761 个 text 文件名与 `paper_id` 大小写不一致，不用小写索引这些论文在服务器上会全部读不到——而在 Windows 上测试完全正常。

## CLI

```bash
# 引文档
py -m xist_kb.cli context <claim_id>

# 节正文档，打印全文
py -m xist_kb.cli context <claim_id> --section
```

支持 claim_id 前缀匹配（唯一时）；多个匹配会列出并退出码 1。

## 服务器路径

`XIST_KB_TEXT_DIR` 环境变量。默认 `<data>/v2/papers/text`，服务器实际位置 `/Data7/luyx/XIST-KB/v2/papers/text`（681 MB，就地读取，不复制进数据树）。

## 未做

- **不做「跳到原文」**：跳过去也是滚 30%，且没有 PDF 阅读器的字节级定位。
- **不做 PDF 呈现**：文本层已足够，PDF 需要额外渲染栈。
- **不做上下文窗口**：S 档不做「该节里引文附近 500 字」，因为没有可靠位置。

## 测试

| 文件 | 条数 |
|---|---|
| `tests/test_sections.py` | 17 |
| `tests/test_context.py` | 21 |
| `tests/test_cli_context.py` | 8 |

全套 133 条通过；ruff 与 mypy 干净。
