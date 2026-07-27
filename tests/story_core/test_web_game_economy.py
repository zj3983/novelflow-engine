import json
from pathlib import Path

import pytest
from copy import deepcopy

from packages.story_core.web_game_economy import (
    appraisal_rules,
    detect_economy_boundary_violations,
    exchange_rules,
    first_chapter_market_exchange_authorized,
    market_rules,
    normalize_legacy_economy_prompt_value,
    opening_market_exchange_flow_lines,
)


def _economy_violation_codes(body: str) -> set[str]:
    return {violation.code for violation in detect_economy_boundary_violations(body)}


@pytest.mark.parametrize(
    ("body", "expected_code"),
    (
        (
            "拍卖物已经成交。官方兑换暂时不可用。\n\n这笔成交款直接进入现实账户。",
            "market_direct_reality_settlement",
        ),
        (
            "求购已经成交。他没有使用官方兑换。\n\n求购所得直接打进现实账户。",
            "market_direct_reality_settlement",
        ),
        (
            "交易行卖出材料。官方兑换失败。\n\n这笔钱直接转入现实账户。",
            "market_direct_reality_settlement",
        ),
        (
            "求购成交。这笔钱不是奖金，而是卖材料所得，随后直接进入现实账户。",
            "market_direct_reality_settlement",
        ),
        (
            "求购成交。奖金并未到账；这笔成交款直接进入现实账户。",
            "market_direct_reality_settlement",
        ),
        (
            "甲玩家的A单资金冻结，甲玩家的A单成交，甲玩家的A单等待买家确认。",
            "funded_order_waits_for_buyer",
        ),
        (
            "甲玩家的A单已经挂出。\n\n资金随后冻结。\n\n该订单成交并等待买家确认。",
            "funded_order_waits_for_buyer",
        ),
        (
            "甲玩家的A单求购已经挂出。\n\n买家的游戏币已经被冻结。\n\nA单成交并等待买家确认。",
            "funded_order_waits_for_buyer",
        ),
        (
            "另一张求购单显示资金已经冻结。夜烬点下立即出售，系统却让他等待买家再次确认。",
            "funded_order_waits_for_buyer",
        ),
        (
            "拍卖物成交。打开官方兑换页面，确认报价、额度和手续费。\n\n这笔成交款直接进入现实账户。",
            "market_direct_reality_settlement",
        ),
        (
            "拍卖物成交。点下确认兑换后，他又放弃了兑换。\n\n这笔成交款直接进入现实账户。",
            "market_direct_reality_settlement",
        ),
    ),
)
def test_detector_flags_explicit_economy_boundary_chains(
    body: str,
    expected_code: str,
) -> None:
    assert expected_code in _economy_violation_codes(body)


@pytest.mark.parametrize(
    "body",
    (
        "拍卖物成交。进入官方兑换页面并确认兑换，兑换成功后现实账户到账。",
        "求购成交。官方兑换尚未确认，成交款仍留在游戏钱包。",
        "求购成交。这笔钱不是卖出所得，公司奖金随后直接进入现实账户。",
        "裂纹狼心已经识别，但他没有把裂纹狼心提交鉴定。",
        "裂纹狼心用途是锻造，他不需要送裂纹狼心去鉴定。",
        "裂纹狼心已经识别，系统禁止把裂纹狼心提交鉴定。",
        "裂纹狼心已经识别，鉴定师不允许送裂纹狼心去鉴定。",
        "拍卖物成交。这笔成交款并未直接进入现实账户。",
        "拍卖物成交。这笔成交款尚未进入现实账户。",
        "拍卖物成交。这笔成交款还没打进现实账户。",
        (
            "拍卖物成交。他进入官方兑换页面并点下确认兑换。"
            "系统显示兑换已受理，游戏币已扣除，现实账户实际到账。"
        ),
        "甲玩家的A单资金冻结，乙玩家的B单成交，丙玩家的C单等待买家确认。",
        "A单求购资金冻结。另一张订单成交。A单等待买家确认。",
        "A单求购资金冻结。另一张求购单成交。A单等待买家确认。",
        "A单求购资金冻结。另一张求购单刚刚挂出。订单随后成交，页面仍等待买家确认。",
        "A单求购资金冻结。另一个求购单成交。A单等待买家确认。",
        "A单求购资金冻结。另一条求购单成交。A单等待买家确认。",
        "A单求购资金冻结。另一笔订单成交。A单等待买家确认。",
        "A单求购资金冻结。别的订单成交。A单等待买家确认。",
        "A单求购资金冻结。另一条订单成交。A单等待买家确认。",
        "A单求购资金冻结。另一张求购单成交。A单等待买家确认。",
        "甲玩家的A单已经挂出。\n\n夜烬离开柜台。资金随后冻结。\n\nA单成交并等待买家确认。",
    ),
)
def test_detector_ignores_negated_or_unrelated_economy_events(body: str) -> None:
    assert not _economy_violation_codes(body)


