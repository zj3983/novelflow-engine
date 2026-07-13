# 东方幻想细分类型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将混合的“修仙玄幻”拆成共享东方幻想基础规则、东方玄幻和修仙仙侠，并把《我替宗门看守断香炉》无损迁移为东方玄幻。

**Architecture:** `eastern_fantasy` 是内部共享插件，不直接出现在页面选择器；选择 `xuanhuan` 或 `xianxia` 时，插件组装器自动加入共享插件。小说类型目录、非网游识别、项目到故事同步和前端选项分别保持单一职责，项目迁移通过可复用脚本完成并在写入前备份 SQLite。

**Tech Stack:** Python 3.11、Pydantic、FastAPI、SQLite、pytest、Next.js 14、TypeScript。

---

## 文件结构

- Create: `packages/story_core/genre_types/eastern_fantasy.py`：东方幻想共同规则和共同开篇模拟模板。
- Create: `packages/story_core/genre_types/xuanhuan.py`：东方玄幻专属承诺和禁写项。
- Modify: `packages/story_core/genre_types/xianxia.py`：只保留修仙仙侠差异，不再同时代表玄幻。
- Modify: `packages/story_core/genre_types/__init__.py`：导出三个东方幻想模块。
- Modify: `packages/story_core/novel_type_catalog.py`：增加玄幻选项并集中维护显式非网游类型判断。
- Modify: `packages/story_core/genre_plugins.py`：自动组装共享插件和细分插件。
- Modify: `packages/story_core/chapter_seed.py`、`packages/story_core/chapter_governance.py`、`packages/story_core/orchestrator.py`、`packages/story_core/web_game_review.py`：改用统一的非网游类型判断。
- Modify: `apps/api/storage.py`：用户修改显式类型后同步更新活跃故事类型。
- Modify: `apps/web/lib/novelTypes.ts`：显示东方玄幻和修仙仙侠两个选项。
- Create: `scripts/migrate_project_genre.py`：备份数据库、修复 GBK 误解码文本并迁移指定项目类型。
- Test: `tests/story_core/test_novel_type_catalog.py`、`tests/story_core/test_genre_plugins.py`、`tests/api/test_project_context_sync.py`、`tests/test_migrate_project_genre.py`。

### Task 1: 建立共享东方幻想与两个细分插件

**Files:**
- Create: `packages/story_core/genre_types/eastern_fantasy.py`
- Create: `packages/story_core/genre_types/xuanhuan.py`
- Modify: `packages/story_core/genre_types/xianxia.py`
- Modify: `packages/story_core/genre_types/__init__.py`
- Test: `tests/story_core/test_genre_plugins.py`

- [ ] **Step 1: 写共享规则和差异规则的失败测试**

```python
def test_xuanhuan_and_xianxia_share_eastern_fantasy_without_mixing_subtype_rules():
    xuanhuan = NovelProject(
        project_id="p-xuanhuan",
        title="断香炉",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    xianxia = NovelProject(
        project_id="p-xianxia-only",
        title="问道长生",
        world_blueprint={"genre_plugin_ids": ["xianxia"]},
    )

    xuanhuan_plugins = select_genre_plugins(xuanhuan)
    xianxia_plugins = select_genre_plugins(xianxia)

    assert [plugin.plugin_id for plugin in xuanhuan_plugins] == [
        "generic_webnovel", "eastern_fantasy", "xuanhuan"
    ]
    assert [plugin.plugin_id for plugin in xianxia_plugins] == [
        "generic_webnovel", "eastern_fantasy", "xianxia"
    ]
    assert "飞升" not in plugin_prompt_guide(xuanhuan_plugins)
    assert "武魂" not in plugin_prompt_guide(xianxia_plugins)
```

- [ ] **Step 2: 运行测试并确认缺少新插件**

Run: `python -m pytest tests/story_core/test_genre_plugins.py::test_xuanhuan_and_xianxia_share_eastern_fantasy_without_mixing_subtype_rules -q`

Expected: FAIL，`xuanhuan` 尚未注册或共享插件未加载。

- [ ] **Step 3: 创建共享基础插件**

