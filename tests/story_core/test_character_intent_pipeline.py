from __future__ import annotations

import json
from types import SimpleNamespace

from packages.story_core.agents.contracts import (
    DirectorArtifact,
    OutlineExecutionContract,
    WriterRequest,
)
from packages.story_core.agents.director.agent import DirectorAgent
from packages.story_core.agents.director.prompt import (
    build_director_prompt,
    parse_director_response,
)
from packages.story_core.agents.fact_extractor.agent import _fact_extractor_director_view
from packages.story_core.canon.registry import CanonRegistry
from packages.story_core.canon.review_snapshot import build_canon_review_snapshot
from packages.story_core.character_agent import (
    OpenAICharacterProposalProvider,
    RuleBasedCharacterProposalProvider,
)
from packages.story_core.agents.pipeline import (
    _build_writer_request,
    _chapter_cast_names,
    _character_intents_for_context,
)
from packages.story_core.agents.writer.prompt import build_writer_prompt
from packages.story_core.context.director_context import DirectorContext
from packages.story_core.context.legacy_adapter import legacy_outline_view
from packages.story_core.context.writer_context import WriterContext
from packages.story_core.models import (
    CharacterProposal,
    CharacterRelationship,
    CharacterState,
    StoryState,
)
from packages.story_core.modular_bundle_adapter import adapt_modular_bundle_to_legacy


def _rich_artifact() -> DirectorArtifact:
    return parse_director_response(
        {
            "chapter_number": 3,
            "chapter_title": "试探",
            "chapter_goal": "林渊处理比试后的关系压力",
            "opening_state": "比试刚结束",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "演武场外",
                    "purpose": "让人物对胜负作出不同反应",
                    "conflict": "苏瑶想确认林渊伤势，王胖子想拿他开玩笑",
                    "participants": ["林渊", "苏瑶", "王胖子"],
                    "action": "三人离开演武场",
                    "result": "苏瑶和林渊的关系产生轻微变化",
                    "character_intents": [
                        {
                            "name": "苏瑶",
                            "want": "确认林渊有没有受伤",
                            "target": "林渊",
                            "emotion": "担心但不愿表现得太明显",
                            "move": "借检查伤势靠近",
                            "speech_strategy": "先问伤，不直接说担心",
                            "withhold": "不承认自己一直在关注他",
                            "reaction": "被调侃后转移话题",
                            "dramatic_function": "romance_progression",
                        },
                        {
                            "name": "王胖子",
                            "want": "确认林渊到底藏了多少实力",
                            "target": "林渊",
                            "emotion": "兴奋",
                            "move": "半开玩笑地追问",
                            "dramatic_function": "comic_relief",
                        },
                    ],
                    "emotional_turn": "林渊开始察觉苏瑶的在意",
                    "relationship_shift": "两人距离略微拉近",
                    "ending_pressure": "赵家的人在远处盯上林渊",
                },
                {
                    "order": 2,
                    "location": "宗门石阶",
                    "action": "林渊察觉有人跟踪",
                    "result": "下一步压力转向赵家",
                },
            ],
            "ending_state": "林渊确认自己被盯上",
            "hook": "赵家开始调查林渊",
        }
    )


def test_director_response_keeps_rich_scene_character_intents() -> None:
    artifact = _rich_artifact()

    beat = artifact.scene_beats[0]
    assert beat.purpose == "让人物对胜负作出不同反应"
    assert beat.participants == ["林渊", "苏瑶", "王胖子"]
    assert [intent.name for intent in beat.character_intents] == ["苏瑶", "王胖子"]
    assert beat.character_intents[0].withhold == "不承认自己一直在关注他"
    assert beat.relationship_shift == "两人距离略微拉近"
    assert beat.ending_pressure == "赵家的人在远处盯上林渊"


