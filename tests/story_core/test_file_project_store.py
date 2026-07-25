import json
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest

from packages.story_core.file_project_store import (
    FileProjectStore,
    _chapter_outline_title,
    _regeneration_quality_blocking,
)
from packages.story_core.models import ChapterSummary, StoryState, TimelineEvent
from packages.story_core.outline_planning import GeneratedOutlinePlan
from packages.story_core.skill_packs import import_skill_pack_from_path
from packages.story_core.orchestrator import _failed_bundle
from packages.story_core.world_blueprint_context import flatten_selected_rules


def _long_test_body(label: str = "Night Ember keeps the chapter grounded.") -> str:
    unit = label + " He checks the task, pays a visible cost, gains a result, and leaves a next step.\n"
    unit_chars = max(1, len("".join(unit.split())))
    return unit * max(1, 4500 // unit_chars)


def test_first_chapter_regeneration_removes_post_chapter_character_states(tmp_path):
    store = FileProjectStore(tmp_path)
    reset = store._reset_first_chapter_regeneration_state(
        {
            "current_chapter": 1,
            "characters": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "game_id": "夜烬",
                    "real_state": {"current": {"balance": "312.60元"}},
                    "game_state": {"current": {"level": "Lv.1"}},
                    "memory": ["现实急账已在第一章解决，余额312.60元。"],
                }
            ],
        }
    )

    protagonist = reset["characters"][0]
    assert "real_state" not in protagonist
    assert "game_state" not in protagonist
    assert not any("312.60元" in item for item in protagonist["memory"])


def test_chapter_outline_title_uses_matching_detailed_outline_title():
    outline_context = {
        "chapter": {
            "chapter_number": 1,
            "title": "灰狼坡的第一笔到账",
        }
    }

    assert _chapter_outline_title(outline_context, 1) == "灰狼坡的第一笔到账"
    assert _chapter_outline_title(outline_context, 2) is None


def test_regeneration_gate_treats_prose_and_scene_feedback_as_advisory():
    writing_review = {
        "issues": [
            "第一章外部压力过早：公会信息提前介入。",
            "场景卡必写内容缺失：缺少现实职业/技能来源。",
            "现代中文对话不自然：存在清单式短句。",
        ],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }

    assert _regeneration_quality_blocking({"issues": ["writing_review"]}, writing_review) is False


def test_regeneration_gate_does_not_let_heuristic_critical_review_override_simplified_gate():
    writing_review = {
        "issues": ["首次与怪物交战前缺少简洁怪物面板。"],
        "critical_review": {
            "hard_issues": ["首次与怪物交战前缺少简洁怪物面板。"],
            "severity_summary": {"has_hard_violation": True},
        },
    }

    assert _regeneration_quality_blocking({"issues": ["writing_review"]}, writing_review) is False


def _make_minimal_file_project(root, *, state=None, project=None):
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": project or {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(project or {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(state or {"story_id": "s-file", "current_chapter": 0, "world_facts": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return FileProjectStore(root)


def _file_snapshot(root) -> dict:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _planning_card(name: str, tier: str, *, age: int = 30) -> dict:
    return {
        "name": name,
        "role": tier,
        "character_tier": tier,
        "first_appearance": 0 if tier == "long_term_antagonist" else 1,
        "identity_profile": {
            "age": age,
            "origin": "青石镇",
            "current_identity": "宗门中人",
            "occupation": "处理宗门差事",
        },
        "background_profile": {},
        "current_life_profile": {},
        "story_drive": {"immediate_goal": "控制祖祠", "failure_stakes": "失去位置"},
        "performance_profile": {},
        "dialogue_examples": ["先把事情说清楚。", "这件事要按规矩处理。"],
        "relationship_notes": [],
    }


def _generated_opening_plan() -> GeneratedOutlinePlan:
    return GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "overall": {
                    "story": "林照追查祖祠旧案。",
                    "protagonist_goal": "查清旧案。",
                    "main_conflict": "有人销毁证据。",
                    "growth_path": "逐步取得调查旧档的权力。",
                    "ending_direction": "旧案公开。",
                    "primary_trope_id": "low_status_reversal",
                },
                "arcs": [
                    {
                        "id": "opening",
                        "title": "祖祠旧案",
                        "start_chapter": 1,
                        "end_chapter": 10,
                        "goal": "找到换名册的人",
                        "obstacle": "赵衡控制清点权",
                        "payoff": "取得查档资格",
                        "trope_id": "low_status_reversal",
                        "end_state": "祖祠不再由赵衡独占",
                        "stage_antagonist": "赵衡",
                        "long_term_antagonist_traces": ["旧名册被换过"],
                    }
                ],
                "chapters": [
                    {
                        "chapter_number": number,
                        "title": f"第{number}步",
                        "goal": "查清祖祠异动",
                        "obstacle": "赵衡阻拦",
                        "action": "林照留下证据",
                        "turn": "旧名册出现矛盾",
                        "payoff": "得到可验证线索",
                        "ending_hook": "有人提前来过",
                        "trope_beat": "低位压力" if number == 1 else None,
                        "cast": ["林照", "赵衡"],
                    }
                    for number in range(1, 31)
                ],
            },
            "characters": [
                _planning_card("林照", "protagonist", age=19),
                _planning_card("赵衡", "stage_antagonist"),
                _planning_card("周满", "supporting"),
                _planning_card("顾长老", "long_term_antagonist"),
            ],
        }
    )


def _shenyu_world_blueprint() -> dict:
    return {
        "premise": "神域中的稀缺资源可以通过受限渠道影响现实生活。",
        "world_rules": ["世界规则一。", "世界规则二。"],
        "power_system": ["转职必须满足等级与技能条件。"],
        "progression_rules": ["升级必须来自可验证经验。", "转职必须留下职业记录。"],
        "economy_rules": ["交易价格取决于真实稀缺性。", "寄售必须支付手续费。"],
        "quest_rules": ["委托必须先登记再提交。", "巡查任务必须记录路线。"],
        "reality_bridge_rules": ["现实到账必须经过官方结算。", "房租支付必须保留账单。"],
        "quest_network": {
            "active_chains": [
                {
                    "name": "灰烬村异常链",
                    "stages": ["提交清道夫委托", "开启后坡巡查"],
                },
                {
                    "name": "黑水沼泽异常链",
                    "stages": ["提交毒腺委托", "调查黑水沼泽"],
                },
            ]
        },
        "locations": [{"name": "灰烬村"}, {"name": "黑水沼泽"}],
        "factions": [{"name": "灰烬村守卫队"}, {"name": "沼泽猎团"}],
        "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
        "server_runtime": {"online": True},
        "current_arc": "开服篇",
        "opening_arc": {"goal": "完成开服验证"},
        "volume_plan": {"volume_title": "新手村"},
        "longform_framework": {"progression_ladder": ["Lv.1-5"]},
        "chapter_formula": ["目标-代价-收益-钩子"],
        "forbidden_breaks": ["不得跳过章节大纲。"],
    }


def _store_with_shenyu_world(
    tmp_path,
    *,
    chapter_number: int,
    chapter_update: dict,
    current_chapter: int = 0,
    current_focus: str = "",
) -> FileProjectStore:
    project = {
        "project_id": "p-shenyu",
        "title": "苟在网游里成神",
        "active_story_id": "s-shenyu",
        "current_focus": current_focus,
        "world_blueprint": _shenyu_world_blueprint(),
    }
    state = {
        "story_id": "s-shenyu",
        "current_chapter": current_chapter,
        "current_focus": current_focus,
        "world_facts": [],
    }
    store = _make_minimal_file_project(tmp_path / "shenyu", project=project, state=state)
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][chapter_number - 1].update(chapter_update)
    (store.webnovel_dir / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False),
        encoding="utf-8",
    )
    return store


def test_save_generated_plan_updates_outline_project_and_state_together(tmp_path):
    root = tmp_path / "novel"
    project = {
        "project_id": "p-file",
        "title": "断香炉",
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "character_profiles": [
            {"name": "林照", "role": "protagonist", "identity_profile": {"age": 21, "occupation": "守祠杂役"}}
        ],
    }
    state = {"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": []}
    store = _make_minimal_file_project(root, project=project, state=state)

    saved = store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")

    assert saved["outline"]["chapters"][0]["chapter_number"] == 1
    assert store.project()["pipeline_stage"] == "world_ready"
    assert store.project()["character_profiles"][0]["identity_profile"]["age"] == 21
    assert store.project()["character_profiles"][0]["identity_profile"]["occupation"] == "守祠杂役"
    assert store.state()["characters"][0]["identity_profile"]["age"] == 21
    assert list((root / ".story-system" / "plans").glob("*-initial.json"))


def test_save_generated_plan_revalidates_tropes_before_writes(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "Fake Trope Bypass",
            "active_story_id": "s-file",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    payload = _generated_opening_plan().model_dump(mode="json")
    payload["outline"]["overall"]["primary_trope_id"] = "not-a-candidate"
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^invalid_primary_trope_id$"):
        store.save_generated_outline_plan(GeneratedOutlinePlan.model_validate(payload), mode="initial")

    assert _file_snapshot(root) == before


def test_save_initial_allows_generated_primary_when_no_existing_lock(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "Direct Initial",
            "active_story_id": "s-file",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )

    saved = store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")

    assert saved["outline"]["overall"]["primary_trope_id"] == "low_status_reversal"
    assert saved["outline"]["arcs"][0]["trope_id"] == "low_status_reversal"


def test_save_generated_plan_builds_canonical_relationship_graph(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    payload = _generated_opening_plan().model_dump(mode="json")
    payload["characters"][0]["relationship_notes"] = [
        {
            "target": payload["characters"][1]["name"],
            "relation_type": "上下级",
            "current_attitude": "彼此提防",
            "shared_interest_or_conflict": "旧名册",
        }
    ]

    store.save_generated_outline_plan(payload, mode="initial")

    graph = store.project()["relationship_graph"]
    assert len(graph) == 1
    assert graph[0]["source"] == payload["characters"][0]["name"]
    assert graph[0]["target"] == payload["characters"][1]["name"]
    assert graph[0]["relation_type"] == "上下级"
    assert graph[0]["id"].startswith("rel-")


def test_project_derives_legacy_character_relations_without_writing_file(tmp_path):
    project = {
        "project_id": "p-file",
        "title": "Legacy",
        "character_profiles": [
            {
                "name": "Lin Zhao",
                "role": "protagonist",
                "relationship_notes": [{"target": "Zhao Heng", "relation_type": "rivals"}],
            }
        ],
    }
    store = _make_minimal_file_project(tmp_path / "novel", project=project)
    project_path = store.webnovel_dir / "project.json"
    before = project_path.read_text(encoding="utf-8")

    loaded = store.project()

    assert loaded["relationship_graph"][0]["relation_type"] == "rivals"
    assert project_path.read_text(encoding="utf-8") == before

    store.update_project({"relationship_graph": []})

    assert store.project()["relationship_graph"] == []


def test_update_project_normalizes_relationship_graph(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")

    updated = store.update_project(
        {"relationship_graph": [{"source": "Lin Zhao", "target": "Zhao Heng", "bond": "rivals", "trust": 140}]}
    )

    assert updated["relationship_graph"][0]["id"].startswith("rel-")
    assert updated["relationship_graph"][0]["relation_type"] == "rivals"
    assert updated["relationship_graph"][0]["trust"] == 100


def test_update_project_shallow_merges_independent_world_blueprint_patches(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "world_blueprint": {
                "genre_plugin_ids": ["game_webnovel"],
                "premise": "旧前提",
                "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
            },
        },
    )

    store.update_project({"world_blueprint": {"world_rules": ["新规则"]}})
    updated = store.update_project(
        {
            "world_blueprint": {
                "locations": [{"name": "新港"}],
                "monster_profiles": [{"id": "wolf", "name": "灰狼", "hp": "90"}],
            }
        }
    )

    assert updated["world_blueprint"] == {
        "genre_plugin_ids": ["game_webnovel"],
        "premise": "旧前提",
        "world_rules": ["新规则"],
        "locations": [{"name": "新港"}],
        "monster_profiles": [{"id": "wolf", "name": "灰狼", "hp": "90"}],
    }


def test_update_project_syncs_canonical_blueprint_to_master_and_markdown(tmp_path):
    root = tmp_path / "novel"
    project = {
        "project_id": "p-shenyu",
        "title": "旧书名",
        "active_story_id": "s-shenyu",
        "world_blueprint": {
            "premise": "旧世界背景。",
            "economy_rules": ["铜币价格必须有锚点。"],
            "quest_rules": ["任务必须先登记，再执行和提交。"],
            "power_system": ["所有玩家统一为见习者。"],
        },
    }
    store = _make_minimal_file_project(root, project=project)
    master_path = root / ".story-system" / "MASTER_SETTING.json"
    master_path.write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "editor_notes": {"owner": "保留我"},
                "world_blueprint": {"premise": "顶层旧镜像"},
                "project": {
                    "project_id": "p-shenyu",
                    "title": "旧书名",
                    "custom_master_field": "不得删除",
                    "world_blueprint": {"premise": "项目旧镜像"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    updated = store.update_project(
        {
            "game_title": "神域",
            "world_blueprint": {"premise": "新世界背景。"},
        }
    )

    saved_project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    saved_master = json.loads(master_path.read_text(encoding="utf-8"))
    canonical = saved_project["world_blueprint"]
    assert updated["game_title"] == "神域"
    assert canonical["premise"] == "新世界背景。"
    assert canonical["economy_rules"] == ["铜币价格必须有锚点。"]
    assert saved_master["world_blueprint"] == canonical
    assert saved_master["project"]["world_blueprint"] == canonical
    assert saved_master["project"]["game_title"] == "神域"
    assert saved_master["project"]["title"] == "旧书名"
    assert saved_master["editor_notes"] == {"owner": "保留我"}
    assert saved_master["project"]["custom_master_field"] == "不得删除"

    world_markdown = (root / "设定集" / "世界观.md").read_text(encoding="utf-8")
    power_markdown = (root / "设定集" / "力量体系.md").read_text(encoding="utf-8")
    assert world_markdown.startswith("<!-- managed: world-blueprint/v1 -->")
    assert "# 《神域》世界观" in world_markdown
    assert "## 经济体系" in world_markdown
    assert "## 任务体系" in world_markdown
    assert "所有玩家统一为见习者。" in power_markdown


@pytest.mark.parametrize(
    ("include_master_project", "master_project"),
    [(False, None), (True, ["legacy-project"])],
    ids=["missing", "non-dict"],
)
def test_update_project_creates_master_project_blueprint_mirror(
    tmp_path,
    include_master_project,
    master_project,
):
    root = tmp_path / "novel"
    project = {
        "project_id": "p-mirror",
        "active_story_id": "s-mirror",
        "title": "镜像测试",
        "game_title": "镜像游戏名",
        "world_blueprint": {
            "premise": "旧前提",
            "economy_rules": ["经济规则不能丢。"],
        },
    }
    store = _make_minimal_file_project(root, project=project)
    master_path = root / ".story-system" / "MASTER_SETTING.json"
    master_payload = {
        "schema_version": "story-system-master-setting/v1",
        "custom_master_field": {"preserved": True},
        "world_blueprint": {"premise": "旧顶层镜像"},
    }
    if include_master_project:
        master_payload["project"] = master_project
    master_path.write_text(
        json.dumps(master_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    store.update_project({"world_blueprint": {"premise": "新前提"}})

    saved_project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    saved_master = json.loads(master_path.read_text(encoding="utf-8"))
    canonical = saved_project["world_blueprint"]
    assert canonical["economy_rules"] == ["经济规则不能丢。"]
    assert saved_master["world_blueprint"] == canonical
    assert saved_master["project"]["world_blueprint"] == canonical
    for key in ("project_id", "active_story_id", "title", "game_title"):
        assert saved_master["project"][key] == saved_project[key]
    assert saved_master["custom_master_field"] == {"preserved": True}


@pytest.mark.parametrize(
    ("project", "expected_title"),
    [
        (
            {"project_id": "p-game-title", "title": "作品标题", "game_title": "游戏标题"},
            "游戏标题",
        ),
        ({"project_id": "p-title", "title": "作品标题"}, "作品标题"),
        ({"project_id": "p-untitled"}, "未命名作品"),
    ],
    ids=["game-title", "title", "fallback"],
)
def test_update_project_uses_title_priority_for_world_markdown(
    tmp_path,
    project,
    expected_title,
):
    root = tmp_path / "novel"
    project = {
        **project,
        "world_blueprint": {
            "premise": "标题优先级测试。",
            "power_system": ["力量规则。"],
        },
    }
    store = _make_minimal_file_project(root, project=project)

    store.update_project({"world_blueprint": {"world_rules": ["触发同步。"]}})

    world_markdown = (root / "设定集" / "世界观.md").read_text(encoding="utf-8")
    power_markdown = (root / "设定集" / "力量体系.md").read_text(encoding="utf-8")
    assert f"# 《{expected_title}》世界观" in world_markdown
    assert f"# 《{expected_title}》力量体系" in power_markdown


def test_update_project_without_world_blueprint_does_not_refresh_world_markdown(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "旧标题",
            "world_blueprint": {"premise": "项目背景"},
        },
    )
    settings_dir = root / "设定集"
    settings_dir.mkdir()
    world_path = settings_dir / "世界观.md"
    power_path = settings_dir / "力量体系.md"
    world_path.write_text("<!-- managed: world-blueprint/v1 -->\n保留世界文档\n", encoding="utf-8")
    power_path.write_text("<!-- managed: world-blueprint/v1 -->\n保留力量文档\n", encoding="utf-8")

    updated = store.update_project({"title": "新标题", "game_title": "新游戏名"})

    assert updated["title"] == "新标题"
    assert updated["game_title"] == "新游戏名"
    assert world_path.read_text(encoding="utf-8") == "<!-- managed: world-blueprint/v1 -->\n保留世界文档\n"
    assert power_path.read_text(encoding="utf-8") == "<!-- managed: world-blueprint/v1 -->\n保留力量文档\n"


def test_update_project_keeps_saved_json_when_world_markdown_sync_fails(
    tmp_path,
    monkeypatch,
    caplog,
):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "故障降级测试",
            "world_blueprint": {
                "premise": "旧前提",
                "economy_rules": ["经济规则保留。"],
            },
        },
    )

    def fail_sync(*args, **kwargs):
        raise OSError("markdown unavailable")

    monkeypatch.setattr(
        "packages.story_core.file_project_store.sync_world_markdown",
        fail_sync,
    )

    with caplog.at_level("WARNING"):
        updated = store.update_project(
            {"world_blueprint": {"premise": "JSON 已保存的新前提"}}
        )

    saved_project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    saved_master = json.loads(
        (root / ".story-system" / "MASTER_SETTING.json").read_text(encoding="utf-8")
    )
    assert updated["world_blueprint"]["premise"] == "JSON 已保存的新前提"
    assert saved_project["world_blueprint"] == updated["world_blueprint"]
    assert saved_master["world_blueprint"] == updated["world_blueprint"]
    assert saved_master["project"]["world_blueprint"] == updated["world_blueprint"]
    assert "world blueprint markdown sync failed" in caplog.text


def test_update_project_serializes_concurrent_instances_for_same_root(tmp_path):
    root = tmp_path / "novel"
    store_a = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "world_blueprint": {"monster_profiles": [{"id": "wolf", "name": "灰狼"}]},
        },
    )
    store_b = FileProjectStore(root)
    read_barrier = threading.Barrier(2)
    start_barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def synchronize_project_read(store):
        original = store.project

        def read_project():
            project = original()
            try:
                read_barrier.wait(timeout=0.25)
            except threading.BrokenBarrierError:
                pass
            return project

        store.project = read_project

    synchronize_project_read(store_a)
    synchronize_project_read(store_b)

    def update(store, patch):
        try:
            start_barrier.wait()
            store.update_project({"world_blueprint": patch})
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors.append(exc)

    threads = [
        threading.Thread(target=update, args=(store_a, {"world_rules": ["并发规则"]})),
        threading.Thread(target=update, args=(store_b, {"locations": [{"name": "并发新港"}]})),
    ]
    for thread in threads:
        thread.start()
    start_barrier.wait()
    for thread in threads:
        thread.join()

    assert errors == []
    assert FileProjectStore(root).project()["world_blueprint"] == {
        "world_rules": ["并发规则"],
        "locations": [{"name": "并发新港"}],
        "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
    }


def test_chapter_reality_events_update_real_state_only(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {
            "protagonist": {"level": "Lv.1"},
            "economy": {"game_currency": "0铜币"},
        },
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {
                    "current": {"balance": "27.60元"},
                    "recent_changes": [],
                },
                "game_state": {
                    "current": {"level": "Lv.1", "currency": "0铜币"},
                    "recent_changes": [],
                },
                "game_panel": {"game_id": "夜烬", "level": "Lv.1", "currency": "0铜币"},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 2,
            "body": "现实线里兼职收入到账，随后支付房租。",
            "state_changes": [
                {
                    "line": "reality",
                    "change": {
                        "current": {"balance": "32.60元", "income": "5.00元"},
                        "fact": "兼职收入到账",
                    },
                },
                {
                    "line": "reality",
                    "change": {
                        "current": {"balance": "30.60元", "rent": "2.00元"},
                        "fact": "支付房租",
                    },
                },
            ],
        },
    )

    character = synced["characters"][0]
    assert character["real_state"]["current"] == {
        "balance": "30.60元",
        "income": "5.00元",
        "rent": "2.00元",
    }
    assert character["real_state"]["recent_changes"] == [
        {"chapter": 2, "fact": "兼职收入到账"},
        {"chapter": 2, "fact": "支付房租"},
    ]
    assert character["game_state"] == {
        "current": {"level": "Lv.1", "currency": "0铜币"},
        "recent_changes": [],
    }


