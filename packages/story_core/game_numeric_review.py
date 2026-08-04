from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


_CENT = Decimal("0.01")
_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _chinese_integer(value: str) -> int | None:
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    if not value or any(char not in digits and char not in units for char in value):
        return None
    total = section = number = 0
    for char in value:
        if char in digits:
            number = digits[char]
            continue
        unit = units[char]
        if unit == 10000:
            section = (section + number) * unit
            total += section
            section = number = 0
        else:
            section += (number or 1) * unit
            number = 0
    return total + section + number


def _amount(value: str) -> Decimal | None:
    parsed = _decimal(value)
    if parsed is not None:
        return parsed
    integer = _chinese_integer(value)
    return Decimal(integer) if integer is not None else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _review_exchange(body: str, issues: list[str], revision_plan: list[str]) -> None:
    wallet = re.search(
        r"(?:兑换(?:游戏币|数额[^：:\n]{0,8})?|消耗)[：:\s]*"
        r"(?:(\d+)金币\s*(?:(\d+)银币)?\s*(?:(\d+)铜币)?|"
        r"(\d+)银币\s*(?:(\d+)铜币)?|(\d+)铜币)",
        body,
    )
    rate = re.search(
        r"(?:本次|当前|即时|实时)?(?:兑换价|兑换比例|兑换汇率)[】\s：:]*1银币\s*[=＝]\s*(\d+(?:\.\d+)?)元",
        body,
    )
    fee_percent_match = re.search(r"手续费(?:[（(]|[】\s：:])\s*(\d+(?:\.\d+)?)%", body)
    fee_value_match = re.search(r"(?:扣除)?手续费[^；。\n]{0,24}?(\d+(?:\.\d+)?)元", body)
    arrival = re.search(r"(?:最终|实际)?预计到账(?:金额)?[：:]\s*(\d+(?:\.\d+)?)元", body)
    if not (wallet and rate and fee_value_match and arrival):
        return

    gold = Decimal(wallet.group(1) or 0)
    silver = Decimal(wallet.group(2) or wallet.group(4) or 0)
    copper = Decimal(wallet.group(3) or wallet.group(5) or wallet.group(6) or 0)
    rate_value = _decimal(rate.group(1))
    fee_value = _decimal(fee_value_match.group(1))
    arrival_value = _decimal(arrival.group(1))
    if rate_value is None or fee_value is None or arrival_value is None:
        return

    gross = _money((gold * 100 + silver + copper / 100) * rate_value)
    expected_fee = None
    if fee_percent_match:
        fee_percent = _decimal(fee_percent_match.group(1))
        if fee_percent is not None:
            expected_fee = _money(gross * fee_percent / 100)
            if expected_fee != _money(fee_value):
                issues.append(
                    f"手续费计算错误：按{fee_percent}%计算应为{expected_fee:.2f}元，正文写成{fee_value:.2f}元。"
                )
                revision_plan.append("按兑换总额乘以手续费率重算手续费，并保留两位小数。")

    net = _money(gross - fee_value)
    if _money(arrival_value) != net:
        issues.append(
            f"净到账计算错误：兑换总额{gross:.2f}元扣除手续费{fee_value:.2f}元后，应到账{net:.2f}元。"
        )
        revision_plan.append("把预计到账和银行卡实际到账统一改为扣费后的净额。")

    actual_arrivals = re.findall(
        r"(?:账户收到|到账(?:金额)?[：:]?|划转的现实货币)\s*(\d+(?:\.\d+)?)元",
        body[arrival.end() :],
    )
    for value in actual_arrivals:
        actual = _decimal(value)
        if actual is not None and _money(actual) != net:
            issues.append(
                f"实际到账与兑换流水不一致：银行卡应收到{net:.2f}元，正文写成{actual:.2f}元。"
            )
            revision_plan.append("银行卡通知必须使用官方兑换面板计算出的净到账金额。")
            break

    balance_matches = list(
        re.finditer(r"(?:当前|现有|银行卡|账户)?余额(?:为|只剩|[：:])?\s*(\d+(?:\.\d+)?)元", body)
    )
    payments = list(
        re.finditer(r"(?:支付|缴纳|补交|清缴)(?:了|完成)?\s*(\d+(?:\.\d+)?)元", body)
    )
    for payment in payments:
        preceding = [match for match in balance_matches if match.start() < payment.start()]
        if not preceding:
            continue
        available = _decimal(preceding[-1].group(1))
        paid = _decimal(payment.group(1))
        if available is not None and paid is not None and _money(available) < _money(paid):
            issues.append(
                f"现实余额不足以支付账单：付款前余额为{available:.2f}元，正文却支付了{paid:.2f}元并声称结清。"
            )
            revision_plan.append("重算兑换净到账、付款前余额、实际支出和付款后余额，四项必须首尾相接。")
            break

    shortfall_match = re.search(r"(?:缺口|还差|尚欠|拖欠)[^。；\n]{0,12}?([\d.]+|[零一二两三四五六七八九十百千万]+)元", body)
    resolved = re.search(r"(?:账单|急账|欠款|房租)[^。；\n]{0,30}?(?:结清|解决|付清|清缴完毕)", body)
    if shortfall_match and resolved:
        shortfall = _amount(shortfall_match.group(1))
        if shortfall is not None and _money(arrival_value) < _money(shortfall):
            issues.append(
                f"兑换净到账不足以填平现实缺口：缺口为{shortfall:.2f}元，本次净到账只有{arrival_value:.2f}元，不能直接声称账单已结清。"
            )
            revision_plan.append("让净到账至少覆盖开篇写明的缺口，或降低缺口；结清后的余额必须继续由原余额加净到账减支出算出。")