def test_market_rules_define_only_in_game_trading() -> None:
    rules = market_rules()
    text = "\n".join(rules)

    assert isinstance(rules, tuple)
    assert all(
        marker in text
        for marker in ("游戏币", "挂单", "现有求购单", "物品ID", "数量", "可交易状态", "立即成交")
    )
    assert "现实账户" not in text
    assert "鉴定" not in text
    assert "官方兑换" not in text


def test_exchange_rules_define_a_separate_official_channel() -> None:
    rules = exchange_rules()
    text = "\n".join(rules)

    assert isinstance(rules, tuple)
    assert all(
        marker in text
        for marker in ("官方兑换渠道", "游戏钱包", "兑换价", "额度", "手续费", "预计到账", "现实账户")
    )
    assert "现实款项只能通过独立官方兑换渠道进入现实账户" in text
    assert "现实结算" not in text
    assert "鉴定" not in text


def test_appraisal_rules_only_allow_unidentified_items() -> None:
    rules = appraisal_rules()
    text = "\n".join(rules)

    assert isinstance(rules, tuple)
    assert "未鉴定物品" in text
    assert "鉴定师" in text
    assert "已识别物品不重复鉴定" in text
    assert "交易行" not in text
    assert "现实账户" not in text


def test_runtime_rules_exclude_legacy_flow_and_forbidden_currency_wording() -> None:
    text = "\n".join((*market_rules(), *exchange_rules(), *appraisal_rules()))
    forbidden_currency = "\u4eba\u6c11\u5e01"

    assert forbidden_currency not in text
    assert all(marker not in text for marker in ("担保交易", "封存交割", "鉴定求购"))


def test_new_opening_contract_authorizes_market_then_exchange() -> None:
    assert first_chapter_market_exchange_authorized(
        {"turn": "第一章在交易行卖出裂纹狼心，再走官方兑换渠道解决现实急账。"},
        [],
    )


def test_opening_market_exchange_flow_lines_define_the_four_ordered_steps() -> None:
    lines = opening_market_exchange_flow_lines()

    assert len(lines) == 4
    assert "已冻结游戏币的现有求购单" in lines[0]
    assert "立即出售已识别裂纹狼心" in lines[0]
    assert "游戏币进入游戏钱包" in lines[0]
    assert "离开交易行" in lines[1] and "独立官方兑换页面" in lines[1]
    assert all(term in lines[2] for term in ("兑换价", "额度", "手续费", "预计到账"))
    assert "现实账户到账后处理急账" in lines[3]

    rendered = "\n".join(lines)
    forbidden = (
        "担保交易",
        "匿名交割",
        "封存交割",
        "提交鉴定",
        "鉴定中",
        "平台验货",
        "买家再次确认",
        "交易行直接现实结算",
        "\u4eba\u6c11\u5e01",
    )
    assert all(term not in rendered for term in forbidden)