在 `packages/story_core/genre_types/eastern_fantasy.py` 定义：

```python
EASTERN_FANTASY = GenrePlugin(
    plugin_id="eastern_fantasy",
    name="东方幻想基础",
    keywords=(),
    core_promises=(
        "力量成长必须有资源、门槛、风险或代价。",
        "宗门、家族、王朝和地方势力围绕资源、传承和地位作出反应。",
        "开篇机缘先给异常、线索或小反馈，不直接送完整传承。",
    ),
    ledger_fields=("境界", "力量", "功法", "资源", "宗门关系", "遗物线索"),
    rulebook={
        "progression_rules": ("境界、功法和资源必须前后一致，越阶需要明确凭依和代价。",),
        "economy_rules": ("修炼资源要体现稀缺度、势力控制和交换代价。",),
        "quest_rules": ("差事、试炼和秘境要有进入条件、竞争者、失败代价和阶段收获。",),
        "faction_rules": ("宗门、家族、王朝和地方势力按可见利益逐步反应。",),
        "panel_rules": ("力量信息通过感知、战斗、传承或鉴定自然呈现。",),
        "chapter_formula": ("低位处境、具体麻烦、核心物件、小反馈和章末新压力。",),
        "forbidden_breaks": ("禁止无代价顿悟、力量体系混乱和长辈无理由送核心资源。",),
    },
    quality_checks=("力量一致", "资源代价", "势力反馈", "机缘递进"),
)
```

将原 `XIANXIA_SIMULATION_BLUEPRINT` 中通用的低位差事、核心物件异常、小反馈和冲突阶梯迁移为 `EASTERN_FANTASY_SIMULATION_BLUEPRINT`。

- [ ] **Step 4: 创建东方玄幻专属插件**

在 `packages/story_core/genre_types/xuanhuan.py` 定义：

```python
XUANHUAN = GenrePlugin(
    plugin_id="xuanhuan",
    name="东方玄幻",
    keywords=("玄幻", "血脉", "体质", "武魂", "异火", "遗物", "古族"),
    core_promises=(
        "允许自创力量体系、异常物件、血脉、体质和古老遗物。",
        "长期拉力来自力量成长、资源争夺、势力竞争和世界秘密。",
    ),
    ledger_fields=("特殊体质", "血脉", "异常物件", "势力位阶", "世界秘密"),
    rulebook={
        "progression_rules": ("自创力量必须先说明可见反馈、升级条件和使用代价。",),
        "economy_rules": (),
        "quest_rules": (),
        "faction_rules": ("势力争夺围绕资源、遗物、血脉和地盘展开。",),
        "panel_rules": (),
        "chapter_formula": ("每章至少推进力量、资源、关系或世界秘密中的一项。",),
        "forbidden_breaks": ("不默认加入灵根、渡劫、飞升和长生求道。",),
    },
    quality_checks=("自创体系清楚", "异物反馈可见", "世界秘密递进"),
)
```

- [ ] **Step 5: 收窄仙侠插件并导出新模块**

将 `XIANXIA.name` 改为“修仙仙侠”，关键词保留灵根、修仙、道法、渡劫和飞升；专属规则只写修真境界、长生求道、道法因果和天劫飞升。更新 `genre_types/__init__.py` 导出 `EASTERN_FANTASY`、`EASTERN_FANTASY_SIMULATION_BLUEPRINT` 和 `XUANHUAN`。

- [ ] **Step 6: 运行插件测试**

Run: `python -m pytest tests/story_core/test_genre_plugins.py -q`

Expected: PASS。

- [ ] **Step 7: 提交插件拆分**

```powershell
git add packages/story_core/genre_types tests/story_core/test_genre_plugins.py
git commit -m "feat: split eastern fantasy genre plugins"
```

### Task 2: 更新类型目录和统一非网游判断

**Files:**
- Modify: `packages/story_core/novel_type_catalog.py`
- Modify: `packages/story_core/genre_plugins.py`
- Modify: `packages/story_core/chapter_seed.py`
- Modify: `packages/story_core/chapter_governance.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/web_game_review.py`
- Test: `tests/story_core/test_novel_type_catalog.py`

