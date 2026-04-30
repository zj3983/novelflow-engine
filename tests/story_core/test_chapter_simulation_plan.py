from packages.story_core.models import CharacterState, StoryState
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
