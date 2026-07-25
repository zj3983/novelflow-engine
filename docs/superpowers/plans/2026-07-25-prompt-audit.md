# Prompt Audit Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a transparent prompt diagnosis tool that checks editable templates and recorded model calls for concrete length, duplication, variable, and conflict problems, with an optional user-triggered AI semantic pass.

**Architecture:** Keep deterministic analysis in a pure `story_core` module that receives only prompt text and declared template metadata. Expose it through a dedicated FastAPI router, and isolate the optional model call in a second provider that reuses the configured `planner` runtime without joining the chapter pipeline. The web app shares one result component between template editing and recorded calls; neither path rewrites, saves, or mutates prompt content.

**Tech Stack:** Python 3.11, Pydantic 2, FastAPI, pytest, TypeScript 5, React 18, Next.js 14, Playwright.

---

## File Map

- Create `packages/story_core/prompt_audit.py`: request-independent models and deterministic analysis.
- Modify `packages/story_core/prompt_templates.py`: expose occurrence-preserving variable parsing from the existing placeholder grammar.
- Create `packages/story_core/prompt_audit_deep.py`: optional semantic analyzer and configured runtime call.
- Create `apps/api/routes/prompt_audit.py`: request validation, HTTP error mapping, and two endpoints.
- Modify `apps/api/main.py`: register the new router.
- Create `tests/story_core/test_prompt_audit.py`: deterministic analyzer unit coverage.
- Modify `tests/story_core/test_prompt_templates.py`: protect the shared occurrence parser contract.
- Create `tests/story_core/test_prompt_audit_deep.py`: model-call contract and runtime metadata coverage.
- Create `tests/api/test_prompt_audit_routes.py`: endpoint limits, error codes, and local/deep isolation.
- Modify `apps/web/lib/api.ts`: shared prompt-audit types and request functions.
- Create `apps/web/components/prompts/PromptAuditPanel.tsx`: compact, reusable result rendering.
- Modify `apps/web/components/prompts/PromptTemplatesView.tsx`: inspect current unsaved template text and track stale results.
- Modify `apps/web/components/prompts/PromptCallsView.tsx`: inspect the selected recorded `user_prompt`.
- Modify `apps/web/app/globals.css`: responsive audit result layout using existing workbench tokens.
- Create `apps/web/tests/prompt-audit.spec.ts`: end-to-end behavior for both entry points.

### Task 1: Define the deterministic audit contract and template validation

**Files:**
- Create: `packages/story_core/prompt_audit.py`
- Modify: `packages/story_core/prompt_templates.py`
- Create: `tests/story_core/test_prompt_audit.py`
- Modify: `tests/story_core/test_prompt_templates.py`

- [ ] **Step 1: Write failing tests for empty input, template variables, and stable output**

```python
from __future__ import annotations

import pytest

from packages.story_core.prompt_audit import audit_prompt


def test_template_audit_reports_missing_unknown_and_repeated_variables() -> None:
    result = audit_prompt(
        mode="template",
        content="{{output_section}}\n{{output_section}}\n{{unexpected}}",
        template_key="writer",
        required_variables=["output_section", "chapter_direction"],
    )

    assert result.schema_version == "prompt-audit/v1"
    assert [issue.code for issue in result.must_fix] == [
        "missing_required_variable",
        "unknown_template_variable",
    ]
    assert any(issue.code == "repeated_template_variable" for issue in result.suggestions)
    assert result.summary.characters == len("{{output_section}}\n{{output_section}}\n{{unexpected}}")


def test_same_input_produces_the_same_result() -> None:
    arguments = {
        "mode": "final_call",
        "content": "只输出正文。\n只输出正文。",
    }
    assert audit_prompt(**arguments).model_dump() == audit_prompt(**arguments).model_dump()


def test_oversized_prompt_is_a_suggestion_below_the_hard_limit() -> None:
    result = audit_prompt(mode="final_call", content="一条具体写作要求。\n" * 5_000)

    assert any(issue.code == "oversized_prompt" for issue in result.suggestions)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"mode": "final_call", "content": "   "}, "content_required"),
        ({"mode": "wrong", "content": "正文"}, "invalid_prompt_audit_mode"),
        ({"mode": "final_call", "content": "字" * 200_001}, "prompt_audit_content_too_long"),
    ],
)
def test_local_audit_rejects_invalid_input(arguments: dict, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        audit_prompt(**arguments)
```

- [ ] **Step 2: Run the focused test and confirm the module is missing**

Run: `python -m pytest tests/story_core/test_prompt_audit.py -v`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'packages.story_core.prompt_audit'`.

- [ ] **Step 3: Expose occurrence-preserving parsing from the existing template grammar**

Add this function beside `template_variables()` in `packages/story_core/prompt_templates.py`:

```python
def template_variable_occurrences(content: str) -> tuple[str, ...]:
    return tuple(_VARIABLE_PATTERN.findall(content))


def template_variables(content: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(template_variable_occurrences(content)))
```

Add this regression test to `tests/story_core/test_prompt_templates.py`:

```python
def test_template_variable_occurrences_preserve_repeated_placeholders() -> None:
    assert template_variable_occurrences("{{chapter}} {{chapter}} {{output}}") == (
        "chapter",
        "chapter",
        "output",
    )
