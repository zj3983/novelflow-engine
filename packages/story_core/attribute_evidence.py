from __future__ import annotations

import re
from typing import Iterable, Iterator


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
_COUNT_PATTERN = r"\d+|[一二两三四五六七八九十百]{1,3}"
_ATTRIBUTE_ACTION_PATTERN = (
    rf"(?:{_COUNT_PATTERN})\s*点(?:(?:自由)?属性点?)?[^。！？\n]{{0,16}}"
    r"(?:全部)?(?:加到(?:了)?|加给|分配给|分配到(?:了)?|投入(?:到)?(?:了)?|点在)"
)
_ATTRIBUTE_CONTEXT = ("属性点", "加点", "分配", "力量", "体质", "敏捷", "智力", "精神", "感知")
_EXPLANATORY_SUBJECT_PATTERNS = (
    re.compile(r"^\s*(?:《[^》]+》)?\s*系统(?:说明|提示|规则)"),
    re.compile(r"^\s*规则(?:写明|说明|如下)"),
    re.compile(r"^\s*示例(?:为|如下)?"),
    re.compile(r"^\s*(?:提示说明|界面说明)"),
)
_CHARACTER_ACTION_PREFIX = re.compile(
    r"(?:他|她|我|玩家|角色|[\u4e00-\u9fff]{2,4})[^。！？\n]{0,28}"
    r"(?:打开|抬手|伸手|把|将|决定|选择|分配|投入|加)[^。！？\n]{0,18}$"
)
_CHARACTER_SUBJECT_PREFIX = re.compile(r"(?:他|她|我|玩家|角色|[\u4e00-\u9fff]{2,4})[^。！？\n]{0,20}$")
_CARRY_DECISION_PREFIX = re.compile(
    r"(?:他|她|我|玩家|角色|[\u4e00-\u9fff]{2,4})[^。！？\n]{0,28}"
    r"(?:决定|打算|选择|准备|想|先|暂时)[^。！？\n]{0,18}$"
)
_PRONOUN_SUBJECT_PREFIX = re.compile(r"(?:^|[，,])\s*(?:他|她|我)[^。！？\n]{0,32}$")
_BYSTANDER_SUBJECT_PREFIX = re.compile(r"(?:^|[，,])\s*(?:(?:短发|长发|高个|矮个|陌生|路过的)?(?:玩家|路人|NPC))")
_ACTION_CONTINUATIONS = {"随后", "然后", "接着", "再", "便", "就", "先", "又"}
_ACTION_MODIFIERS = ("直接", "果断", "又", "重新", "干脆", "索性", "还是")
_GENERIC_REASON_TERMS = {"先", "为了", "因为", "属性点", "属性", "点", "保留", "留着", "分配", "决定", "原因", "目的", "以后", "再用", "留给"}


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
    if value == "一百":
        return 100
    return None


def sentence_bounds(text: str, position: int) -> tuple[int, int]:
    start = max(text.rfind(marker, 0, position) for marker in "。！？\n") + 1
    ends = [index for marker in "。！？\n" if (index := text.find(marker, position)) >= 0]
    return start, min(ends) if ends else len(text)


def _is_explanatory_sentence(text: str, position: int) -> bool:
    start, end = sentence_bounds(text, position)
    return any(pattern.search(text[start:end]) for pattern in _EXPLANATORY_SUBJECT_PATTERNS)


def _is_negated_before(text: str, position: int, *, carry: bool = False) -> bool:
    start, _ = sentence_bounds(text, position)
    prefix = text[start:position].rstrip()
    if carry:
        return bool(
            re.search(r"(?:没有|没|未|并未|不)\s*(?:打算|准备|想|决定|选择)[^。！？\n]{0,16}$", prefix)
            or re.search(r"(?:打算|准备|想|决定|选择)\s*不\s*(?:把|将)[^。！？\n]{0,16}$", prefix)
        )
    return bool(
        re.search(r"(?:没有|没|未|并未|不)(?:\s*(?:打算|准备|决定|选择))?\s*(?:把|将)[^。！？\n]{0,16}$", prefix)
    )