def test_legacy_economy_prompt_normalization_is_recursive_pure_and_keeps_amounts() -> None:
    legacy_trade = "\u62c5\u4fdd\u4ea4\u6613"
    legacy_delivery = "\u533f\u540d\u4ea4\u5272"
    legacy_appraisal = "\u63d0\u4ea4\u9274\u5b9a"
    forbidden_currency = "\u4eba\u6c11\u5e01"
    source = {
        "outline": f"第一章通过{legacy_trade}到账1764.00元。",
        "facts": [
            f"裂纹狼心{legacy_appraisal}后进入{legacy_delivery}。",
            {"rate": f"1金币=100{forbidden_currency}"},
        ],
    }
    original = deepcopy(source)

    normalized = normalize_legacy_economy_prompt_value(source, game_context=True, chapter_number=1)
    rendered = str(normalized)

    assert source == original
    assert normalized is not source
    assert "1764.00元" in rendered
    assert "1金币=100元" in rendered
    assert all(line.rstrip("。") in rendered for line in opening_market_exchange_flow_lines())
    assert all(term not in rendered for term in (legacy_trade, legacy_delivery, legacy_appraisal, forbidden_currency))


@pytest.mark.parametrize(
    ("legacy", "current"),
    [
        ("持牌虚拟资产担保平台", "官方兑换渠道"),
        ("担保交易平台", "交易行与官方兑换渠道"),
        ("持牌担保平台", "官方兑换渠道"),
        ("担保平台", "官方兑换渠道"),
        ("担保订单", "官方兑换流水"),
        ("担保订单号", "官方兑换流水号"),
        ("担保交割", "交易行成交与官方兑换"),
        ("稀有资产担保", "交易行成交与官方兑换"),
        ("买家确认收购", "求购单已成交"),
        ("担保名单", "官方兑换记录"),
        ("担保到账", "官方兑换到账"),
    ],
)
def test_real_project_legacy_vocabulary_uses_specific_longest_first_replacements(
    legacy: str,
    current: str,
) -> None:
    normalized = normalize_legacy_economy_prompt_value(
        f"记录：{legacy}。",
        game_context=True,
        chapter_number=1,
    )

    assert normalized == f"记录：{current}。"
    assert "担保" not in normalized


def test_anonymous_submit_changes_only_in_economy_context() -> None:
    assert normalize_legacy_economy_prompt_value(
        "裂纹狼心选择匿名提交。",
        game_context=True,
        chapter_number=1,
    ) == "裂纹狼心选择立即出售。"
    assert normalize_legacy_economy_prompt_value(
        "匿名提交读者反馈。",
        game_context=True,
        chapter_number=1,
    ) == "匿名提交读者反馈。"


def test_anonymous_submit_uses_clause_context_inside_a_mixed_long_prompt() -> None:
    source = (
        "担保平台处理订单。裂纹狼心选择匿名提交，匿名提交读者反馈。\n"
        "交易行要求物品匿名提交；匿名提交编辑意见。"
    )

    normalized = normalize_legacy_economy_prompt_value(source, game_context=True, chapter_number=1)

    assert normalized == (
        "官方兑换渠道处理订单。裂纹狼心选择立即出售，匿名提交读者反馈。\n"
        "交易行要求物品立即出售；匿名提交编辑意见。"
    )


@pytest.mark.parametrize(
    ("game_context", "chapter_number"),
    [(False, 1), (True, 10)],
)
def test_legacy_prompt_migration_requires_web_game_first_chapter_scope(
    game_context: bool,
    chapter_number: int,
) -> None:
    source = "裂纹狼心通过担保交易完成现实结算。"

    assert normalize_legacy_economy_prompt_value(
        source,
        game_context=game_context,
        chapter_number=chapter_number,
    ) == source