def test_legacy_director_artifact_still_validates_without_character_intents() -> None:
    artifact = DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 1,
            "chapter_goal": "离开山谷",
            "opening_state": "天将亮",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "山谷",
                    "action": "林昭起身",
                    "result": "找到出口",
                }
            ],
            "ending_state": "走出山谷",
        }
    )

    assert artifact.scene_beats[0].character_intents == []
    assert artifact.schema_version == "director-artifact/v1"


def test_writer_prompt_treats_character_intents_as_private_control() -> None:
    artifact = _rich_artifact()
    request = WriterRequest(
        chapter_number=3,
        director_artifact=artifact,
        character_cards=[
            {
                "name": "林渊",
                "role": "protagonist",
                "performance_profile": {"speech_style": "说话直接"},
            },
            {
                "name": "苏瑶",
                "role": "女主",
                "performance_profile": {"speech_style": "嘴硬，关心时绕着说"},
            },
            {
                "name": "王胖子",
                "role": "盟友",
                "performance_profile": {"speech_style": "熟人面前爱调侃"},
            },
        ],
    )

    prompt = build_writer_prompt(request)

    assert "苏瑶想要：确认林渊有没有受伤" in prompt
    assert "不说出口：不承认自己一直在关注他" in prompt
    assert "character_intents 是作者侧写作控制" in prompt
    assert "禁止为了体现群像而让出场人物依次发表观点" in prompt


def test_writer_receives_contract_and_pipeline_character_intent_with_explicit_priority() -> None:
    artifact = _rich_artifact().model_copy(
        update={
            "outline_contract": OutlineExecutionContract(
                chapter_number=3,
                core_conflict="林渊必须在赵家封锁前拿到通行令",
                gain="拿到通行令",
                cost="暴露一次真实实力",
                state_delta="从被动躲避变成带令离场",
                planned_hook="通行令背面浮出血字",
                must_not_write=["不得提前揭开赵家幕后身份"],
            )
        }
    )
    request = WriterRequest(
        chapter_number=3,
        director_artifact=artifact,
        previous_tail="上章末尾，林渊听见山门方向传来三声钟响。",
    )

    prompt = build_writer_prompt(request)

    assert "核心冲突：林渊必须在赵家封锁前拿到通行令" in prompt
    assert "本章收益：拿到通行令" in prompt
    assert "上章末尾\n上章末尾，林渊听见山门方向传来三声钟响。" in prompt
    assert "苏瑶想要：确认林渊有没有受伤" in prompt
    assert "优先级：上游章节执行合同 > 导演公开场景计划 > Director 最终 scene-level character intents" in prompt
    assert "不得改写收益、代价、状态变化、禁止事项或章末钩子" in prompt


def test_writer_ignores_compatibility_character_intents_and_uses_director_beats_only() -> None:
    artifact = _rich_artifact()
    request = WriterRequest(
        chapter_number=3,
        director_artifact=artifact,
        # This field remains accepted for old direct callers, but must not
        # become another production prompt source.
        character_intents=[
            {
                "name": "苏瑶",
                "want": "苏瑶追出去质问林渊",
                "move": "苏瑶追出去质问林渊",
            }
        ],
    )

    prompt = build_writer_prompt(request)

    assert "苏瑶想要：确认林渊有没有受伤" in prompt
    assert "苏瑶追出去质问林渊" not in prompt


def test_production_writer_request_leaves_compatibility_intents_empty() -> None:
    artifact = _rich_artifact()
    request = _build_writer_request(
        context=WriterContext(chapter_number=3, director_artifact=artifact),
        director_artifact=artifact,
    )

    assert request.character_intents == []
    assert "苏瑶想要：确认林渊有没有受伤" in build_writer_prompt(request)


