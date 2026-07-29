from packages.story_core.agent_base import compact_list
import packages.story_core.orchestrator as orchestrator_module
from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.models import NovelProject
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import (
    _apply_ledger_updates,
    _extract_economy_anchors,
    _extract_equipment_ledger_updates,
    _extract_system_anchors,
    _merge_writing_review_quality,
    _limit_metaphor_markers,
    _normalize_chapter_summary,
    _normalize_moves,
    _normalize_web_game_terms,
    _review_chapter_body,
    _sanitize_chapter_output,
    _expanded_body_is_acceptable,
    _compressed_body_is_acceptable,
    _compressed_body_is_progress,
    _compression_candidate_action,
    _chapter_body_is_hard_length_acceptable,
    _rebalanced_body_is_acceptable,
    _repair_outline_amount_anchors,
    _should_extract_final_memory,
    _should_run_full_revision,
    _compact_first_chapter_scene_cards,
    _compression_review_not_worse,
    _should_expand_chapter,
)
from packages.story_core.prose_rule_review import review_critical_prose_rules, review_emotion_quota, review_paragraph_form
from packages.story_core.simplified_review import build_simplified_review
from packages.story_core.world_enrichment import _merge_enrichment


def test_compact_list_treats_single_string_as_one_item():
    assert compact_list("混沌之种已经完成首次验证。", max_items=5) == ["混沌之种已经完成首次验证。"]


def test_chapter_review_passes_explicit_genre_context_to_shared_reviewers(monkeypatch):
    captured = {}

    def fake_style(body, *, genre_context=None):
        captured["style"] = genre_context
        return {"pass": True, "scores": {}, "issues": [], "revision_plan": []}

    def fake_consistency(body, **kwargs):
        captured["consistency"] = kwargs.get("genre_context")
        return {
            "pass": True,
            "scores": {},
            "issues": [],
            "revision_plan": [],
            "scene_contract_failures": [],
        }

    monkeypatch.setattr(orchestrator_module, "review_prose_style", fake_style)
    monkeypatch.setattr(orchestrator_module, "review_world_event_consistency", fake_consistency)

    _review_chapter_body(
        1,
        "plain body",
        {},
        [],
        genre_context={"genre": "xuanhuan"},
    )

    assert captured == {
        "style": {"genre": "xuanhuan"},
        "consistency": {"genre": "xuanhuan"},
    }


def test_chapter_review_preserves_nested_reports_to_repair_aggregate_plan_shift(monkeypatch):
    body = "网游正文"
    local_issue_a = (
        f"章节字数偏少：当前约{len(body)}字，"
        f"番茄长篇建议至少{orchestrator_module._chapter_review_min_chars({})}字。"
    )
    issue_b = "设定冲突：issue B"
    calls = {"web_game": 0, "consistency": 0, "style": 0}

    def empty_review(*_args, **_kwargs):
        return {"pass": True, "scores": {}, "issues": [], "revision_plan": []}

    def web_game_review(*_args, **_kwargs):
        calls["web_game"] += 1
        return {
            "pass": False,
            "scores": {},
            "issues": [local_issue_a],
            "revision_plan": ["web-extra-plan-for-A"],
        }

    def consistency_review(*_args, **_kwargs):
        calls["consistency"] += 1
        return {
            "pass": False,
            "scores": {},
            "issues": [issue_b],
            "revision_plan": ["fix-B"],
            "scene_contract_failures": [],
        }

    def style_review(*_args, **_kwargs):
        calls["style"] += 1
        return {"pass": True, "scores": {}, "issues": [], "revision_plan": []}

    monkeypatch.setattr(orchestrator_module, "review_web_game_chapter", web_game_review)
    monkeypatch.setattr(orchestrator_module, "review_world_event_consistency", consistency_review)
    monkeypatch.setattr(orchestrator_module, "review_prose_style", style_review)
    for name in (
        "review_prose_quality",
        "review_adversarial_cuts",
        "review_ai_flavor",
        "review_reader_feel",
        "review_cold_reader_experience",
            "review_plot_spine_completion",
            "review_progression_lead",
            "review_critical_prose_rules",
        ):
        monkeypatch.setattr(orchestrator_module, name, empty_review)

    writing_review = _review_chapter_body(
        4,
        body,
        {"world_reactions": ["玩家继续练级。"], "next_focus": "继续推进。"},
        [],
    )
    simplified = build_simplified_review({"writing_review": writing_review})
    issue = next(item for item in simplified["issues"] if item["message"] == issue_b)

    assert issue["suggestion"] == "fix-B"
    assert simplified["revision_plan"][simplified["issues"].index(issue)] == "fix-B"
    assert writing_review["web_game_review"]["revision_plan"] == ["web-extra-plan-for-A"]
    assert writing_review["consistency_review"]["revision_plan"] == ["fix-B"]
    assert writing_review["prose_style_review"] == {
        "pass": True,
        "scores": {},
        "issues": [],
        "revision_plan": [],
    }
    assert calls == {"web_game": 1, "consistency": 1, "style": 1}


def test_quality_merge_propagates_nested_revision_reports():
    writing_review = {
        "pass": False,
        "scores": {},
        "issues": ["设定冲突：issue B"],
        "revision_plan": ["fix-B"],
        "web_game_review": {"issues": ["issue A"], "revision_plan": ["fix-A"]},
        "consistency_review": {"issues": ["设定冲突：issue B"], "revision_plan": ["fix-B"]},
        "prose_style_review": {"issues": [], "revision_plan": []},
    }

    merged = _merge_writing_review_quality({"ok": True, "issues": []}, writing_review)

    for key in ("web_game_review", "consistency_review", "prose_style_review"):
        assert merged[key] is writing_review[key]


def test_chapter_review_enables_economy_checks_for_mixed_game_plugin_context():
    body = "拍卖物成交后，这笔成交款直接进入现实账户。"

    mixed = _review_chapter_body(
        1,
        body,
        {},
        [],
        genre_context={"genre_plugin_ids": ["xuanhuan", "game_webnovel"]},
    )
    non_game = _review_chapter_body(
        1,
        body,
        {},
        [],
        genre_context={"genre_plugin_ids": ["xuanhuan"]},
    )

    assert any("经济边界" in issue for issue in mixed["issues"])
    assert not any("经济边界" in issue for issue in non_game["issues"])


def test_rebalanced_short_draft_can_grow_into_target_range():
    short = "短" * 3300
    candidate = "正文" * 2300

    assert _rebalanced_body_is_acceptable(short, candidate) is True
    assert _rebalanced_body_is_acceptable(short, "正文" * 1500) is False


def test_rebalanced_draft_allows_small_upper_length_tolerance():
    assert _rebalanced_body_is_acceptable("短" * 2700, "新" * 5587) is True


def test_hard_length_fallback_accepts_publishable_draft_outside_preferred_range():
    assert _chapter_body_is_hard_length_acceptable("字" * 3849) is True
    assert _chapter_body_is_hard_length_acceptable("字" * 5640) is True
    assert _chapter_body_is_hard_length_acceptable("字" * 5844) is True
    assert _chapter_body_is_hard_length_acceptable("字" * 2993) is False
    assert _chapter_body_is_hard_length_acceptable("字" * 6001) is False


def test_compression_accepts_small_lower_boundary_tolerance():
    original = "原" * 6500
    candidate = "新" * 4193

    assert _compressed_body_is_acceptable(original, candidate) is True
    assert _compression_candidate_action(original, candidate) == "accept"


def test_locked_outline_amounts_are_repaired_from_structured_anchor():
    body = (
        "苏叶看着账户余额7.40元，戴上头盔。\n\n"
        "交易行求购单成交后，游戏币进入钱包。\n\n"
        "付清房租、宽带和信用卡最低还款后，账户余额100.00元。"
    )
    anchor = {
        "opening_balance": "27.60元",
        "trade_arrival": "1764.00元",
        "ending_balance": "312.60元",
    }

    repaired = _repair_outline_amount_anchors(body, anchor)

    assert "余额27.60元" in repaired
    assert "游戏币进入钱包" in repaired
    assert "现实账户收到1764.00元" in repaired
    assert "余额312.60元" in repaired
    assert "7.40元" not in repaired
    assert "100.00元" not in repaired
    assert repaired.index("交易行求购单成交") < repaired.index("官方兑换页面")
    assert repaired.index("官方兑换页面") < repaired.index("现实账户收到1764.00元")
    assert repaired.index("现实账户收到1764.00元") < repaired.index("付清房租")
    assert repaired.index("付清房租") < repaired.rindex("余额312.60元")


