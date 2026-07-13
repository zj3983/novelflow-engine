# 工作区代码整理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变小说生成行为、不损坏本地数据库和正文的前提下，清理运行产物、收拢重复代码，并把当前有效改动按后端、前端和文档归档提交。

**Architecture:** 当前工作区本身就是待整理对象，因此在现有 `codex/recover-lost-work` 分支执行，不另建 worktree。先通过 SQLite backup 和章节哈希建立恢复点，再补忽略规则、做一处可测试的重复判断提取，最后按依赖边界提交；若某组不能独立通过测试，则与相邻组合并，不使用交互式拆补丁强行分离。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、SQLite、pytest、Next.js 14、TypeScript、PowerShell、Git。

---

## 文件结构

- Modify: `.gitignore`：忽略数据库备份和 Next.js 开发缓存。
- Modify: `apps/api/storage.py`：集中项目显式类型读取，删除重复判断。
- Modify: `tests/api/test_project_context_sync.py`：保护显式类型、未知类型和旧网游兼容行为。
- Keep: `apps/web/next.config.mjs`：开发环境使用 `.next-dev`，生产环境使用 `.next`。
- Keep: `apps/web/tsconfig.json`：包含两个构建目录的 Next.js 类型文件。
- Preserve: `apps/api/data/**`：本地数据库和备份，只忽略，不纳入提交。
- Remove locally: `apps/web/.next-dev/`：可重新生成的开发缓存。
- Commit as backend: `packages/story_core/**`、`apps/api/**`、`scripts/**`、`data/skill-packs/**` 及对应测试。
- Commit as frontend: `apps/web/**`，排除已忽略的构建产物。
- Commit as docs: `docs/superpowers/plans/2026-07-05-split-outline-world-characters.md`、`docs/superpowers/plans/2026-07-11-simplified-chapter-review.md` 和工作区规则。

### Task 1: 建立数据库与正文恢复点

**Files:**
- Preserve: `apps/api/data/stories.db`
- Create locally: `apps/api/data/backups/stories-before-code-organization-<timestamp>.db`
- Create locally: `$env:TEMP/xiaoshuofish-code-organization-baseline.json`

- [ ] **Step 1: 确认数据库和项目存在**

Run:

```powershell
Test-Path 'D:\xiaoshuofish-flow-test\apps\api\data\stories.db'
curl.exe -s -o NUL -w "api=%{http_code}`n" http://127.0.0.1:8000/health
curl.exe -s -o NUL -w "web=%{http_code}`n" 'http://localhost:3000/projects/p-xianxia-incense-test-2/write?chapter=1'
```

Expected: 数据库为 `True`；运行中的服务返回 `200`。服务未运行时只记录状态，不把它当成数据损坏。

- [ ] **Step 2: 使用 SQLite backup 创建一致备份并记录正文哈希**

Run:

```powershell
@'
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from apps.api.storage import SQLiteStoryStore

root = Path(r"D:\xiaoshuofish-flow-test")
db_path = root / "apps" / "api" / "data" / "stories.db"
backup_dir = db_path.parent / "backups"
backup_dir.mkdir(parents=True, exist_ok=True)
backup_path = backup_dir / f"stories-before-code-organization-{datetime.now():%Y%m%d-%H%M%S}.db"
with sqlite3.connect(db_path) as source, sqlite3.connect(backup_path) as destination:
    source.backup(destination)

