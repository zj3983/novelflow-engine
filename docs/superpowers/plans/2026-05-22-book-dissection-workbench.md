# Book Dissection Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a "拆书" workbench that can analyze pasted reference chapters and diagnose chapters from the current file project.

**Architecture:** Add a focused `book_dissection` story-core module with a stable report schema and deterministic heuristics. Expose it through one generic reference API and one file-project chapter API, then add a project page that calls those APIs and renders grouped report sections.

**Tech Stack:** Python, FastAPI, pytest, Next.js App Router, TypeScript, existing workspace shell and API helpers.

---

## File Structure

- Create `packages/story_core/book_dissection.py`: owns report schema helpers and deterministic dissection logic.
- Create `tests/story_core/test_book_dissection.py`: unit tests for reference and project diagnosis reports.
- Modify `apps/api/routes/file_projects.py`: add request models and file-project chapter dissection route.
- Modify `apps/api/main.py`: register a small generic book-dissection router if route modules are not auto-included.
- Create `tests/api/test_book_dissection_routes.py`: API tests for reference and file-project routes.
- Modify `apps/web/lib/api.ts`: add TypeScript types and API functions for dissection.
- Modify `apps/web/components/ws/WorkspaceShell.tsx`: add "拆书" to project navigation.
- Create `apps/web/app/projects/[id]/dissection/page.tsx`: project dissection UI.
- Add or extend frontend tests under `apps/web/tests` if the existing test runner can cover the new page.

## Task 1: Story-Core Dissection Module

**Files:**
- Create: `packages/story_core/book_dissection.py`
- Test: `tests/story_core/test_book_dissection.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/story_core/test_book_dissection.py`:

```python
import pytest

from packages.story_core.book_dissection import diagnose_project_chapter, dissect_reference_text


def section(report: dict, key: str) -> list[str]:
    return report["sections"][key]


def test_dissect_reference_text_returns_required_sections():
    text = "\n".join(
        [
            "夜烬绕开人群，等灰狼落单才出手。",
            "短发玩家说：\"你怎么不接任务？\"",
            "夜烬说：\"还差两份材料，先把蓝回满。\"",
            "任务牌上写着清道夫委托需要十份毒腺。",
        ]
    )

    report = dissect_reference_text(text, genre="网游", focus="苟道幕后")

    assert report["schema_version"] == "book-dissection/v1"
    assert report["mode"] == "reference"
    for key in [
        "章节作用",
        "爽点来源",
        "主角进展",
        "冲突推进",
        "对话功能",
        "节奏拆解",
        "结尾钩子",
        "可学习写法",
        "不能照抄",
    ]:
        assert key in report["sections"]
        assert section(report, key)
    assert any("网游" in item or "任务" in item for item in section(report, "可学习写法"))


def test_diagnose_project_chapter_flags_common_webgame_issues():
    chapter = {
        "chapter_number": 2,
        "chapter_title": "提前转职",
        "body": "夜烬1级就接了转职任务。\n他说：\"行。\"\n他说：\"好。\"\n【货币：0铜】\n怪物面板弹出来。",
    }
    state = {
        "current_chapter": 2,
        "progression_ledger": {
            "protagonist": {"level": "Lv.1"},
            "economy": {"game_currency": "0铜"},
        },
    }

    report = diagnose_project_chapter({"state": state}, chapter)

    assert report["mode"] == "project"
    assert any("转职" in item for item in section(report, "设定冲突"))
    assert any("短" in item or "不像" in item for item in section(report, "对话问题"))
    assert any("货币：0铜" in item for item in section(report, "说明感问题"))
    assert section(report, "可写入提示词")


def test_dissect_reference_text_rejects_empty_text():
    with pytest.raises(ValueError, match="text_required"):
        dissect_reference_text("   ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/story_core/test_book_dissection.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'packages.story_core.book_dissection'`.

- [ ] **Step 3: Implement the module**

Create `packages/story_core/book_dissection.py`:

```python
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


REFERENCE_KEYS = ["章节作用", "爽点来源", "主角进展", "冲突推进", "对话功能", "节奏拆解", "结尾钩子", "可学习写法", "不能照抄"]
PROJECT_KEYS = ["主要问题", "不爽原因", "设定冲突", "对话问题", "说明感问题", "下一版改法", "可写入提示词"]


def _lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _require_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("text_required")
    if len(cleaned) > 50000:
        raise ValueError("text_too_long")
    return cleaned


def _dialogue_lines(text: str) -> list[str]:
    return [line for line in _lines(text) if "“" in line or '"' in line or "：" in line and "【" not in line]


def _short_dialogue_count(text: str) -> int:
    count = 0
    for line in _dialogue_lines(text):
        matches = re.findall(r"[“\"]([^”\"]{1,8})[”\"]", line)
        count += len([item for item in matches if len(item.strip()) <= 4])
    return count


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _report(mode: str, sections: dict[str, list[str]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "book-dissection/v1",
        "mode": mode,
        "sections": sections,
        "summary": "；".join(next(iter(items)) for items in sections.values() if items)[:240],
        "meta": meta or {},
    }


def dissect_reference_text(text: str, *, genre: str = "", focus: str = "") -> dict[str, Any]:
    body = _require_text(text)
    lines = _lines(body)
    has_task = _contains_any(body, ["任务", "委托", "奖励", "前置"])
    has_game = _contains_any(body, ["等级", "经验", "法力", "背包", "技能", "玩家", "怪"])
    has_dialogue = bool(_dialogue_lines(body))
    sections = {key: [] for key in REFERENCE_KEYS}

    sections["章节作用"].append("这一段主要用于展示主角的选择、即时压力和下一步目标。")
    sections["爽点来源"].append("爽点来自主角比普通人更早看见机会，并把机会落到行动上。")
    sections["主角进展"].append("主角完成了信息确认或资源推进，读者能看到状态变化。")
    sections["冲突推进"].append("压力先来自环境或规则，随后由主角用路线、等待、交易或战斗处理。")
    sections["对话功能"].append("对话用于暴露玩家生态和任务信息。") if has_dialogue else sections["对话功能"].append("样本文本对话较少，主要靠行动推进。")
    sections["节奏拆解"].append(f"文本约{len(lines)}个有效段落，适合拆成目标、阻碍、行动、结果四步看。")
    sections["结尾钩子"].append("结尾应留下下一步可执行目标，而不是只留抽象悬念。")
    sections["可学习写法"].append("把网游规则放进任务牌、背包、面板和玩家闲聊里。") if has_game or has_task or "网游" in genre else sections["可学习写法"].append("学习它用具体动作承接设定，不直接搬句子。")
    sections["不能照抄"].append("人物名、专有设定、原文句式和具体桥段不能复制，只能学习结构。")

    if focus:
        sections["可学习写法"].append(f"本次关注“{focus}”，拆解时优先看它如何服务主角行动。")
    return _report("reference", sections, {"genre": genre, "focus": focus, "text_chars": len(body)})


def diagnose_project_chapter(project_context: Mapping[str, Any], chapter: Mapping[str, Any]) -> dict[str, Any]:
    body = _require_text(str(chapter.get("body") or ""))
    sections = {key: [] for key in PROJECT_KEYS}
    chapter_number = int(chapter.get("chapter_number") or 0)

    if "转职任务" in body and ("1级" in body or "Lv.1" in body):
        sections["设定冲突"].append("Lv.1阶段出现转职任务，容易显得升级线跳太快。")
    if _contains_any(body, ["【货币：0铜】", "怪物面板", "法师兄", "牙缝", "草屑"]):
        for token in ["【货币：0铜】", "怪物面板", "法师兄", "牙缝", "草屑"]:
            if token in body:
                sections["说明感问题"].append(f"命中已拒绝写法：{token}。")
    if _short_dialogue_count(body) >= 2:
        sections["对话问题"].append("连续短对白偏多，人物像在报点，不像自然交流。")
    if len(re.findall(r"【经验：", body)) > 4 and body.count("灰狼") > 8:
        sections["不爽原因"].append("刷怪信息重复时，要增加意外、选择或收益兑现。")
    if not _contains_any(body, ["获得", "奖励", "接取", "完成", "升级", "解锁", "前置任务"]):
        sections["主要问题"].append("章节缺少明确进展，读者不容易感到爽点兑现。")

    if not any(sections.values()):
        sections["主要问题"].append("没有命中硬性错误，下一步应重点看节奏和爽点强度。")

    sections["下一版改法"].append("先固定本章目标，再安排阻碍、行动和结果，避免边写边改设定。")
    sections["可写入提示词"].append("对话要有具体目的和完整回应；网游规则通过行动、任务牌、背包和玩家反应呈现。")
    sections["可写入提示词"].append("隐藏优势只让主角确认，不让NPC、公会或论坛过早注意。")

    return _report("project", sections, {"chapter_number": chapter_number, "title": chapter.get("chapter_title") or chapter.get("title") or ""})
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
pytest tests/story_core/test_book_dissection.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/book_dissection.py tests/story_core/test_book_dissection.py
git commit -m "feat: add book dissection core"
```

