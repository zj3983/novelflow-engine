from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from packages.story_core.ending_planning import plan_ending, _ending_input
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.outline_planning_generation import GeneratedDetailedChapter
from packages.story_core.persistence.snapshot_store import SnapshotStore


def project(root, completed=False):
    writer = SnapshotStore()
    state = {"story_id": "s-test", "current_chapter": 53 if completed else 50,
             "characters": [{"name": "林修", "role": "protagonist"}], "world_facts": ["左臂负伤"]}
    meta = {"project_id": "p-test", "title": "维修", "active_story_id": "s-test"}
    writer.write_json_atomic(root / ".webnovel/project.json", meta)
    writer.write_json_atomic(root / ".webnovel/state.json", state)
    outline = {"overall": {"story": "林修完成最后的修理", "ending_contract": "还家休养",
                           "current_strategy": "close" if completed else "observe",
                           "core_ending_chapter": 53, "extension_ceiling_chapter": 53},
               "arcs": [{"id": "old", "start_chapter": 1, "end_chapter": 50}],
               "chapters": [{"chapter_number": 50, "title": "旧任务", "goal": "已发生"}]}
    if completed:
        outline["arcs"].append({"id": "old-ending", "start_chapter": 51, "end_chapter": 53, "is_final_arc": True})
        outline["chapters"].append({"chapter_number": 51, "title": "旧结尾", "goal": "错误旧细纲"})
        writer.write_json_atomic(root / ".story-system/continuity/snapshots/0050.json",
                                 {"state_after": {**state, "current_chapter": 50, "world_facts": ["左臂负伤"]}})
    writer.write_json_atomic(root / ".webnovel/outline.json", outline)
    writer.write_json_atomic(root / ".story-system/outline.json", deepcopy(outline))
    (root / "chapters").mkdir(parents=True)
    (root / "chapters/0050-旧任务.md").write_text("他带着伤接下最后的修理。", encoding="utf-8")
    writer.write_json_atomic(root / ".story-system/chapters/0050.json",
                             {"chapter_number": 50, "chapter_summary": {"summary": "左臂受伤，尚未完成修理"}})
    return FileProjectStore(root)


class Generator:
    def __init__(self, change=None, end=53):
        self.change = change
        self.end = end

    def generate_ending_blueprint(self, brief, *, constraints, guidance):
        self.brief, self.constraints = brief, constraints
        if self.change:
            self.change()
        start = constraints["required_start_chapter"]
        return {"closing_route": "修好最后的机器，然后回家", "ending_contract": "任务交付，左臂慢慢养伤",
                "volume": {"id": "new-ending", "title": "最后的修理", "start_chapter": start,
                           "end_chapter": self.end, "is_final_arc": True,
                           "goal": "完成修理", "obstacle": "旧伤限制", "climax": "机器重新转动",
                           "payoff": "任务交付", "end_state": "回家休养",
                           "story_nodes": [{"start_chapter": n, "end_chapter": min(n + 14, self.end),
                                            "objective": "交付修理", "pressure": "伤势加重", "turn": "同伴接手",
                                            "payoff": "机器恢复", "next_effect": "回家休养"}
                                           for n in range(start, self.end + 1, 15)]}}

    def generate_chapter_batch(self, brief, *, chapter_numbers, **kwargs):
        return SimpleNamespace(chapters=[GeneratedDetailedChapter(
            chapter_number=n, title=f"修理{n}", goal="恢复机器", obstacle="左臂有伤", action="同伴接手拆机",
            turn="发现旧零件仍可用", payoff="机器恢复运转", ending_hook="同伴把灯关上，二人回家",
            cast=["林修"], core_conflict="负伤无法独自修理", gain="完成修理", cost="仍需养伤",
            state_delta_summary="任务完成，伤势保留",
            scene_chain=[{"location": "维修铺", "pov": "林修", "goal": "确认故障", "obstacle": "左臂负伤",
                          "action": "用右手拆开外壳", "change": "找到断线"},
                         {"location": "门口", "pov": "林修", "goal": "交回机器", "obstacle": "怕故障再现",
                          "action": "通电试运行", "change": "机器正常运转"}],
        ) for n in chapter_numbers])


