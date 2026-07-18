import json
from types import SimpleNamespace

import pytest

from packages.story_core.file_project_store import FileProjectStore, _regeneration_quality_blocking
from packages.story_core.outline_planning import GeneratedOutlinePlan
from packages.story_core.skill_packs import import_skill_pack_from_path


def _long_test_body(label: str = "Night Ember keeps the chapter grounded.") -> str:
    return (label + " He checks the task, pays a visible cost, gains a result, and leaves a next step.\n") * 80


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
                        "cast": ["林照", "赵衡"],
                    }
                    for number in range(1, 6)
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

    store.generate_outline_plan(RecordingGenerator(), mode="initial", guidance="  对手有现实利益  ")

    brief, mode, guidance = calls[0]
    assert mode == "initial"
    assert guidance == "对手有现实利益"
    assert brief.novel_type_id == "xuanhuan"
    assert brief.opening_direction.hook == "林照看守断香炉。"
    assert brief.existing_characters == []
    secret = "对手有现实利益".encode("utf-8")
    assert all(secret not in path.read_bytes() for path in store.root.rglob("*") if path.is_file())


def test_extend_generated_plan_requires_and_appends_next_five_chapters(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["arcs"][0]["end_chapter"] = 5
    store.update_project_outline(current_outline)
    addition = GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "arcs": [
                    {
                        **current_outline["arcs"][0],
                        "end_chapter": 10,
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
                    for number in range(6, 11)
                ]
            },
            "characters": [_planning_card("新档房弟子", "supporting")],
        }
    )

    saved = store.save_generated_outline_plan(addition, mode="extend")

    assert [item["chapter_number"] for item in saved["outline"]["chapters"]] == list(range(1, 11))
    assert saved["outline"]["arcs"][0]["end_chapter"] == 10
    assert saved["outline"]["arcs"][0]["long_term_antagonist_traces"] == [
        "旧名册被换过",
        "执法堂有人提前封档",
    ]
    assert any(item["name"] == "新档房弟子" for item in saved["characters"])


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
    modules = {item["key"]: item for item in preview["modules"]}
    assert {"core_context", "character_context", "genre_context", "writing_taskbook", "packet_context"}.issubset(modules)
    assert "source_body" not in modules
    keys = {item["key"] for item in preview["prompts"]}
    assert {"director_plan", "writer_body", "revision", "writing_taskbook", "review_agents"}.issubset(keys)
    by_key = {item["key"]: item for item in preview["prompts"]}
    assert "## 输出要求" in by_key["writer_body"]["content"]
    assert "## 本章方向" in by_key["writer_body"]["content"]
    assert "## 本章事实" in by_key["writer_body"]["content"]
    assert "## 出场人物" in by_key["writer_body"]["content"]
    assert "## 正文写法" in by_key["writer_body"]["content"]
    assert "character_cards" not in modules["core_context"]["content"]
    assert "苏叶" in by_key["writer_body"]["content"]
    assert "character_context" in by_key["writer_body"]["module_keys"]
    assert "网游写法方法卡" in by_key["writer_body"]["content"]
    assert "genre_context" in by_key["writer_body"]["module_keys"]
    assert "web_game" in modules["genre_context"]["content"]
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
            updated_story = story.model_copy(update={"current_chapter": 1})
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
    assert constraints["progression_rules"] == ["visible gain every chapter"]
    assert constraints["forbidden_breaks"] == ["do not skip the outline"]
    assert isinstance(packet["state"]["characters"], list)


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
        json.dumps({"project_id": "p-file", "title": "File Novel"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-file",
                "outline": "网游开服，主角先确认边界。",
                "genre": "网游",
                "style": "番茄升级流",
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
            simulation_variant = story.progression_ledger["simulation_variant"]
            variant = simulation_variant["id"]
            seen_variants.append(variant)
            assert simulation_variant["skip_style_adapt"] is True
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
    assert regenerated["simulation_variant"]["skip_style_adapt"] is True
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
