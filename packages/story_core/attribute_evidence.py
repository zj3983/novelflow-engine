from __future__ import annotations

import re
from typing import Iterator


_CN_NUMERAL_VALUES = {
    "零": 0,
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
}
_COUNT_PATTERN = r"\d+|[一二两三四五六七八九十]{1,3}"
_ATTRIBUTE_ACTION_PATTERN = (
    rf"(?:{_COUNT_PATTERN})\s*点(?:(?:自由)?属性点?)?[^。！？\n]{{0,16}}"
    r"(?:全部)?(?:加到|加给|分配给|投入|点在)"
)
_EXPLANATORY_MARKERS = ("系统说明", "系统提示", "系统规则", "规则", "示例", "提示说明", "界面说明")
_ATTRIBUTE_CONTEXT = ("属性点", "加点", "分配", "力量", "体质", "敏捷", "智力", "精神", "感知")
_CHARACTER_ACTION_PREFIX = re.compile(
    r"(?:他|她|我|玩家|角色|[\u4e00-\u9fff]{2,4})[^。！？\n]{0,20}"
    r"(?:打开|抬手|伸手|把|将|决定|选择|分配|投入|加)\s*$"
)
_CHARACTER_SUBJECT_PREFIX = re.compile(r"(?:他|她|我|玩家|角色|[\u4e00-\u9fff]{2,4})[^。！？\n]{0,20}$")
_CARRY_DECISION_PREFIX = re.compile(
    r"(?:他|她|我|玩家|角色|[\u4e00-\u9fff]{2,4})[^。！？\n]{0,24}"
    r"(?:决定|打算|选择|准备|想|先|暂时)\s*$"
)


