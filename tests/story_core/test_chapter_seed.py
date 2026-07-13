from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.models import ChapterSummary, StoryState
from packages.story_core.orchestrator import (
    StoryOrchestrator,
    _merge_writing_review_quality,
    _review_chapter_body,
    _scene_card_writing_protocol,
    _sanitize_generated_body,
)


def test_game_chapter_seed_turns_rules_into_generation_contract():
    story = StoryState(
        story_id="s-seed-game",
        outline="网游开服，主角靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        current_chapter=0,
        author_constraints=["禁止单次低级材料交易暴露坐标或现实身份。"],
        world_facts=[
            "信息可见规则：交易行只能暴露价格、数量、批次和时间戳。",
            "NPC硬规则：命名NPC需要地点、服务、利益诉求和信息边界。",
        ],
    )

    seed = build_chapter_seed(story, 1)

    assert seed["schema_version"] == "chapter-seed/v1"
    assert seed["chapter_number"] == 1
    assert "game_webnovel" in seed["genre_plugins"]
    assert any("游戏ID" in beat for beat in seed["chapter_contract"]["required_beats"])
    assert any("职业" in beat for beat in seed["chapter_contract"]["required_beats"])
    assert any("已兑现账本" in beat for beat in seed["chapter_contract"]["required_beats"])
    assert any("坐标" in item for item in seed["chapter_contract"]["forbidden_moves"])
    assert any("库存矛盾" in item for item in seed["chapter_contract"]["forbidden_moves"])
    assert seed["simulation_axes"]["economy"]
    assert seed["simulation_axes"]["npc"]


def test_chapter_seed_preserves_regeneration_fast_path_flags():
    story = StoryState(
        story_id="s-seed-regeneration",
        outline="game_webnovel retry",
        genre="game_webnovel",
        style="fast retry",
        current_chapter=0,
        progression_ledger={
            "simulation_variant": {
                "id": "boundary-inventory-route",
                "skip_style_adapt": True,
                "skip_expansion": True,
            }
        },
    )

    seed = build_chapter_seed(story, 1)

    assert seed["simulation_variant"]["id"] == "boundary-inventory-route"
    assert seed["simulation_variant"]["skip_style_adapt"] is True
    assert seed["simulation_variant"]["skip_expansion"] is True


def test_chapter_seed_carries_recent_continuity_and_ledger():
    story = StoryState(
        story_id="s-seed-continuity",
        outline="夜烬继续推进元素回廊前置。",
        genre="网游",
        style="升级流",
        current_chapter=1,
        progression_ledger={
            "protagonist": {"level": 1, "exp": "30/100", "class_path": "元素法师学徒"},
            "economy": {"currency": "0金币0银币15铜币", "inventory": {"毒腺": 8}},
            "equipment": {"weapon": "粗糙木杖", "durability": "9/10"},
        },
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="夜烬完成首次小额验证。",
                facts=["经济锚点：毒腺挂单价9铜，余额15铜。"],
                unresolved_threads=["交易行商人记录了时间戳。"],
                next_focus="继续验证刷怪路线和交易行弱线索。",
            )
        ],
    )

    seed = build_chapter_seed(story, 2)

    assert seed["continuity"]["latest_summary"] == "夜烬完成首次小额验证。"
    assert "经济锚点：毒腺挂单价9铜，余额15铜。" in seed["continuity"]["must_keep_facts"]
    assert seed["current_state"]["protagonist"]["class_path"] == "元素法师学徒"
    assert any("直接完成元素回廊" in item for item in seed["chapter_contract"]["forbidden_moves"])


