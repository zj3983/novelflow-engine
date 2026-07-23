# 《神域》世界体系实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将《神域》的世界背景、成长、经济、任务和现实桥接体系写入唯一结构化数据源，分别展示于工作台，并在生成章节时只读取本章相关模块。

**Architecture:** 继续以 `.webnovel/project.json.world_blueprint` 为规范数据源；`FileProjectStore.update_project()` 负责字段级合并，并把规范数据同步到 `MASTER_SETTING.json` 和带生成标记的设定集 Markdown。新增一个纯函数模块负责规则筛选与 Markdown 渲染，导演和写作包共用同一套相关性选择，不再把完整世界观传入每章。

**Tech Stack:** Python 3.11、Pydantic、FastAPI、Next.js 14、React 18、TypeScript、pytest、Playwright。

---

## 文件结构

- Create: `packages/story_core/world_blueprint_context.py`：世界蓝图字段定义、字段级合并、按章筛选和设定集 Markdown 渲染。
- Modify: `packages/story_core/file_project_store.py`：统一保存蓝图镜像、调用 Markdown 同步、构造相关写作上下文。
- Modify: `packages/story_core/orchestrator.py`：使用共用筛选函数，避免另一套关键词逻辑。
- Modify: `apps/web/components/ws/WorldRulesEditor.tsx`：将成长、经济、任务、现实桥接作为独立可见模块。
- Modify: `apps/web/app/projects/[id]/world/page.tsx`：修复页面标题乱码并保持模块顺序。
- Modify: `apps/web/tests/story-workbench.spec.ts`：验证模块显示、独立保存和并发刷新。
- Modify: `tests/story_core/test_file_project_store.py`：验证蓝图镜像、写作包范围和相关任务链。
- Create: `tests/story_core/test_world_blueprint_context.py`：验证纯函数的合并、筛选和 Markdown 输出。
- Runtime data: `data/exported-projects/p-gou-webgame-restored/**`：迁移当前作品，不纳入代码仓库提交。

### Task 1: 建立世界蓝图公共模块

**Files:**
- Create: `packages/story_core/world_blueprint_context.py`
- Create: `tests/story_core/test_world_blueprint_context.py`

- [ ] **Step 1: 写字段级合并失败测试**

```python
def test_merge_world_blueprint_preserves_unpatched_modules():
    current = {
        "premise": "旧背景",
        "economy_rules": ["匿名寄售"],
        "quest_network": {"active_chains": [{"name": "灰烬村"}]},
    }
    merged = merge_world_blueprint(current, {"premise": "新背景"})
    assert merged == {
        "premise": "新背景",
        "economy_rules": ["匿名寄售"],
        "quest_network": {"active_chains": [{"name": "灰烬村"}]},
    }
```

- [ ] **Step 2: 写按章筛选失败测试**

```python
def _complete_blueprint():
    return {
        "premise": "《神域》是全球同步运营的全感官虚拟现实网游。",
        "world_rules": ["游戏与现实同速", "六块开放大陆环绕中央封锁区"],
        "progression_rules": ["所有玩家从Lv.1见习者起步"],
        "economy_rules": ["交易行允许匿名寄售"],
        "quest_rules": ["普通任务无需前置任务"],
        "reality_bridge_rules": ["稀有资产可由持牌平台担保结算人民币"],
        "quest_network": {
            "active_chains": [{
                "name": "灰烬村异常链",
                "description": "从清道夫委托进入后坡巡查",
                "stages": [{"goal": "完成清道夫委托"}, {"goal": "巡查后坡"}],
            }],
        },
    }


def test_select_world_context_for_trade_chapter_keeps_economy_not_quest_chain():
    selected = select_world_context(
        _complete_blueprint(),
        "夜烬把裂纹狼心匿名寄售，等待现实担保结算。",
    )
    assert selected["economy_rules"]
    assert selected["reality_bridge_rules"]
    assert "quest_network" not in selected
    assert len(flatten_selected_rules(selected)) <= 8


def test_select_world_context_for_quest_chapter_keeps_matching_chain():
    selected = select_world_context(
        _complete_blueprint(),
        "完成清道夫委托后，守卫交出后坡巡查路线。",
    )
    chains = selected["quest_network"]["active_chains"]
    assert [chain["name"] for chain in chains] == ["灰烬村异常链"]
    assert selected["quest_rules"]
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_world_blueprint_context.py -q`