def test_writer_sees_director_rewritten_intent_but_not_raw_proposal() -> None:
    artifact = parse_director_response(
        {
            "chapter_number": 3,
            "chapter_goal": "处理通行令与关系压力",
            "opening_state": "林渊在山门前",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "山门",
                    "action": "苏瑶检查林渊伤势",
                    "result": "她没有公开追问秘密",
                    "character_intents": [
                        {
                            "name": "苏瑶",
                            "want": "只确认林渊是否受伤",
                            "move": "只问伤势，不公开追问秘密",
                            "withhold": "不提自己真正担心的事",
                        }
                    ],
                },
                {
                    "order": 2,
                    "location": "山门外",
                    "action": "林渊带令离场",
                    "result": "通行令背面留下异常痕迹",
                },
            ],
            "ending_state": "林渊带令离场",
        }
    )

    prompt = build_writer_prompt(
        WriterRequest(
            chapter_number=3,
            director_artifact=artifact,
            character_intents=[
                {
                    "name": "苏瑶",
                    "want": "苏瑶当众质问林渊",
                    "move": "苏瑶当众质问林渊",
                }
            ],
        )
    )

    assert "苏瑶想要：只确认林渊是否受伤" in prompt
    assert "只问伤势，不公开追问秘密" in prompt
    assert "苏瑶当众质问林渊" not in prompt


def test_fact_extractor_director_view_omits_private_character_intents() -> None:
    projected = _fact_extractor_director_view(_rich_artifact())

    assert projected is not None
    rendered = json.dumps(projected, ensure_ascii=False)
    assert "三人离开演武场" in rendered
    assert "不承认自己一直在关注他" not in rendered
    assert "speech_strategy" not in rendered
    assert "character_intents" not in rendered


def test_canon_review_snapshot_does_not_project_private_character_intent(tmp_path) -> None:
    snapshot = build_canon_review_snapshot(
        project_root=tmp_path,
        chapter_number=1,
        registry=CanonRegistry(),
        character_cards=[
            {
                "name": "苏瑶",
                "role": "女主",
                "private_intent": "这是作者侧秘密，不应成为事实",
                "story_drive": {"immediate_goal": "确认林渊伤势"},
            }
        ],
    )

    assert "这是作者侧秘密，不应成为事实" not in json.dumps(
        snapshot, ensure_ascii=False
    )
    assert snapshot["characters"][0]["name"] == "苏瑶"