def test_body_ledger_sync_uses_final_panel_and_real_balance(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "Web Game",
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
    )
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {
            "real": {"start_balance": "27.60元", "end_balance": "27.60元"},
            "protagonist": {"level": "Lv.3", "exp": "80/100"},
            "panel": {"level": "Lv.3", "exp": "80/100"},
            "economy": {"inventory": {}},
        },
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "game_id": "夜烬",
                "game_panel": {"level": "Lv.3", "exp": "80/100"},
            }
        ],
    }
    body = (
        "银行卡可用余额：27.60元。\n"
        "【急账代付已通过】【可用余额：312.60元】\n"
        "【等级：Lv.1】【经验：20/100】【生命：82/100】【法力：36/60】\n"
        "【新手法杖 9/10】【钱袋：空】【背包：灰狼毒腺×16，粗糙狼皮×10（2/20）】"
    )

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 1, "chapter_title": "夜烬", "body": body},
    )

    ledger = synced["progression_ledger"]
    assert ledger["real"]["end_balance"] == "312.60元"
    assert ledger["protagonist"]["level"] == "Lv.1"
    assert ledger["panel"]["level"] == "Lv.1"
    assert synced["characters"][0]["game_panel"]["level"] == "Lv.1"
    facts = synced["chapter_summaries"][0]["facts"]
    assert "苏叶现实余额312.60元" in facts
    assert "苏叶现实余额27.60元未变" not in facts


def test_opening_ledger_derives_latest_project_balance_instead_of_fixed_amount(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    chapters = [
        {
            "chapter_number": 1,
            "body": "登录前，银行卡可用余额43.18元。收到转账并付完急账后，账户余额286.41元。",
            "chapter_summary": {},
        }
    ]

    ledger = store._derive_opening_progression_ledger(chapters, {})

    assert ledger["economy"]["real_balance"] == "286.41元"
    assert "27.60" not in str(ledger)


def test_chapter_ledger_does_not_copy_monster_level_and_hp_to_protagonist(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {"protagonist": {"level": "Lv.1", "hp": "100/100"}},
        "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
    }
    body = (
        "苏叶打开角色面板，等级Lv.1，生命100/100，法力60/60。"
        "任务结算后，系统提示等级提升至Lv.2，生命110/110，法力66/66。"
        "系统弹出信息：裂纹狼（精英），等级Lv.5，生命320/320，攻击方式为撕咬。"
        "夜烬击杀了裂纹狼。"
    )

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 1, "chapter_title": "第一笔到账", "body": body},
    )

    protagonist = synced["progression_ledger"]["protagonist"]
    assert protagonist["level"] == "Lv.2"
    assert protagonist["hp"] == "110/110"
    assert protagonist["mp"] == "66/66"


def test_chapter_ledger_scopes_weapon_durability_and_quantity_backpack_lines(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {"economy": {"inventory": {}}},
        "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
    }
    body = (
        "夜烬装备灰狼护腕，防御+2，耐久8/8。"
        "铁匠修好新手法杖，耐久回到10/10。"
        "背包里还剩灰狼毒腺×2、粗糙狼皮×4、狼牙×1、灰狼护腕×1。"
        "下线后，他还在想该怎么解释背包里的东西。"
    )

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 1, "chapter_title": "第一笔到账", "body": body},
    )

    ledger = synced["progression_ledger"]
    assert ledger["equipment"]["durability"] == "10/10"
    assert ledger["economy"]["inventory"] == {
        "灰狼毒腺": 2,
        "粗糙狼皮": 4,
        "狼牙": 1,
        "灰狼护腕": 1,
    }


def test_body_ledger_summary_preserves_confirmed_next_focus(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    chapter = {
        "chapter_number": 1,
        "chapter_title": "夜烬",
        "chapter_summary": {
            "next_focus": "用现有材料登记并完成清道夫委托，优先拿任务经验。"
        },
    }
    ledger = {
        "protagonist": {"level": "Lv.1", "exp": "20/100"},
        "economy": {"inventory": {"灰狼毒腺": 16}, "game_currency": "空"},
        "quests": {"清道夫委托": "未接取；未提交；奖励未到账"},
    }

    summary = store._chapter_body_ledger_summary(chapter, ledger)

    assert summary["next_focus"] == "用现有材料登记并完成清道夫委托，优先拿任务经验。"


def test_generation_state_reconciles_saved_chapter_before_planning(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "genre": "game_webnovel",
            "current_chapter": 1,
            "world_facts": [],
            "progression_ledger": {
                "real": {"end_balance": "27.60元"},
                "protagonist": {"level": "Lv.3", "exp": "80/100"},
                "panel": {"level": "Lv.3"},
            },
            "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
        },
        project={
            "project_id": "p-file",
            "title": "Web Game",
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "夜烬",
        "body": (
            "银行卡可用余额：27.60元。后来急账代付通过。"
            "【可用余额：312.60元】【等级：Lv.1】【经验：20/100】"
            "【生命：82/100】【法力：36/60】【新手法杖 9/10】【钱袋：空】"
        ),
        "chapter_summary": {"chapter_number": 1, "facts": ["旧摘要误写Lv.3"]},
    }
    (store.story_system_dir / "chapters" / "0001.json").write_text(
        json.dumps(chapter, ensure_ascii=False), encoding="utf-8"
    )

    reconciled = store._generation_state(store.state())

    ledger = reconciled["progression_ledger"]
    assert ledger["real"]["end_balance"] == "312.60元"
    assert ledger["protagonist"]["level"] == "Lv.1"
    assert ledger["panel"]["level"] == "Lv.1"


def test_state_before_next_chapter_prefers_current_state_over_stale_embedded_snapshot(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "progression_ledger": {
                "real": {"start_balance": "27.60元", "end_balance": "312.60元"},
                "economy": {"real_balance": "312.60元"},
            },
            "chapter_summaries": [
                {
                    "chapter_number": 1,
                    "summary": "急账已经付清。",
                    "facts": ["苏叶现实余额312.60元"],
                }
            ],
        },
    )
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "updated_story": {
                "story_id": "s-file",
                "current_chapter": 1,
                "progression_ledger": {
                    "real": {"start_balance": "27.60元", "end_balance": "27.60元"},
                    "economy": {"real_balance": "27.60元"},
                },
                "chapter_summaries": [
                    {
                        "chapter_number": 1,
                        "summary": "急账尚未解决。",
                        "facts": ["苏叶现实余额27.60元未变"],
                    }
                ],
            },
        },
    )
    (store.root / "chapters" / "0001-第一章.md").write_text("第一章正文", encoding="utf-8")

    before = store._state_before_chapter(2)

    assert before["progression_ledger"]["real"]["end_balance"] == "312.60元"
    assert before["chapter_summaries"][-1]["facts"] == ["苏叶现实余额312.60元"]


def test_story_payload_uses_project_constraints_and_preserves_character_lifecycle(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "outline": "夜烬推进新手任务。",
            "genre": "网游",
            "style": "白描",
            "author_constraints": ["stale english constraint"],
            "characters": [
                {"name": "苏叶", "role": "protagonist", "game_id": "夜烬", "lifecycle_state": "active"},
                {
                    "name": "白河仓库收购方",
                    "role": "收购方NPC",
                    "lifecycle_state": "proposed",
                    "last_approved_chapter": 0,
                },
            ],
        },
        project={
            "project_id": "p-file",
            "title": "Web Game",
            "author_constraints": ["游戏内使用夜烬。"],
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
    )

    payload = store._story_state_payload_for_direction(store.state(), store.project(), 2)

    assert payload["author_constraints"] == ["游戏内使用夜烬。"]
    assert payload["characters"][1]["lifecycle_state"] == "proposed"
    assert payload["characters"][1]["last_approved_chapter"] == 0


def test_director_story_payload_contains_progression_and_scoped_quest_context(tmp_path):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=2,
        chapter_update={
            "title": "升级与巡查",
            "goal": "升级转职后提交清道夫委托，开启后坡巡查",
            "action": "返回灰烬村登记任务并提交记录",
            "payoff": "获得新职业与巡查权限",
        },
    )

    payload = store._story_state_payload_for_direction(store.state(), store.project(), 2)
    world_context = payload["world_context"]

    assert world_context["progression_rules"]
    assert world_context["quest_rules"]
    assert [
        chain["name"]
        for chain in world_context["quest_network"]["active_chains"]
    ] == ["灰烬村异常链"]
    assert "server_runtime" not in world_context
    assert "monster_profiles" not in world_context
    assert payload["monster_profiles"] == [{"id": "wolf", "name": "灰狼"}]


def test_world_relevance_text_uses_explicit_current_chapter_snapshot(tmp_path, monkeypatch):
    focus = "下一章交易材料并支付现实房租"
    store = FileProjectStore(tmp_path / "novel")
    monkeypatch.setattr(
        store,
        "chapter_numbers",
        lambda: (_ for _ in ()).throw(AssertionError("helper must not rescan chapters")),
    )
    outline_context = {"chapter": {"title": "灰狼坡", "goal": "击败灰狼"}}
    state = {"current_focus": focus}
    project = {"current_focus": focus}

    rewrite_text = store._world_relevance_text(
        state,
        project,
        2,
        outline_context,
        current_chapter=2,
    )
    future_text = store._world_relevance_text(
        state,
        project,
        3,
        outline_context,
        current_chapter=2,
    )

    assert focus not in rewrite_text
    assert focus in future_text


def test_writing_packet_passes_existing_current_chapter_to_relevance_helper(tmp_path, monkeypatch):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={"title": "灰狼坡", "goal": "击败灰狼"},
        current_chapter=3,
        current_focus="下一章交易材料",
    )
    captured = {}

    def capture_relevance(
        state,
        project,
        target_chapter,
        outline_context,
        scene_cards=None,
        *,
        current_chapter,
    ):
        captured["target_chapter"] = target_chapter
        captured["current_chapter"] = current_chapter
        return "灰狼"

    monkeypatch.setattr(store, "_world_relevance_text", capture_relevance)

    store.writing_packet(1)

    assert captured == {"target_chapter": 1, "current_chapter": 3}


