# Recent Three-Year Corpus Slimming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为MiroFish项目生成可审计、不可破坏原文的最近3年派生语料，并允许建图接口显式选择该语料。

**Architecture:** 新增纯Python `CorpusSlimmer`解析现有header文档边界、确定性识别文件名日期并应用类别排除规则。派生文本和manifest通过临时文件原子写入项目目录；项目模型只记录当前语料选择和manifest摘要，建图接口显式读取`full`或`recent_3y`。

**Tech Stack:** Python 3.11、Flask、dataclasses、pytest、JSON

**Spec:** `docs/superpowers/specs/2026-08-27-recent-corpus-slimming-design.md`

## Global Constraints

- 基准窗口为运行日向前3年，截止日当天纳入。
- 原始上传文件和`extracted_text.txt`不得修改。
- 无日期、模糊2023年份、索引/矩阵、历史基线和完整年度/中期报告默认排除。
- 业绩公告、业务更新和业绩会纪要不得因名称包含“年度”而误排除。
- 派生结果为空时不得覆盖已有派生文件。
- 未经用户明确授权不提交或推送Git。

---

### Task 1: 文档边界、日期与选择规则

**Files:**
- Create: `backend/app/services/corpus_slimmer.py`
- Create: `backend/tests/test_corpus_slimmer.py`

**Interfaces:**
- Produces: `parse_document_sections(text: str) -> list[DocumentSection]`
- Produces: `detect_document_date(name: str, cutoff: date) -> DateDecision`
- Produces: `build_recent_corpus(text: str, *, cutoff: date, exclude_full_reports: bool) -> CorpusBuildResult`

- [ ] **Step 1: 写文档边界失败测试**

```python
def test_parse_document_sections_preserves_order_and_content():
    text = "=== a.txt ===\nA\n\n=== b.md ===\nB\n"
    sections = parse_document_sections(text)
    assert [(s.name, s.content) for s in sections] == [
        ("a.txt", "A\n\n"),
        ("b.md", "B\n"),
    ]
```

覆盖无header、重复header和空文档段。

- [ ] **Step 2: 写日期识别失败测试**

覆盖：

- `2023-08-27`纳入、`2023-08-26`排除。
- `2024-08`按月末。
- 唯一年份2024纳入。
- 只有2023标记`ambiguous_date`。
- 多个完整日期取最晚并标记`latest_date_fallback`。
- 无日期标记`undated`。

- [ ] **Step 3: 写类别规则失败测试**

断言：

- `2025年年度报告`和`2025年中期报告`排除。
- `2025年度业绩公告`、`2025年度业绩会`保留。
- `00_索引`、`覆盖矩阵`、`元数据库`、`07_历史基线`排除。
- 普通券商研报和团队访谈保留。

- [ ] **Step 4: 实现不可变数据结构和解析**

使用frozen dataclass：

```python
@dataclass(frozen=True)
class DocumentSection:
    name: str
    content: str

@dataclass(frozen=True)
class DateDecision:
    detected_date: date | None
    source: str
    reason: str | None
```

日期仅从文件名确定性解析，不读取正文猜测。

- [ ] **Step 5: 实现语料选择与manifest内存结果**

`CorpusBuildResult`包含`text`、`documents`、summary。派生文本继续使用：

```text
=== 文件名 ===
正文
```

每条manifest记录名称、日期、来源、纳入状态、原因和字符数。

- [ ] **Step 6: 运行单元测试**

Run: `python3 -m pytest backend/tests/test_corpus_slimmer.py -v`

Expected: 全部通过，且原始输入字符串保持不变。

### Task 2: 原子持久化与项目模型

**Files:**
- Modify: `backend/app/services/corpus_slimmer.py`
- Modify: `backend/app/models/project.py`
- Create: `backend/tests/test_corpus_persistence.py`

**Interfaces:**
- Produces: `write_recent_corpus(project_dir: Path, result: CorpusBuildResult) -> CorpusArtifacts`
- Produces: `ProjectManager.get_corpus_text(project_id: str, corpus: str) -> str | None`
- Adds: `Project.active_corpus: str = "full"`
- Adds: `Project.corpus_manifest: dict | None = None`

