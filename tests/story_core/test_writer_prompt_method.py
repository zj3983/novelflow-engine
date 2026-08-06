from pathlib import Path

import pytest

import packages.story_core.orchestrator as orchestrator_module
import packages.story_core.genre_stages.game_webnovel.director as game_director_module
import packages.story_core.genre_stages.game_webnovel.revision as game_revision_module
import packages.story_core.genre_stages.game_webnovel.writer as game_writer_module

from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.genre_types.urban import URBAN
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.genre_stages.common_writer import (
    _plan_target_chars,
    _writer_character_section,
    _writer_craft_section,
)
from packages.story_core.genre_stages.game_webnovel.writer import (
    _augment_game_character_section,
    _web_game_writing_method_lines,
)
from packages.story_core.orchestrator import (
    StoryOrchestrator,
    _character_context_for_prompt,
    _compact_writer_plan_for_prompt,
    _director_context_payload,
    _review_context_facts,
)
from packages.story_core.web_game_economy import (
    normalize_legacy_economy_prompt_value,
    opening_market_exchange_flow_lines,
)
from packages.story_core.writing_packet import build_codex_writing_packet


def _writer_power_spec() -> dict:
    return {
        "name": "神域职业体系",
        "origin": ["职业权能来自试炼"],
        "stages": [
            {"name": "见习者", "level": 1, "entry": "创建角色", "change": "通用能力", "failure": "重新建号"},
            {"name": "正式职业", "level": 10, "entry": "正式转职任务", "change": "职业资源", "failure": "任务冷却"},
            {"name": "专精", "level": 20, "entry": "专精试炼", "change": "强化方向", "failure": "材料损失"},
            {"name": "进阶职业", "level": 30, "entry": "分支任务", "change": "分支能力", "failure": "晋升延期"},
        ],
        "paths": [
            {"name": "法师", "branches": ["元素法师", "秘术法师"], "role": "远程输出", "advancement": ["元素核心试炼"]},
            {"name": "战士", "branches": ["盾战士", "狂战士"], "role": "近战承伤", "advancement": ["战团试炼"]},
        ],
        "skills": ["技能必须通过导师、技能书或试炼获得"],
        "equipment": ["装备必须来自掉落、制作或交易"],
        "resources": ["法力通过休息或药剂恢复"],
        "advancement": ["晋升必须满足等级、任务和材料"],
        "costs": ["透支会造成虚弱"],
        "counters": ["沉默克制持续施法"],
        "boundaries": ["不得无条件跨越两个阶段"],
        "continuity_ledger": ["level", "class_path", "skills", "equipment", "resources", "conditions"],
    }


def test_writer_default_length_matches_quality_target_instead_of_triggering_expansion():
    assert _plan_target_chars({}) == "4200到5000字，绝对不要超过5500字"
    assert _plan_target_chars({"target_chars": 3000}) == "4200到5000字，绝对不要超过5500字"
    assert _plan_target_chars({"target_chars": 4800}) == "4500到5100字，绝对不要超过5500字"


def test_director_context_uses_current_chapter_cast_not_future_outline_names():
    story = StoryState(
        story_id="s-current-cast",
        outline="The long outline eventually introduces Lu Heng.",
        genre="urban",
        style="",
        outline_context={"chapter": {"chapter_number": 1, "cast": ["Shen Chuan", "Shen Yu"]}},
        characters=[
            CharacterState(name="Shen Chuan", role="protagonist"),
            CharacterState(name="Shen Yu", role="son"),
            CharacterState(name="Lu Heng", role="future antagonist"),
        ],
    )

    payload = _director_context_payload(story, 1)
    names = [card["identity"]["name"] for card in payload["character_cards"]["cards"]]
    snapshot_names = [card["name"] for card in payload["project_snapshot"]["characters"]]

    assert names == ["Shen Chuan", "Shen Yu"]
    assert snapshot_names == ["Shen Chuan", "Shen Yu"]


def test_writer_character_section_uses_story_identity_instead_of_internal_role_label():
    story = StoryState(
        story_id="s-display-role",
        outline="A watchmaker faces eviction.",
        genre="urban",
        style="",
        characters=[
            CharacterState(
                name="Shen Chuan",
                role="protagonist",
                identity_profile={
                    "current_identity": "old mall watch shop owner",
                    "occupation": "watchmaker",
                },
            )
        ],
    )

    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {"event_plan": {"character_moves": [{"name": "Shen Chuan"}]}},
    )

    assert "Shen Chuan：old mall watch shop owner" in prompt
    assert "Shen Chuan：protagonist" not in prompt


def test_writer_prompt_prevents_long_runs_of_telegraphic_everyday_dialogue():
    story = StoryState(story_id="s-dialogue-rhythm", outline="A family argument.", genre="urban", style="")

    prompt = StoryOrchestrator()._body_prompt(story, 1, {})

    assert "连续问答不能三句以上都只剩两到六个字" in prompt


def test_writer_prompt_does_not_turn_professional_character_notes_into_checklist_dialogue():
    lines = _writer_character_section(
        {
            "cards": [
                {
                    "identity": {"name": "沈屿", "display_role": "沈川的儿子"},
                    "motivation": "找出旧表的来路",
                    "speech_style": "说话像在核对条款，常用流程、数据和时间节点压人，不愿先示弱。",
                }
            ]
        },
        {},
    )
    prompt = "\n".join(lines)

    assert "说话像在核对条款" not in prompt
    assert "不连续罗列术语或材料" in prompt


def test_writer_prompt_keeps_book_level_outline_and_growth_rules_out_of_prose_context():
    story = StoryState(
        story_id="s-chapter-only-context",
        outline="父子在互不信任中被迫合作，最终完成整座商场的权益谈判。",
        genre="urban",
        style="",
        author_constraints=[
            "沈川的成长从沉默匠人转向证据组织者，每一步必须依靠台账拼合和证人确认。"
        ],
    )
    plan = {
        "event_plan": {
            "chapter_satisfaction": {
                "core_event": "沈川认出旧表上的维修定位痕。",
                "obstacle": "儿子不肯说明旧表来路。",
                "state_change": "沈川把旧表留下。",
                "next_hook": "清退负责人带着协议进门。",
            }
        }
    }

    prompt = StoryOrchestrator()._body_prompt(story, 1, plan)

    assert "最终完成整座商场的权益谈判" not in prompt
    assert "成长从沉默匠人转向证据组织者" not in prompt


def test_writer_prompt_forbids_padding_with_process_explanations():
    story = StoryState(story_id="s-no-process-padding", outline="A tense family meeting.", genre="urban", style="")

    prompt = StoryOrchestrator()._body_prompt(story, 1, {})

    assert "不靠重复问答、材料清单或流程解释补足篇幅" in prompt
    assert "只说促成眼前决定所需的信息" in prompt


