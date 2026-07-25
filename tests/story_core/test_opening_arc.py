from apps.api.storage import _project_world_facts, _sync_project_character_profiles
from packages.story_core.models import CharacterState, NovelProject, StoryState
from packages.story_core.orchestrator import _normalize_event_plan, _review_chapter_body, _story_snapshot
from packages.story_core.world_enrichment import _merge_enrichment


def test_world_enrichment_adds_game_golden_three_chapters():
    project = NovelProject(
        project_id="p-opening-game",
        title="苟在网游里成神",
        seed_outline="网游开服，主角靠千倍爆率低调发育，交易行变现，被公会注意。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    opening_arc = enriched.world_blueprint["opening_arc"]["golden_three_chapters"]

    assert "chapter_1" in opening_arc
    assert any("交易行" in item for item in opening_arc["chapter_1"]["must_include"])
    assert any("公会" in item for item in opening_arc["chapter_1"]["must_include"])
    assert any("职业/工作状态" in item for item in opening_arc["chapter_1"]["must_include"])
    assert any("触发条件" in item for item in opening_arc["chapter_1"]["must_include"])
    assert any("现实压力" in item for item in opening_arc["chapter_1"]["conflict_modes"])
    assert any("精准锁定" in item for item in opening_arc["chapter_1"]["forbidden_conflicts"])
    assert any("资源路线" in item for item in opening_arc["chapter_2"]["conflict_modes"])
    assert any("职业门槛" in item for item in opening_arc["chapter_3"]["conflict_modes"])
    assert any("外包测试" in item for item in opening_arc["chapter_1"]["exposition_beats"])
    assert any("底层日志" in item for item in opening_arc["chapter_1"]["exposition_beats"])
    assert opening_arc["chapter_1"]["exposition_beats"]
    assert any("现实入口" in item for item in opening_arc["chapter_1"]["background_budget"]["required_layers"])
    assert any("多个命名NPC" in item for item in opening_arc["chapter_1"]["background_budget"]["forbidden_layers"])


def test_project_world_facts_prioritize_opening_arc():
    project = NovelProject(
        project_id="p-opening-facts",
        title="Opening Facts",
        world_blueprint={
            "opening_arc": {
                "golden_three_chapters": {
                    "chapter_1": {
                        "purpose": "立世界、立主角、立金手指。",
                        "conflict_modes": ["现实压力与规则验证。"],
                        "forbidden_conflicts": ["禁止第一章精准锁定。"],
                        "exposition_beats": ["通过登录界面交代游戏背景。"],
                        "ending_hook": "交易行捕捉异常。",
                    }
                }
            }
        },
    )

    facts = _project_world_facts(project)

    assert facts[0] == "黄金三章第1章职责：立世界、立主角、立金手指。"
    assert "第1章冲突模式：现实压力与规则验证。" in facts
    assert "第1章禁止冲突：禁止第一章精准锁定。" in facts
    assert "第1章背景节拍：通过登录界面交代游戏背景。" in facts
    assert "第1章章末钩子：交易行捕捉异常。" in facts


def test_project_world_facts_include_background_budget_and_visibility():
    project = NovelProject(
        project_id="p-background-budget",
        title="苟在网游里成神",
        seed_outline="网游开服，主角靠千倍爆率低调发育。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    facts = _project_world_facts(enriched)

    assert any("第1章背景预算" in fact and "现实入口" in fact for fact in facts)
    assert any("玩家生态" in fact and "搬砖党" in fact for fact in facts)
    assert any("信息可见规则" in fact and "交易行" in fact for fact in facts)


def test_game_world_facts_include_currency_guardrails():
    project = NovelProject(
        project_id="p-currency-facts",
        title="Currency Facts",
        seed_outline="网游开服，主角靠千倍爆率卖材料。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    facts = _project_world_facts(enriched)

    assert any("1金币=100银币=10000铜币" in fact for fact in facts)
    assert any("不得写死游戏币与现实货币的兑换比例" in fact for fact in facts)


def test_event_plan_carries_exposition_beats_into_snapshot_flow():
    story = StoryState(
        story_id="s-opening",
        outline="网游开服，主角低调发育。",
        genre="网游",
        style="升级流",
        world_facts=["黄金三章第1章职责：立世界、立主角、立金手指。"],
    )

    snapshot = _story_snapshot(story)
    event_plan = _normalize_event_plan(
        {
            "exposition_beats": ["通过论坛热帖交代公会生态。"],
            "world_reactions": ["交易行商人记录异常账号。"],
        },
        1,
        story,
    )

    assert snapshot["world_facts"] == ["黄金三章第1章职责：立世界、立主角、立金手指。"]
    assert event_plan["exposition_beats"] == ["通过论坛热帖交代公会生态。"]


def test_review_rejects_low_tier_market_trade_as_precise_tracking():
    body = (
        "苏叶把狼皮拆成二十笔匿名挂进交易行，低级材料价格立刻波动。"
        "白袍公会马上锁定坐标，确认他的真人身份。"
        "《天启之门》全沉浸开服，出租屋账单压在桌上，苏叶是失业外包测试员。"
        "混沌之种在旧头盔神经接驳协议异常后出现，千倍爆率首次验证。"
        "交易行显示匿名寄售、手续费、流水、风控异常；白袍、赤焰、星河和散人都在频道争论。"
    )

    review = _review_chapter_body(
        1,
        body,
        {
            "world_reactions": ["商人记录时间戳。"],
            "next_focus": "继续低调变现。",
        },
        ["低级材料匿名上架只暴露价格、数量和时间戳等弱线索。"],
    )

    assert not review["pass"]
    assert any("追踪强度" in issue for issue in review["issues"])


def test_opening_review_rejects_overleveled_game_conflict():
    body = (
        "《天启之门》全沉浸开服，出租屋账单压在桌上，苏叶是失业外包测试员。"
        "旧头盔神经接驳时出现协议异常，角色创建界面闪过底层日志，他激活隐藏天赋混沌之种，确认千倍爆率生效。"
        "他通过交易行匿名寄售狼皮，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
        "白袍公会会长却突然带人围杀苏叶，双方正面撞上，争夺世界BOSS和核心资源。"
    ) * 20

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert review["pass"] is False
    assert any("冲突越级" in issue for issue in review["issues"])


def test_opening_review_rejects_missing_real_job_or_skill_source():
    body = (
        "《天启之门》全沉浸VRMMO开服当晚，苏叶在出租屋里看着房租账单和医疗欠费登录游戏。"
        "旧头盔神经接驳时出现协议异常，角色创建界面闪过灰色日志，他激活隐藏天赋混沌之种，确认千倍爆率生效。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
    ) * 25

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "公会试探。"},
    )

    assert review["pass"] is False
    assert any("现实职业" in issue for issue in review["issues"])


def test_opening_review_rejects_unforeshadowed_goldfinger():
    body = (
        "《天启之门》全沉浸VRMMO开服当晚，苏叶在出租屋里看着房租账单和医疗欠费登录游戏。"
        "他是失业外包测试员，过去做过网游交易数据校验，所以习惯先算手续费和风控成本。"
        "他第一次击杀灰狼后看见掉落判定×1000，混沌之种未解析，获得灰狼毒腺×8，千倍爆率让任务进度一下补到清道夫前置任务只差两份。"
        "职业导师艾伦在木屋门口登记法师学徒，提醒元素回廊试炼需要先交十份毒腺。"
        "他没有急着处理材料，只把灰狼毒腺压在背包里，记下前置任务、背包变化和法杖耐久。"
        "灰烬村公告栏上写着新手外坡怪物密度偏高，普通玩家还在排队接任务，只当他运气好。"
        "他关掉背包，下一步准备再刷一轮，先摸清后坡入口。"
    ) * 25

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["NPC只记录任务登记。"], "next_focus": "继续摸后坡入口。"},
    )

    assert review["pass"] is False
    assert any("金手指出现缺少触发条件" in issue for issue in review["issues"])


