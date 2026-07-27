from packages.story_core.writing_taskbook import (
    build_writing_taskbook,
    ensure_writing_taskbook,
    format_taskbook_prompt_section,
    taskbook_segment_specs,
)


def test_taskbook_has_no_style_contract_when_style_is_unselected():
    taskbook = build_writing_taskbook(chapter_number=2, genre="都市", style="", plan={})

    assert taskbook["style_contract"] == []
    assert "通用白描" not in str(taskbook)


def test_taskbook_uses_one_selected_style_prompt():
    taskbook = build_writing_taskbook(chapter_number=2, genre="都市", style="幽默", plan={})

    assert taskbook["style_contract"] == [
        "幽默：让笑点来自人物反应、处境反差和顺口接话，不刻意抖包袱。"
    ]


def test_trade_authorized_first_chapter_taskbook_uses_market_then_exchange():
    taskbook = build_writing_taskbook(
        chapter_number=1,
        genre="网游",
        plan={
            "governance": {"chapter_intent": {"first_chapter_trade_authorized": True}},
            "event_plan": {"turn": "第一章卖出裂纹狼心，再走官方兑换渠道并付清急账。"},
        },
    )

    rendered = str(taskbook)
    assert "天启之门" not in rendered
    assert "第一章只完成登录、低级验证和领先预期" not in rendered
    assert "已冻结游戏币的现有求购单" in rendered
    assert "独立官方兑换页面" in rendered
    assert "现实账户到账后处理急账" in rendered
    assert "担保交易" not in rendered


def test_first_chapter_taskbook_keeps_only_three_useful_scenes():
    taskbook = build_writing_taskbook(
        chapter_number=1,
        plan={
            "target_chars": {"min": 3200, "max": 4200},
            "event_plan": {"chapter_title": "两只灰狼，掉了五份毒腺"},
            "scene_cards": [
                {"template_id": "single_npc_service", "location": "药剂铺", "must_show": ["洛婶报价"]},
            ],
        },
        genre="网游",
        style="白话爽文",
    )

    scenes = taskbook["scenes"]
    assert [scene["key"] for scene in scenes] == ["entry_login", "small_verification", "decision_hook"]
    assert "NPC" not in scenes[2]["goal"]
    assert "不要展开力量/敏捷/体质/智力" in scenes[0]["required_surface"]
    assert "底层协议校验通过" in scenes[1]["required_surface"]
    assert "至少兑现一项" in scenes[2]["required_surface"]
    assert "交易、论坛、公会追查后移" in " ".join(taskbook["global_required"])
    assert "材料公开处理成大钱" in taskbook["global_forbidden"]
    assert "公开扣费或大额收款反馈" in taskbook["global_forbidden"]
    templates = "\n".join(taskbook["craft_templates"])
    assert "选择场面" in templates
    assert "对话场面" in templates
    assert "战斗场面" in templates
    assert "怪物面板" in templates
    assert "名称、等级、生命和攻击方式" in templates
    assert "同类普通怪" in templates
    assert "精英怪和首领" in templates
    assert "爽点场面" in templates
    assert "夜烬不能只说两个字装高手" in templates
    assert "不要只写火球命中、怪倒地、掉落入包" in templates


def test_first_chapter_taskbook_uses_project_balance_and_requires_plausible_network_access():
    taskbook = build_writing_taskbook(
        chapter_number=1,
        plan={"outline_anchor": {"opening_balance": "43.18元"}},
        genre="网游",
    )

    entry = taskbook["scenes"][0]
    assert "43.18元" in entry["required_surface"]
    assert "27.60" not in entry["required_surface"]
    assert "有效联网方式" in entry["forbidden_surface"]