def test_legacy_prompt_migration_preserves_mapping_keys_and_container_types() -> None:
    source = {
        "担保订单": "裂纹狼心通过担保交易成交。",
        "nested": {"担保平台": "担保订单号A-17"},
        "list": ["担保平台"],
        "tuple": ("担保交割",),
        "set": {"稀有资产担保"},
    }

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert set(normalized) == set(source)
    assert "担保订单" in normalized
    assert "担保平台" in normalized["nested"]
    assert isinstance(normalized["list"], list)
    assert isinstance(normalized["tuple"], tuple)
    assert isinstance(normalized["set"], set)
    assert "担保交易" not in normalized["担保订单"]
    assert normalized["nested"]["担保平台"] == "官方兑换流水号A-17"


def test_legacy_prompt_migration_preserves_json_string_keys_without_collision() -> None:
    source = '{"担保订单":"A","官方兑换流水":"B","goal":"裂纹狼心通过担保交易成交"}'

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )
    payload = json.loads(normalized)

    assert payload["担保订单"] == "A"
    assert payload["官方兑换流水"] == "B"
    assert "担保订单" in normalized
    assert "担保交易" not in payload["goal"]


@pytest.mark.parametrize(
    "source",
    (
        "银行愿意为这笔贷款提供担保。",
        "古剑提交鉴定后才能收入宗门库房。",
        "匿名提交物品举报。",
    ),
)
def test_legacy_prompt_migration_keeps_unrelated_language(source: str) -> None:
    assert normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    ) == source


def test_web_game_first_chapter_legacy_wolf_heart_flow_still_migrates() -> None:
    source = "裂纹狼心提交鉴定后进入担保平台，随后匿名提交到求购单并成交。"

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert "提交鉴定" not in normalized
    assert "匿名提交" not in normalized
    assert "担保平台" not in normalized
    assert "立即出售" in normalized
    assert "官方兑换" in normalized


@pytest.mark.parametrize("later_marker", ("第十章", "第10章", "第2章"))
def test_legacy_prompt_migration_preserves_explicit_later_chapter_ranges(later_marker: str) -> None:
    source = f"第一章通过裂纹狼心担保交易处理急账。{later_marker}建立担保交易制度，银行继续提供担保。"

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert "第一章通过裂纹狼心担保交易" not in normalized
    assert f"{later_marker}建立担保交易制度，银行继续提供担保。" in normalized


def test_legacy_prompt_migration_preserves_later_chapter_in_structured_json_text() -> None:
    source = (
        '{"chapter_number": 1, "goal": "裂纹狼心担保交易"}\n'
        '{"chapter_number": 10, "goal": "建立担保交易制度"}'
    )

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert '"chapter_number": 1' in normalized
    assert '"chapter_number": 10, "goal": "建立担保交易制度"' in normalized
    assert normalized.count("担保交易") == 1


def test_legacy_prompt_migration_keeps_multiline_later_chapter_scope() -> None:
    source = "第一章通过裂纹狼心担保交易处理急账。\n第十章\n建立担保交易制度，银行继续提供担保。"

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert "第一章通过裂纹狼心担保交易" not in normalized
    assert "第十章\n建立担保交易制度，银行继续提供担保。" in normalized


def test_future_json_object_is_protected_without_scoping_over_following_current_text() -> None:
    future_object = '{\n  "chapter_number": 10,\n  "goal": "建立担保交易制度"\n}'
    source = f"规划记录：\n{future_object}\n当前旧约束：裂纹狼心担保交易处理急账。"

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert future_object in normalized
    assert "当前旧约束：裂纹狼心担保交易" not in normalized
    assert "官方兑换" in normalized


def test_legacy_prompt_migration_uses_nested_mapping_chapter_number_scope() -> None:
    source = {
        "chapters": [
            {"chapter_number": 1, "goal": "裂纹狼心担保交易"},
            {"chapter_number": 10, "goal": "建立担保交易制度"},
        ]
    }

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert "担保交易" not in normalized["chapters"][0]["goal"]
    assert normalized["chapters"][1] == source["chapters"][1]


def test_order_complaint_and_isolated_order_status_do_not_create_trade_context() -> None:
    source = "匿名提交订单投诉。订单状态变成鉴定中。"

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert normalized == source