```

Update the test module import to include `template_variable_occurrences`, then run:

Run: `python -m pytest tests/story_core/test_prompt_templates.py -v`

Expected: PASS.

- [ ] **Step 4: Add the result models, validation, variable checks, whole-prompt length warning, and stable sorting**

Implement these public types and function in `packages/story_core/prompt_audit.py`:

```python
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.prompt_templates import template_variable_occurrences, template_variables

PromptAuditMode = Literal["template", "final_call"]
LOCAL_CONTENT_LIMIT = 200_000
LONG_PROMPT_WARNING = 40_000


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PromptAuditSection(_StrictModel):
    title: str
    characters: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)


class PromptAuditSummary(_StrictModel):
    characters: int = Field(ge=0)
    lines: int = Field(ge=0)
    estimated_redundant_characters: int = Field(ge=0)
    estimated_reduction_percent: float = Field(ge=0, le=100)
    sections: list[PromptAuditSection] = Field(default_factory=list)


class PromptAuditIssue(_StrictModel):
    code: str
    title: str
    evidence: str
    location: str
    suggestion: str
    estimated_reduction_characters: int = Field(default=0, ge=0)


class PromptAuditResult(_StrictModel):
    schema_version: Literal["prompt-audit/v1"] = "prompt-audit/v1"
    mode: PromptAuditMode
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: PromptAuditSummary
    must_fix: list[PromptAuditIssue] = Field(default_factory=list)
    suggestions: list[PromptAuditIssue] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)


def _issue_sort_key(issue: PromptAuditIssue) -> tuple[int, str, str]:
    return (-issue.estimated_reduction_characters, issue.code, issue.location)


def audit_prompt(
    *,
    mode: str,
    content: str,
    template_key: str = "",
    required_variables: list[str] | tuple[str, ...] = (),
) -> PromptAuditResult:
    if mode not in {"template", "final_call"}:
        raise ValueError("invalid_prompt_audit_mode")
    if not content.strip():
        raise ValueError("content_required")
    if len(content) > LOCAL_CONTENT_LIMIT:
        raise ValueError("prompt_audit_content_too_long")

    must_fix: list[PromptAuditIssue] = []
    suggestions: list[PromptAuditIssue] = []
    passed: list[str] = []
    if mode == "template":
        variables = template_variables(content)
        variable_counts = Counter(template_variable_occurrences(content))
        required = set(required_variables)
        present = set(variables)
        for name in sorted(required - present):
            must_fix.append(variable_issue("missing_required_variable", name, template_key))
        for name in sorted(present - required):
            must_fix.append(variable_issue("unknown_template_variable", name, template_key))
        for name in sorted(key for key, count in variable_counts.items() if count > 1):
            suggestions.append(repeated_variable_issue(name, variable_counts[name]))
        if not must_fix:
            passed.append("模板变量完整且没有未知变量")

    if len(content) > LONG_PROMPT_WARNING:
        suggestions.append(
            PromptAuditIssue(
                code="oversized_prompt",
                title="整段提示词较长",
                evidence=f"当前共 {len(content)} 个字符",
                location="完整提示词",
                suggestion="先查看区块占比和重复项，再决定是否精简。",
                estimated_reduction_characters=0,
            )
        )

    summary = PromptAuditSummary(
        characters=len(content),
        lines=len([line for line in content.splitlines() if line.strip()]),
        estimated_redundant_characters=0,
        estimated_reduction_percent=0,
        sections=[],
    )
    return PromptAuditResult(
        mode=mode,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
        summary=summary,
        must_fix=sorted(must_fix, key=_issue_sort_key),
        suggestions=sorted(suggestions, key=_issue_sort_key),
        passed_checks=passed,
    )
```

Add private helpers `variable_issue` and `repeated_variable_issue` in the same file. Evidence must be `{{name}}`, locations must name the template key when supplied, and repeated variables are suggestions because repetition can be intentional. Do not introduce another placeholder regex in the audit module.

- [ ] **Step 5: Run the focused tests and confirm they pass**

Run: `python -m pytest tests/story_core/test_prompt_audit.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the contract and template checks**

```bash
git add packages/story_core/prompt_templates.py packages/story_core/prompt_audit.py tests/story_core/test_prompt_templates.py tests/story_core/test_prompt_audit.py
git commit -m "feat: add deterministic prompt audit contract"
```

### Task 2: Add duplicate, section, and explicit-conflict checks

**Files:**
- Modify: `packages/story_core/prompt_audit.py`
- Modify: `tests/story_core/test_prompt_audit.py`

- [ ] **Step 1: Add failing tests for line normalization, Markdown sections, and conflicts**

