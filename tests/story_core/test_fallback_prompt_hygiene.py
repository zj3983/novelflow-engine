from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


def test_body_prompt_does_not_dump_full_plan_or_game_rules_into_non_game_story():
    story = StoryState(
        story_id="s-non-game-fallback",
        outline="都市悬疑，女记者调查一桩旧楼失踪案。",
        genre="都市悬疑",
        style="冷静克制",
    )
    plan = {
        "unused_big_blob": "NOISE" * 2000,
        "event_plan": {"chapter_title": "旧楼门口", "next_focus": "找到保安的矛盾证词"},
        "scene_cards": [{"location": "旧楼门口", "purpose": "逼出第一处证词矛盾", "must_show": ["门禁记录"]}],
        "craft_pack": {"genre_mode": "general", "micro_hooks": {"types": ["物件位置不对"]}},
    }

    prompt = StoryOrchestrator()._body_prompt(story, 1, plan)

    assert "unused_big_blob" not in prompt
    assert "NOISENOISE" not in prompt
    assert "world_events" not in prompt
    assert "scene_cards" not in prompt
    assert "网游插件审稿规则" not in prompt
    assert "交易行" not in prompt
    assert "1金币=100银币=10000铜币" not in prompt
    assert "法师学徒" not in prompt
    assert "千倍爆率" not in prompt
    assert "旧楼门口" in prompt
    assert "## 本章方向" in prompt
    assert "悬疑写法" in prompt
    assert "genre_family" not in prompt
    assert "网游写法方法卡" not in prompt
    assert "## 正文写法" in prompt
    assert "段落写法：长短段交替" in prompt
    assert "玩家势力内部频道" not in prompt
    assert "人物不能全知" in prompt


def test_body_prompt_uses_dynamic_game_class_in_fallback_packet():
    story = StoryState(
        story_id="s-game-fallback",
        outline="网游开服，主角选择潜行路线低调验证异常收益。",
        genre="网游",
        style="升级流",
        progression_ledger={"protagonist": {"game_id": "影灯", "class_path": "盗贼学徒"}},
    )
    plan = {
        "event_plan": {"chapter_title": "夜市入口"},
        "scene_cards": [{"location": "新手村外", "purpose": "验证一次掉落边界"}],
        "craft_pack": {"genre_mode": "game"},
    }

    prompt = StoryOrchestrator()._body_prompt(story, 1, plan)

    assert "盗贼学徒" in prompt
    assert "元素法师学徒" not in prompt
    assert "法师学徒用基础法术" not in prompt


def test_explicit_game_genre_wins_over_generic_marker_in_project_context():
    story = StoryState(
        story_id="s-game-explicit",
        outline="网游开服，主角低调推进任务。",
        genre="网游升级文",
        style="白描",
        world_facts=["题材目录同时保留 generic_webnovel 通用模块。"],
    )

    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "开服"}})

    assert "网游写法方法卡" in prompt
    assert "隐藏优势只在幕后起作用" in prompt


def test_revision_prompt_does_not_inject_game_rules_into_non_game_story():
    story = StoryState(
        story_id="s-non-game-revision",
        outline="现实主义家庭故事，兄妹处理父亲留下的旧账本。",
        genre="现实主义",
        style="朴素",
    )
    plan = {
        "event_plan": {"chapter_title": "旧账本"},
        "scene_cards": [{"location": "厨房", "purpose": "让兄妹第一次谈到债务"}],
    }
    review = {"pass": False, "issues": ["字数偏少"], "revision_plan": ["补动作和对话"]}

    prompt = StoryOrchestrator()._revision_prompt(story, 1, "原正文", plan, review)

    assert "交易拆成多笔" not in prompt
    assert "第一章改稿特别规则" not in prompt
    assert "网游" not in prompt
    assert "千倍爆率" not in prompt
    assert "## 本章方向" in prompt
    assert "scene_cards" not in prompt
    assert "## 正文写法" in prompt
    assert "规则从动作和反馈里露出来" in prompt


