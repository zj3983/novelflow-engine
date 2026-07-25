from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import (
    StoryOrchestrator,
    _character_context_for_prompt,
    _compact_writer_plan_for_prompt,
    _web_game_writing_method_lines,
    _writer_character_section,
)
from packages.story_core.segmented_writing import build_segment_prompt, build_segment_specs


def test_body_prompt_has_no_unselected_plain_style_fallback():
    story = StoryState(story_id="s-no-style", outline="公司发生一场争执。", genre="都市", style="")

    prompt = StoryOrchestrator()._body_prompt(story, 2, {"event_plan": {"chapter_title": "争执"}})

    assert "通用白描" not in prompt
    assert "整体用白描" not in prompt
    assert "番茄白话风" not in prompt
    assert "表达风格：" not in prompt


def test_body_prompt_injects_selected_style_once():
    story = StoryState(story_id="s-humor", outline="公司发生一场争执。", genre="都市", style="幽默")

    prompt = StoryOrchestrator()._body_prompt(story, 2, {"event_plan": {"chapter_title": "争执"}})

    expected = "表达风格：幽默：让笑点来自人物反应、处境反差和顺口接话，不刻意抖包袱。"
    assert prompt.count(expected) == 1


def test_web_game_method_loads_only_trade_language_for_trade_scene():
    text = "\n".join(
        _web_game_writing_method_lines(
            2,
            {"chapter_goal": "打开交易行，查看求购单并按一口价出售材料"},
        )
    )

    assert "求购单" in text
    assert "一口价" in text
    assert "平台封存" in text
    assert "进本" not in text
    assert "坦克" not in text


def test_web_game_method_loads_only_combat_language_for_combat_scene():
    text = "\n".join(
        _web_game_writing_method_lines(
            2,
            {"chapter_goal": "在灰狼坡拉怪，卡位以后脱战回蓝"},
        )
    )

    assert "拉怪" in text
    assert "脱战" in text
    assert "一口价" not in text
    assert "求购单" not in text


def test_segment_prompt_puts_scene_method_before_guardrails():
    spec = build_segment_specs(1, {})[0]
    prompt = build_segment_prompt(chapter_number=1, spec=spec, plan={})

    assert "输出要求：只写连续小说正文" in prompt
    assert "把这一场写成连续小说正文" in prompt
    assert "要有完整来回" in prompt
    assert "情绪放进动作、停顿和回答里" in prompt
    assert "写法施工单" not in prompt
    assert "本段收住自己的场面" in prompt
    assert prompt.index("## 本章方向") < prompt.index("写作保护线")


def test_compact_writer_plan_excludes_planning_memory_and_world_noise():
    compacted = _compact_writer_plan_for_prompt(
        {
            "chapter_intent": {
                "chapter_title": "补齐委托",
                "next_focus": "查看新收购单",
                "primary_conflict": {"collision": "刷新点竞争激烈"},
            },
            "event_plan": {
                "chapter_title": "补齐委托",
                "ordered_actions": ["换到侧坡", "凑齐材料", "提交任务"],
                "chapter_satisfaction": {
                    "obstacle": "刷新点竞争激烈",
                    "visible_payoff": "提交任务并升级",
                    "cost": "消耗法力药水",
                    "state_change": "升到二级",
                    "next_hook": "查看新收购单",
                },
                "chapter_end_hook": {"content": "查看新收购单"},
                "world_reactions": ["不应进入写手合同的后台反应"],
                "npc_beats": ["不应进入写手合同的NPC调度"],
            },
            "memory_constraints": {
                "must_keep_facts": ["旧事实"],
                "ledger_updates": {"protagonist": {"level": 2}},
            },
            "debug_noise": "不应进入写手合同",
        }
    )

    assert compacted == {
        "chapter_intent": {
            "chapter_title": "补齐委托",
            "next_focus": "查看新收购单",
            "primary_conflict": {"collision": "刷新点竞争激烈"},
        },
        "event_plan": {
            "chapter_title": "补齐委托",
            "chapter_satisfaction": {
                "obstacle": "刷新点竞争激烈",
                "visible_payoff": "提交任务并升级",
                "cost": "消耗法力药水",
                "state_change": "升到二级",
                "next_hook": "查看新收购单",
            },
            "ordered_actions": ["换到侧坡", "凑齐材料", "提交任务"],
            "chapter_end_hook": {"content": "查看新收购单"},
        },
    }


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