def test_outline_amount_repair_moves_late_arrival_before_urgent_payment() -> None:
    body = (
        "交易行求购单成交，游戏币进入钱包。\n\n"
        "付清现实急账后，账户余额100.00元。\n\n"
        "官方兑换完成，现实账户收到305.20元。"
    )
    anchor = {"trade_arrival": "1764.00元", "ending_balance": "312.60元"}

    repaired = _repair_outline_amount_anchors(body, anchor)

    assert repaired.count("现实账户收到1764.00元") == 1
    assert "305.20元" not in repaired
    assert repaired.index("交易行求购单成交") < repaired.index("官方兑换页面")
    assert repaired.index("官方兑换页面") < repaired.index("现实账户收到1764.00元")
    assert repaired.index("现实账户收到1764.00元") < repaired.index("付清现实急账")
    assert repaired.index("付清现实急账") < repaired.rindex("余额312.60元")
    assert "官方兑换完成" not in repaired


def test_outline_amount_repair_inserts_before_whole_urgency_sentence() -> None:
    body = "交易行求购单成交，游戏币进入钱包。然后他处理急账，准备给房东回消息。"

    repaired = _repair_outline_amount_anchors(body, {"trade_arrival": "1764.00元"})

    assert "然后他处理急账，准备给房东回消息。" in repaired
    assert "然后他\n" not in repaired
    assert repaired.index("现实账户收到1764.00元") < repaired.index("然后他处理急账")


def test_outline_amount_repair_moves_only_late_arrival_phrase_and_keeps_sentence() -> None:
    body = (
        "交易行求购单成交，游戏币进入钱包。他先付清现实急账。"
        "队友发来消息，现实账户收到305.20元，他决定稍后回复。"
    )

    repaired = _repair_outline_amount_anchors(body, {"trade_arrival": "1764.00元"})

    assert "队友发来消息，他决定稍后回复。" in repaired
    assert "队友发来消息" in repaired
    assert "他决定稍后回复" in repaired
    assert repaired.count("现实账户收到1764.00元") == 1
    assert repaired.index("现实账户收到1764.00元") < repaired.index("付清现实急账")


def test_outline_amount_repair_removes_late_duplicate_when_earlier_receipt_exists() -> None:
    body = (
        "现实账户收到305.20元，他随后付清现实急账。"
        "队友发来消息，实际到账300.00元，他决定稍后回复。"
    )

    repaired = _repair_outline_amount_anchors(body, {"trade_arrival": "1764.00元"})

    assert repaired.count("1764.00元") == 1
    assert "队友发来消息，他决定稍后回复。" in repaired
    assert "官方兑换页面" not in repaired


def test_outline_amount_repair_removes_independent_late_receipt_period_cleanly() -> None:
    body = "他先付清现实急账。现实账户收到305.20元。队友随后发来消息。"

    repaired = _repair_outline_amount_anchors(body, {"trade_arrival": "1764.00元"})

    assert "队友随后发来消息。" in repaired
    assert "。。" not in repaired
    assert repaired.count("现实账户收到1764.00元") == 1


def test_outline_amount_repair_removes_independent_late_receipt_exclamation_cleanly() -> None:
    body = "他先付清现实急账。手机提示进账305.20元！队友随后发来消息。"

    repaired = _repair_outline_amount_anchors(body, {"trade_arrival": "1764.00元"})

    assert "队友随后发来消息。" in repaired
    assert "。！" not in repaired
    assert repaired.count("现实账户收到1764.00元") == 1


def test_outline_amount_repair_updates_expected_and_actual_arrival_amounts() -> None:
    body = "页面显示预计到账1700.00元，确认兑换后实际到账1690.00元。"

    repaired = _repair_outline_amount_anchors(body, {"trade_arrival": "1764.00元"})

    assert "预计到账1764.00元" in repaired
    assert "实际到账1764.00元" in repaired
    assert "1700.00元" not in repaired
    assert "1690.00元" not in repaired


def test_outline_amount_repair_recognizes_mobile_credit_without_duplicate_exchange() -> None:
    body = "手机提示进账305.20元，他看了一眼就去付清现实急账。"

    repaired = _repair_outline_amount_anchors(body, {"trade_arrival": "1764.00元"})

    assert "手机提示进账1764.00元" in repaired
    assert "官方兑换页面" not in repaired
    assert repaired.count("1764.00元") == 1


def test_outline_amount_repair_does_not_insert_exchange_before_opening_balance() -> None:
    body = "苏叶看着账户余额27.60元。\n\n交易行求购单成交，游戏币进入钱包。"
    anchor = {"opening_balance": "27.60元", "trade_arrival": "1764.00元", "ending_balance": "312.60元"}

    repaired = _repair_outline_amount_anchors(body, anchor)

    assert repaired.index("余额27.60元") < repaired.index("交易行求购单成交")
    assert repaired.index("交易行求购单成交") < repaired.index("官方兑换页面")
    assert repaired.index("现实账户收到1764.00元") < repaired.rindex("余额312.60元")


def test_compact_list_accepts_model_object_instead_of_array():
    assert compact_list({"最高": "先完成担保交易", "其次": "隐藏掉落异常"}, max_items=2) == [
        "先完成担保交易",
        "隐藏掉落异常",
    ]


def test_director_move_priority_accepts_chinese_levels():
    moves = _normalize_moves(
        [
            {"name": "苏叶", "goal": "解决急账", "action": "完成担保交易", "priority": "最高"},
            {"name": "夜烬", "goal": "验证爆率", "action": "击杀灰狼", "priority": "2"},
        ]
    )

    assert [move["priority"] for move in moves] == [3, 2]


def test_director_moves_accept_character_grouped_object():
    moves = _normalize_moves(
        {
            "林照": [{"goal": "查清香火来源", "action": "带周满去祖祠查看香灰", "priority": "高"}],
            "赵管事": {"goal": "压住消息", "action": "提前锁上祖祠侧门", "priority": 2},
        }
    )

    assert [(move["name"], move["action"]) for move in moves] == [
        ("林照", "带周满去祖祠查看香灰"),
        ("赵管事", "提前锁上祖祠侧门"),
    ]


def test_director_moves_accept_grouped_text_actions_skip_blanks_and_limit_to_six():
    moves = _normalize_moves(
        {
            "林照": ["动作1", "   ", "动作2"],
            "赵管事": "动作3",
            "周满": ["动作4", "动作5", "动作6", "动作7"],
        },
        allow_text_items=True,
    )

    assert [(move["name"], move["action"]) for move in moves] == [
        ("林照", "动作1"),
        ("林照", "动作2"),
        ("赵管事", "动作3"),
        ("周满", "动作4"),
        ("周满", "动作5"),
        ("周满", "动作6"),
    ]


def test_director_moves_use_group_name_for_invalid_names_without_stringifying_null():
    moves = _normalize_moves(
        {
            "林照": [
                {"name": None, "action": "检查香灰"},
                {"name": "   ", "action": "追问守祠人"},
                {"name": "周满", "action": "查看侧门"},
            ],
            "赵管事": {"action": None},
        }
    )

    assert [move["name"] for move in moves] == ["林照", "林照", "周满", "赵管事"]
    assert moves[-1]["action"] == "继续推进当前主线"
    assert all("None" not in (move["name"], move["action"]) for move in moves)


def test_writer_character_moves_drop_invalid_actions_from_mixed_input():
    moves = _normalize_moves(
        [
            {"name": "林照", "action": "检查香灰"},
            {},
            {"name": "赵管事", "action": None},
            {"name": "周满", "action": "   "},
            None,
        ],
        require_action=True,
        allow_text_items=True,
    )

    assert [(move["name"], move["action"]) for move in moves] == [("林照", "检查香灰")]


def test_expansion_candidate_must_land_inside_target_range():
    original = "原" * 4069

    assert _expanded_body_is_acceptable(original, "新" * 4300) is True
    assert _expanded_body_is_acceptable(original, "新" * 8304) is False
    assert _expanded_body_is_acceptable(original, "新" * 4000) is False


def test_compression_candidate_must_land_inside_target_range():
    original = "原" * 8763

    assert _compressed_body_is_acceptable(original, "新" * 5000) is True
    assert _compressed_body_is_acceptable(original, "新" * 8020) is False
    assert _compressed_body_is_acceptable(original, "新" * 3500) is False