Expected: FAIL，提示 `packages.story_core.world_blueprint_context` 不存在。

- [ ] **Step 4: 实现公共模块**

```python
from copy import deepcopy


RULE_FIELDS = (
    "world_rules",
    "power_system",
    "progression_rules",
    "economy_rules",
    "quest_rules",
    "faction_rules",
    "panel_rules",
    "reality_bridge_rules",
)

RULE_KEYWORDS = {
    "power_system": ("等级", "职业", "技能", "装备", "怪物", "战斗"),
    "progression_rules": ("经验", "升级", "转职", "属性", "声望"),
    "economy_rules": ("铜币", "交易", "寄售", "价格", "材料", "修理", "药水"),
    "quest_rules": ("任务", "委托", "登记", "提交", "巡查", "前置"),
    "reality_bridge_rules": ("现实", "人民币", "到账", "担保", "身体"),
}

QUEST_KEYWORDS = ("任务", "委托", "巡查", "守卫", "提交", "奖励")


def _texts(value):
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _matches(text, keywords):
    return any(keyword in text for keyword in keywords)


def _chain_tokens(text):
    chinese = "".join(char for char in str(text) if "\u4e00" <= char <= "\u9fff")
    return tuple(dict.fromkeys(chinese[index:index + 2] for index in range(len(chinese) - 1)))


def merge_world_blueprint(current, patch):
    return {**(current if isinstance(current, dict) else {}), **(patch if isinstance(patch, dict) else {})}


def select_world_context(blueprint, relevance_text, *, max_rules=8):
    source = blueprint if isinstance(blueprint, dict) else {}
    text = str(relevance_text or "")
    selected = {}
    if source.get("premise"):
        selected["premise"] = str(source["premise"]).strip()

    remaining = max(0, int(max_rules))
    base_rules = _texts(source.get("world_rules"))[: min(2, remaining)]
    if base_rules:
        selected["world_rules"] = base_rules
        remaining -= len(base_rules)

    matched = {
        field: _texts(source.get(field))
        for field in RULE_FIELDS[1:]
        if _texts(source.get(field)) and _matches(text, RULE_KEYWORDS.get(field, ()))
    }
    for field, values in matched.items():
        if remaining == 0:
            break
        selected[field] = [values[0]]
        remaining -= 1
    offset = 1
    while remaining and any(len(values) > offset for values in matched.values()):
        for field, values in matched.items():
            if remaining == 0:
                break
            if len(values) > offset:
                selected[field].append(values[offset])
                remaining -= 1
        offset += 1

    if _matches(text, QUEST_KEYWORDS):
        network = source.get("quest_network") if isinstance(source.get("quest_network"), dict) else {}
        matching = []
        for chain in network.get("active_chains") or []:
            if not isinstance(chain, dict):
                continue
            searchable = " ".join(str(value) for value in chain.values())
            if any(token and token in text for token in _chain_tokens(searchable)):
                matching.append(deepcopy(chain))
        if matching:
            selected["quest_network"] = {"active_chains": matching}
    return selected


def flatten_selected_rules(selected):
    return [rule for field in RULE_FIELDS for rule in _texts(selected.get(field))]
```

`deepcopy` 从标准库导入，保证返回值不修改输入。任务链匹配只用于选择上下文，不改变任务状态。

- [ ] **Step 5: 运行测试并确认通过**