def test_writer_character_section_renders_compact_projected_states():
    lines = _writer_character_section(
        {
            "cards": [
                {
                    "identity": {"name": "苏叶", "role": "主角"},
                    "motivation": "验证异常",
                    "state_context": {
                        "real_state": {"current": {"balance": "27.60"}},
                        "game_state": {"current": {"level": "Lv.2"}},
                    },
                }
            ]
        },
        {},
    )

    rendered = "\n".join(lines)
    assert "现实状态：" in rendered
    assert "游戏状态：" in rendered
    assert "balance" not in rendered
    assert "level" not in rendered
    assert "27.60" in rendered
    assert "Lv.2" in rendered


def test_writer_character_section_omits_metadata_only_zero_state():
    lines = _writer_character_section(
        {
            "cards": [
                {
                    "identity": {"name": "夜烬", "role": "主角"},
                    "state_context": {"game_state": {"current": {"updated_chapter": 0}}},
                }
            ]
        },
        {},
    )

    assert "游戏状态：0" not in "\n".join(lines)


def test_writer_context_excludes_unapproved_proposed_character_from_stale_plan():
    story = StoryState(
        story_id="s-proposed-cast",
        outline="夜烬在游戏里推进新手任务。",
        genre="网游",
        style="白描",
        characters=[
            CharacterState(name="苏叶", role="protagonist", game_id="夜烬"),
            CharacterState(
                name="白河仓库收购方",
                role="收购方NPC",
                lifecycle_state="proposed",
                last_approved_chapter=0,
            ),
        ],
    )
    plan = {
        "character_moves": [
            {"name": "夜烬", "action": "接取清道夫委托"},
            {"name": "白河仓库收购方", "action": "询问材料来源"},
        ]
    }

    context = _character_context_for_prompt(story, plan)

    assert [card["identity"]["name"] for card in context["cards"]] == ["苏叶"]


def test_writer_prompt_projects_only_the_scene_line_and_renders_it():
    story = StoryState(
        story_id="s-dual-prompt",
        outline="网游开服，同时承受现实压力。",
        genre="网游",
        style="升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                real_state={"current": {"balance": "27.60"}},
                game_state={"current": {"level": "Lv.2"}},
            )
        ],
    )
    plan = {"scene_cards": [{"location": "副本入口", "purpose": "领取任务"}]}

    context = _character_context_for_prompt(story, plan)
    assert set(context["cards"][0]["state_context"]) == {"game_state"}
    assert "27.60" not in str(context)

    prompt = StoryOrchestrator()._body_prompt(story, 1, plan)
    assert "游戏状态：" in prompt
    assert "Lv.2" in prompt
    assert "现实状态：" not in prompt


def test_fallback_body_prompt_uses_same_scene_method():
    story = StoryState(story_id="s-method", outline="都市悬疑", genre="悬疑", style="克制")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "旧楼"}})

    assert "## 输出要求" in prompt
    assert "写成一章顺着人物行动自然展开的连续正文" in prompt
    assert "人物说话要有来有回" in prompt
    assert "## 本章方向" in prompt
    assert "写法施工单" not in prompt
    assert prompt.index("## 本章方向") < prompt.index("## 本章事实")


def test_writer_direction_drops_generic_taskbook_placeholders():
    story = StoryState(
        story_id="s-concrete-direction",
        outline="夜烬完成清道夫委托。",
        genre="网游",
        style="白描",
    )
    prompt = StoryOrchestrator()._body_prompt(
        story,
        2,
        {
            "writing_taskbook": {
                "chapter_goal": "完成本章推进",
                "scenes": [
                    {
                        "title": "当前地点：清道夫委托完成，经验推进到60/100",
                        "goal": "清道夫委托完成，经验推进到60/100；阻力是出现可见阻力。",
                        "required_surface": "地点、行动、反馈、代价",
                        "exit_state": "形成下一场压力。",
                    }
                ],
            }
        },
    )

    assert "目标：清道夫委托完成，经验推进到60/100" in prompt
    assert "完成本章推进" not in prompt
    assert "出现可见阻力" not in prompt
    assert "形成下一场压力" not in prompt


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

    assert "## 本章方向" in prompt
    assert "网游写法方法卡" in prompt
    assert "眼前目标" in prompt
    assert "看得见的小进展" in prompt
    assert "隐藏优势只在幕后起作用" in prompt
    assert "## 本章方向" in prompt
    assert "小样例" not in prompt
    assert "试清楚能不能走，不急着赚钱" in prompt
    assert "本章先不写" in prompt
    assert all(term in prompt for term in ("寄售", "成交", "到账"))
    assert "边界章禁写" not in prompt


