# Review and Rewrite Pipeline Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将章节质量流程收敛为“一次硬门禁、最多一次定向改写、一次最终软审稿”，并用一个规范结果控制保存、改写和展示。

**Architecture:** 新建结构化 `ReviewFinding` 与 `ReviewResult` 作为运行时唯一事实源；硬性审查和软性审稿分开调度，自动改写只由阻断项触发。现有 `simplified_review`、旧 Agent 字段和历史报告继续通过兼容适配器读取，但不再参与新章节的流程裁决。

**Tech Stack:** Python 3、dataclasses、typing、pytest、现有 Story Core 模型与前端兼容 JSON

---

## Scope and non-negotiable behavior

- 新流程只有三个运行状态：`passed`、`warning`、`blocked`。
- 只有 `blocking=True` 的 finding 可以阻止候选稿确认或触发自动改写。
- 对话、文风、AI 味和阅读感受默认是软建议，不触发整章自动改写。
- 每次生成最多执行一次模型改写；改写后只重跑硬门禁，最终正文只跑一次软审稿。
- 篇幅不足、篇幅超硬上限、连续性冲突、设定或数值冲突、题材污染、人物状态冲突属于硬门禁。
- 原始检查器明细继续写入 `diagnostics`，便于排查，但业务代码不得读取其中的 `pass`、`scores` 或 Agent 字段进行裁决。
- 历史章节不迁移磁盘文件；读取时即时投影为新结果。
- 本计划不改页面布局、不增加 LLM 调用、不重构世界模拟和写作规划。

## Target file structure

```text
packages/story_core/review/
  contracts.py          # ReviewFinding、ReviewResult 及序列化
  legacy_adapter.py     # 旧报告 -> ReviewResult，仅用于历史数据
  service.py            # hard gate、soft review 和最终结果合并
  quality_gate.py       # 保留旧公开入口，委托给 ReviewService

packages/story_core/pipeline/
  review_revision_stage.py  # 新的单轮质量控制器
  quality_stage.py           # 兼容入口，迁移完成后只做薄委托
```

依赖方向必须保持为：检查器 → `ReviewFinding` → `ReviewService` → 流程控制器。`contracts.py` 和 `service.py` 不得导入 `orchestrator.py` 或 `file_project_store.py`。

---

### Task 1: 建立规范审稿契约

**Files:**
- Create: `packages/story_core/review/contracts.py`
- Modify: `packages/story_core/review/__init__.py`
- Create: `tests/story_core/test_review_contracts.py`

- [ ] **Step 1: 写序列化和状态规则的失败测试**

```python
from packages.story_core.review.contracts import ReviewFinding, ReviewResult


def test_review_result_is_blocked_only_by_blocking_findings():
    result = ReviewResult.from_findings(
        [
            ReviewFinding(
                code="continuity.timeline_conflict",
                category="hard",
                blocking=True,
                message="时间线与上一章冲突。",
                suggestion="把事件时间改回次日早晨。",
                source="continuity",
            ),
            ReviewFinding(
                code="style.ai_flavor",
                category="ai_flavor",
                blocking=False,
                message="存在报告腔。",
                suggestion="改成动作和现场结果。",
                source="ai_flavor",
            ),
        ]
    )

    assert result.status == "blocked"
    assert result.has_hard_errors is True
    assert result.needs_revision is True
    assert result.revision_plan == ["把事件时间改回次日早晨。"]
    assert result.to_dict()["issues"][0]["code"] == "continuity.timeline_conflict"


def test_review_result_uses_warning_for_advisory_findings():
    result = ReviewResult.from_findings(
        [
            ReviewFinding(
                code="dialogue.unnatural",
                category="dialogue",
                blocking=False,
                message="对白不够自然。",
                suggestion="只重写对应对话。",
                source="dialogue",
            )
        ]
    )

    assert result.status == "warning"
    assert result.has_hard_errors is False
    assert result.needs_revision is False
    assert result.revision_plan == []
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_review_contracts.py -q`

Expected: FAIL，提示 `packages.story_core.review.contracts` 不存在。

- [ ] **Step 3: 实现最小契约**

