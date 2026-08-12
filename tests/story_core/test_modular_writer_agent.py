"""Tests for the modular writer agent boundary.

The writer agent is the only path that turns a director-approved
chapter plan into prose. The boundary contract is:

1. One ``WriterRequest`` in, one ``WriterResult`` out.
2. The agent must not know whether the backing runtime is
   Codex CLI, Gemini CLI, or an HTTP API — it talks to a
   ``WriterRuntime`` protocol only.
3. The rendered prompt must contain the director artifact and
   the selected context the request asked for, but not internal
   trace hashes, unrelated character cards, or retired entities.
4. Empty model output must surface as ``writer_empty_body``.
5. Every model call enters the project-level prompt_call_log so
   the workbench can audit what the writer asked and what came
   back, with the resolved provider / model / status fields
   filled from the same stage settings the gateway saw.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from packages.story_core.agents.contracts import (
    DirectorArtifact,
    EntityRequirement,
    SceneBeat,
    WriterRequest,
    WriterResult,
)
from packages.story_core.agents.writer import WriterAgent
from packages.story_core.agents.writer.prompt import build_writer_prompt
from packages.story_core.agents.writer.runtime import (
    GatewayWriterRuntime,
    WriterRuntime,
)
from packages.story_core.prompt_call_log import (
    PromptCallLog,
    prompt_call_recording,
)


# --- Test doubles -----------------------------------------------------------


@dataclass
class _RecordingRuntime:
    """Capture every ModelRequest the writer sends through."""

    responses: list[str]
    requests: list[Any] = field(default_factory=list)
    error: Exception | None = None
    call_count: int = 0

    def complete(self, request: Any) -> Any:
        self.call_count += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        text = self.responses.pop(0) if self.responses else ""
        return _Response(text=text)


@dataclass
class _Response:
    text: str
    finish_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)


def _director_artifact() -> DirectorArtifact:
    return DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 7,
            "chapter_goal": "天黑前离开妖林深处",
            "opening_state": "林照左肩受伤。",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "妖林",
                    "action": "起身",
                    "result": "沿溪流走出密林",
                }
            ],
            "ending_state": "抵达驿站。",
            "entity_requirements": [
                {"kind": "character", "name": "林照"},
            ],
        }
    )


def _writer_request(**overrides: Any) -> WriterRequest:
    payload: dict[str, Any] = {
        "chapter_number": 7,
        "director_artifact": _director_artifact(),
        "previous_tail": "林照按住左肩喘息。",
        "continuity_facts": [{"id": "f1", "subject": "林照", "field": "left_shoulder", "value": "抓伤"}],
        "character_cards": [
            {"id": "char-lin", "name": "林照", "role": "主角", "lifecycle": "active"},
            {"id": "char-zhou", "name": "周执事", "role": "师父", "lifecycle": "retired"},
        ],
        "entity_cards": [
            {"id": "loc-yao", "name": "妖林", "lifecycle": "active"},
            {"id": "loc-old", "name": "旧神龛", "lifecycle": "retired"},
        ],
        "world_rules": ["时间倒流不可逆。", "灵力以丹田为核心。"],
        "craft_modules": [
            {"id": "dialogue-natural", "content": "对话先回应再表态。"},
        ],
    }
    payload.update(overrides)
    return WriterRequest.model_validate(payload)


# --- Boundary contract -----------------------------------------------------


def test_writer_agent_takes_one_request_and_returns_one_result() -> None:
    runtime = _RecordingRuntime(responses=["林照起身，离开妖林。"])
    agent = WriterAgent(runtime=runtime)

    result = agent.run(_writer_request())

    assert isinstance(result, WriterResult)
    assert result.body == "林照起身，离开妖林。"
    assert runtime.call_count == 1
    # The agent must consume exactly one model call per request —
    # no hidden expansion or rewrite passes.
    assert result.notes == ""


def test_writer_agent_rewrites_once_when_first_draft_exceeds_hard_max() -> None:
    runtime = _RecordingRuntime(responses=["甲" * 31, "乙" * 18])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == "乙" * 18
    assert runtime.call_count == 2
    assert "上一稿约31字" in runtime.requests[1].prompt
    assert "只需删减约" in runtime.requests[1].prompt
    assert "不要从头另写" in runtime.requests[1].prompt
    assert "不可压成摘要" in runtime.requests[1].prompt
    assert runtime.requests[1].metadata["attempt"] == 2


def test_writer_agent_does_not_rewrite_without_human_approval() -> None:
    first_draft = "甲" * 31
    runtime = _RecordingRuntime(responses=[first_draft, "乙" * 18])
    agent = WriterAgent(runtime=runtime)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == first_draft
    assert runtime.call_count == 1


def test_writer_agent_rewrites_again_when_first_compaction_is_still_over_limit() -> None:
    runtime = _RecordingRuntime(responses=["甲" * 31, "乙" * 28, "丙" * 18])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == "丙" * 18
    assert runtime.call_count == 3
    assert runtime.requests[2].metadata["attempt"] == 3
    assert runtime.requests[2].metadata["reason"] == "over_hard_max"


def test_writer_agent_expands_draft_when_it_is_below_acceptance_minimum() -> None:
    runtime = _RecordingRuntime(responses=["甲" * 7, "乙" * 18])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == "乙" * 18
    assert runtime.call_count == 2
    assert runtime.requests[1].metadata["attempt"] == 2
    assert runtime.requests[1].metadata["reason"] == "under_acceptance_min"
    assert "上一稿约7字" in runtime.requests[1].prompt
    assert "只需增加约" in runtime.requests[1].prompt
    assert "不要从头另写" in runtime.requests[1].prompt
    assert "在原有段落之间补入" in runtime.requests[1].prompt


def test_writer_agent_can_expand_after_two_overlong_compactions() -> None:
    runtime = _RecordingRuntime(
        responses=["甲" * 31, "乙" * 28, "丙" * 7, "丁" * 18]
    )
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == "丁" * 18
    assert runtime.call_count == 4
    assert runtime.requests[3].metadata["attempt"] == 4
    assert runtime.requests[3].metadata["reason"] == "under_acceptance_min"


def test_writer_agent_alternates_repair_direction_but_returns_closest_draft() -> None:
    runtime = _RecordingRuntime(
        responses=["甲" * 31, "乙" * 7, "丙" * 30, "丁" * 6]
    )
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == "乙" * 7
    assert runtime.call_count == 5
    assert runtime.requests[4].metadata["attempt"] == 5
    assert runtime.requests[2].metadata["reason"] == "under_acceptance_min"
    assert runtime.requests[3].metadata["reason"] == "over_hard_max"
    assert "丙" * 30 in runtime.requests[3].prompt


def test_writer_agent_rewrites_explicit_non_graphic_guidance_violation() -> None:
    graphic = ("事故发生，伤者内脏破裂。" + "甲" * 3800)
    compliant = ("事故发生，伤者被送往医院。" + "乙" * 3800)
    runtime = _RecordingRuntime(responses=[graphic, compliant])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            rewrite_guidance="车祸不描写器官、脑组织或尸体细节。",
            repair_length=True,
        )
    )

    assert result.body == compliant
    assert result.notes == ""
    assert runtime.call_count == 2
    assert runtime.requests[1].metadata["reason"] == "rewrite_guidance_violation"
    assert "内脏" in runtime.requests[1].prompt


def test_writer_agent_rewrites_long_form_transcription() -> None:
    copied_form = (
        "事故地点：路口\n"
        "事故时间：十八点\n"
        "当事人姓名：赵某\n"
        "处理结果：等待事故发生\n"
        + "甲" * 20
    )
    runtime = _RecordingRuntime(responses=[copied_form, "乙" * 18])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 40},
            acceptance_chars={"min": 8, "max": 100},
            repair_length=True,
        )
    )

    assert result.body == "乙" * 18
    assert runtime.requests[1].metadata["reason"] == "document_transcription"
    assert "总共最多保留三行" in runtime.requests[1].prompt


def test_writer_agent_rewrites_dense_simile_stacking() -> None:
    stacked = "。".join(
        [
            "风仿佛一只手",
            "雷声如同重锤",
            "灰尘犹如潮水",
            "火光宛如星辰",
            "伤口就像裂缝",
            "黑云像是铁幕",
            "脚步仿佛鼓点",
            "冷意如同细针",
        ]
    )
    clean = "人物观察到雷声变重，立刻退到石墙后面。" * 5
    runtime = _RecordingRuntime(responses=[stacked, clean])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 200},
            acceptance_chars={"min": 8, "max": 300},
            repair_length=True,
            rewrite_guidance="STYLE-ORIGINAL-MARKER",
        )
    )

    assert result.body == clean
    assert runtime.call_count == 2
    assert runtime.requests[1].metadata["reason"] == "simile_stacking"
    assert "改成直接的动作、状态和结果" in runtime.requests[1].prompt
    assert "STYLE-ORIGINAL-MARKER" not in runtime.requests[1].prompt


def test_writer_agent_repairs_length_before_similes_when_both_fail() -> None:
    stacked = "仿佛如同犹如宛如就像像是仿佛如同" + "甲" * 40
    runtime = _RecordingRuntime(responses=[stacked, "乙" * 18])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == "乙" * 18
    assert runtime.requests[1].metadata["reason"] == "over_hard_max"


def test_writer_agent_repairs_length_before_document_transcription() -> None:
    copied_overlong = (
        "事故地点：路口\n"
        "事故时间：十八点\n"
        "当事人姓名：赵某\n"
        "处理结果：等待事故发生\n"
        + "甲" * 40
    )
    compact = "乙" * 18
    runtime = _RecordingRuntime(responses=[copied_overlong, compact])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == compact
    assert runtime.requests[1].metadata["reason"] == "over_hard_max"


def test_writer_agent_keeps_valid_length_draft_when_style_repair_explodes() -> None:
    stacked = "仿佛如同犹如宛如就像像是仿佛如同" + "甲" * 30
    runtime = _RecordingRuntime(responses=[stacked, "乙" * 80])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 60},
            acceptance_chars={"min": 8, "max": 70},
            repair_length=True,
        )
    )

    assert result.body == stacked


def test_writer_agent_tightens_each_overlong_compaction_target() -> None:
    runtime = _RecordingRuntime(
        responses=["甲" * 31, "乙" * 29, "丙" * 27, "丁" * 18]
    )
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == "丁" * 18
    assert runtime.call_count == 4
    assert "上一稿约27字" in runtime.requests[3].prompt
    assert "只需删减约" in runtime.requests[3].prompt
    assert "18至20字" in runtime.requests[3].prompt


def test_writer_agent_gets_one_final_repair_after_length_oscillation() -> None:
    runtime = _RecordingRuntime(
        responses=["甲" * 31, "乙" * 7, "丙" * 29, "丁" * 25, "戊" * 18]
    )
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": 20},
            acceptance_chars={"min": 8, "max": 24},
            repair_length=True,
        )
    )

    assert result.body == "戊" * 18
    assert runtime.call_count == 5
    assert runtime.requests[4].metadata["reason"] == "over_hard_max"


def test_writer_agent_trims_small_final_overflow_without_cutting_hook() -> None:
    opening = "陈默推开仓库门。"
    expendable = "墙边堆着多年没人处理的破木箱，灰尘落得很厚。"
    hook = "门外忽然传来脚步声。"
    draft = f"{opening}\n\n{expendable}\n\n{hook}"
    compact_length = len("".join(draft.split()))
    runtime = _RecordingRuntime(responses=[draft, "短。", "短。", "短。", "短。"])
    agent = WriterAgent(runtime=runtime, allow_automatic_repair=True)

    result = agent.run(
        _writer_request(
            target_chars={"min": 10, "max": compact_length - 6},
            acceptance_chars={"min": 10, "max": compact_length - 5},
            repair_length=True,
        )
    )

    assert len("".join(result.body.split())) <= compact_length - 5
    assert opening in result.body
    assert hook in result.body
    assert expendable not in result.body
    assert "deterministic_length_trim" in result.notes


def test_writer_agent_uses_same_request_contract_for_cli_and_api_runtimes() -> None:
    cli_runtime = _RecordingRuntime(responses=["body-cli"])
    api_runtime = _RecordingRuntime(responses=["body-api"])

    cli_agent = WriterAgent(runtime=cli_runtime)
    api_agent = WriterAgent(runtime=api_runtime)

    request = _writer_request()
    cli_result = cli_agent.run(request)
    api_result = api_agent.run(request)

    # The same WriterRequest must produce a WriterResult regardless
    # of which runtime is plugged in; only the body text differs.
    assert cli_result.body == "body-cli"
    assert api_result.body == "body-api"
    assert isinstance(cli_result, WriterResult)
    assert isinstance(api_result, WriterResult)


def test_writer_agent_prompt_contains_director_artifact_and_context() -> None:
    runtime = _RecordingRuntime(responses=["正文"])
    agent = WriterAgent(runtime=runtime)
    request = _writer_request()

    agent.run(request)

    prompt = runtime.requests[0].prompt
    assert "天黑前离开妖林" in prompt
    assert "林照按住左肩" in prompt
    assert "时间倒流不可逆" in prompt
    # Selected craft module content must make it into the prompt.
    assert "对话先回应" in prompt


def test_writer_agent_runtime_receives_final_plan_without_title_strategy() -> None:
    runtime = _RecordingRuntime(responses=["顾临背着守夜人跃上屋顶。"])
    artifact = DirectorArtifact(
        chapter_number=12,
        chapter_title="余烬照夜",
        chapter_goal="顾临在钟楼熄灭前救出被困的守夜人",
        opening_state="钟楼起火，楼梯已经断裂。",
        scene_beats=[
            SceneBeat(
                order=1,
                location="旧钟楼",
                action="顾临沿外墙攀上钟室",
                result="他找到守夜人并确认唯一出口",
            )
        ],
        ending_state="两人落到相邻屋顶，钟楼在身后坍塌。",
        hook="守夜人交出一枚刻着王室徽记的钥匙。",
    )

    WriterAgent(runtime=runtime).run(
        _writer_request(
            chapter_number=12,
            project_title="诸天薪火",
            director_artifact=artifact,
        )
    )

    prompt = runtime.requests[0].prompt
    assert "诸天薪火" in prompt
    assert artifact.chapter_goal in prompt
    assert artifact.scene_beats[0].action in prompt
    assert artifact.scene_beats[0].result in prompt
    assert artifact.hook in prompt
    for planning_only_text in (
        "核心卖点/能力",
        "章节标题必须对应",
        "满级魔龙",
        "chapter_title_strategy",
        "book_title_candidates",
        "三个候选",
    ):
        assert planning_only_text not in prompt


def test_commercial_shuangwen_modular_writer_loads_only_writer_modules() -> None:
    runtime = _RecordingRuntime(responses=["沈砚收起拓印，走向藏谱阁。"])
    request = _writer_request(
        genre="玄幻",
        craft_modules=[
            {"id": "commercial-shuangwen", "enabled": True},
            {
                "id": "commercial-shuangwen::plot-engine",
                "enabled": True,
                "content": "plot-engine：5—15章推进说明",
            },
            {
                "id": "commercial-shuangwen::chapter-sop",
                "enabled": True,
                "content": "chapter-sop：章节规划指令",
            },
            {
                "id": "commercial-shuangwen::writer-execution",
                "enabled": True,
                "content": "未筛选的写手规则",
            },
            {
                "id": "commercial-shuangwen::review-checklist",
                "enabled": True,
                "content": "review-checklist：审稿检查",
            },
            {
                "id": "commercial-shuangwen::genre-examples",
                "enabled": True,
                "content": "未按题材筛选的公会押上声望示例",
            },
        ],
    )

    WriterAgent(runtime=runtime).run(request)

    model_request = runtime.requests[0]
    prompt = model_request.prompt
    assert model_request.metadata["loaded_skill_module_ids"] == [
        "commercial-shuangwen::genre-examples",
        "commercial-shuangwen::writer-execution",
    ]
    assert model_request.metadata["writer_skill_context_chars"] <= 2200
    assert "写清施压者为什么误判" in prompt
    assert "周执事押上长老担保" in prompt
    assert "审核员怕担责而扣件" in prompt
    assert prompt.count("周执事押上长老担保") == 1
    assert prompt.count("审核员怕担责而扣件") == 1
    for excluded in (
        "plot-engine",
        "chapter-sop",
        "review-checklist",
        "5—15章",
        "审稿检查",
        "能断句就断句",
        "公会押上声望",
        "供应商承担违约风险停货",
    ):
        assert excluded not in prompt


@pytest.mark.parametrize(
    "craft_modules",
    [
        [],
        [{"id": "commercial-shuangwen", "enabled": True}],
        [
            {"id": "commercial-shuangwen", "enabled": True},
            {"id": "commercial-shuangwen::writer-execution", "enabled": False},
        ],
        [{"id": "missing-pack::writer-execution", "enabled": True}],
    ],
)
def test_modular_writer_ignores_disabled_or_missing_skill_modules(craft_modules) -> None:
    baseline_runtime = _RecordingRuntime(responses=["正文。"])
    selected_runtime = _RecordingRuntime(responses=["正文。"])

    WriterAgent(runtime=baseline_runtime).run(_writer_request(genre="玄幻", craft_modules=[]))
    WriterAgent(runtime=selected_runtime).run(
        _writer_request(genre="玄幻", craft_modules=craft_modules)
    )

    assert selected_runtime.requests[0].prompt == baseline_runtime.requests[0].prompt
    assert selected_runtime.requests[0].metadata.get("loaded_skill_module_ids", []) == []


def test_writer_prompt_contains_one_off_rewrite_guidance() -> None:
    prompt = build_writer_prompt(
        _writer_request(rewrite_guidance="事故只写必要后果，不描写器官和尸体细节。")
    )

    assert "## 本次写作指导（优先执行）" in prompt
    assert "事故只写必要后果" in prompt


def test_writer_prompt_contains_numeric_length_policy_and_current_character_state() -> None:
    """The writer prompt must include the concrete length policy
    and the active character's current state (including game
    state) so the model can keep prose on the hard production
    target and stop hallucinating equipment or quests.
    """
    request = WriterRequest(
        chapter_number=2,
        director_artifact=_director_artifact(),
        target_chars={"min": 4200, "max": 5500},
        acceptance_chars={"min": 3800, "max": 5700},
        character_cards=[{
            "name": "苏叶",
            "role": "protagonist",
            "lifecycle": "active",
            "real_state": {"current": {"balance": "61.10元"}},
            "game_state": {"current": {
                "game_id": "夜烬",
                "level": "Lv.2",
                "class_path": "见习者（未转职）",
                "equipment": {"main_hand": "新手法杖"},
                "inventory": {"灰狼毒腺": 8},
                "quests": {"active": "清道夫：8/16；未提交"},
            }},
        }],
    )

    prompt = build_writer_prompt(request)

    assert "目标4200至5500字" in prompt
    assert "低于3800字" in prompt
    assert "超过5700字" in prompt
    assert "整章只在必要处保留一两处比喻" in prompt
    assert "新手法杖" in prompt
    assert "清道夫：8/16；未提交" in prompt


def test_writer_prompt_includes_concise_craft_baseline_and_relevant_character_voice() -> None:
    request = _writer_request(
        character_cards=[
            {
                "name": "林照",
                "role": "主角",
                "lifecycle": "active",
                "story_drive": {
                    "immediate_goal": "天黑前离开妖林",
                    "motivation": "把受伤的同伴带回城",
                },
                "performance_profile": {
                    "speech_style": "说话完整直接，不故作高深",
                    "action_style": "先观察退路再行动",
                    "decision_rules": ["不拿同伴冒险"],
                },
            },
            {
                "name": "无关城主",
                "role": "后期人物",
                "lifecycle": "active",
                "performance_profile": {"speech_style": "每句话都像宣判"},
            },
        ]
    )

    prompt = build_writer_prompt(request)

    assert "## 成稿要求" in prompt
    assert "不要替读者总结人物心理" in prompt
    assert "可谓" in prompt
    assert "世界观被击碎" in prompt
    assert "说话完整直接，不故作高深" in prompt
    assert "先观察退路再行动" in prompt
    assert "不拿同伴冒险" in prompt
    assert "无关城主" not in prompt
    assert "每句话都像宣判" not in prompt
    assert "把受伤的同伴带回城" not in prompt
    assert "严格停在导演给出的收尾状态" in prompt
    assert "每个节拍平均不超过" in prompt
    assert "文书、面板或记录最多摘三行" in prompt
    assert "不细写暴露的器官" in prompt


def test_writer_prompt_omits_empty_legacy_character_entities() -> None:
    request = _writer_request(
        entity_cards=[
            {"name": "林照", "lifecycle": "active"},
            {"name": "无关城主", "lifecycle": "active"},
        ]
    )

    prompt = build_writer_prompt(request)

    assert "## 活动实体卡" not in prompt


def test_writer_agent_prompt_excludes_unrelated_cards_and_retired_entities() -> None:
    runtime = _RecordingRuntime(responses=["正文"])
    agent = WriterAgent(runtime=runtime)
    request = _writer_request()

    agent.run(request)

    prompt = runtime.requests[0].prompt
    # The retired entity must not leak into the writer view.
    assert "旧神龛" not in prompt
    # Internal trace markers the runtime would never see must
    # not be in the prompt either.
    assert "ctx-trace" not in prompt
    assert "sha256:" not in prompt


def test_writer_agent_raises_writer_empty_body_on_blank_response() -> None:
    runtime = _RecordingRuntime(responses=["   "])
    agent = WriterAgent(runtime=runtime)

    with pytest.raises(RuntimeError, match="writer_empty_body"):
        agent.run(_writer_request())


def test_writer_agent_raises_writer_empty_body_on_empty_response() -> None:
    runtime = _RecordingRuntime(responses=[""])
    agent = WriterAgent(runtime=runtime)

    with pytest.raises(RuntimeError, match="writer_empty_body"):
        agent.run(_writer_request())


def test_writer_agent_records_proposed_facts_when_runtime_returns_them() -> None:
    @dataclass
    class FactAwareRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="正文",
                raw={
                    "proposed_facts": [
                        {"subject_id": "char-lin", "field": "left_shoulder", "value": "已包扎"}
                    ]
                },
            )

    agent = WriterAgent(runtime=FactAwareRuntime())
    result = agent.run(_writer_request())

    assert result.proposed_facts == [
        {"subject_id": "char-lin", "field": "left_shoulder", "value": "已包扎"}
    ]


# --- Runtime protocol -----------------------------------------------------


def test_gateway_writer_runtime_uses_complete_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gateway-backed runtime must route through the
    canonical ``RuntimeModelGateway.complete_stage("writer", ...)``
    so the writer agent has no knowledge of the transport
    (Codex CLI, Gemini CLI, HTTP API).
    """

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(text="正文")

    fake_gateway = _FakeGateway()
    runtime = GatewayWriterRuntime(gateway=fake_gateway)
    agent = WriterAgent(runtime=runtime)

    result = agent.run(_writer_request())

    assert result.body == "正文"
    assert len(fake_gateway.calls) == 1
    stage, request = fake_gateway.calls[0]
    assert stage == "writer"


