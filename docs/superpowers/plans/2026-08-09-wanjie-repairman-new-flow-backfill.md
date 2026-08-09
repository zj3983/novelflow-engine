# 《万界维修工：从家电到仙器》新流程补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改现有 147 章正文的前提下，从章节证据重建本书的新流程资料，并验证第 148 章写作上下文。

**Architecture:** 新增一个可复用的长篇项目回填服务：先对章节 JSON 与 Markdown 建立只读证据索引，再分层生成核心、总纲、世界观、角色、关系、伏笔和连续性补丁。所有补丁先写入预览文件并校验，确认章节文件哈希不变后再通过 `FileProjectStore` 原子落盘。

**Tech Stack:** Python 3.11、Pydantic、`FileProjectStore`、现有模型网关、pytest。

---

### Task 1: 建立只读章节证据索引

**Files:**
- Create: `packages/story_core/project_backfill.py`
- Test: `tests/story_core/test_project_backfill.py`

- [ ] **Step 1: 写失败测试，要求完整读取章节且记录正文哈希**

```python
def test_build_evidence_index_reads_every_chapter_without_mutation(project_root):
    before = chapter_hashes(project_root)
    index = build_evidence_index(project_root)
    assert [item.chapter_number for item in index.chapters] == [1, 2, 3]
    assert all(item.title and item.body_hash for item in index.chapters)
    assert chapter_hashes(project_root) == before
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_project_backfill.py::test_build_evidence_index_reads_every_chapter_without_mutation -q`

Expected: FAIL，提示 `build_evidence_index` 尚未定义。

- [ ] **Step 3: 实现证据索引**

```python
@dataclass(frozen=True)
class ChapterEvidence:
    chapter_number: int
    title: str
    body_hash: str
    body: str
    summary: str
    timeline: tuple[dict[str, Any], ...]
    character_updates: tuple[dict[str, Any], ...]
    foreshadowing: tuple[dict[str, Any], ...]

def build_evidence_index(project_root: Path) -> ProjectEvidenceIndex:
    store = FileProjectStore(project_root)
    chapters = tuple(_chapter_evidence(store, number) for number in store.chapter_numbers())
    return ProjectEvidenceIndex(project_root=project_root, chapters=chapters)
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `python -m pytest tests/story_core/test_project_backfill.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add packages/story_core/project_backfill.py tests/story_core/test_project_backfill.py
git commit -m "feat: index longform project evidence"
```

### Task 2: 生成分层回填补丁

**Files:**
- Modify: `packages/story_core/project_backfill.py`
- Test: `tests/story_core/test_project_backfill.py`

- [ ] **Step 1: 写失败测试，约束正文事实优先和题材隔离**

```python
def test_build_backfill_patch_uses_chapter_facts_and_excludes_game_fields(evidence):
    patch = build_backfill_patch(evidence, generated_payload())
    assert patch.story_core.logline
    assert patch.master_outline.volumes
    assert patch.continuity.current_chapter == 147
    assert "game_panel" not in json.dumps(patch.model_dump(), ensure_ascii=False)
    assert patch.characters["林修"].current_state
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_project_backfill.py::test_build_backfill_patch_uses_chapter_facts_and_excludes_game_fields -q`

Expected: FAIL，提示补丁构建器尚未定义。

- [ ] **Step 3: 实现七个互不混写的补丁分区**

```python
class ProjectBackfillPatch(BaseModel):
    story_core: StoryCoreCard
    master_outline: dict[str, Any]
    world_blueprint: dict[str, Any]
    characters: dict[str, dict[str, Any]]
    relationships: list[dict[str, Any]]
    foreshadowing: list[dict[str, Any]]
    continuity: dict[str, Any]

def build_backfill_patch(index, generated):
    payload = ProjectBackfillPatch.model_validate(generated)
    payload = enforce_chapter_evidence(payload, index)
    payload = strip_genre_foreign_fields(payload, genre="玄幻修仙")
    return payload
```

- [ ] **Step 4: 增加角色归并测试**

```python
def test_character_merge_keeps_aliases_but_rejects_non_character_entities(evidence):
    patch = build_backfill_patch(evidence, generated_with_duplicates())
    assert "林修" in patch.characters
    assert "白河仓库收购方" not in patch.characters
    assert patch.characters["林修"]["aliases"] == ["林师傅"]
