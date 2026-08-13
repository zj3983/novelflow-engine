from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import ChapterSummary, TimelineEvent
from packages.story_core.outline_planning_generation import GeneratedChapterWindow
from packages.story_core.project_outline import ArcOutline


def _story_nodes(start_chapter: int, end_chapter: int) -> list[dict]:
    return [
        {
            "start_chapter": start,
            "end_chapter": min(start + 14, end_chapter),
            "objective": f"推进第{start}章开始的阶段目标。",
            "pressure": "旧行会封锁独立维修渠道。",
            "turn": "一份可核验的旧账册改变调查方向。",
            "payoff": "主角拿到推进下一阶段的明确结果。",
            "next_effect": "当前结果引出下一节点。",
        }
        for start in range(start_chapter, end_chapter + 1, 15)
    ]


def _make_project(root: Path) -> FileProjectStore:
    for relative in (
        ".story-system/chapters",
        ".story-system/reviews",
        ".webnovel",
        "chapters",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    project = {
        "project_id": "p-volume-lifecycle",
        "title": "卷纲生命周期验收",
        "active_story_id": "s-volume-lifecycle",
    }
    state = {
        "story_id": "s-volume-lifecycle",
        "outline": "林修脱离旧行会，建立独立维修铺。",
        "genre": "玄幻",
        "style": "",
        "current_chapter": 50,
        "world_facts": ["旧行会的第一张经营许可已经被撤销。"],
        "characters": [
            {
                "name": "林修",
                "role": "protagonist",
                "goals": ["建立不受旧行会控制的维修铺"],
                "current_emotion": "警惕",
                "location": "旧维修铺",
            }
        ],
    }
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": project,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(project, ensure_ascii=False), encoding="utf-8"
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )

    store = FileProjectStore(root)
    store.update_project_outline(
        {
            "schema_version": "project-outline/v1",
            "overall": {
                "story": "林修从旧行会的封锁中建立自己的维修体系。",
                "theme_statement": "修复之前，先查清故障和代价。",
                "foreground_story": "林修争取独立维修资格。",
                "background_story": "旧行会借许可制度垄断维修渠道。",
                "book_objective": "建立公开、可核验的独立维修体系。",
                "ending_image": "独立维修铺正式开门。",
                "protagonist_goal": "取得独立维修资格。",
                "main_conflict": "旧行会封锁证据和渠道。",
                "growth_path": "从被动接活到制定维修规则。",
                "ending_direction": "林修建立独立维修铺。",
                "primary_trope_id": "low_status_reversal",
                "core_ending_chapter": 200,
                "extension_ceiling_chapter": 300,
                "current_strategy": "expand",
                "planned_arc_count": 1,
                "planned_length": 200,
            },
            "arcs": [
                {
                    "id": "volume-1",
                    "title": "旧许可",
                    "start_chapter": 1,
                    "end_chapter": 50,
                    "goal": "撤销旧行会非法占用的经营许可。",
                    "obstacle": "旧行会控制许可档案。",
                    "payoff": "第一张许可被公开撤销。",
                    "emotional_curve": "受压查证，找到漏洞，公开反击。",
                    "key_results": ["撤销旧许可", "付出失去旧铺面的代价"],
                    "hook_plan": "旧账册指向另一份独立维修许可。",
                    "irreversible_change": "林修与旧行会公开决裂。",
                    "end_state": "旧行会失去第一张许可。",
                    "extension_gate": {
                        "continue_route": "追查缺失的独立维修账册。",
                        "close_route": "公开第一份许可档案。",
                    },
                    "midpoint_turn": "保管人承认档案被替换。",
                    "climax": "林修当众核验伪造印章。",
                    "next_arc_entry": "缺失账册在城外出现。",
                    "is_final_arc": False,
                    "story_nodes": _story_nodes(1, 50),
                }
            ],
            "chapters": [],
        }
    )
    return store