def test_non_game_writer_does_not_receive_procedural_world_rule_checklists():
    story = StoryState(
        story_id="s-urban-procedure-boundary",
        outline="A watchmaker examines an old watch.",
        genre="urban",
        style="",
        world_context={
            "world_rules": [
                "旧物只能作为线索入口，不能替代法律程序；每次鉴定必须落到痕迹、编号、维修记录、照片、证言或票据。"
            ]
        },
    )

    prompt = StoryOrchestrator()._body_prompt(story, 1, {})

    assert "编号、维修记录、照片、证言或票据" not in prompt


def test_writer_character_section_uses_scene_voice_not_book_length_motivation():
    lines = _writer_character_section(
        {
            "cards": [
                {
                    "identity": {"name": "沈川", "display_role": "老商场修表匠"},
                    "motivation": "证明旧表与历史权益有关，争取暂缓清退，并弥补过去对家人的逃避。",
                    "risk_posture": "不肯在来路不明时下结论",
                    "speech_style": "平时话少，但会把当下决定说清楚。",
                }
            ]
        },
        {},
    )
    prompt = "\n".join(lines)

    assert "老商场修表匠" in prompt
    assert "不肯在来路不明时下结论" in prompt
    assert "平时话少" in prompt
    assert "弥补过去对家人的逃避" not in prompt


def test_writer_character_section_drops_planner_meta_wants():
    lines = _writer_character_section(
        {},
        {
            "participants": [
                {
                    "name": "沈川",
                    "want": "让沈川在清退倒计时里接下旧表，建立核心悬念。",
                    "emotion": "警惕",
                }
            ]
        },
    )
    prompt = "\n".join(lines)

    assert "让沈川" not in prompt
    assert "沈川当前情绪：警惕" in prompt


def test_writer_prompt_surfaces_financial_attribute_and_anomaly_anchors():
    story = StoryState(
        story_id="s-writer-explicit-anchors",
        outline="夜烬在神域开服首日解决现实急账。",
        genre="网游",
        style="简洁",
        author_constraints=["第一章付清急账后现实余额为332.60元。"],
        world_facts=[
            "苏叶登录游戏前，账户余额46.83元。",
            "官方兑换实际到账1764.00元。",
            "核心异常为底层协议校验通过、千倍爆率、混沌之种：未解析。",
        ],
        outline_context={
            "chapter": {
                "chapter_number": 1,
                "attribute_allocation_decision": {
                    "mode": "allocate",
                    "allocations": {"智力": 5},
                    "remaining": 0,
                    "reason": "强化基础火球术",
                },
            }
        },
    )
    plan = {
        "event_plan": story.outline_context["chapter"],
        "power_system": _writer_power_spec(),
    }

    prompt = StoryOrchestrator()._body_prompt(story, 1, plan)

    assert "登录前现实余额46.83元" in prompt
    assert "交易完成后净到账1764.00元" in prompt
    assert "章末余额332.60元" in prompt
    assert "本章属性点决定：智力+5" in prompt
    assert "可用点归零" in prompt
    assert "底层协议校验通过" in prompt
    assert "千倍爆率" in prompt
    assert "混沌之种：未解析" in prompt


def _writer_power_story() -> StoryState:
    return StoryState(
        story_id="s-power-prompts",
        outline="夜烬推进元素法师路线。",
        genre="网游",
        style="白描",
        progression_ledger={"protagonist": {"level": 12, "class_path": "元素法师"}},
        world_context={"power_system_spec": _writer_power_spec()},
    )


def test_chapter_planner_and_writer_receive_packet_power_system_slice():
    story = _writer_power_story()
    packet = build_codex_writing_packet(story, chapter_number=3)
    plan = {"event_plan": {"chapter_title": "元素试炼"}, "power_system": packet["power_system"]}

    director_prompt = StoryOrchestrator()._plan_prompt(story, 3)
    writer_prompt = StoryOrchestrator()._body_prompt(story, 3, plan)

    for prompt in (director_prompt, writer_prompt):
        assert "神域职业体系" in prompt
        assert "正式职业" in prompt and "专精" in prompt
        assert "元素法师" in prompt
        assert "透支会造成虚弱" in prompt
        assert "不得无条件跨越两个阶段" in prompt
    assert "战士" not in writer_prompt


def test_reviewer_and_revision_context_receive_power_contract_and_explicit_checks():
    story = _writer_power_story()
    facts = "\n".join(_review_context_facts(story))
    prompt = StoryOrchestrator()._revision_prompt(
        story,
        3,
        "夜烬抬手施法。",
        {"event_plan": {"chapter_title": "元素试炼"}},
        {"issues": ["晋升缺少代价"], "revision_plan": ["补足失败后果"]},
    )

    for context in (facts, prompt):
        assert "costs" in context and "boundaries" in context and "continuity_ledger" in context
        assert "正式职业" in context and "专精" in context and "元素法师" in context
        assert "虚构技能" in context
        assert "免费晋升" in context
        assert "不可能的等级差" in context


def test_body_prompt_has_no_unselected_plain_style_fallback():
    story = StoryState(story_id="s-no-style", outline="公司发生一场争执。", genre="都市", style="")

    prompt = StoryOrchestrator()._body_prompt(story, 2, {"event_plan": {"chapter_title": "争执"}})

    assert "通用白描" not in prompt
    assert "整体用白描" not in prompt
    assert "番茄白话风" not in prompt
    assert "表达风格：" not in prompt


def test_non_game_body_prompt_does_not_receive_game_interface_rules():
    story = StoryState(story_id="s-urban-clean", outline="便利店盘点异常。", genre="都市", style="")

    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "夜班盘点"}})

    assert "面板只作为" not in prompt
    assert "交易、鉴定和任务办理" not in prompt
    assert "面板、公告和物品说明" not in prompt
    assert "交易与鉴定也按现场来写" not in prompt


def test_universal_writer_craft_is_short_and_genre_neutral():
    lines = _writer_craft_section(
        {},
        {},
        include_genre_method=False,
        style_guidance={},
    )
    text = "\n".join(lines)

    for phrase in (
        "经历、眼前利益和性格",
        "配角有自己的目的",
        "关键冲突、转折和结果写成现场",
        "对话先回应对方刚说的内容",
        "情绪放进动作、停顿、语气、回避和选择",
        "环境跟着人物行动出现",
        "完整的现代中文句子",
        "具体动作、物件和后果",
        "场景结束时发生看得见的变化",
    ):
        assert phrase in text
    for game_term in (
        "玩家",
        "NPC",
        "怪物",
        "面板",
        "等级",
        "技能",
        "装备",
        "任务",
        "掉落",
        "背包",
        "拍卖行",
        "铜币",
        "每300字",
        "每500字",
        "80%",
    ):
        assert game_term not in text
    assert len(lines) <= 11