## Task 2: API Routes

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Test: `tests/api/test_book_dissection_routes.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/api/test_book_dissection_routes.py`:

```python
from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def test_reference_dissection_route_returns_report():
    response = client.post(
        "/book-dissection/reference",
        json={"text": "夜烬看了一眼任务牌。玩家问：\"你不接任务？\"", "genre": "网游", "focus": "对话"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "book-dissection/v1"
    assert payload["mode"] == "reference"
    assert "爽点来源" in payload["sections"]


def test_reference_dissection_route_validates_empty_text():
    response = client.post("/book-dissection/reference", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["detail"] == "text_required"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/api/test_book_dissection_routes.py -q
```

Expected: fail with 404 for `/book-dissection/reference`.

- [ ] **Step 3: Add route models and reference endpoint**

Modify `apps/api/routes/file_projects.py` near existing imports:

```python
from packages.story_core.book_dissection import diagnose_project_chapter, dissect_reference_text
```

Add request models near other Pydantic models:

```python
class BookDissectionReferenceRequest(BaseModel):
    text: str
    genre: str = ""
    focus: str = ""


class BookDissectionChapterRequest(BaseModel):
    chapter_number: int | None = None
```

Add this route inside `init_file_project_routes()` before `return router`:

```python
    @router.post("/book-dissection/reference")
    def dissect_reference(payload: BookDissectionReferenceRequest) -> dict[str, Any]:
        try:
            return dissect_reference_text(payload.text, genre=payload.genre, focus=payload.focus)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 4: Run reference route tests**

Run:

```powershell
pytest tests/api/test_book_dissection_routes.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Add file-project chapter test**

Append to `tests/api/test_book_dissection_routes.py`:

```python
def test_file_project_chapter_dissection_route_uses_store():
    projects = client.get("/file-projects").json()
    if not projects:
        return
    project_id = projects[0]["project_id"]

    response = client.post(
        f"/file-projects/{project_id}/book-dissection/chapter",
        json={"chapter_number": 1},
    )

    assert response.status_code in {200, 404}
    if response.status_code == 200:
        payload = response.json()
        assert payload["schema_version"] == "book-dissection/v1"
        assert payload["mode"] == "project"
        assert "下一版改法" in payload["sections"]
```

- [ ] **Step 6: Implement file-project chapter endpoint**

Add inside `init_file_project_routes()`:

```python
    @router.post("/file-projects/{project_id}/book-dissection/chapter")
    def dissect_file_project_chapter(project_id: str, payload: BookDissectionChapterRequest) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            chapter = store.chapter(payload.chapter_number)
            return diagnose_project_chapter({"project": store.project(), "state": store.state()}, chapter)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 7: Run API tests**

Run:

```powershell
pytest tests/api/test_book_dissection_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add apps/api/routes/file_projects.py tests/api/test_book_dissection_routes.py
git commit -m "feat: expose book dissection APIs"
```

## Task 3: Frontend API Client

**Files:**
- Modify: `apps/web/lib/api.ts`

- [ ] **Step 1: Add TypeScript types and API functions**

Add near other exported API types in `apps/web/lib/api.ts`:

```ts
export type BookDissectionReport = {
  schema_version: "book-dissection/v1";
  mode: "reference" | "project";
  summary: string;
  sections: Record<string, string[]>;
  meta?: Record<string, unknown>;
};