def protagonist_aliases_from_characters(characters: Iterable[object]) -> set[str]:
    """Return the real-name and game-ID aliases for explicit protagonist cards."""

    aliases: set[str] = set()
    for character in characters:
        if isinstance(character, dict):
            role = str(character.get("role") or "").strip().casefold()
            values = (character.get("name"), character.get("game_id"))
            panel = character.get("game_panel")
        else:
            role = str(getattr(character, "role", "") or "").strip().casefold()
            values = (getattr(character, "name", ""), getattr(character, "game_id", ""))
            panel = getattr(character, "game_panel", None)
        if role not in {"protagonist", "主角"}:
            continue
        for value in values:
            alias = str(value or "").strip()
            if alias:
                aliases.add(alias)
        panel_game_id = panel.get("game_id") if isinstance(panel, dict) else getattr(panel, "game_id", "")
        panel_alias = str(panel_game_id or "").strip()
        if panel_alias:
            aliases.add(panel_alias)
    return aliases


def _normalized_aliases(protagonist_aliases: Iterable[str] | None) -> tuple[str, ...]:
    if protagonist_aliases is None:
        return ()
    return tuple(
        sorted(
            {alias.strip() for alias in protagonist_aliases if isinstance(alias, str) and alias.strip()},
            key=len,
            reverse=True,
        )
    )


def _has_protagonist_actor(prefix: str, pattern: re.Pattern[str], protagonist_aliases: Iterable[str] | None) -> bool:
    if not pattern.search(prefix):
        return False
    aliases = _normalized_aliases(protagonist_aliases)
    if aliases:
        return any(alias in prefix for alias in aliases) or bool(_PRONOUN_SUBJECT_PREFIX.search(prefix))
    return not _BYSTANDER_SUBJECT_PREFIX.search(prefix)


def _protagonist_subject_before_bridge(prefix: str, aliases: tuple[str, ...]) -> bool | None:
    """Bind 把/将 to a known lead, a lead pronoun, or an inherited local subject."""

    if not aliases:
        return None
    clause = re.split(r"[，,；;]", prefix)[-1].rstrip()
    if not clause.endswith(("把", "将")):
        return None
    stem = clause[:-1].strip()
    if not stem or stem in _ACTION_CONTINUATIONS:
        return None
    modifier_pattern = "(?:" + "|".join(_ACTION_MODIFIERS) + ")*"
    if any(re.search(rf"{re.escape(alias)}{modifier_pattern}$", stem) for alias in aliases):
        return True
    if re.search(rf"(?:他|她|我){modifier_pattern}$", stem):
        return True
    return False


def _has_character_action(text: str, action_start: int, protagonist_aliases: Iterable[str] | None = None) -> bool:
    start, _ = sentence_bounds(text, action_start)
    if _is_explanatory_sentence(text, action_start):
        return False
    prefix = text[start:action_start]
    bound_subject = _protagonist_subject_before_bridge(prefix, _normalized_aliases(protagonist_aliases))
    if bound_subject is not None:
        return bound_subject
    return _has_protagonist_actor(prefix, _CHARACTER_ACTION_PREFIX, protagonist_aliases)


def _action_matches(body: str, attribute: str | None = None, points: int | None = None) -> Iterator[re.Match[str]]:
    if attribute is not None and points is not None:
        forms = (str(points), _chinese_number(points))
        for form in forms:
            if not form:
                continue
            pattern = (
                rf"{re.escape(form)}\s*点(?:(?:自由)?属性点?)?[^。！？\n]{{0,16}}"
                rf"(?:全部)?(?:加到(?:了)?|加给|分配给|分配到(?:了)?|投入(?:到)?(?:了)?|点在)\s*{re.escape(attribute)}(?:上|里)?"
            )
            yield from re.finditer(pattern, body)
        return
    yield from re.finditer(_ATTRIBUTE_ACTION_PATTERN, body)


def _chinese_number(value: int) -> str:
    digits = ("零", "一", "二", "三", "四", "五", "六", "七", "八", "九")
    if 0 <= value < 10:
        return digits[value]
    if value == 100:
        return "一百"
    if 10 <= value < 100:
        tens, ones = divmod(value, 10)
        prefix = "十" if tens == 1 else f"{digits[tens]}十"
        return prefix if ones == 0 else f"{prefix}{digits[ones]}"
    return ""


def has_character_attribute_allocation(
    body: str,
    attribute: str | None = None,
    points: int | None = None,
    *,
    protagonist_aliases: Iterable[str] | None = None,
) -> bool:
    for match in _action_matches(body, attribute, points):
        if not _is_negated_before(body, match.start()) and _has_character_action(
            body, match.start(), protagonist_aliases
        ):
            return True
    return False