- [ ] **Step 1: 写原子写入失败测试**

在临时项目目录生成原文、派生文本和manifest。断言输出文件完整、临时文件消失、manifest计数与文本一致。

正式文件名固定为`extracted_text_recent_3y.txt`和`corpus_recent_3y_manifest.json`。

- [ ] **Step 2: 写空结果保护测试**

已有派生文件存在时，空`CorpusBuildResult`必须抛`ValueError`且旧文件哈希不变。

- [ ] **Step 3: 写项目模型兼容测试**

旧project.json没有新字段时，`from_dict`默认`active_corpus="full"`；新字段能to_dict/from_dict往返。

- [ ] **Step 4: 实现原子写入**

同目录创建唯一临时文件，写入、flush、`os.fsync`后使用`os.replace`。先完成两个临时文件，再替换正式文件；任一步失败时清理临时文件。

- [ ] **Step 5: 实现语料读取**

允许值严格限定：

- `full` -> `extracted_text.txt`
- `recent_3y` -> `extracted_text_recent_3y.txt`

未知值抛`ValueError`，缺失文件返回`None`。

- [ ] **Step 6: 运行持久化测试**

Run: `python3 -m pytest backend/tests/test_corpus_persistence.py -v`

### Task 3: 生成API与建图语料选择

**Files:**
- Modify: `backend/app/api/graph.py`
- Create: `backend/tests/test_corpus_api.py`

**Interfaces:**
- Produces: `POST /api/graph/project/<project_id>/corpus/recent`
- Extends: `POST /api/graph/build` with `corpus: "full" | "recent_3y"`

- [ ] **Step 1: 写生成API失败测试**

使用临时项目根和Flask test client，断言：

- 项目不存在404。
- `years<=0`返回400。
- 成功返回cutoff、included/excluded和字符数，不返回完整语料。
- 重复生成确定性一致。

- [ ] **Step 2: 写建图语料选择失败测试**

mock `GraphBuilderService`和后台线程，断言`corpus=recent_3y`读取派生文件；派生文件不存在返回400；未知corpus返回400；默认仍读取full。

- [ ] **Step 3: 实现生成API**

读取原文，计算`date.today() - relativedelta`不得引入新依赖；使用安全的年份回退：

```python
try:
    cutoff = today.replace(year=today.year - years)
except ValueError:
    cutoff = today.replace(month=2, day=28, year=today.year - years)
```

写入派生文件后更新`active_corpus`和manifest摘要并保存项目。

- [ ] **Step 4: 修改建图接口**

请求读取`corpus = data.get("corpus", project.active_corpus or "full")`，调用`ProjectManager.get_corpus_text`。任务结果加入`corpus`和实际字符数。

- [ ] **Step 5: 运行API测试和后端全量测试**

Run: `python3 -m pytest backend/tests -v`

### Task 4: 服务器生成与审计验收

**Files:**
- No additional repository files.
- Server outputs under project directory only.

**Interfaces:**
- Consumes project `proj_ebb7ae725574` original text.
- Produces derived corpus and manifest; does not start graph build.

- [ ] **Step 1: 提交前敏感信息与格式检查**

Run: `git diff --check`

扫描不得包含服务器IP、Token或Key。

- [ ] **Step 2: 构建并运行后端测试镜像**

同步代码但排除`.env`，构建backend，在容器内运行后端测试。测试失败不得重建生产backend。

- [ ] **Step 3: 部署backend**

测试通过后重建backend，确认Gateway、backend、Neo4j和Embedding健康。

- [ ] **Step 4: 调用派生语料API**

请求`years=3`、`exclude_full_reports=true`。保存返回摘要，不输出完整语料。

- [ ] **Step 5: 验证原文不变**

生成前后计算原`extracted_text.txt` SHA-256，必须一致。

- [ ] **Step 6: 验证manifest和规模**

检查：

- total=105。
- included约57。
- output约97.6万字符。
- 无完整年度/中期报告和索引文件。
- 分块约126。
- 每个排除项有原因。

- [ ] **Step 7: 停止，不启动建图**

报告派生语料路径、摘要和审计结果。Direct OAuth Provider未验收前，不调用`/api/graph/build`。