export async function dissectReferenceText(payload: {
  text: string;
  genre?: string;
  focus?: string;
}): Promise<BookDissectionReport> {
  return (await tryFetchJson(`${apiBase()}/book-dissection/reference`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })) as BookDissectionReport;
}

export async function dissectFileProjectChapter(
  projectId: string,
  chapterNumber?: number,
): Promise<BookDissectionReport> {
  if (!isFileProjectId(projectId)) {
    throw new Error("book_dissection_only_supports_file_projects");
  }
  return (await tryFetchJson(`${fileProjectPath(projectId)}/book-dissection/chapter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chapter_number: chapterNumber }),
  })) as BookDissectionReport;
}
```

- [ ] **Step 2: Run TypeScript check**

Run:

```powershell
cd apps/web
npm run lint
```

Expected: no new TypeScript or lint errors. If the repo has no lint script, run `npm run build` and record the existing result.

- [ ] **Step 3: Commit**

```powershell
git add apps/web/lib/api.ts
git commit -m "feat: add book dissection API client"
```

## Task 4: Dissection Page and Navigation

**Files:**
- Modify: `apps/web/components/ws/WorkspaceShell.tsx`
- Create: `apps/web/app/projects/[id]/dissection/page.tsx`

- [ ] **Step 1: Add navigation item**

Modify `projectNav()` in `apps/web/components/ws/WorkspaceShell.tsx`:

```tsx
function projectNav(projectId: string): NavItem[] {
  const base = projectHref(projectId);
  return [
    { href: base, label: "概览", exact: true },
    { href: `${base}/write`, label: "章节" },
    { href: `${base}/dissection`, label: "拆书" },
    { href: `${base}/sim`, label: "世界推演" },
    { href: `${base}/world`, label: "角色卡" },
  ];
}
```

- [ ] **Step 2: Create the page**

Create `apps/web/app/projects/[id]/dissection/page.tsx`:

```tsx
"use client";

import { useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { type BookDissectionReport, dissectFileProjectChapter, dissectReferenceText } from "../../../../lib/api";

type Mode = "reference" | "project";

const SECTION_ORDER = ["章节作用", "爽点来源", "主角进展", "冲突推进", "对话功能", "节奏拆解", "结尾钩子", "可学习写法", "不能照抄", "主要问题", "不爽原因", "设定冲突", "对话问题", "说明感问题", "下一版改法", "可写入提示词"];

function ReportView({ report }: { report: BookDissectionReport | null }) {
  if (!report) {
    return (
      <div className="ws-empty">
        <p className="ws-empty__title">还没有拆书报告</p>
        <p>粘贴参考章节，或者选择本书章节后开始分析。</p>
      </div>
    );
  }
  const keys = SECTION_ORDER.filter((key) => report.sections[key]?.length).concat(
    Object.keys(report.sections).filter((key) => !SECTION_ORDER.includes(key)),
  );
  return (
    <div className="ws-stat-row">
      {keys.map((key) => (
        <section className="ws-card" key={key} style={{ gridColumn: "1 / -1" }}>
          <p className="ws-card__title">{key}</p>
          <ul className="ws-plain-list">
            {report.sections[key].map((item, index) => (
              <li key={`${key}-${index}`}>{item}</li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export default function DissectionPage() {
  const { project, story, error, encodedProjectId } = useProjectWorkspace();
  const [mode, setMode] = useState<Mode>("reference");
  const [text, setText] = useState("");
  const [genre, setGenre] = useState("网游");
  const [focus, setFocus] = useState("爽点和对话");
  const [chapterNumber, setChapterNumber] = useState<number | undefined>(story?.current_chapter || undefined);
  const [report, setReport] = useState<BookDissectionReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const chapters = useMemo(() => story?.history ?? [], [story?.history]);

  async function run() {
    setBusy(true);
    setMessage("");
    try {
      const next =
        mode === "reference"
          ? await dissectReferenceText({ text, genre, focus })
          : await dissectFileProjectChapter(project?.project_id || "", chapterNumber);
      setReport(next);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "拆书失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="拆书"
        subtitle="拆参考章节的写法，也检查本书章节的问题。"
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : (
        <div className="ws-editor-layout">
          <section className="ws-card">
            <div className="ws-toolbar">
              <button className={mode === "reference" ? "ws-button ws-button--primary" : "ws-button"} onClick={() => setMode("reference")} type="button">
                参考书拆解
              </button>
              <button className={mode === "project" ? "ws-button ws-button--primary" : "ws-button"} onClick={() => setMode("project")} type="button">
                本书体检
              </button>
            </div>

            {mode === "reference" ? (
              <div className="ws-form-grid">
                <label>
                  题材
                  <input value={genre} onChange={(event) => setGenre(event.target.value)} />
                </label>
                <label>
                  关注点
                  <input value={focus} onChange={(event) => setFocus(event.target.value)} />
                </label>
                <label style={{ gridColumn: "1 / -1" }}>
                  参考文本
                  <textarea rows={16} value={text} onChange={(event) => setText(event.target.value)} />
                </label>
              </div>
            ) : (
              <label>
                章节
                <select value={chapterNumber || ""} onChange={(event) => setChapterNumber(Number(event.target.value) || undefined)}>
                  {chapters.map((chapter) => (
                    <option key={chapter.chapter_number} value={chapter.chapter_number}>
                      第 {chapter.chapter_number} 章 {chapter.chapter_title || ""}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <div className="ws-toolbar">
              <button className="ws-button ws-button--primary" onClick={run} disabled={busy || (mode === "reference" && !text.trim())} type="button">
                {busy ? "分析中" : "开始拆书"}
              </button>
              {message ? <span className="ws-toolbar__meta">{message}</span> : null}
            </div>
          </section>
          <aside className="ws-sidepanel">
            <section className="ws-card">
              <p className="ws-card__title">使用方式</p>
              <p className="ws-card__hint">参考书拆结构和写法，本书体检找问题。报告默认只读，不会自动写入作者约束。</p>
            </section>
          </aside>
          <section style={{ gridColumn: "1 / -1" }}>
            <ReportView report={report} />
          </section>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Run frontend check**

Run:

```powershell
cd apps/web
npm run build
```

Expected: build completes or only fails on pre-existing unrelated issues. If CSS classes like `ws-form-grid` are missing, add minimal styles in `apps/web/app/globals.css`.

- [ ] **Step 4: Commit**

```powershell
git add apps/web/components/ws/WorkspaceShell.tsx apps/web/app/projects/[id]/dissection/page.tsx apps/web/app/globals.css
git commit -m "feat: add book dissection workbench page"
```

## Task 5: End-to-End Verification

**Files:**
- Modify if needed: `apps/web/tests/story-workbench.spec.ts` or add `apps/web/tests/book-dissection.spec.ts`

- [ ] **Step 1: Add a smoke test if Playwright setup is active**

Create `apps/web/tests/book-dissection.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("book dissection page is reachable", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.getByText("作品")).toBeVisible();
});
```

This is intentionally small because local project IDs differ between machines. The main verification should be manual against the active file project.

- [ ] **Step 2: Run focused backend tests**

Run:

```powershell
pytest tests/story_core/test_book_dissection.py tests/api/test_book_dissection_routes.py -q
```

Expected: all pass.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd apps/web
npm run build
```

Expected: build passes.

- [ ] **Step 4: Manual browser verification**

Open:

```text
http://127.0.0.1:3003/projects/file%3Ap-gou-webgame-restored/dissection
```

Check:

- Navigation includes `拆书`.
- Reference mode accepts pasted text and displays report sections.
- Project mode can analyze chapter 1.
- Report says read-only or otherwise makes clear it will not auto-write constraints.

- [ ] **Step 5: Final commit if smoke test or fixes were added**

```powershell
git status --short
git add apps/web/tests/book-dissection.spec.ts
git commit -m "test: add book dissection smoke coverage"
```

Skip this commit if no test file or fix was added in Task 5.

## Self-Review

- Spec coverage: reference text, own chapter diagnosis, stable report, API, UI, read-only behavior, validation, and tests are covered.
- Scope: full-book import, scraping, automatic saving, and automatic rewrite remain out of scope.
- Risk: existing frontend files contain some mojibake text. This plan avoids broad cleanup and keeps new page text clean UTF-8.
