"""Planning intent must survive conversion without manufacturing new costs."""
import json
from types import SimpleNamespace

import pytest

from packages.story_core.agents.contracts import DirectorArtifact, SceneBeat, WriterRequest
from packages.story_core.agents.director.prompt import build_director_prompt, build_outline_execution_contract
from packages.story_core.agents.writer.prompt import build_writer_prompt
from packages.story_core.character_agent import _chapter_pressure
from packages.story_core.context.director_context import DirectorContext, build_director_context
from packages.story_core.context.legacy_adapter import legacy_outline_view
from packages.story_core.contextual_prose_review import chapter_review_plan, review_contextual_prose
from packages.story_core.continuation_outline_bootstrap import rolling_batch_from_generated_window
from packages.story_core.models import StoryState
from packages.story_core.outline_planning_generation import GeneratedDetailedChapter
from packages.story_core.outline_rolling import rolling_chapter_to_outline_entry, validate_rolling_chapter
from packages.story_core.plot_spine_review import review_plot_spine_completion
from packages.story_core.writing_taskbook import build_writing_taskbook


TONE = "从疲惫落到传承者的耐心，允许门人因学会方法而放松。"


def chapter_plan():
    return {
        "chapter_number": 307, "title": "留下诊断法", "goal": "教会门人诊断",
        "obstacle": "门人不熟悉读数", "action": "示范并让门人复测",
        "turn": "门人自己发现读数抄反", "payoff": "门人完成第一次复核",
        "ending_hook": "明早由门人独立值守", "cast": ["林修"],
        "core_conflict": "从依赖代劳转向自主判断", "gain": "门人学会复核", "foreshadowing": [],
        "state_delta_summary": "交接完成第一步", "emotional_change": TONE,
        "scene_chain": [
            {"location": "阀前", "pov": "林修", "goal": "示范测温", "obstacle": "手法生疏",
             "action": "演示指腹测温", "change": "门人记住基准", "next": "让门人复测"},
            {"location": "值守房", "pov": "林修", "goal": "让门人复核", "obstacle": "抄错读数",
             "action": "等门人查出错项", "change": "门人完成复核", "next": "准备明早值守"},
        ],
    }


@pytest.mark.parametrize("cost", [None, "", "无新增代价", "战斗消耗两枚灵石，左臂旧伤持续，不能免费恢复"])
def test_cost_and_emotion_survive_planner_to_writer_without_forced_loss(cost):
    raw = chapter_plan()
    if cost is not None:
        raw["cost"] = cost
    generated = GeneratedDetailedChapter.model_validate(raw)
    row = rolling_batch_from_generated_window(
        chapters=[generated.model_dump()], character_cards=[{"name": "林修"}],
        volume_range=(301, 310), expected_chapter_numbers=[307],
    )[0]
    row = validate_rolling_chapter(row, expected_chapter_number=307, volume_range=(301, 310))
    entry = rolling_chapter_to_outline_entry(row)
    context = DirectorContext(chapter_number=307, volume={}, book_outline_summary="交接", nearby_outline=[entry])
    contract = build_outline_execution_contract(context)
    assert contract.cost == (cost or "")
    assert contract.emotional_change == TONE
    director_prompt = build_director_prompt(context)
    artifact = DirectorArtifact(chapter_number=307, chapter_goal=raw["goal"], opening_state="维修完成",
        scene_beats=[SceneBeat(order=1, location="阀前", action="演示测温", result="门人学会方法")],
        ending_state="准备明早值守", outline_contract=contract)
    writer_prompt = build_writer_prompt(WriterRequest(chapter_number=307, director_artifact=artifact))
    assert TONE in director_prompt and TONE in writer_prompt
    assert (cost or "无新增代价") in writer_prompt
    assert "本章必须付出" not in writer_prompt
    assert "人物意图是压力来源" not in director_prompt
    assert "本章已确定的成本" in writer_prompt