def _review_experience(body: str, issues: list[str], revision_plan: list[str]) -> None:
    threshold_match = re.search(r"经验[：:]\s*\d+\s*/\s*(\d+)", body)
    if not threshold_match:
        return
    threshold = int(threshold_match.group(1))

    per_kill_match = re.search(r"每只[^。\n]{0,16}(?:提供|获得|奖励)?\s*(\d+)点经验", body)
    if not per_kill_match:
        per_kill_match = re.search(r"获得经验值[：:]?\s*[+＋]?\s*(\d+)", body)
    count_match = re.search(r"前([一二两三四五六七八九十\d]+)只[^。\n]{0,20}(?:击杀|杀死|倒下|灰狼)", body)
    if not (per_kill_match and count_match):
        return

    after_count = body[count_match.end() : count_match.end() + 2200]
    numbered_kill = re.search(r"第([一二两三四五六七八九十\d]+)只", after_count)
    upgrade = re.search(r"(?:升级光芒|等级提升|升到|升至|升级至)", after_count)
    if not numbered_kill or not upgrade or upgrade.start() <= numbered_kill.start():
        return

    count_text = count_match.group(1)
    upgrade_text = numbered_kill.group(1)
    count = int(count_text) if count_text.isdigit() else _CHINESE_NUMBERS.get(count_text)
    upgrade_kill = int(upgrade_text) if upgrade_text.isdigit() else _CHINESE_NUMBERS.get(upgrade_text)
    if count is None or upgrade_kill is None or upgrade_kill <= count:
        return
    per_kill = int(per_kill_match.group(1))
    if per_kill * count >= threshold:
        issues.append(
            f"升级时点错误：前{count}只怪按每只{per_kill}点经验已达到{per_kill * count}/{threshold}，不能等到第{upgrade_kill}只才升级。"
        )
        revision_plan.append("重算逐次经验；升级必须在经验首次达到阈值的那次击杀后立即发生。")