def test_gateway_writer_runtime_translates_lightweight_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway-backed writer runtime must hand the gateway a
    real :class:`ModelRequest` — provider / model / operation
    included — even though the agent only knows about the
    lightweight ``_ModelRequest`` shape.

    Without the translation the gateway's ``dataclasses.replace``
    call would raise ``TypeError`` for the missing fields and
    the gateway's broad ``except`` would turn the call into a
    silent model-failure response. The writer agent would then
    raise ``writer_empty_body`` and the orchestrator would crash
    the chapter run. The translation reads the stage-resolved
    runtime settings to fill the missing fields the same way
    the gateway would have done internally.
    """

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(text="正文")

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-4o-mini"
        temperature = 0.5

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(_runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings())

    fake_gateway = _FakeGateway()
    runtime = GatewayWriterRuntime(gateway=fake_gateway)
    agent = WriterAgent(runtime=runtime)

    result = agent.run(_writer_request())

    assert result.body == "正文"
    assert len(fake_gateway.calls) == 1
    stage, request = fake_gateway.calls[0]
    from packages.story_core.model_gateway.contracts import ModelRequest

    assert stage == "writer"
    assert isinstance(request, ModelRequest)
    assert request.provider == "openai"
    assert request.model == "gpt-4o-mini"
    assert request.operation == "writer"


def test_writer_runtime_protocol_accepts_custom_runtime() -> None:
    """Any object that implements ``complete(request)`` must be
    usable as a ``WriterRuntime`` — the agent only depends on
    the protocol, not on the concrete type.
    """

    @dataclass
    class CustomRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(text="custom-body")

    agent: WriterAgent = WriterAgent(runtime=CustomRuntime())  # type: ignore[arg-type]
    result = agent.run(_writer_request())
    assert result.body == "custom-body"


def test_gateway_writer_runtime_records_resolved_provider_model_and_prompt(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway-backed writer runtime must record every
    successful call to the project-level ``PromptCallLog`` so
    the workbench can audit what the writer asked, which
    provider / model answered, and how long it took. The
    provider / model values come from
    :func:`resolve_stage_runtime` — the same source the
    gateway itself reads internally — so the recorded
    metadata is never a placeholder.
    """

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(text="正文记录")

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-test"
        temperature = 0.4
        protocol = "openai"

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(
        _runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings()
    )

    fake_gateway = _FakeGateway()
    runtime = GatewayWriterRuntime(gateway=fake_gateway)
    agent = WriterAgent(runtime=runtime)
    recorder = PromptCallLog(tmp_path, project_id="file:writer-log")

    with prompt_call_recording(recorder):
        result = agent.run(_writer_request())

    assert result.body == "正文记录"
    writer_calls = [
        entry for entry in recorder.list(chapter_number=7) if entry["agent"] == "writer"
    ]
    assert len(writer_calls) == 1
    entry = writer_calls[0]
    assert entry["stage"] == "writer"
    assert entry["provider"] == "openai"
    assert entry["model"] == "gpt-test"
    assert entry["status"] == "succeeded"
    assert entry["prompt_chars"] > 0
    assert entry["output_chars"] >= len("正文记录")