@pytest.mark.parametrize("genre", ["都市", "东方玄幻", "仙侠"])
def test_non_game_writer_prompts_do_not_receive_web_game_craft(genre):
    story = StoryState(
        story_id=f"s-genre-neutral-{genre}",
        outline="主角进入一处陌生环境并处理眼前冲突。",
        genre=genre,
        style="白描",
    )

    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {"event_plan": {"chapter_title": "初入此地"}},
    )

    for game_phrase in (
        "## 网游写法",
        "怪物面板",
        "背包",
        "拍卖行",
        "一口价",
        "掉落",
        "玩家和NPC",
    ):
        assert game_phrase not in prompt


def test_web_game_writer_prompt_has_one_compact_genre_method_card():
    story = StoryState(
        story_id="s-one-web-game-method-card",
        outline="玩家继续完成新手区委托。",
        genre="网游",
        style="白描",
        current_chapter=2,
    )

    prompt = StoryOrchestrator()._body_prompt(
        story,
        2,
        {"chapter_goal": "击败同级怪物并提交任务"},
    )

    output_section = prompt.split("## 输出要求", 1)[1].split("\n## ", 1)[0]
    web_game_section = prompt.split("## 网游写法", 1)[1].split("\n## ", 1)[0]

    assert "面板只作为" not in output_section
    assert "交易、鉴定和任务办理" not in output_section
    assert prompt.count("## 网游写法") == 1
    for phrase in ("面板", "交易", "任务", "背包", "隐藏优势"):
        assert phrase in web_game_section


def test_new_game_story_does_not_inherit_another_books_names_or_cheat():
    story = StoryState(story_id="s-space-game", outline="玩家进入星舰网游，准备修复采矿机器人。", genre="网游", style="")
    plan = {
        "event_plan": {"chapter_title": "失控的采矿机"},
        "scene_cards": [
            {
                "id": "mine-robot",
                "location": "月面矿坑",
                "purpose": "关闭失控的采矿机器人",
                "conflict": "能源护盾挡住控制台",
                "must_show": ["工程终端", "护盾电量"],
            }
        ],
    }

    prompt = StoryOrchestrator()._body_prompt(story, 1, plan)

    assert "采矿机器人" in prompt
    for term in ("夜烬", "千倍爆率", "混沌之种", "灰狼", "毒腺", "清道夫"):
        assert term not in prompt


def test_game_writer_prompt_does_not_rewrite_profession_words_inside_seed_facts():
    story = StoryState(
        story_id="s-no-profession-string-patch",
        outline="玩家选择战士路线。",
        genre="网游",
        style="",
        world_facts=["元素法师协会位于王城东区。"],
    )
    plan = {
        "chapter_seed": {
            "continuity_facts": ["元素法师协会位于王城东区。"],
            "genre_plugins": ["game_webnovel"],
        },
        "event_plan": {"chapter_title": "王城东区"},
    }

    prompt = StoryOrchestrator()._body_prompt(story, 2, plan)

    assert "元素法师协会位于王城东区" in prompt


def test_body_prompt_injects_selected_style_once():
    story = StoryState(story_id="s-humor", outline="公司发生一场争执。", genre="都市", style="幽默")

    prompt = StoryOrchestrator()._body_prompt(story, 2, {"event_plan": {"chapter_title": "争执"}})

    expected = "表达风格：幽默：让笑点来自人物反应、处境反差和顺口接话，不刻意抖包袱。"
    assert prompt.count(expected) == 1


def test_web_game_method_loads_only_trade_language_for_trade_scene():
    text = "\n".join(
        _web_game_writing_method_lines(
            2,
            {"chapter_goal": "打开交易行，按一口价挂单并等待买家购买材料"},
        )
    )

    assert "求购单" in text
    assert "一口价" in text
    assert "接受现有求购单价格" in text
    assert "立即出售并直接成交" in text
    assert "平台封存" in text
    assert "进本" not in text
    assert "坦克" not in text


def test_web_game_method_requests_at_most_three_language_cards(monkeypatch):
    requested_limits = []

    def record_selection(plan, *, max_cards):
        requested_limits.append(max_cards)
        return []

    monkeypatch.setattr(
        "packages.story_core.genre_stages.game_webnovel.writer.select_game_language_cards",
        record_selection,
    )

    _web_game_writing_method_lines(1, {"chapter_goal": "登录后卖出材料并官方兑换"})

    assert requested_limits == [3]


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


TROPE_PROGRESS_GUIDANCE = "本章产生可观察推进"
TROPE_EMPTY_BEAT_GUIDANCE = "只保持阶段承诺，不强行完成整套节点，也不得自行换套路"
TROPE_AVOID_GUIDANCE = "保守遵守 avoid 规则"
OLD_ENGLISH_PROGRESS_GUIDANCE = "This chapter must create observable progress for current_beat; do not merely mention it."
OLD_ENGLISH_EMPTY_BEAT_GUIDANCE = "Maintain the trigger/payoff/avoid stage promise; do not force a full trope beat and do not switch tropes."
OLD_ENGLISH_AVOID_GUIDANCE = "Always follow avoid rules conservatively."


def _urban_trope(template_id: str) -> dict[str, object]:
    return next(template for template in URBAN.trope_templates if template["id"] == template_id)


def _urban_story_with_trope(template_id: str, beat: str | None) -> StoryState:
    return StoryState(
        story_id=f"s-real-trope-{template_id}",
        outline="Urban professional pressure story.",
        genre="urban",
        genre_plugin_ids=["urban"],
        style="plain",
        outline_context={
            "overall": {"primary_trope_id": template_id},
            "active_arc": {"trope_id": template_id},
            "chapter": {
                "chapter_number": 1,
                "title": "Proof",
                "goal": "Build a visible professional result.",
                "trope_beat": beat,
            },
        },
    )




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






def test_writer_character_section_renders_compact_projected_states():
    lines = _augment_game_character_section(
        ["## 出场人物"],
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
    )

    rendered = "\n".join(lines)
    assert "现实状态：" in rendered
    assert "游戏状态：" in rendered
    assert "balance" not in rendered
    assert "level" not in rendered
    assert "27.60" in rendered
    assert "Lv.2" in rendered