@pytest.mark.parametrize("completed", [False, True])
def test_one_click_saves_all_three_projections_and_never_writes_prose(tmp_path, completed):
    store = project(tmp_path, completed)
    prose = (tmp_path / "chapters/0050-旧任务.md").read_bytes()
    state = (tmp_path / ".webnovel/state.json").read_bytes()
    generator = Generator()
    result = plan_ending(store, generator)
    assert result["chapter_range"] == [51, 53]
    assert generator.brief.current_chapter == 50
    assert generator.brief.world_facts == ["左臂负伤"]
    assert all(row["chapter_number"] <= 50 for row in generator.brief.existing_outline["chapters"])
    assert generator.constraints["recent_prose"][0]["chapter_number"] == 50
    for path in (".webnovel/outline.json", ".story-system/outline.json",
                 ".story-system/outline-generation/rolling_outline.json"):
        saved = json.loads((tmp_path / path).read_text(encoding="utf-8"))
        assert [row["chapter_number"] for row in saved["chapters"]][-3:] == [51, 52, 53]
    assert result["outline"]["overall"]["current_strategy"] == "close"
    assert result["outline"]["chapters"][0]["goal"] == "已发生"
    assert (tmp_path / "chapters/0050-旧任务.md").read_bytes() == prose
    assert (tmp_path / ".webnovel/state.json").read_bytes() == state


def test_context_change_during_model_call_prevents_all_planning_writes(tmp_path):
    store = project(tmp_path)
    outline = (tmp_path / ".webnovel/outline.json").read_bytes()
    def edit():
        (tmp_path / "chapters/0050-旧任务.md").write_text("作者新改的正文", encoding="utf-8")
    with pytest.raises(ValueError, match="ending_planning_context_changed"):
        plan_ending(store, Generator(change=edit))
    assert (tmp_path / ".webnovel/outline.json").read_bytes() == outline
    assert not (tmp_path / ".story-system/outline-generation/rolling_outline.json").exists()


def test_completed_ending_cannot_extend_past_fixed_end(tmp_path):
    store = project(tmp_path, True)
    with pytest.raises(ValueError, match="ending_planning_invalid_range"):
        plan_ending(store, Generator(end=54))


def test_invalid_blueprint_is_repaired_once_without_partial_save(tmp_path):
    store = project(tmp_path)
    generator = Generator()
    original = generator.generate_ending_blueprint
    calls = []
    def blueprint(brief, *, constraints, guidance):
        calls.append(guidance)
        result = original(brief, constraints=constraints, guidance=guidance)
        if len(calls) == 1:
            result["volume"]["story_nodes"][0]["payoff"] = ""
        return result
    generator.generate_ending_blueprint = blueprint
    assert plan_ending(store, generator)["chapter_count"] == 3
    assert len(calls) == 2
    assert "ending_planning_invalid_story_nodes" in calls[1]


def test_failed_second_batch_does_not_save_partial_ending(tmp_path):
    store = project(tmp_path)
    before = (tmp_path / ".webnovel/outline.json").read_bytes()
    generator = Generator(end=68)
    original_batch = generator.generate_chapter_batch
    def batch(brief, *, chapter_numbers, **kwargs):
        if chapter_numbers[0] > 51:
            raise RuntimeError("model unavailable")
        return original_batch(brief, chapter_numbers=chapter_numbers, **kwargs)
    generator.generate_chapter_batch = batch
    with pytest.raises(RuntimeError, match="model unavailable"):
        plan_ending(store, generator)
    assert (tmp_path / ".webnovel/outline.json").read_bytes() == before


def test_long_ending_uses_small_batches_with_previous_handoffs(tmp_path):
    store = project(tmp_path)
    generator = Generator(end=62)
    original_batch = generator.generate_chapter_batch
    calls = []
    def batch(brief, *, chapter_numbers, previous_batches, **kwargs):
        calls.append((list(chapter_numbers), deepcopy(previous_batches)))
        return original_batch(brief, chapter_numbers=chapter_numbers, **kwargs)
    generator.generate_chapter_batch = batch
    result = plan_ending(store, generator)
    assert result["chapter_range"] == [51, 62]
    assert [numbers for numbers, _ in calls] == [list(range(51, 55)), list(range(55, 59)), list(range(59, 63))]
    assert not calls[0][1]
    assert calls[1][1][-1]["chapters"][-1]["chapter_number"] == 54
    assert calls[2][1][-1]["chapters"][-1]["chapter_number"] == 58
    assert [row["chapter_number"] for row in result["outline"]["chapters"]][-12:] == list(range(51, 63))


