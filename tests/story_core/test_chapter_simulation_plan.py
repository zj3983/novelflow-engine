from packages.story_core.models import (
    CharacterPerformanceProfile,
    CharacterState,
    StoryState,
    VoiceSignature,
)
from packages.story_core.orchestrator import StoryOrchestrator
from packages.story_core.simulation import build_chapter_simulation_plan


def test_game_opening_simulation_plan_merges_event_and_performance_constraints():
    story = StoryState(
        story_id="s-sim-plan",
        outline="网游开服，主角获得千倍爆率但必须低调变强。",
        genre="网游",
        style="番茄升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["低调验证千倍爆率"],
            ),
            CharacterState(
                name="仓库管理员铁格",
                role="NPC",
            ),
        ],
    )

    plan = build_chapter_simulation_plan(
        story,
        1,
        event_plan={"turn": "夜烬完成首次小额掉落验证"},
        memory_constraints={},
        chapter_seed={},
    )

    dumped = plan.model_dump()
    required_text = "\n".join(dumped["required_beats"])
    forbidden_text = "\n".join(dumped["forbidden_moves"])
    visibility_text = "\n".join(dumped["information_visibility"])

    assert dumped["chapter_goal"] == "夜烬完成首次小额掉落验证"
    assert dumped["protagonist_strategy"]["game_id"] == "夜烬"
    assert "职业选择" in required_text
    assert "交易行弱钩子" in required_text
    assert "低级材料单次交易" in forbidden_text
    assert "交易行低级材料匿名上架" in visibility_text
    assert dumped["character_performance"][0]["risk_posture"]
    assert dumped["npc_boundaries"][0]["information_limits"]


def test_orchestrator_bundle_contains_simulation_plan():
    story = StoryState(
        story_id="s-sim-bundle",
        outline="网游开服，主角谨慎验证隐藏优势。",
        genre="网游",
        style="升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["完成首次验证"],
            )
        ],
    )

    bundle = StoryOrchestrator().generate_next_chapter(story)

    assert bundle.simulation_plan["chapter_number"] == 1
    assert bundle.simulation_plan["protagonist_strategy"]["game_id"] == "夜烬"
    assert bundle.simulation_plan["character_performance"]
    assert bundle.simulation_plan["review_focus"]
    assert bundle.world_events
    assert bundle.scene_cards
    assert any("visible_to" in event for event in bundle.world_events)
    assert any("must_show" in scene for scene in bundle.scene_cards)


def test_character_voice_signature_flows_into_simulation_plan():
    story = StoryState(
        story_id="s-voice",
        outline="网游开服，主角谨慎登录。",
        genre="网游",
        style="升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                performance_profile=CharacterPerformanceProfile(
                    voice=VoiceSignature(
                        signature_phrases=["先算账", "回报和成本得对得上"],
                        lexicon=["成本", "回报", "拆单"],
                        taboo=["命运", "天选", "热血"],
                        sentence_rhythm="短句为主，少形容词",
                        self_reference="我",
                        subtext_habit="顾左右而言他，不直接表达情绪",
                    ),
                ),
            )
        ],
    )

    plan = build_chapter_simulation_plan(story, 1).model_dump()

    voice = plan["character_performance"][0]["voice"]
    assert "先算账" in voice["signature_phrases"]
    assert "命运" in voice["taboo"]
    assert voice["self_reference"] == "我"
    assert "顾左右而言他" in voice["subtext_habit"]


def test_simulation_plan_carries_longform_constraints():
    story = StoryState(
        story_id="s-sim-longform",
        outline="网游开服，主角靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        world_facts=[
            "百万字框架：目标约1000000字，章节推演必须服从长期解锁顺序与阶段上限。",
            "长期卷阶梯：1-30 - 灰烬村蛰伏；1-10级、千倍爆率小额验证；只能出现商人盯盘和公会外围弱试探",
            "长期推演规则：每章只允许解锁当前卷范围内的世界层级。",
        ],
    )

    plan = build_chapter_simulation_plan(story, 1)
    dumped = plan.model_dump()

    assert dumped["longform_constraints"]
    assert dumped["longform_constraints"][0].startswith("百万字框架")
    assert any("百万字长期框架" in item for item in dumped["review_focus"])


def test_game_opening_plan_requires_wow_hook_and_reality_bridge():
    story = StoryState(
        story_id="s-opening-director-beats",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率，并背着现实催租压力。",
        genre="网游",
        style="番茄升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["验证千倍爆率", "找到游戏收益通向现实债务的路"],
            )
        ],
    )

    plan = build_chapter_simulation_plan(story, 1)
    dumped = plan.model_dump()
    event_plan = dumped["event_plan"]
    required_text = "\n".join(dumped["required_beats"])

    assert "wow_beat" in event_plan
    assert "千倍爆率" in event_plan["wow_beat"]
    assert "2-8倍" in event_plan["wow_beat"]
    assert "explicit_chapter_end_hook" in event_plan
    assert "下一章" in event_plan["explicit_chapter_end_hook"]
    assert "reality_game_bridge" in event_plan
    assert "现实" in event_plan["reality_game_bridge"]
    assert "混沌之种" in event_plan["core_mystery_reinforcement"]
    assert "wow_beat" in required_text
    assert "explicit_chapter_end_hook" in required_text
    assert "reality_game_bridge" in required_text


def test_game_simulation_plan_carries_author_craft_and_director_card():
    story = StoryState(
        story_id="s-web-game-craft",
        outline="网游开服，苏叶以夜烬身份先确认灰狼坡掉落边界。",
        genre="网游",
        style="番茄升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )

    plan = build_chapter_simulation_plan(
        story,
        1,
        event_plan={"turn": "夜烬先确认边界，不急着赚钱"},
    ).model_dump()

    craft_text = "\n".join(plan["web_game_author_craft"]["craft_laws"])
    director = plan["web_game_director_card"]

    assert "规则靠操作显形" in craft_text
    assert director["boundary_focus"] is True
    assert "寄售" in director["boundary_chapter_bans"]
    assert any("NPC" in item for item in director["reaction_ladder"])