def test_director_payload_scans_chapters_once_and_passes_current_snapshot(tmp_path, monkeypatch):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=2,
        chapter_update={"title": "后坡巡查", "goal": "提交清道夫委托"},
        current_chapter=1,
        current_focus="开启后坡巡查",
    )
    state = store.state()
    project = store.project()
    original = store.chapter_numbers
    calls = 0
    captured = {}

    def counted_chapter_numbers():
        nonlocal calls
        calls += 1
        return original()

    def capture_relevance(
        state,
        project,
        target_chapter,
        outline_context,
        scene_cards=None,
        *,
        current_chapter,
    ):
        captured["target_chapter"] = target_chapter
        captured["current_chapter"] = current_chapter
        return "提交清道夫委托"

    monkeypatch.setattr(store, "chapter_numbers", counted_chapter_numbers)
    monkeypatch.setattr(store, "_world_relevance_text", capture_relevance)

    store._story_state_payload_for_direction(state, project, 2)

    assert calls == 1
    assert captured == {"target_chapter": 2, "current_chapter": 1}


def test_transition_reality_change_does_not_fallback_to_game_change(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
                "game_panel": {"game_id": "夜烬", "level": "Lv.1"},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 3,
            "body": "从现实回到游戏。",
            "state_changes": [
                {
                    "line": "transition",
                    "real_change": {
                        "current": {"balance": "32.60元"},
                        "fact": "现实收入到账",
                    },
                }
            ],
        },
    )

    character = synced["characters"][0]
    assert character["real_state"]["current"]["balance"] == "32.60元"
    assert character["game_state"] == {
        "current": {"level": "Lv.1"},
        "recent_changes": [],
    }


def test_state_event_with_unknown_target_updates_no_character(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
            },
            {
                "name": "林照",
                "role": "supporting",
                "real_state": {"current": {"balance": "10.00元"}, "recent_changes": []},
            },
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 4,
            "body": "现实线出现一笔明确收入。",
            "state_changes": [
                {
                    "line": "reality",
                    "target": "不存在的人",
                    "change": {"current": {"balance": "99.00元"}, "fact": "错误目标"},
                }
            ],
        },
    )

    assert synced["characters"][0]["real_state"]["current"]["balance"] == "27.60元"
    assert synced["characters"][1]["real_state"]["current"]["balance"] == "10.00元"


def test_plain_money_in_game_body_without_state_changes_does_not_change_real_state(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 5, "body": "他摸了摸口袋里的钱，随后继续登录游戏。"},
    )

    character = synced["characters"][0]
    assert character["real_state"] == {"current": {"balance": "27.60元"}, "recent_changes": []}


def test_web_game_english_body_updates_game_state(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "web game",
        "progression_ledger": {},
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_panel": {"game_id": "Night Ember"},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 6,
            "body": (
                "Level: 2\nExperience: 20/200\nHP: 80/100\nMP: 40/60\n"
                "Inventory: wolf fang x3\nCurrency: 30 coins\nQuest: patrol\nDurability: 90/100"
            ),
        },
    )

    character = synced["characters"][0]
    current = character["game_state"]["current"]
    assert current["level"] == "Lv.2"
    assert current["exp"] == "20/200"
    assert current["hp"] == "80/100"
    assert current["mp"] == "40/60"
    assert current["inventory"] == {"wolf fang": 3}
    assert current["currency"] == "30 coins"


def test_explicit_game_event_wins_over_chapter_ledger(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {},
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
                "game_panel": {"game_id": "夜烬"},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 7,
            "body": "Level: 2 Experience: 20/200",
            "state_changes": [
                {
                    "line": "game",
                    "change": {
                        "current": {"level": "Lv.5"},
                        "fact": "事件确认等级",
                    },
                }
            ],
        },
    )

    character = synced["characters"][0]
    assert character["game_state"]["current"]["level"] == "Lv.5"
    assert character["game_panel"]["level"] == "Lv.5"


def test_full_chapter_sync_applies_game_state_event_once(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {},
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
                "game_panel": {"game_id": "夜烬", "level": "Lv.1"},
            }
        ],
    }

    synced = store._sync_after_chapter(
        {
            "chapter_number": 8,
            "chapter_title": "回到副本",
            "body": "现实线结束，夜烬重新登录。",
            "state_changes": [
                {
                    "line": "game",
                    "change": {
                        "current": {"level": "Lv.2"},
                        "fact": "重新登录后等级确认",
                    },
                }
            ],
        },
        state,
    )

    changes = synced["characters"][0]["game_state"]["recent_changes"]
    assert changes == [{"chapter": 8, "fact": "重新登录后等级确认"}]


def test_english_prose_question_questing_and_coins_do_not_create_ledger_updates(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "web game",
        "characters": [{"name": "苏叶", "role": "protagonist"}],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 9,
            "body": "He questioned the questing route while coins glittered in the prose.",
        },
    )

    assert synced.get("progression_ledger", {}) == {}
    assert "game_state" not in synced["characters"][0]


def test_reality_line_with_only_game_namespace_does_not_fallback_to_generic_change(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 12,
            "body": "现实线没有账本变化。",
            "state_changes": [
                {
                    "line": "reality",
                    "change": {
                        "current": {"balance": "99.00元"},
                        "game_state": {"current": {"level": "Lv.9"}},
                    },
                }
            ],
        },
    )

    character = synced["characters"][0]
    assert character["real_state"]["current"]["balance"] == "27.60元"
    assert character["game_state"]["current"]["level"] == "Lv.1"


def test_game_line_with_only_reality_namespace_does_not_fallback_to_generic_change(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 13,
            "body": "游戏线没有账本变化。",
            "state_changes": [
                {
                    "line": "game",
                    "change": {
                        "current": {"level": "Lv.9"},
                        "real_state": {"current": {"balance": "99.00元"}},
                    },
                }
            ],
        },
    )

    character = synced["characters"][0]
    assert character["game_state"]["current"]["level"] == "Lv.1"
    assert character["real_state"]["current"]["balance"] == "27.60元"


def test_generated_plan_transaction_restores_old_files_on_replace_failure(tmp_path, monkeypatch):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root)
    outline_path = root / ".webnovel" / "outline.json"
    outline_path.write_text(json.dumps({"schema_version": "project-outline/v1", "overall": {}, "arcs": [], "chapters": []}), encoding="utf-8")
    before = {
        path: path.read_bytes()
        for path in (root / ".webnovel" / "project.json", root / ".webnovel" / "state.json", outline_path)
    }
    import packages.story_core.file_project_store as module

    real_replace = module.os.replace
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")

    assert {path: path.read_bytes() for path in before} == before


def test_update_outline_rejects_core_ending_before_current_chapter(tmp_path) -> None:
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root, state={"current_chapter": 21})
    before = store.project_outline()
    invalid = deepcopy(before)
    invalid["overall"]["core_ending_chapter"] = 20
    invalid["overall"]["extension_ceiling_chapter"] = 30

    with pytest.raises(ValueError, match="core_ending_before_current_chapter"):
        store.update_project_outline(invalid)

    assert store.project_outline() == before


def test_generate_outline_plan_uses_compact_brief_and_one_time_guidance(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "seed_outline": "林照看守断香炉。",
            "current_focus": "查清第三块青砖。",
            "author_constraints": ["对白完整。"],
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": []},
    )
    calls = []

    class RecordingGenerator:
        def generate(self, brief, *, mode, guidance):
            calls.append((brief, mode, guidance))
            return _generated_opening_plan()

    (store.webnovel_dir / "opening_directions.json").write_text(
        json.dumps(
            {
                "schema_version": "opening-directions/v1",
                "directions": [
                    {
                        "id": "direction-1",
                        "title": "方向一",
                        "hook": "林照看守断香炉。",
                        "protagonist_goal": "守住香火。",
                        "main_conflict": "有人想毁掉旧案。",
                        "growth_path": "从守住现场开始掌握宗门规则。",
                        "opening_promise": "每次解决具体问题都会换来一条可验证线索。",
                        "primary_trope_id": "selected-trope",
                    },
                    {
                        "id": "direction-2",
                        "title": "方向二",
                        "hook": "另一条方向。",
                        "protagonist_goal": "另一目标。",
                        "main_conflict": "另一冲突。",
                        "growth_path": "另一成长。",
                        "opening_promise": "另一承诺。",
                        "primary_trope_id": "unused-trope",
                    },
                    {
                        "id": "direction-3",
                        "title": "方向三",
                        "hook": "第三条方向。",
                        "protagonist_goal": "第三目标。",
                        "main_conflict": "第三冲突。",
                        "growth_path": "第三成长。",
                        "opening_promise": "第三承诺。",
                        "primary_trope_id": "backup-trope",
                    },
                ],
                "selected_id": "direction-1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store.generate_outline_plan(RecordingGenerator(), mode="initial", guidance="  对手有现实利益  ")

    brief, mode, guidance = calls[0]
    assert mode == "initial"
    assert guidance == "对手有现实利益"
    assert brief.novel_type_id == "xuanhuan"
    assert brief.opening_direction.hook == "林照看守断香炉。"
    assert brief.opening_direction.primary_trope_id == "selected-trope"
    assert brief.existing_characters == []
    assert brief.existing_character_names == []
    secret = "对手有现实利益".encode("utf-8")
    assert all(secret not in path.read_bytes() for path in store.root.rglob("*") if path.is_file())


def test_planning_brief_falls_back_to_saved_overall_primary_trope_id(tmp_path) -> None:
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "Fallback Trope",
            "seed_outline": "Seed outline",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": []},
    )
    (store.webnovel_dir / "outline.json").write_text(
        json.dumps(
            {
                "schema_version": "project-outline/v1",
                "overall": {
                    "story": "Saved hook",
                    "protagonist_goal": "Saved goal",
                    "main_conflict": "Saved conflict",
                    "growth_path": "Saved growth",
                    "ending_direction": "Saved promise",
                    "primary_trope_id": "saved-overall-trope",
                },
                "arcs": [],
                "chapters": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    brief = store._planning_brief()

    assert brief.opening_direction.primary_trope_id == "saved-overall-trope"


def test_planning_brief_keeps_all_character_names_while_limiting_detailed_cards(tmp_path) -> None:
    project_cards = [
        _planning_card(f"已有角色{number}", "supporting")
        for number in range(1, 8)
    ]
    state_cards = [project_cards[0], _planning_card("状态角色8", "supporting")]
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "角色清单",
            "character_profiles": project_cards,
        },
        state={
            "story_id": "s-file",
            "current_chapter": 0,
            "world_facts": [],
            "characters": state_cards,
        },
    )

    brief = store._planning_brief()

    assert len(brief.existing_characters) == 6
    assert brief.existing_character_names == [
        *[f"已有角色{number}" for number in range(1, 8)],
        "状态角色8",
    ]


def _prepare_extendable_outline(tmp_path, *, locked_inner_arc: bool = False):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root)
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 20
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    if locked_inner_arc:
        current_outline["arcs"].append(
            {
                **current_outline["arcs"][0],
                "id": "locked-inner",
                "title": "Locked inner",
                "start_chapter": 31,
                "end_chapter": 50,
                "trope_id": "golden_finger_first_test",
                "goal": "Test the anomaly",
            }
        )
    store.update_project_outline(current_outline)
    prepared = store.project_outline()
    prepared.pop("source", None)
    return root, store, prepared


def _extension_plan(
    current_outline: dict,
    *,
    arcs: list[dict] | None = None,
    first_trope_beat=None,
) -> GeneratedOutlinePlan:
    return GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "overall": current_outline["overall"],
                "arcs": current_outline["arcs"] if arcs is None else arcs,
                "chapters": [
                    {
                        "chapter_number": number,
                        "goal": "继续追查旧案",
                        "obstacle": "旧档房封门",
                        "action": "林照争取查档资格",
                        "turn": "发现新的经手人",
                        "payoff": "锁定下一条线索",
                        "ending_hook": "经手人已经离宗",
                        "trope_beat": first_trope_beat if number == 31 else None,
                        "cast": ["林照", "New"],
                    }
                    for number in range(31, 51)
                ],
            },
            "characters": [_planning_card("New", "supporting")],
        }
    )


def test_extend_generated_outline_plan_fills_missing_rolling_window_chapters(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 20
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    store.update_project_outline(current_outline)
    addition = GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "overall": current_outline["overall"],
                "arcs": [
                    {
                        **current_outline["arcs"][0],
                        "end_chapter": 150,
                        "long_term_antagonist_traces": ["旧名册被换过", "执法堂有人提前封档"],
                    }
                ],
                "chapters": [
                    {
                        "chapter_number": number,
                        "goal": "继续追查旧案",
                        "obstacle": "旧档房封闭",
                        "action": "林照争取查档资格",
                        "turn": "发现新的经手人",
                        "payoff": "锁定下一条线索",
                        "ending_hook": "经手人已经离宗",
                        "cast": ["林照", "周满"],
                    }
                    for number in range(31, 51)
                ]
            },
            "characters": [_planning_card("新档房弟子", "supporting")],
        }
    )

    saved = store.save_generated_outline_plan(addition, mode="extend")

    assert [item["chapter_number"] for item in saved["outline"]["chapters"]] == list(range(1, 51))
    assert saved["outline"]["arcs"][0]["trope_id"] == "low_status_reversal"
    assert saved["outline"]["chapters"][0]["trope_beat"] == "低位压力"
    assert saved["outline"]["arcs"][0]["end_chapter"] == 150
    assert saved["outline"]["arcs"][0]["long_term_antagonist_traces"] == [
        "旧名册被换过",
        "执法堂有人提前封档",
    ]
    assert any(item["name"] == "新档房弟子" for item in saved["characters"])


@pytest.mark.parametrize(
    "new_card_name,cast,error",
    [
        ("新角色", ["未知角色"], "missing_character_card:未知角色"),
        ("林照", ["林照"], "duplicate_existing_character_card:林照"),
    ],
)
def test_extend_direct_save_revalidates_cast_and_new_cards_without_writes(
    tmp_path,
    new_card_name: str,
    cast: list[str],
    error: str,
) -> None:
    store = _make_minimal_file_project(tmp_path / "novel")
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 20
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    store.update_project_outline(current_outline)
    addition = GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "arcs": [current_outline["arcs"][0]],
                "chapters": [
                    {
                        "chapter_number": number,
                        "goal": "继续追查旧案",
                        "obstacle": "旧档房封闭",
                        "action": "林照争取查档资格",
                        "turn": "发现新的经手人",
                        "payoff": "锁定下一条线索",
                        "ending_hook": "经手人已经离宗",
                        "cast": cast,
                    }
                    for number in range(31, 51)
                ],
            },
            "characters": [_planning_card(new_card_name, "supporting")],
        }
    )
    before = {
        path.relative_to(store.root): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match=f"^{error}$"):
        store.save_generated_outline_plan(addition, mode="extend")

    assert {
        path.relative_to(store.root): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.parametrize(
    "overall_trope_id,arc_trope_id,error",
    [
        ("golden_finger_first_test", "low_status_reversal", "unexpected_primary_trope_id"),
        ("low_status_reversal", "golden_finger_first_test", "locked_arc_trope_drift:opening"),
    ],
)
def test_extend_rejects_locked_trope_drift_without_writes(
    tmp_path,
    overall_trope_id: str,
    arc_trope_id: str,
    error: str,
) -> None:
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root)
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 20
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    store.update_project_outline(current_outline)
    addition = GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "overall": {**current_outline["overall"], "primary_trope_id": overall_trope_id},
                "arcs": [{**current_outline["arcs"][0], "trope_id": arc_trope_id}],
                "chapters": [
                    {
                        "chapter_number": number,
                        "goal": "继续追查旧案",
                        "obstacle": "旧档房封门",
                        "action": "林照争取查档资格",
                        "turn": "发现新的经手人",
                        "payoff": "锁定下一条线索",
                        "ending_hook": "经手人已经离宗",
                        "trope_beat": None,
                        "cast": ["林照", "New"],
                    }
                    for number in range(31, 51)
                ],
            },
            "characters": [_planning_card("New", "supporting")],
        }
    )
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match=f"^{error}$"):
        store.save_generated_outline_plan(addition, mode="extend")

    assert _file_snapshot(root) == before