store = SQLiteStoryStore(str(db_path))
project = store.get_project("p-xianxia-incense-test-2")
assert project is not None and project.active_story_id
record = store.get(project.active_story_id)
assert record is not None
chapters = [
    {
        "chapter_number": bundle.chapter_number,
        "chapter_title": bundle.chapter_title,
        "body_chars": len(bundle.body),
        "sha256": hashlib.sha256(
            f"{bundle.chapter_title}\0{bundle.body}".encode("utf-8")
        ).hexdigest(),
    }
    for bundle in record.history
]
payload = {
    "project_id": project.project_id,
    "active_story_id": project.active_story_id,
    "genre_plugin_ids": project.world_blueprint.get("genre_plugin_ids", []),
    "chapter_count": len(chapters),
    "chapters": chapters,
    "backup_path": str(backup_path),
}
target = Path.home() / "AppData" / "Local" / "Temp" / "xiaoshuofish-code-organization-baseline.json"
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
'@ | .\.venv\Scripts\python.exe -
```

Expected: 输出项目类型、章节数量、标题、字符数、SHA-256 和新备份绝对路径；第一章正文不被写入仓库。

### Task 2: 忽略并清理运行产物

**Files:**
- Modify: `.gitignore`
- Remove locally: `apps/web/.next-dev/`
- Preserve: `apps/api/data/**`

- [ ] **Step 1: 写入失败检查，确认当前规则没有覆盖嵌套备份和开发缓存**

Run:

```powershell
git check-ignore -q apps/api/data/backups/stories-before-genre-migration-20260713-105329-741044.db
if ($LASTEXITCODE -eq 0) { throw 'backup is already ignored; update the test input' }
git check-ignore -q apps/web/.next-dev/app-build-manifest.json
if ($LASTEXITCODE -eq 0) { throw 'next-dev is already ignored; update the test input' }
```

Expected: 两项当前都未被忽略，因此命令按设计抛出。

- [ ] **Step 2: 补充精确忽略规则**

Add to `.gitignore`:

```gitignore
# Local SQLite backups and nested database snapshots
apps/api/data/backups/
apps/api/data/**/*.db

# Separate Next.js development cache
apps/web/.next-dev/
```

- [ ] **Step 3: 验证忽略规则，不删除数据库**

Run:

```powershell
git check-ignore -v apps/api/data/backups/stories-before-genre-migration-20260713-105329-741044.db
git check-ignore -v apps/web/.next-dev/app-build-manifest.json
Test-Path apps/api/data/stories.db
```

Expected: 前两项命中 `.gitignore`，数据库仍为 `True`。

- [ ] **Step 4: 安全删除可重建的 `.next-dev` 缓存**

Run:

```powershell
$target = (Resolve-Path 'apps/web/.next-dev').Path
$root = (Resolve-Path '.').Path
if (-not $target.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove path outside workspace: $target"
}
Remove-Item -LiteralPath $target -Recurse -Force
Test-Path $target
```

Expected: 最后输出 `False`。不对 `apps/api/data` 执行任何删除命令。

- [ ] **Step 5: 提交工作区规则**

Run:

```powershell
git add -- .gitignore
git diff --cached --check
git commit -m "chore: ignore local novel runtime artifacts"
```

Expected: 只提交 `.gitignore`。

### Task 3: 集中项目类型读取逻辑

**Files:**
- Modify: `apps/api/storage.py`
- Modify: `tests/api/test_project_context_sync.py`

- [ ] **Step 1: 增加类型选择边界测试**

Add to `tests/api/test_project_context_sync.py`:

```python
from apps.api.storage import _project_genre_selection


def test_project_genre_selection_distinguishes_missing_unknown_and_known_values():
    missing = NovelProject(project_id="p-missing", title="无类型", world_blueprint={})
    unknown = NovelProject(
        project_id="p-unknown",
        title="未知类型",
        world_blueprint={"genre_plugin_ids": ["future_genre"]},
    )
    known = NovelProject(
        project_id="p-known",
        title="东方玄幻",
        world_blueprint={"genre_plugin_ids": ["东方玄幻", "XUANHUAN"]},
    )

    assert _project_genre_selection(missing) == ([], False)
    assert _project_genre_selection(unknown) == ([], True)
    assert _project_genre_selection(known) == (["xuanhuan"], True)
```

- [ ] **Step 2: 运行测试确认 helper 尚不存在**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_project_context_sync.py::test_project_genre_selection_distinguishes_missing_unknown_and_known_values -q
```

Expected: FAIL，提示无法导入 `_project_genre_selection`。

- [ ] **Step 3: 提取单一 helper 并替换重复判断**

Add to `apps/api/storage.py`:

```python
def _project_genre_selection(project: NovelProject) -> tuple[list[str], bool]:
    world = project.world_blueprint if isinstance(project.world_blueprint, dict) else {}
    raw = world.get("genre_plugin_ids")
    if isinstance(raw, str):
        has_explicit_value = bool(raw.strip())
    elif isinstance(raw, list):
        has_explicit_value = any(str(item).strip() for item in raw)
    else:
        has_explicit_value = False
    return normalize_novel_type_ids(raw), has_explicit_value
```

Use it in `_sync_project_character_profiles`:

```python
genre_ids, has_explicit_genre_value = _project_genre_selection(project)
story_genre_ids = normalize_novel_type_ids(story.genre) if not has_explicit_genre_value else []
effective_genre_ids = genre_ids or story_genre_ids
```

Use it in `_sync_project_generation_context`:

```python
genre_ids, _ = _project_genre_selection(project)
primary_genre = genre_ids[0] if genre_ids else ""
```

- [ ] **Step 4: 运行同步和题材回归测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api/test_project_context_sync.py tests/story_core/test_novel_type_catalog.py tests/story_core/test_genre_plugins.py -q
```

Expected: 全部通过；未知显式类型不清理，旧网游保持，玄幻和仙侠正常清理旧游戏状态。

### Task 4: 审核有效文件并形成后端提交

**Files:**
- Stage: `packages/story_core/**`
- Stage: `apps/api/**`
- Stage: `scripts/**`
- Stage: `data/skill-packs/**`
- Stage: `tests/**`
- Exclude: `apps/api/data/**`

- [ ] **Step 1: 检查未跟踪文件中没有运行二进制**

Run:

```powershell
$unexpected = git ls-files --others --exclude-standard |
    Where-Object { $_ -match '\.(db|db-wal|db-shm|pack\.gz|hot-update\.js|pyc)$' }
if ($unexpected) { $unexpected; throw 'runtime artifacts remain unignored' }
```

Expected: 无输出。

- [ ] **Step 2: 编译后端并运行完整测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q apps/api packages/story_core scripts
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 编译成功；测试数量不低于整理前记录的 `853 passed`，不得出现失败。

- [ ] **Step 3: 暂存后端、产品 Skill 数据和全部对应测试**

Run:

```powershell
git add -- apps/api packages/story_core scripts data/skill-packs tests
git restore --staged -- apps/api/data 2>$null
git diff --cached --check
git diff --cached --stat
```

Expected: 暂存区不包含 `apps/api/data`、`.next-dev` 或前端文件；实现和测试同时存在。

- [ ] **Step 4: 提交后端工作流**

Run:

```powershell
git commit -m "feat: stabilize modular novel writing workflow"
```

Expected: 提交包含写作流程、API、Skill、题材插件、迁移工具和 Python 测试。

### Task 5: 审核并提交前端工作台

**Files:**
- Stage: `apps/web/**`
- Preserve deletion: `apps/web/components/ChapterBundleView.tsx`
- Include replacement: `apps/web/components/ws/SimplifiedReview.tsx`

- [ ] **Step 1: 确认 Next.js 构建目录设置成对存在**

Run:

```powershell
git diff -- apps/web/next.config.mjs apps/web/tsconfig.json
Select-String -Path apps/web/next.config.mjs -Pattern 'distDir'
Select-String -Path apps/web/tsconfig.json -Pattern '.next-dev/types'
```

Expected: 开发环境使用 `.next-dev`，TypeScript 同时包含 `.next` 和 `.next-dev` 类型目录；两项都保留。

- [ ] **Step 2: 运行生产构建**

Run:

```powershell
npm run build
```

Workdir: `apps/web`

Expected: Next.js 编译、类型检查和静态页面生成全部成功。

- [ ] **Step 3: 暂存并检查前端改动**

Run:

```powershell
git add -- apps/web
git diff --cached --check
git diff --cached --stat
git status --short apps/web/.next-dev
```

Expected: `.next-dev` 不出现；旧组件删除和新简化审稿组件同时暂存。

- [ ] **Step 4: 提交前端工作台**

Run:

```powershell
git commit -m "feat: organize the novel project workbench"
```

Expected: 只提交 `apps/web` 中的源码和配置。

### Task 6: 提交剩余文档并检查工作区

**Files:**
- Stage: `docs/superpowers/plans/2026-07-05-split-outline-world-characters.md`
- Stage: `docs/superpowers/plans/2026-07-11-simplified-chapter-review.md`

- [ ] **Step 1: 检查文档没有占位文本**

Run:

```powershell
rg -n "TBD|TODO|待定|现在无法访问编辑器" docs/superpowers/plans/2026-07-05-split-outline-world-characters.md docs/superpowers/plans/2026-07-11-simplified-chapter-review.md
```

Expected: 无输出；若命中，先删除无效编辑器提示或补齐内容。

- [ ] **Step 2: 提交历史设计计划**

Run:

```powershell
git add -- docs/superpowers/plans/2026-07-05-split-outline-world-characters.md docs/superpowers/plans/2026-07-11-simplified-chapter-review.md
git diff --cached --check
git commit -m "docs: archive novel workflow implementation plans"
```

Expected: 只提交两份有效计划文档。

- [ ] **Step 3: 检查剩余状态**

Run:

```powershell
git status --short
git ls-files --others --exclude-standard
```

Expected: 没有未归类源码、测试、文档或运行产物；若仍有文件，先按“源码、产品数据、文档、运行数据、缓存”分类，不直接删除未知文件。

### Task 7: 最终全链路验证

**Files:**
- Read: `$env:TEMP/xiaoshuofish-code-organization-baseline.json`
- Read: `apps/api/data/stories.db`

- [ ] **Step 1: 再次运行完整测试和前端构建**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm run build --prefix apps/web
```

Expected: Python 测试数量不低于 `853 passed`；前端生产构建成功。

- [ ] **Step 2: 验证小说正文哈希没有变化**

Run:

```powershell
@'
import hashlib
import json
from pathlib import Path

from apps.api.storage import SQLiteStoryStore

baseline_path = Path.home() / "AppData" / "Local" / "Temp" / "xiaoshuofish-code-organization-baseline.json"
baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
store = SQLiteStoryStore(r"D:\xiaoshuofish-flow-test\apps\api\data\stories.db")
project = store.get_project(baseline["project_id"])
assert project is not None and project.active_story_id == baseline["active_story_id"]
record = store.get(project.active_story_id)
assert record is not None
current = [
    {
        "chapter_number": bundle.chapter_number,
        "chapter_title": bundle.chapter_title,
        "body_chars": len(bundle.body),
        "sha256": hashlib.sha256(
            f"{bundle.chapter_title}\0{bundle.body}".encode("utf-8")
        ).hexdigest(),
    }
    for bundle in record.history
]
assert current == baseline["chapters"], (baseline["chapters"], current)
assert project.world_blueprint.get("genre_plugin_ids", []) == baseline["genre_plugin_ids"]
print(json.dumps(current, ensure_ascii=False, indent=2))
'@ | .\.venv\Scripts\python.exe -
```

Expected: 断言全部通过，章节数量、标题、字符数、正文 SHA-256 和项目类型与整理前一致。

- [ ] **Step 3: 重启服务并做真实接口检查**

Run:

```powershell
$apiListener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($apiListener) { Stop-Process -Id $apiListener.OwningProcess -Force }
$webListener = Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($webListener) { Stop-Process -Id $webListener.OwningProcess -Force }

Start-Process -FilePath '.\.venv\Scripts\python.exe' -ArgumentList '-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory 'D:\xiaoshuofish-flow-test' -WindowStyle Hidden
Start-Process -FilePath 'npm.cmd' -ArgumentList 'start','--','-p','3000' -WorkingDirectory 'D:\xiaoshuofish-flow-test\apps\web' -WindowStyle Hidden
Start-Sleep -Seconds 4

curl.exe -s -o NUL -w "api=%{http_code}`n" http://127.0.0.1:8000/health
curl.exe -s -o NUL -w "web=%{http_code}`n" 'http://localhost:3000/projects/p-xianxia-incense-test-2/write?chapter=1'
```

Expected: API 和项目页均返回 `200`。

- [ ] **Step 4: 输出最终提交和状态**

Run:

```powershell
git log --oneline -6
git status --short
```

Expected: 能看到工作区规则、后端、前端和文档提交；工作区为空或只剩已明确说明的本地文件。