def test_writer_character_section_omits_metadata_only_zero_state():
    lines = _augment_game_character_section(
        ["## 出场人物"],
        {
            "cards": [
                {
                    "identity": {"name": "夜烬", "role": "主角"},
                    "state_context": {"game_state": {"current": {"updated_chapter": 0}}},
                }
            ]
        },
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


def test_writer_context_reads_generic_director_character_move_mapping():
    story = StoryState(
        story_id="s-generic-cast-mapping",
        outline="林修与沈墨璃困在雪山神殿。",
        genre="玄幻",
        style="自然口语",
        characters=[
            CharacterState(name="林修", role="主角"),
            CharacterState(name="沈墨璃", role="同伴"),
            CharacterState(name="青云宗主", role="师长"),
        ],
    )
    plan = {
        "character_moves": {
            "林修": [{"goal": "检查寒毒", "emotion": "强撑", "action": "阻止沈墨璃继续探查"}],
            "沈墨璃": [{"goal": "确认伤势", "emotion": "着急", "action": "用灵力探查经脉"}],
        }
    }

    context = _character_context_for_prompt(story, plan)

    assert [card["identity"]["name"] for card in context["cards"]] == ["林修", "沈墨璃"]


def test_writer_character_context_prefers_concrete_drive_and_omits_raw_memory():
    future_marker = "STALE_MEMORY_THAT_BELONGS_TO_CONTINUITY"
    story = StoryState(
        story_id="s-compact-character-context",
        outline="林修检查祖祠阵纹。",
        genre="玄幻",
        style="自然口语",
        characters=[
            CharacterState(
                name="林修",
                role="主角",
                core_motivation="围绕主线目标行动",
                story_drive={"motivation": "保住祖祠，也查清父亲失踪的原因。"},
                memory=[future_marker],
            )
        ],
    )

    context = _character_context_for_prompt(
        story,
        {"character_moves": [{"name": "林修", "action": "检查阵纹"}]},
    )

    card = context["cards"][0]
    assert card["motivation"] == "保住祖祠，也查清父亲失踪的原因。"
    assert "memory" not in card
    assert future_marker not in str(context)


def test_writer_context_does_not_pull_names_from_broad_chapter_intent_metadata():
    story = StoryState(
        story_id="s-scoped-cast",
        outline="陈砚接手早餐店。",
        genre="都市",
        style="自然口语",
        characters=[
            CharacterState(name="陈砚", role="主角"),
            CharacterState(name="梁守成", role="房东"),
            CharacterState(name="赵明启", role="商会负责人"),
            CharacterState(name="周兰", role="母亲"),
        ],
    )
    plan = {
        "character_moves": [{"name": "陈砚", "action": "核对欠租单"}],
        "event_plan": {"ordered_actions": [{"name": "梁守成", "action": "催租"}]},
        "chapter_intent": {
            "background_reference": "赵明启和周兰属于长期人物资料，本章不出场。"
        },
    }

    context = _character_context_for_prompt(story, plan)

    assert [card["identity"]["name"] for card in context["cards"]] == ["陈砚", "梁守成"]


def test_writer_context_does_not_treat_author_constraint_names_as_cast():
    story = StoryState(
        story_id="s-author-constraint-cast",
        outline="沈川检查旧表。",
        genre="都市",
        style="自然口语",
        characters=[
            CharacterState(name="沈川", role="protagonist"),
            CharacterState(name="沈屿", role="儿子"),
            CharacterState(name="陆衡", role="后期对手"),
        ],
    )
    plan = {
        "character_moves": [{"name": "沈川", "action": "检查旧表"}],
        "event_plan": {
            "ordered_actions": ["沈川检查旧表，沈屿在旁边等待。"],
            "author_constraints": ["陆衡前期不能正面出场。"],
        },
    }

    context = _character_context_for_prompt(story, plan)

    assert [card["identity"]["name"] for card in context["cards"]] == ["沈川", "沈屿"]


def test_writer_context_adds_known_character_named_in_chapter_continuity():
    story = StoryState(
        story_id="s-continuity-cast",
        outline="雪山神殿争夺。",
        genre="玄幻",
        style="自然口语",
        characters=[
            CharacterState(name="林修", role="主角"),
            CharacterState(name="沈墨璃", role="同伴"),
            CharacterState(name="青云宗主", role="师长"),
        ],
    )
    plan = {
        "character_moves": {"林修": [{"action": "检查阵心"}]},
        "chapter_seed": {"must_carry": ["沈墨璃和林修同在雪山神殿，并负责查看他的伤势。"]},
    }

    context = _character_context_for_prompt(story, plan)

    assert [card["identity"]["name"] for card in context["cards"]] == ["林修", "沈墨璃"]


def test_writer_context_honors_protagonist_tier_when_imported_role_is_stale():
    story = StoryState(
        story_id="s-stale-protagonist-role",
        outline="林修继承维修之道。",
        genre="玄幻",
        style="自然口语",
        characters=[CharacterState(name="林修", role="supporting", character_tier="protagonist")],
    )

    context = _character_context_for_prompt(story, {"character_moves": {"林修": [{"action": "检查阵心"}]}})

    card = context["cards"][0]
    assert card["identity"]["role"] == "protagonist"
    assert "围绕自己的职位" not in card["motivation"]


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
    assert "state_context" not in context["cards"][0]
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
    assert "对话先回应对方刚说的内容" in prompt
    assert "## 本章方向" in prompt
    assert "写法施工单" not in prompt
    assert prompt.index("## 本章方向") < prompt.index("## 本章事实")


def test_writer_prompt_uses_scene_dialogue_contract_without_fixed_exchange_template():
    story = StoryState(
        story_id="s-natural-dialogue-contract",
        outline="林修和沈墨璃处理失控的寒毒。",
        genre="玄幻",
        style="自然口语",
        characters=[
            CharacterState(name="林修", role="主角"),
            CharacterState(name="沈墨璃", role="配角"),
        ],
    )
    plan = {
        "event_plan": {
            "chapter_title": "寒毒",
            "chapter_satisfaction": {"emotion_target": "两人决定是否继续引出寒毒"},
            "unsaid_pressure": "林修没有说出寒毒已经接近心脉",
        },
        "character_moves": {
            "林修": [{"goal": "劝沈墨璃停手", "emotion": "担心", "action": "按住她的手腕"}],
            "沈墨璃": [{"goal": "确认寒毒位置", "emotion": "着急", "action": "继续运转灵力"}],
        },
    }

    prompt = StoryOrchestrator()._body_prompt(story, 1, plan)

    for phrase in (
        "先回应对方刚说的内容",
        "关系和场合决定说话方式",
        "允许解释、犹豫、回避和日常过渡",
        "整场对话发生变化即可",
        "谈话缘由：两人决定是否继续引出寒毒",
        "林修此刻想要：劝沈墨璃停手",
        "沈墨璃当前情绪：着急",
        "没有说出口：林修没有说出寒毒已经接近心脉",
    ):
        assert phrase in prompt
    for old_rule in (
        "每段对话都让人知道一个条件",
        "本场对话目的：",
        "不用两个字装冷静",
        "一人问/催/提醒",
        "每章至少有一轮连续问答",
        "先试，不深入",
        "柜台不认",
    ):
        assert old_rule not in prompt


def test_non_game_writer_prompt_does_not_receive_planning_trope_contract(monkeypatch):
    contract = {
        "template_id": "public-turnaround",
        "name": "Public turnaround",
        "trigger": "public pressure",
        "current_beat": "collect visible proof",
        "payoff": "reputation turns",
        "avoid": ["no instant full vindication"],
    }
    monkeypatch.setattr(
        "packages.story_core.orchestrator.build_chapter_seed",
        lambda story, chapter_number: {
            "chapter_number": chapter_number,
            "trope_contract": contract,
        },
    )
    story = StoryState(story_id="s-urban-trope", outline="urban pressure", genre="urban", style="plain")

    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "Proof"}})

    assert "当前阶段套路" not in prompt
    assert "public-turnaround" not in prompt
    assert "collect visible proof" not in prompt
    assert TROPE_PROGRESS_GUIDANCE not in prompt
    assert TROPE_AVOID_GUIDANCE not in prompt
    assert OLD_ENGLISH_PROGRESS_GUIDANCE not in prompt
    assert OLD_ENGLISH_AVOID_GUIDANCE not in prompt
    assert "游戏主角" not in prompt