def test_game_chapter_two_blocks_level_one_transfer_or_trial_task():
    story = StoryState(
        story_id="s-seed-ch2-level-gate",
        outline="网游开服，夜烬靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        current_chapter=1,
        progression_ledger={
            "protagonist": {"level": 1, "exp": "30/100", "class_path": "元素法师学徒"},
            "economy": {"currency": "0铜", "inventory": {"灰狼毒腺": 33, "粗糙狼皮": 28}},
            "equipment": {"weapon": "新手法杖", "durability": "17/20"},
        },
    )

    seed = build_chapter_seed(story, 2)

    forbidden = "\n".join(seed["chapter_contract"]["forbidden_moves"])
    required = "\n".join(seed["chapter_contract"]["required_beats"])
    assert "Lv.1" in forbidden
    assert "转职任务" in forbidden
    assert "职业试炼" in forbidden
    assert "10级" in forbidden
    assert "新手村任务" in required


def test_game_chapter_two_builds_actionable_writing_contract():
    story = StoryState(
        story_id="s-seed-ch2-writing-contract",
        outline="网游开服，夜烬靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        current_chapter=1,
        progression_ledger={
            "protagonist": {"level": 1, "exp": "30/100", "class_path": "元素法师学徒"},
            "economy": {"currency": "0铜", "inventory": {"灰狼毒腺": 33, "粗糙狼皮": 28}},
            "equipment": {"weapon": "新手法杖", "durability": "17/20"},
        },
    )

    seed = build_chapter_seed(story, 2)
    writing_contract = seed["writing_contract"]

    assert writing_contract["current_level"] == "Lv.1"
    assert any("清道夫" in item for item in writing_contract["allowed_progress"])
    assert any("基础火球术命中记录" in item for item in writing_contract["allowed_progress"])
    assert any("转职任务" in item for item in writing_contract["forbidden_unlocks"])
    assert any("后坡" in scene["goal"] for scene in writing_contract["scene_plan"])
    assert all("职业试炼" not in scene["goal"] for scene in writing_contract["scene_plan"])
    assert len(writing_contract["emotional_arc"]) >= 3
    assert any("现实余额" in beat or "怕亏" in beat for beat in writing_contract["emotional_arc"])
    assert any("收益" in beat or "修好" in beat or "补给" in beat for beat in writing_contract["emotional_arc"])
    loop = writing_contract["satisfaction_loop"]
    assert "可见收益" in loop["visible_payoff"] or "铜币" in loop["visible_payoff"]
    assert "误判" in loop["outsider_misread"] or "运气好" in loop["outsider_misread"]
    assert "下一章" in loop["next_hook"] or "下一轮" in loop["next_hook"]
    craft = writing_contract["genre_craft"]
    assert any("玩家行动" in item for item in craft["method_card"])
    assert any("先写代价" in item and "收获" in item for item in craft["method_card"])
    assert any("试一次" in item for item in craft["action_chain"])
    assert any("本场用得上" in item for item in craft["panel_method"])
    assert "weak" in craft["micro_example"] and "better" in craft["micro_example"]


def test_game_low_level_later_chapter_still_uses_newbie_progression_gate():
    story = StoryState(
        story_id="s-seed-ch6-low-level-gate",
        outline="网游开服，夜烬靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        current_chapter=5,
        progression_ledger={
            "protagonist": {"level": 4, "exp": "210/500", "class_path": "元素法师学徒"},
            "economy": {"currency": "83铜", "inventory": {"灰狼毒腺": 18, "粗糙狼皮": 42}},
            "equipment": {"weapon": "修过的新手法杖", "durability": "13/20"},
        },
    )

    seed = build_chapter_seed(story, 6)
    writing_contract = seed["writing_contract"]

    assert writing_contract["progression_stage"] == "newbie_low"
    assert writing_contract["current_level"] == "Lv.4"
    assert any("新手村" in item for item in writing_contract["allowed_progress"])
    assert any("10级前" in item and "转职任务" in item for item in writing_contract["forbidden_unlocks"])
    assert all("职业试炼" not in scene["goal"] for scene in writing_contract["scene_plan"])