def test_project_character_profiles_enrich_runtime_characters():
    project = NovelProject(
        project_id="p-character-depth",
        title="Character Depth",
        character_profiles=[
            {
                "name": "苏叶",
                "role": "主角",
                "motivation": "缺钱但必须隐藏千倍爆率。",
                "personality": "谨慎、计算、极度厌恶失控。",
                "speech_style": "先报数字再说结论，话要完整。",
                "goals": ["安全升至10级", "建立隐蔽变现渠道"],
                "secrets": ["千倍爆率"],
                "conflict_hooks": ["被公会识破"],
            }
        ],
        relationship_graph=[
            {"source": "苏叶", "target": "赵胖子", "bond": "供货与试探", "trust": 0.4, "tension": 0.5}
        ],
    )
    story = StoryState(
        story_id="s-character-depth",
        outline="网游开服，主角低调发育。",
        genre="网游",
        style="升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="protagonist",
                goals=["在赵胖子缓过来之前抢先控制苏叶与赵胖子正面撞上，争的就是核心资源的控制权。"],
                memory=['第1章把苏叶直接推入了围绕"苏叶与赵胖子正面撞上"展开的正面冲突。'],
            )
        ],
    )

    _sync_project_character_profiles(story, project)
    snapshot = _story_snapshot(story)

    character = story.characters[0]
    assert character.role == "主角"
    assert character.goals[:2] == ["安全升至10级", "建立隐蔽变现渠道"]
    assert "千倍爆率" in character.secrets
    assert any("说话方式" in item for item in character.memory)
    assert "赵胖子" in character.relationships
    assert snapshot["characters"][0]["secrets"] == ["千倍爆率"]
    assert snapshot["characters"][0]["relationships"][0]["bond"] == "供货与试探"


