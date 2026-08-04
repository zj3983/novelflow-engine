from packages.story_core.game_numeric_review import review_game_numeric_consistency
from packages.story_core.genre_stages.game_webnovel.review import review_game_chapter


def _issues(body: str) -> list[str]:
    return review_game_numeric_consistency(body)["issues"]


def test_rejects_exchange_net_that_does_not_deduct_fee() -> None:
    body = (
        "【兑换游戏币：24银币75铜币；即时兑换汇率：1银币=80.00元；"
        "手续费（1%）：19.80元；最终预计到账金额：1980.00元】"
        "【储蓄卡账户收到1980.00元。】"
    )

    issues = _issues(body)

    assert any("净到账计算错误" in issue for issue in issues)


def test_accepts_exchange_net_after_fee() -> None:
    body = (
        "【兑换游戏币：24银币75铜币；即时兑换汇率：1银币=80.00元；"
        "手续费（1%）：19.80元；最终预计到账金额：1960.20元】"
        "【储蓄卡账户收到1960.20元。】"
    )

    assert not any("到账" in issue or "手续费" in issue for issue in _issues(body))


def test_detects_bank_balance_that_cannot_cover_claimed_payment() -> None:
    body = (
        "苏叶原有余额612元。"
        "【兑换75银币；本次兑换价：1银币=20元；手续费：7.50元；预计到账：1492.50元】"
        "银行卡到账1492.50元，当前余额2104.50元。"
        "他随后支付了2200元，账单已经结清。"
    )

    assert any("不足以支付" in issue for issue in _issues(body))


def test_detects_exchange_net_below_chinese_written_shortfall() -> None:
    body = (
        "现实缺口整整一千四百元。"
        "【兑换比例】：1银币=10元【手续费】：0.5%。"
        "他在兑换数额一栏输入15银币，扣除手续费0.75元，实际预计到账：149.25元。"
        "现实账户收到149.25元，他随后把房租账单结清。"
    )

    assert any("不足以填平现实缺口" in issue for issue in _issues(body))


def test_rejects_upgrade_delayed_past_experience_threshold() -> None:
    body = (
        "【等级：Lv.1；经验：0/100】第一只灰狼倒下，获得经验值15。"
        "前七只灰狼已经被他击杀。第八只灰狼倒下后，金色升级光芒亮起，等级提升至Lv.2。"
    )

    assert any("升级时点错误" in issue for issue in _issues(body))


def test_rejects_delayed_upgrade_when_loot_text_separates_eighth_kill_from_upgrade() -> None:
    body = (
        "【等级：Lv.1；经验：0/100】第一只灰狼倒下，获得经验值15。"
        "前七只灰狼一共为他贡献了七份毒腺。随着第八只狼尸化为白光，"
        + "掉落说明。" * 30
        + "与此同时，金色的升级光芒亮起，等级提升至Lv.2。"
    )

    assert any("升级时点错误" in issue for issue in _issues(body))


def test_reads_colon_separated_experience_reward() -> None:
    body = (
        "【等级：Lv.1；经验：0/100】第一只灰狼倒下，【获得经验值：15】。"
        "前七只灰狼已经被他击杀。第八只灰狼倒下后，等级提升至Lv.2。"
    )

    assert any("升级时点错误" in issue for issue in _issues(body))


def test_accepts_experience_total_that_reaches_threshold_on_eighth_kill() -> None:
    body = (
        "【等级：Lv.1；经验：0/100】同级灰狼每只提供12点经验。"
        "前七只灰狼已经被他击杀。第八只灰狼额外提供16点经验，"
        "经验达到100/100，等级提升至Lv.2。"
    )

    assert not any("升级时点" in issue for issue in _issues(body))


def test_rejects_impossible_minutes_remaining_before_midnight() -> None:
    body = (
        "账单必须在今晚24点前付清。"
        "游戏界面显示现实时间已经来到23点12分，留给他支付账单的时间只剩四百多分钟。"
    )

    assert any("截止时间计算错误" in issue for issue in _issues(body))


def test_rejects_visible_damage_below_monster_health_without_damage_source() -> None:
    body = (
        "【灰狼 Lv.1；生命：80/80】火球砸中灰狼，跳出伤害：-32。"
        "第二发火球落下，灰狼的生命值彻底归零。"
    )

    assert any("伤害不足" in issue for issue in _issues(body))


def test_accepts_damage_with_explicit_weak_point_critical() -> None:
    body = (
        "【灰狼 Lv.2；生命：100/100】灰狼满血扑来。"
        "火球钻进张开的狼口，触发致命弱点，暴击伤害-105，灰狼倒地。"
    )

    assert not any("伤害不足" in issue for issue in _issues(body))


def test_game_genre_review_includes_numeric_consistency_issues() -> None:
    body = (
        "【角色面板】游戏ID：夜烬；等级：Lv.1；经验：0/100。"
        "第一只灰狼倒下，获得经验值15。前七只灰狼已经被他击杀。"
        "第八只灰狼倒下后，等级提升至Lv.2。"
    )

    review = review_game_chapter(
        context={
            "chapter_number": 1,
            "body": body,
            "event_plan": {},
            "world_facts": [],
            "simulation_plan": {},
        }
    )

    assert any("升级时点错误" in issue for issue in review["issues"])
    assert "numeric_consistency_review" in review["active_genre_reviews"]