```python
def test_final_call_finds_normalized_duplicate_lines_without_fuzzy_matching() -> None:
    result = audit_prompt(
        mode="final_call",
        content=(
            "# 输出要求\n"
            "1. 对话必须符合人物关系。\n"
            "2. 对话必须符合人物关系。\n"
            "# 正文资料\n"
            "对话要符合当前场面的关系。"
        ),
    )

    duplicates = [issue for issue in result.suggestions if issue.code == "duplicate_line"]
    assert len(duplicates) == 1
    assert duplicates[0].location == "第3行"
    assert result.summary.sections[0].title == "输出要求"
    assert result.summary.sections[1].title == "正文资料"
    assert result.summary.estimated_redundant_characters > 0


def test_final_call_reports_only_clear_instruction_conflicts() -> None:
    result = audit_prompt(
        mode="final_call",
        content=(
            "只输出小说正文，不要解释。\n"
            "最后输出分析报告。\n"
            "全文使用第一人称。\n"
            "全文使用第三人称。\n"
            "目标字数：2000-2500字。\n"
            "目标字数：3500-4000字。"
        ),
    )

    assert {issue.code for issue in result.must_fix} == {
        "conflicting_output_format",
        "conflicting_viewpoint",
        "conflicting_word_count",
    }


def test_long_section_is_a_suggestion_not_an_error() -> None:
    result = audit_prompt(
        mode="final_call",
        content="# 写作要求\n" + "必须遵守这条具体要求。\n" * 900 + "# 输出\n只输出正文。",
    )

    assert any(issue.code == "oversized_section" for issue in result.suggestions)
    assert all(issue.code != "oversized_section" for issue in result.must_fix)
```

- [ ] **Step 2: Run the new cases and confirm they fail**

Run: `python -m pytest tests/story_core/test_prompt_audit.py -v`

Expected: FAIL because duplicate, section, and conflict checks are not implemented.

- [ ] **Step 3: Implement conservative deterministic analysis**

Add these constants and helpers to `packages/story_core/prompt_audit.py`:

```python
import re

_LIST_PREFIX = re.compile(r"^\s*(?:[-*+]|\d+[.)、]|[一二三四五六七八九十]+[、.])\s*")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_WORD_RANGE = re.compile(r"(\d{2,6})\s*(?:-|—|~|到|至)\s*(\d{2,6})\s*字")
_MIN_DUPLICATE_CHARACTERS = 12
_OVERSIZED_SECTION_CHARACTERS = 12_000
_OVERSIZED_SECTION_SHARE = 45


def normalize_audit_line(line: str) -> str:
    without_prefix = _LIST_PREFIX.sub("", line.strip())
    return re.sub(r"\s+", " ", without_prefix)


def markdown_sections(content: str) -> list[PromptAuditSection]:
    buckets: list[tuple[str, list[str]]] = [("开头", [])]
    for line in content.splitlines():
        heading = _HEADING.match(line)
        if heading:
            buckets.append((heading.group(1).strip(), []))
        else:
            buckets[-1][1].append(line)
    total = max(len(content), 1)
    return [
        PromptAuditSection(
            title=title,
            characters=len("\n".join(lines)),
            percent=round(len("\n".join(lines)) * 100 / total, 1),
        )
        for title, lines in buckets
        if lines or title != "开头"
    ]
```

Implement `duplicate_line_issues(content)`, `oversized_section_issues(sections)`, and `explicit_conflict_issues(content)`. Duplicate detection must compare only `normalize_audit_line()` equality, ignore normalized lines shorter than 12 characters, retain the first occurrence, and report each later line once. Conflict checks must be limited to:

```python
conflict pairs = {
    "conflicting_output_format": ("只输出正文/小说正文", "输出分析/报告/解释"),
    "conflicting_viewpoint": ("第一人称", "第三人称"),
}
```

For word counts, parse all numeric ranges, normalize reversed bounds, and report `conflicting_word_count` only when at least two ranges do not overlap. Do not add embeddings, tokenization, fuzzy matching, or Chinese semantic heuristics.

Wire the helpers into `audit_prompt()`, set `summary.sections`, cap redundant characters at `len(content)`, calculate the percentage with one decimal place, and sort `must_fix` and `suggestions` by estimated savings then code/location. Add passed checks only for categories that actually ran and found nothing.

- [ ] **Step 4: Run all deterministic audit tests**

Run: `python -m pytest tests/story_core/test_prompt_audit.py -v`

Expected: PASS, including the similar-but-not-identical line remaining unflagged.

- [ ] **Step 5: Commit the complete local analyzer**

```bash
git add packages/story_core/prompt_audit.py tests/story_core/test_prompt_audit.py
git commit -m "feat: diagnose prompt duplication and conflicts"
```

### Task 3: Add the explicit AI semantic pass

**Files:**
- Create: `packages/story_core/prompt_audit_deep.py`
- Create: `tests/story_core/test_prompt_audit_deep.py`

- [ ] **Step 1: Write failing tests for one model call, merged findings, and runtime metadata**