def _regeneration_plan_from_current(
    current_outline: dict,
    *,
    arcs: list[dict] | None = None,
    first_trope_beat=None,
) -> GeneratedOutlinePlan:
    payload = _generated_opening_plan().model_dump(mode="json")
    template = payload["outline"]["chapters"][0]
    payload["outline"]["overall"] = {
        **payload["outline"]["overall"],
        **current_outline["overall"],
    }
    payload["outline"]["arcs"] = current_outline["arcs"] if arcs is None else arcs
    payload["outline"]["chapters"] = [
        {
            **template,
            "chapter_number": number,
            "title": f"Regenerated {number}",
            "trope_beat": first_trope_beat if number == 21 else None,
        }
        for number in range(21, 51)
    ]
    return GeneratedOutlinePlan.model_validate(payload)


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_preserves_omitted_locked_arc_after_merge(tmp_path, mode: str) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path, locked_inner_arc=True)
    generated_arcs = [arc for arc in current_outline["arcs"] if arc["id"] != "locked-inner"]
    plan = (
        _extension_plan(current_outline, arcs=generated_arcs)
        if mode == "extend"
        else _regeneration_plan_from_current(current_outline, arcs=generated_arcs)
    )

    saved = store.save_generated_outline_plan(plan, mode=mode)

    assert any(
        arc["id"] == "locked-inner" and arc["trope_id"] == "golden_finger_first_test"
        for arc in saved["outline"]["arcs"]
    )
    assert _file_snapshot(root)


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_accepts_future_nested_arc_inside_locked_arc(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    nested = {
        **current_outline["arcs"][0],
        "id": "future-nested",
        "title": "Future nested",
        "start_chapter": 31,
        "end_chapter": 45,
        "trope_id": "golden_finger_first_test",
        "goal": "Test the anomaly",
    }
    plan = (
        _extension_plan(current_outline, arcs=[*current_outline["arcs"], nested])
        if mode == "extend"
        else _regeneration_plan_from_current(current_outline, arcs=[*current_outline["arcs"], nested])
    )

    saved = store.save_generated_outline_plan(plan, mode=mode)

    assert any(arc["id"] == "future-nested" for arc in saved["outline"]["arcs"])
    assert _file_snapshot(root)


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_rejects_renamed_arc_overlapping_committed_locked_range_without_writes(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    renamed = {**current_outline["arcs"][0], "id": "renamed-opening", "start_chapter": 10, "end_chapter": 30}
    plan = (
        _extension_plan(current_outline, arcs=[renamed])
        if mode == "extend"
        else _regeneration_plan_from_current(current_outline, arcs=[*current_outline["arcs"], renamed])
    )
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^locked_arc_overlap:renamed-opening$"):
        store.save_generated_outline_plan(plan, mode=mode)

    assert _file_snapshot(root) == before


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_rejects_renamed_arc_exactly_replacing_locked_range_without_writes(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    renamed = {**current_outline["arcs"][0], "id": "renamed-opening"}
    plan = (
        _extension_plan(current_outline, arcs=[renamed])
        if mode == "extend"
        else _regeneration_plan_from_current(current_outline, arcs=[renamed])
    )
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^locked_arc_overlap:renamed-opening$"):
        store.save_generated_outline_plan(plan, mode=mode)

    assert _file_snapshot(root) == before


def test_regenerate_rejects_same_id_locked_trope_drift_without_writes(tmp_path) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    drifted = [{**current_outline["arcs"][0], "trope_id": "golden_finger_first_test"}]
    plan = _regeneration_plan_from_current(current_outline, arcs=drifted)
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^locked_arc_trope_drift:opening$"):
        store.save_generated_outline_plan(plan, mode="regenerate")

    assert _file_snapshot(root) == before


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_accepts_omitted_locked_arc_as_trope_beat_context(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path, locked_inner_arc=True)
    generated_arcs = [arc for arc in current_outline["arcs"] if arc["id"] != "locked-inner"]
    if mode == "extend":
        plan = _extension_plan(
            current_outline,
            arcs=generated_arcs,
            first_trope_beat="异常出现",
        )
    else:
        plan = _regeneration_plan_from_current(current_outline, arcs=generated_arcs)
        payload = plan.model_dump(mode="json")
        for chapter in payload["outline"]["chapters"]:
            if chapter["chapter_number"] == 31:
                chapter["trope_beat"] = "异常出现"
        plan = GeneratedOutlinePlan.model_validate(payload)

    saved = store.save_generated_outline_plan(plan, mode=mode)

    assert any(
        arc["id"] == "locked-inner" and arc["trope_id"] == "golden_finger_first_test"
        for arc in saved["outline"]["arcs"]
    )
    assert _file_snapshot(root)


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_rejects_invalid_beat_after_locked_arc_context_merge(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path, locked_inner_arc=True)
    generated_arcs = [arc for arc in current_outline["arcs"] if arc["id"] != "locked-inner"]
    if mode == "extend":
        plan = _extension_plan(
            current_outline,
            arcs=generated_arcs,
            first_trope_beat="低位压力",
        )
    else:
        plan = _regeneration_plan_from_current(current_outline, arcs=generated_arcs)
        payload = plan.model_dump(mode="json")
        for chapter in payload["outline"]["chapters"]:
            if chapter["chapter_number"] == 31:
                chapter["trope_beat"] = "低位压力"
        plan = GeneratedOutlinePlan.model_validate(payload)
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:31$"):
        store.save_generated_outline_plan(plan, mode=mode)

    assert _file_snapshot(root) == before


def test_regenerate_preserves_committed_chapter_outline(tmp_path) -> None:
    store = _make_minimal_file_project(tmp_path / "novel")
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 20
    state["world_facts"] = [{"fact": "Committed fact"}]
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    store.update_project_outline(current_outline)
    before_outline = store.project_outline()
    before_chapter = before_outline["chapters"][0]

    payload = _generated_opening_plan().model_dump(mode="json")
    template = payload["outline"]["chapters"][0]
    payload["outline"]["arcs"] = current_outline["arcs"]
    payload["outline"]["chapters"] = [
        {
            **template,
            "chapter_number": number,
            "title": f"Regenerated {number}",
            "trope_beat": None,
        }
        for number in range(21, 51)
    ]
    payload["outline"]["overall"]["story"] = "Regenerated future story"
    generated_plan = GeneratedOutlinePlan.model_validate(payload)

    store.save_generated_outline_plan(generated_plan, mode="regenerate")

    after = store.project_outline()
    assert after["chapters"][0] == before_chapter
    assert [item["chapter_number"] for item in after["chapters"]] == list(range(1, 51))
    assert after["overall"]["story"] == "Regenerated future story"
    assert store.state()["world_facts"] == [{"fact": "Committed fact"}]


def test_regenerate_at_extension_ceiling_rejects_without_file_changes(tmp_path) -> None:
    store = _make_minimal_file_project(tmp_path / "novel")
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=500,
        extension_ceiling_chapter=500,
    )
    current_outline["arcs"][0]["end_chapter"] = 500
    store.update_project_outline(current_outline)
    state = store.state()
    state["current_chapter"] = 500
    store._write_json(store.webnovel_dir / "state.json", state)

    payload = _generated_opening_plan().model_dump(mode="json")
    payload["outline"]["overall"].update(
        core_ending_chapter=500,
        extension_ceiling_chapter=500,
    )
    payload["outline"]["arcs"][0]["end_chapter"] = 500
    payload["outline"]["chapters"] = []

    before = {
        path.relative_to(store.root): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="^outline_window_already_full$"):
        store.save_generated_outline_plan(
            GeneratedOutlinePlan.model_validate(payload),
            mode="regenerate",
        )

    assert {
        path.relative_to(store.root): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    } == before


def test_writing_packet_uses_planned_cast_and_hides_long_term_secrets(tmp_path):
    root = tmp_path / "novel"
    characters = [
        _planning_card("林照", "protagonist", age=19),
        _planning_card("赵衡", "stage_antagonist"),
        _planning_card("周满", "supporting"),
        {
            **_planning_card("顾长老", "long_term_antagonist"),
            "story_drive": {
                "immediate_goal": "让赵衡清掉旧档",
                "failure_stakes": "旧案牵出自己",
                "hidden_matters": ["亲手换掉旧名册"],
            },
            "secrets": ["真实身份是执法堂首座"],
        },
    ]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "character_profiles": characters,
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={
            "story_id": "s-file",
            "current_chapter": 0,
            "world_facts": [],
            "characters": characters,
        },
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["overall"]["ending_contract"] = "游戏线与现实线完整收束。"
    outline["chapters"][0]["cast"] = ["林照", "赵衡", "顾长老"]
    (root / ".webnovel" / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert [card["name"] for card in packet["character_cards"]] == ["林照", "赵衡", "顾长老"]
    assert [card["name"] for card in packet["state"]["characters"]] == ["林照", "赵衡", "顾长老"]
    assert [card["name"] for card in packet["project"]["character_profiles"]] == ["林照", "赵衡", "顾长老"]
    serialized = json.dumps(packet, ensure_ascii=False)
    assert "亲手换掉旧名册" not in serialized
    assert "真实身份是执法堂首座" not in serialized
    assert packet["outline_context"]["active_arc"]["long_term_antagonist_traces"] == ["旧名册被换过"]
    assert packet["outline_context"]["overall"]["ending_contract"]
    assert "extension_gate" not in packet["outline_context"]["active_arc"]
    assert "chapters" not in packet["outline_context"]


def test_writing_packet_only_includes_relationships_within_chapter_cast(tmp_path):
    characters = [
        _planning_card("Lin Zhao", "protagonist", age=19),
        _planning_card("Zhao Heng", "stage_antagonist"),
        _planning_card("Zhou Man", "supporting"),
    ]
    project = {
        "project_id": "p-file",
        "title": "Relations",
        "character_profiles": characters,
        "relationship_graph": [
            {"source": "Lin Zhao", "target": "Zhao Heng", "bond": "rivals", "private_notes": ["hidden patron"]},
            {"source": "Lin Zhao", "target": "Zhou Man", "bond": "friends"},
        ],
    }
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project=project,
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": characters},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0]["cast"] = ["Lin Zhao", "Zhao Heng"]
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert [(item["source"], item["target"]) for item in packet["relationship_context"]] == [
        ("Lin Zhao", "Zhao Heng")
    ]
    assert "private_notes" not in packet["relationship_context"][0]
    assert "relationship_graph" not in packet["project"]


def _character_portrait_state():
    return {
        "story_id": "s-file",
        "current_chapter": 0,
        "genre": "都市悬疑",
        "world_facts": [],
        "characters": [
            {
                "name": "林月",
                "role": "药剂师",
                "game_id": "月见",
                "npc_profile": {"service_role": "药剂师", "incentives": ["维持药材供应"]},
                "personality_portrait": {
                    "temperament": {"core_traits": ["嘴硬心软"]},
                    "voice": {"sentence_habit": "先问来意，再说规矩。"},
                },
            }
        ],
    }


def test_state_exposes_completed_character_portrait_without_writing_old_project(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root, state=_character_portrait_state())
    state_path = root / ".webnovel" / "state.json"
    before = state_path.read_text(encoding="utf-8")

    character = store.state()["characters"][0]

    assert character["personality_portrait"]["temperament"]["core_traits"] == ["嘴硬心软"]
    assert character["personality_portrait"]["behavior"]["pressure_mode"]
    assert state_path.read_text(encoding="utf-8") == before


def test_update_character_merges_nested_portrait_and_finds_game_id(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel", state=_character_portrait_state())

    updated = store.update_character(
        "月见",
        {"personality_portrait": {"psychology": {"fear": "欠下人情"}}},
    )

    assert updated["name"] == "林月"
    assert updated["personality_portrait"]["temperament"]["core_traits"] == ["嘴硬心软"]
    assert updated["personality_portrait"]["psychology"]["fear"] == "欠下人情"
    persisted = store._read_json(store.webnovel_dir / "state.json")
    assert persisted["characters"][0]["personality_portrait"]["psychology"]["fear"] == "欠下人情"


def test_complete_character_portrait_persists_without_overwriting_user_fields(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel", state=_character_portrait_state())

    completed = store.complete_character_portrait("林月")

    assert completed["personality_portrait"]["temperament"]["core_traits"] == ["嘴硬心软"]
    assert completed["personality_portrait"]["growth"]["invariants"]
    persisted = store._read_json(store.webnovel_dir / "state.json")
    assert persisted["characters"][0]["personality_portrait"]["growth"]["invariants"]


def test_update_character_rejects_unknown_name_and_renaming(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel", state=_character_portrait_state())

    with pytest.raises(KeyError, match="character_not_found"):
        store.update_character("不存在", {"core_motivation": "x"})
    with pytest.raises(ValueError, match="character_name_immutable"):
        store.update_character("林月", {"name": "其他人"})


def test_regeneration_quality_allows_soft_scene_coverage_warnings():
    writing_review = {
        "issues": [
            "场景卡必写内容缺失：s3-c2-reaction-1 缺少 路人玩家抱怨爆率低。",
            "Scene contract not consumed: s1-c2-inherit-ledger missing visibility_boundary_surface.",
        ],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }
    quality_report = {"ok": False, "issues": ["writing_review"], "writing_review": writing_review}

    assert _regeneration_quality_blocking(quality_report, writing_review) is False


def test_regeneration_quality_blocks_short_chapter():
    writing_review = {
        "issues": ["章节字数偏少：当前约3061字，最低要求3800字。"],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }
    quality_report = {"ok": False, "issues": ["writing_review"], "writing_review": writing_review}

    assert _regeneration_quality_blocking(quality_report, writing_review) is True


def test_regeneration_quality_still_blocks_progression_overreach():
    writing_review = {
        "issues": ["第二章推进过快：从第一章账本直接完成元素回廊前置或升级。"],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }
    quality_report = {"ok": False, "issues": ["writing_review"], "writing_review": writing_review}

    assert _regeneration_quality_blocking(quality_report, writing_review) is True


def test_file_project_store_writes_rewrites_and_commits(tmp_path, monkeypatch):
    root = tmp_path / "novel"
    workflow_log = tmp_path / "chapter_exports" / "workflow_log.jsonl"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_WORKFLOW_LOG_PATH", str(workflow_log))
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps({"story_id": "s-file", "current_chapter": 0, "world_facts": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    store = FileProjectStore(root)
    written = store.write_chapter(
        chapter_number=1,
        title="Chapter One",
        body="Night Ember checked the village counter and kept walking.",
        next_outline="Check the wolf slope.",
        summary="Night Ember enters the village.",
        instructions=["keep it grounded"],
    )

    assert written["schema_version"] == "file-project-write/v1"
    assert "ai_flavor_review" in written["review"]
    assert "cold_reader_review" in written["review"]
    assert "cold_reader_review" in written["review"]["writing_review"]
    assert written["review"]["length_review"]["pass"] is False
    assert written["review"]["length_review"]["body_chars"] < written["review"]["length_review"]["min_chars"]
    assert written["review"]["writing_review"]["pass"] is False
    assert any("章节字数偏少" in issue for issue in written["review"]["writing_review"]["issues"])
    assert (root / ".story-system" / "chapters" / "0001.json").exists()
    assert (root / "chapters" / "0001-Chapter One.md").read_text(encoding="utf-8").startswith("Night Ember")
    assert store.summary()["current_chapter"] == 1
    assert (root / ".story-system" / "commits" / "latest_commit.json").exists()
    project_after_write = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert project_after_write["world_blueprint"]["continuity_state"]["latest_chapter"] == 1
    assert project_after_write["world_blueprint"]["continuity_state"]["latest_summary"] == "Night Ember enters the village."

    rewritten = store.rewrite_chapter(
        chapter_number=1,
        title="Chapter One Revised",
        body="Night Ember bought nothing. He only counted the cost and left.",
        next_outline="Return after two more glands.",
        instructions=["remove explanatory narrator voice"],
    )

    assert rewritten["schema_version"] == "file-project-rewrite/v1"
    assert "ai_flavor_review" in rewritten["review"]
    assert "cold_reader_review" in rewritten["review"]
    assert "cold_reader_review" in rewritten["review"]["writing_review"]
    assert not (root / "chapters" / "0001-Chapter One.md").exists()
    assert (root / "chapters" / "0001-Chapter One Revised.md").read_text(encoding="utf-8").startswith("Night Ember")
    latest_commit = json.loads((root / ".story-system" / "commits" / "latest_commit.json").read_text(encoding="utf-8"))
    assert latest_commit["operation"] == "rewrite"
    assert any(item["path"] == "chapters/0001-Chapter One Revised.md" for item in latest_commit["manifest"])
    project_after_rewrite = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert project_after_rewrite["world_blueprint"]["continuity_state"]["latest_title"] == "Chapter One Revised"
    state_after_rewrite = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    world_facts_after_rewrite = "\n".join(state_after_rewrite["world_facts"])
    assert "remove explanatory narrator voice" in world_facts_after_rewrite
    assert "keep it grounded" not in world_facts_after_rewrite
    workflow_records = [json.loads(line) for line in workflow_log.read_text(encoding="utf-8").splitlines()]
    assert [record["operation"] for record in workflow_records] == ["write", "rewrite"]
    assert workflow_records[0]["chapter"] == 1
    assert workflow_records[1]["chapter_title"] == "Chapter One Revised"


def test_file_project_store_prompt_preview_exposes_generation_prompts(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "world_blueprint": {
                "world_rules": ["NPC只能处理岗位权限内的事务。"],
                "quest_rules": ["任务必须先登记，再执行和提交。"],
                "economy_rules": ["材料价格必须来自任务、配方或真实稀缺性。"],
            },
        },
        state={
            "story_id": "s-file",
            "outline": "A grounded webgame story.",
            "genre": "网游",
            "style": "白描",
            "current_chapter": 1,
            "world_facts": ["夜烬用新手法杖验证灰狼坡。"],
            "characters": [{"name": "苏叶", "role": "protagonist", "goal": "低调验证机会"}],
        },
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "灰狼坡试水",
        "body": _long_test_body("Night Ember tests the wolf slope."),
        "event_plan": {"chapter_title": "灰狼坡试水", "next_focus": "回村接清道夫委托"},
        "writing_taskbook": {
            "chapter_number": 1,
            "chapter_title": "灰狼坡试水",
            "chapter_goal": "验证灰狼掉落",
            "target_chars": "3800到5500字",
            "style_contract": ["白描"],
            "craft_templates": ["对话场面：别人问、催或提醒；夜烬用完整句子给表面理由。"],
            "global_required": ["写出新手法杖"],
            "global_forbidden": ["不要公开暴露千倍爆率"],
            "scenes": [
                {
                    "key": "entry_login",
                    "title": "登录建号",
                    "goal": "夜烬进入灰烬村",
                    "required_surface": "游戏ID夜烬、新手法杖",
                    "forbidden_surface": "转职",
                    "entry_state": "现实余额紧张",
                    "exit_state": "进入村口",
                    "handoff": "去灰狼坡",
                    "target_chars": 900,
                }
            ],
        },
        "quality_report": {"writing_review": {"pass": False, "issues": ["对话不够自然"], "revision_plan": ["补完整对话"]}},
    }
    store._write_json(root / ".story-system" / "chapters" / "0001.json", chapter)
    store._write_json(root / ".story-system" / "reviews" / "0001.json", chapter["quality_report"])

    preview = store.prompt_preview(1)

    assert preview["schema_version"] == "file-project-prompt-preview/v1"
    assert preview["reconstructed"] is True
    assert preview["source"] == "rebuilt_from_current_project_files"
    modules = {item["key"]: item for item in preview["modules"]}
    assert {"core_context", "character_context", "genre_context", "writing_taskbook", "packet_context"}.issubset(modules)
    assert "source_body" not in modules
    keys = {item["key"] for item in preview["prompts"]}
    assert {"director_plan", "writer_body", "revision", "writing_taskbook", "review_agents"}.issubset(keys)
    assert "style_adapt" not in keys
    by_key = {item["key"]: item for item in preview["prompts"]}
    assert "## 输出要求" in by_key["writer_body"]["content"]
    assert "## 本章方向" in by_key["writer_body"]["content"]
    assert "## 本章事实" in by_key["writer_body"]["content"]
    assert "## 出场人物" in by_key["writer_body"]["content"]
    assert "## 正文写法" in by_key["writer_body"]["content"]
    assert "character_cards" not in modules["core_context"]["content"]
    assert "苏叶" in by_key["writer_body"]["content"]
    assert "character_context" in by_key["writer_body"]["module_keys"]
    assert "NPC只能处理岗位权限内的事务" in by_key["writer_body"]["content"]
    assert "任务必须先登记" not in by_key["writer_body"]["content"]
    assert "材料价格必须来自任务" not in by_key["writer_body"]["content"]
    assert "网游写法方法卡" in by_key["writer_body"]["content"]
    assert "genre_context" in by_key["writer_body"]["module_keys"]
    assert "web_game" in modules["genre_context"]["content"]

    context = store.prompt_context(1)
    assert context["schema_version"] == "file-project-prompt-context/v1"
    assert "prompts" not in context
    assert {item["key"] for item in context["modules"]}.issuperset(
        {"core_context", "character_context", "genre_context", "writing_taskbook"}
    )
    missing = {item["key"]: item for item in context["modules"] if item.get("available") is False}
    assert "dialogue_context" in missing
    assert "验证灰狼掉落" in by_key["writing_taskbook"]["content"]
    assert "对话场面" not in by_key["writing_taskbook"]["content"]
    assert "补完整对话" in by_key["revision"]["content"]
    assert "file-writing-packet/v1" in modules["packet_context"]["content"]
    assert modules["packet_context"]["source"] == "file_project_store.writing_packet_compact_preview"
    assert "完整写作包仍由 writing_packet 接口返回" in modules["packet_context"]["content"]
    assert "game_world_simulation" not in by_key["writer_body"]["content"]
    assert by_key["writer_body"]["chars"] < 18000
    assert modules["packet_context"]["chars"] < 12000


def test_file_project_writing_packet_includes_enabled_skill_context(tmp_path, monkeypatch):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "outline": "A grounded webgame story.", "genre": "网游", "current_chapter": 0},
    )
    pack = tmp_path / "skill-pack"
    (pack / "skills" / "writer").mkdir(parents=True)
    (pack / "SKILL.md").write_text("---\nname: local-pack\n---\n\n# Local Pack", encoding="utf-8")
    (pack / "skills" / "writer" / "SKILL.md").write_text(
        "---\nname: writer\ndescription: 正文写作\n---\n\n写出自然对话。",
        encoding="utf-8",
    )
    registry = tmp_path / "registry"
    import_skill_pack_from_path(pack, root=registry)
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))

    store.update_project({"enabled_skill_ids": ["local-pack"]})
    packet = store.writing_packet(1)

    assert packet["skill_context"]["writer"][0]["skill_id"] == "local-pack"
    assert packet["skill_context"]["writer"][0]["modules"][0]["module_id"] == "writer"


def test_file_project_store_generates_next_chapter_without_api(tmp_path):
    root = tmp_path / "novel"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-file",
                "outline": "A grounded game story.",
                "genre": "webgame",
                "style": "plain",
                "current_chapter": 0,
                "world_facts": [],
                "characters": [
                    {
                        "name": "Night Ember",
                        "role": "protagonist",
                        "game_id": "Night Ember",
                        "goals": ["stay quiet"],
                        "memory": ["Entered the village."],
                        "current_emotion": "neutral",
                        "location": "village gate",
                        "game_panel": {"level": 1, "class_path": "apprentice", "currency": "0 gold"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(
                update={
                    "current_chapter": 1,
                    "timeline": [
                        TimelineEvent(
                            chapter_number=1,
                            summary="Night Ember checks the counter.",
                            impact="Chapter 1 closes with a visible cost.",
                        )
                    ],
                    "chapter_summaries": [
                        ChapterSummary(
                            chapter_number=1,
                            chapter_title="Generated One",
                            summary="Night Ember checks the counter.",
                        )
                    ],
                }
            )
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Generated One",
                body=_long_test_body("Night Ember checked the quest counter and left quietly."),
                cadence="manual",
                next_outline="Check costs.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Generated One",
                    "cadence": "manual",
                    "summary": "Night Ember checks the counter.",
                    "facts": ["No sale happened."],
                    "next_focus": "Check costs.",
                    "primary_conflict": "Low resources.",
                    "secondary_conflict": "Limited information.",
                    "event_beat": "Counter check.",
                },
            )

    generated = FileProjectStore(root).generate_next_chapter(engine=FakeEngine())

    assert generated["schema_version"] == "file-project-generate-next/v1"
    assert generated["chapter_number"] == 1
    assert (root / ".story-system" / "chapters" / "0001.json").exists()
    assert (root / "chapters" / "0001-Generated One.md").read_text(encoding="utf-8").startswith("Night Ember")
    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state["current_chapter"] == 1
    assert any(item["chapter_number"] == 1 for item in state["chapter_summaries"])
    assert any("Night Ember checks the counter." in item for item in state["world_facts"])
    assert state["time_state"]["server_day"] == 1
    assert state["time_state"]["chapter_time_spans"][0]["chapter_number"] == 1
    project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert project["current_focus"] == "Check costs."
    assert project["world_blueprint"]["continuity_state"]["latest_title"] == "Generated One"
    assert project["world_blueprint"]["time_state"]["current_scene_time"] == "第1章章末"
    assert project["character_profiles"][0]["name"] == "Night Ember"
    assert project["character_profiles"][0]["game_panel"]["updated_chapter"] == 1
    packet = FileProjectStore(root).writing_packet(2)
    assert packet["state"]["time_state"]["current_scene_time"] == "第1章章末"
    latest_commit = json.loads((root / ".story-system" / "commits" / "latest_commit.json").read_text(encoding="utf-8"))
    assert latest_commit["operation"] == "generate"


def test_file_project_store_does_not_persist_unaccepted_review_lessons(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root)

    store.write_chapter(
        chapter_number=1,
        title="Lesson",
        body="Night Ember walked to the slope.",
        next_outline="Continue.",
        summary="Short weak scene.",
    )

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert state["writing_lessons"] == []
    assert project["world_blueprint"]["writing_learning"]["lessons"] == []


def test_file_project_writing_packet_requires_fast_visible_progression(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "genre": "webgame",
            "current_chapter": 4,
            "current_focus": "Turn the hidden route into a visible level gain.",
            "world_facts": [],
        },
    )

    packet = store.writing_packet(5)

    assert any("前10章节奏要快" in rule for rule in packet["style_rules"])
    assert any("连续两章不能只拿线索不给成长" in rule for rule in packet["style_rules"])
    assert packet["state"]["current_focus"] == "Turn the hidden route into a visible level gain."


def test_file_project_writing_packet_exposes_next_chapter_direction_options(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "网游开服，夜烬低调验证千倍爆率。",
            "genre": "网游",
            "style": "番茄升级流",
            "current_chapter": 1,
            "world_facts": ["现实催租压力未解决。"],
            "progression_ledger": {
                "economy": {"game_currency": "0铜", "inventory": {"灰狼毒腺": 8}},
                "quests": {"清道夫委托": "未完成，还差2份毒腺"},
            },
        },
    )

    packet = store.writing_packet(2)

    choices = packet["chapter_direction_options"]
    assert choices["recommended_id"] == "trade-bridge"
    assert [item["id"] for item in choices["options"]] == [
        "trade-bridge",
        "chaos-seed-trace",
        "guild-ecology",
    ]
    assert any("现实" in item["reader_promise"] for item in choices["options"])


def test_file_project_writing_packet_does_not_offer_branches_over_explicit_chapter_outline(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "genre": "网游",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    (store.webnovel_dir / "outline.json").write_text(
        json.dumps(
            {
                "overall": {"story": "夜烬低调验证混沌之种。"},
                "chapters": [
                    {
                        "chapter_number": 2,
                        "title": "还差八份毒腺",
                        "goal": "补齐八份毒腺并完成清道夫委托。",
                        "payoff": "升到Lv.3。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    packet = store.writing_packet(2)

    assert packet["outline_context"]["chapter"]["title"] == "还差八份毒腺"
    assert packet["chapter_direction_options"] == {}


def test_file_project_generate_next_accepts_selected_chapter_direction(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "网游开服，夜烬低调验证千倍爆率。",
            "genre": "网游",
            "style": "番茄升级流",
            "current_chapter": 1,
            "world_facts": ["现实催租压力未解决。"],
            "progression_ledger": {
                "economy": {"game_currency": "0铜", "inventory": {"灰狼毒腺": 8}},
                "quests": {"清道夫委托": "未完成，还差2份毒腺"},
            },
        },
    )
    captured = {}

    class FakeEngine:
        def generate_next_chapter(self, story):
            captured["direction"] = story.progression_ledger["chapter_direction"]
            updated_story = story.model_copy(update={"current_chapter": 2})
            return SimpleNamespace(
                chapter_number=2,
                chapter_title="混沌再闪",
                body=_long_test_body("Night Ember hid the strange fragment and counted the cost."),
                cadence="manual",
                next_outline="Check the recorded trace.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "混沌再闪",
                    "cadence": "manual",
                    "summary": "Night Ember sees a hidden trace.",
                    "facts": ["Selected chaos direction."],
                    "next_focus": "Check the recorded trace.",
                    "primary_conflict": "Hidden trace.",
                    "secondary_conflict": "No one else can know.",
                    "event_beat": "Trace appears.",
                },
                quality_report={"ok": True},
            )

    generated = store.generate_next_chapter(engine=FakeEngine(), chapter_direction_id="chaos-seed-trace")

    assert generated["chapter_number"] == 2
    assert captured["direction"]["id"] == "chaos-seed-trace"
    assert "未解析" in captured["direction"]["wow_beat"] or "残片" in captured["direction"]["wow_beat"]


def test_file_project_writing_packet_exposes_outline_constraints(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "Follow the arc.",
            "world_blueprint": {
                "current_arc": "Opening arc.",
                "opening_arc": {
                    "golden_three_chapters": {"1": {"payoff": "first sale"}},
                    "chapter_beats": [
                        {
                            "chapter": 2,
                            "title": "First Sale",
                            "required_payoff": "finish first sale",
                            "ending_hook": "buyer asks source",
                        }
                    ],
                },
                "volume_plan": {"volume_title": "Newbie Village"},
                "longform_framework": {"progression_ladder": ["Lv.1-5"]},
                "chapter_formula": ["goal-cost-payoff-hook"],
                "progression_rules": ["visible gain every chapter"],
                "forbidden_breaks": ["do not skip the outline"],
            },
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )

    packet = store.writing_packet(2)

    assert packet["target_chars"] == {"min": 3800, "max": 5500}
    assert packet["chapter_number"] == 2
    assert any("正文必须满足目标字数区间" in lock for lock in packet["hard_locks"])
    assert any("当前主线焦点：Follow the arc." in lock for lock in packet["hard_locks"])
    assert packet["scene_cards"][0]["title"] == "First Sale"
    assert packet["scene_cards"][0]["purpose"] == "finish first sale"
    assert packet["scene_cards"][0]["ending_hook"] == "buyer asks source"
    assert isinstance(packet["character_cards"], list)
    outline_context = packet["outline_context"]
    assert set(outline_context) == {"overall", "active_arc", "chapter"}
    assert outline_context["active_arc"]["goal"] == "Opening arc."
    assert outline_context["chapter"]["chapter_number"] == 2
    assert outline_context["chapter"]["payoff"] == "finish first sale"
    assert outline_context["chapter"]["ending_hook"] == "buyer asks source"
    constraints = packet["outline_constraints"]
    assert "current_arc" not in constraints
    assert "opening_arc" not in constraints
    assert constraints["volume_plan"]["volume_title"] == "Newbie Village"
    assert constraints["longform_framework"]["progression_ladder"] == ["Lv.1-5"]
    assert constraints["chapter_formula"] == ["goal-cost-payoff-hook"]
    assert set(constraints) == {
        "volume_plan",
        "longform_framework",
        "chapter_formula",
        "forbidden_breaks",
    }
    assert "progression_rules" not in constraints
    assert "reality_bridge_rules" not in constraints
    assert constraints["forbidden_breaks"] == ["do not skip the outline"]
    assert "visible gain every chapter" in packet["hard_locks"]
    assert isinstance(packet["state"]["characters"], list)


def test_compact_prompt_preview_keeps_only_governance_outline_constraints(tmp_path):
    store = FileProjectStore(tmp_path / "novel")

    preview = store._compact_prompt_preview_packet(
        {
            "outline_constraints": {
                "volume_plan": {"title": "第一卷"},
                "longform_framework": {"chapters": 300},
                "chapter_formula": ["目标-代价-收益-钩子"],
                "progression_rules": ["每章可见成长"],
                "forbidden_breaks": ["不得跳过大纲"],
                "reality_bridge_rules": ["现实到账需结算"],
            }
        }
    )

    assert set(preview["outline_constraints"]) == {
        "volume_plan",
        "longform_framework",
        "chapter_formula",
        "forbidden_breaks",
    }


def test_writing_packet_keeps_only_global_progression_governance_in_hard_locks(tmp_path):
    governance_rule = "前十章每章至少完成一次可见成长。"
    descriptive_rule = "成长节奏随剧情自然推进。"
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=3,
        chapter_update={
            "title": "村口闲谈",
            "goal": "拜访灰烬村村长",
            "action": "询问后坡天气",
            "payoff": "确认明日路线",
        },
    )
    project = store.project()
    project["world_blueprint"]["progression_rules"] = [
        governance_rule,
        descriptive_rule,
    ]
    store._write_json(store.webnovel_dir / "project.json", project)

    packet = store.writing_packet(3)

    assert governance_rule in packet["hard_locks"]
    assert descriptive_rule not in packet["hard_locks"]
    assert "progression_rules" not in packet["project"]["world_blueprint"]


def test_writing_packet_recognizes_chinese_and_english_progression_governance(tmp_path):
    chinese_rule = "经验只来自可验证行动"
    english_rule = "Visible gain every chapter"
    descriptive_rule = "Lv.10完成转职"
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=3,
        chapter_update={
            "title": "Village conversation",
            "goal": "Ask about tomorrow's route",
            "action": "Record the weather",
            "payoff": "Confirm the departure time",
        },
    )
    project = store.project()
    project["world_blueprint"]["progression_rules"] = [
        chinese_rule,
        english_rule,
        descriptive_rule,
    ]
    store._write_json(store.webnovel_dir / "project.json", project)

    packet = store.writing_packet(3)

    assert chinese_rule in packet["hard_locks"]
    assert english_rule in packet["hard_locks"]
    assert descriptive_rule not in packet["hard_locks"]


def test_writing_packet_does_not_duplicate_scoped_progression_governance_rule(tmp_path):
    governance_rule = "升级必须留下可验证记录。"
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=3,
        chapter_update={
            "title": "第一次升级",
            "goal": "积累经验并升级",
            "action": "核对成长记录",
            "payoff": "等级提升",
        },
    )
    project = store.project()
    project["world_blueprint"]["progression_rules"] = [governance_rule]
    store._write_json(store.webnovel_dir / "project.json", project)

    packet = store.writing_packet(3)

    assert governance_rule in packet["project"]["world_blueprint"]["progression_rules"]
    assert governance_rule not in packet["hard_locks"]


def test_writing_packet_includes_only_relevant_monster_profiles_at_top_level(tmp_path):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={
            "title": "灰狼坡",
            "goal": "追踪灰狼",
            "action": "观察灰狼的扑咬路线",
            "payoff": "找到灰狼巢穴",
        },
    )
    project = store.project()
    project["world_blueprint"]["monster_profiles"] = [
        {"name": "灰狼", "stats": {"hp": 90}},
        {"name": "史莱姆", "stats": {"hp": 30}},
    ]
    store._write_json(store.webnovel_dir / "project.json", project)

    packet = store.writing_packet(1)

    assert packet["monster_profiles"] == [{"name": "灰狼", "stats": {"hp": 90}}]
    assert "monster_profiles" not in packet["project"]["world_blueprint"]


def test_writing_packet_limits_and_deep_copies_relevant_monster_profiles(tmp_path, monkeypatch):
    names = [f"怪物{i}" for i in range(1, 8)]
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={
            "title": "怪物巡查",
            "goal": "依次观察" + "、".join(names),
            "action": "记录全部目标的行动",
            "payoff": "完成图鉴核对",
        },
    )
    project = store.project()
    profiles = [
        {"name": name, "stats": {"hp": index}}
        for index, name in enumerate(names, start=1)
    ]
    profiles.append({"name": "史莱姆", "stats": {"hp": 99}})
    project["world_blueprint"]["monster_profiles"] = profiles
    monkeypatch.setattr(store, "project", lambda: project)

    packet = store.writing_packet(1)

    assert [item["name"] for item in packet["monster_profiles"]] == names[:6]
    packet["monster_profiles"][0]["stats"]["hp"] = 999
    assert profiles[0]["stats"]["hp"] == 1


def test_rewriting_old_chapter_removes_future_focus_from_entire_writing_packet(tmp_path):
    future_focus = "下一章去白河仓库交易材料并支付现实房租"
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={
            "title": "灰狼坡",
            "goal": "击败灰狼",
            "action": "使用法杖清理怪群",
            "payoff": "获得游戏经验",
        },
        current_chapter=3,
        current_focus=future_focus,
    )

    packet = store.writing_packet(1)

    assert future_focus not in json.dumps(packet, ensure_ascii=False)
    assert "current_focus" not in packet["project"]
    assert packet["state"].get("current_focus") in (None, "")
    assert packet["chapter_direction_options"] == {}