def parse_count(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value in _CN_NUMERAL_VALUES:
        return _CN_NUMERAL_VALUES[value]
    if "十" in value:
        left, _, right = value.partition("十")
        tens = _CN_NUMERAL_VALUES.get(left, 1 if left == "" else None)
        ones = _CN_NUMERAL_VALUES.get(right, 0 if right == "" else None)
        if tens is not None and ones is not None:
            return tens * 10 + ones
    return None


def sentence_bounds(text: str, position: int) -> tuple[int, int]:
    start = max(text.rfind(marker, 0, position) for marker in "。！？\n") + 1
    ends = [index for marker in "。！？\n" if (index := text.find(marker, position)) >= 0]
    return start, min(ends) if ends else len(text)


def _is_explanatory_sentence(text: str, position: int) -> bool:
    start, end = sentence_bounds(text, position)
    return any(marker in text[start:end] for marker in _EXPLANATORY_MARKERS)


def _is_negated_before(text: str, position: int, *, carry: bool = False) -> bool:
    start, _ = sentence_bounds(text, position)
    prefix = text[start:position].rstrip()
    if carry:
        return bool(re.search(r"(?:没有|没|未|并未|不)\s*(?:打算|准备|想|决定|选择|再|先)?\s*$", prefix))
    return bool(re.search(r"(?:没有|没|未|并未|不)\s*(?:把|将)?\s*$", prefix))


def _has_character_action(text: str, action_start: int) -> bool:
    start, _ = sentence_bounds(text, action_start)
    if _is_explanatory_sentence(text, action_start):
        return False
    return bool(_CHARACTER_ACTION_PREFIX.search(text[start:action_start]))


def _action_matches(body: str, attribute: str | None = None, points: int | None = None) -> Iterator[re.Match[str]]:
    if attribute is not None and points is not None:
        forms = (str(points), _chinese_number(points))
        for form in forms:
            if not form:
                continue
            pattern = (
                rf"{re.escape(form)}\s*点(?:(?:自由)?属性点?)?[^。！？\n]{{0,16}}"
                rf"(?:全部)?(?:加到|加给|分配给|投入|点在)\s*{re.escape(attribute)}(?:上|里)?"
            )
            yield from re.finditer(pattern, body)
        return
    yield from re.finditer(_ATTRIBUTE_ACTION_PATTERN, body)


def _chinese_number(value: int) -> str:
    return next((token for token, number in _CN_NUMERAL_VALUES.items() if number == value), "")


def has_character_attribute_allocation(body: str, attribute: str | None = None, points: int | None = None) -> bool:
    for match in _action_matches(body, attribute, points):
        if not _is_negated_before(body, match.start()) and _has_character_action(body, match.start()):
            return True
    return False


def character_attribute_allocation_points(body: str, attribute: str) -> int | None:
    pattern = (
        rf"(?P<count>{_COUNT_PATTERN})\s*点(?:(?:自由)?属性点?)?[^。！？\n]{{0,16}}"
        rf"(?:全部)?(?:加到|加给|分配给|投入|点在)\s*{re.escape(attribute)}(?:上|里)?"
    )
    values: list[int] = []
    for match in re.finditer(pattern, body):
        if _is_negated_before(body, match.start()) or not _has_character_action(body, match.start()):
            continue
        count = parse_count(match.group("count"))
        if count is not None:
            values.append(count)
    return values[-1] if values else None


def _positive_confirmation_positions(body: str) -> list[int]:
    confirmations = list(re.finditer(r"确认|确定|生效|保存", body))
    positions: list[int] = []
    for action in _action_matches(body):
        if _is_negated_before(body, action.start()) or not _has_character_action(body, action.start()):
            continue
        action_start, action_end = sentence_bounds(body, action.start())
        _, nearby_end = sentence_bounds(body, action_end + 1)
        for match in confirmations:
            confirmation_start, confirmation_end = sentence_bounds(body, match.start())
            suffix = body[match.end() : match.end() + 8]
            if confirmation_start not in (action_start, action_end + 1) or match.start() > nearby_end:
                continue
            if _is_negated_before(body, match.start()) or re.match(r"\s*(?:不分配|不加点|不加属性)", suffix):
                continue
            confirmation_sentence = body[confirmation_start:confirmation_end]
            confirmation_window = body[max(confirmation_start, match.start() - 8) : match.end() + 12]
            if any(token in confirmation_window for token in ("修理", "订单", "交易", "任务")):
                continue
            if any(token in confirmation_sentence for token in _ATTRIBUTE_CONTEXT):
                positions.append(match.start())
    return positions


def has_positive_attribute_allocation_confirmation(body: str) -> bool:
    return bool(_positive_confirmation_positions(body))


def _attribute_point_results(body: str) -> list[tuple[int, int]]:
    results: list[tuple[int, int]] = []
    labelled = re.compile(
        rf"(?:可用属性点|剩余属性点|自由属性点|属性点还剩)\s*(?:还是|还剩|为|：|:)?\s*(?P<count>{_COUNT_PATTERN})\s*点?"
    )
    for match in labelled.finditer(body):
        count = parse_count(match.group("count"))
        if count is not None:
            results.append((match.start(), count))
    for match in re.finditer(rf"(?P<count>{_COUNT_PATTERN})\s*点(?:可用|剩余|自由)属性点", body):
        count = parse_count(match.group("count"))
        if count is not None:
            results.append((match.start(), count))
    for match in re.finditer(r"(?:可用属性点|剩余属性点|自由属性点)[^。！？\n]{0,8}归零", body):
        results.append((match.start(), 0))
    return sorted(results)


def latest_attribute_points(body: str) -> int | None:
    results = _attribute_point_results(body)
    return results[-1][1] if results else None


def latest_confirmed_attribute_points(body: str) -> int | None:
    confirmations = _positive_confirmation_positions(body)
    if not confirmations:
        return None
    confirmed_at = confirmations[-1]
    results = [result for result in _attribute_point_results(body) if result[0] >= confirmed_at]
    return results[-1][1] if results else None


def has_character_attribute_carry_choice_and_reason(body: str) -> tuple[bool, bool]:
    choice_pattern = r"暂时不加|先不加|留着|保留|攒着|不分配"
    reason_pattern = r"因为|为了|留给|等到|等转职"
    for choice in re.finditer(choice_pattern, body):
        start, end = sentence_bounds(body, choice.start())
        sentence = body[start:end]
        prefix = body[start:choice.start()]
        if _is_explanatory_sentence(body, choice.start()) or _is_negated_before(body, choice.start(), carry=True):
            continue
        direct_choice = choice.group(0) in ("暂时不加", "先不加")
        has_actor = bool(_CHARACTER_SUBJECT_PREFIX.search(prefix)) if direct_choice else bool(_CARRY_DECISION_PREFIX.search(prefix))
        if not has_actor:
            continue
        if re.search(reason_pattern, sentence):
            return True, True
        next_start = end + 1
        _, next_end = sentence_bounds(body, next_start)
        next_sentence = body[next_start:next_end].lstrip()
        if re.match(rf"(?:{reason_pattern})", next_sentence):
            return True, True
        return True, False
    return False, False