def test_game_level_ten_contract_allows_trial_registration_without_free_completion():
    story = StoryState(
        story_id="s-seed-ch10-trial-ready",
        outline="网游开服，夜烬靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        current_chapter=9,
        progression_ledger={
            "protagonist": {"level": 10, "exp": "0/1600", "class_path": "元素法师学徒"},
            "economy": {"currency": "4银35铜", "inventory": {"灰狼毒腺": 20, "风干狼皮": 12}},
            "equipment": {"weapon": "学徒法杖", "durability": "18/30"},
        },
    )

    seed = build_chapter_seed(story, 10)
    writing_contract = seed["writing_contract"]

    assert writing_contract["progression_stage"] == "trial_ready"
    assert writing_contract["current_level"] == "Lv.10"
    assert any("职业导师" in item or "试炼登记" in item for item in writing_contract["allowed_progress"])
    assert any("直接完成" in item and "元素回廊" in item for item in writing_contract["forbidden_unlocks"])
    assert any("材料" in scene["goal"] or "费用" in scene["goal"] for scene in writing_contract["scene_plan"])
    assert any("失败惩罚" in item for item in writing_contract["genre_craft"]["action_chain"])


def test_orchestrator_prompts_use_chapter_seed_contract():
    story = StoryState(
        story_id="s-seed-prompt",
        outline="网游开服，夜烬靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        current_chapter=0,
        world_facts=["信息可见规则：交易行只暴露价格、数量、批次和时间戳。"],
    )
    orchestrator = StoryOrchestrator()

    plan_prompt = orchestrator._plan_prompt(story, 1)
    body_prompt = orchestrator._body_prompt(story, 1, {"event_plan": {}})

    assert "网游计划写法" in plan_prompt
    assert "本章连续性材料" in plan_prompt
    assert "生成前世界推演契约" not in plan_prompt
    assert "writing_contract" not in plan_prompt
    assert "本章可用材料" in body_prompt
    assert "人物情绪" in body_prompt
    assert "整章四拍" in body_prompt
    assert "chapter-seed/v1" not in body_prompt
    assert "生成前世界推演契约" not in body_prompt
    assert "emotional_arc" not in body_prompt
    assert "genre_craft" not in body_prompt
    assert "网游写法方法卡" in body_prompt
    assert "眼前目标" in body_prompt
    assert "遇到阻力后付出代价" in body_prompt
    assert "情绪放在动作、停顿和回答里" in body_prompt
    assert "隐藏优势只在幕后起作用" in body_prompt


def test_scene_card_writing_protocol_compiles_ordered_prose_contract():
    scene_cards = [
        {
            "scene_id": "s1-character-create",
            "template_id": "character_creation",
            "location": "角色创建界面",
            "purpose": "建立游戏ID、职业选择和第一版角色面板。",
            "conflict": "职业选择必须解释后续路线。",
            "must_show": ["游戏ID", "职业选择", "角色面板", "生命/法力"],
            "must_not_explain": ["world_events", "state_delta", "爽点"],
        },
        {
            "scene_id": "s2-market",
            "template_id": "market_weak_trace",
            "location": "交易行",
            "purpose": "小额匿名寄售。",
            "conflict": "交易只留下弱线索。",
            "must_show": ["价格", "数量", "批次", "手续费", "到账"],
            "must_not_explain": ["coordinate_lock", "real_identity_exposure"],
        },
    ]

    protocol = _scene_card_writing_protocol(scene_cards)

    assert "场景1" in protocol
    assert "character_creation" in protocol
    assert "角色创建界面" in protocol
    assert "必须表面化：游戏ID、职业选择、角色面板、生命/法力" in protocol
    assert "场景2" in protocol
    assert "交易行" in protocol
    assert "禁止写成后台解释：coordinate_lock、real_identity_exposure" in protocol


def test_chapter_body_review_merges_anti_ai_style_review():
    body = (
        "霎时间，夜烬心中一紧，脸色一变。"
        "这一段爽点已经兑现，读者能看懂节奏。"
        "他不由得身形一闪，继续推进下一阶段剧情。"
    )

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行出现弱线索"], "next_focus": "继续低调验证"},
        world_facts=[],
        simulation_plan={},
        world_events=[],
        scene_cards=[],
    )

    assert not review["pass"]
    assert review["scores"]["prose_style_cliche_terms"] < 8
    assert review["scores"]["prose_style_meta_language"] < 8
    assert any("AI高频套话" in issue for issue in review["issues"])