def test_plan_prompt_does_not_inject_game_rules_into_non_game_story():
    story = StoryState(
        story_id="s-non-game-plan",
        outline="职场悬疑，编辑接到一项危险任务，要查清失踪作者的职业关系。",
        genre="都市悬疑",
        style="冷静克制",
    )

    prompt = StoryOrchestrator()._plan_prompt(story, 1)

    assert "网游插件审稿规则" not in prompt
    assert "交易行机制" not in prompt
    assert "公会/玩家生态" not in prompt
    assert "游戏ID" not in prompt
    assert "角色面板" not in prompt
    assert "背包容量" not in prompt
    assert "刷怪路线" not in prompt
    assert "铜币" not in prompt


def test_revision_prompt_uses_compact_review_and_packet_target_chars():
    story = StoryState(
        story_id="s-revision-compact",
        outline="都市故事。",
        genre="都市",
        style="朴素",
    )
    plan = {
        "target_chars": {"min": 1800, "max": 2400},
        "event_plan": {"chapter_title": "旧账本"},
    }
    review = {
        "pass": False,
        "issues": ["字数偏少"],
        "revision_plan": ["补足行动过程"],
        "scores": {"webnovel_hook": 5, "background_integration": 8},
        "style_review": {"issues": ["套话偏多"], "revision_plan": ["替换套话"]},
    }

    prompt = StoryOrchestrator()._revision_prompt(story, 1, "原正文", plan, review)

    assert "修订后控制在1800到2400字" in prompt
    assert "不要因为补问题而扩写整章" in prompt
    assert "修改意见" in prompt
    assert "webnovel_hook" not in prompt
    assert "background_integration" not in prompt
    assert "套话偏多" in prompt


def test_revision_prompt_uses_only_consolidated_review_actions():
    story = StoryState(story_id="s-review-compact", outline="查清旧印", genre="xuanhuan", style="白描")
    review = {
        "issues": [
            "对话不够自然。",
            "AI味偏重：报告腔明显。",
            "章末动作不够具体。",
            "剧情推进偏慢。",
            "同一信息重复解释。",
        ],
        "revision_plan": [f"原始修改意见{i}" for i in range(8)],
    }

    prompt = StoryOrchestrator()._revision_prompt(story, 1, "原正文", {}, review)

    assert "## 综合审稿修改" in prompt
    assert "原始修改意见7" not in prompt
    assert prompt.count("问题：") <= 3


def test_revision_prompt_keeps_each_action_with_its_issue_after_reordering():
    story = StoryState(story_id="s-review-pairs", outline="查清旧印", genre="xuanhuan", style="白描")
    review = {
        "issues": ["对话不够自然。", "设定冲突：规划实体写错。"],
        "revision_plan": ["修对白。", "修规划词。"],
    }

    prompt = StoryOrchestrator()._revision_prompt(story, 1, "原正文", {}, review)

    assert "1. 问题：设定冲突：规划实体写错。 修改：修规划词。" in prompt
    assert "2. 问题：对话不够自然。 修改：修对白。" in prompt
    assert "问题：设定冲突：规划实体写错。 修改：修对白。" not in prompt


def test_revision_prompt_prefers_nested_issue_specific_suggestion_over_aggregate_plan():
    story = StoryState(story_id="s-review-specific", outline="查清旧印", genre="xuanhuan", style="白描")
    message = "设定冲突：规划实体写错。"
    review = {
        "issues": [message],
        "revision_plan": ["aggregate-wrong"],
        "reviewer_agent_review": {
            "issues": [{"message": message, "suggestion": "embedded-correct"}],
        },
    }

    prompt = StoryOrchestrator()._revision_prompt(story, 1, "原正文", {}, review)

    assert f"问题：{message} 修改：embedded-correct" in prompt
    assert "aggregate-wrong" not in prompt


def test_revision_prompt_prefers_nested_paired_plan_over_aggregate_paired_plan():
    story = StoryState(story_id="s-review-nested-pair", outline="查清旧印", genre="xuanhuan", style="白描")
    message = "设定冲突：规划实体写错。"
    review = {
        "issues": [message],
        "revision_plan": ["aggregate-wrong"],
        "reviewer_agent_review": {
            "issues": [message],
            "revision_plan": ["nested-paired-correct"],
        },
    }

    prompt = StoryOrchestrator()._revision_prompt(story, 1, "原正文", {}, review)

    assert f"问题：{message} 修改：nested-paired-correct" in prompt
    assert "aggregate-wrong" not in prompt