在 `contracts.py` 中实现：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ReviewCategory = Literal["hard", "dialogue", "ai_flavor", "prose"]
ReviewStatus = Literal["passed", "warning", "blocked"]


@dataclass(frozen=True)
class ReviewFinding:
    code: str
    category: ReviewCategory
    blocking: bool
    message: str
    suggestion: str
    source: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "severity": "blocking" if self.blocking else "advisory",
            "blocking": self.blocking,
            "message": self.message,
            "suggestion": self.suggestion,
            "source": self.source,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ReviewResult:
    status: ReviewStatus
    findings: tuple[ReviewFinding, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_findings(
        cls,
        findings: list[ReviewFinding],
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> "ReviewResult":
        deduplicated: dict[tuple[str, str], ReviewFinding] = {}
        for finding in findings:
            key = (finding.code, "".join(finding.message.split()).rstrip("。；;！!"))
            deduplicated.setdefault(key, finding)
        ordered = sorted(
            deduplicated.values(),
            key=lambda item: (not item.blocking, {"hard": 0, "dialogue": 1, "ai_flavor": 2, "prose": 3}[item.category]),
        )
        status: ReviewStatus = "blocked" if any(item.blocking for item in ordered) else ("warning" if ordered else "passed")
        return cls(status=status, findings=tuple(ordered), diagnostics=diagnostics or {})

    @property
    def has_hard_errors(self) -> bool:
        return any(item.blocking for item in self.findings)

    @property
    def needs_revision(self) -> bool:
        return self.has_hard_errors

    @property
    def revision_plan(self) -> list[str]:
        return [item.suggestion for item in self.findings if item.blocking and item.suggestion][:3]

    def to_dict(self, *, issue_limit: int = 3) -> dict[str, Any]:
        selected = self.findings[:issue_limit]
        counts = {category: 0 for category in ("hard", "dialogue", "ai_flavor", "prose")}
        for finding in self.findings:
            counts[finding.category] += 1
        return {
            "schema_version": "review-result/v2",
            "status": self.status,
            "pass": not self.has_hard_errors,
            "has_hard_errors": self.has_hard_errors,
            "needs_revision": self.needs_revision,
            "issues": [item.to_dict() for item in selected],
            "revision_plan": self.revision_plan,
            "total_issues": len(self.findings),
            "categories": {
                "hard": {"label": "硬伤", "count": counts["hard"]},
                "dialogue": {"label": "对话", "count": counts["dialogue"]},
                "ai_flavor": {"label": "AI味", "count": counts["ai_flavor"]},
                "prose": {"label": "正文", "count": counts["prose"]},
            },
            "diagnostics": self.diagnostics,
        }
```

从 `review/__init__.py` 导出 `ReviewFinding` 和 `ReviewResult`。

- [ ] **Step 4: 重跑测试**

Run: `python -m pytest tests/story_core/test_review_contracts.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add packages/story_core/review/contracts.py packages/story_core/review/__init__.py tests/story_core/test_review_contracts.py
git commit -m "refactor: add canonical chapter review contracts"
```

---

### Task 2: 把关键词分类限制在历史兼容边界

**Files:**
- Create: `packages/story_core/review/legacy_adapter.py`
- Modify: `packages/story_core/simplified_review.py`
- Modify: `tests/story_core/test_simplified_review.py`
- Modify: `tests/story_core/test_review_contracts.py`

- [ ] **Step 1: 写明确 finding 优先于中文关键词的失败测试**

```python
from packages.story_core.simplified_review import build_simplified_review


def test_explicit_finding_metadata_wins_over_message_keywords():
    report = build_simplified_review(
        {
            "review_result": {
                "schema_version": "review-result/v2",
                "status": "warning",
                "issues": [
                    {
                        "code": "prose.timeline_metaphor",
                        "category": "prose",
                        "blocking": False,
                        "message": "这句用了时间线作为比喻。",
                        "suggestion": "换成具体动作。",
                        "source": "prose",
                    }
                ],
            }
        }
    )

    assert report["status"] == "warning"
    assert report["has_hard_errors"] is False
    assert report["issues"][0]["category"] == "prose"
```

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `python -m pytest tests/story_core/test_simplified_review.py tests/story_core/test_review_contracts.py -q`

Expected: 新测试 FAIL，因为当前实现仍根据“时间线”关键词归为硬伤。

- [ ] **Step 3: 移动旧解析逻辑**

把当前 `simplified_review.py` 中的 `HARD_TOKENS`、`AI_FLAVOR_TOKENS`、`DIALOGUE_TOKENS`、嵌套遍历和关键词分类移动到 `review/legacy_adapter.py`，公开：

```python
def review_result_from_legacy_report(report: object) -> ReviewResult:
    """Convert persisted v1 reports only; new runtime code must not call this directly."""
```

旧适配器必须保留现有历史章节测试行为，包括嵌套 Agent 字段、问题去重、三项上限和硬伤关键词。

- [ ] **Step 4: 让 `build_simplified_review` 变成兼容投影**

```python
def build_simplified_review(quality_report: Any, *, limit: int = 3) -> dict[str, Any]:
    report = quality_report if isinstance(quality_report, dict) else {}
    explicit = report.get("review_result")
    if isinstance(explicit, dict) and explicit.get("schema_version") == "review-result/v2":
        return project_review_result_dict(explicit, issue_limit=limit)
    return review_result_from_legacy_report(report).to_dict(issue_limit=limit)
```

`project_review_result_dict` 只裁剪 `issues`，不得重新判断类别、阻断性或状态。

- [ ] **Step 5: 运行兼容测试**

Run: `python -m pytest tests/story_core/test_simplified_review.py tests/story_core/test_review_contracts.py -q`

Expected: PASS，旧报告仍兼容，新报告不再走关键词分类。

- [ ] **Step 6: 提交**

```bash
git add packages/story_core/review/legacy_adapter.py packages/story_core/simplified_review.py tests/story_core/test_simplified_review.py tests/story_core/test_review_contracts.py
git commit -m "refactor: isolate legacy review classification"
```

---

### Task 3: 建立硬门禁与软审稿服务

**Files:**
- Create: `packages/story_core/review/service.py`
- Modify: `packages/story_core/review/quality_gate.py`
- Create: `tests/story_core/test_review_service.py`
- Modify: `tests/story_core/test_review_quality_gate.py`

- [ ] **Step 1: 写调度边界的失败测试**

使用记录调用次数的假检查器，覆盖以下行为：

```python
def test_hard_gate_does_not_run_soft_reviewers(review_service):
    result = review_service.run_hard_gate(body="正文", context={})

    assert result.status in {"passed", "blocked"}
    assert review_service.calls == ["continuity", "fragments", "consistency", "critical", "genre"]


def test_soft_review_never_returns_blocking_findings(review_service):
    result = review_service.run_soft_review(body="正文", context={})

    assert review_service.calls == ["style", "prose_quality", "adversarial_cut", "ai_flavor", "reader_feel", "cold_reader", "plot_spine"]
    assert all(finding.blocking is False for finding in result.findings)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_review_service.py -q`

Expected: FAIL，提示 `ReviewService` 不存在。

- [ ] **Step 3: 实现 `ReviewService`**

`ReviewService` 提供三个方法：

```python
class ReviewService:
    def run_hard_gate(self, *, body: str, context: dict[str, Any]) -> ReviewResult: ...

    def run_soft_review(self, *, body: str, context: dict[str, Any]) -> ReviewResult: ...

    def combine(self, hard: ReviewResult, soft: ReviewResult) -> ReviewResult:
        return ReviewResult.from_findings(
            [*hard.findings, *soft.findings],
            diagnostics={**hard.diagnostics, **soft.diagnostics},
        )
```

硬门禁来源固定为：

- 篇幅检查；低于最小值或高于硬上限生成 `length.out_of_range`。
- `review_continuity`。
- `review_fragments`。
- `review_consistency`。
- `review_critical_rules`。
- 题材 profile 的确定性规则；只有检查器明确标记为 blocking 的结果才能阻断。

软审稿来源固定为：

- `review_style`。
- `review_prose_quality`。
- `review_adversarial_cuts`。
- `review_ai_flavor`。
- `review_reader_feel`。
- `review_cold_reader`。
- `review_plot_spine` 中未标记为 blocking 的项目。

检查器暂未返回结构化 findings 时，在 `service.py` 内按“检查器来源”适配，不得根据 `message` 内容猜类别。硬检查器的 issue 映射为 blocking；软检查器的 issue 映射为 advisory。题材检查器需要在其返回项上增加显式 `blocking`，不能整包默认为硬伤。

- [ ] **Step 4: 让旧质量入口委托给服务**

保留 `review_chapter_body(...) -> dict` 函数签名，内部改为：

```python
hard = service.run_hard_gate(body=body, context=context)
soft = service.run_soft_review(body=body, context=context)
combined = service.combine(hard, soft)
payload = combined.to_dict()
return {
    "pass": not hard.has_hard_errors,
    "issues": [item.message for item in combined.findings],
    "revision_plan": combined.revision_plan,
    "review_result": payload,
    "simplified_review": payload,
    "diagnostics": combined.diagnostics,
}
```

不得再创建 `reader_agent_review`、`editor_agent_review`、`reviewer_agent_review`。原底层报告放入 `diagnostics`，键名保持稳定。

- [ ] **Step 5: 更新旧断言并运行测试**

删除 `test_review_quality_gate.py` 中要求三个 Agent 包装字段存在的断言，改为断言：

```python
assert report["review_result"]["schema_version"] == "review-result/v2"
assert "reader_agent_review" not in report
assert "prose_style_review" in report["diagnostics"]
```

Run: `python -m pytest tests/story_core/test_review_service.py tests/story_core/test_review_quality_gate.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add packages/story_core/review/service.py packages/story_core/review/quality_gate.py tests/story_core/test_review_service.py tests/story_core/test_review_quality_gate.py
git commit -m "refactor: split hard gate from soft chapter review"
```

---

### Task 4: 用单轮控制器替换审稿—改稿—压缩循环

**Files:**
- Create: `packages/story_core/pipeline/review_revision_stage.py`
- Modify: `packages/story_core/pipeline/__init__.py`
- Create: `tests/story_core/test_review_revision_stage.py`

- [ ] **Step 1: 写调用次数和状态转换测试**

至少覆盖四条路径：

```python
def test_passed_draft_runs_one_hard_gate_and_one_soft_review(): ...

def test_blocked_draft_revises_once_then_rechecks_hard_gate(): ...

def test_failed_revision_is_not_retried(): ...

def test_soft_warning_never_triggers_revision(): ...
```

阻断后成功改写路径的精确调用顺序必须为：

```python
assert calls == ["hard", "revise", "hard", "soft"]
assert result.revision_rounds == 1
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_review_revision_stage.py -q`

Expected: FAIL，提示新流程模块不存在。

- [ ] **Step 3: 实现新控制器**

```python
@dataclass(frozen=True)
class ReviewRevisionCallbacks:
    hard_review: Callable[[str], ReviewResult]
    soft_review: Callable[[str], ReviewResult]
    revise: Callable[[str, ReviewResult], tuple[str, str]]
    postprocess: Callable[[str], str]
    choose_revision: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ReviewRevisionResult:
    body: str
    review_result: ReviewResult
    hard_result: ReviewResult
    soft_result: ReviewResult
    revision_rounds: int
    revision_safety_report: dict[str, Any] | None = None
```

算法固定为：

```text
hard = hard_review(body)
if hard.status == blocked:
    candidate = revise(body, hard)
    if candidate exists:
        candidate_hard = hard_review(candidate)
        body/hard = choose_revision(original, candidate)
soft = soft_review(final body)
combined = combine(hard, soft)
return
```

控制器内部不得包含 `while`。压缩不再拥有独立循环；篇幅问题由 `length.out_of_range` finding 进入同一次定向改写。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/story_core/test_review_revision_stage.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add packages/story_core/pipeline/review_revision_stage.py packages/story_core/pipeline/__init__.py tests/story_core/test_review_revision_stage.py
git commit -m "refactor: add bounded review revision controller"
```

---

### Task 5: 接入生成流程并删除旧控制分支

**Files:**
- Modify: `packages/story_core/orchestrator.py:313`
- Modify: `packages/story_core/orchestrator.py:3716`
- Modify: `packages/story_core/orchestrator.py:4484`
- Modify: `packages/story_core/pipeline/quality_stage.py`
- Modify: `tests/story_core/test_generation_quality_guardrails.py`
- Modify: `tests/story_core/test_orchestrator.py`
- Modify: `tests/story_core/test_quality_stage.py`

- [ ] **Step 1: 写生成流程只调用一次软审稿的失败测试**

在 orchestrator 测试中使用计数 fake，断言阻断并改写成功时：

```python
assert calls.count("hard_review") == 2
assert calls.count("soft_review") == 1
assert calls.count("revision_model") == 1
```

软建议路径断言 `revision_model` 为零次。

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `python -m pytest tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_orchestrator.py -q`

Expected: 新调用次数断言 FAIL。

- [ ] **Step 3: 替换 `run_quality_stage` 调用**

在 `_generate_next_chapter_bundle` 中构造 `ReviewRevisionCallbacks`，改为调用 `run_review_revision_stage`。最终 bundle 写入：

```python
quality_report["review_result"] = quality_result.review_result.to_dict()
quality_report["simplified_review"] = quality_report["review_result"]
quality_report["writing_review"] = {
    "pass": not quality_result.hard_result.has_hard_errors,
    "issues": [item.message for item in quality_result.review_result.findings],
    "revision_plan": quality_result.hard_result.revision_plan,
    "diagnostics": quality_result.review_result.diagnostics,
}
quality_report["ok"] = not quality_result.hard_result.has_hard_errors
```

- [ ] **Step 4: 删除运行时多状态判断**

删除或停止调用：

- `_should_run_full_revision`。
- 基于 `needs_revision` 阻止最终记忆提取的逻辑；改为读取 `status == "blocked"`。
- 生成流程中的独立 compression retry 分支。
- 从 `writing_review.pass`、`core_passed`、`soft_passed` 推导保存决策的代码。

`quality_stage.py` 暂时保留 `run_quality_stage` 导入兼容，但实现为对新控制器的薄适配；文件内不得再有改稿 `while` 或压缩重试。

- [ ] **Step 5: 更新并运行回归测试**

Run: `python -m pytest tests/story_core/test_quality_stage.py tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_orchestrator.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add packages/story_core/orchestrator.py packages/story_core/pipeline/quality_stage.py tests/story_core/test_quality_stage.py tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_orchestrator.py
git commit -m "refactor: use bounded review flow for chapter generation"
```

---

### Task 6: 简化改写提示词和安全选择

**Files:**
- Modify: `packages/story_core/genre_stages/common_revision.py`
- Modify: `packages/story_core/genre_stages/game_webnovel/revision.py`
- Modify: `packages/story_core/revision_safety.py`
- Modify: `tests/story_core/test_writer_prompt_method.py`
- Modify: `tests/story_core/test_revision_safety.py`

- [ ] **Step 1: 写改写输入边界测试**

断言自动改写提示词只包含：原文、最多三条阻断指令、用户指令、事实锁和篇幅要求。构造 diagnostics 中带有大量软审稿内容，并断言它们不出现在 prompt：

```python
assert "修复时间线" in prompt
assert "报告腔建议" not in prompt
assert "reader_agent_review" not in prompt
assert "scores" not in prompt
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_revision_safety.py -q`

Expected: 至少一个新增 prompt 边界断言 FAIL。

- [ ] **Step 3: 缩减 `render_common_revision_prompt`**

参数中的 `context.review` 只允许读取：

```python
review_result = context.review.get("review_result", context.review)
instructions = [
    str(item.get("suggestion") or "").strip()
    for item in review_result.get("issues", [])
    if isinstance(item, dict) and item.get("blocking")
][:3]
```

保留 `manual_instructions`、写作任务书、事实锁和字数上下限。删除对完整 review 字符串的扫描、Agent 子报告读取和软审稿建议拼装。题材特有禁写词必须来自结构化 finding 的 `evidence` 或明确字段，不得再 `json.dumps(review)` 后搜索。

- [ ] **Step 4: 把安全选择改成比较硬门禁**

`choose_best_revision` 的首要判定顺序固定为：

1. 候选正文非空且在硬篇幅范围内。
2. 候选 blocking finding 数少于原文。
3. 候选没有新增 blocking code。
4. 事实锁检查未出现回退。
5. blocking 数相同且原文仍有硬伤时保留原文。

软分数变化可以记录到报告，但不得否决已经修复硬伤的候选稿。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_revision_safety.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add packages/story_core/genre_stages/common_revision.py packages/story_core/genre_stages/game_webnovel/revision.py packages/story_core/revision_safety.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_revision_safety.py
git commit -m "refactor: restrict rewrite input to blocking findings"
```

---

### Task 7: 统一生成、重生成和手工改写的审稿入口

**Files:**
- Modify: `packages/story_core/file_project_store.py:533`
- Modify: `packages/story_core/file_project_store.py:604`
- Modify: `packages/story_core/file_project_store.py:6191`
- Modify: `packages/story_core/file_project_store.py:6669`
- Modify: `packages/story_core/file_project_store.py:7137`
- Modify: `packages/story_core/file_project_store.py:7267`
- Modify: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: 写三个入口结果一致性的失败测试**

用同一正文分别走生成结果持久化、重生成结果持久化和 `rewrite_chapter`，断言三者都包含：

```python
assert review["review_result"]["schema_version"] == "review-result/v2"
assert review["simplified_review"] == review["review_result"]
assert review["ok"] is (review["review_result"]["status"] != "blocked")
assert "reader_agent_review" not in review
assert "editor_agent_review" not in review
assert "reviewer_agent_review" not in review
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_file_project_store.py -q`

Expected: 新一致性测试 FAIL；当前手工改写仍单独运行三个 Agent 审稿器。

- [ ] **Step 3: 删除 `_manual_chapter_quality_report` 的独立审稿组合**

将其改为调用同一个 `ReviewService`：硬门禁一次、软审稿一次、合并一次。手工改写不自动调用模型改写，只把 `blocked` 结果返回给用户并按现有手工保存政策处理。

- [ ] **Step 4: 简化保存门禁**

`_assert_auto_chapter_quality` 只读取：

```python
review_result = quality_report.get("review_result") or build_simplified_review(quality_report)
if review_result.get("status") == "blocked":
    raise ChapterQualityError(...)
```

删除 `_regeneration_quality_blocking` 中对 `quality_report.ok`、`writing_review` 和 `_blocking_quality_issues` 的交叉判断。若重生成允许降级保存，降级标志只能改变抛错策略，不得改写审稿状态。

- [ ] **Step 5: 保持历史读取兼容**

`review()` 读取旧 JSON 时，如果没有 `review_result`，即时调用 `build_simplified_review` 并在返回对象中补上：

```python
payload["review_result"] = projected
payload["simplified_review"] = projected
```

只修改返回值，不回写历史文件。

- [ ] **Step 6: 运行测试**

Run: `python -m pytest tests/story_core/test_file_project_store.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add packages/story_core/file_project_store.py tests/story_core/test_file_project_store.py
git commit -m "refactor: unify file project review entrypoints"
```

---

### Task 8: 更新前端类型兼容并验证旧章节

**Files:**
- Modify: `apps/web/lib/api.ts:460`
- Modify: `apps/web/components/ws/SimplifiedReview.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: 更新类型测试夹具**

将状态类型收敛为：

```typescript
export type ReviewStatus = "passed" | "warning" | "blocked";

export type ReviewFinding = {
  code: string;
  category: "hard" | "dialogue" | "ai_flavor" | "prose";
  blocking: boolean;
  severity: "blocking" | "advisory";
  message: string;
  suggestion: string;
  source: string;
  evidence?: string;
};
```

保留 `simplified_review` 字段；新增可选 `review_result`。删除页面组件对 `needs_revision` 状态字符串的依赖。

- [ ] **Step 2: 写页面兼容测试**

覆盖：

- `warning` 显示“有修改建议”，不显示“未通过”。
- `blocked` 显示“存在硬伤”。
- 旧章节只有 `simplified_review` 时仍正常显示。
- 页面最多展示三项，不显示 diagnostics 和旧 Agent 卡片。

- [ ] **Step 3: 运行前端测试并确认失败**

Run: `npm --prefix apps/web run test:e2e -- tests/story-workbench.spec.ts`

Expected: 新 `warning` 状态断言 FAIL。

- [ ] **Step 4: 更新组件状态映射并重跑**

Run: `npm --prefix apps/web run test:e2e -- tests/story-workbench.spec.ts`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add apps/web/lib/api.ts apps/web/components/ws/SimplifiedReview.tsx apps/web/tests/story-workbench.spec.ts
git commit -m "refactor: align review UI with canonical statuses"
```

---

### Task 9: 删除死代码并执行完整验收

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/review/quality_gate.py`
- Modify: `packages/story_core/pipeline/quality_stage.py`
- Modify: tests affected by removed compatibility helpers

- [ ] **Step 1: 搜索残留控制逻辑**

Run:

```powershell
rg -n "core_passed|soft_passed|needs_revision.*should|reader_agent_review|editor_agent_review|reviewer_agent_review|compression_retry|while .*revision" packages/story_core apps/web
```

Expected: 只允许以下残留：历史适配器、历史数据类型、测试旧章节兼容的夹具。运行时生成与保存代码不得命中。

- [ ] **Step 2: 删除无调用帮助函数和导入**

使用 `rg` 确认每个候选函数没有调用者后再删除。不要删除独立底层检查器；只删除重复聚合、虚拟 Agent 包装、多状态裁决和旧循环控制代码。

- [ ] **Step 3: 运行后端聚焦测试**

Run:

```powershell
python -m pytest tests/story_core/test_review_contracts.py tests/story_core/test_simplified_review.py tests/story_core/test_review_service.py tests/story_core/test_review_quality_gate.py tests/story_core/test_review_revision_stage.py tests/story_core/test_quality_stage.py tests/story_core/test_revision_safety.py tests/story_core/test_orchestrator.py tests/story_core/test_file_project_store.py -q
```

Expected: PASS。

- [ ] **Step 4: 运行 Story Core 全量测试**

Run: `python -m pytest tests/story_core -q`

Expected: PASS，无 warning 被误当成失败。

- [ ] **Step 5: 运行 API/CLI 相关回归**

Run:

```powershell
python -m pytest tests/test_novel_agent_cli.py tests/test_novel_autogrowth_mcp.py -q
```

Expected: PASS；旧接口仍能取得 `simplified_review`，新接口同时取得 `review_result`。

- [ ] **Step 6: 运行前端回归**

运行 TypeScript 编译检查和已有的目标 Playwright 测试：

```powershell
npm --prefix apps/web exec -- tsc --noEmit
npm --prefix apps/web run test:e2e -- tests/story-workbench.spec.ts
```

Expected: PASS。

- [ ] **Step 7: 做两类题材验收**

各选择一个修仙和网游测试 fixture，断言：

- 修仙正文不会收到网游数值、交易行或新手村建议。
- 网游连续性和数值冲突仍为 blocking。
- 两类正文的普通文风问题都是 warning。
- 任一生成流程的模型改写调用次数不超过一次。
- 任一最终正文的软审稿调用次数恰好一次。

- [ ] **Step 8: 提交清理与验收结果**

```bash
git add packages/story_core apps/web tests
git commit -m "refactor: complete review rewrite pipeline simplification"
```

---

## Acceptance criteria

执行 AI 在声明完成前必须提供以下证据：

1. `ReviewResult` 是生成、重生成、手工改写和保存门禁共同读取的唯一裁决对象。
2. 新章节报告不再生成 reader/editor/reviewer 三个包装 Agent 字段。
3. 新运行时问题类别不依赖中文关键词匹配；关键词匹配只存在于历史适配器。
4. 无硬伤正文：硬门禁一次、软审稿一次、模型改写零次。
5. 有硬伤且改写成功：硬门禁两次、软审稿一次、模型改写一次。
6. 软建议不会触发自动改写，也不会阻止候选稿保存或确认。
7. 改写提示词最多包含三条阻断修改指令，不携带完整 diagnostics。
8. 旧章节无需迁移即可继续显示综合审稿。
9. Story Core、CLI/MCP 和相关前端测试全部通过。

## Rollback boundary

每个任务单独提交。若新流程出现题材误判，优先回退 Task 5 的 orchestrator 接入提交，保留 Task 1–3 的契约、历史适配器和服务测试；不要通过恢复多套状态判断来临时修补。