def test_rolling_overlay_and_legacy_view_retain_original_emotional_direction(tmp_path):
    raw = chapter_plan()
    row = rolling_batch_from_generated_window(
        chapters=[raw], character_cards=[{"name": "林修"}], volume_range=(301, 310), expected_chapter_numbers=[307],
    )[0]
    row.pop("emotional_change")  # Existing rolling rows predate this optional field.
    system = tmp_path / ".story-system"
    (system / "outline-generation").mkdir(parents=True)
    (tmp_path / ".webnovel").mkdir()
    (tmp_path / ".webnovel/outline.json").write_text(json.dumps({"chapters": [raw]}), encoding="utf-8")
    legacy = legacy_outline_view(system)
    (system / "outline.json").write_text(json.dumps(legacy), encoding="utf-8")
    (system / "outline-generation/rolling_outline.json").write_text(json.dumps({"chapters": [row]}), encoding="utf-8")
    context = build_director_context(project=tmp_path, chapter_number=307)
    assert build_outline_execution_contract(context).emotional_change == TONE
    assert chapter_review_plan(tmp_path, 307)["emotional_change"] == TONE
    assert raw["emotional_change"] == TONE


def test_story_turn_does_not_become_a_cost_when_no_cost_was_planned():
    context = DirectorContext(chapter_number=307, volume={}, book_outline_summary="交接", nearby_outline=[{
        "number": 307, "turn": "门人终于自己纠正误判", "emotional_change": TONE,
    }])
    assert build_outline_execution_contract(context).cost == ""


def test_character_proposals_receive_tone_even_when_actions_are_long():
    story = StoryState(story_id="tone", outline="教学", genre="修仙", style="",
        outline_context={"chapter": {"chapter_number": 307, "emotional_change": TONE,
                                    "cost": "无新增代价", "action": "复测。" * 2000}})
    rendered = _chapter_pressure(story)
    assert TONE in rendered and "无新增代价" in rendered


def test_default_scene_handoffs_allow_results_and_relief():
    book = build_writing_taskbook(chapter_number=307, genre="修仙", plan={})
    rendered = str(book)
    assert "同时付出可见代价" not in rendered
    assert "形成下一场压力" not in rendered
    assert "无新增代价时不追加损失" in rendered
    cards = [{"location": "阀前", "action": "示范测温"}] * 3
    planned = build_writing_taskbook(chapter_number=307, genre="修仙", plan={"scene_cards": cards})
    assert "承接本场结果，可推进或缓和" in str(planned)


@pytest.mark.parametrize("cost", ["", "无新增代价"])
def test_spine_review_does_not_demand_cost_prose_when_no_cost_was_planned(cost):
    report = review_plot_spine_completion("门人学会复测，笑着收好了记录。", {"plot_simulation": {"cost": cost}})
    assert report["pass"] and not report["issues"]


def test_spine_review_still_checks_a_planned_resource_cost():
    report = review_plot_spine_completion("门人学会复测，笑着收好了记录。", {"plot_simulation": {"cost": "三枚珍贵灵石尽数耗空"}})
    assert not report["pass"] and any("代价" in issue for issue in report["issues"])


def test_existing_review_receives_upstream_boundary_in_one_call_and_keeps_evidence():
    body = "林修喝道：再看错一格，全门弟子都得死在这里。"
    class Gateway:
        def __init__(self):
            self.calls = []
        def complete_stage(self, stage, request):
            self.calls.append(request)
            return SimpleNamespace(text=json.dumps({"summary": "教学被擅自升级为死亡威胁", "issues": [{
                "category": "prose", "title": "新增死亡威胁", "quote": body,
                "context_reason": "上游要求耐心教学且无新增代价，正文却把一次读数纠错升级成全门死亡，与既定风险范围不符。",
                "suggestion": "保留门人复测和纠错的过程，去掉未经计划的死亡威胁。",
            }]}), ok=True)
    gateway = Gateway()
    report = review_contextual_prose(body, {"upstream_chapter_plan": {
        "goal": "示范复测", "cost": "无新增代价", "emotional_change": TONE,
    }}, model_gateway=gateway)
    assert len(gateway.calls) == 1
    assert "upstream_chapter_plan" in gateway.calls[0].prompt
    assert TONE in gateway.calls[0].prompt
    assert "上游确有战斗、抢修或资源成本时也不能一律降压" in gateway.calls[0].prompt
    assert report["status"] == "completed" and not report["pass"]
    assert report["annotations"][0]["quotes"] == [body]