def test_rewriting_chapter_uses_only_chapters_before_target_for_writer_context(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={"story_id": "s-file", "current_chapter": 3, "world_facts": []},
    )
    chapter_markers = {}
    review_markers = {}
    for number in range(1, 4):
        next_focus = f"CHAPTER_{number}_NEXT_FOCUS_UNIQUE"
        event_focus = f"CHAPTER_{number}_EVENT_FOCUS_UNIQUE"
        review_marker = f"CHAPTER_{number}_REVIEW_UNIQUE"
        chapter_markers[number] = (next_focus, event_focus)
        review_markers[number] = review_marker
        store._write_json(
            store.story_system_dir / "chapters" / f"{number:04d}.json",
            {
                "chapter_number": number,
                "chapter_title": f"Chapter {number}",
                "body": f"Completed chapter {number}.",
                "chapter_summary": {"summary": f"Summary {number}"},
                "next_focus": next_focus,
                "next_outline": next_focus,
                "event_plan": {"next_focus": event_focus},
            },
        )
        store._write_json(
            store.story_system_dir / "reviews" / f"{number:04d}.json",
            {"ok": True, "issues": [review_marker]},
        )

    first_packet = store.writing_packet(1)
    first_json = json.dumps(first_packet, ensure_ascii=False)

    assert first_packet["latest_chapter_number"] == 0
    assert first_packet["recent_chapters"] == []
    assert first_packet["latest_event_plan"] == {}
    assert first_packet["latest_review"] == {}
    for number in range(1, 4):
        assert chapter_markers[number][0] not in first_json
        assert chapter_markers[number][1] not in first_json
        assert review_markers[number] not in first_json

    second_packet = store.writing_packet(2)
    second_json = json.dumps(second_packet, ensure_ascii=False)

    assert second_packet["latest_chapter_number"] == 1
    assert [item["chapter_number"] for item in second_packet["recent_chapters"]] == [1]
    assert second_packet["latest_event_plan"]["next_focus"] == chapter_markers[1][1]
    assert second_packet["latest_review"]["issues"] == [review_markers[1]]
    assert chapter_markers[1][0] in second_json
    assert chapter_markers[1][1] in second_json
    assert review_markers[1] in second_json
    for number in (2, 3):
        assert chapter_markers[number][0] not in second_json
        assert chapter_markers[number][1] not in second_json
        assert review_markers[number] not in second_json