def test_quality_merge_marks_any_writing_review_failure():
    quality = {"ok": True, "issues": []}
    writing_review = {
        "pass": False,
        "scores": {"prose_style_cliche_terms": 5},
        "issues": ["AI高频套话进入正文：此刻。"],
    }

    merged = _merge_writing_review_quality(quality, writing_review)

    assert merged["ok"] is False
    assert "writing_review" in merged["issues"]


def test_quality_merge_exposes_layered_review_sections():
    quality = {"ok": True, "issues": [], "metrics": {"body_chars": 4200}}
    writing_review = {
        "pass": True,
        "scores": {},
        "issues": [],
        "critical_review": {"pass": True, "scores": {"diagnostic_terms": 10}},
        "hook_review": {"pass": False, "scores": {"hook_landed": 5}},
        "pacing_review": {"pass": True, "scores": {"arc_spacing": 8}},
        "beats_review": {"pass": True, "scores": {"required_beats_completion": 9}},
    }

    merged = _merge_writing_review_quality(quality, writing_review)

    assert merged["critical_review"] == writing_review["critical_review"]
    assert merged["hook_review"] == writing_review["hook_review"]
    assert merged["pacing_review"] == writing_review["pacing_review"]
    assert merged["beats_review"] == writing_review["beats_review"]
    assert merged["writing_review"] == writing_review


def test_revision_prompt_contains_hard_fix_checklist_and_scene_protocol():
    story = StoryState(
        story_id="s-revision-prompt",
        outline="网游开服，夜烬低调验证千倍爆率。",
        genre="网游",
        style="直白爽文",
    )
    plan = {
        "scene_cards": [
            {
                "scene_id": "s1-character-create",
                "template_id": "character_creation",
                "location": "角色创建界面",
                "purpose": "建立游戏ID、职业选择和第一版角色面板。",
                "conflict": "职业选择必须解释后续路线。",
                    "must_show": ["游戏ID", "职业选择", "角色面板", "生命/法力", "基础技能"],
                "must_not_explain": ["节奏", "生成", "审稿"],
            }
        ],
        "world_events": [],
    }
    review = {
        "pass": False,
        "issues": [
            "第一章缺少带职业栏的角色面板。",
            "创作层术语进入正文：节奏、生成。",
            "命名NPC出场缺少完整设定。",
            "可见性越界：交易行小额寄售被正文升级成坐标、现实身份、隐藏天赋或刷怪点暴露。",
        ],
        "revision_plan": [
            "补写角色面板。",
            "删除节奏、生成。",
            "补写NPC信息边界。",
            "把交易行信息降回弱线索。",
        ],
    }

    prompt = StoryOrchestrator()._revision_prompt(story, 1, "原正文里有节奏和生成。", plan, review)

    assert "必须改到" in prompt
    assert "## 本章方向" in prompt
    assert "现实压力与登录建号" in prompt
    assert "角色面板" in prompt
    assert "需要删掉的词" in prompt
    assert "节奏" in prompt and "生成" in prompt
    assert "改完后检查" in prompt


def test_chapter_seed_carries_longform_constraints_separately():
    story = StoryState(
        story_id="s-seed-longform",
        outline="网游开服，主角靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        world_facts=[
            "百万字框架：目标约1000000字，章节推演必须服从长期解锁顺序与阶段上限。",
            "长期卷阶梯：1-30 - 灰烬村蛰伏；1-10级、千倍爆率小额验证；只能出现商人盯盘和公会外围弱试探",
            "长期推演规则：每章只允许解锁当前卷范围内的世界层级。",
        ],
    )

    seed = build_chapter_seed(story, 1)

    assert seed["longform_constraints"]
    assert seed["longform_constraints"][0].startswith("百万字框架")
    assert any("当前卷范围" in item for item in seed["longform_constraints"])