def test_compression_keeps_a_shorter_reviewable_intermediate_draft():
    original = "原" * 9937

    assert _compressed_body_is_progress(original, "新" * 6235) is True
    assert _compressed_body_is_progress(original, "新" * 10000) is False
    assert _compressed_body_is_progress(original, "新" * 3500) is False


def test_compression_retries_when_model_overcompresses():
    assert _compression_candidate_action("原" * 6104, "新" * 4321) == "accept"
    assert _compression_candidate_action("原" * 9937, "新" * 6235) == "continue"
    assert _compression_candidate_action("原" * 6104, "新" * 2632) == "retry"
    assert _compression_candidate_action("原" * 6104, "新" * 6200) == "reject"


def test_final_memory_runs_only_for_a_reviewable_in_range_body():
    assert _should_extract_final_memory("正文" * 2300, {"needs_revision": False}) is True
    assert _should_extract_final_memory("正文" * 3001, {"needs_revision": False}) is False
    assert _should_extract_final_memory("正文" * 2751 + "字", {"needs_revision": False}) is True
    assert _should_extract_final_memory("正文" * 2300, {"needs_revision": True}) is False


def test_final_memory_accepts_advisory_review_but_rejects_hard_errors():
    body = "正文" * 2300

    assert _should_extract_final_memory(
        body,
        {"needs_revision": True, "has_hard_errors": False},
    ) is True
    assert _should_extract_final_memory(
        body,
        {"needs_revision": True, "has_hard_errors": True},
    ) is False


def test_full_revision_only_runs_for_hard_errors():
    assert _should_run_full_revision({"needs_revision": True, "has_hard_errors": False}) is False
    assert _should_run_full_revision({"needs_revision": True, "has_hard_errors": True}) is True


def test_planning_meta_leak_critical_report_triggers_full_revision_gate():
    critical_report = review_critical_prose_rules("周满说完，迈出前置条件。")
    gate = build_simplified_review({"writing_review": {"critical_review": critical_report}})

    assert critical_report["severity_summary"]["has_hard_violation"] is True
    assert gate["has_hard_errors"] is True
    assert _should_run_full_revision(gate) is True


def test_compression_review_must_not_add_hard_or_total_issues():
    before = {
        "issues": ["第一章缺少带身份栏的角色面板。", "段首主语重复。"],
    }
    improved = {"issues": ["段首主语重复。"]}
    worsened = {
        "issues": [
            "第一章缺少带身份栏的角色面板。",
            "首次正式交战前缺少简洁怪物面板。",
            "段首主语重复。",
        ]
    }

    assert _compression_review_not_worse(before, improved) is True
    assert _compression_review_not_worse(before, worsened) is False


def test_first_chapter_scene_cards_keep_four_core_scenes_and_drop_variant_numbers():
    cards = [
        {"scene_id": "s0-plot-simulation", "purpose": "后台计划"},
        {"scene_id": "s2-c1-reality-entry", "purpose": "现实入口"},
        {"scene_id": "s3-c1-character-create", "purpose": "建号"},
        {
            "scene_id": "s4-c1-small-verify",
            "purpose": "首次验证",
            "must_show": ["低级怪物", "变体boundary-durability-route：生命46/100、法力0/60、法杖2/10"],
            "ending_pressure": "变体boundary-durability-route：法杖2/10",
            "state_delta": {"simulation": {"variant": "boundary-durability-route"}},
        },
        {"scene_id": "s5-c1-npc-service", "purpose": "可选NPC服务"},
        {"scene_id": "s6-c1-next-step-hook", "purpose": "交易与结尾"},
    ]

    compacted = _compact_first_chapter_scene_cards(cards, chapter_number=1, trade_authorized=True)

    assert [card["scene_id"] for card in compacted] == [
        "s2-c1-reality-entry",
        "s3-c1-character-create",
        "s4-c1-small-verify",
        "s6-c1-next-step-hook",
    ]
    assert "boundary-durability-route" not in str(compacted)
    assert "46/100" not in str(compacted)


def test_metaphor_limiter_never_rewrites_like_into_ungrammatical_gen():
    body = "他像没看见。烟像有人牵着。门外像有人开口。那缕烟像是在提醒他。"

    cleaned = _limit_metaphor_markers(body, max_like=1)

    assert cleaned == body
    assert "跟有人" not in cleaned
    assert "跟是在" not in cleaned


def test_sanitizer_does_not_author_missing_story_content():
    body = (
        "苏叶进入《天启之门》，角色名是夜烬。\n\n"
        "夜烬打倒一只灰狼，收起材料以后回到村口。"
    )
    scene_cards = [
        {"scene_id": "s1-c1-reality-entry", "must_show": ["现实职业/技能来源"]},
        {"scene_id": "s4-c1-npc-service", "must_show": ["NPC地点", "信息边界"]},
    ]

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=scene_cards)

    assert cleaned == body
    assert "底层协议校验通过" not in cleaned
    assert "外包测试员" not in cleaned
    assert "柜台窗口" not in cleaned
    assert "清道夫委托" not in cleaned
    assert "低声说" not in cleaned


def test_sanitizer_preserves_completed_reward_and_payment_events():
    body = "任务完成。系统提示：获得：30铜。随后修理装备，扣除：30铜。"

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[])

    assert cleaned == body
    assert "奖励栏还没亮" not in cleaned
    assert "没有扣费" not in cleaned