def test_web_game_first_chapter_whole_body_prompt_has_plain_four_beat_contract():
    story = StoryState(story_id="s-whole-ch1", outline="网游开服，千倍爆率。", genre="网游", style="番茄升级流")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "灰狼坡"}})

    assert "整章顺序" in prompt
    assert "网游写法方法卡" in prompt
    assert "遇到阻力后付出代价" in prompt
    assert "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子" in prompt
    assert "本次不用分段生成" in prompt
    assert "白描" not in prompt
    assert "自然对话" in prompt
    assert "句子随动作和对话自然变化，保持现代中文语序" in prompt
    assert "规则从动作和反馈里露出来" in prompt
    assert prompt.index("整章顺序") < prompt.index("## 本章事实")


def test_trade_authorized_first_chapter_prompt_uses_the_actual_five_step_order():
    story = StoryState(story_id="s-trade-order", outline="网游开服后匿名处理稀有材料。", genre="网游", style="白描")
    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {
            "governance": {"chapter_intent": {"first_chapter_trade_authorized": True}},
            "event_plan": {"chapter_title": "第一笔到账", "turn": "担保交易到账并付清急账"},
        },
    )

    assert "现实压力 -> 登录建号 -> 低级验证 -> 匿名交割与急账处理 -> 下一步" in prompt
    assert "第一章只完成开服现场、建号、低级验证和下一步决定" not in prompt


def test_web_game_writer_prompt_moves_on_after_a_panel_instead_of_explaining_it():
    story = StoryState(story_id="s-panel-transition", outline="网游开服。", genre="网游", style="白描")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "灰狼坡"}})

    assert "面板后不复述字段含义" in prompt
    assert "下一句直接写人物的动作、选择或受到的影响" in prompt


def test_writer_system_prompt_distinguishes_prose_from_json_work():
    orchestrator = StoryOrchestrator()

    prose_prompt = orchestrator._model_system_prompt(False)
    json_prompt = orchestrator._model_system_prompt(True)

    assert "中文网文作者" in prose_prompt
    assert "不解释创作规则" in prose_prompt
    assert "novel simulation engine" not in prose_prompt
    assert "json format only" in json_prompt


def test_web_game_writer_seed_is_rendered_as_clean_chinese_not_python_data():
    story = StoryState(
        story_id="s-clean-seed",
        outline="网游开服。",
        genre="网游",
        style="白描",
        outline_context={
            "overall": {"story": "苏叶以最后46.83元等待《神域》开服。"},
            "chapter": {
                "chapter_number": 1,
                "title": "第一笔到账",
                "opening_balance": "46.83元",
                "trade_arrival": "1764.00元",
                "ending_balance": "332.60元",
            }
        },
    )
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "第一笔到账"}})

    assert "章节：1" not in prompt
    assert "当前职业路线为当前职业" not in prompt
    assert "{'" not in prompt


def test_writer_prompt_keeps_style_voice_without_profile_metadata_or_duplicate_pattern():
    story = StoryState(story_id="s-style-slice", outline="网游开服。", genre="网游", style="白描")
    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {
            "event_plan": {"chapter_title": "灰狼坡"},
            "style_guidance": {
                "profile_id": "web_game_leveling_opening",
                "genre": "web_game_leveling",
                "voice": "直白、紧凑、生活化",
                "chapter_pattern": "现实压力 -> 游戏入口 -> 领先验证",
                "show_rules": ["用面板表现优势。"],
                "avoid_rules": ["不要写成说明书。"],
            },
        },
    )

    assert "表达风格：直白、紧凑、生活化" in prompt
    assert "profile_id" not in prompt
    assert "chapter_pattern" not in prompt
    assert "用面板表现优势" not in prompt