def test_opening_review_requires_background_and_motivation():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "角色创建界面确认游戏ID：夜烬。"
        "职业选择栏弹出后，他选择元素法师学徒。"
        "【角色面板】游戏ID：夜烬；等级：1；职业：元素法师学徒；经验：0/100；主武器：新手法杖。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他第一次击杀灰狼后看见掉落判定×1000，混沌之种未解析，获得灰狼毒腺×8，千倍爆率让任务进度一下补到清道夫前置任务只差两份。"
        "职业导师艾伦在木屋门口登记法师学徒，提醒元素回廊试炼需要先交十份毒腺。"
        "他没有急着处理材料，只把灰狼毒腺压在背包里，记下前置任务、背包变化和法杖耐久。"
        "灰烬村公告栏上写着新手外坡怪物密度偏高，普通玩家还在排队接任务，只当他运气好。"
        "他关掉背包，下一步准备再刷一轮，先摸清后坡入口。"
    ) * 45

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["NPC只记录任务登记。"], "next_focus": "继续摸后坡入口。"},
    )

    assert review["pass"] is False
    assert review["scores"]["background_integration"] >= 8
    assert review["scores"]["protagonist_motivation"] >= 8
    assert review["scores"]["reader_feel_patchwork"] <= 5


def test_opening_review_rejects_invented_real_money_exchange_rate():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他激活隐藏天赋混沌之种，确认千倍爆率生效。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
        "玩家频道有人断言，1金币=500人民币，这让所有人都疯狂起来。"
    ) * 25

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "公会试探。"},
        ["经济规则：开服初期兑换价尚未稳定，除非世界档案明确给出官方兑换规则，否则不得写死游戏币与现实货币的兑换比例。"],
    )

    assert review["pass"] is False
    assert any("汇率" in issue for issue in review["issues"])


def test_opening_review_rejects_wrong_coin_conversion():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他激活隐藏天赋混沌之种，确认千倍爆率生效。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
        "【确认上架？扣除5%手续费后，预计到账：8550铜币（8金55银）。】"
    ) * 25

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "公会试探。"},
        ["经济规则：网游币制默认使用 1金币=100银币=10000铜币。"],
    )

    assert review["pass"] is False
    assert any("币制换算错误" in issue for issue in review["issues"])


def test_opening_review_rejects_fractional_copper_and_limit_breaks():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他激活隐藏天赋混沌之种，确认千倍爆率生效。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
        "【寄售规则：匿名上架（手续费5%），单笔限额50。】"
        "【系统提示：您已上架“腐皮×80”，单价9.5铜币。】"
    ) * 25

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "公会试探。"},
        ["经济规则：网游币制默认使用 1金币=100银币=10000铜币。"],
    )

    assert review["pass"] is False
    assert any("游戏币显示不应出现小数" in issue for issue in review["issues"])
    assert any("单笔限额" in issue for issue in review["issues"])


def test_opening_review_rejects_drop_multiplier_mismatch():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "【天赋：千倍爆率】"
        "【效果：击杀怪物时，基础掉落物数量×1000。】"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
        "【触发天赋“千倍爆率”。获得：腐皮野猪皮×100。】"
    ) * 25

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "公会试探。"},
    )

    assert review["pass"] is False
    assert any("首次掉落只写×100" in issue for issue in review["issues"])