def test_trade_chapter_writing_packet_only_includes_relevant_world_modules(tmp_path):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={
            "title": "第一笔交易",
            "goal": "匿名寄售材料并等待现实到账",
            "action": "在交易行出售材料后提现支付房租账单",
            "payoff": "完成第一笔现实结算",
        },
    )

    packet = store.writing_packet(1)
    blueprint = packet["project"]["world_blueprint"]

    assert blueprint["economy_rules"]
    assert blueprint["reality_bridge_rules"]
    assert "quest_rules" not in blueprint
    assert "quest_network" not in blueprint
    assert "progression_rules" not in blueprint
    assert "server_runtime" not in blueprint
    assert "monster_profiles" not in blueprint
    assert len(flatten_selected_rules(blueprint)) <= 8


def test_quest_chapter_writing_packet_includes_only_matching_chain(tmp_path):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=2,
        chapter_update={
            "title": "后坡巡查",
            "goal": "提交清道夫委托，开启后坡巡查",
            "action": "向灰烬村守卫队登记巡查路线",
            "payoff": "取得后坡调查权限",
        },
    )

    packet = store.writing_packet(2)
    blueprint = packet["project"]["world_blueprint"]
    chains = blueprint["quest_network"]["active_chains"]

    assert [chain["name"] for chain in chains] == ["灰烬村异常链"]
    assert blueprint["quest_rules"]
    assert "server_runtime" not in blueprint
    assert len(flatten_selected_rules(blueprint)) <= 8


def test_writing_packet_includes_reality_bridge_rules_for_relevant_chapter_only(tmp_path):
    root = tmp_path / "novel"
    reality_rules = [f"现实规则{i}" for i in range(1, 9)]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "完成本章计划。",
            "world_blueprint": {
                "reality_bridge_rules": reality_rules,
                "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
            },
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0]["goal"] = "确认第一笔收入到账并支付房租"
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert "reality_bridge_rules" not in packet["outline_constraints"]
    scoped_world = packet["project"]["world_blueprint"]
    assert scoped_world["reality_bridge_rules"] == reality_rules
    assert len(flatten_selected_rules(scoped_world)) <= 8
    assert not any(rule in packet["hard_locks"] for rule in reality_rules)


def test_writing_packet_omits_reality_bridge_rules_for_game_only_chapter(tmp_path):
    root = tmp_path / "novel"
    reality_rules = ["游戏收益只能通过合规渠道进入现实", "现实资金变化必须留下可核对记录"]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "清理矿洞深处的怪物。",
            "world_blueprint": {
                "reality_bridge_rules": reality_rules,
                "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
            },
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0].update(
        {
            "goal": "击败矿洞狼王",
            "action": "组队进入洞穴并清理怪群",
            "payoff": "获得新装备和经验",
            "ending_hook": "更深处传来咆哮",
        }
    )
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert "reality_bridge_rules" not in packet["outline_constraints"]
    assert "reality_bridge_rules" not in packet["project"]["world_blueprint"]
    assert not any(rule in packet["hard_locks"] for rule in reality_rules)


@pytest.mark.parametrize("game_only_focus", ["金币收入到账", "任务奖励到账"])
def test_writing_packet_does_not_treat_game_income_as_reality_bridge(game_only_focus, tmp_path):
    root = tmp_path / "novel"
    reality_rules = ["现实资金变化必须留下可核对记录"]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": game_only_focus,
            "world_blueprint": {"reality_bridge_rules": reality_rules},
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0].update(
        {
            "goal": game_only_focus,
            "action": "领取奖励并整理背包",
            "payoff": "获得游戏金币",
        }
    )
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert "reality_bridge_rules" not in packet["outline_constraints"]
    assert "reality_bridge_rules" not in packet["project"]["world_blueprint"]


def test_writing_packet_ignores_next_focus_when_rewriting_game_only_chapter(tmp_path):
    root = tmp_path / "novel"
    reality_rules = ["现实资金变化必须留下可核对记录"]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "筹钱支付房租账单",
            "world_blueprint": {"reality_bridge_rules": reality_rules},
        },
        state={"story_id": "s-file", "current_chapter": 3, "world_facts": []},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0].update(
        {
            "goal": "击败矿洞狼王",
            "action": "进入洞穴清理怪群",
            "payoff": "获得新装备和经验",
            "ending_hook": "更深处传来咆哮",
        }
    )
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert "reality_bridge_rules" not in packet["outline_constraints"]
    assert "reality_bridge_rules" not in packet["project"]["world_blueprint"]


def test_state_restores_protagonist_character_card_from_ledger(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "current_chapter": 4,
            "world_facts": [],
            "characters": [
                {
                    "name": "药剂师洛婶",
                    "role": "服务NPC",
                    "goals": ["收任务材料"],
                    "memory": ["药剂铺NPC。"],
                }
            ],
            "progression_ledger": {
                "protagonist": {
                    "real_name": "苏叶",
                    "game_id": "夜烬",
                    "class_path": "见习冒险者（未转职）",
                    "level": "Lv.3",
                    "exp": "196/300",
                    "hp": "91/140",
                    "mp": "22/80",
                    "skills": ["基础火球术", "火线牵引"],
                },
                "economy": {"game_currency": "空", "inventory": {"灰狼毒腺": 11}},
                "equipment": {"weapon": "新手法杖", "durability": "10/12"},
            },
        },
    )

    characters = store.state()["characters"]
    protagonist = next(character for character in characters if character["name"] == "苏叶")

    assert protagonist["role"] == "protagonist"
    assert protagonist["game_id"] == "夜烬"
    assert protagonist["game_panel"]["level"] == "Lv.3"
    assert protagonist["game_panel"]["inventory"]["灰狼毒腺"] == 11


def test_state_does_not_append_legacy_defaults_to_saved_protagonist(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "world_facts": [],
            "characters": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "game_id": "夜烬",
                    "goals": ["在《神域》中完成清道夫委托。"],
                    "memory": ["现实余额332.60元。"],
                    "game_panel": {
                        "game_id": "夜烬",
                        "level": "Lv.2",
                        "class_path": "见习者（未转职）",
                        "currency": "39铜币",
                    },
                }
            ],
            "progression_ledger": {
                "protagonist": {
                    "real_name": "苏叶",
                    "game_id": "夜烬",
                    "level": "Lv.2",
                    "class_path": "见习者（未转职）",
                },
                "economy": {"game_currency": "39铜币"},
            },
        },
    )

    protagonist = next(card for card in store.state()["characters"] if card["name"] == "苏叶")

    assert protagonist["goals"] == ["在《神域》中完成清道夫委托。"]
    assert protagonist["memory"] == ["现实余额332.60元。"]
    assert protagonist["game_panel"]["class_path"] == "见习者（未转职）"
    assert protagonist["game_panel"]["currency"] == "39铜币"