@pytest.mark.parametrize(
    "source",
    (
        "裂纹狼心从背包中消失，订单状态变成“鉴定中”。",
        "裂纹狼心从背包中消失，订单状态变成鉴定中。",
    ),
)
def test_wolf_heart_order_status_uses_natural_completed_wording(source: str) -> None:
    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert normalized == "裂纹狼心从背包中消失，求购单显示已成交。"


def test_isolated_appraisal_status_in_wolf_heart_context_becomes_completed_only() -> None:
    source = "裂纹狼心已经交给求购单，页面仍显示鉴定中。"

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert normalized == "裂纹狼心已经交给求购单，页面仍显示已成交。"
    assert "官方兑换页面" not in normalized


def test_anonymous_submit_action_uses_one_sentence_trade_lookahead_only() -> None:
    source = "夜烬点下匿名提交。裂纹狼心从背包中消失，订单状态变成鉴定中。"

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert normalized == "夜烬点下立即出售。裂纹狼心从背包中消失，求购单显示已成交。"


@pytest.mark.parametrize("action", ("匿名提交反馈", "匿名提交投诉"))
def test_anonymous_feedback_action_stays_unchanged_before_trade_sentence(action: str) -> None:
    source = f"夜烬点下{action}。裂纹狼心随后放进求购单。"

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert action in normalized


def test_real_chapter_one_trade_sequence_migrates_to_readable_market_exchange_steps() -> None:
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
    body = chapter_path.read_text(encoding="utf-8")
    start_marker = "第三条求购单发布于三分钟前"
    end_marker = "手机的到账震动透过头盔提醒传来。"
    if start_marker not in body or end_marker not in body:
        pytest.skip("real chapter fixture no longer contains the legacy trade sequence")
    start = body.index(start_marker)
    segment = body[start : body.index(end_marker, start) + len(end_marker)]
    if not any(marker in segment for marker in ("匿名提交", "订单状态变成鉴定中", "担保净到账")):
        pytest.skip("real chapter fixture already uses the current market/exchange flow")

    ancient_sword_inside = "古剑交给鉴定师，等待鉴定结果。【样本符合求购要求】\n\n"
    if "夜烬盯着订单页面" not in segment:
        pytest.skip("real chapter fixture no longer has the legacy insertion anchor")
    insert_at = segment.index("夜烬盯着订单页面")
    segment = segment[:insert_at] + ancient_sword_inside + segment[insert_at:]
    normalized = normalize_legacy_economy_prompt_value(
        segment,
        game_context=True,
        chapter_number=1,
    )

    ordered_fragments = (
        "夜烬点下立即出售",
        "求购单显示已成交",
        "【成交价：按求购单标价。】",
        "【游戏币已进入钱包。】",
        "他随后打开独立的官方兑换页面。",
        "【兑换价：当前官方报价。】",
        "【可用额度：足够完成本次兑换。】",
        "【手续费：已计入预计到账。】",
        "【预计到账：1764.00元。】",
        "他确认兑换",
        "【现实账户到账1764.00元。】",
    )
    assert all(fragment in normalized for fragment in ordered_fragments)
    assert [normalized.index(fragment) for fragment in ordered_fragments] == sorted(
        normalized.index(fragment) for fragment in ordered_fragments
    )
    assert normalized.count("求购单显示已成交") == 1
    assert "交易完成以后，村口不断有玩家跑进跑出" in normalized
    assert "一个法杖玩家坐在喷泉边回蓝" in normalized
    assert "手机的到账震动透过头盔提醒传来" in normalized
    sale_index = normalized.index("夜烬点下立即出售")
    market_index = normalized.index("求购单显示已成交", sale_index)
    price_index = normalized.index("【成交价：按求购单标价。】", market_index)
    wallet_index = normalized.index("【游戏币已进入钱包。】", market_index)
    exchange_index = normalized.index("他随后打开独立的官方兑换页面。", wallet_index)
    actual_index = normalized.index("【现实账户到账1764.00元。】", exchange_index)
    assert price_index < wallet_index
    assert "【成交价：按求购单标价。】【游戏币已进入钱包。】" in normalized
    assert "等待" not in normalized[market_index:wallet_index]
    assert "村口" not in normalized[market_index:wallet_index]
    assert "官方兑换" not in normalized[:sale_index]
    assert "预计到账" not in normalized[:sale_index]
    assert "1764.00元" not in normalized[:exchange_index]
    assert "【担保净到账1764.00元。】" not in normalized
    assert normalized.count(ancient_sword_inside.strip()) == 1
    assert wallet_index < normalized.index(ancient_sword_inside.strip()) < exchange_index
    exchange_sentence = (
        "他随后打开独立的官方兑换页面。"
        "【兑换价：当前官方报价。】"
        "【可用额度：足够完成本次兑换。】"
        "【手续费：已计入预计到账。】"
        "【预计到账：1764.00元。】"
        "他确认兑换。"
    )
    assert exchange_sentence in normalized
    assert exchange_index == normalized.index(exchange_sentence)
    assert normalized.index("他确认兑换。", exchange_index) < actual_index
    assert "成交价：1764.00元" not in normalized
    assert "游戏币已进入钱包1764.00元" not in normalized
    assert "汇率" not in normalized
    assert all(
        term not in normalized
        for term in (
            "等待的半分钟里",
            "买家确认收购",
            "匿名担保交易已完成",
            "夜烬盯着订单页面",
            "屏幕终于一跳",
            "担保",
            "求购单已成交，官方兑换完成",
        )
    )