Run: `python -m pytest tests/story_core/test_world_blueprint_context.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add packages/story_core/world_blueprint_context.py tests/story_core/test_world_blueprint_context.py
git commit -m "feat: add scoped world blueprint context"
```

### Task 2: 统一世界蓝图保存与设定集同步

**Files:**
- Modify: `packages/story_core/world_blueprint_context.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `tests/story_core/test_world_blueprint_context.py`
- Modify: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: 写镜像保存失败测试**

```python
def _shenyu_blueprint():
    return {
        "premise": "《神域》是全球同步运营的全感官虚拟现实网游。",
        "world_rules": ["游戏与现实同速"],
        "power_system": ["初始武器与基础技能不等于正式职业"],
        "progression_rules": ["所有玩家统一为见习者，从Lv.1开始"],
        "economy_rules": ["交易行允许匿名寄售"],
        "quest_rules": ["普通任务无需前置任务"],
        "reality_bridge_rules": ["稀有资产可由持牌平台担保结算人民币"],
        "quest_network": {"active_chains": [{"name": "灰烬村异常链"}]},
    }


def test_update_project_mirrors_world_blueprint_without_overwriting_other_modules(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel", project={
        "project_id": "p-file",
        "title": "File Novel",
        "game_title": "神域",
        "active_story_id": "s-file",
        "world_blueprint": {"premise": "旧背景", "economy_rules": ["匿名寄售"]},
    })
    updated = store.update_project({"world_blueprint": {"premise": "新背景"}})
    master = json.loads((store.story_system_dir / "MASTER_SETTING.json").read_text("utf-8"))
    assert updated["world_blueprint"]["economy_rules"] == ["匿名寄售"]
    assert master["world_blueprint"] == updated["world_blueprint"]