- [ ] **Step 1: 写类型目录和非网游识别失败测试**

```python
def test_catalog_separates_xuanhuan_and_xianxia():
    options = {item["id"]: item for item in novel_type_options()}
    assert options["xuanhuan"]["label"] == "东方玄幻"
    assert options["xianxia"]["label"] == "修仙仙侠"
    assert "飞升" not in options["xuanhuan"]["description"]
    assert "飞升" in options["xianxia"]["description"]


def test_xuanhuan_marker_is_explicitly_non_game():
    text = "小说类型：xuanhuan。故事里不写玩家、面板、背包和掉落。"
    assert has_explicit_non_game_type(text) is True
    assert is_game_genre(text) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/story_core/test_novel_type_catalog.py -q`

Expected: FAIL，目录中没有 `xuanhuan`，且统一判断函数不存在。

- [ ] **Step 3: 增加目录选项和统一判断函数**

在 `novel_type_catalog.py` 中：

```python
EXPLICIT_NON_GAME_TYPE_IDS = (
    "xuanhuan", "xianxia", "urban", "suspense", "romance", "rules_mystery", "generic_webnovel"
)


def has_explicit_non_game_type(text: str) -> bool:
    haystack = str(text or "")
    return any(
        re.search(rf"(?:^|[：:\s'\"\[,]){re.escape(plugin_id)}(?:$|[\s'\"\],。])", haystack)
        for plugin_id in EXPLICIT_NON_GAME_TYPE_IDS
    )
```

新增 `xuanhuan` 目录项；将 `xianxia` 标签从“修仙玄幻”改为“修仙仙侠”。

- [ ] **Step 4: 删除各模块重复的显式非网游标记列表**

让 `genre_plugins.is_game_genre`、`chapter_seed._is_game_story`、`chapter_governance`、`orchestrator` 和 `web_game_review` 调用 `has_explicit_non_game_type`。保留各模块自己的强网游证据判断，不改变网游项目逻辑。

- [ ] **Step 5: 更新插件选择和模拟模板组装**

显式选择 `xuanhuan` 时返回 `[GENERIC_WEBNOVEL, EASTERN_FANTASY, XUANHUAN]`；选择 `xianxia` 时返回 `[GENERIC_WEBNOVEL, EASTERN_FANTASY, XIANXIA]`。`plugin_simulation_blueprint` 返回共享模板的深拷贝，并将 `plugin_id` 设置为当前细分类型。

- [ ] **Step 6: 运行题材识别相关测试**

Run: `python -m pytest tests/story_core/test_novel_type_catalog.py tests/story_core/test_genre_plugins.py tests/story_core/test_game_identity.py -q`

Expected: PASS。

- [ ] **Step 7: 提交目录和识别修改**

```powershell
git add packages/story_core/novel_type_catalog.py packages/story_core/genre_plugins.py packages/story_core/chapter_seed.py packages/story_core/chapter_governance.py packages/story_core/orchestrator.py packages/story_core/web_game_review.py tests/story_core/test_novel_type_catalog.py tests/story_core/test_genre_plugins.py
git commit -m "feat: add xuanhuan novel type"
```

### Task 3: 让项目类型修改同步到活跃故事

**Files:**
- Modify: `apps/api/storage.py`
- Test: `tests/api/test_project_context_sync.py`

- [ ] **Step 1: 写已有历史时仍同步显式类型的失败测试**

```python
def test_project_context_updates_story_genre_after_user_changes_type():
    project = NovelProject(
        project_id="p-change-type",
        title="断香炉",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    story = StoryState(
        story_id="s-change-type",
        outline="林照看守断香炉。",
        genre="xianxia",
        style="白描、现代中文",
        current_chapter=1,
    )

    _sync_project_generation_context(story, project, has_history=True)

    assert story.genre == "xuanhuan"
    assert "小说类型：xuanhuan" in story.world_facts
```

- [ ] **Step 2: 运行测试确认当前故事仍为 xianxia**