def test_first_chapter_prompt_explains_amount_sequence_without_changing_prices():
    story = StoryState(
        story_id="s-amount-sequence",
        outline="匿名处理稀有材料并付清急账。",
        genre="网游",
        style="白描",
        outline_context={
            "overall": {"story": "苏叶以最后46.83元等待《神域》开服。"},
            "chapter": {
                "chapter_number": 1,
                "goal": "苏叶以最后46.83元登录游戏。",
                "payoff": "担保交易到账1764.00元，付清急账后现实余额变为332.60元。",
                "opening_balance": "46.83元",
                "trade_arrival": "1764.00元",
                "ending_balance": "332.60元",
            }
        },
    )

    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "第一笔到账"}})

    assert "金额顺序" in prompt
    assert "支付完成后才写章末余额332.60元" in prompt
    assert "净到账1764.00元不能同时写成成交总价" in prompt


def test_body_prompt_uses_writer_facing_material_not_backend_contract_keys():
    story = StoryState(story_id="s-writer-facing", outline="网游开服，千倍爆率。", genre="网游", style="番茄升级流")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "灰狼坡"}})

    assert "章节：1" not in prompt
    assert "看得见的小进展" in prompt
    assert "生成前世界推演契约" not in prompt
    assert "writing_contract" not in prompt
    assert "allowed_progress" not in prompt
    assert "chapter_contract" not in prompt
    assert "current_level" not in prompt
    assert "progression_stage" not in prompt
    assert "must_show" not in prompt
    assert "must_not_write" not in prompt


def test_body_prompt_prefers_positive_craft_guidance_over_rule_scolding():
    story = StoryState(story_id="s-positive-guidance", outline="网游开服，千倍爆率。", genre="网游", style="番茄升级流")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "灰狼坡"}})

    assert "段落写法：长短段交替" in prompt
    assert "人物说话要有来有回" in prompt
    assert "段落形态：禁止" not in prompt
    assert "后台术语和事实矛盾词不得进正文" not in prompt
    assert prompt.count("不要") <= 8
    assert prompt.count("禁止") <= 2
    assert prompt.count("不得") <= 2


def test_body_prompt_loads_only_enabled_skill_purposes(monkeypatch):
    from packages.story_core import orchestrator as orchestrator_module

    monkeypatch.setattr(
        orchestrator_module,
        "skill_pack_prompt_context",
        lambda skill_ids, *, purpose, max_chars_per_pack: [{"purpose": purpose, "skill_ids": skill_ids}],
    )
    story = StoryState(
        story_id="s-skill-stage",
        outline="都市故事",
        genre="都市",
        style="白描",
        enabled_skill_ids=["plain-webnovel"],
    )
    prompt = StoryOrchestrator()._body_prompt(story, 1, {})

    assert "启用 Skill 模块摘要" in prompt
    assert "plain-webnovel" in prompt


def test_body_prompt_does_not_teach_by_checklist_or_imitation_sample():
    story = StoryState(story_id="s-compact-method", outline="网游开服，千倍爆率。", genre="网游", style="番茄升级流")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "灰狼坡"}})

    assert "写法施工单" not in prompt
    assert "小样例" not in prompt
    assert "进入压力 -> 尝试动作 -> 即时反馈 -> 选择代价 -> 余波/小钩子" not in prompt


def test_body_prompt_has_five_writer_facing_sections_without_duplicate_style_rules():
    story = StoryState(story_id="s-five", outline="外门守炉", genre="xianxia", style="白描")
    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {"event_plan": {"chapter_title": "守炉", "character_moves": [{"name": "林照"}]}},
    )

    headings = ["## 输出要求", "## 本章方向", "## 本章事实", "## 出场人物", "## 正文写法"]
    assert all(heading in prompt for heading in headings)
    assert [prompt.index(heading) for heading in headings] == sorted(prompt.index(heading) for heading in headings)
    assert prompt.count("第三人称有限视角") == 1
    assert "event_plan" not in prompt
    assert "character_moves" not in prompt
    assert "每句台词" not in prompt
    assert "全面禁用" not in prompt