```python
from __future__ import annotations

from packages.story_core.prompt_audit import audit_prompt
from packages.story_core.prompt_audit_deep import DeepPromptAuditor
from packages.story_core.runtime_config import StageRuntimeSettings


def test_deep_audit_calls_configured_runtime_once_and_merges_semantic_issues() -> None:
    calls: list[dict] = []

    def fake_post(base_url, path, payload, api_key, **kwargs):
        calls.append({"base_url": base_url, "path": path, "payload": payload, **kwargs})
        return {
            "choices": [{"message": {"content": '{"issues":[{"severity":"suggestion","code":"semantic_duplicate","title":"语义重复","evidence":"两处都要求对话自然","location":"对话要求","suggestion":"合并为一条具体要求","estimated_reduction_characters":18}]}'}}],
        }

    runtime = StageRuntimeSettings(
        provider="openai",
        model="test-model",
        api_key="secret",
        base_url="https://example.test/v1",
        codex_command="",
        temperature=0.2,
        new_character_policy="Director review",
    )
    local = audit_prompt(mode="final_call", content="对话要自然。\n人物说话要符合日常口语。")
    result = DeepPromptAuditor(
        post_json=fake_post,
        runtime_resolver=lambda stage: runtime,
        clock=iter([10.0, 11.25]).__next__,
    ).analyze(content="对话要自然。\n人物说话要符合日常口语。", local_result=local)

    assert len(calls) == 1
    assert calls[0]["path"] == "/chat/completions"
    assert result.runtime.model == "test-model"
    assert result.runtime.provider == "openai"
    assert result.runtime.elapsed_seconds == 1.25
    assert result.runtime.prompt_characters == len("对话要自然。\n人物说话要符合日常口语。")
    assert any(issue.code == "semantic_duplicate" for issue in result.suggestions)


def test_deep_audit_rejects_oversized_input_without_calling_model() -> None:
    called = False

    def fail_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("model must not be called")

    local = audit_prompt(mode="final_call", content="字" * 80_001)
    auditor = DeepPromptAuditor(post_json=fail_post)

    try:
        auditor.analyze(content="字" * 80_001, local_result=local)
    except ValueError as exc:
        assert str(exc) == "prompt_audit_deep_content_too_long"
    assert called is False
```

- [ ] **Step 2: Run the tests and confirm the provider is missing**

Run: `python -m pytest tests/story_core/test_prompt_audit_deep.py -v`

Expected: FAIL during collection with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the isolated semantic analyzer**

Create `packages/story_core/prompt_audit_deep.py` with:

```python
from __future__ import annotations

import json
from hashlib import sha256
from time import perf_counter
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.prompt_audit import PromptAuditIssue, PromptAuditResult
from packages.story_core.runtime_config import StageRuntimeSettings, resolve_stage_runtime

DEEP_CONTENT_LIMIT = 80_000


class DeepAuditRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    elapsed_seconds: float = Field(ge=0)
    prompt_characters: int = Field(ge=0)


class DeepPromptAuditResult(PromptAuditResult):
    runtime: DeepAuditRuntime


class _SemanticIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["must_fix", "suggestion"]
    code: Literal["semantic_duplicate", "semantic_conflict"]
    title: str = Field(min_length=1, max_length=80)
    evidence: str = Field(min_length=1, max_length=300)
    location: str = Field(min_length=1, max_length=120)
    suggestion: str = Field(min_length=1, max_length=300)
    estimated_reduction_characters: int = Field(default=0, ge=0)


class _SemanticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issues: list[_SemanticIssue] = Field(default_factory=list, max_length=20)


class DeepPromptAuditor:
    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[str], StageRuntimeSettings] = resolve_stage_runtime,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._post_json = post_json
        self._runtime_resolver = runtime_resolver
        self._clock = clock

    def analyze(self, *, content: str, local_result: PromptAuditResult) -> DeepPromptAuditResult:
        if not content.strip():
            raise ValueError("content_required")
        if len(content) > DEEP_CONTENT_LIMIT:
            raise ValueError("prompt_audit_deep_content_too_long")
        expected_hash = sha256(content.encode("utf-8")).hexdigest()
        if local_result.content_sha256 != expected_hash:
            raise ValueError("prompt_audit_local_result_mismatch")
        runtime = self._runtime_resolver("planner")
        if runtime.provider != "codexcli" and not runtime.api_key:
            raise ValueError("runtime_unavailable")
        payload = self._payload(content, local_result, runtime)
        started = self._clock()
        try:
            response = self._post_json(
                runtime.base_url,
                "/chat/completions",
                payload,
                runtime.api_key,
                provider=runtime.provider,
                codex_command=runtime.codex_command,
            )
        except Exception as exc:
            raise ValueError("prompt_audit_deep_failed") from exc
        elapsed = round(max(0.0, self._clock() - started), 3)
        parsed = parse_json_message_content(response)
        if parsed is None:
            raise ValueError("prompt_audit_deep_invalid_response")
        try:
            semantic = _SemanticResponse.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError("prompt_audit_deep_invalid_response") from exc
        return merge_semantic_issues(local_result, semantic, runtime, elapsed, len(content))
```

`_payload()` must send the original prompt and a compact `local_result.model_dump()` as JSON, require JSON-only output, and explicitly limit the model to semantic duplication and semantic conflict. `merge_semantic_issues()` must preserve all local statistics and findings, convert validated semantic issues to `PromptAuditIssue`, deduplicate by `(code, evidence, location)`, sort by estimated savings, and attach `DeepAuditRuntime`. Do not let the model propose rewritten prompt text.

- [ ] **Step 4: Run the deep analyzer tests**