Run: `python -m pytest tests/api/test_project_context_sync.py::test_project_context_updates_story_genre_after_user_changes_type -q`

Expected: FAIL，`story.genre == "xianxia"`。

- [ ] **Step 3: 修改同步规则**

在 `_sync_project_generation_context` 中，显式 `genre_plugin_ids` 始终是题材权威来源：

```python
if primary_genre:
    story.genre = primary_genre
    if first_generation or placeholder_style:
        story.style = _default_story_style_for_genre(primary_genre)
```

只同步 `genre`，已有历史时不覆盖真实大纲和用户风格。

- [ ] **Step 4: 运行上下文同步测试**

Run: `python -m pytest tests/api/test_project_context_sync.py -q`

Expected: PASS。

- [ ] **Step 5: 提交同步修改**

```powershell
git add apps/api/storage.py tests/api/test_project_context_sync.py
git commit -m "fix: sync explicit project genre to story"
```

### Task 4: 更新页面类型选项

**Files:**
- Modify: `apps/web/lib/novelTypes.ts`
- Test: `apps/web/lib/novelTypes.test.ts`（若当前前端未配置单测，则以 TypeScript 构建验证）

- [ ] **Step 1: 更新前端目录**

将原 `xianxia` 项替换为两个选项：

```typescript
{
  id: "xuanhuan",
  label: "东方玄幻",
  description: "自创力量、异物机缘、资源成长和世界秘密。",
},
{
  id: "xianxia",
  label: "修仙仙侠",
  description: "灵根修炼、道法因果、渡劫飞升和长生求道。",
},
```

- [ ] **Step 2: 运行前端生产构建**

Run: `npm run build`（工作目录 `apps/web`）

Expected: Next.js 编译、类型检查和静态页面生成全部成功。

- [ ] **Step 3: 提交页面选项**

```powershell
git add apps/web/lib/novelTypes.ts
git commit -m "feat: show xuanhuan and xianxia separately"
```

### Task 5: 迁移断香炉项目并修复乱码

**Files:**
- Create: `scripts/migrate_project_genre.py`
- Test: `tests/test_migrate_project_genre.py`

- [ ] **Step 1: 写递归乱码修复和无损迁移失败测试**

```python
def _fixture_store(tmp_path, *, body: str, genre_id: str) -> SQLiteStoryStore:
    store = SQLiteStoryStore(str(tmp_path / "stories.db"))
    initial = StoryState(
        story_id="s-incense",
        outline="林照看守断香炉。",
        genre=genre_id,
        style="白描、现代中文",
    )
    store.create(initial)
    store.create_project(
        NovelProject(
            project_id="p-incense",
            title="断香炉",
            active_story_id="s-incense",
            world_blueprint={"genre_plugin_ids": [genre_id]},
        )
    )
    updated = initial.model_copy(deep=True)
    updated.current_chapter = 1
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="祖祠守炉",
        body=body,
        next_outline="赵管事来清点祖祠。",
        updated_story=updated,
    )
    store.append_chapter_bundle("s-incense", bundle)
    return store


def test_repair_gbk_mojibake_recursively():
    value = {"summary": "ÁÖÕÕ¿´ÊØ¶ÏÏãÂ¯", "items": ["×ÚÃÅ", "正常中文"]}
    repaired = repair_gbk_mojibake(value)
    assert repaired == {"summary": "林照看守断香炉", "items": ["宗门", "正常中文"]}


def test_migration_preserves_chapter_body_and_switches_type(tmp_path):
    before_body = "林照接下祖祠守炉差事。"
    result = migrate_project_genre(
        store=_fixture_store(tmp_path, body=before_body, genre_id="xianxia"),
        project_id="p-incense",
        target_genre="xuanhuan",
        repair_mojibake=True,
    )
    assert result["before_body_sha256"] == result["after_body_sha256"]
    assert result["chapter_count"] == 1
    assert result["target_genre"] == "xuanhuan"
```

- [ ] **Step 2: 运行测试确认迁移工具不存在**

Run: `python -m pytest tests/test_migrate_project_genre.py -q`

Expected: FAIL，迁移模块尚未创建。

