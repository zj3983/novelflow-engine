import pytest
from copy import deepcopy

from packages.story_core.web_game_economy import (
    appraisal_rules,
    exchange_rules,
    first_chapter_market_exchange_authorized,
    market_rules,
    normalize_legacy_economy_prompt_value,
    opening_market_exchange_flow_lines,
)


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