def _combat_windows(body: str) -> list[tuple[int, str]]:
    starts: list[tuple[int, int]] = []
    panel_pattern = re.compile(
        r"(?:【怪物面板】[^【]{0,160}?|【[^】]{0,120}?)(?:生命值?|生命)[：:]\s*(\d+)\s*/\s*\1",
        re.DOTALL,
    )
    prose_pattern = re.compile(r"生命值达到\s*(\d+)\s*点的\s*Lv\.?\s*\d+[^。！!？?\n]{0,12}(?:怪|狼|兽)")
    for match in panel_pattern.finditer(body):
        starts.append((match.start(), int(match.group(1))))
    for match in prose_pattern.finditer(body):
        starts.append((match.start(), int(match.group(1))))
    starts.sort()

    windows: list[tuple[int, str]] = []
    death_pattern = re.compile(r"生命值彻底归零|失去(?:了)?生机|倒地(?:不起)?|轰然倒下|死亡")
    for start, health in starts:
        tail = body[start : start + 2600]
        death = death_pattern.search(tail)
        if death:
            windows.append((health, tail[: death.end()]))
    return windows


def _review_combat(body: str, issues: list[str], revision_plan: list[str]) -> None:
    explanation_markers = ("暴击", "致命弱点", "弱点伤害", "要害", "持续伤害", "灼烧", "残血")
    for health, window in _combat_windows(body):
        damages = [int(value) for value in re.findall(r"[-－]\s*(\d+)", window)]
        if not damages or any(marker in window for marker in explanation_markers):
            continue
        visible_damage = sum(damages)
        if visible_damage < health:
            issues.append(
                f"战斗伤害不足：怪物满生命为{health}，死亡前正文只交代了{visible_damage}点可见伤害，也没有暴击、弱点或持续伤害来源。"
            )
            revision_plan.append("补齐普通攻击次数和伤害，或明确写出能够覆盖剩余生命的暴击、弱点或持续伤害。")


def _review_deadline_time(body: str, issues: list[str], revision_plan: list[str]) -> None:
    deadline = re.search(r"(?:今晚|当日|当天)?(?:24点|零点)(?:整)?(?:前|之前|截止)?", body)
    if not deadline:
        return
    current = re.search(
        r"(?:现实时间|当前时间)[^。；\n]{0,16}?(\d{1,2})点(\d{1,2})分",
        body[deadline.end() :],
    )
    if not current:
        return
    hour, minute = int(current.group(1)), int(current.group(2))
    if hour > 23 or minute > 59:
        return
    tail = body[deadline.end() + current.end() : deadline.end() + current.end() + 180]
    stated = re.search(
        r"只剩\s*(?P<value>\d+|[零一二两三四五六七八九十百千万]+)(?P<approx>多)?\s*分钟",
        tail,
    )
    if not stated:
        return
    stated_minutes = _amount(stated.group("value"))
    if stated_minutes is None:
        return
    actual_minutes = 24 * 60 - (hour * 60 + minute)
    lower = int(stated_minutes)
    upper = lower
    if stated.group("approx"):
        raw = stated.group("value")
        upper += 9999 if raw.endswith("万") else 999 if raw.endswith("千") else 99 if raw.endswith("百") else 9
    if not lower <= actual_minutes <= upper:
        issues.append(
            f"截止时间计算错误：现实时间{hour:02d}:{minute:02d}距离零点只有{actual_minutes}分钟，正文却写成{stated.group(0)}。"
        )
        revision_plan.append("按当前时刻到截止时刻的实际分钟数改写倒计时，不要凭感觉填写。")


def review_game_numeric_consistency(body: str) -> dict[str, Any]:
    issues: list[str] = []
    revision_plan: list[str] = []
    _review_exchange(body, issues, revision_plan)
    _review_experience(body, issues, revision_plan)
    _review_combat(body, issues, revision_plan)
    _review_deadline_time(body, issues, revision_plan)
    return {
        "reviewer": "game_numeric_consistency",
        "pass": not issues,
        "scores": {"numeric_consistency": 8 if not issues else 3},
        "issues": issues,
        "revision_plan": revision_plan,
    }