- [ ] **Step 3: 实现安全的递归乱码修复**

```python
def repair_gbk_mojibake(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: repair_gbk_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_gbk_mojibake(item) for item in value]
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin1").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired if any("\u4e00" <= char <= "\u9fff" for char in repaired) else value
```

工具只修复可逆的 Latin-1/GBK 误解码文本，正常中文保持原样。

- [ ] **Step 4: 实现带备份和正文哈希保护的项目迁移**

迁移顺序：

1. 使用 SQLite `Connection.backup` 创建 `data/backups/stories-before-genre-migration-<timestamp>.db`。
2. 读取项目、活跃故事和所有章节正文 SHA-256。
3. 递归修复 `world_blueprint`、`author_constraints`、`character_profiles`、`seed_outline`、`world_summary` 和 `current_focus`。
4. 设置 `world_blueprint.genre_plugin_ids = [target_genre]`。
5. 保存项目并调用 `sync_project_context`。
6. 再次计算章节正文 SHA-256；不一致时抛出异常并报告备份路径。
7. 输出迁移前后类型、章节数、正文哈希和备份路径。

- [ ] **Step 5: 运行迁移工具测试**

Run: `python -m pytest tests/test_migrate_project_genre.py -q`

Expected: PASS。

- [ ] **Step 6: 备份并迁移真实项目**

Run:

```powershell
python scripts/migrate_project_genre.py p-xianxia-incense-test-2 --target-genre xuanhuan --repair-gbk-mojibake
```

Expected:

- `target_genre` 为 `xuanhuan`。
- `chapter_count` 为 `1`。
- 迁移前后正文 SHA-256 相同。
- 输出可用的数据库备份路径。

- [ ] **Step 7: 提交迁移工具**

```powershell
git add scripts/migrate_project_genre.py tests/test_migrate_project_genre.py
git commit -m "feat: add safe project genre migration"
```

### Task 6: 全链路验证

**Files:**
- Test: `tests/story_core/test_novel_type_catalog.py`
- Test: `tests/story_core/test_genre_plugins.py`
- Test: `tests/api/test_project_context_sync.py`
- Test: `tests/api/test_story_routes.py`

- [ ] **Step 1: 运行完整 Python 测试**

Run: `python -m pytest -q`

Expected: 所有测试通过。

- [ ] **Step 2: 运行前端生产构建**

Run: `npm run build`（工作目录 `apps/web`）

Expected: 构建成功，无 TypeScript 错误。

- [ ] **Step 3: 重启 API 并检查真实项目**

检查：

```text
GET /projects/p-xianxia-incense-test-2
GET /projects/p-xianxia-incense-test-2/writing-packet?chapter_number=2
GET /projects/p-xianxia-incense-test-2/prompt-preview?chapter_number=2
GET /projects/p-xianxia-incense-test-2/agent-review?chapter_number=1&include_body=true
```

Expected:

- 项目 `genre_plugin_ids` 为 `xuanhuan`。
- 写作包 `story.genre` 为 `xuanhuan`。
- 世界事实包含 `小说类型：xuanhuan`。
- 提示词包含东方玄幻方法，不包含渡劫、飞升和长生求道默认要求。
- 第一章标题仍为《祖祠守炉》，正文字符数和 SHA-256 与迁移前一致。
- 项目配置、角色卡和页面没有乱码。

- [ ] **Step 4: 检查改动格式和工作区边界**

Run:

```powershell
git diff --check -- packages/story_core/genre_types packages/story_core/novel_type_catalog.py packages/story_core/genre_plugins.py packages/story_core/chapter_seed.py packages/story_core/chapter_governance.py packages/story_core/orchestrator.py packages/story_core/web_game_review.py apps/api/storage.py apps/web/lib/novelTypes.ts scripts/migrate_project_genre.py tests/story_core/test_novel_type_catalog.py tests/story_core/test_genre_plugins.py tests/api/test_project_context_sync.py tests/test_migrate_project_genre.py
```

Expected: 无格式错误；只处理本计划文件，不回退工作区中的其他用户改动。