def test_empty_beat_writer_prompt_omits_planning_contract(monkeypatch):
    contract = {
        "template_id": "slow-burn",
        "name": "Slow burn",
        "trigger": "stage promise",
        "current_beat": "",
        "payoff": "later payoff",
        "avoid": ["do not switch tropes"],
    }
    monkeypatch.setattr(
        "packages.story_core.orchestrator.build_chapter_seed",
        lambda story, chapter_number: {
            "chapter_number": chapter_number,
            "trope_contract": contract,
        },
    )
    story = StoryState(story_id="s-empty-beat", outline="slow chapter", genre="urban", style="plain")

    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "Promise"}})

    assert "slow-burn" not in prompt
    assert '"current_beat": ""' not in prompt
    assert TROPE_EMPTY_BEAT_GUIDANCE not in prompt
    assert TROPE_PROGRESS_GUIDANCE not in prompt
    assert OLD_ENGLISH_EMPTY_BEAT_GUIDANCE not in prompt
    assert OLD_ENGLISH_PROGRESS_GUIDANCE not in prompt


def test_writer_fact_section_omits_trope_guidance_when_contract_missing():
    story = StoryState(story_id="s-no-trope", outline="plain", genre="urban", style="plain")

    rendered = StoryOrchestrator()._body_prompt(
        story,
        1,
        {"chapter_seed": {"chapter_number": 1}},
    )

    assert "当前阶段套路" not in rendered
    assert "current_beat" not in rendered
    assert TROPE_AVOID_GUIDANCE not in rendered
    assert OLD_ENGLISH_AVOID_GUIDANCE not in rendered


def test_game_writer_prompt_keeps_game_facts_without_planning_trope_contract(monkeypatch):
    contract = {
        "template_id": "first-advantage",
        "name": "First advantage",
        "trigger": "first test",
        "current_beat": "visible gain",
        "payoff": "advantage lands",
        "avoid": ["no global exposure"],
    }
    monkeypatch.setattr(
        "packages.story_core.orchestrator.build_chapter_seed",
        lambda story, chapter_number: {
            "chapter_number": chapter_number,
            "trope_contract": contract,
            "current_state": {"protagonist": {"level": "Lv.1"}},
        },
    )
    story = StoryState(
        story_id="s-game-trope",
        outline="网游开服",
        genre="网游",
        style="白描",
        progression_ledger={"protagonist": {"game_id": "Night", "class_path": "Rogue"}},
    )

    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "Start"}})

    assert "游戏主角" in prompt
    assert "Night" in prompt
    assert "Rogue" in prompt
    assert "当前阶段套路" not in prompt
    assert "first-advantage" not in prompt
    assert TROPE_PROGRESS_GUIDANCE not in prompt
    assert TROPE_AVOID_GUIDANCE not in prompt
    assert OLD_ENGLISH_PROGRESS_GUIDANCE not in prompt


def test_real_non_game_director_and_writer_prompts_include_selected_trope_only():
    selected_id = "professional_save_the_day"
    unrelated_id = "shenhao_system_spend"
    beat = _urban_trope(selected_id)["beats"][0]
    story = _urban_story_with_trope(selected_id, str(beat))

    seed = build_chapter_seed(story, 1)
    blueprint_ids = {template["id"] for template in seed["simulation_blueprint"]["trope_templates"]}
    plan_prompt = StoryOrchestrator()._plan_prompt(story, 1)
    body_prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "Proof"}})

    assert selected_id in blueprint_ids
    assert unrelated_id in blueprint_ids
    assert seed["trope_contract"]["template_id"] == selected_id
    assert "当前阶段套路" in plan_prompt
    assert selected_id in plan_prompt
    assert str(beat) in plan_prompt
    assert "当前阶段套路" not in body_prompt
    assert selected_id not in body_prompt
    assert str(beat) not in body_prompt
    for prompt in (plan_prompt, body_prompt):
        assert unrelated_id not in prompt
        assert "trope_templates" not in prompt
    assert TROPE_PROGRESS_GUIDANCE not in body_prompt
    assert TROPE_AVOID_GUIDANCE not in body_prompt
    assert OLD_ENGLISH_PROGRESS_GUIDANCE not in body_prompt
    assert OLD_ENGLISH_AVOID_GUIDANCE not in body_prompt


def test_real_non_game_prompts_omit_trope_contract_for_deleted_template_id():
    unrelated_id = "shenhao_system_spend"
    story = _urban_story_with_trope("deleted-template", "missing beat")

    seed = build_chapter_seed(story, 1)
    plan_prompt = StoryOrchestrator()._plan_prompt(story, 1)
    body_prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "Proof"}})

    assert unrelated_id in {template["id"] for template in seed["simulation_blueprint"]["trope_templates"]}
    assert "trope_contract" not in seed
    for prompt in (plan_prompt, body_prompt):
        assert "当前阶段套路" not in prompt
        assert TROPE_PROGRESS_GUIDANCE not in prompt
        assert TROPE_AVOID_GUIDANCE not in prompt
        assert OLD_ENGLISH_PROGRESS_GUIDANCE not in prompt
        assert OLD_ENGLISH_AVOID_GUIDANCE not in prompt
        assert "deleted-template" not in prompt
        assert unrelated_id not in prompt
        assert "trope_templates" not in prompt