def character_attribute_allocation_points(
    body: str, attribute: str, *, protagonist_aliases: Iterable[str] | None = None
) -> int | None:
    pattern = (
        rf"(?P<count>{_COUNT_PATTERN})\s*点(?:(?:自由)?属性点?)?[^。！？\n]{{0,16}}"
        rf"(?:全部)?(?:加到(?:了)?|加给|分配给|分配到(?:了)?|投入(?:到)?(?:了)?|点在)\s*{re.escape(attribute)}(?:上|里)?"
    )
    values: list[int] = []
    for match in re.finditer(pattern, body):
        if _is_negated_before(body, match.start()) or not _has_character_action(
            body, match.start(), protagonist_aliases
        ):
            continue
        count = parse_count(match.group("count"))
        if count is not None:
            values.append(count)
    return values[-1] if values else None


def _positive_confirmation_positions(body: str, protagonist_aliases: Iterable[str] | None = None) -> list[int]:
    confirmations = list(re.finditer(r"确认|确定|生效|保存", body))
    positions: list[int] = []
    for action in _action_matches(body):
        if _is_negated_before(body, action.start()) or not _has_character_action(
            body, action.start(), protagonist_aliases
        ):
            continue
        action_start, action_end = sentence_bounds(body, action.start())
        nearby_start, nearby_end = _next_nonempty_sentence_bounds(body, action_end + 1)
        for match in confirmations:
            confirmation_start, confirmation_end = sentence_bounds(body, match.start())
            suffix = body[match.end() : match.end() + 8]
            if confirmation_start not in (action_start, nearby_start) or match.start() > nearby_end:
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


def _next_nonempty_sentence_bounds(text: str, position: int) -> tuple[int, int]:
    while position < len(text) and text[position] in "。！？ \t\r\n":
        position += 1
    return sentence_bounds(text, position)


def has_positive_attribute_allocation_confirmation(
    body: str, *, protagonist_aliases: Iterable[str] | None = None
) -> bool:
    return bool(_positive_confirmation_positions(body, protagonist_aliases))


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


def latest_confirmed_attribute_points(body: str, *, protagonist_aliases: Iterable[str] | None = None) -> int | None:
    confirmations = _positive_confirmation_positions(body, protagonist_aliases)
    if not confirmations:
        return None
    confirmed_at = confirmations[-1]
    results = [result for result in _attribute_point_results(body) if result[0] >= confirmed_at]
    return results[-1][1] if results else None


def _normalized_reason(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)


def _meaningful_reason_terms(reason: str) -> set[str]:
    normalized = _normalized_reason(reason)
    terms: set[str] = set()
    for group in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", normalized):
        for length in (2, 3, 4):
            for start in range(len(group) - length + 1):
                term = group[start : start + length]
                if term not in _GENERIC_REASON_TERMS:
                    terms.add(term)
    return terms


def _carry_reason_matches(context: str, expected_reason: str) -> bool:
    purpose_pattern = r"因为|为了|留给|等(?:到)?|以便|好在"
    if not re.search(purpose_pattern, context):
        return False
    normalized_expected = _normalized_reason(expected_reason)
    normalized_context = _normalized_reason(context)
    if normalized_expected and normalized_expected in normalized_context:
        return True
    terms = _meaningful_reason_terms(expected_reason)
    return True if not terms else any(term in normalized_context for term in terms)


def has_character_attribute_carry_choice_and_reason(
    body: str,
    expected_reason: str = "",
    *,
    protagonist_aliases: Iterable[str] | None = None,
) -> tuple[bool, bool]:
    choice_pattern = r"暂时不加|先不加|留着|保留|攒着|不分配"
    for choice in re.finditer(choice_pattern, body):
        start, end = sentence_bounds(body, choice.start())
        sentence = body[start:end]
        prefix = body[start:choice.start()]
        if _is_explanatory_sentence(body, choice.start()) or _is_negated_before(body, choice.start(), carry=True):
            continue
        direct_choice = choice.group(0) in ("暂时不加", "先不加")
        actor_pattern = _CHARACTER_SUBJECT_PREFIX if direct_choice else _CARRY_DECISION_PREFIX
        has_actor = _has_protagonist_actor(prefix, actor_pattern, protagonist_aliases)
        if not has_actor:
            continue
        context = sentence
        next_start, next_end = _next_nonempty_sentence_bounds(body, end + 1)
        next_sentence = body[next_start:next_end].lstrip()
        if re.match(r"(?:因为|为了|留给|等(?:到)?|以便|好在)", next_sentence):
            context = f"{context} {next_sentence}"
        return True, _carry_reason_matches(context, expected_reason)
    return False, False