def test_body_prompt_translates_planning_jargon_into_natural_chinese():
    story = StoryState(story_id="s-natural-direction", outline="外门守炉", genre="xianxia", style="白描")
    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {
            "writing_taskbook": {
                "chapter_number": 1,
                "chapter_goal": "让世界根据主角行动给出可见反应",
                "scenes": [
                    {
                        "key": "test",
                        "title": "库房",
                        "goal": "确认关键账本或状态",
                        "required_surface": "NPC/环境/任务/对手反应",
                        "exit_state": "收益和代价落到账本或关系里",
                    }
                ],
            }
        },
    )

    for jargon in (
        "关键账本或状态",
        "让世界根据主角行动给出可见反应",
        "NPC/环境/任务/对手反应",
        "收益和代价落到账本或关系里",
    ):
        assert jargon not in prompt
    assert "主角动手以后，马上出现一个具体结果或麻烦" in prompt
    assert "现场人物、环境或对手的反应" in prompt


def test_body_prompt_keeps_normal_chinese_connectors_available():
    story = StoryState(story_id="s-connectors", outline="外门守炉", genre="xianxia", style="白描")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "守炉"}})

    assert "禁用‘但是’" not in prompt
    assert "禁用‘虽然’" not in prompt
    assert "正常的接话、解释和情绪变化" in prompt
    assert "不要把多个判断压成逗号清单" in prompt
    assert "没好处，没奖励，地方偏" in prompt


def test_web_game_second_chapter_does_not_inherit_first_chapter_service_bans():
    story = StoryState(story_id="s-ch2-method", outline="网游开服，千倍爆率。", genre="网游", style="番茄升级流")
    prompt = StoryOrchestrator()._body_prompt(story, 2, {"event_plan": {"chapter_title": "清道夫柜台"}})

    assert "网游写法方法卡" in prompt
    assert "第一章领先流" not in prompt
    assert "不要写成交任务、领取铜币、扣费修理或购买药水" not in prompt


def test_writer_prompt_reads_all_scoped_world_context_rules_once():
    story = StoryState(
        story_id="s-world-context",
        outline="夜烬回村提交清道夫委托。",
        genre="网游",
        style="白描",
        world_context={
            "world_rules": ["NPC只能处理岗位权限内的事务。"],
            "progression_rules": ["升级必须来自可验证经验。"],
            "quest_rules": ["任务必须先登记，再执行和提交。"],
            "economy_rules": ["材料价格必须来自任务、配方或真实稀缺性。"],
            "faction_rules": ["服务NPC只能处理岗位权限内的事务。"],
        },
    )

    prompt = StoryOrchestrator()._body_prompt(
        story,
        2,
        {"event_plan": {"chapter_title": "提交清道夫委托", "turn": "药剂师NPC用毒腺结算任务经验和铜币"}},
    )

    assert "本章相关世界规则" in prompt
    assert "NPC只能处理岗位权限内的事务" in prompt
    assert "升级必须来自可验证经验" in prompt
    assert "任务必须先登记" in prompt
    assert "材料价格必须来自任务" in prompt
    assert "服务NPC只能处理岗位权限内的事务" in prompt
    assert "现实到账必须经过官方结算渠道" not in prompt
    assert prompt.count("任务必须先登记") == 1


def test_revision_prompt_keeps_method_and_separates_viewpoint_rule():
    story = StoryState(story_id="s-revision-method", outline="都市悬疑", genre="悬疑", style="克制")
    prompt = StoryOrchestrator()._revision_prompt(
        story,
        1,
        "原正文",
        {"event_plan": {"chapter_title": "旧楼"}},
        {"pass": False, "issues": ["视角越界"], "revision_plan": ["改回主角限知"]},
    )

    assert "## 输出要求" in prompt
    assert "写成一章顺着人物行动自然展开的连续正文" in prompt
    assert "写法施工单" not in prompt
    assert "第三人称有限视角" in prompt
    assert "## 综合审稿修改" in prompt
    assert "## 原正文" in prompt
    assert "上帝视角。工作流词" not in prompt