def test_review_splits_world_state_patch_plan_from_prose_issues():
    body = (
        "《天启之门》开服后，夜烬把低级狼皮匿名上架交易行。"
        "白袍公会只看了一笔交易，就立刻锁定他的坐标和现实身份。"
        "他又按1金币=100人民币计算收益，确认今天能还房租。"
    ) * 40

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["公会外围开始注意。"]},
        ["没有明确设定前，不得把金币直接换算成人民币。"],
    )

    world_review = review["world_state_review"]
    assert any(item["surface"] == "economy" for item in world_review["issues"])
    assert any(item["surface"] == "information_visibility" for item in world_review["issues"])
    assert any("world_blueprint" in patch for patch in world_review["patch_plan"])


def test_body_prompt_includes_style_coach_and_scene_card_guidance():
    story = StoryState(
        story_id="s-style-coach-prompt",
        outline="网游开服，主角低调验证千倍爆率。",
        genre="网游",
        style="直白爽文",
    )
    plan = {
        "style_guidance": {
            "profile_id": "web_game_leveling_opening",
            "chapter_pattern": "现实压力 -> 游戏入口 -> 异常伏笔 -> 小额验证 -> 交易弱线索",
            "show_rules": ["交易规则通过界面、手续费、到账、批次号表现。"],
            "avoid_rules": ["不要把交易行规则写成说明书。"],
        },
        "scene_cards": [
            {
                "scene_id": "s1-market",
                "template_id": "market_weak_trace",
                "location": "灰烬村交易行",
                "purpose": "完成小额寄售并留下弱线索",
                "conflict": "成交太快会被脚本记录",
                "must_show": ["寄售数量", "手续费", "到账金额"],
                "write_as": ["界面操作", "成交提示音"],
                "avoid": ["解释市场规则"],
                "fact_locks": ["寄售数量", "最终余额"],
            }
        ],
    }

    prompt = StoryOrchestrator()._body_prompt(story, 2, plan)

    assert "表达提醒" in prompt
    assert "写作教练 Style Coach" not in prompt
    assert "web_game_leveling_opening" in prompt
    assert "## 本章方向" in prompt
    assert "灰烬村交易行" in prompt
    assert "界面操作" in prompt
    assert "成交提示音" in prompt
    assert "最终余额" in prompt


def test_revision_prompt_includes_style_coach_and_fact_lock_rule():
    story = StoryState(
        story_id="s-style-coach-revision",
        outline="网游开服，主角低调验证千倍爆率。",
        genre="网游",
        style="直白爽文",
    )
    plan = {
        "style_guidance": {"profile_id": "web_game_leveling_opening"},
        "scene_cards": [
            {
                "scene_id": "s1-create",
                "template_id": "character_creation",
                "location": "角色创建界面",
                "purpose": "建立游戏ID、职业和面板",
                "conflict": "职业选择影响后续路线",
                "must_show": ["游戏ID", "职业", "角色面板"],
                "write_as": ["角色创建界面", "成本权衡"],
                "fact_locks": ["游戏ID", "职业", "等级", "基础属性"],
            }
        ],
    }
    review = {
        "pass": False,
        "issues": ["角色面板缺少属性。"],
        "revision_plan": ["补齐面板，但不要改职业。"],
    }

    prompt = StoryOrchestrator()._revision_prompt(story, 2, "原正文", plan, review)

    assert "表达提醒" in prompt
    assert "写作教练 Style Coach" not in prompt
    assert "web_game_leveling_opening" in prompt
    assert "事实锁硬规则" in prompt
    assert "职业、余额、库存、任务、装备和NPC能知道什么/不知道什么" in prompt
    assert "游戏ID" in prompt
    assert "职业" in prompt
    assert "等级" in prompt


def test_sanitize_generated_body_removes_lone_ascii_question_marks_in_chinese_prose():
    body = "角色创建界面展开。?输入ID。夜烬。?职业列表弹出。保留英文 URL query?a=1。"

    cleaned = _sanitize_generated_body(body)

    assert "。?输入" not in cleaned
    assert "。?职业" not in cleaned
    assert "query?a=1" in cleaned