def test_appraisal_wait_outside_wolf_heart_trade_context_stays_unchanged() -> None:
    source = "古剑交给鉴定师以后，等待鉴定结果期间，他去院外喝了杯茶。"

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert normalized == source


def test_amounts_and_anonymous_action_without_old_trade_results_do_not_form_a_window() -> None:
    source = (
        "【担保净到账88元。】求购单还在展示。夜烬点下匿名提交。"
        "古剑交给鉴定师以后，等待鉴定结果期间，柜台显示【样本符合求购要求。】"
        "【净到账88元。】"
    )

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert "古剑交给鉴定师以后，等待鉴定结果期间" in normalized
    assert "【样本符合求购要求。】" in normalized
    assert "游戏币已进入钱包" not in normalized
    assert "页面显示兑换价、可用额度、手续费" not in normalized
    assert "官方兑换预计到账" not in normalized


def test_trade_window_uses_captured_amount_without_inventing_coin_price_or_rate() -> None:
    source = (
        "求购单详情。\n\n【要求：可匿名。】【担保净到账93.25元。】\n\n"
        "夜烬点下匿名提交。裂纹狼心从背包中消失，订单状态变成鉴定中。"
        "等待的半分钟里，村口仍有人排队。"
        "夜烬盯着订单页面，食指轻轻敲着膝盖。屏幕终于一跳。"
        "【样本符合求购要求。】【买家确认收购。】【匿名担保交易已完成。】"
        "【净到账92.00元。】"
    )

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert "【成交价：按求购单标价。】【游戏币已进入钱包。】" in normalized
    assert "【预计到账：93.25元。】" in normalized
    assert "【现实账户到账92.00元。】" in normalized
    assert "1764.00" not in normalized
    assert "成交价：93.25元" not in normalized
    assert "汇率" not in normalized


def test_unrelated_paragraph_between_wolf_context_and_amount_panel_breaks_association() -> None:
    source = (
        "裂纹狼心的旧说明还在页面上。\n\n"
        "村口有人讨论天气，和交易没有关系。\n\n"
        "【担保净到账45.00元。】\n\n"
        "夜烬点下匿名提交。裂纹狼心从背包中消失，订单状态变成鉴定中。"
        "夜烬盯着订单页面，食指轻轻敲着膝盖。屏幕终于一跳。"
        "【样本符合求购要求。】【买家确认收购。】【匿名担保交易已完成。】"
        "【净到账44.00元。】"
    )

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert "成交价：按求购单标价" not in normalized
    assert "兑换价：当前官方报价" not in normalized
    assert "现实账户到账44.00元" not in normalized