def test_revision_prompt_reuses_five_sections_and_adds_only_revision_material():
    story = StoryState(story_id="s-revision-five", outline="外门守炉", genre="xianxia", style="白描")
    prompt = StoryOrchestrator()._revision_prompt(
        story,
        1,
        "林照关上门。",
        {"event_plan": {"chapter_title": "守炉"}},
        {"issues": ["对话太短"], "revision_plan": ["补成完整来回"]},
    )

    headings = [
        "## 输出要求",
        "## 本章方向",
        "## 本章事实",
        "## 出场人物",
        "## 正文写法",
        "## 综合审稿修改",
        "## 原正文",
    ]
    assert all(heading in prompt for heading in headings)
    assert [prompt.index(heading) for heading in headings] == sorted(prompt.index(heading) for heading in headings)
    assert "对话太短" in prompt
    assert "林照关上门。" in prompt
    assert "scores" not in prompt


def test_game_writer_prompt_explains_monster_panel_frequency_and_fields():
    story = StoryState(story_id="s-monster-panel", outline="夜烬进入新地图打怪。", genre="网游", style="白描")

    prompt = StoryOrchestrator()._body_prompt(
        story,
        2,
        {"event_plan": {"chapter_title": "矿洞入口", "ordered_actions": ["首次挑战矿洞精英怪"]}},
    )

    assert "怪物面板" in prompt
    assert "名称、等级、生命和攻击方式" in prompt
    assert "同类普通怪后续不重复" in prompt
    assert "精英怪和首领" in prompt
    assert "掉落" in prompt and "击杀后" in prompt


def test_game_writer_prompt_only_includes_monsters_named_in_chapter_plan():
    story = StoryState(
        story_id="s-monster-cards",
        outline="夜烬进入灰狼坡。",
        genre="网游",
        style="白描",
        monster_profiles=[
            {
                "name": "灰狼",
                "category": "野兽",
                "rank": "普通",
                "level": "1-2",
                "hp": "80",
                "attack_mode": "扑咬",
                "skills": [],
                "traits": ["听觉敏锐"],
                "habitats": ["灰狼坡"],
                "drops": ["灰狼毒腺", "粗糙狼皮"],
            },
            {
                "name": "熔岩蜥蜴",
                "category": "元素兽",
                "rank": "精英",
                "level": "18",
                "hp": "2400",
                "attack_mode": "喷火",
                "skills": ["熔岩吐息"],
                "traits": ["火焰抗性"],
                "habitats": ["熔岩洞穴"],
                "drops": ["熔岩核心"],
            },
        ],
    )

    prompt = StoryOrchestrator()._body_prompt(
        story,
        2,
        {"event_plan": {"chapter_title": "灰狼坡", "ordered_actions": ["夜烬迎战灰狼"]}},
    )

    assert "本章怪物卡" in prompt
    assert "灰狼" in prompt and "扑咬" in prompt and "灰狼毒腺" in prompt
    assert "熔岩蜥蜴" not in prompt


def test_game_writer_prompt_filters_unplanned_common_monster_drops_from_locked_chapter_ledger():
    story = StoryState(
        story_id="s-monster-ledger",
        outline="夜烬在灰狼坡验证异常掉落，并卖掉裂纹狼心。",
        genre="网游",
        style="白描",
        monster_profiles=[
            {
                "name": "灰狼",
                "level": "1",
                "hp": "82",
                "attack_mode": "扑咬",
                "drops": [
                    "灰狼毒腺：用于清道夫委托",
                    "粗糙狼皮：用于新手护具",
                    "磨损狼牙：用于箭簇制造",
                    "裂纹狼心：稀有样本",
                ],
            }
        ],
    )
    plan = {
        "event_plan": {
            "chapter_title": "灰狼坡的第一笔到账",
            "ordered_actions": ["击杀灰狼", "匿名卖掉裂纹狼心"],
        },
        "scene_cards": [
            {
                "state_delta": {
                    "game_world_simulation": {
                        "final_state": {"inventory": {"灰狼毒腺": 8, "粗糙狼皮": 7}}
                    }
                }
            }
        ],
    }

    prompt = StoryOrchestrator()._body_prompt(story, 1, plan)

    assert "灰狼毒腺" in prompt
    assert "粗糙狼皮" in prompt
    assert "裂纹狼心" in prompt
    assert "磨损狼牙" not in prompt
    assert "本章普通掉落账本：灰狼毒腺、粗糙狼皮" in prompt