def test_real_non_game_prompts_omit_trope_contract_for_invalid_beat():
    selected_id = "professional_save_the_day"
    unrelated_id = "shenhao_system_spend"
    story = _urban_story_with_trope(selected_id, "not a valid trope beat")

    seed = build_chapter_seed(story, 1)
    plan_prompt = StoryOrchestrator()._plan_prompt(story, 1)
    body_prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "Proof"}})

    assert unrelated_id in {template["id"] for template in seed["simulation_blueprint"]["trope_templates"]}
    assert "trope_contract" not in seed
    for prompt in (plan_prompt, body_prompt):
        assert "当前阶段套路" not in prompt
        assert TROPE_PROGRESS_GUIDANCE not in prompt
        assert TROPE_AVOID_GUIDANCE not in prompt
        assert OLD_ENGLISH_PROGRESS_GUIDANCE not in prompt
        assert OLD_ENGLISH_AVOID_GUIDANCE not in prompt
        assert selected_id not in prompt
        assert "not a valid trope beat" not in prompt
        assert unrelated_id not in prompt
        assert "trope_templates" not in prompt


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
    assert "现场素材" not in prompt
    assert "接住：" not in prompt


def test_writer_direction_drops_repeated_and_scaffolding_scene_goals():
    story = StoryState(
        story_id="s-no-scaffold",
        outline="现实都市父子修表故事",
        genre="urban",
        style="",
    )
    chapter_goal = "沈川检查儿子带来的旧表，发现它和商场旧案有关。"
    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {
            "writing_taskbook": {
                "chapter_goal": chapter_goal,
                "scenes": [
                    {"goal": chapter_goal + "两人因此发生争执。"},
                    {"goal": "让阻碍具体出现：清退人员来到铺子。"},
                    {"goal": "主角做选择，兑现一点收益，同时付出可见代价。"},
                ],
            }
        },
    )

    assert prompt.count("沈川检查儿子带来的旧表") == 1
    assert "让阻碍具体出现" not in prompt
    assert "主角做选择" not in prompt


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
    assert "## 网游写法" in prompt
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
    assert "## 网游写法" in prompt
    assert "遇到阻力后付出代价" in prompt
    assert "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子" in prompt
    assert "连续小说正文" in prompt
    assert "分段" not in prompt
    assert "白描" not in prompt
    assert "对话先回应对方刚说的内容" in prompt
    assert "使用完整的现代中文句子" in prompt
    assert "优先写具体动作、物件和后果" in prompt
    assert prompt.index("整章顺序") < prompt.index("## 本章事实")


def test_trade_authorized_first_chapter_prompt_uses_market_then_exchange_order():
    story = StoryState(story_id="s-trade-order", outline="网游开服后匿名处理稀有材料。", genre="网游", style="白描")
    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {
            "governance": {"chapter_intent": {"first_chapter_trade_authorized": True}},
            "event_plan": {"chapter_title": "第一笔到账", "turn": "卖出裂纹狼心，再走官方兑换渠道并付清急账"},
        },
    )

    assert "交易行游戏币成交 -> 官方兑换 -> 现实账户到账 -> 处理急账" in prompt
    assert "担保交易" not in prompt
    assert "第一章只完成开服现场、建号、低级验证和下一步决定" not in prompt


def test_formal_prompts_normalize_legacy_plan_review_and_source_body_without_changing_amounts():
    legacy_trade = "\u62c5\u4fdd\u4ea4\u6613"
    legacy_delivery = "\u5c01\u5b58\u4ea4\u5272"
    legacy_appraisal = "\u63d0\u4ea4\u9274\u5b9a"
    forbidden_currency = "\u4eba\u6c11\u5e01"
    story = StoryState(
        story_id="s-legacy-prompt",
        outline=f"第一章通过裂纹狼心{legacy_trade}解决现实急账。",
        genre="网游",
        style="升级流",
        author_constraints=[f"第一章必须通过裂纹狼心{legacy_trade}解决现实急账。"],
    )
    plan = {"event_plan": {"turn": f"完成{legacy_trade}并处理急账"}}
    review = {"issues": [f"补足裂纹狼心{legacy_appraisal}"], "revision_plan": [f"删除{legacy_delivery}"]}
    source_body = f"裂纹狼心{legacy_appraisal}后{legacy_delivery}，到账1764.00{forbidden_currency}。"
    orchestrator = StoryOrchestrator()

    prompts = (
        orchestrator._plan_prompt(story, 1),
        orchestrator._body_prompt(story, 1, plan),
        orchestrator._revision_prompt(story, 1, source_body, plan, review),
    )

    for prompt in prompts:
        assert all(term not in prompt for term in (legacy_trade, legacy_delivery, legacy_appraisal, forbidden_currency))
        assert "交易行" in prompt
        assert "官方兑换" in prompt
        assert "现实账户" in prompt
        assert "处理急账" in prompt
    assert "1764.00元" in prompts[-1]


def test_each_formal_prompt_uses_its_single_normalization_owner(monkeypatch):
    story = StoryState(
        story_id="s-single-migration-exit",
        outline="第一章通过裂纹狼心担保交易解决现实急账。",
        genre="网游",
        style="升级流",
    )
    plan = {"event_plan": {"turn": "裂纹狼心通过担保平台成交"}}
    review = {"issues": ["裂纹狼心提交鉴定"]}
    original = normalize_legacy_economy_prompt_value
    director_calls: list[tuple[bool, int]] = []
    revision_calls: list[tuple[bool, int]] = []
    writer_calls: list[tuple[bool, int]] = []

    def track_director(value, *, game_context, chapter_number):
        director_calls.append((game_context, chapter_number))
        return original(value, game_context=game_context, chapter_number=chapter_number)

    def track_writer(value, *, game_context, chapter_number):
        writer_calls.append((game_context, chapter_number))
        return original(value, game_context=game_context, chapter_number=chapter_number)

    def track_revision(value, *, game_context, chapter_number):
        revision_calls.append((game_context, chapter_number))
        return original(value, game_context=game_context, chapter_number=chapter_number)

    monkeypatch.setattr(game_director_module, "normalize_legacy_economy_prompt_value", track_director)
    monkeypatch.setattr(game_revision_module, "normalize_legacy_economy_prompt_value", track_revision)
    monkeypatch.setattr(game_writer_module, "normalize_legacy_economy_prompt_value", track_writer)
    orchestrator = StoryOrchestrator()

    assert not hasattr(orchestrator_module, "normalize_legacy_economy_prompt_value")

    for build, expected_director_calls, expected_writer_calls, expected_revision_calls in (
        (lambda: orchestrator._plan_prompt(story, 1), [(True, 1)], [], []),
        (lambda: orchestrator._body_prompt(story, 1, plan), [], [(True, 1)], []),
        (
            lambda: orchestrator._revision_prompt(story, 1, "裂纹狼心担保交易。", plan, review),
            [],
            [],
            [(True, 1)],
        ),
    ):
        director_calls.clear()
        writer_calls.clear()
        revision_calls.clear()
        build()
        assert director_calls == expected_director_calls
        assert writer_calls == expected_writer_calls
        assert revision_calls == expected_revision_calls


