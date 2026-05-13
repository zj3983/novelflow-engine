from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator
from packages.story_core.segmented_writing import build_segment_prompt, build_segment_specs


def test_segment_prompt_puts_scene_method_before_guardrails():
    spec = build_segment_specs(1, {})[0]
    prompt = build_segment_prompt(chapter_number=1, spec=spec, plan={})

    assert "OUTPUT CONTRACT: prose only" in prompt
    assert "写手身份：你只负责把本段写成可读正文" in prompt
    assert "番茄白话风" in prompt
    assert "不要在正文或标题里写后台硬词" in prompt
    assert "不要把目标写成后台硬词" in prompt
    assert "情绪暗线" in prompt
    assert "写法施工单" in prompt
    assert "进入压力 -> 尝试动作 -> 即时反馈 -> 选择代价 -> 余波/小钩子" in prompt
    assert "抽象判断必须落到具体物件或动作" in prompt
    assert prompt.index("写法施工单") < prompt.index("硬性质量闸门")


def test_segment_prompt_uses_web_game_director_card_not_full_plan_dump():
    spec = build_segment_specs(1, {})[0]
    plan = {
        "event_plan": {"chapter_title": "灰狼坡验边界", "ordered_actions": ["登录", "刷怪"]},
        "simulation_plan": {
            "chapter_goal": "确认边界",
            "web_game_director_card": {
                "read_feel": "主角撞到游戏世界的边界",
                "scene_formula": "现实压力 -> 试探动作 -> 即时反馈 -> 资源代价 -> 半个答案 -> 更大问题",
                "one_line": "第一章不是赚钱，是确认边界。",
                "reaction_ladder": ["NPC：只按岗位规则回应。"],
                "write_rules": ["规则只能通过动作、面板变化、NPC岗位回答出现。"],
                "boundary_chapter_bans": ["寄售", "成交", "到账"],
            },
        },
        "debug_noise": {"huge": ["不要进入提示词"] * 50},
    }

    prompt = build_segment_prompt(chapter_number=1, spec=spec, plan=plan)

    assert "网游导演卡" in prompt
    assert "第一章不是赚钱，是试清楚能不能走" in prompt
    assert "灰狼坡验边界" not in prompt
    assert "确认边界" not in prompt
    assert "本章推演计划" not in prompt
    assert "debug_noise" not in prompt
    assert "不要进入提示词" not in prompt


def test_segment_prompt_promotes_variant_fact_locks():
    spec = build_segment_specs(1, {})[2]
    plan = {
        "event_plan": {"chapter_title": "灰狼坡验边界"},
        "simulation_plan": {
            "simulation_variant": "boundary-inventory-route",
            "chapter_goal": "确认背包容量边界",
            "web_game_director_card": {
                "read_feel": "主角撞到游戏世界的边界",
                "fact_locks": [
                    "本章首次验证对象固定为灰狼，地点固定为灰狼坡；不得写成灰鼠、灰鼠坡、鼠皮或灰鼠毒囊。",
                    "本章服务NPC固定为仓库管理员铁栓；他只懂仓储格、寄存门槛和背包占用。",
                ],
            },
        },
    }

    prompt = build_segment_prompt(chapter_number=1, spec=spec, plan=plan)

    assert "变体事实锁" in prompt
    assert "固定为灰狼" in prompt
    assert "不得写成灰鼠" in prompt
    assert "仓库管理员铁栓" in prompt


def test_fallback_body_prompt_uses_same_scene_method():
    story = StoryState(story_id="s-method", outline="都市悬疑", genre="悬疑", style="克制")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "旧楼"}})

    assert "OUTPUT CONTRACT: prose only" in prompt
    assert "写手身份：你只负责把本章写成可读正文" in prompt
    assert "情绪暗线" in prompt
    assert "写法施工单" in prompt
    assert "本章按“进入压力 -> 尝试动作 -> 即时反馈 -> 选择代价 -> 余波/小钩子”推进" in prompt
    assert prompt.index("写法施工单") < prompt.index("硬性质量闸门")


def test_fallback_body_prompt_includes_web_game_director_card():
    story = StoryState(story_id="s-game-method", outline="网游开服确认边界", genre="网游", style="番茄升级流")
    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {
            "event_plan": {"chapter_title": "灰狼坡验边界"},
            "simulation_plan": {
                "web_game_director_card": {
                    "read_feel": "主角撞到游戏世界的边界",
                    "scene_formula": "现实压力 -> 试探动作 -> 即时反馈 -> 资源代价 -> 半个答案 -> 更大问题",
                    "one_line": "确认边界，不急着赚钱。",
                    "reaction_ladder": ["玩家：只看见散人试错。"],
                    "write_rules": ["规则只能通过动作、面板变化、NPC岗位回答出现。"],
                    "boundary_chapter_bans": ["寄售", "成交", "到账"],
                }
            },
        },
    )

    assert "网游导演卡" in prompt
    assert "试清楚能不能走，不急着赚钱" in prompt
    assert "第一章别写：把材料换成钱、市场玩家盯上主角、公共频道或玩家势力追过来" in prompt
    assert "寄售、成交、到账" not in prompt
    assert "边界章禁写" not in prompt


def test_web_game_first_chapter_whole_body_prompt_has_plain_four_beat_contract():
    story = StoryState(story_id="s-whole-ch1", outline="网游开服，千倍爆率。", genre="网游", style="番茄升级流")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "灰狼坡"}})

    assert "整章四拍" in prompt
    assert "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子" in prompt
    assert "本次不用分段生成" in prompt
    assert "白描" in prompt
    assert "自然对话" in prompt
    assert "不要用华丽词语、夸张比喻或谜语式暗示" in prompt
    assert "台词不能替作者讲规则" in prompt
    assert prompt.index("整章四拍") < prompt.index("硬性质量闸门")


def test_revision_prompt_keeps_method_and_separates_viewpoint_rule():
    story = StoryState(story_id="s-revision-method", outline="都市悬疑", genre="悬疑", style="克制")
    prompt = StoryOrchestrator()._revision_prompt(
        story,
        1,
        "原正文",
        {"event_plan": {"chapter_title": "旧楼"}},
        {"pass": False, "issues": ["视角越界"], "revision_plan": ["改回主角限知"]},
    )

    assert "OUTPUT CONTRACT: prose only" in prompt
    assert "写手身份：你只负责把本章写成可读正文" in prompt
    assert "写法施工单" in prompt
    assert "一、视角：保持主角限知第三人称" in prompt
    assert "审核术语、规则术语、推演词不得入正文" in prompt
    assert "上帝视角。审核术语" not in prompt