def test_long_purchase_paragraph_still_associates_without_a_character_limit() -> None:
    long_detail = "求购单详情：" + "卖家要求与物品说明。" * 70
    source = (
        f"{long_detail}【担保净到账71.50元。】\n\n"
        "夜烬点下匿名提交。裂纹狼心从背包中消失，订单状态变成鉴定中。"
        "夜烬盯着订单页面，食指轻轻敲着膝盖。屏幕终于一跳。"
        "【样本符合求购要求。】【买家确认收购。】【匿名担保交易已完成。】"
        "【净到账70.00元。】"
    )

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert len(long_detail) > 500
    assert "【预计到账：71.50元。】" in normalized
    assert "【现实账户到账70.00元。】" in normalized


def test_plain_amount_panel_without_purchase_or_wolf_context_does_not_form_trade_window() -> None:
    source = (
        "普通金额提醒。【担保净到账45.00元。】夜烬点下匿名提交。"
        "订单状态变成鉴定中。【买家确认收购。】【匿名担保交易已完成。】"
        "【净到账44.00元。】"
    )

    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert "成交价：按求购单标价" not in normalized
    assert "兑换价：当前官方报价" not in normalized
    assert "现实账户到账44.00元" not in normalized


@pytest.mark.parametrize(
    ("source", "forbidden"),
    (
        ("裂纹狼心通过担保交易。", "。。"),
        ("裂纹狼心提交鉴定！", "。！"),
    ),
)
def test_legacy_flow_replacement_keeps_one_terminal_mark(source: str, forbidden: str) -> None:
    normalized = normalize_legacy_economy_prompt_value(
        source,
        game_context=True,
        chapter_number=1,
    )

    assert forbidden not in normalized
    assert normalized[-1] in "。！"


def test_specific_replacements_do_not_leave_duplicate_or_partial_order_words() -> None:
    source = "持牌虚拟资产担保平台生成担保订单号，买家确认收购后完成担保交割。"

    normalized = normalize_legacy_economy_prompt_value(source, game_context=True, chapter_number=1)

    assert normalized == "官方兑换渠道生成官方兑换流水号，求购单已成交后完成交易行成交与官方兑换。"
    assert "官方兑换流水号号" not in normalized
    assert "担保" not in normalized


def test_implementation_plan_wording_does_not_require_market_name() -> None:
    assert first_chapter_market_exchange_authorized(
        {"turn": "第一章卖出裂纹狼心，再走官方兑换渠道解决现实急账。"},
        [],
    )


def test_transaction_completion_before_exchange_is_authorized() -> None:
    assert first_chapter_market_exchange_authorized(
        {"turn": "本章交易成交后，走官方兑换渠道解决现实急账。"},
        [],
    )


def test_contract_cannot_be_assembled_across_separate_entries() -> None:
    assert not first_chapter_market_exchange_authorized(
        {"ordered_actions": ["在交易行卖出裂纹狼心"]},
        ["本章再走官方兑换渠道解决现实急账。"],
    )


@pytest.mark.parametrize(
    "text",
    (
        "第一章不得卖出裂纹狼心，第二章再走官方兑换渠道解决现实急账。",
        "第一章只处理战斗，第二章卖出裂纹狼心，再走官方兑换渠道解决现实急账。",
        "第二章，本章卖出裂纹狼心，再走官方兑换渠道解决现实急账。",
        "第一章先走官方兑换渠道解决现实急账，再卖出裂纹狼心。",
        "卖出裂纹狼心后，再走官方兑换渠道解决现实急账。",
    ),
)
def test_new_contract_requires_order_and_chapter_association(text: str) -> None:
    assert not first_chapter_market_exchange_authorized(
        {"turn": text},
        [],
    )


