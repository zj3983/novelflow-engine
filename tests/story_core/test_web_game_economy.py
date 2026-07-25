import pytest

from packages.story_core.web_game_economy import (
    appraisal_rules,
    exchange_rules,
    first_chapter_market_exchange_authorized,
    market_rules,
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
    assert "交易行不能直接现实结算" in text
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


def test_implementation_plan_wording_does_not_require_market_name() -> None:
    assert first_chapter_market_exchange_authorized(
        {"turn": "第一章卖出裂纹狼心，再走官方兑换渠道解决现实急账。"},
        [],
    )


def test_contract_can_be_split_between_event_plan_and_world_facts() -> None:
    assert first_chapter_market_exchange_authorized(
        {"ordered_actions": ["在交易行卖出裂纹狼心"]},
        ["成交所得游戏币进入游戏钱包。", "再走官方兑换渠道解决现实急账。"],
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
    ),
)
def test_original_legacy_opening_markers_remain_readable(marker: str) -> None:
    assert first_chapter_market_exchange_authorized(
        {"turn": marker},
        [],
    )