def test_state_overlays_ledger_status_on_saved_protagonist_profile(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "current_chapter": 2,
            "genre_plugin_ids": ["game_webnovel"],
            "world_facts": [],
            "characters": [
                {
                    "name": "苏叶",
                    "role": "主角",
                    "goals": ["隐藏混沌之种"],
                    "game_panel": {"level": "Lv.1", "currency": "0铜币"},
                    "real_state": {"current": {"balance": "27.60元"}},
                }
            ],
            "progression_ledger": {
                "protagonist": {
                    "real_name": "苏叶",
                    "game_id": "夜烬",
                    "level": "Lv.2",
                    "class_path": "见习者（未转职）",
                    "exp": "75/200",
                },
                "economy": {"game_currency": "39铜币", "inventory": {"灰狼毒腺": 2}},
                "real": {"end_balance": "332.60元"},
            },
        },
    )

    protagonist = next(card for card in store.state()["characters"] if card["name"] == "苏叶")

    assert protagonist["goals"] == ["隐藏混沌之种"]
    assert protagonist["game_panel"]["level"] == "Lv.2"
    assert protagonist["game_panel"]["exp"] == "75/200"
    assert protagonist["game_panel"]["currency"] == "39铜币"
    assert protagonist["game_panel"]["inventory"] == {"灰狼毒腺": 2}
    assert protagonist["real_state"]["current"]["balance"] == "332.60元"


def test_completed_quest_is_not_reintroduced_as_active(tmp_path):
    store = FileProjectStore(tmp_path)
    state = {
        "story_id": "s-file",
        "current_chapter": 1,
        "genre_plugin_ids": ["game_webnovel"],
        "progression_ledger": {
            "quests": {
                "active": "灰狼材料收集：2/10",
                "available": "清道夫委托：提交灰狼毒腺×10；当前2/10",
            }
        },
    }
    chapter = {
        "chapter_number": 1,
        "body": "任务：灰狼材料收集。系统提示：完成任务：灰狼材料收集，获得经验100点。",
    }

    synced = store._sync_ledger_from_chapter_body(state, chapter)

    quests = synced["progression_ledger"]["quests"]
    assert "active" not in quests
    assert quests["灰狼材料收集"] == "已完成"


def test_negated_quest_completion_does_not_mark_quest_completed(tmp_path):
    store = FileProjectStore(tmp_path)
    state = {
        "story_id": "s-file",
        "current_chapter": 1,
        "genre_plugin_ids": ["game_webnovel"],
        "progression_ledger": {"quests": {}},
    }
    chapter = {
        "chapter_number": 1,
        "body": "任务：灰狼材料收集。他还没有完成任务：灰狼材料收集。",
    }

    synced = store._sync_ledger_from_chapter_body(state, chapter)

    quests = synced["progression_ledger"]["quests"]
    assert quests["active"] == "灰狼材料收集"
    assert "灰狼材料收集" not in quests


def test_state_adds_proposed_character_card_before_outline_appearance(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "第5章按大纲写担保名单：确认白河仓库收购规则和交易风险，收购方开始追问材料来源。",
            "world_blueprint": {
                "opening_arc": {
                    "chapter_beats": [
                        {
                            "chapter": 5,
                            "title": "担保名单",
                            "required_payoff": "确认白河仓库收购规则和交易风险",
                            "ending_hook": "收购方开始追问材料来源",
                        }
                    ]
                }
            },
        },
        state={"story_id": "s-file", "current_chapter": 4, "world_facts": []},
    )

    characters = store.state()["characters"]
    proposed = next(character for character in characters if character["name"] == "白河仓库收购方")

    assert proposed["lifecycle_state"] == "proposed"
    assert proposed["last_proposed_chapter"] == 5
    assert "材料来源" in proposed["memory"][0]


def test_chapter_entity_keeps_white_river_buyer_proposed_until_real_appearance(tmp_path):
    store = FileProjectStore(tmp_path / "novel")

    mention_only = store._chapter_entity_cards(
        {
            "chapter_number": 1,
            "chapter_title": "灰狼坡到账",
            "body": "帖子里的收购人ID叫白河仓库，认证是材料商。",
        }
    )
    proposed = next(card for card in mention_only if card["name"] == "白河仓库收购方")

    assert proposed["lifecycle_state"] == "proposed"
    assert proposed["last_approved_chapter"] == 0

    real_appearance = store._chapter_entity_cards(
        {
            "chapter_number": 5,
            "chapter_title": "担保名单",
            "body": "白河仓库的人追问材料来源，收购方问这批灰粉是不是从灰石裂缝来的。",
        }
    )
    active = next(card for card in real_appearance if card["name"] == "白河仓库收购方")

    assert active["lifecycle_state"] == "active"
    assert active["last_approved_chapter"] == 5


def test_state_sanitizes_placeholder_facts_from_writing_context(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "current_chapter": 2,
            "world_facts": ["manual draft", "第2章事实：夜烬仍为Lv.1见习冒险者（未转职）", "fresh fact"],
            "chapter_summaries": [
                {
                    "chapter_number": 2,
                    "chapter_title": "Chapter Two",
                    "facts": ["manual draft", "fresh chapter fact"],
                    "primary_conflict": "manual draft",
                    "secondary_conflict": {"note": "manual draft", "source": "secondary_conflict"},
                    "event_beat": {"turn": "real beat"},
                }
            ],
            "memory_index": [
                {"chapter_number": 2, "chapter_title": "Chapter Two", "facts": ["夜烬仍为Lv.1见习冒险者", "clean memory"]}
            ],
        },
    )

    state = store.state()

    assert state["world_facts"] == ["fresh fact"]
    assert state["chapter_summaries"][0]["facts"] == ["fresh chapter fact"]
    assert state["chapter_summaries"][0]["primary_conflict"] == {}
    assert state["chapter_summaries"][0]["secondary_conflict"] == {}
    assert state["chapter_summaries"][0]["event_beat"] == {"turn": "real beat"}
    assert state["memory_index"][0]["facts"] == ["clean memory"]


def test_rewrite_latest_chapter_keeps_canonical_state_and_summary(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )
    for number in range(1, 5):
        store.write_chapter(
            chapter_number=number,
            title=f"Chapter {number}",
            body=f"Night Ember chapter {number}.",
            summary=f"Accepted summary {number}.",
        )
    chapter3_path = root / ".story-system" / "chapters" / "0003.json"
    chapter3 = json.loads(chapter3_path.read_text(encoding="utf-8"))
    chapter3["updated_story"] = {
        "story_id": "s-file",
        "outline": "A grounded game story.",
        "genre": "webgame",
        "style": "plain",
        "current_chapter": 3,
        "progression_ledger": {"protagonist": {"level": "Lv.1"}},
    }
    chapter3_path.write_text(json.dumps(chapter3, ensure_ascii=False), encoding="utf-8")
    state_path = root / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_chapter"] = 4
    state["progression_ledger"] = {"protagonist": {"level": "Lv.2"}}
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    store.rewrite_chapter(
        chapter_number=4,
        title="Chapter 4",
        body="Night Ember keeps the hidden route and returns to repair.",
        instructions=["hidden route remains"],
    )

    state_after = json.loads(state_path.read_text(encoding="utf-8"))
    chapter4 = json.loads((root / ".story-system" / "chapters" / "0004.json").read_text(encoding="utf-8"))
    assert state_after["progression_ledger"]["protagonist"]["level"] == "Lv.2"
    assert chapter4["chapter_summary"]["summary"] == "Accepted summary 4."
    assert chapter4["chapter_summary"]["summary"] != "Manual rewrite chapter 4."


def test_persist_bundle_ignores_stale_bundle_updated_story(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": ["source:canonical"]},
    )

    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Fresh Chapter",
        body=_long_test_body("Night Ember keeps the current ledger clean."),
        cadence="manual",
        next_outline="Continue from fresh facts.",
        updated_story={
            "story_id": "s-file",
            "current_chapter": 99,
            "world_facts": ["stale fact should not return"],
        },
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "chapter_title": "Fresh Chapter",
            "cadence": "manual",
            "summary": "Fresh summary wins.",
            "facts": ["fresh fact from summary"],
            "next_focus": "Continue from fresh facts.",
            "primary_conflict": "Clean state.",
            "secondary_conflict": "Old snapshot.",
            "event_beat": "Persist.",
        },
    )

    store.persist_bundle(bundle)

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    facts = "\n".join(state["world_facts"])
    assert "fresh fact from summary" in facts
    assert "Fresh summary wins." in facts
    assert "stale fact should not return" not in facts
    assert state["current_chapter"] == 1


def test_persist_bundle_uses_runtime_updated_story(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "progression_ledger": {"economy": {"game_currency": "0铜"}},
            "world_facts": ["source:canonical"],
        },
    )

    bundle = SimpleNamespace(
        chapter_number=2,
        chapter_title="Ledger Chapter",
        body=_long_test_body("Night Ember turns the completed quest into a clean ledger."),
        cadence="manual",
        next_outline="Continue from the updated ledger.",
        updated_story={
            "story_id": "s-file",
            "current_chapter": 2,
            "progression_ledger": {"economy": {"game_currency": "5铜"}},
            "world_facts": ["source:canonical"],
            "timeline": [{"chapter_number": 2, "label": "第2章"}],
            "chapter_summaries": [
                {"chapter_number": 2, "chapter_title": "Ledger Chapter", "summary": "ledger settles"}
            ],
        },
        chapter_summary={
            "chapter_title": "Ledger Chapter",
            "cadence": "manual",
            "summary": "The quest reward and costs settle into the ledger.",
            "facts": ["ledger fact"],
            "next_focus": "Continue from the updated ledger.",
            "primary_conflict": "Clean state.",
            "secondary_conflict": "Old snapshot.",
            "event_beat": "Persist.",
        },
    )

    store.persist_bundle(bundle)

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state["progression_ledger"]["economy"]["game_currency"] == "5铜"
    assert state["current_chapter"] == 2