Run: `python -m pytest tests/story_core/test_prompt_audit_deep.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the optional model-backed analyzer**

```bash
git add packages/story_core/prompt_audit_deep.py tests/story_core/test_prompt_audit_deep.py
git commit -m "feat: add optional deep prompt audit"
```

### Task 4: Expose local and deep audit endpoints

**Files:**
- Create: `apps/api/routes/prompt_audit.py`
- Modify: `apps/api/main.py`
- Create: `tests/api/test_prompt_audit_routes.py`

- [ ] **Step 1: Write failing API tests for validation and call isolation**

```python
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import prompt_audit as prompt_audit_routes


def test_local_prompt_audit_returns_result_without_deep_model_call(monkeypatch) -> None:
    monkeypatch.setattr(
        prompt_audit_routes.deep_auditor,
        "analyze",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("deep audit must not run")),
    )
    response = TestClient(app).post(
        "/prompt-audit",
        json={"mode": "template", "content": "{{known}}", "required_variables": ["known"]},
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "prompt-audit/v1"


def test_prompt_audit_maps_domain_errors_to_stable_details() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/prompt-audit", json={"mode": "bad", "content": "x"}).json()["detail"] == "invalid_prompt_audit_mode"
    assert client.post("/prompt-audit", json={"mode": "final_call", "content": " "}).json()["detail"] == "content_required"
    assert client.post("/prompt-audit", json={"mode": "final_call", "content": "x" * 200_001}).json()["detail"] == "prompt_audit_content_too_long"


def test_deep_prompt_audit_rejects_a_local_result_from_different_content() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    local_result = client.post(
        "/prompt-audit",
        json={"mode": "final_call", "content": "第一份内容"},
    ).json()

    response = client.post(
        "/prompt-audit/deep",
        json={"mode": "final_call", "content": "第二份内容", "local_result": local_result},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "prompt_audit_local_result_mismatch"


def test_deep_prompt_audit_is_called_only_by_explicit_endpoint(monkeypatch) -> None:
    local_response = TestClient(app).post(
        "/prompt-audit",
        json={"mode": "final_call", "content": "只输出正文。"},
    ).json()
    calls = []
    monkeypatch.setattr(
        prompt_audit_routes.deep_auditor,
        "analyze",
        lambda **kwargs: calls.append(kwargs) or {**local_response, "runtime": {"provider": "codexcli", "model": "test", "elapsed_seconds": 1, "prompt_characters": 6}},
    )

    response = TestClient(app).post(
        "/prompt-audit/deep",
        json={"mode": "final_call", "content": "只输出正文。", "local_result": local_response},
    )

    assert response.status_code == 200
    assert len(calls) == 1
```

- [ ] **Step 2: Run the API tests and confirm the router is missing**

Run: `python -m pytest tests/api/test_prompt_audit_routes.py -v`

Expected: FAIL during import because `apps.api.routes.prompt_audit` does not exist.

- [ ] **Step 3: Implement and register the dedicated router**

Create `apps/api/routes/prompt_audit.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.story_core.prompt_audit import PromptAuditResult, audit_prompt
from packages.story_core.prompt_audit_deep import DeepPromptAuditResult, DeepPromptAuditor

router = APIRouter()
deep_auditor = DeepPromptAuditor()


class PromptAuditRequest(BaseModel):
    mode: str
    content: str
    template_key: str = ""
    required_variables: list[str] = Field(default_factory=list)


class DeepPromptAuditRequest(PromptAuditRequest):
    local_result: PromptAuditResult


def _http_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail == "runtime_unavailable":
        status = 503
    elif detail in {"prompt_audit_deep_failed", "prompt_audit_deep_invalid_response"}:
        status = 502
    else:
        status = 422
    return HTTPException(status_code=status, detail=detail)


def init_prompt_audit_routes() -> APIRouter:
    @router.post("/prompt-audit", response_model=PromptAuditResult)
    def run_prompt_audit(payload: PromptAuditRequest) -> PromptAuditResult:
        try:
            return audit_prompt(
                mode=payload.mode,
                content=payload.content,
                template_key=payload.template_key,
                required_variables=payload.required_variables,
            )
        except ValueError as exc:
            raise _http_error(exc) from exc

    @router.post("/prompt-audit/deep", response_model=DeepPromptAuditResult)
    def run_deep_prompt_audit(payload: DeepPromptAuditRequest) -> DeepPromptAuditResult:
        try:
            if payload.local_result.mode != payload.mode:
                raise ValueError("prompt_audit_local_result_mismatch")
            return deep_auditor.analyze(content=payload.content, local_result=payload.local_result)
        except ValueError as exc:
            raise _http_error(exc) from exc

    return router
```

Import `init_prompt_audit_routes` in `apps/api/main.py` and add `app.include_router(init_prompt_audit_routes())` beside the other independent global routers.

- [ ] **Step 4: Run endpoint and app smoke tests**

Run: `python -m pytest tests/api/test_prompt_audit_routes.py tests/api/test_main.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the API surface**

```bash
git add apps/api/routes/prompt_audit.py apps/api/main.py tests/api/test_prompt_audit_routes.py
git commit -m "feat: expose prompt audit endpoints"
```

### Task 5: Add the typed web client and shared result panel

**Files:**
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/components/prompts/PromptAuditPanel.tsx`
- Modify: `apps/web/components/prompts/PromptTemplatesView.tsx`
- Modify: `apps/web/app/globals.css`
- Create: `apps/web/tests/prompt-audit.spec.ts`

- [ ] **Step 1: Add a failing browser test for compact local results**

Create `apps/web/tests/prompt-audit.spec.ts` with a route fixture that opens a file project prompt page, returns one `writer` template, and handles `POST /prompt-audit`. The test must include these assertions:

```typescript
test("模板诊断使用未保存内容并显示紧凑结果", async ({ page }) => {
  await installPromptAuditFixture(page);
  await page.goto(`/projects/${encodeURIComponent("file:prompt-audit")}/prompts`);
  await page.getByLabel("原始模板").fill("只输出正文。\n只输出正文。\n{{output_section}}");
  await page.getByRole("button", { name: "检查提示词" }).click();

  expect(lastAuditRequest.content).toContain("只输出正文。\n只输出正文。");
  await expect(page.getByRole("heading", { name: "提示词检查" })).toBeVisible();
  await expect(page.getByText("建议精简", { exact: true })).toBeVisible();
  await expect(page.getByText("重复指令", { exact: true })).toBeVisible();
  await expect(page.getByText("分析报告", { exact: true })).toHaveCount(0);
});
```

The mocked response must use the exact TypeScript contract introduced below, including summary sections and one `duplicate_line` suggestion.

- [ ] **Step 2: Run the test and confirm the button is absent**

Run: `npm --prefix apps/web run test:e2e -- prompt-audit.spec.ts --grep "模板诊断使用未保存内容"`

Expected: FAIL because `检查提示词` is not rendered.

- [ ] **Step 3: Add TypeScript contracts and API functions**

Add to `apps/web/lib/api.ts`:

```typescript
export type PromptAuditMode = "template" | "final_call";

export type PromptAuditIssue = {
  code: string;
  title: string;
  evidence: string;
  location: string;
  suggestion: string;
  estimated_reduction_characters: number;
};

export type PromptAuditResult = {
  schema_version: "prompt-audit/v1";
  mode: PromptAuditMode;
  content_sha256: string;
  summary: {
    characters: number;
    lines: number;
    estimated_redundant_characters: number;
    estimated_reduction_percent: number;
    sections: Array<{ title: string; characters: number; percent: number }>;
  };
  must_fix: PromptAuditIssue[];
  suggestions: PromptAuditIssue[];
  passed_checks: string[];
  runtime?: {
    provider: string;
    model: string;
    elapsed_seconds: number;
    prompt_characters: number;
  };
};

export type PromptAuditRequest = {
  mode: PromptAuditMode;
  content: string;
  template_key?: string;
  required_variables?: string[];
};

export async function auditPrompt(payload: PromptAuditRequest): Promise<PromptAuditResult> {
  return await tryFetchJson(`${apiBase()}/prompt-audit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deepAuditPrompt(
  payload: PromptAuditRequest,
  localResult: PromptAuditResult,
): Promise<PromptAuditResult> {
  return await tryFetchJson(`${apiBase()}/prompt-audit/deep`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, local_result: localResult }),
  }, 360_000);
}
```

- [ ] **Step 4: Build the shared compact result component**

Create `apps/web/components/prompts/PromptAuditPanel.tsx` with props:

```typescript
type PromptAuditPanelProps = {
  result: PromptAuditResult;
  stale?: boolean;
  deepLoading?: boolean;
  deepError?: string;
  onDeepAudit?: () => void;
};
```

Render:

```tsx
<section className="ws-prompt-audit" aria-labelledby="prompt-audit-title">
  <div className="ws-section-head">
    <div>
      <h3 id="prompt-audit-title" className="ws-card__title">提示词检查</h3>
      <p className="ws-card__hint">
        {result.summary.characters} 字符 · {result.summary.lines} 个有效行 · 预计可减少 {result.summary.estimated_redundant_characters} 字符
      </p>
    </div>
    {onDeepAudit ? (
      <button className="ws-btn" type="button" disabled={deepLoading || stale} onClick={onDeepAudit}>
        {deepLoading ? "深度检查中..." : "AI 深度检查"}
      </button>
    ) : null}
  </div>
  {stale ? <p className="ws-inline-warning" role="status">内容已变化，请重新检查。</p> : null}
  <AuditGroup title="必须修" issues={result.must_fix} emptyText="没有发现会直接影响执行的问题。" />
  <AuditGroup title="建议精简" issues={result.suggestions} emptyText="没有发现明确重复。" />
  <PassedChecks checks={result.passed_checks} />
  {result.runtime ? <p className="ws-card__hint">{result.runtime.provider} / {result.runtime.model} · {result.runtime.elapsed_seconds} 秒 · 输入 {result.runtime.prompt_characters} 字符</p> : null}
  {deepError ? <p className="ws-inline-error" role="alert">深度检查失败：{deepError}</p> : null}
</section>
```

`AuditGroup` must render each issue as a plain bordered row with title, evidence, location, suggestion, and estimated savings. Do not use nested cards, charts, auto-fix controls, or long explanatory copy. Add `.ws-prompt-audit`, `.ws-prompt-audit__summary`, `.ws-prompt-audit__group`, `.ws-prompt-audit__issue`, and `.ws-inline-warning` styles to `globals.css`, using existing colors, 6px radii, and a single-column mobile layout.

- [ ] **Step 5: Add the minimal template entry point needed by the browser test**

In `PromptTemplatesView.tsx`, import `auditPrompt`, `PromptAuditResult`, and `PromptAuditPanel`. Add local `auditResult`, `auditLoading`, and `auditError` state, submit the current editor content with the selected template key and required variables, render the `检查提示词` button in the existing action row, and render `PromptAuditPanel` below it. Omit `onDeepAudit` in this first integration so no inactive deep-check control is shown; Task 6 adds complete stale/deep behavior.

- [ ] **Step 6: Run the focused browser test and TypeScript compilation**

Run: `npm --prefix apps/web run test:e2e -- prompt-audit.spec.ts --grep "模板诊断使用未保存内容"`

Expected: PASS.

Run: `npm --prefix apps/web exec tsc -- --noEmit`

Expected: PASS.

- [ ] **Step 7: Commit the client contract, result UI, and first entry point**

```bash
git add apps/web/lib/api.ts apps/web/components/prompts/PromptAuditPanel.tsx apps/web/components/prompts/PromptTemplatesView.tsx apps/web/app/globals.css apps/web/tests/prompt-audit.spec.ts
git commit -m "feat: add prompt audit result panel"
```

### Task 6: Integrate template auditing with unsaved and stale state

**Files:**
- Modify: `apps/web/components/prompts/PromptTemplatesView.tsx`
- Modify: `apps/web/tests/prompt-audit.spec.ts`

- [ ] **Step 1: Extend the failing test to cover stale state and request failure**

Add these assertions to `apps/web/tests/prompt-audit.spec.ts`:

```typescript
await page.getByLabel("原始模板").fill("检查后的新内容 {{output_section}}");
await expect(page.getByText("内容已变化，请重新检查。")).toBeVisible();

auditShouldFail = true;
await page.getByRole("button", { name: "检查提示词" }).click();
await expect(page.getByRole("alert")).toContainText("检查失败");
await expect(page.getByLabel("原始模板")).toHaveValue("检查后的新内容 {{output_section}}");
```

- [ ] **Step 2: Run the template test and confirm stale/error behavior fails**

Run: `npm --prefix apps/web run test:e2e -- prompt-audit.spec.ts --grep "模板诊断"`

Expected: FAIL because the template view has no audit state.

- [ ] **Step 3: Add independent local/deep audit state to `PromptTemplatesView`**

Import `auditPrompt`, `deepAuditPrompt`, `PromptAuditResult`, and `PromptAuditPanel`. Add:

```typescript
const [auditResult, setAuditResult] = useState<PromptAuditResult | null>(null);
const [auditedContent, setAuditedContent] = useState("");
const [auditLoading, setAuditLoading] = useState(false);
const [deepLoading, setDeepLoading] = useState(false);
const [auditError, setAuditError] = useState("");
const [deepError, setDeepError] = useState("");

const auditPayload = selected ? {
  mode: "template" as const,
  content,
  template_key: selected.key,
  required_variables: selected.required_variables,
} : null;
```

Implement `runAudit()` so it submits the current `content`, stores both result and exact `auditedContent`, and never calls save. Implement `runDeepAudit()` so it requires a current non-stale local result and passes that exact result to `deepAuditPrompt`. On template selection, clear all audit state. On editor changes, retain the old result so `auditedContent !== content` visibly marks it stale. Keep audit errors separate from existing save/load errors.

Add a `检查提示词` button to the existing actions and render `PromptAuditPanel` below the actions when a result exists:

```tsx
<button className="ws-btn" type="button" disabled={auditLoading || saving !== null} onClick={() => void runAudit()}>
  {auditLoading ? "检查中..." : "检查提示词"}
</button>
{auditError ? <p className="ws-inline-error" role="alert">检查失败：{auditError}</p> : null}
{auditResult ? (
  <PromptAuditPanel
    result={auditResult}
    stale={auditedContent !== content}
    deepLoading={deepLoading}
    deepError={deepError}
    onDeepAudit={() => void runDeepAudit()}
  />
) : null}
```

- [ ] **Step 4: Run template browser coverage and TypeScript**

Run: `npm --prefix apps/web run test:e2e -- prompt-audit.spec.ts --grep "模板诊断"`

Expected: PASS.

Run: `npm --prefix apps/web exec tsc -- --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit template integration**

```bash
git add apps/web/components/prompts/PromptTemplatesView.tsx apps/web/tests/prompt-audit.spec.ts
git commit -m "feat: audit editable prompt templates"
```

### Task 7: Integrate recorded-call auditing and explicit deep diagnosis

**Files:**
- Modify: `apps/web/components/prompts/PromptCallsView.tsx`
- Modify: `apps/web/tests/prompt-audit.spec.ts`

- [ ] **Step 1: Add a failing recorded-call and deep-audit browser test**

```typescript
test("真实调用可单独检查且深度检查只在点击后运行", async ({ page }) => {
  await installPromptAuditFixture(page);
  await page.goto(`/projects/${encodeURIComponent("file:prompt-audit")}/prompts?view=calls&chapter=1`);
  await page.getByRole("button", { name: "查看调用 pc-audit" }).click();
  await page.getByRole("button", { name: "检查这次调用" }).click();

  expect(localAuditCount).toBe(1);
  expect(deepAuditCount).toBe(0);
  await page.getByRole("button", { name: "AI 深度检查" }).click();
  await expect.poll(() => deepAuditCount).toBe(1);
  await expect(page.getByText("codexcli / gpt-test", { exact: false })).toBeVisible();
});
```

The fixture must return a recorded `user_prompt`, a local result, and a deep result with one semantic suggestion plus runtime metadata.

- [ ] **Step 2: Run the test and confirm the call-audit button is absent**

Run: `npm --prefix apps/web run test:e2e -- prompt-audit.spec.ts --grep "真实调用"`

Expected: FAIL because `检查这次调用` is not rendered.

- [ ] **Step 3: Add call-specific audit state and clear it when selection changes**

In `PromptCallsView.tsx`, add the same local/deep loading and error state used by the template view, but no stale state because call records are immutable. Clear the result before opening another call. Submit only `selected.user_prompt` with `mode: "final_call"`:

```typescript
const payload = selected ? { mode: "final_call" as const, content: selected.user_prompt } : null;

async function runAudit() {
  if (!payload) return;
  setAuditLoading(true);
  setAuditError("");
  setDeepError("");
  try {
    setAuditResult(await auditPrompt(payload));
  } catch (reason) {
    setAuditError(reason instanceof Error ? reason.message : String(reason));
  } finally {
    setAuditLoading(false);
  }
}
```

Render `检查这次调用` beside the full prompt heading and place `PromptAuditPanel` immediately after the `user_prompt` block. `runDeepAudit()` must call `deepAuditPrompt(payload, auditResult)` only after the user clicks the panel button. A failed request must leave the selected call and prompt visible.

- [ ] **Step 4: Run all prompt-audit browser tests and TypeScript**

Run: `npm --prefix apps/web run test:e2e -- prompt-audit.spec.ts`

Expected: PASS.

Run: `npm --prefix apps/web exec tsc -- --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit recorded-call integration**

```bash
git add apps/web/components/prompts/PromptCallsView.tsx apps/web/tests/prompt-audit.spec.ts
git commit -m "feat: audit recorded model prompts"
```

### Task 8: Verify regression safety and the no-side-effect contract

**Files:**
- Modify only if a verification failure identifies a defect in files already listed above.

- [ ] **Step 1: Run the complete new backend suite**

Run: `python -m pytest tests/story_core/test_prompt_audit.py tests/story_core/test_prompt_audit_deep.py tests/api/test_prompt_audit_routes.py -v`

Expected: PASS.

- [ ] **Step 2: Run adjacent prompt and runtime regression tests**

Run: `python -m pytest tests/story_core/test_prompt_templates.py tests/story_core/test_prompt_call_log.py tests/story_core/test_runtime_config.py tests/api/test_main.py -v`

Expected: PASS; existing template rendering, call logs, and runtime configuration remain unchanged.

- [ ] **Step 3: Run the existing prompt workbench test with the new browser tests**

Run: `npm --prefix apps/web run test:e2e -- story-workbench.spec.ts --grep "提示词工作台"`

Expected: PASS.

Run: `npm --prefix apps/web run test:e2e -- prompt-audit.spec.ts`

Expected: PASS.

- [ ] **Step 4: Build the web application**

Run: `npm --prefix apps/web run build`

Expected: Next.js build completes with no type or route errors.

- [ ] **Step 5: Inspect the final diff for forbidden coupling**

Run: `git diff --check`

Expected: no whitespace errors.

Run: `rg -n "auditPrompt|DeepPromptAuditor|prompt-audit" packages/story_core apps/api apps/web`

Expected: references appear only in the new analyzer, dedicated router, web API/client components, and tests; no chapter-generation orchestrator, writer, director, memory, project-store, or prompt-template save path invokes prompt auditing.

- [ ] **Step 6: Commit any verification-only corrections**

If verification required corrections, stage only the prompt-audit files and commit:

```bash
git add packages/story_core/prompt_templates.py packages/story_core/prompt_audit.py packages/story_core/prompt_audit_deep.py apps/api/routes/prompt_audit.py apps/api/main.py apps/web/lib/api.ts apps/web/components/prompts/PromptAuditPanel.tsx apps/web/components/prompts/PromptTemplatesView.tsx apps/web/components/prompts/PromptCallsView.tsx apps/web/app/globals.css tests/story_core/test_prompt_templates.py tests/story_core/test_prompt_audit.py tests/story_core/test_prompt_audit_deep.py tests/api/test_prompt_audit_routes.py apps/web/tests/prompt-audit.spec.ts
git commit -m "fix: complete prompt audit verification"
```

If no correction was needed, do not create an empty commit.