def test_first_chapter_sanitizer_leaves_missing_emotion_for_review():
    body = "\n\n".join(
        [
            "苏叶打开《天启之门》，给角色取名夜烬。",
            "夜烬选择元素法师学徒，拿到新手法杖。",
            "夜烬在灰狼坡试打一只灰狼，确认掉落判定×1000。",
            "夜烬看着背包里的灰狼毒腺，决定先不声张。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
    review = review_emotion_quota(cleaned)

    assert review["scores"]["emotion_quota"] < 8
    assert "喉咙发紧" not in cleaned
    assert "掌心全是汗" not in cleaned
    assert "不敢真的松下来" not in cleaned


def test_review_chapter_body_handles_soft_low_scores_without_name_error(monkeypatch):
    def low_ai_flavor(body):
        return {
            "reviewer": "ai_flavor/v1",
            "pass": False,
            "scores": {"ai_flavor": 5},
            "issues": ["soft low"],
            "revision_plan": [],
        }

    monkeypatch.setattr("packages.story_core.orchestrator.review_ai_flavor", low_ai_flavor)

    review = _review_chapter_body(
        1,
        "《天启之门》开服，夜烬用新手法杖试打一只灰狼，混沌之种提示掉落判定×1000。旁边玩家只当他运气好，他把材料压进背包，下一步准备再刷一轮。",
        {"summary": "夜烬试打灰狼", "next_focus": "再刷一轮"},
        world_facts=["网游开服，夜烬低调验证千倍爆率。"],
    )

    assert "review_summary" in review
    assert review["review_summary"]["soft_passed"] is False


def test_review_without_planned_world_reactions_is_not_failed_for_absence_alone():
    body = "苏叶走进车站，和工作人员问清时间以后买了票。" * 300

    review = _review_chapter_body(
        2,
        body,
        {"next_focus": "到达下一座城市。", "world_reactions": []},
        [],
        {},
        [],
        [],
        genre_context={"genre": "现实题材"},
    )

    assert review["scores"]["world_reaction"] == 8


def test_review_chapter_body_blocks_patchwork_reader_feel(monkeypatch):
    def patchwork_review(body):
        return {
            "reviewer": "reader_feel/v1",
            "pass": False,
            "scores": {"patchwork": 5, "panel_balance": 8},
            "issues": ["段落重复，正文有明显拼补感。"],
            "revision_plan": ["合并重复段落，只保留一次信息。"],
            "metrics": {"near_duplicate_count": 1},
        }

    monkeypatch.setattr("packages.story_core.orchestrator.review_reader_feel", patchwork_review)

    review = _review_chapter_body(
        1,
        "《天启之门》开服，夜烬用新手法杖试打一只灰狼，混沌之种提示掉落判定×1000。旁边玩家只当他运气好，他把材料压进背包，下一步准备再刷一轮。",
        {"summary": "夜烬试打灰狼", "next_focus": "再刷一轮"},
        world_facts=["网游开服，夜烬低调验证千倍爆率。"],
    )

    assert review["pass"] is False
    assert review["scores"]["reader_feel_patchwork"] == 5
    assert review["reader_feel_review"]["metrics"]["near_duplicate_count"] == 1


def test_review_chapter_body_treats_review_exception_as_failure(monkeypatch):
    def broken_web_game_review(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("packages.story_core.orchestrator.review_web_game_chapter", broken_web_game_review)

    review = _review_chapter_body(
        1,
        "《天启之门》开服，夜烬用新手法杖试打一只灰狼，混沌之种提示掉落判定×1000。旁边玩家只当他运气好，他把材料压进背包，下一步准备再刷一轮。",
        {"summary": "夜烬试打灰狼", "next_focus": "再刷一轮"},
        world_facts=["网游开服，夜烬低调验证千倍爆率。"],
    )

    assert review["pass"] is False
    assert any("审稿器web_game异常" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_normalizes_panel_values_and_report_phrase():
    body = (
        "角色面板亮起：ID：夜烬等级：Lv.1经验：0/100生命：100/100法力：20/80"
        "主武器：新手法杖（耐久10/10）基础技能：基础火球术背包：空钱袋：空。\n\n"
        "面板边缘泛着微光，数据很干净。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "法力：60/60" in cleaned
    assert "数据很干净" not in cleaned
    assert "生命：100/100；法力" in cleaned


def test_first_chapter_sanitizer_does_not_add_progression_hook():
    body = "\n\n".join(
        [
            "苏叶进入《天启之门》，游戏ID是夜烬。",
            "夜烬在灰狼坡击杀五只灰狼，背包里多了八份灰狼毒腺。",
            "他把背包关上，准备先回村。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert cleaned == body
    assert "清道夫委托" not in cleaned
    assert "后坡探路" not in cleaned


def test_first_chapter_sanitizer_does_not_rewrite_premature_story_events():
    body = "\n\n".join(
        [
            "夜烬把灰狼毒腺递给窗口，钱袋里多了5枚铜币。",
            "夜烬把法杖递给铁匠，耐久条从6/10跳回9/10，扣掉3铜币。",
            "他走到药剂铺门口，看了一眼价牌。初级蓝药，10铜币一瓶。",
            "技能书残页还差九份。下一步，换技能书。",
            "夜烬回到村口，背包里还有灰狼毒腺八份。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert cleaned == body
    assert "钱袋里多了" in cleaned
    assert "扣掉" in cleaned
    assert "技能书" in cleaned
    assert "清道夫委托" not in cleaned


def test_first_chapter_sanitizer_does_not_truncate_service_overrun():
    body = "\n\n".join(
        [
            "苏叶进入《天启之门》，游戏ID夜烬。夜烬在灰狼坡击杀五只灰狼，背包里有八份灰狼毒腺。",
            "回到村口，登记窗口前的人少了一半。他走过去，把两份毒腺放在柜台上。",
            "NPC说：清道夫委托完成。奖励铜币×50，经验×100。后坡通行木牌也给了他。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert cleaned == body
    assert "清道夫委托完成" in cleaned
    assert "奖励铜币" in cleaned
    assert "后坡通行" in cleaned
    assert "没有伸手接" not in cleaned


def test_first_chapter_review_blocks_premature_rewards_and_services():
    body = (
        "《天启之门》开服，苏叶现实余额27.60元。夜烬完成角色创建，职业元素法师学徒。"
        "角色面板显示：游戏ID夜烬，Lv.1，职业元素法师学徒，经验0/100，生命100/100，法力60/60，钱袋空。"
        "他击杀灰狼后看见千倍爆率，灰狼毒腺掉进背包。"
        "窗口NPC盖章，钱袋里多了5枚铜币。夜烬又把法杖修好，想着下一步换技能书。"
    )

    review = _review_chapter_body(1, body, {}, ["本书设定：夜烬拥有千倍爆率。"], {}, [], [])

    assert review["pass"] is False
    assert any("第一章账本越界" in issue for issue in review["issues"])


def test_first_chapter_review_allows_visible_prices_as_future_goal():
    body = (
        "《天启之门》开服，苏叶现实余额27.60元。夜烬完成角色创建，职业元素法师学徒。"
        "角色面板显示：游戏ID夜烬，Lv.1，职业元素法师学徒，经验0/100，生命100/100，法力60/60，钱袋空。"
        "村口任务牌写着清道夫委托：提交灰狼毒腺十份，奖励三十铜。旁边价牌挂着修理费和基础法力药水价格，"
        "但夜烬没有交材料，也没有买药水，只把背包扣紧。"
        "他击杀五只灰狼后看见千倍爆率，背包里有灰狼毒腺八份和粗糙狼皮七张，还差两份才能提交委托。"
    )

    review = _review_chapter_body(1, body, {}, ["网游"], {}, [], [])

    assert not any("第一章账本越界" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_preserves_price_and_precondition_surface():
    body = (
        "村口任务牌写着清道夫委托：提交灰狼毒腺十份，奖励三十铜。"
        "旁边价牌挂着修理费和基础法力药水价格，但夜烬没有交材料，也没有买药水。"
        "背包里现在只有灰狼毒腺八份，还差两份才能提交委托，后坡探路只是后续前置。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "基础法力药水价格" in cleaned
    assert "灰狼毒腺十份" in cleaned
    assert "奖励三十铜" in cleaned
    assert "还差两份" in cleaned
    assert "后坡探路" in cleaned


def test_first_chapter_sanitizer_does_not_insert_protagonist_speech():
    body = (
        "苏叶进入游戏，角色面板显示职业是元素法师学徒。"
        "任务牌写着清道夫委托需要灰狼毒腺十份。"
        "背包里现在只有灰狼毒腺八份，还差两份。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "夜烬把背包扣上，低声说" not in cleaned
    assert "先不交" not in cleaned


def test_first_chapter_review_allows_negated_arrival_wording():
    body = (
        "《天启之门》开服，苏叶现实余额27.60元。夜烬完成角色创建，职业元素法师学徒。"
        "任务牌写着清道夫委托需要灰狼毒腺十份，奖励三十铜。"
        "夜烬没有交材料，没有到账，也没有把材料挂出去，只把灰狼毒腺八份压进背包。"
    )

    review = _review_chapter_body(1, body, {}, ["网游"], {}, [], [])

    assert not any("第一章提前展开交易线" in issue for issue in review["issues"])


def test_first_chapter_review_honors_project_authorized_trade_payoff():
    body = (
        "《天启之门》开服，苏叶以夜烬的游戏ID进入游戏，并在灰狼坡确认千倍爆率。"
        "裂纹狼心是开服首批稀有心核样本，他通过担保交易完成交割，扣除手续费后到账1764.00元。"
        "苏叶退出游戏，付清房租、宽带和信用卡最低还款，银行卡余额变成312.60元。"
    )
    world_facts = [
        "第一章必须通过裂纹狼心担保交易解决现实急账，到账后余额312.60元。",
    ]

    review = _review_chapter_body(1, body, {}, world_facts, {}, [], [])

    assert not any("第一章提前展开交易" in issue for issue in review["issues"])
    assert not any("边界章目标漂移" in issue for issue in review["issues"])


def test_first_chapter_review_allows_future_repair_plan_without_marking_service_complete():
    body = (
        "《神域》开服，夜烬用基础火球术击杀灰狼，确认千倍爆率。"
        "他没有修理装备，也没有买药。接下来要先修好法杖，再回灰狼坡补齐任务材料。"
    )

    review = _review_chapter_body(1, body, {}, ["网游"], {}, [], [])

    assert not any("第一章账本越界" in issue for issue in review["issues"])


def test_first_chapter_review_allows_price_check_and_unfinished_repair_intent():
    body = (
        "《神域》开服，夜烬用基础火球术击杀灰狼，确认千倍爆率。"
        "药剂铺的价牌写着最低级的法力药水要十二枚铜币，他的钱袋还是空的。"
        "他转向铁匠铺，准备问清修理需要多少铜币，等法杖修好以后再回灰狼坡。"
    )

    review = _review_chapter_body(1, body, {}, ["网游", "第一章允许完成现实交易"], {}, [], [])

    assert not any("第一章账本越界" in issue for issue in review["issues"])


def test_authorized_trade_does_not_treat_item_utility_as_guild_pressure():
    body = (
        "《天启之门》开服，苏叶以夜烬的游戏ID进入游戏，完成角色创建并去灰狼坡刷怪。"
        "裂纹狼心可供公会图鉴收集，也能用于二环解毒剂。夜烬通过平台私聊确认用途，"
        "完成担保交易后到账1764.00元，付清现实急账，余额变成312.60元。"
    )
    world_facts = [
        "第一章必须通过裂纹狼心担保交易解决现实急账，到账后余额312.60元。",
    ]

    review = _review_chapter_body(1, body, {}, world_facts, {}, [], [])

    assert not any("第一章节奏过载" in issue for issue in review["issues"])
    assert not any("第一章外部压力过早" in issue for issue in review["issues"])


def test_authorized_trade_ignores_ambient_chat_other_players_and_negated_forum_pressure():
    body = (
        "《神域》开服，苏叶以夜烬的游戏ID进入游戏，完成角色创建并去灰狼坡刷怪。"
        "广场有人喊‘收铜币，价格私聊’，坡外也有普通玩家三人一组围杀灰狼。"
        "裂纹狼心可供公会图鉴收集，也能用于二环解毒剂。担保交易实际到账1764.00元，"
        "苏叶补上房租并付清信用卡最低还款。之后他没有去论坛搜索，买家也不知道材料来源。"
    )
    world_facts = ["第一章必须通过裂纹狼心担保交易解决现实急账。"]

    review = _review_chapter_body(1, body, {}, world_facts, {}, [], [])

    assert not any("第一章节奏过载" in issue for issue in review["issues"])
    assert not any("第一章外部压力过早" in issue for issue in review["issues"])
    assert not any("第一章冲突越级" in issue for issue in review["issues"])


def test_review_rejects_trade_amount_that_differs_from_outline_anchor():
    body = (
        "夜烬把裂纹狼心交给担保平台，扣除手续费后到账1664元。"
        "苏叶付清现实急账，银行卡余额变成312.60元。"
    )
    event_plan = {
        "chapter_satisfaction": {
            "visible_payoff": "担保交易到账1764.00元，现实余额变为312.60元。",
        }
    }
    world_facts = ["第一章必须通过裂纹狼心担保交易解决现实急账。"]

    review = _review_chapter_body(1, body, event_plan, world_facts, {}, [], [])

    assert any("大纲金额不一致" in issue and "1764.00元" in issue for issue in review["issues"])


def test_review_accepts_equivalent_trade_amount_outside_arrival_phrase():
    body = (
        "担保订单最终成交价1764元，平台随后发来到账通知。"
        "苏叶付清急账，银行卡余额变成312.60元。"
    )
    event_plan = {
        "chapter_satisfaction": {
            "visible_payoff": "担保交易到账1764.00元，现实余额变为312.60元。",
        }
    }
    world_facts = ["第一章必须通过裂纹狼心担保交易解决现实急账。"]

    review = _review_chapter_body(1, body, event_plan, world_facts, {}, [], [])

    assert not any("大纲金额不一致" in issue for issue in review["issues"])


def test_review_rejects_opening_and_ending_balances_that_differ_from_outline():
    body = (
        "苏叶看着账户里的7.40元进入游戏。"
        "担保交易到账1764.00元，付清急账后余额只剩100.00元。"
    )
    world_facts = [
        "第一章必须通过裂纹狼心担保交易解决现实急账。",
        '{"story":"苏叶以最后27.60元进入游戏。"}',
        '{"payoff":"担保交易到账1764.00元，现实余额变为312.60元。"}',
    ]

    review = _review_chapter_body(1, body, {}, world_facts, {}, [], [])

    assert any("开篇余额不一致" in issue and "27.60元" in issue for issue in review["issues"])
    assert any("章末余额不一致" in issue and "312.60元" in issue for issue in review["issues"])


def test_second_chapter_does_not_require_first_chapter_reality_amounts_again():
    review = _review_chapter_body(
        2,
        "夜烬回到灰狼坡补齐任务材料，提交清道夫委托后升到Lv.3。" * 200,
        {
            "chapter_number": 2,
            "goal": "补齐灰狼毒腺并完成任务。",
            "payoff": "升到Lv.3。",
            "next_focus": "接取后坡巡查。",
        },
        [
            (
                "第一章必须解决现实急账：裂纹狼心以2金币一口价匿名拍卖成交取得游戏币，"
                "再经官方兑换实际到账1764.00元，房租和信用卡最低还款已付，余额变为332.60元。"
            ),
        ],
        {},
        [],
        [],
        genre_context={"genre": "网游"},
    )

    assert not any("到账金额" in issue or "章末余额不一致" in issue for issue in review["issues"])


def test_amount_anchor_repair_keeps_distinct_opening_and_ending_when_draft_has_one_balance():
    repaired = _repair_outline_amount_anchors(
        "苏叶看着余额7.40元登录游戏。担保交易到账305.20元。",
        {
            "opening_balance": "27.60元",
            "trade_arrival": "1764.00元",
            "ending_balance": "312.60元",
        },
    )

    assert "余额27.60元" in repaired[:1200]
    assert "1764.00元" in repaired
    assert "余额312.60元" in repaired[-1600:]


def test_amount_anchor_repair_preserves_gross_trade_price_when_arrival_is_net():
    repaired = _repair_outline_amount_anchors(
        "成交价1800.00元，服务费36.00元，预计到账1700.00元。",
        {"trade_arrival": "1764.00元"},
    )

    assert "成交价1800.00元" in repaired
    assert "服务费36.00元" in repaired
    assert "预计到账1764.00元" in repaired


def test_amount_anchor_repair_replaces_chinese_word_balance_without_duplicating_opening():
    repaired = _repair_outline_amount_anchors(
        "苏叶看着银行卡可用余额只剩四十六块八毛三，把手机扣在桌上。",
        {"opening_balance": "46.83元"},
    )

    assert repaired.startswith("苏叶看着银行卡可用余额只剩46.83元")
    assert repaired.count("46.83元") == 1
    assert "苏叶登录游戏前" not in repaired


def test_amount_anchor_repair_normalizes_balance_split_across_sentence_boundary():
    repaired = _repair_outline_amount_anchors(
        "苏叶看了一眼账户余额。46.83元。随后戴上头盔。",
        {"opening_balance": "46.83元"},
    )

    assert "账户余额46.83元" in repaired
    assert repaired.count("46.83元") == 1
    assert "苏叶登录游戏前" not in repaired


def test_amount_anchor_repair_recognizes_bank_account_remaining_without_balance_word():
    repaired = _repair_outline_amount_anchors(
        "他切回余额页面，看见银行卡里只剩四十六块八毛三。",
        {"opening_balance": "46.83元"},
    )

    assert "银行卡里只剩46.83元" in repaired
    assert "苏叶登录游戏前" not in repaired


def test_amount_anchor_repair_replaces_chinese_ending_balance_with_stop_wording():
    repaired = _repair_outline_amount_anchors(
        "银行卡里只剩四十六块八毛三。到账后付清两笔急账，银行卡余额停在三百三十二块六毛。",
        {"opening_balance": "46.83元", "ending_balance": "332.60元"},
    )

    assert "银行卡里只剩46.83元" in repaired
    assert "银行卡余额停在332.60元" in repaired
    assert "付清现实急账后" not in repaired


def test_amount_anchor_repair_replaces_repeated_opening_balance_after_bank_income():
    body = (
        "手机屏幕上，银行余额那一栏只有四个数字。46.83元。\n\n"
        "手机银行通知写着：您尾号账户收入1764.00元。\n\n"
        "他转给房东1200元，又支付信用卡最低还款额278.23元。\n\n"
        "现实账户余额停在46.83元。\n\n"
        "他重新登录游戏。\n\n"
        "他离开交易行，打开独立官方兑换页面。页面显示兑换价、额度、手续费和预计到账；"
        "确认兑换后，现实账户收到1764.00元。\n\n"
        "付清现实急账后，账户余额332.60元。"
    )

    repaired = _repair_outline_amount_anchors(
        body,
        {
            "opening_balance": "46.83元",
            "trade_arrival": "1764.00元",
            "ending_balance": "332.60元",
        },
    )

    assert repaired.count("独立官方兑换页面") == 0
    assert repaired.count("1764.00元") == 1
    assert repaired.count("332.60元") == 1
    assert "现实账户余额停在332.60元" in repaired
    assert "付清现实急账后" not in repaired


def test_review_rejects_ending_balance_shown_before_real_world_payments():
    body = (
        "苏叶登录前看见账户余额46.83元。"
        "担保交易完成，1764.00元到账。手机上立刻显示银行卡余额332.60元。"
        "随后他才把房租转了过去，又确认支付信用卡最低还款。"
        "两笔急账付清后，账户余额332.60元。"
    )
    world_facts = [
        "第一章必须通过裂纹狼心担保交易解决现实急账。",
        '{"story":"苏叶以最后46.83元进入游戏。"}',
        '{"payoff":"担保交易到账1764.00元，现实余额变为332.60元。"}',
    ]

    review = _review_chapter_body(1, body, {}, world_facts, {}, [], [])

    assert any("现实余额出现顺序错误" in issue for issue in review["issues"])


def test_review_rejects_opening_balance_repeated_after_trade_arrival():
    body = (
        "苏叶登录前看见账户余额46.83元。"
        "担保交易完成，1764.00元到账，银行通知随后显示账户余额变成46.83元。"
        "他接着支付房租，又完成信用卡最低还款，最后账户余额332.60元。"
    )
    world_facts = [
        "第一章必须通过裂纹狼心担保交易解决现实急账。",
        "苏叶以最后46.83元进入游戏。",
        "担保交易到账1764.00元，付清急账后现实余额变为332.60元。",
    ]

    review = _review_chapter_body(1, body, {}, world_facts, {}, [], [])

    assert any("到账后余额仍停在登录前金额" in issue for issue in review["issues"])


def test_review_rejects_same_amount_as_gross_price_and_net_arrival_with_fee():
    body = (
        "苏叶登录前看见账户余额46.83元。"
        "成交价1764.00元，服务费36.00元，预计到账1764.00元。"
        "他付清急账后，账户余额332.60元。"
    )
    world_facts = [
        "第一章必须通过裂纹狼心担保交易解决现实急账。",
        '{"story":"苏叶以最后46.83元进入游戏。"}',
        '{"payoff":"担保交易到账1764.00元，现实余额变为332.60元。"}',
    ]

    review = _review_chapter_body(1, body, {}, world_facts, {}, [], [])

    assert any("交易金额流水矛盾" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_merges_overfragmented_paragraphs():
    body = "\n\n".join([f"夜烬看了一眼背包{i}。" for i in range(90)])

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert len([part for part in cleaned.split("\n\n") if part.strip()]) < 90


def test_chapter_sanitizer_compacts_adjacent_system_panels_into_one_block():
    body = (
        "火光散去。\n\n"
        "【击杀灰狼，获得经验22】【等级提升至Lv.2】【获得自由属性点×5】\n\n"
        "夜烬关掉面板。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert cleaned.count("【") == 1
    assert "击杀灰狼，获得经验22；等级提升至Lv.2；获得自由属性点×5" in cleaned


def test_first_chapter_sanitizer_merges_sentence_shards_until_paragraph_form_passes():
    body = "\n\n".join([f"法力栏见底{i}。夜烬退到石头后面。" for i in range(100)])

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
    form_review = review_paragraph_form(cleaned)

    assert form_review["pass"] is True
    assert not any("段落形态过碎" in issue for issue in form_review["issues"])


def test_first_chapter_sanitizer_softens_repeated_state_openers():
    body = "\n\n".join([f"法力栏见底{i}。夜烬退到石头后面。" for i in range(30)])

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
    review = _review_chapter_body(1, cleaned, {}, ["网游"], {}, [], [])

    assert not any("段首主语过度单调" in issue and "法力" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_does_not_add_protocol_anchor():
    body = (
        "苏叶打开登录界面，完成角色创建，游戏ID夜烬。\n\n"
        "第一次击杀灰狼后，背包里多出几份毒腺。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert cleaned == body
    assert "底层协议校验通过" not in cleaned
    assert "混沌之种：未解析" not in cleaned


def test_chapter_summary_string_fields_are_not_split_into_characters():
    summary = _normalize_chapter_summary(
        {
            "summary": "苏叶完成首次小额变现。",
            "facts": "混沌之种已经完成首次验证。",
            "unresolved_threads": "白袍公会是否会继续追查交易行异常？",
            "next_focus": "扩大刷怪收益。",
            "chapter_title": "蛰伏与首金",
        },
        1,
    )

    assert summary["facts"] == ["混沌之种已经完成首次验证。"]
    assert summary["unresolved_threads"] == ["白袍公会是否会继续追查交易行异常？"]


def test_economy_anchors_capture_price_fee_and_balance_for_continuity():
    body = (
        "市场价目前是10-11铜币/个，他定价8铜币。"
        "【确认寄售：灰鼠毒腺 × 49，单价 8铜币】"
        "【扣除手续费 5%，到账铜币：372】"
        "【当前余额：850铜币】"
    )

    anchors = _extract_economy_anchors(body)

    assert any("10-11铜币" in anchor for anchor in anchors)
    assert any("单价 8铜币" in anchor or "定价8铜币" in anchor for anchor in anchors)
    assert any("手续费 5%" in anchor for anchor in anchors)
    assert any("850铜币" in anchor for anchor in anchors)


def test_system_anchors_capture_class_equipment_and_npc_continuity():
    body = (
        "【职业倾向：元素法师（学徒）】夜烬打开武器栏。"
        "【粗糙的学徒法杖】耐久度：62%。"
        "药剂师洛婶在药剂铺柜台后报价，只收未污染毒腺，库存告急但看不到玩家面板。"
    )

    anchors = _extract_system_anchors(body)

    assert any("职业锚点" in anchor and "元素法师" in anchor for anchor in anchors)
    assert any("装备锚点" in anchor and "法杖" in anchor for anchor in anchors)
    assert any("NPC锚点" in anchor and "洛婶" in anchor for anchor in anchors)


def test_ledger_updates_are_mirrored_into_structured_game_ledger():
    story = StoryState(
        story_id="s-ledger",
        outline="网游开服。",
        genre="网游",
        style="升级流",
        progression_ledger={
            "protagonist": {"level": 1, "class_path": "法师学徒"},
            "economy": {"currency": "0金币0银币0铜币"},
            "equipment": {"weapon": "新手法杖", "durability": "正常"},
            "pressure": {},
            "level": 2,
            "exp": "45/200",
            "currency": "0金币21银币0铜币",
            "inventory": ["灰鼠毒腺×0"],
            "guild_attention": 1,
        },
    )

    _apply_ledger_updates(
        story,
        {"protagonist": {"class_path": "元素法师学徒"}, "equipment": {"weapon": "粗糙的学徒法杖", "durability": "62%"}},
    )

    assert story.progression_ledger["protagonist"]["level"] == 2
    assert story.progression_ledger["protagonist"]["exp"] == "45/200"
    assert story.progression_ledger["protagonist"]["class_path"] == "元素法师学徒"
    assert story.progression_ledger["economy"]["currency"] == "0金币21银币0铜币"
    assert story.progression_ledger["equipment"]["weapon"] == "粗糙的学徒法杖"
    assert story.progression_ledger["equipment"]["durability"] == "62%"
    assert story.progression_ledger["pressure"]["guild_attention"] == 1


def test_revised_body_ledger_extraction_captures_current_currency_level_and_exp():
    body = (
        "【当前等级：2。经验：45/200。】"
        "【当前资产：0金币 3银币 50铜币。】"
        "法杖耐久降至86%，短剑只是临时工具。"
    )

    updates = _extract_equipment_ledger_updates(body)

    assert updates["protagonist"]["level"] == 2
    assert updates["protagonist"]["exp"] == "45/200"
    assert updates["economy"]["currency"] == "0金币3银币50铜币"
    assert updates["currency"] == "0金币3银币50铜币"
    assert updates["equipment"]["durability"] == "86%"


def test_revised_body_ledger_uses_latest_balance_surface():
    body = (
        "【角色状态】等级：3 经验：120/400 货币：0金币 4银币 20铜币。"
        "他补给之后再次成交。余额栏跳动：0金币 5银币 8铜币。"
    )

    updates = _extract_equipment_ledger_updates(body)

    assert updates["economy"]["currency"] == "0金币5银币8铜币"
    assert updates["currency"] == "0金币5银币8铜币"


def test_opening_review_rejects_short_fanqie_style_chapter():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他激活混沌之种，确认千倍爆率生效。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
    ) * 20

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
        ["本书设定：夜烬拥有千倍爆率。"],
    )

    assert review["pass"] is False
    assert any("字数偏少" in issue for issue in review["issues"])


def test_quality_report_fails_when_prose_texture_review_fails_even_without_hard_score_drop():
    quality = {"ok": True, "issues": []}
    writing_review = {
        "pass": False,
        "scores": {"web_game_identity_layer": 8, "prose_style_meta_language": 8, "prose_quality_texture": 5},
        "prose_quality_review": {
            "pass": False,
            "overall": 68,
            "issues": [{"type": "mechanical_explanation", "quote": "意味着"}],
        },
        "adversarial_cut_review": {"pass": True, "cuts": []},
    }

    merged = _merge_writing_review_quality(quality, writing_review)

    assert merged["ok"] is False
    assert "writing_review" in merged["issues"]


def test_chapter_body_review_exposes_ai_flavor_critical_review():
    body = (
        "他不是为了多拿一点，而是为了确认这件事是否成立。"
        "这不是一次选择，而是一次边界验证。"
        "风险很清楚，逻辑也很完整。"
        "他需要在可见性和稳定性之间找到答案。"
    ) * 40

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["村口排队变长。"], "next_focus": "继续补材料。"},
    )

    assert "critical_review" in review
    assert "ai_flavor_review" in review
    assert review["critical_review"]["scores"]["ai_flavor"] < 8
    assert review["ai_flavor_review"]["metrics"]["formula_count"] >= 2
    assert any("AI味" in issue or "模型腔" in issue for issue in review["issues"])


def test_sanitizer_removes_ai_formula_and_report_clarity_phrase():
    body = (
        "不是一张皮，也不是一颗毒腺，而是好几份材料挤在一起。"
        "疼痛不重，却很清楚，像被钝刀刮了一下。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
    ai_review = review_ai_flavor(cleaned)

    assert "不是一张皮" not in cleaned
    assert "而是" not in cleaned
    assert "很清楚" not in cleaned
    assert not any("不是X而是Y" in issue for issue in ai_review["issues"])


def test_sanitizer_does_not_turn_name_action_into_dialogue():
    body = "\n\n".join(
        [
            "夜烬说完规则以后，把背包里的毒腺数了一遍。",
            "旁边的人还在问清道夫委托要几份材料。",
            "他没有递材料，也没有领铜币。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert cleaned == body
    assert "低声说" not in cleaned


def test_first_chapter_sanitizer_normalizes_starting_identity_and_stackable_bag():
    body = (
        "角色面板显示：游戏ID夜烬，职业元素法师学徒，Lv.1，背包：15/20。"
        "背包格子一下子亮了好几格，灰狼毒腺×8，粗糙狼皮×7。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "元素法师学徒" not in cleaned
    assert "见习冒险者（未转职）" in cleaned
    assert "背包：15/20" not in cleaned
    assert "背包：2/20" in cleaned
    assert "数量叠在图标角上" in cleaned


def test_first_chapter_sanitizer_keeps_empty_starting_backpack_empty():
    body = "角色面板显示：游戏ID夜烬，身份见习冒险者（未转职），Lv.1，背包：0/20。"

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "背包：0/20" in cleaned
    assert "背包：2/20" not in cleaned


def test_first_chapter_sanitizer_removes_obvious_doubled_weapon_typo():
    body = "夜烬冲上去，用法法杖末端端连砸两下。"

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "用法杖末端连砸两下" in cleaned


def test_chapter_body_review_uses_event_plan_protagonist_names_for_speech_gate():
    body = "苏叶站在柜台前，把背包里的毒腺数了一遍。铁栓看他一眼，继续翻账本。\n\n" * 90

    review = _review_chapter_body(
        1,
        body,
        {
            "ordered_actions": [{"name": "苏叶", "action": "询问仓库寄存"}],
            "world_reactions": ["村口排队变长。"],
            "next_focus": "继续补材料。",
        },
    )

    assert review["critical_review"]["scores"]["protagonist_speech"] < 8
    assert any("主角全章没有可识别的开口对话" in issue for issue in review["issues"])


def test_regeneration_fast_path_skips_whole_chapter_expansion():
    short_body = "夜烬走到柜台前，把背包里的灰狼毒腺数了一遍。" * 120

    assert (
        _should_expand_chapter(
            short_body,
            {
                "simulation_plan": {
                    "simulation_variant": {
                        "id": "boundary-inventory-route",
                        "skip_expansion": True,
                    }
                }
            },
        )
        is False
    )


def test_chapter_body_review_uses_lower_minimum_for_regeneration_fast_path():
    body = "苏叶看着余额，夜烬进村问价，柜台只认铜币和任务牌。" * 150

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["村口排队变长。"], "next_focus": "继续补材料。"},
        simulation_plan={"simulation_variant": {"skip_expansion": True}},
    )

    assert review["scores"]["webnovel_hook"] == 8
    assert not any("字数偏少" in issue for issue in review["issues"])


def test_sanitize_chapter_output_repairs_regeneration_surface_traps():
    body = "\n\n".join(
        [
            "夜烬看着法力满格，继续往前走。",
            "夜烬把灰狼毒腺收进背包。",
            "夜烬没有急着笑。",
            "夜烬回头看了一眼。",
            "夜烬把法杖压低。",
            "夜烬走到柜台前。",
            "夜烬问了一句价格。",
            "夜烬把背包扣上。",
            "夜烬退到门边。",
        ]
    )
    scene_cards = [
        {
            "state_delta": {
                "game_world_simulation": {
                    "systemic_simulation": {"ledger_delta": {"cost_delta": {"mp": -60}}}
                }
            }
        }
    ]

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=scene_cards)

    assert "法力满" not in cleaned
    assert "法力只剩一截" in cleaned
    assert cleaned.count("\n\n夜烬") == body.count("\n\n夜烬")


def test_sanitize_chapter_output_does_not_delete_npcs_or_guild_events():
    body = (
        "夜烬走到仓库管理员铁栓面前，问背包能不能寄存。\n\n"
        "修理匠老葛也把修理价格和耐久规则说了一遍。\n\n"
        "白袍公会很快锁定坐标，知道了他的隐藏天赋。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "铁栓" in cleaned
    assert "老葛" in cleaned
    assert "锁定坐标" in cleaned
    assert "隐藏天赋" in cleaned


def test_opening_review_rejects_1000_times_wording_mixed_with_qianbei():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他激活混沌之种，系统显示1000倍爆率，随后旁白又写千倍爆率。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
    ) * 35

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
        ["本书设定：夜烬拥有千倍爆率。"],
    )

    assert review["pass"] is False
    assert any("千倍爆率写法不统一" in issue for issue in review["issues"])


def test_review_rejects_decimal_game_currency_denominations():
    body = (
        "《天启之门》开服后，夜烬在灰烬村交易行匿名寄售毒腺。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒他别一次砸盘。"
        "交易行提示实际到账：银币0.18，铜币42，余额栏跳动。"
        "白袍公会外围只记录价格、数量批次和时间戳。"
    ) * 35

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"]},
        ["网游币制默认使用 1金币=100银币=10000铜币。"],
    )

    assert review["pass"] is False
    assert any("游戏币显示不应出现小数" in issue for issue in review["issues"])


def test_web_game_term_normalizer_keeps_formula_but_unifies_reader_terms():
    body = "系统显示1000倍爆率，旁白写放大了1000倍，但公式仍是掉落判定×1000。"

    normalized = _normalize_web_game_terms(body)

    assert "1000倍爆率" not in normalized
    assert "放大了1000倍" not in normalized
    assert "千倍爆率" in normalized
    assert "掉落判定×1000" in normalized


def test_opening_review_rejects_overpacked_first_chapter_pacing():
    body = (
        "《天启之门》开服当晚，苏叶登录游戏，旧头盔异常触发混沌之种。"
        "他立刻出村刷怪，灰狼连续掉落狼皮和狼牙。"
        "随后他回村进入交易行，拆单寄售材料。"
        "赵胖子这个商人当场登场试探价格，白袍公会外围也开始追查交易行异常。"
        "苏叶意识到公会、商人、NPC和风控都已经压了过来。"
    ) * 35

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
        ["本书设定：夜烬拥有千倍爆率。"],
    )

    assert review["pass"] is False
    assert any("第一章节奏过载" in issue for issue in review["issues"])


def test_opening_review_allows_world_channel_and_signpost_without_direct_pursuit():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬在灰烬村看见世界频道里白袍、赤焰和星河争抢资源点，但那只是开服生态背景。"
        "他出村小范围刷怪，验证混沌之种和千倍爆率后，回到村口交易行拆单寄售低级材料。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒解毒剂材料缺口大，别一次砸盘。"
        "交易行只留下匿名寄售、手续费、价格、数量批次和时间戳，没有暴露坐标或现实身份。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert "第一章节奏过载：登录、金手指、刷怪、回村交易、商人登场和公会追查被压进同一章。" not in review["issues"]


def test_opening_review_allows_protagonist_pricing_strategy_without_merchant_scene():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬在灰烬村看见世界频道里公会招募和商会收货，那只是开服生态背景。"
        "他出村小范围刷怪，验证混沌之种和千倍爆率后，回到村口交易行拆单寄售低级材料。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒解毒剂材料缺口大，别一次砸盘。"
        "夜烬选择主动压价一铜币走匿名批次，交易行只留下手续费、价格、数量批次和时间戳。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert not any("第一章节奏过载" in issue for issue in review["issues"])


def test_opening_review_allows_negated_coordinate_locking():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬在灰烬村接任务后出村小范围刷怪，验证混沌之种和千倍爆率。"
        "他回到交易行拆单寄售低级材料，药剂师洛婶报价回收狼牙并提醒别一次砸盘。"
        "白袍公会外围只记录价格波动、数量批次和时间戳，没有锁定坐标，也没有锁定身份。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert not any("第一章节奏过载" in issue for issue in review["issues"])
    assert not any("暴露坐标/身份" in issue for issue in review["issues"])


def test_opening_review_allows_resource_point_clearance_as_world_ecology():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬进入灰烬村，世界频道里白袍公会提醒黑水沼泽东侧清场，赤焰和星河在频道里吵资源点。"
        "他在低密度灰鼠坡小范围刷怪，验证混沌之种和千倍爆率后，回到交易行拆单寄售。"
        "药剂师洛婶报价回收毒腺，提醒低级材料不要砸盘。"
        "交易行只留下匿名流水、手续费、价格、数量批次和时间戳，没有坐标或现实身份。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录时间戳。"], "next_focus": "下一次验证。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert not any("第一章节奏过载" in issue for issue in review["issues"])


def test_second_chapter_rejects_rushing_element_corridor_completion():
    body = (
        "夜烬打开角色面板，等级1，经验30/100，职业：元素法师学徒，货币15铜币。"
        "他在灰烬村交易行分批寄售毒腺，药剂师洛婶提醒元素回廊前置需要材料。"
        "白袍公会外围只记录价格、数量批次和时间戳，没有锁定坐标或现实身份。"
        "夜烬随后去了职业导师艾伦面前，系统提示：元素回廊前置材料已提交，进度：10/10。"
        "【系统提示】任务完成。等级提升！当前等级：2。"
    ) * 30

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第2章必须承接第一章账本：夜烬等级1、经验30/100、职业元素法师学徒、货币15铜、库存毒腺×8狼皮×5。"],
    )

    assert review["pass"] is False
    assert any("第二章推进过快" in issue for issue in review["issues"])


def test_second_chapter_rejects_level_one_transfer_or_trial_start():
    body = (
        "夜烬打开角色面板，等级：Lv.1，经验40/100，职业：元素法师学徒。"
        "他拿着清道夫委托奖励去了法师塔，职业导师艾伦让他开始转职任务。"
        "系统提示：职业试炼已开启，进入元素试炼区域。"
        "短发玩家还在村口排队，夜烬已经踏进法师塔一层。"
    ) * 35

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["普通玩家还在排队。"], "next_focus": "继续任务。"},
        ["第2章必须承接第一章账本：夜烬仍是Lv.1，只能推进新手村任务。"],
    )

    assert review["pass"] is False
    assert any("Lv.1越级" in issue for issue in review["issues"])


def test_later_low_level_chapter_rejects_transfer_or_trial_start():
    body = (
        "夜烬打开角色面板，当前等级：4，经验210/500，职业：元素法师学徒。"
        "他刚从后坡交完一轮材料，就被职业导师艾伦叫进法师塔。"
        "系统提示：职业试炼已开启，进入元素试炼区域。"
        "旁边玩家还在排队修装备，他已经开始转职任务。"
    ) * 35

    review = _review_chapter_body(
        6,
        body,
        {"world_reactions": ["普通玩家还在新手村刷材料。"], "next_focus": "继续任务。"},
        ["第6章账本：夜烬等级4，仍在新手村低级地图推进，10级前不能正式接取转职任务或职业试炼。"],
    )

    assert review["pass"] is False
    assert any("低等级越级" in issue for issue in review["issues"])


def test_game_review_rejects_unexplained_full_exp_without_level_up():
    body = (
        "夜烬打开角色面板，等级：Lv.1，职业：元素法师学徒，经验：100/100（未升级），钱袋：5铜。"
        "他站在灰狼坡入口，旁边玩家还在交清道夫委托，洛婶只按十份毒腺验材料。"
        "他点开面板，经验条卡在100/100，没跳，只好继续往坡上走。"
    ) * 35

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["普通玩家还在新手村排队。"], "next_focus": "继续凑技能书钱。"},
        ["第2章必须承接第一章账本：夜烬仍是Lv.1元素法师学徒。"],
    )

    assert review["pass"] is False
    assert any("经验账本不清" in issue for issue in review["issues"])


def test_game_review_rejects_task_submission_contradiction():
    body = (
        "夜烬打开角色面板，等级：Lv.1，职业：元素法师学徒，经验：15/100，钱袋：空。"
        "他心里记着清道夫委托也没有提交，先绕到柜台前看价牌。"
        "洛婶验完十份灰狼毒腺，提示跳出：清道夫委托完成，奖励三十铜。"
    ) * 35

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["旁人只当他普通排队。"], "next_focus": "凑技能书钱。"},
        ["网游新手村开局，夜烬选择元素法师学徒。"],
    )

    assert review["pass"] is False
    assert any("任务账本自相矛盾" in issue for issue in review["issues"])


def test_game_review_rejects_repeated_newbie_task_loop():
    body = (
        "夜烬回村，村口的任务牌前排着队。洛婶验完材料，提示跳出：清道夫委托完成，奖励三十铜。"
        "他又回到灰狼坡刷怪，蓝条见底后再次回村，任务牌前的人少了一些。"
        "洛婶又验十份毒腺，提示跳出：清道夫委托完成，奖励三十铜。"
        "他第三次站到任务牌前，旁边玩家还在抱怨毒腺难出。"
    ) * 25

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["散人只看见他排队交任务。"], "next_focus": "继续刷怪。"},
        ["第2章仍在灰狼坡和灰烬村。"],
    )

    assert review["pass"] is False
    assert any("新手章流程重复" in issue for issue in review["issues"])


def test_game_world_enrichment_seeds_core_character_profiles():
    project = NovelProject(
        project_id="p-character-profiles",
        title="苟在网游里成神",
        seed_outline="网游开服，主角靠千倍爆率低调发育，交易行变现，被商人与公会逐步注意。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    names = {profile["name"] for profile in enriched.character_profiles}

    assert {"苏叶", "赵胖子", "药剂师洛婶", "职业导师艾伦", "白袍公会外围队长"}.issubset(names)


def test_sanitizer_rewrites_reader_facing_bad_game_terms():
    body = (
        "夜烬看见任务门槛还没满足，只能先修杖。"
        "他握杖退后，杖尖对着灰狼，系统提示火球术熟练度还差一点。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[])

    assert "门槛" not in cleaned
    assert "修杖" not in cleaned
    assert "握杖" not in cleaned
    assert "杖尖" not in cleaned
    assert "熟练度" not in cleaned
    assert "任务前置" in cleaned
    assert "修法杖" in cleaned
    assert "握着法杖" in cleaned
    assert "法杖前端" in cleaned
    assert "基础火球术记录" in cleaned
def test_sanitize_chapter_output_does_not_inject_webgame_text_into_xianxia():
    body = "林照守在祖祠里，等第三块青砖后面的人露出破绽。"

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[], game_story=False)

    assert cleaned == body
    assert "夜烬" not in cleaned
    assert "灰狼" not in cleaned
    assert "法杖" not in cleaned