def test_rewrite_chapter_uses_canonical_state_not_embedded_snapshot(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": ["source:canonical"]},
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "Old Chapter",
        "body": "Old body.",
        "next_outline": "Old next.",
        "updated_story": {
            "story_id": "s-file",
            "current_chapter": 1,
            "world_facts": ["stale embedded snapshot"],
        },
        "chapter_summary": {
            "chapter_title": "Old Chapter",
            "cadence": "manual",
            "summary": "Old summary.",
            "facts": ["old fact"],
            "next_focus": "Old next.",
            "primary_conflict": "Old.",
            "secondary_conflict": "Old.",
            "event_beat": "Old.",
        },
    }
    (root / ".story-system" / "chapters" / "0001.json").write_text(json.dumps(chapter, ensure_ascii=False), encoding="utf-8")
    (root / ".story-system" / "reviews" / "0001.json").write_text(
        json.dumps({"writing_review": {"pass": True, "issues": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "chapters" / "0001-Old Chapter.md").write_text("Old body.", encoding="utf-8")

    store.rewrite_chapter(
        chapter_number=1,
        title="Rewritten Chapter",
        body="Night Ember rewrites only the live facts.",
        instructions=["fresh rewrite fact"],
    )

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    facts = "\n".join(state["world_facts"])
    assert "fresh rewrite fact" in facts
    assert "stale embedded snapshot" not in facts


def test_regenerate_blocks_frozen_chapter(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "current_chapter": 1,
            "world_facts": [],
            "progression_ledger": {"continuity_lock": {"chapters_frozen": [1]}},
        },
    )

    try:
        store.regenerate_chapter(1, engine=SimpleNamespace(generate_next_chapter=lambda story: None))
    except ValueError as exc:
        assert str(exc) == "chapter_frozen:1:regenerate"
    else:
        raise AssertionError("expected frozen chapter regeneration to fail")


def test_freeze_opening_baseline_rebuilds_state_and_blocks_rewrites(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "Opening test.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 3,
            "world_facts": [],
            "timeline": ["chapter 1: stale shell"],
            "chapter_summaries": [
                {"chapter_title": "One", "summary": "stale unnumbered shell"},
                {"chapter_number": 2, "chapter_title": "Old Two", "summary": "stale two"},
            ],
        },
    )
    store.write_chapter(chapter_number=1, title="One", body="Night Ember sees the grey prompt.", summary="First accepted.")
    store.write_chapter(
        chapter_number=2,
        title="Two",
        body="Night Ember submits 清道夫委托已提交 and 等级升到Lv.2. 钱袋：空。背包：粗糙狼皮×7，小法力药水×1。",
        summary="Second accepted.",
        instructions=["等级升到Lv.2", "钱袋：空", "灰狼毒腺×0", "粗糙狼皮×7", "小法力药水×1"],
    )
    store.write_chapter(chapter_number=3, title="Three", body="Night Ember reaches 后坡登记 and 灰石裂缝.", summary="Third accepted.")

    frozen = store.freeze_opening_baseline(through_chapter=3)

    assert frozen["chapters_frozen"] == [1, 2, 3]
    assert frozen["preflight"]["ok"] is True
    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert [item["chapter_number"] for item in state["chapter_summaries"]] == [1, 2, 3]
    assert "stale unnumbered shell" not in json.dumps(state, ensure_ascii=False)
    assert state["progression_ledger"]["protagonist"]["level"] == "Lv.2"
    assert state["progression_ledger"]["economy"]["game_currency"] == "空"
    assert state["progression_ledger"]["economy"]["inventory"]["灰狼毒腺"] == 0
    assert state["progression_ledger"]["continuity_lock"]["opening_baseline"]["next_chapter"] == 4
    project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    continuity = project["world_blueprint"]["continuity_state"]
    assert [item["chapter_number"] for item in continuity["chapter_facts"]] == [1, 2, 3]
    assert "stale two" not in json.dumps(project, ensure_ascii=False)

    try:
        store.write_chapter(chapter_number=1, title="Bad Rewrite", body="Should not write.", overwrite=True)
    except ValueError as exc:
        assert str(exc) == "chapter_frozen:1:write"
    else:
        raise AssertionError("expected frozen write to fail")


def test_opening_preflight_reports_stale_tokens_after_baseline(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "Opening test.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )
    store.write_chapter(chapter_number=1, title="One", body="Night Ember starts.", summary="First.")
    store.freeze_opening_baseline(through_chapter=1)
    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    state["world_facts"].append("旧设定：元素法师学徒。")
    (root / ".webnovel" / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    report = FileProjectStore(root).opening_preflight(next_chapter=2)

    assert report["ok"] is False
    assert "元素法师学徒" in report["issues"][0]


def test_file_project_store_dedupes_npc_aliases_and_filters_surface_entities(tmp_path):
    store = FileProjectStore(tmp_path / "novel")
    chapter = {
        "chapter_number": 1,
        "chapter_title": "药剂铺窗口",
        "body": "夜烬走进药剂铺。灰头巾老妇人抬头。公共频道还在滚动。清道夫委托写在木牌上。",
        "chapter_summary": {"summary": "夜烬问药剂师。"},
    }

    cards = store._merge_character_cards([], store._chapter_entity_cards(chapter))

    assert [card["name"] for card in cards] == ["药剂师洛婶"]
    assert cards[0]["role"] == "服务NPC"
    assert "药剂师NPC" not in {card["name"] for card in cards}
    assert "药剂铺老妇人" not in {card["name"] for card in cards}
    assert "公共频道" not in {card["name"] for card in cards}
    assert "清道夫委托" not in {card["name"] for card in cards}


def test_file_project_store_filters_stale_non_character_profiles(tmp_path):
    store = FileProjectStore(tmp_path / "novel")
    project = {
        "project_id": "p-file",
        "character_profiles": [
            {"name": "公共频道", "role": "玩家群体", "memory": ["旧噪音。"]},
            {"name": "药剂铺老妇人", "role": "服务NPC", "memory": ["旧药剂铺卡。"]},
        ],
    }
    state = {
        "characters": [
            {"name": "药剂师NPC", "role": "服务NPC", "memory": ["第1章：委托十份一批。"]},
            {"name": "清道夫委托", "role": "任务线", "memory": ["不是人物。"]},
        ]
    }
    chapter = {
        "chapter_number": 1,
        "chapter_title": "药剂铺窗口",
        "body": "夜烬问药剂师。",
        "chapter_summary": {
            "chapter_title": "药剂铺窗口",
            "cadence": "urgent",
            "summary": "夜烬问药剂师。",
            "facts": ["药剂铺十份一批。"],
            "next_focus": "回灰狼坡。",
            "primary_conflict": "材料不足。",
            "secondary_conflict": "0铜。",
            "event_beat": "窗口规则。",
        },
    }

    synced = store._sync_project_after_chapter(project, state, chapter)

    names = [profile["name"] for profile in synced["character_profiles"]]
    assert names == ["药剂师洛婶"]
    assert synced["character_profiles"][0]["memory"][-1] == "第1章：委托十份一批。"


def test_sync_project_after_chapter_applies_relationship_state_changes(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    project = {
        "project_id": "p-file",
        "relationship_graph": [
            {"source": "Lin Zhao", "target": "Zhao Heng", "origin": "first meeting", "trust": 40, "tension": 20}
        ],
    }
    state = {
        "characters": [
            {
                "name": "Lin Zhao",
                "role": "protagonist",
                "relationships": {
                    "Zhao Heng": {"target": "Zhao Heng", "bond": "open rivals", "trust": 10, "tension": 85}
                },
            }
        ]
    }
    chapter = {
        "chapter_number": 3,
        "chapter_title": "Public conflict",
        "body": "Lin Zhao leaves evidence in public.",
        "chapter_summary": {"summary": "Lin Zhao leaves evidence in public.", "facts": [], "next_focus": "continue"},
    }

    synced = store._sync_project_after_chapter(project, state, chapter)

    edge = synced["relationship_graph"][0]
    assert edge["origin"] == "first meeting"
    assert edge["bond"] == "open rivals"
    assert edge["trust"] == 10
    assert edge["tension"] == 85
    assert edge["last_changed_chapter"] == 3
    assert edge["changes"][-1]["chapter_number"] == 3


def test_file_project_store_regenerates_target_chapter_with_rotating_variant(tmp_path):
    root = tmp_path / "novel"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {"schema_version": "story-system-master-setting/v1", "project": {"project_id": "p-file", "title": "File Novel"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(
            {
                "project_id": "p-file",
                "title": "File Novel",
                "author_constraints": ["第一章必须通过裂纹狼心担保交易解决现实急账。"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-file",
                "outline": "网游开服，主角先确认边界。",
                "genre": "网游",
                "style": "番茄升级流",
                "author_constraints": ["第一章不得交易。"],
                "writing_lessons": ["删除第一章实际交易，只保留价牌。"],
                "current_chapter": 1,
                "world_facts": ["世界摘要：保留。", "第1章事实：灰鼠毒腺x18。", "第4章章末：巡夜人残牌和废井污染源。"],
                "progression_ledger": {
                    "inventory": ["灰鼠毒腺18份"],
                    "simulation_variant": {"id": "old"},
                },
                "characters": [
                    {
                        "name": "苏叶",
                        "role": "主角",
                        "game_id": "夜烬",
                        "game_panel": {"game_id": "夜烬", "inventory": {"灰鼠毒腺": "18份"}},
                        "memory": ["第1章灰鼠毒腺。", "第4章章末有巡夜人残牌。", "现实压力。"],
                    },
                    {"name": "公共频道", "role": "玩家群体", "memory": ["旧噪音。"]},
                ],
                "chapter_summaries": [{"chapter_number": 1, "chapter_title": "旧第一章", "summary": "旧版。"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = FileProjectStore(root)
    store.write_chapter(chapter_number=1, title="旧第一章", body="旧正文。", summary="旧版。")

    seen_variants: list[str] = []

    class FakeEngine:
        def generate_next_chapter(self, story):
            assert story.author_constraints == ["第一章必须通过裂纹狼心担保交易解决现实急账。"]
            assert story.writing_lessons == []
            simulation_variant = story.progression_ledger["simulation_variant"]
            variant = simulation_variant["id"]
            seen_variants.append(variant)
            assert "skip_style_adapt" not in simulation_variant
            assert simulation_variant["skip_expansion"] is False
            dumped_story = json.dumps(story.model_dump(mode="json"), ensure_ascii=False)
            assert "灰鼠" not in dumped_story
            assert "巡夜人残牌" not in dumped_story
            assert "第4章" not in dumped_story
            assert "废井" not in dumped_story
            assert story.chapter_summaries == []
            assert [character.name for character in story.characters] == ["苏叶"]
            assert story.characters[0].game_panel.game_id == "夜烬"
            assert story.characters[0].game_panel.inventory == {}
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title=f"新版-{variant}",
                body=_long_test_body(f"正文使用变体 {variant}。"),
                cadence="manual",
                next_outline="继续确认边界。",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": f"新版-{variant}",
                    "cadence": "manual",
                    "summary": f"使用 {variant} 重推。",
                    "facts": [f"variant:{variant}"],
                    "next_focus": "继续确认边界。",
                    "primary_conflict": "边界",
                    "secondary_conflict": "代价",
                    "event_beat": "重推",
                },
            )

    regenerated = store.regenerate_chapter(1, engine=FakeEngine())

    assert regenerated["schema_version"] == "file-project-regenerate/v1"
    assert regenerated["chapter_number"] == 1
    assert regenerated["chapter_title"] == "背包快满了"
    assert seen_variants == ["boundary-inventory-route"]
    assert regenerated["simulation_variant"]["id"] == "boundary-inventory-route"
    assert "skip_style_adapt" not in regenerated["simulation_variant"]
    assert regenerated["simulation_variant"]["skip_expansion"] is False
    assert (root / "chapters" / "0001-背包快满了.md").exists()


def test_file_project_store_passes_temporary_guidance_to_regeneration(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    store.write_chapter(chapter_number=1, title="Old One", body="Old body kept costs visible.", summary="Old summary.")
    guidance = "Use the dissection report: keep exp 30/100 and do not jump to class change."
    seen_guidance: list[dict] = []

    class FakeEngine:
        def generate_next_chapter(self, story):
            temporary = story.progression_ledger["simulation_variant"]["rewrite_guidance"]
            seen_guidance.append(temporary)
            assert temporary["source"] == "book_dissection"
            assert temporary["text"] == guidance
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Guided One",
                body=_long_test_body("Night Ember keeps exp 30/100 visible and stays away from class change."),
                cadence="manual",
                next_outline="Continue the guided path.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Guided One",
                    "cadence": "manual",
                    "summary": "Guidance shaped the rewrite.",
                    "facts": ["guided rewrite"],
                    "next_focus": "Continue the guided path.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "guided",
                },
            )

    regenerated = store.regenerate_chapter(1, engine=FakeEngine(), guidance=guidance)

    assert seen_guidance == [{"source": "book_dissection", "text": guidance}]
    assert regenerated["simulation_variant"]["rewrite_guidance"]["text"] == guidance
    state_after = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert "rewrite_guidance" not in state_after.get("progression_ledger", {}).get("simulation_variant", {})


def test_file_project_store_regenerate_does_not_fail_on_continuity_quality_fields(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    store.write_chapter(
        chapter_number=1,
        title="Old One",
        body=_long_test_body("Old draft keeps costs visible."),
        summary="Old summary.",
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Regenerated One",
                body=_long_test_body("Regenerated body keeps structure and continuity."),
                cadence="manual",
                next_outline="Continue from continuity.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Regenerated One",
                    "cadence": "manual",
                    "summary": "Continuity fields are missing in report.",
                    "facts": ["continuity fallback"],
                    "next_focus": "Continue from continuity.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "continuity",
                },
                quality_report={
                    "ok": False,
                    "issues": ["body", "chapter_title", "next_outline", "timeline", "chapter_summaries"],
                    "writing_review": {"pass": False, "issues": ["body", "chapter_title", "next_outline", "timeline", "chapter_summaries"]},
                },
            )

    regenerated = store.regenerate_chapter(1, engine=FakeEngine())

    assert regenerated["schema_version"] == "file-project-regenerate/v1"
    assert isinstance(regenerated["chapter_title"], str) and bool(regenerated["chapter_title"])
    assert regenerated["chapter_number"] == 1


def test_file_project_store_blocks_short_generated_bundle(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Too Short",
                body="Night Ember only looks around.",
                cadence="manual",
                next_outline="Continue.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Too Short",
                    "cadence": "manual",
                    "summary": "Too short.",
                    "facts": ["too short"],
                    "next_focus": "Continue.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "short",
                },
            )

    with pytest.raises(ValueError, match="generate_length_failed"):
        store.generate_next_chapter(engine=FakeEngine())

    assert not (root / ".story-system" / "chapters" / "0001.json").exists()


def test_file_project_store_blocks_failed_generated_quality_report(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Bad Trade",
                body=_long_test_body("Night Ember keeps the body long enough but closes the trade too early."),
                cadence="manual",
                next_outline="Continue.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Bad Trade",
                    "cadence": "manual",
                    "summary": "Quality should block this generated chapter.",
                    "facts": ["bad trade closure"],
                    "next_focus": "Continue.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "blocked",
                },
                quality_report={
                    "ok": False,
                    "issues": ["writing_review"],
                    "writing_review": {
                        "pass": False,
                        "issues": ["第一章提前展开交易闭环：出现寄售、上架、成交、到账、手续费或提现。"],
                    },
                },
            )

    with pytest.raises(ValueError, match="generate_quality_failed"):
        store.generate_next_chapter(engine=FakeEngine())

    assert not (root / ".story-system" / "chapters" / "0001.json").exists()


def test_file_project_store_saves_generated_chapter_with_advisory_review(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Usable Draft",
                body=_long_test_body("The chapter is complete but the dialogue can still be polished."),
                cadence="manual",
                next_outline="Continue.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Usable Draft",
                    "cadence": "manual",
                    "summary": "The usable draft advances the story.",
                    "facts": ["the chapter advanced"],
                    "next_focus": "Continue.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "advanced",
                },
                quality_report={
                    "ok": False,
                    "issues": ["writing_review"],
                    "writing_review": {
                        "pass": False,
                        "issues": ["现代中文对话不够自然，建议局部修改。"],
                    },
                    "simplified_review": {
                        "status": "needs_revision",
                        "pass": True,
                        "has_hard_errors": False,
                        "needs_revision": True,
                    },
                },
            )

    result = store.generate_next_chapter(engine=FakeEngine())

    assert result["chapter_number"] == 1
    saved = json.loads((root / ".story-system" / "chapters" / "0001.json").read_text(encoding="utf-8"))
    assert saved["quality_report"]["quality_warning"]["status"] == "needs_revision"


def test_persist_bundle_quality_failure_raises_chapter_quality_error_with_report(tmp_path):
    from packages.story_core.file_project_store import ChapterQualityError

    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Fresh Chapter",
        body=_long_test_body(),
        cadence="manual",
        next_outline="Continue.",
        updated_story={"story_id": "s-file", "current_chapter": 1},
        chapter_summary={
            "chapter_title": "Fresh Chapter",
            "cadence": "manual",
            "summary": "Fresh summary.",
            "facts": ["fresh fact"],
            "next_focus": "Continue.",
            "primary_conflict": "Clean state.",
            "secondary_conflict": "Old snapshot.",
            "event_beat": "Persist.",
        },
    )

    with pytest.raises(ChapterQualityError, match="generate_quality_failed") as exc_info:
        store.persist_bundle(bundle)

    assert exc_info.value.operation == "generate"
    assert exc_info.value.quality_report.get("ok") is False



def test_file_project_store_generate_bundle_with_empty_failure_body_reports_generate_failed_reason(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )

    bundle = _failed_bundle(
        StoryState(
            story_id="s-file",
            outline="A grounded game story.",
            genre="webgame",
            style="plain",
            current_chapter=0,
            world_facts=[],
        ),
        1,
        "plan_timeout",
    )

    with pytest.raises(ValueError, match="generate_failed:plan_timeout"):
        store.persist_bundle(bundle, operation="generate")


def test_file_project_store_generate_bundle_with_empty_body_reports_generate_failed(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )

    bundle = {
        "chapter_number": 1,
        "chapter_title": "第一章",
        "body": "",
        "quality_report": {
            "ok": False,
            "issues": ["body", "cadence", "next_outline", "timeline", "chapter_summaries"],
            "writing_review": {
                "pass": False,
                "issues": ["body", "cadence", "next_outline", "timeline", "chapter_summaries"],
            },
        },
    }

    with pytest.raises(ValueError, match="generate_failed:body"):
        store.persist_bundle(bundle, operation="generate")


def test_file_project_store_regenerate_bundle_with_empty_body_reports_regenerate_failed(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )

    bundle = {
        "chapter_number": 1,
        "chapter_title": "第一章",
        "body": "",
        "quality_report": {
            "ok": False,
            "issues": ["body", "timeline", "chapter_summaries"],
            "writing_review": {"pass": False, "issues": ["body", "timeline", "chapter_summaries"]},
        },
    }

    with pytest.raises(ValueError, match="regenerate_failed:body"):
        store.persist_bundle(bundle, operation="regenerate")


def test_file_project_store_normalizes_generated_chapter_title_prefix(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="第1章 夜烬",
                body=_long_test_body("Night Ember keeps the body long enough and clean."),
                cadence="manual",
                next_outline="Continue.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "第1章 夜烬",
                    "cadence": "manual",
                    "summary": "Title should be normalized.",
                    "facts": ["title normalized"],
                    "next_focus": "Continue.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "title",
                },
                quality_report={
                    "ok": True,
                    "issues": [],
                    "writing_review": {"pass": True, "issues": []},
                },
            )

    generated = store.generate_next_chapter(engine=FakeEngine())

    assert generated["chapter_title"] == "夜烬"
    assert (root / "chapters" / "0001-夜烬.md").exists()


def test_file_project_store_reads_exported_layout(tmp_path):
    root = tmp_path / "novel"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)

    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {"project_id": "p-test", "title": "测试书", "active_story_id": "s-test"},
                "active_story_id": "s-test",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-test", "title": "测试书", "active_story_id": "s-test"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-test",
                "genre": "网游",
                "style": "升级流",
                "current_chapter": 1,
                "author_constraints": ["不要写后台判断"],
                "world_facts": ["洛婶在药剂铺"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "第一章 灰烬村",
        "body": "夜烬走进药剂铺，洛婶抬头看了他一眼。",
        "chapter_summary": {"summary": "夜烬见到洛婶。"},
        "event_plan": {"next_focus": "补齐毒腺"},
        "quality_report": {"writing_review": {"pass": True, "issues": []}},
    }
    (root / ".story-system" / "chapters" / "0001.json").write_text(
        json.dumps(chapter, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".story-system" / "reviews" / "0001.json").write_text(
        json.dumps({"writing_review": {"pass": True, "issues": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "chapters" / "0001-第一章.md").write_text(chapter["body"], encoding="utf-8")

    store = FileProjectStore(root)

    assert store.exists()
    assert store.summary()["chapter_count"] == 1
    assert store.review(1)["writing_review"]["pass"] is True
    assert store.query("洛婶")["result_count"] > 0
    packet = store.writing_packet(2)
    assert packet["target_chapter"] == 2
    assert packet["latest_chapter_number"] == 1
    assert packet["prose_renderer"]["skill"] == "chinese-novelist"
    assert packet["prose_renderer"]["role"] == "prose_renderer_only"
    assert packet["title_contract"]["style"] == "tomato_concrete_short_title"
    assert any("番茄爆款网文" in rule for rule in packet["style_rules"])
    assert packet["recent_chapters"][0]["next_focus"] == "补齐毒腺"