def test_first_chapter_allocate_requires_visible_choice_without_full_attribute_panel() -> None:
    taskbook = build_writing_taskbook(
        chapter_number=1,
        genre="网游",
        plan={
            "event_plan": {
                "attribute_allocation_decision": {
                    "mode": "allocate",
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            }
        },
    )

    required = "\n".join(scene["required_surface"] for scene in taskbook["scenes"])

    assert "新增5点" in required
    assert "智力" in required and "剩余0点" in required
    assert "力量/敏捷/体质/智力等扩展属性" not in required


def test_first_chapter_without_attribute_decision_keeps_initial_panel_short() -> None:
    taskbook = build_writing_taskbook(chapter_number=1, genre="网游", plan={})

    assert "Lv.1短面板" in taskbook["scenes"][0]["required_surface"]
    assert "力量/敏捷/体质/智力等扩展属性" in taskbook["scenes"][0]["required_surface"]


def test_taskbook_carry_requires_visible_reason() -> None:
    taskbook = build_writing_taskbook(
        chapter_number=2,
        genre="网游",
        plan={"event_plan": {"attribute_allocation_decision": {"mode": "carry", "remaining": 5, "reason": "留给转职"}}},
    )

    assert "保留原因" in "\n".join(taskbook["global_required"])


def test_taskbook_allocate_uses_only_the_protagonist_level_scene() -> None:
    taskbook = build_writing_taskbook(
        chapter_number=2,
        genre="网游",
        plan={
            "event_plan": {
                "attribute_allocation_decision": {
                    "mode": "allocate",
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            },
            "scene_cards": [
                {
                    "id": "protagonist-level",
                    "location": "灰狼坡",
                    "purpose": "夜烬升级",
                    "state_delta": {"protagonist": {"level": "Lv.2"}},
                },
                {
                    "id": "monster-level",
                    "location": "灰狼坡",
                    "purpose": "击败灰狼",
                    "state_delta": {"monster": {"level": "Lv.60"}},
                },
            ],
        },
    )

    scenes = {scene["key"]: scene["required_surface"] for scene in taskbook["scenes"]}

    assert "新增5点" not in scenes["monster-level"]
    assert "新增5点" in scenes["protagonist-level"]


def test_taskbook_does_not_attach_later_chapter_decision_without_upgrade_scene() -> None:
    taskbook = build_writing_taskbook(
        chapter_number=2,
        genre="网游",
        plan={
            "event_plan": {
                "attribute_allocation_decision": {
                    "mode": "allocate",
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            },
            "scene_cards": [
                {"id": "search", "location": "仓库", "purpose": "核对清单"},
                {"id": "hook", "location": "巷口", "purpose": "躲开盯梢"},
            ],
        },
    )

    assert all("新增5点" not in scene["required_surface"] for scene in taskbook["scenes"])
    assert any("人物实际处理属性点的场景落地" in item for item in taskbook["global_required"])
    assert not any("发生升级的场景落地" in item for item in taskbook["global_required"])


def test_taskbook_carry_without_upgrade_uses_attribute_handling_scene_wording() -> None:
    taskbook = build_writing_taskbook(
        chapter_number=2,
        genre="网游",
        plan={
            "event_plan": {
                "turn": "打开面板处理已有属性点",
                "attribute_allocation_decision": {"mode": "carry", "remaining": 5, "reason": "留给转职"},
            },
            "scene_cards": [{"id": "rest", "location": "营地", "purpose": "整理背包"}],
        },
    )

    assert any("人物实际处理属性点的场景落地" in item for item in taskbook["global_required"])
    assert not any("发生升级的场景落地" in item for item in taskbook["global_required"])


def test_taskbook_compiles_scene_cards_for_later_chapters():
    plan = {
        "target_chars": 3600,
        "scene_cards": [
            {
                "template_id": "npc-counter",
                "location": "药剂铺",
                "purpose": "让洛婶只给药材报价",
                "conflict": "她不回答公会消息",
                "must_show": ["库存", "报价"],
                "avoid": ["公会内部频道"],
                "ending_pressure": "苏叶必须决定卖不卖",
            }
        ],
    }

    specs = taskbook_segment_specs(2, plan)

    assert len(specs) == 1
    assert specs[0]["key"] == "npc-counter"
    assert "药剂铺" in specs[0]["title"]
    assert "库存" in specs[0]["required_surface"]
    assert "公会内部频道" in specs[0]["forbidden_surface"]
    assert "苏叶必须决定卖不卖" in specs[0]["exit_state"]


def test_taskbook_prompt_section_is_writer_facing_not_json_dump():
    taskbook = ensure_writing_taskbook(
        1,
        {
            "unused_big_blob": "NOISE" * 500,
            "event_plan": {"chapter_title": "两只灰狼"},
            "scene_cards": [{"template_id": "single_npc_service", "must_show": ["洛婶报价"]}],
        },
        genre="网游",
        style="白话爽文",
    )

    section = format_taskbook_prompt_section(taskbook, segment_key="small_verification")

    assert "## 本章写法材料" in section
    assert "下面是给作者的场面材料" in section
    assert "低级怪小验证" in section
    assert "场面参考" in section
    assert "别人问、催或提醒" in section
    assert "不要只写火球命中、怪倒地、掉落入包" in section
    assert "写作任务书" not in section
    assert "必写：" not in section
    assert "禁写：" not in section
    assert "NOISENOISE" not in section
    assert "unused_big_blob" not in section
    assert "scene_cards" not in section


def test_taskbook_turns_plot_simulation_into_narrative_spine():
    taskbook = build_writing_taskbook(
        chapter_number=2,
        plan={
            "target_chars": 3600,
            "simulation_plan": {
                "chapter_goal": "完成清道夫委托",
                "plot_simulation": {
                    "reader_hook": "读者要看到夜烬暗中把优势滚起来。",
                    "chapter_desire": "夜烬想补齐清道夫委托还差的两份毒腺。",
                    "obstacle_chain": ["蓝量不够", "法杖耐久快见底", "旁边玩家会误判他的路线"],
                    "choice_point": "他要决定先交任务，还是先把来源藏住。",
                    "payoff": "清道夫委托进度必须有明确变化。",
                    "cost": "至少付出蓝量、耐久或铜币中的一项。",
                    "emotional_turn": "从缺资源的紧绷转成小领先后的警惕。",
                    "outsider_misread": "外人只能以为他运气好。",
                    "ending_hook": "章末落到后坡巡查前置任务。",
                },
            },
        },
        genre="网游",
        style="白描",
    )

    required = "\n".join(taskbook["global_required"])
    scenes = "\n".join(scene["goal"] + "\n" + scene["required_surface"] + "\n" + scene["exit_state"] for scene in taskbook["scenes"])

    assert "剧情主线：读者要看到夜烬暗中把优势滚起来。" in required
    assert "主角目标：夜烬想补齐清道夫委托还差的两份毒腺。" in required
    assert "阻碍：蓝量不够；法杖耐久快见底；旁边玩家会误判他的路线" in required
    assert "夜烬想补齐清道夫委托还差的两份毒腺" in scenes
    assert "清道夫委托进度必须有明确变化" in scenes
    assert "章末落到后坡巡查前置任务" in scenes


def test_taskbook_includes_longform_plot_contract():
    taskbook = build_writing_taskbook(
        chapter_number=4,
        plan={
            "simulation_plan": {
                "chapter_goal": "把清道夫奖励换成下一轮升级准备",
                "longform_plot_contract": {
                    "arc_window": {
                        "name": "新手村滚雪球",
                        "purpose": "把掉落优势换成等级、技能、装备和任务优势。",
                        "upper_bound": "不能直接揭开千倍爆率。",
                    },
                    "payoff_requirement": "每章至少让一项账本向前滚。",
                    "anti_drag_rule": "不要把耐久、蓝量、排队写成整章主线。",
                    "future_use_rule": "新增道具、人物、任务和线索都要说明能怎样继续推动后续。",
                    "reader_reason_to_continue": "章末必须留下下一章立刻能执行的动作。",
                    "snowball_logic": ["苟不是不拿好处，而是拆开拿、换壳拿。"],
                    "webgame_satisfaction": ["爽感落在暗中领先。"],
                },
            },
        },
        genre="网游",
        style="白描",
    )

    required = "\n".join(taskbook["global_required"])

    assert "长篇阶段：新手村滚雪球" in required
    assert "本章兑现：每章至少让一项账本向前滚。" in required
    assert "不能拖：不要把耐久、蓝量、排队写成整章主线。" in required
    assert "新增内容要有后续用途" in required
    assert "滚雪球：苟不是不拿好处" in required


def test_taskbook_prompt_uses_plot_words_not_backend_key():
    taskbook = ensure_writing_taskbook(
        2,
        {
            "simulation_plan": {
                "chapter_goal": "完成清道夫委托",
                "plot_simulation": {
                    "reader_hook": "读者要看到具体领先。",
                    "chapter_desire": "夜烬想补齐材料。",
                    "payoff": "任务进度变化。",
                    "ending_hook": "后坡巡查前置任务露出。",
                },
            }
        },
        genre="网游",
        style="白描",
    )

    section = format_taskbook_prompt_section(taskbook)

    assert "剧情主线" in section
    assert "读者要看到具体领先" in section
    assert "plot_simulation" not in section
    assert "全章必守" not in section
    assert "全章禁区" not in section