```

- [ ] **Step 2: 写受管 Markdown 失败测试**

```python
def test_update_project_refreshes_managed_world_markdown(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    store.update_project({"world_blueprint": _shenyu_blueprint()})
    world_text = (store.root / "设定集" / "世界观.md").read_text("utf-8")
    power_text = (store.root / "设定集" / "力量体系.md").read_text("utf-8")
    assert world_text.startswith("<!-- managed: world-blueprint/v1 -->")
    assert "# 《神域》世界观" in world_text
    assert "## 经济体系" in world_text
    assert "## 任务体系" in world_text
    assert "所有玩家统一为见习者" in power_text
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_file_project_store.py -k "mirrors_world_blueprint or managed_world_markdown" -q`

Expected: FAIL，`MASTER_SETTING.json` 仍是旧蓝图，Markdown 未生成。

- [ ] **Step 4: 实现确定性 Markdown 渲染**

在 `world_blueprint_context.py` 增加：

```python
MANAGED_MARKER = "<!-- managed: world-blueprint/v1 -->"


def render_world_markdown(title: str, blueprint: dict) -> str:
    return "\n".join([
        MANAGED_MARKER,
        f"# 《{title}》世界观",
        "",
        "## 世界背景",
        str(blueprint.get("premise") or ""),
        _render_rule_section("世界规则", blueprint.get("world_rules")),
        _render_rule_section("经济体系", blueprint.get("economy_rules")),
        _render_rule_section("任务体系", blueprint.get("quest_rules")),
        _render_quest_network(blueprint.get("quest_network")),
        _render_rule_section("现实桥接", blueprint.get("reality_bridge_rules")),
    ]).rstrip() + "\n"
```

`render_power_markdown()` 单独输出成长阶段、战斗边界、职业与面板规则。同步函数只自动覆盖带 `MANAGED_MARKER` 的文件；首次迁移当前项目时使用 `force=True` 接管旧文件。

- [ ] **Step 5: 在 `FileProjectStore.update_project()` 统一保存**

用 `merge_world_blueprint()` 替换当前顶层展开逻辑。写入 `project.json` 后，将同一蓝图写入 `MASTER_SETTING.json.world_blueprint`，再调用：

```python
sync_world_markdown(
    self.root,
    title=str(project.get("game_title") or "神域"),
    blueprint=world_blueprint,
)
```

同步失败记录 warning，但不得回滚已经验证通过的 JSON 保存。

- [ ] **Step 6: 运行相关测试**

Run: `python -m pytest tests/story_core/test_world_blueprint_context.py tests/story_core/test_file_project_store.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add packages/story_core/world_blueprint_context.py packages/story_core/file_project_store.py tests/story_core/test_world_blueprint_context.py tests/story_core/test_file_project_store.py
git commit -m "feat: synchronize world blueprint sources"
```

### Task 3: 让导演和写手只读取本章相关体系

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `tests/story_core/test_file_project_store.py`
- Modify: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: 写写作包范围失败测试**

先在 `tests/story_core/test_file_project_store.py` 增加明确的测试辅助函数：

```python
def _store_with_shenyu_blueprint(tmp_path, *, chapter_goal="匿名寄售材料并等待现实担保结算"):
    project = {
        "project_id": "p-shenyu",
        "title": "苟在网游里成神",
        "game_title": "神域",
        "active_story_id": "s-shenyu",
        "world_blueprint": _shenyu_blueprint(),
        "detailed_outline": [{"chapter": 1, "title": "第一笔交易", "chapter_goal": chapter_goal}],
    }
    return _make_minimal_file_project(tmp_path / "shenyu", project=project)
```

```python
def test_trade_chapter_writing_packet_only_includes_relevant_world_modules(tmp_path):
    store = _store_with_shenyu_blueprint(tmp_path)
    packet = store.writing_packet(chapter_number=1)
    blueprint = packet["project"]["world_blueprint"]
    assert blueprint["economy_rules"]
    assert blueprint["reality_bridge_rules"]
    assert "quest_network" not in blueprint
    assert "server_runtime" not in blueprint


def test_quest_chapter_writing_packet_includes_matching_chain(tmp_path):
    store = _store_with_shenyu_blueprint(tmp_path, chapter_goal="提交清道夫委托，开启后坡巡查")
    packet = store.writing_packet(chapter_number=2)
    chains = packet["project"]["world_blueprint"]["quest_network"]["active_chains"]
    assert [item["name"] for item in chains] == ["灰烬村异常链"]
```

- [ ] **Step 2: 写导演上下文失败测试**

```python
def test_director_story_payload_contains_progression_and_scoped_quest_context(tmp_path):
    store = _store_with_shenyu_blueprint(tmp_path, chapter_goal="提交清道夫委托，开启后坡巡查")
    state = store.state()
    project = store.project()
    payload = store._story_state_payload_for_direction(state, project, 1)
    assert payload["world_context"]["progression_rules"]
    assert payload["world_context"]["quest_network"]["active_chains"][0]["name"] == "灰烬村异常链"
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_file_project_store.py tests/story_core/test_writer_prompt_method.py -k "relevant_world_modules or matching_chain or scoped_quest_context" -q`

Expected: FAIL，当前写作包仍保留完整蓝图，导演载荷缺少 `progression_rules`。

- [ ] **Step 4: 接入公共筛选函数**

在 `_story_state_payload_for_direction()` 和 `writing_packet()` 中，用章节大纲、场景卡和当前焦点拼成 `relevance_text`，调用：

```python
scoped_world = select_world_context(world_blueprint, relevance_text, max_rules=8)
story_payload["world_context"] = scoped_world
packet_project["world_blueprint"] = scoped_world
```

删除写作包中“复制完整蓝图后逐个 `pop`”的逻辑。`outline_constraints` 只保留大纲治理字段，不重复附加整套经济与任务规则。

在 `orchestrator.py` 中让 `_compact_world_context_for_prompt()` 消费已经筛好的字段，仅做字符压缩和最终八条上限，不再维护第二套关键词表。

- [ ] **Step 5: 运行相关测试**

Run: `python -m pytest tests/story_core/test_file_project_store.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_orchestrator.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add packages/story_core/file_project_store.py packages/story_core/orchestrator.py tests/story_core/test_file_project_store.py tests/story_core/test_writer_prompt_method.py
git commit -m "feat: scope world context by chapter"
```

### Task 4: 整理世界观页面模块

**Files:**
- Modify: `apps/web/components/ws/WorldRulesEditor.tsx`
- Modify: `apps/web/app/projects/[id]/world/page.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: 更新组件测试预期**

```typescript
expect(WORLD_RULE_EDITOR_SECTIONS.map((section) => section.title)).toEqual([
  "基础规则",
  "成长体系",
  "经济体系",
  "任务体系",
  "阵营与面板",
  "游戏影响现实",
  "世界硬约束",
]);
```

添加页面测试，要求标题和顺序为：世界背景、基础规则、成长体系、经济体系、任务体系、阵营与面板、游戏影响现实、世界硬约束、地点与阵营、怪物图鉴、已确认事实。

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm.cmd run test:e2e -- --grep "世界背景与分类规则编辑器|世界观页面"`

Working directory: `apps/web`

Expected: FAIL，当前“任务与经济”仍合并显示，页面标题存在乱码。

- [ ] **Step 3: 调整分组与页面文字**

将 `WORLD_RULE_EDITOR_SECTIONS` 改为独立模块：

```typescript
{ id: "progression", title: "成长体系", fields: [
  { field: "power_system", label: "等级、职业与技能", buttonLabel: "保存力量体系" },
  { field: "progression_rules", label: "成长与战斗边界", buttonLabel: "保存成长规则" },
] },
{ id: "economy", title: "经济体系", fields: [
  { field: "economy_rules", label: "货币、价格与交易", buttonLabel: "保存经济体系" },
] },
{ id: "quest", title: "任务体系", fields: [
  { field: "quest_rules", label: "任务类型、状态与奖励", buttonLabel: "保存任务体系" },
] },
```

修复 `world/page.tsx` 的 UTF-8 标题、面包屑、错误文字和副标题。保持现有独立保存行为，不增加新的整页保存按钮。

- [ ] **Step 4: 运行测试与生产构建**

Run: `npm.cmd run test:e2e -- --grep "世界背景与分类规则编辑器|世界观页面"`

Expected: PASS。

Run: `npm.cmd run build`

Working directory: `apps/web`

Expected: Next.js production build exit 0。

- [ ] **Step 5: 提交**

```powershell
git add apps/web/components/ws/WorldRulesEditor.tsx apps/web/app/projects/[id]/world/page.tsx apps/web/tests/story-workbench.spec.ts
git commit -m "feat: separate world system editors"
```

### Task 5: 迁移当前《神域》项目

**Files:**
- Runtime update: `data/exported-projects/p-gou-webgame-restored/.webnovel/project.json`
- Runtime update: `data/exported-projects/p-gou-webgame-restored/.story-system/MASTER_SETTING.json`
- Runtime update: `data/exported-projects/p-gou-webgame-restored/设定集/世界观.md`
- Runtime update: `data/exported-projects/p-gou-webgame-restored/设定集/力量体系.md`
- Runtime update: 当前大纲、非归档章节和状态事实中仍在生效的游戏名称与旧规则。

- [ ] **Step 1: 通过项目更新接口写入确认后的蓝图**

蓝图至少包含：

```json
{
  "premise": "《神域》是全球同步运营的全感官虚拟现实网游。灰烬村属于东部大陆旧商路边缘，游戏与现实的真实关系在前期保持未知。",
  "progression_rules": [
    "所有玩家以Lv.1见习者开局，初始武器和基础技能不等于正式职业。",
    "Lv.10完成职业任务后获得正式职业，Lv.30形成职业分支，Lv.60以后进入传承路线。",
    "怪物高出三级及以上默认不能正常单杀，例外必须有已建立的组队、克制、装备、机关或残血条件。"
  ],
  "economy_rules": [
    "交易行默认匿名寄售，不显示卖家ID；买家关注抢货、价格和用途，不能追查普通订单来源。",
    "普通任务奖励以经验为主，10至30铜币只够新手补给；价格随供需和开服进度变化。",
    "稀有虚拟资产可经许可担保平台匿名交割并结算人民币，平台内部保留实名记录。"
  ],
  "quest_rules": [
    "普通任务可直接接取，不要求前置任务；只有任务链后续、职业任务和少数地区内容检查前置。",
    "任务状态为发现、接取、执行、可提交、完成或失败；未登记任务不能直接提交。",
    "新手任务主要奖励经验、补给、声望、服务或后续任务资格。"
  ]
}
```

同时写入“灰烬村异常链”的 `quest_network.active_chains`，以及游戏影响现实的分阶段 `reality_bridge_rules`。

迁移数据必须逐项覆盖设计文档中的已确认内容，不能只写上面示例里的最低字段：六块开放大陆与中央封锁区、八百年断层、界碑、游戏与现实一比一时间；`100铜币=1银币`、`100银币=1金币`、价格锚点、匿名交易和关注升级条件；普通/重复/任务链/区域/职业/动态/隐藏任务及状态流转；怪物观察面板；Lv.10、Lv.30、Lv.60成长阶段；游戏能力进入现实的前中后期揭示节奏。

- [ ] **Step 2: 接管并重建设定集 Markdown**

调用 `sync_world_markdown(..., force=True)`，确认旧版灰鼠坡、旧交易预警阈值和“官方无现实渠道”被新的受管文档替换。

- [ ] **Step 3: 清理当前有效内容中的旧称和冲突**

只处理当前大纲、当前章节、`project.json`、`state.json` 和 `MASTER_SETTING.json`；不改 `归档-旧正文`、历史 commit 和 generation-job 日志。

Run:

```powershell
rg -n "天启之门|灰鼠坡|元素法师学徒|官方无任何现实货币兑换渠道|单次出售.*10份|公会.*追查卖家" data/exported-projects/p-gou-webgame-restored/.webnovel data/exported-projects/p-gou-webgame-restored/.story-system/MASTER_SETTING.json data/exported-projects/p-gou-webgame-restored/chapters data/exported-projects/p-gou-webgame-restored/大纲 data/exported-projects/p-gou-webgame-restored/设定集
```

Expected: 当前有效文件中 0 个命中；排除目录不参与检查。

- [ ] **Step 4: 验证项目接口和第一章写作包**

Run: `Invoke-RestMethod http://127.0.0.1:8000/file-projects/file%3Ap-gou-webgame-restored`

Expected: `world_blueprint.premise` 包含《神域》，独立返回成长、经济、任务和现实桥接模块。

Run: `python scripts/novel_agent.py writing-packet file:p-gou-webgame-restored --chapter-number 1`

Expected: 第一章写作包出现《神域》、见习者、匿名交易与现实担保规则；不出现灰鼠坡、元素法师学徒或卖少量材料引来公会追查。

当前作品数据被 `.gitignore` 排除，不创建代码提交；在最终结果中单独说明已迁移本地项目。

### Task 6: 全量验证

**Files:**
- Verify only.

- [ ] **Step 1: 运行 Python 全量测试**

Run: `python -m pytest -q`

Expected: 全部测试通过，0 failed。

- [ ] **Step 2: 运行前端生产构建**

Run: `npm.cmd run build`

Working directory: `apps/web`

Expected: 编译、类型检查和静态页面生成全部成功。

- [ ] **Step 3: 检查工作区与格式**

Run: `git diff --check`

Expected: 无输出，exit 0。

Run: `git status --short`

Expected: 无未提交代码改动；被忽略的本地作品数据不显示。