def test_revision_prompt_migrates_real_order_status_appraisal_sentence() -> None:
    story = StoryState(
        story_id="s-real-order-appraisal",
        outline="第一章在交易行卖出裂纹狼心，再走官方兑换渠道解决现实急账。",
        genre="网游",
        style="升级流",
    )
    source_body = "裂纹狼心从背包中消失，订单状态变成‘鉴定中’。"

    plan = {
        "governance": {"chapter_intent": {"first_chapter_trade_authorized": True}},
        "event_plan": {"turn": story.outline},
    }
    prompt = StoryOrchestrator()._revision_prompt(story, 1, source_body, plan, {})

    assert "鉴定中" not in prompt
    assert "求购单显示已成交" in prompt
    assert "订单状态变成" not in prompt


def test_real_chapter_one_revision_prompt_uses_natural_local_trade_migration() -> None:
    worktree_root = Path(__file__).resolve().parents[2]
    candidates = (
        worktree_root / "data" / "exported-projects" / "p-gou-webgame-restored",
        worktree_root.parent.parent / "data" / "exported-projects" / "p-gou-webgame-restored",
    )
    project_root = next((candidate for candidate in candidates if candidate.exists()), None)
    if project_root is None:
        pytest.skip("real p-gou-webgame-restored fixture is unavailable")
    chapter_path = next((project_root / "chapters").glob("0001-*.md"), None)
    if chapter_path is None:
        pytest.skip("real chapter one fixture is unavailable")

    source_body = chapter_path.read_text(encoding="utf-8")
    if not any(
        marker in source_body
        for marker in ("担保净到账", "订单状态变成鉴定中", "匿名担保交易已完成")
    ):
        pytest.skip("real chapter fixture already uses the current market/exchange flow")
    story = StoryState(
        story_id="s-real-chapter-one-migration",
        outline="第一章在交易行卖出裂纹狼心，再走官方兑换渠道解决现实急账。",
        genre="网游",
        style="升级流",
    )

    plan = {
        "governance": {"chapter_intent": {"first_chapter_trade_authorized": True}},
        "event_plan": {"turn": story.outline},
    }
    prompt = StoryOrchestrator()._revision_prompt(story, 1, source_body, plan, {})

    assert "夜烬点下立即出售" in prompt
    assert "求购单显示已成交" in prompt
    assert "订单状态变成" not in prompt
    assert "匿名提交" not in prompt
    assert "鉴定中" not in prompt
    source_section = prompt.split("## 原正文", 1)[1]
    local_steps = (
        "夜烬点下立即出售",
        "求购单显示已成交",
        "游戏币已进入钱包",
        "他随后打开独立的官方兑换页面",
        "现实账户到账1764.00元",
    )
    assert [source_section.index(step) for step in local_steps] == sorted(
        source_section.index(step) for step in local_steps
    )
    assert "求购单已成交，官方兑换完成" not in source_section
    for line in opening_market_exchange_flow_lines():
        assert prompt.count(line) == 1


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


def test_writer_system_prompt_is_genre_neutral():
    prompt = StoryOrchestrator._model_system_prompt(False, agent="writer")

    assert "只输出正在发生的小说正文" in prompt
    assert "不解释创作规则" in prompt
    for game_term in ("面板", "任务", "NPC"):
        assert game_term not in prompt


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

    assert "使用完整的现代中文句子" in prompt
    assert "每个场景结束时发生看得见的变化" in prompt
    assert "段落形态：禁止" not in prompt
    assert "后台术语和事实矛盾词不得进正文" not in prompt
    assert prompt.count("不要") <= 8
    assert prompt.count("禁止") <= 2
    assert prompt.count("不得") <= 2


def test_body_prompt_loads_only_enabled_skill_purposes(monkeypatch):
    from packages.story_core.genre_stages import common_writer as common_writer_module

    monkeypatch.setattr(
        common_writer_module,
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


def test_writer_skill_rules_are_deduplicated_and_use_full_instructions():
    from packages.story_core.genre_stages.common_writer import _writer_skill_lines, writer_skill_trace

    module = {
        "module_id": "dialogue",
        "instructions": "先明确说话双方和场景，再让对白回应前一句；把必要的原因和决定说完整。",
        "summary": "这是一段不完整的摘要",
    }
    context = {
        "dialogue": [{"skill_id": "local-pack", "name": "Local Pack", "modules": [module]}],
        "continuity": [{"skill_id": "local-pack", "name": "Local Pack", "modules": [module.copy()]}],
    }

    lines = _writer_skill_lines(context)

    assert len(lines) == 1
    assert "把必要的原因和决定说完整" in lines[0]
    assert len(writer_skill_trace(context)) == 1


def test_short_speech_marker_keeps_reticence_without_forcing_clipped_dialogue():
    from packages.story_core.character_profiles import normalize_speech_style_for_writing

    speech = normalize_speech_style_for_writing("平时话少，短句偏多，但会把当下决定说清楚。")

    assert "平时话少" in speech
    assert "必要的对象、原因和决定要说完整" in speech
    assert "短句偏多" not in speech


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
    assert "现场素材" not in prompt


def test_body_prompt_keeps_normal_chinese_connectors_available():
    story = StoryState(story_id="s-connectors", outline="外门守炉", genre="xianxia", style="白描")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "守炉"}})

    assert "禁用‘但是’" not in prompt
    assert "禁用‘虽然’" not in prompt
    assert "使用完整的现代中文句子" in prompt
    assert "不把判断压成逗号清单" in prompt
    assert "把必要的原因、条件和结果说清楚" in prompt


def test_web_game_second_chapter_does_not_inherit_first_chapter_service_bans():
    story = StoryState(story_id="s-ch2-method", outline="网游开服，千倍爆率。", genre="网游", style="番茄升级流")
    prompt = StoryOrchestrator()._body_prompt(story, 2, {"event_plan": {"chapter_title": "清道夫柜台"}})

    assert "## 网游写法" in prompt
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
        {
            "review_result": {
                "schema_version": "review-result/v2",
                "status": "blocked",
                "issues": [
                    {
                        "code": "dialogue.too_short",
                        "category": "hard",
                        "blocking": True,
                        "message": "对话太短。",
                        "suggestion": "补成完整来回。",
                    }
                ],
            }
        },
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