def test_legacy_outline_view_preserves_cast(tmp_path) -> None:
    legacy_root = tmp_path / ".webnovel"
    legacy_root.mkdir(parents=True)
    (legacy_root / "outline.json").write_text(
        json.dumps(
            {
                "chapters": [
                    {
                        "chapter_number": 3,
                        "title": "比试之后",
                        "goal": "处理赛后压力",
                        "obstacle": "赵家盯上林渊",
                        "action": "离开演武场",
                        "turn": "察觉跟踪",
                        "payoff": "关系推进",
                        "ending_hook": "赵家开始调查",
                        "cast": ["林渊", "苏瑶", "王胖子"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    view = legacy_outline_view(tmp_path / ".story-system")

    assert view is not None
    chapter = view["chapters"][0]
    assert chapter["cast"] == ["林渊", "苏瑶", "王胖子"]
    assert chapter["turn"] == "察觉跟踪"
    assert chapter["ending_hook"] == "赵家开始调查"


def test_relevant_cast_prefers_explicit_chapter_cast_and_adds_protagonist() -> None:
    story = StoryState(
        story_id="s-intent-cast",
        outline="宗门比试后各方重新评估林渊。",
        genre="玄幻",
        style="自然口语",
        current_chapter=2,
        outline_context={
            "chapter": {
                "chapter_number": 3,
                "cast": ["苏瑶", "王胖子"],
                "goal": "处理赛后关系和新的敌意",
            }
        },
        characters=[
            CharacterState(name="林渊", role="protagonist"),
            CharacterState(name="苏瑶", role="女主"),
            CharacterState(name="王胖子", role="盟友"),
            CharacterState(name="赵天衡", role="stage_antagonist"),
        ],
    )
    context = DirectorContext(
        chapter_number=3,
        volume={"chapter_range": [1, 20]},
        book_outline_summary="",
        nearby_outline=[
            {
                "number": 3,
                "goal": "处理赛后关系和新的敌意",
                "cast": ["苏瑶", "王胖子"],
            }
        ],
        character_cards=[],
    )

    names = _chapter_cast_names(story, context, 3)

    assert names[:3] == ["苏瑶", "王胖子", "林渊"]
    assert "赵天衡" not in names



class _RecordingCharacterAgent:
    def __init__(self) -> None:
        self.seen_names: list[str] = []
        self.seen_chapter: dict = {}

    def propose_all(self, story: StoryState) -> list[CharacterProposal]:
        self.seen_names = [character.name for character in story.characters]
        raw_chapter = (
            story.outline_context.get("chapter")
            if isinstance(story.outline_context, dict)
            else {}
        )
        self.seen_chapter = dict(raw_chapter) if isinstance(raw_chapter, dict) else {}
        return [
            CharacterProposal(
                name=character.name,
                goal=f"{character.name}自己的目标",
                emotion="active",
                action=f"{character.name}采取自己的行动",
                target="林渊" if character.name != "林渊" else "",
                speech_strategy="按自己的说话方式试探",
                withhold="不把全部想法说出口",
                dramatic_function="relationship_pressure",
                priority=5,
            )
            for character in story.characters
        ]


def test_character_intent_stage_only_runs_selected_cast() -> None:
    story = StoryState(
        story_id="s-intent-stage",
        outline="宗门比试之后。",
        genre="玄幻",
        style="自然口语",
        current_chapter=2,
        outline_context={
            "chapter": {
                "chapter_number": 3,
                "cast": ["苏瑶", "王胖子"],
                "goal": "处理赛后关系",
            }
        },
        characters=[
            CharacterState(name="林渊", role="protagonist"),
            CharacterState(name="苏瑶", role="女主"),
            CharacterState(name="王胖子", role="盟友"),
            CharacterState(name="赵天衡", role="stage_antagonist"),
        ],
    )
    context = DirectorContext(
        chapter_number=3,
        volume={"chapter_range": [1, 20]},
        book_outline_summary="",
        nearby_outline=[
            {
                "number": 3,
                "goal": "处理赛后关系",
                "core_conflict": "赵家封锁前处理赛后关系",
                "gain": "拿到通行令",
                "cost": "暴露真实实力",
                "state_delta": "从场内转为带令离场",
                "hook": "赵家开始调查",
                "chapter_sop": {"opening_carry": "比试刚结束"},
                "payoff_contract": {"required": "关系发生变化"},
                "must_not_write": ["不得揭开赵家幕后身份"],
                "cast": ["苏瑶", "王胖子"],
            }
        ],
        character_cards=[],
    )
    agent = _RecordingCharacterAgent()

    intents = _character_intents_for_context(
        story,
        context,
        3,
        agent=agent,  # type: ignore[arg-type]
    )

    assert agent.seen_names == ["苏瑶", "王胖子", "林渊"]
    assert [item["name"] for item in intents] == ["苏瑶", "王胖子", "林渊"]
    assert intents[0]["withhold"] == "不把全部想法说出口"
    assert agent.seen_chapter["core_conflict"] == "赵家封锁前处理赛后关系"
    assert agent.seen_chapter["gain"] == "拿到通行令"
    assert agent.seen_chapter["cost"] == "暴露真实实力"
    assert agent.seen_chapter["state_delta"] == "从场内转为带令离场"
    assert agent.seen_chapter["planned_hook"] == "赵家开始调查"
    assert agent.seen_chapter["chapter_sop"] == {"opening_carry": "比试刚结束"}
    assert agent.seen_chapter["payoff_contract"] == {"required": "关系发生变化"}
    assert agent.seen_chapter["must_not_write"] == ["不得揭开赵家幕后身份"]


def test_character_intent_stage_does_not_fall_back_to_all_active_characters() -> None:
    story = StoryState(
        story_id="s-intent-no-cast",
        outline="一章没有明确出场角色。",
        genre="玄幻",
        style="自然口语",
        current_chapter=2,
        characters=[
            CharacterState(name="甲", role="supporting"),
            CharacterState(name="乙", role="supporting"),
        ],
    )
    context = DirectorContext(
        chapter_number=3,
        volume={"chapter_range": [1, 20]},
        book_outline_summary="",
        nearby_outline=[{"number": 3, "goal": "推进主线", "cast": []}],
        character_cards=[],
    )
    agent = _RecordingCharacterAgent()

    assert _character_intents_for_context(story, context, 3, agent=agent) == []
    assert agent.seen_names == []


class _FailingCharacterAgent:
    def __init__(self) -> None:
        self.rule_provider = _RecordingCharacterAgent()

    def propose_all(self, _story: StoryState) -> list[CharacterProposal]:
        raise RuntimeError("character agent unavailable")


def test_character_intent_failure_uses_bounded_rule_fallback() -> None:
    story = StoryState(
        story_id="s-intent-fallback",
        outline="赛后关系变化。",
        genre="玄幻",
        style="自然口语",
        current_chapter=2,
        outline_context={"chapter": {"chapter_number": 3, "cast": ["苏瑶"]}},
        characters=[
            CharacterState(name="林渊", role="protagonist"),
            CharacterState(name="苏瑶", role="女主"),
            CharacterState(name="赵天衡", role="stage_antagonist"),
        ],
    )
    context = DirectorContext(
        chapter_number=3,
        volume={"chapter_range": [1, 20]},
        book_outline_summary="",
        nearby_outline=[{"number": 3, "cast": ["苏瑶"]}],
        character_cards=[],
    )
    agent = _FailingCharacterAgent()

    intents = _character_intents_for_context(story, context, 3, agent=agent)  # type: ignore[arg-type]

    assert agent.rule_provider.seen_names == ["苏瑶", "林渊"]
    assert {item["name"] for item in intents} == {"苏瑶", "林渊"}
    assert "赵天衡" not in {item["name"] for item in intents}


def test_character_provider_prompt_contains_full_execution_contract() -> None:
    story = StoryState(
        story_id="s-intent-prompt-contract",
        outline="拿到通行令并留下钩子。",
        genre="玄幻",
        style="自然口语",
        current_chapter=2,
        outline_context={
            "chapter": {
                "chapter_number": 3,
                "core_conflict": "赵家封锁前拿到通行令",
                "gain": "拿到通行令",
                "cost": "暴露实力",
                "state_delta": "从被动转为带令离场",
                "planned_hook": "令牌背面浮出血字",
                "opening_carry": "上章钟声未停",
                "chapter_sop": {"opening_carry": "上章钟声未停"},
                "payoff_contract": {"required": "通行令到手"},
                "must_not_write": ["不得揭开幕后人"],
                "cast": ["林渊"],
            }
        },
        characters=[CharacterState(name="林渊", role="protagonist")],
    )

    prompt = OpenAICharacterProposalProvider()._build_prompt(story, story.characters)

    assert "赵家封锁前拿到通行令" in prompt
    assert "拿到通行令" in prompt
    assert "暴露实力" in prompt
    assert "从被动转为带令离场" in prompt
    assert "令牌背面浮出血字" in prompt
    assert "不得揭开幕后人" in prompt
    assert "Character proposals must stay inside the current chapter execution contract." in prompt


def test_director_prompt_receives_character_intents_as_optional_pressure() -> None:
    context = DirectorContext(
        chapter_number=3,
        volume={"chapter_range": [1, 20]},
        book_outline_summary="",
        nearby_outline=[
            {
                "number": 3,
                "title": "比试之后",
                "summary": "林渊赢下比试，各方反应不同。",
                "cast": ["林渊", "苏瑶", "王胖子"],
            }
        ],
        character_cards=[
            {
                "name": "苏瑶",
                "role": "女主",
                "narrative_function": "love_interest",
                "story_drive": {"immediate_goal": "确认林渊伤势"},
            }
        ],
        character_intents=[
            {
                "name": "苏瑶",
                "goal": "确认林渊有没有受伤",
                "target": "林渊",
                "action": "借检查伤势靠近",
                "withhold": "不承认一直在关注他",
                "priority": 7,
            }
        ],
    )

    prompt = build_director_prompt(context)

    assert "人物当前意图（候选压力" in prompt
    assert "确认林渊有没有受伤" in prompt
    assert "可以采用、延后、阻断或让它们互相冲突" in prompt
    assert "不要求所有出场人物都有台词或动作" in prompt
    assert "OutlineExecutionContract > Character Intent > Director staging" in prompt
    assert "Character Intent 是候选压力，不是 required event" in prompt


class _ConflictingDirectorRuntime:
    def complete(self, _request):
        return {
            "chapter_number": 3,
            "chapter_title": "伪造标题",
            "chapter_goal": "放弃通行令",
            "opening_state": "林渊在山门前",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "山门",
                    "action": "林渊试图通过",
                    "result": "守门人交出通行令",
                },
                {
                    "order": 2,
                    "location": "山门外",
                    "action": "林渊查看令牌",
                    "result": "令牌背面浮出血字",
                },
            ],
            "ending_state": "林渊拿到通行令",
            "hook": "人物意图提出的伪造钩子",
        }


def test_director_keeps_program_contract_and_planned_hook_over_character_pressure(
    tmp_path,
) -> None:
    context = DirectorContext(
        chapter_number=3,
        volume={"chapter_range": [1, 20]},
        book_outline_summary="",
        nearby_outline=[
            {
                "number": 3,
                "core_conflict": "赵家封锁前拿到通行令",
                "gain": "拿到通行令",
                "cost": "暴露实力",
                "state_delta": "从被动转为带令离场",
                "hook": "令牌背面浮出血字",
                "must_not_write": ["不得揭开幕后人"],
            }
        ],
        character_intents=[
            {
                "name": "林渊",
                "goal": "放弃通行令",
                "action": "转身离开",
            }
        ],
    )

    artifact = DirectorAgent(
        runtime=_ConflictingDirectorRuntime(),
        project_root=tmp_path,
    ).plan(context)

    assert artifact.outline_contract is not None
    assert artifact.outline_contract.gain == "拿到通行令"
    assert artifact.outline_contract.state_delta == "从被动转为带令离场"
    assert artifact.outline_contract.planned_hook == "令牌背面浮出血字"
    assert artifact.hook == artifact.outline_contract.planned_hook
    assert artifact.schema_version == "director-artifact/v1"


def test_modular_bundle_adapter_preserves_character_intent_lifecycle() -> None:
    artifact = _rich_artifact()
    story = StoryState(
        story_id="s-adapter-intents",
        outline="赛后关系变化。",
        genre="玄幻",
        style="自然口语",
        current_chapter=2,
        characters=[
            CharacterState(name="林渊", role="protagonist"),
            CharacterState(name="苏瑶", role="女主"),
            CharacterState(name="王胖子", role="盟友"),
        ],
    )
    writer_context = WriterContext(
        chapter_number=3,
        director_artifact=artifact,
        character_cards=[
            {"name": "林渊", "role": "protagonist"},
            {"name": "苏瑶", "role": "女主"},
            {"name": "王胖子", "role": "盟友"},
        ],
    )
    modular = SimpleNamespace(
        director_artifact=artifact,
        body="林渊走出演武场，苏瑶跟了上来，王胖子在旁边笑了一句。",
        consistency_findings=[],
        continuity_delta=None,
        writer_context=writer_context,
        canon_preflight={},
    )

    bundle = adapt_modular_bundle_to_legacy(
        story=story,
        modular_bundle=modular,
        chapter_number=3,
    )

    suyao = next(move for move in bundle.character_moves if move["name"] == "苏瑶")
    assert suyao["withhold"] == "不承认自己一直在关注他"
    assert bundle.scene_cards[0]["character_intents"][0]["name"] == "苏瑶"
    assert bundle.scene_cards[0]["relationship_shift"] == "两人距离略微拉近"
    assert bundle.pipeline_stages[0] == "character_intent"


def test_rule_based_character_proposal_can_stay_inactive_without_stimulus() -> None:
    story = StoryState(
        story_id="s-intent-noop",
        outline="本章没有触及路人的利益。",
        genre="玄幻",
        style="自然中文",
        characters=[CharacterState(name="路人甲", role="supporting")],
    )

    proposal = RuleBasedCharacterProposalProvider().propose_all(story)[0]

    assert proposal.goal == "暂不行动，先观察局势"
    assert proposal.action == ""
    assert proposal.priority == 0


def test_rule_based_character_proposals_keep_personality_pressure_distinct() -> None:
    story = StoryState(
        story_id="s-intent-personality",
        outline="林渊赢下宗门比试。",
        genre="玄幻",
        style="自然中文",
        characters=[
            CharacterState(
                name="林渊",
                role="protagonist",
                goals=["守住胜利并查清赵家动机"],
            ),
            CharacterState(
                name="苏瑶",
                role="love_interest",
                goals=["确认林渊伤势"],
                current_emotion="介意",
                relationships={
                    "lin": CharacterRelationship(target="林渊", tension=0.8)
                },
            ),
            CharacterState(
                name="王胖子",
                role="ally",
                goals=["弄清两人气氛"],
                relationships={
                    "lin": CharacterRelationship(target="林渊", trust=0.8)
                },
            ),
            CharacterState(
                name="赵天衡",
                role="stage_antagonist",
                goals=["查清林渊实力提升的原因"],
                relationships={
                    "lin": CharacterRelationship(target="林渊", tension=0.9)
                },
            ),
        ],
    )

    proposals = {
        proposal.name: proposal
        for proposal in RuleBasedCharacterProposalProvider().propose_all(story)
    }

    assert proposals["苏瑶"].target == "林渊"
    assert proposals["王胖子"].target == "林渊"
    assert proposals["赵天衡"].target == "林渊"
    assert proposals["苏瑶"].emotion == "介意"
    assert proposals["王胖子"].action != proposals["苏瑶"].action
    assert proposals["赵天衡"].priority > proposals["王胖子"].priority


def test_character_intent_stage_survives_both_provider_failures() -> None:
    class BrokenRuleProvider:
        def propose_all(self, _story: StoryState) -> list[CharacterProposal]:
            raise RuntimeError("rule fallback unavailable")

    class BrokenCharacterAgent:
        rule_provider = BrokenRuleProvider()

        def propose_all(self, _story: StoryState) -> list[CharacterProposal]:
            raise RuntimeError("llm provider unavailable")

    story = StoryState(
        story_id="s-intent-double-failure",
        outline="本章继续推进。",
        genre="玄幻",
        style="自然中文",
        outline_context={"chapter": {"chapter_number": 1, "cast": ["林渊"]}},
        characters=[CharacterState(name="林渊", role="protagonist")],
    )
    context = DirectorContext(
        chapter_number=1,
        volume={},
        book_outline_summary="",
        nearby_outline=[{"number": 1, "cast": ["林渊"]}],
    )

    assert (
        _character_intents_for_context(
            story,
            context,
            1,
            agent=BrokenCharacterAgent(),  # type: ignore[arg-type]
        )
        == []
    )