def test_incomplete_json_splits_only_failed_batch_and_commits_once(tmp_path):
    store = project(tmp_path)
    before = (tmp_path / ".webnovel/outline.json").read_bytes()
    generator = Generator(end=56)
    original_blueprint = generator.generate_ending_blueprint
    original_batch = generator.generate_chapter_batch
    blueprint_calls, calls = [], []
    def blueprint(*args, **kwargs):
        blueprint_calls.append(1)
        return original_blueprint(*args, **kwargs)
    def batch(brief, *, chapter_numbers, previous_batches, **kwargs):
        assert (tmp_path / ".webnovel/outline.json").read_bytes() == before
        calls.append((list(chapter_numbers), deepcopy(previous_batches)))
        if len(chapter_numbers) > 2:
            raise ValueError("invalid_chapter_batch_json")
        return original_batch(brief, chapter_numbers=chapter_numbers, **kwargs)
    generator.generate_ending_blueprint = blueprint
    generator.generate_chapter_batch = batch
    result = plan_ending(store, generator)
    assert len(blueprint_calls) == 1
    assert [numbers for numbers, _ in calls] == [[51, 52, 53, 54], [51, 52], [53, 54], [55, 56]]
    assert not calls[1][1]
    assert calls[2][1][-1]["chapters"][-1]["chapter_number"] == 52
    assert calls[3][1][-1]["chapters"][-1]["chapter_number"] == 54
    assert result["chapter_count"] == 6


def test_invalid_single_chapter_stops_without_saving(tmp_path):
    store = project(tmp_path)
    before = (tmp_path / ".webnovel/outline.json").read_bytes()
    generator = Generator(end=54)
    calls = []
    def batch(brief, *, chapter_numbers, **kwargs):
        calls.append(list(chapter_numbers))
        raise ValueError("invalid_chapter_batch_json")
    generator.generate_chapter_batch = batch
    with pytest.raises(ValueError, match="invalid_chapter_batch_json"):
        plan_ending(store, generator)
    assert calls == [[51, 52, 53, 54], [51, 52], [51]]
    assert (tmp_path / ".webnovel/outline.json").read_bytes() == before


def test_multi_file_commit_rolls_back_on_replace_failure(tmp_path, monkeypatch):
    store = project(tmp_path)
    paths = [tmp_path / ".webnovel/outline.json", tmp_path / ".story-system/outline.json"]
    before = [p.read_bytes() for p in paths]
    replace = SnapshotStore._replace_file
    failed = False
    def replace_once(source, target):
        nonlocal failed
        if target == paths[1] and not failed:
            failed = True
            raise OSError("disk full")
        return replace(source, target)
    monkeypatch.setattr(SnapshotStore, "_replace_file", staticmethod(replace_once))
    with pytest.raises(OSError, match="disk full"):
        plan_ending(store, Generator())
    assert [p.read_bytes() for p in paths] == before


def test_base_snapshot_required_for_existing_ending(tmp_path):
    store = project(tmp_path, True)
    (tmp_path / ".story-system/continuity/snapshots/0050.json").unlink()
    with pytest.raises(ValueError, match="ending_planning_base_snapshot_missing"):
        _ending_input(store, None)


def test_blueprint_uses_planner_gateway_and_supplies_canon_and_closing_constraints(tmp_path):
    from packages.story_core.model_gateway import ModelResponse
    from packages.story_core.outline_planning_generation import LLMOutlinePlanningGenerator
    from packages.story_core.runtime_config import StageRuntimeSettings
    store = project(tmp_path, True)
    _, brief, constraints = _ending_input(store, None)
    calls = []
    class Gateway:
        def complete_stage(self, stage, request):
            calls.append((stage, request))
            data = Generator().generate_ending_blueprint(brief, constraints=constraints, guidance="")
            return ModelResponse.success(request, text=json.dumps(data, ensure_ascii=False))
    runtime = StageRuntimeSettings(provider_id="deepseek", protocol="openai_compatible", model="test",
                                   api_key="test-key", base_url="https://example.test", temperature=0.2)
    result = LLMOutlinePlanningGenerator(runtime_resolver=lambda _: runtime, model_gateway=Gateway()).generate_ending_blueprint(
        brief, constraints=constraints, guidance="白描")
    assert result.volume.is_final_arc
    stage, request = calls[0]
    assert stage == "planner" and request.operation == "outline_planning_ending_blueprint"
    context = json.loads(request.messages[1]["content"])
    assert context["canon"]["current_chapter"] == 50
    assert context["constraints"]["fixed_end_chapter"] == 53
    assert context["guidance"] == "白描"