def test_revision_prompt_reuses_plan_chapter_seed_when_build_seed_drifts(monkeypatch):
    locked_contract = {
        "template_id": "locked-contract",
        "name": "Locked Contract",
        "trigger": "locked trigger",
        "current_beat": "locked beat",
        "payoff": "locked payoff",
        "avoid": ["locked avoid"],
    }
    drift_contract = {
        "template_id": "drift-contract",
        "name": "Drift Contract",
        "trigger": "drift trigger",
        "current_beat": "drift beat",
        "payoff": "drift payoff",
        "avoid": ["drift avoid"],
    }
    monkeypatch.setattr(
        "packages.story_core.orchestrator.build_chapter_seed",
        lambda story, chapter_number: {
            "chapter_number": chapter_number,
            "trope_contract": drift_contract,
        },
    )
    story = StoryState(story_id="s-revision-seed-lock", outline="urban pressure", genre="urban", style="plain")

    prompt = StoryOrchestrator()._revision_prompt(
        story,
        1,
        "old body",
        {
            "event_plan": {"chapter_title": "Proof"},
            "chapter_seed": {
                "chapter_number": 1,
                "trope_contract": locked_contract,
            },
        },
        {
            "review_result": {
                "schema_version": "review-result/v2",
                "status": "blocked",
                "issues": [
                    {
                        "code": "trope.beat_miss",
                        "category": "hard",
                        "blocking": True,
                        "message": "套路节点未兑现：本章未写出当前节点「locked beat」的正文动作或反馈。",
                        "suggestion": "按套路节点改：本章必须兑现「locked beat」，并落到回报「locked payoff」。",
                    }
                ],
            },
            "plot_spine_review": {"diagnostics": {"trope_avoid": ["locked avoid"]}},
        },
    )

    assert "locked-contract" not in prompt
    assert "locked beat" in prompt
    assert "locked avoid" in prompt
    assert "drift-contract" not in prompt
    assert "drift beat" not in prompt
    assert "drift avoid" not in prompt


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


def test_writer_prompt_keeps_director_scene_actions_instead_of_only_scene_goals():
    story = StoryState(
        story_id="s-director-scenes",
        outline="林照进入祖祠查账。",
        genre="玄幻",
        style="",
        characters=[CharacterState(name="林照", role="protagonist")],
    )
    plan = {
        "event_plan": {
            "chapter_title": "祖祠旧账",
            "chapter_satisfaction": {
                "obstacle": "侧门被锁",
                "state_change": "林照拿到账册",
                "next_hook": "账册少了三个名字",
            },
        },
        "scene_cards": [
            {
                "scene_id": "s1-director",
                "location": "祖祠侧门",
                "pov": "林照",
                "purpose": "进入账房",
                "conflict": "赵管事提前换锁",
                "must_show": ["林照拿旧工牌追问换锁时间", "守门人说钥匙送进了内院"],
                "ending_pressure": "林照必须混进送香队伍",
            },
            {
                "scene_id": "s2-director",
                "location": "祖祠内院",
                "pov": "林照",
                "purpose": "拿到钥匙",
                "conflict": "保管人不肯交钥匙",
                "must_show": ["林照要求当面核对换锁记录"],
                "ending_pressure": "账房门终于打开",
            },
            {
                "scene_id": "s3-director",
                "location": "祖祠账房",
                "pov": "林照",
                "purpose": "核对账册",
                "conflict": "其中一页被撕掉",
                "must_show": ["林照对照页码发现三个名字消失"],
                "ending_pressure": "线索指向内院库房",
            },
        ],
    }

    prompt = StoryOrchestrator()._body_prompt(story, 3, plan)

    assert "林照拿旧工牌追问换锁时间" in prompt
    assert "守门人说钥匙送进了内院" in prompt
    assert "账房门终于打开" in prompt


def test_revision_prompt_only_includes_blocking_suggestions():
    from packages.story_core.genre_stages.common_revision import (
        RevisionContext,
        render_common_revision_prompt,
    )

    story = StoryState(
        story_id="s-revision-prompt-boundary",
        outline="林照看守断香炉。",
        genre="xianxia",
        style="白描",
    )
    review = {
        "manual_instructions": ["保留断香炉位置。"],
        "review_result": {
            "schema_version": "review-result/v2",
            "status": "blocked",
            "pass": False,
            "has_hard_errors": True,
            "needs_revision": True,
            "issues": [
                {
                    "code": "continuity.timeline",
                    "category": "hard",
                    "blocking": True,
                    "message": "时间线与上一章冲突。",
                    "suggestion": "修复时间线",
                },
                {
                    "code": "style.ai_flavor",
                    "category": "ai_flavor",
                    "blocking": False,
                    "message": "报告腔建议。",
                    "suggestion": "改成动作",
                },
            ],
            "diagnostics": {
                "soft": "报告腔建议",
                "reader_agent_review": "old agent payload",
                "scores": {"something": 5},
            },
        },
    }
    context = RevisionContext(
        story=story,
        chapter_number=2,
        body="林照检查断香炉。",
        plan={"event_plan": {}},
        review=review,
        writer_context=None,
    )
    prompt = render_common_revision_prompt(
        context=context,
        base_prompt="writer-prompt-base",
        fact_lock="时间线硬规则：事件时间需一致。",
    )
    assert "修复时间线" in prompt
    assert "报告腔建议" not in prompt
    assert "reader_agent_review" not in prompt
    assert "scores" not in prompt
    assert "保留断香炉位置" in prompt


def test_revision_prompt_limits_to_three_blocking_suggestions():
    from packages.story_core.genre_stages.common_revision import (
        RevisionContext,
        render_common_revision_prompt,
    )

    story = StoryState(
        story_id="s-revision-three-blockers",
        outline="outline",
        genre="xianxia",
        style="白描",
    )
    review = {
        "review_result": {
            "schema_version": "review-result/v2",
            "status": "blocked",
            "issues": [
                {
                    "code": f"hard.{i}",
                    "category": "hard",
                    "blocking": True,
                    "message": f"问题{i}",
                    "suggestion": f"修复{i}",
                }
                for i in range(5)
            ],
        },
    }
    context = RevisionContext(
        story=story,
        chapter_number=1,
        body="正文",
        plan={},
        review=review,
        writer_context=None,
    )
    prompt = render_common_revision_prompt(
        context=context,
        base_prompt="base",
    )
    assert "修复0" in prompt
    assert "修复1" in prompt
    assert "修复2" in prompt
    assert "修复3" not in prompt
    assert "修复4" not in prompt