def test_gateway_writer_runtime_records_failure_with_status_failed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed gateway call must close the prompt_call_log
    entry as ``status="failed"`` and preserve the error
    message. The workbench's stage evidence column depends on
    this so the operator can tell a 401 from a model timeout
    at a glance.
    """

    class _FakeGateway:
        def complete_stage(self, stage: str, request: Any) -> Any:
            from packages.story_core.model_gateway.contracts import ModelRequest
            from packages.story_core.model_gateway.contracts import ModelResponse

            return ModelResponse.failure(
                ModelRequest(
                    prompt=request.prompt,
                    provider="openai",
                    model="gpt-test",
                    operation="writer",
                ),
                "missing_api_key",
            )

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-test"
        temperature = 0.4
        protocol = "openai"

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(
        _runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings()
    )

    recorder = PromptCallLog(tmp_path, project_id="file:writer-fail")
    runtime = GatewayWriterRuntime(gateway=_FakeGateway())
    agent = WriterAgent(runtime=runtime)
    # The writer must surface the failure to the agent; the
    # recorder must still capture the failed lifecycle.
    with prompt_call_recording(recorder):
        with pytest.raises(RuntimeError, match="writer_empty_body"):
            agent.run(_writer_request())

    writer_calls = [
        entry for entry in recorder.list(chapter_number=7) if entry["agent"] == "writer"
    ]
    assert len(writer_calls) == 1
    entry = writer_calls[0]
    assert entry["status"] == "failed"
    assert entry["provider"] == "openai"
    assert entry["model"] == "gpt-test"


def test_gateway_writer_runtime_does_not_rewrite_preexisting_prompt_log(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing ``index.jsonl`` (a pre-fix call the user
    already audited) must remain byte-identical after the
    runtime finishes a new call. The new entry is appended,
    not rewritten in place.
    """

    class _FakeGateway:
        def complete_stage(self, stage: str, request: Any) -> Any:
            return _Response(text="正文")

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-test"
        temperature = 0.4
        protocol = "openai"

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(
        _runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings()
    )

    recorder = PromptCallLog(tmp_path, project_id="file:writer-append")
    historical_id = recorder.start(
        chapter_number=1,
        stage="writer",
        agent="writer",
        user_prompt="历史 prompt",
        provider="legacy",
        model="legacy-model",
    )
    recorder.finish(historical_id, status="succeeded", output="历史正文")
    historical_detail_bytes = (
        tmp_path / "prompt_calls" / f"{historical_id}.json"
    ).read_bytes()
    historical_index_line = (
        tmp_path / "prompt_calls" / "index.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()[0]

    runtime = GatewayWriterRuntime(gateway=_FakeGateway())
    agent = WriterAgent(runtime=runtime)
    with prompt_call_recording(recorder):
        agent.run(_writer_request())

    # The historical detail file is byte-identical to the
    # snapshot we took before the new call — the runtime
    # appends, never rewrites.
    assert (
        tmp_path / "prompt_calls" / f"{historical_id}.json"
    ).read_bytes() == historical_detail_bytes
    # The first line of the index (the historical lifecycle
    # row) is preserved verbatim; the new lifecycle rows
    # come after.
    first_line = (
        tmp_path / "prompt_calls" / "index.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()[0]
    assert first_line == historical_index_line
    # The historical detail is still readable through the
    # public ``get`` API.
    historical_payload = recorder.get(historical_id)
    assert historical_payload["user_prompt"] == "历史 prompt"
    assert historical_payload["status"] == "succeeded"