```

- [ ] **Step 5: 运行测试并提交**

Run: `python -m pytest tests/story_core/test_project_backfill.py -q`

Expected: PASS。

```powershell
git add packages/story_core/project_backfill.py tests/story_core/test_project_backfill.py
git commit -m "feat: build evidence constrained project backfill"
```

### Task 3: 增加预览、备份和原子应用命令

**Files:**
- Create: `scripts/backfill_longform_project.py`
- Modify: `packages/story_core/project_backfill.py`
- Test: `tests/test_backfill_longform_project.py`

- [ ] **Step 1: 写失败测试，要求默认仅预览**

```python
def test_cli_defaults_to_preview_and_preserves_project(tmp_project):
    before = snapshot_project(tmp_project)
    assert main([str(tmp_project)]) == 0
    assert (tmp_project / ".story-system" / "backfill-preview.json").exists()
    assert snapshot_project(tmp_project, exclude_preview=True) == before
```

- [ ] **Step 2: 写失败测试，要求应用前备份并验证章节哈希**

```python
def test_apply_backs_up_and_rejects_chapter_mutation(tmp_project, monkeypatch):
    monkeypatch.setattr(backfill, "chapter_hashes", changing_hashes())
    with pytest.raises(BackfillConflict, match="chapter_hash_changed"):
        main([str(tmp_project), "--apply"])
```

- [ ] **Step 3: 实现命令入口**

```python
def main(argv=None) -> int:
    args = parser().parse_args(argv)
    index = build_evidence_index(args.project_root)
    patch = generate_backfill_patch(index)
    write_preview(args.project_root, patch)
    if args.apply:
        backup_project_metadata(args.project_root)
        apply_backfill_patch(args.project_root, patch, expected_hashes=index.chapter_hashes)
    return 0
```

- [ ] **Step 4: 运行测试并提交**

Run: `python -m pytest tests/test_backfill_longform_project.py tests/story_core/test_project_backfill.py -q`

Expected: PASS。

```powershell
git add scripts/backfill_longform_project.py packages/story_core/project_backfill.py tests/test_backfill_longform_project.py tests/story_core/test_project_backfill.py
git commit -m "feat: add safe longform backfill command"
```

### Task 4: 预览并人工核对本书补全结果

**Files:**
- Generate: `data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0/.story-system/backfill-preview.json`

- [ ] **Step 1: 记录147章正文哈希基线**

Run: `python scripts/backfill_longform_project.py data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0 --hash-only`

Expected: 输出 `147 chapters indexed` 和总哈希。

- [ ] **Step 2: 生成预览补丁**

Run: `python scripts/backfill_longform_project.py data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0`

Expected: 生成预览，项目正式资料未变化。

- [ ] **Step 3: 检查关键内容**

Run: `python scripts/backfill_longform_project.py data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0 --check-preview`

Expected: 主角为林修；当前章为147；摘要覆盖1至147章；没有网游字段；人物、物品、势力没有相互误判；开放伏笔均有首次出现章和最近触碰章。

- [ ] **Step 4: 应用补丁**

Run: `python scripts/backfill_longform_project.py data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0 --apply`

Expected: 元数据原子更新，147章正文哈希保持不变。

### Task 5: 验证页面与第148章写作包

**Files:**
- Verify: `data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0/.webnovel/project.json`
- Verify: `data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0/.webnovel/outline.json`
- Verify: `data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0/.webnovel/state.json`

- [ ] **Step 1: 运行项目回归测试**

Run: `python -m pytest tests/story_core/test_project_backfill.py tests/test_backfill_longform_project.py tests/story_core/test_file_project_store.py tests/story_core/test_modular_pipeline_e2e.py -q`

Expected: PASS。

- [ ] **Step 2: 检查工作台页面**

打开：`http://127.0.0.1:3000/projects/file%3Ap-da2c16a6ee9440d6ad52cb402ead88a0/outline`

Expected: 可见故事核心、总纲、分卷大纲；世界观、角色、关系和伏笔页面均有本书内容。

- [ ] **Step 3: 生成第148章上下文预览**

Run: `Invoke-RestMethod http://127.0.0.1:8000/file-projects/file%3Ap-da2c16a6ee9440d6ad52cb402ead88a0/writing-packet?chapter_number=148`

Expected: 读取当前卷、相关角色、未解伏笔和第147章连续性；不加载网游规则；不重复灌入147章全文。

- [ ] **Step 4: 最终核对正文未变**

Run: `python scripts/backfill_longform_project.py data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0 --verify-hashes`

Expected: `147/147 chapter hashes unchanged`。