class _LifecycleGenerator:
    def __init__(self) -> None:
        self.detail_batches: list[tuple[int, ...]] = []

    def generate_next_volume(self, brief, *, previous_volume, guidance=""):
        assert previous_volume["id"] == "volume-1"
        return ArcOutline.model_validate(
            {
                "id": "volume-2",
                "title": "独立维修铺",
                "start_chapter": 51,
                "end_chapter": 100,
                "goal": "找回缺失账册并取得独立维修资格。",
                "obstacle": "旧行会控制所有合法维修渠道。",
                "payoff": "林修取得独立维修许可。",
                "emotional_curve": "失去旧铺面后重新建立可信渠道。",
                "key_results": ["取得独立维修许可", "代价是失去旧铺面"],
                "hook_plan": "账册指向京城的维修总署。",
                "irreversible_change": "林修永久脱离旧行会。",
                "end_state": "独立维修铺正式开门。",
                "extension_gate": {
                    "continue_route": "沿账册线索前往京城。",
                    "close_route": "公开本地账册并守住维修铺。",
                },
                "midpoint_turn": "关键证人承认账册经过伪造。",
                "climax": "林修在听证会上公开隐藏记录。",
                "next_arc_entry": "京城维修总署派来一名监察官。",
                "is_final_arc": False,
                "story_nodes": _story_nodes(51, 100),
            }
        )

    def generate_chapter_batch(
        self,
        brief,
        *,
        volume,
        chapter_numbers,
        previous_batches,
        adjacent_chapters=None,
        committed_context=None,
        guidance="",
    ):
        self.detail_batches.append(tuple(chapter_numbers))
        return GeneratedChapterWindow.model_validate(
            {
                "chapters": [
                    {
                        "chapter_number": number,
                        "title": f"第{number}章 独立维修的第一步",
                        "goal": "取得一条可核验的账册线索。",
                        "obstacle": "档案室即将关闭。",
                        "action": "林修对照印章和出入记录。",
                        "turn": "账册上出现第二个签名。",
                        "payoff": "下一名证人的身份得到确认。",
                        "ending_hook": "证人已经提前离开。",
                        "cast": ["林修"],
                        "core_conflict": "必须在封档前复制证据。",
                        "gain": "一份可核验的签名记录。",
                        "cost": "档案保管人注意到了林修。",
                        "foreshadowing": ["第二个签名"],
                        "state_delta_summary": "调查转向失踪证人。",
                        "scene_chain": [
                            {
                                "location": "档案室",
                                "pov": "林修",
                                "goal": "复制证据",
                                "obstacle": "档案室即将关闭",
                                "action": "对照两枚印章",
                                "change": "发现第二个签名",
                                "next": "寻找签名人",
                                "state_delta": {"clue": 1},
                            },
                            {
                                "location": "外院",
                                "pov": "林修",
                                "goal": "找到签名人",
                                "obstacle": "签名人已经离开",
                                "action": "检查出入记录",
                                "change": "确认对方提前离场",
                                "next": "追查离场路线",
                                "state_delta": {"lead": 1},
                            },
                        ],
                    }
                    for number in chapter_numbers
                ]
            }
        )


class _ChapterEngine:
    def generate_next_chapter(self, story):
        assert story.current_chapter == 50
        updated_story = story.model_copy(
            update={
                "current_chapter": 51,
                "timeline": [
                    TimelineEvent(
                        chapter_number=51,
                        summary="林修查到独立维修账册的第一条线索。",
                        impact="第二卷正式开始。",
                    )
                ],
                "chapter_summaries": [
                    ChapterSummary(
                        chapter_number=51,
                        chapter_title="独立维修的第一步",
                        summary="林修查到独立维修账册的第一条线索。",
                    )
                ],
            }
        )
        return SimpleNamespace(
            chapter_number=51,
            chapter_title="独立维修的第一步",
            body=("林修按照新卷细纲查验账册，拿到了第一条可核验的线索。\n" * 220),
            cadence="measured",
            next_outline="追查提前离开的签名人。",
            updated_story=updated_story,
            chapter_summary={
                "chapter_number": 51,
                "chapter_title": "独立维修的第一步",
                "summary": "林修查到独立维修账册的第一条线索。",
                "facts": ["独立维修账册上存在第二个签名。"],
                "next_focus": "追查提前离开的签名人。",
            },
        )


def test_completed_volume_can_design_detail_and_generate_next_chapter(tmp_path) -> None:
    store = _make_project(tmp_path / "volume-lifecycle")
    generator = _LifecycleGenerator()

    missing = store.volume_workflow_status(51)
    assert missing["status"] == "volume_missing"
    assert missing["next_action"] == "design_next_volume"

    designed = store.design_next_volume(generator)
    assert designed["volume_id"] == "volume-2"
    assert designed["volume_range"] == [51, 100]

    detailed = store.generate_volume_detail(generator, volume_id="volume-2")
    assert detailed["detail_status"] == "complete"
    assert detailed["completed_chapters"] == detailed["total_chapters"] == 50
    assert generator.detail_batches == [
        tuple(range(51, 66)),
        tuple(range(66, 81)),
        tuple(range(81, 96)),
        tuple(range(96, 101)),
    ]

    ready = store.volume_workflow_status(51)
    assert ready["status"] == "detail_complete"
    assert ready["next_action"] == "generate_prose"
    assert ready["volume_id"] == "volume-2"

    generated = store.generate_next_chapter(engine=_ChapterEngine(), persist=False)
    assert generated["schema_version"] == "file-project-candidate/v1"
    assert generated["chapter_number"] == 51
    assert generated["chapter_title"] == "独立维修的第一步"
    assert generated["candidate"]["chapter_number"] == 51
    assert store.state()["current_chapter"] == 50