def test_incomplete_new_contract_is_not_authorized() -> None:
    assert not first_chapter_market_exchange_authorized(
        {"turn": "第一章在交易行卖出裂纹狼心解决现实急账。"},
        [],
    )


@pytest.mark.parametrize(
    "marker",
    (
        "第一章必须通过裂纹狼心担保交易",
        "第一章必须解决现实急账",
        "第一章通过裂纹狼心担保交易解决",
        "第一章的裂纹狼心担保交易",
        "第一章已经通过担保交易解决现实急账",
        "第一章已通过担保交易解决现实急账",
        "第一章允许完成裂纹狼心担保交易",
    ),
)
def test_all_legacy_opening_markers_remain_readable(marker: str) -> None:
    assert first_chapter_market_exchange_authorized(
        {"turn": marker},
        [],
    )


@pytest.mark.parametrize(
    "denial",
    (
        "本章不交易",
        "第一章不得卖出裂纹狼心",
        "第一章禁止交易",
        "第一章不兑换",
    ),
)
def test_explicit_denial_overrides_new_and_legacy_authorization(denial: str) -> None:
    assert not first_chapter_market_exchange_authorized(
        {"turn": f"第一章卖出裂纹狼心，再走官方兑换渠道解决现实急账；{denial}。"},
        [],
    )
    assert not first_chapter_market_exchange_authorized(
        {"turn": f"第一章必须解决现实急账；{denial}。"},
        [],
    )


def test_other_chapter_denial_does_not_override_first_chapter_contract() -> None:
    assert first_chapter_market_exchange_authorized(
        {"turn": "第一章卖出裂纹狼心，再走官方兑换渠道解决现实急账。"},
        ["第二章不交易。"],
    )


def test_later_second_chapter_denial_does_not_cancel_first_chapter_contract() -> None:
    assert first_chapter_market_exchange_authorized(
        {
            "turn": (
                "第一章卖出裂纹狼心，再走官方兑换渠道解决现实急账；"
                "第二章不交易。"
            )
        },
        [],
    )


def test_legacy_contract_is_cancelled_by_same_chapter_legacy_denial() -> None:
    assert not first_chapter_market_exchange_authorized(
        {
            "turn": (
                "第一章必须通过裂纹狼心担保交易；"
                "第一章不得担保交易。"
            )
        },
        [],
    )


@pytest.mark.parametrize(
    "text",
    (
        (
            "第一章不再使用担保交易，改为卖出裂纹狼心，"
            "再走官方兑换渠道解决现实急账。"
        ),
        (
            "第一章卖出裂纹狼心，再走官方兑换渠道解决现实急账；"
            "本章不再使用担保交易。"
        ),
    ),
)
def test_complete_new_chain_is_independent_of_legacy_denial(text: str) -> None:
    assert first_chapter_market_exchange_authorized(
        {"turn": text},
        [],
    )


@pytest.mark.parametrize(
    "text",
    (
        "第一章卖出裂纹狼心，再走官方兑换不用于解决现实急账。",
        "第一章卖出裂纹狼心，再走官方兑换并非用于解决现实急账。",
        "第一章卖出裂纹狼心不是为了兑换，随后走官方兑换解决现实急账。",
        "第一章卖出裂纹狼心并非为了兑换，随后走官方兑换解决现实急账。",
        "第一章交易成交并非用于官方兑换，随后官方兑换解决现实急账。",
        "第一章卖出裂纹狼心，但官方兑换不能解决现实急账。",
        "第一章卖出裂纹狼心，但官方兑换不解决现实急账。",
        "第一章卖出裂纹狼心，但官方兑换并不能处理现实急账。",
    ),
)
def test_flow_purpose_denial_does_not_authorize_new_chain(text: str) -> None:
    assert not first_chapter_market_exchange_authorized(
        {"turn": text},
        [],
    )
