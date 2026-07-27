from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Iterator


def _empty_result() -> dict[str, Any]:
    return {
        "summary": "",
        "facts": [],
        "unresolved_threads": [],
        "next_focus": "",
        "chapter_title": "",
        "character_updates": [],
        "ledger_updates": {},
        "ledger_evidence": {},
        "rejected_updates": [],
    }


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _evidence_text(value: str) -> str:
    return "".join(
        character
        for character in value
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


def _evidence_matches(body: str, evidence: Any) -> bool:
    evidence_value = _text(evidence)
    if not evidence_value:
        return False
    normalized_evidence = _evidence_text(evidence_value)
    return bool(normalized_evidence) and normalized_evidence in _evidence_text(body)


def _claim_has_body_anchors(claim: str, body: str) -> bool:
    normalized_claim = _evidence_text(claim)
    normalized_body = _evidence_text(body)
    if not normalized_claim:
        return False
    if normalized_claim in normalized_body:
        return True
    if len(normalized_claim) < 4:
        return False
    claim_bigrams = {
        normalized_claim[index : index + 2]
        for index in range(len(normalized_claim) - 1)
    }
    body_bigrams = {
        normalized_body[index : index + 2]
        for index in range(len(normalized_body) - 1)
    }
    return len(claim_bigrams & body_bigrams) >= 2


def _literal_value_in_body(value: str, body: str) -> bool:
    normalized_value = _evidence_text(value)
    return bool(normalized_value) and normalized_value in _evidence_text(body)


def _compact_json(value: Any, *, limit: int) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        rendered = json.dumps(str(value), ensure_ascii=False)
    return rendered[:limit]


def build_post_draft_memory_prompt(
    body: str,
    *,
    previous_summary: str = "",
    existing_character_names: set[str] | None = None,
    genre: str = "",
    fact_locks: Any = None,
) -> str:
    """Build a compact extraction prompt whose sole factual source is final prose."""

    names = sorted(
        name.strip()
        for name in (existing_character_names or set())
        if isinstance(name, str) and name.strip()
    )
    return "\n".join(
        [
            "你是小说项目的后置记忆提取器。JSON only，不要解释。",
            "硬性规则：最终正文是唯一事实来源。",
            "计划、大纲、模拟只是上下文，不能直接当事实。写前事实锁只用于识别冲突。",
            "summary只能概括最终正文实际写出的内容。",
            "facts与unresolved_threads的每一项必须是{text, evidence}，evidence必须逐字来自最终正文。",
            "每个character_update必须包含已知人物name与evidence；不得创建未知人物。",
            "ledger_updates只写正文已落地的叶子；ledger_evidence用protagonist.location这类扁平路径逐项给证据。",
            "自由属性加点必须同时写成：ledger_updates.protagonist.attribute_allocation={allocations:{智力:5}, remaining:0, reason?:...}；"
            "并给出protagonist.attribute_allocation.allocations.智力和protagonist.attribute_allocation.remaining两条ledger_evidence。"
            "只有正文明确写出人物把几点加到哪项、并确认结果或剩余点数时才可落账；只列最终面板不算。",
            "证据可以忽略空白和常见中英文标点差异，但禁止同义改写、模糊匹配或语义猜测。",
            "返回字段：summary, facts, unresolved_threads, next_focus, chapter_title, character_updates, ledger_updates, ledger_evidence。",
            f"题材：{_text(genre)}",
            f"上一章状态摘要（仅连续性上下文）：{_text(previous_summary)[:600]}",
            f"已知人物：{_compact_json(names, limit=600)}",
            f"写前事实锁（仅冲突对照）：{_compact_json(fact_locks or {}, limit=1200)}",
            "最终正文：",
            body if isinstance(body, str) else "",
        ]
    )


def _normalize_evidenced_items(
    value: Any,
    *,
    body: str,
    kind: str,
    rejected: list[dict[str, str]],
) -> list[str]:
    if not isinstance(value, list):
        return []

    accepted: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            rejected.append({"kind": kind, "reason": "invalid_item"})
            continue
        text = _text(item.get("text"))
        evidence = _text(item.get("evidence"))
        if not text or not evidence:
            rejected.append(
                {"kind": kind, "value": text, "reason": "missing_evidence"}
            )
            continue
        if not _evidence_matches(body, evidence):
            rejected.append(
                {"kind": kind, "value": text, "reason": "evidence_not_in_body"}
            )
            continue
        if not _claim_has_body_anchors(text, body):
            rejected.append(
                {"kind": kind, "value": text, "reason": "claim_not_supported_by_body"}
            )
            continue
        if text not in accepted:
            accepted.append(text)
    return accepted


def _known_names(value: Any) -> set[str]:
    try:
        return {
            name.strip()
            for name in value
            if isinstance(name, str) and name.strip()
        }
    except TypeError:
        return set()


def _normalize_character_updates(
    value: Any,
    *,
    body: str,
    existing_character_names: Any,
    rejected: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    known_names = _known_names(existing_character_names)
    accepted: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            rejected.append({"kind": "character_update", "reason": "invalid_item"})
            continue
        name = _text(item.get("name"))
        if not name or name not in known_names:
            rejected.append(
                {
                    "kind": "character_update",
                    "name": name,
                    "reason": "unknown_character",
                }
            )
            continue
        if not _literal_value_in_body(name, body):
            rejected.append(
                {
                    "kind": "character_update",
                    "name": name,
                    "reason": "character_not_in_body",
                }
            )
            continue
        evidence = _text(item.get("evidence"))
        if not evidence:
            rejected.append(
                {
                    "kind": "character_update",
                    "name": name,
                    "reason": "missing_evidence",
                }
            )
            continue
        if not _evidence_matches(body, evidence):
            rejected.append(
                {
                    "kind": "character_update",
                    "name": name,
                    "reason": "evidence_not_in_body",
                }
            )
            continue

        update = {"name": name}
        for field in ("emotion", "goal", "location"):
            field_value = _text(item.get(field))
            if field_value and _literal_value_in_body(field_value, body):
                update[field] = field_value
        if len(update) == 1:
            rejected.append(
                {
                    "kind": "character_update",
                    "name": name,
                    "reason": "empty_update",
                }
            )
            continue
        update["evidence"] = evidence
        accepted.append(update)
    return accepted


def _flatten_ledger(
    value: dict[str, Any],
    prefix: tuple[str, ...] = (),
) -> Iterator[tuple[tuple[str, ...], Any]]:
    for key, child in value.items():
        if not isinstance(key, str) or not key or "." in key:
            continue
        path = (*prefix, key)
        if isinstance(child, dict):
            yield from _flatten_ledger(child, path)
        else:
            yield path, child


def _set_nested(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = target
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


_NUMBER_WORDS = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}

_LEDGER_PATH_ALIASES = {
    "location": (),
    "current_location": (),
    "spirit_stones": ("灵石",),
    "level": ("等级", "lv"),
    "exp": ("经验",),
    "experience": ("经验",),
    "currency": ("铜币", "银币", "金币", "余额", "钱"),
    "hp": ("生命", "血量", "hp"),
    "mp": ("法力", "蓝量", "mp"),
    "durability": ("耐久",),
    "inventory": ("背包", "持有", "获得", "捡到"),
    "backpack": ("背包", "持有", "获得", "捡到"),
    "attributes": ("属性", "基础属性", "力量", "体质", "敏捷", "智力", "精神", "感知"),
    "unallocated_attribute_points": ("可用属性点", "剩余属性点", "自由属性点"),
    "attribute_allocation": ("属性点", "加点", "分配属性"),
    "remaining": ("可用属性点", "剩余属性点", "自由属性点", "归零"),
    "reason": (),
}

_COUNT_UNITS = (
    "枚",
    "个",
    "点",
    "级",
    "层",
    "件",
    "份",
    "次",
    "只",
    "张",
    "块",
    "颗",
    "瓶",
    "本",
    "套",
    "把",
    "支",
    "条",
    "章",
    "铜币",
    "银币",
    "金币",
    "灵石",
    "经验",
)


def _ledger_path_supported(path: tuple[str, ...], body: str, evidence: str) -> bool:
    leaf = path[-1].lower()
    haystack = _evidence_text(body + evidence).lower()
    if leaf in {"location", "current_location"}:
        return True
    aliases = _LEDGER_PATH_ALIASES.get(leaf)
    if aliases is not None:
        return any(_evidence_text(alias).lower() in haystack for alias in aliases)
    normalized_leaf = _evidence_text(leaf).lower()
    return len(normalized_leaf) >= 2 and normalized_leaf in haystack


def _ledger_value_supported(value: Any, body: str, evidence: str) -> bool:
    source_text = unicodedata.normalize("NFKC", f"{body}\n{evidence}")
    source_text = source_text.translate(str.maketrans({"−": "-", "﹣": "-"}))
    haystack = _evidence_text(source_text).lower()
    if isinstance(value, bool):
        return str(value).lower() in haystack
    if isinstance(value, (int, float)):
        number = re.escape(str(value))
        numeric_syntax = (
            r"\dA-Za-z.,，%+\-−﹣*/eE:：~～–—×^"
            "零一二三四五六七八九十百千万亿兆两"
            "壹贰叁肆伍陆柒捌玖拾佰仟萬億点分倍成折半余"
        )
        if re.search(rf"(?<![{numeric_syntax}]){number}(?![{numeric_syntax}])", source_text):
            return True
        if isinstance(value, int) and value in _NUMBER_WORDS:
            expected_word = _NUMBER_WORDS[value]
            for match in re.finditer(r"(?:负)?[零一二三四五六七八九十百千万两]+", source_text):
                if match.group(0) != expected_word:
                    continue
                prefix = source_text[max(0, match.start() - 3) : match.start()]
                suffix = source_text[match.end() :]
                if prefix.endswith("分之") or (prefix and prefix[-1] in "至到~～-–—"):
                    continue
                if re.match(r"点[零一二三四五六七八九]+", suffix):
                    continue
                if suffix.startswith(_COUNT_UNITS):
                    return True
            return False
        return False
    if isinstance(value, str):
        normalized_value = _evidence_text(value).lower()
        return bool(normalized_value) and normalized_value in haystack
    if isinstance(value, list):
        return bool(value) and all(_ledger_value_supported(item, body, evidence) for item in value)
    return False


def _attribute_allocation_action_supported(body: str, attribute: str, points: int) -> bool:
    if not isinstance(attribute, str) or not attribute or isinstance(points, bool) or not isinstance(points, int) or points <= 0:
        return False
    point_forms = (str(points), _NUMBER_WORDS.get(points, ""))
    for point_form in point_forms:
        if not point_form:
            continue
        pattern = (
            rf"{re.escape(point_form)}\s*点(?:(?:自由)?属性点?)?[^。！？\n]{{0,16}}"
            rf"(?:全部)?(?:加到|加给|分配给|投入|点在)\s*{re.escape(attribute)}(?:上|里)?"
        )
        if re.search(pattern, body):
            return True
    return False


def _attribute_remaining_supported(value: Any, body: str, evidence: str) -> bool:
    if _ledger_value_supported(value, body, evidence):
        return True
    return value == 0 and "归零" in body and any(
        token in body for token in ("可用属性点", "剩余属性点", "自由属性点")
    )


def _has_attribute_allocation_action(body: str) -> bool:
    return bool(
        re.search(
            r"(?:\d+|[零一二两三四五六七八九十])\s*点(?:(?:自由)?属性点?)?[^。！？\n]{0,16}"
            r"(?:全部)?(?:加到|加给|分配给|投入|点在)",
            body,
        )
    )


def _attribute_state_value_supported(
    path_parts: tuple[str, ...], value: Any, body: str, evidence: str
) -> bool:
    if not _has_attribute_allocation_action(body):
        return False
    if path_parts[-1] == "unallocated_attribute_points":
        return _attribute_remaining_supported(value, body, evidence)
    if "attributes" not in path_parts or not isinstance(value, int) or isinstance(value, bool):
        return False
    attribute = path_parts[-1]
    return any(
        re.search(
            rf"{re.escape(attribute)}[^。！？\n]{{0,16}}(?:变成|提升到|增加到)\s*{re.escape(point_form)}",
            body,
        )
        for point_form in (str(value), _NUMBER_WORDS.get(value, ""))
        if point_form
    )


def _attribute_allocation_group_supported(value: Any, body: str) -> bool:
    if not isinstance(value, dict):
        return False
    allocations = value.get("allocations")
    remaining = value.get("remaining")
    if not isinstance(allocations, dict) or not allocations or isinstance(remaining, bool) or not isinstance(remaining, int):
        return False
    if not all(_attribute_allocation_action_supported(body, attribute, points) for attribute, points in allocations.items()):
        return False
    has_confirmation = any(token in body for token in ("确认", "确定", "生效", "保存"))
    has_result = any(
        re.search(rf"{re.escape(attribute)}[^。！？\n]{{0,16}}(?:变成|提升到|增加到)\s*(?:{points}|{_NUMBER_WORDS.get(points, '')})", body)
        for attribute, points in allocations.items()
    )
    has_remaining = _attribute_remaining_supported(remaining, body, body)
    return has_confirmation and (has_result or has_remaining)


def _drop_attribute_allocation_update(
    accepted: dict[str, Any], accepted_evidence: dict[str, str], rejected: list[dict[str, str]]
) -> None:
    protagonist = accepted.get("protagonist")
    if not isinstance(protagonist, dict) or "attribute_allocation" not in protagonist:
        return
    protagonist.pop("attribute_allocation", None)
    if not protagonist:
        accepted.pop("protagonist", None)
    for path in list(accepted_evidence):
        if path.startswith("protagonist.attribute_allocation."):
            accepted_evidence.pop(path, None)
    rejected.append({"kind": "ledger_update", "path": "protagonist.attribute_allocation", "reason": "attribute_allocation_not_visible_in_body"})


def _normalize_ledger_updates(
    updates: Any,
    evidence_by_path: Any,
    *,
    body: str,
    rejected: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, str]]:
    if not isinstance(updates, dict) or not isinstance(evidence_by_path, dict):
        return {}, {}

    accepted: dict[str, Any] = {}
    accepted_evidence: dict[str, str] = {}
    for path_parts, value in _flatten_ledger(updates):
        path = ".".join(path_parts)
        evidence = _text(evidence_by_path.get(path))
        if not evidence:
            rejected.append(
                {"kind": "ledger_update", "path": path, "reason": "missing_evidence"}
            )
            continue
        if not _evidence_matches(body, evidence):
            rejected.append(
                {
                    "kind": "ledger_update",
                    "path": path,
                    "reason": "evidence_not_in_body",
                }
            )
            continue
        supports_value = _ledger_value_supported(value, body, evidence)
        if path_parts[-1] == "remaining" and "attribute_allocation" in path_parts:
            supports_value = _attribute_remaining_supported(value, body, evidence)
        if path_parts[-1] == "unallocated_attribute_points" or "attributes" in path_parts:
            supports_value = _attribute_state_value_supported(path_parts, value, body, evidence)
        supports_path = _ledger_path_supported(path_parts, body, evidence)
        if path_parts[-1] == "reason" and "attribute_allocation" in path_parts:
            supports_path = True
        if not supports_path or not supports_value:
            rejected.append(
                {
                    "kind": "ledger_update",
                    "path": path,
                    "reason": "value_not_supported_by_body",
                }
            )
            continue
        _set_nested(accepted, path_parts, value)
        accepted_evidence[path] = evidence
    proposed_protagonist = updates.get("protagonist") if isinstance(updates.get("protagonist"), dict) else {}
    proposed_allocation = proposed_protagonist.get("attribute_allocation")
    if proposed_allocation is not None and not _attribute_allocation_group_supported(proposed_allocation, body):
        _drop_attribute_allocation_update(accepted, accepted_evidence, rejected)
    return accepted, accepted_evidence


def normalize_post_draft_memory(
    payload: Any,
    *,
    body: str,
    existing_character_names: set[str],
) -> dict[str, Any]:
    """Drop every proposed state change that lacks literal final-prose evidence."""

    result = _empty_result()
    if not isinstance(payload, dict):
        return result

    body_text = body if isinstance(body, str) else ""
    rejected = result["rejected_updates"]
    for field in ("summary", "next_focus", "chapter_title"):
        value = _text(payload.get(field))
        if not value:
            continue
        if _evidence_matches(body_text, value):
            result[field] = value
        else:
            rejected.append({"kind": field, "reason": "value_not_in_body"})
    result["facts"] = _normalize_evidenced_items(
        payload.get("facts"),
        body=body_text,
        kind="fact",
        rejected=rejected,
    )
    result["unresolved_threads"] = _normalize_evidenced_items(
        payload.get("unresolved_threads"),
        body=body_text,
        kind="unresolved_thread",
        rejected=rejected,
    )
    result["character_updates"] = _normalize_character_updates(
        payload.get("character_updates"),
        body=body_text,
        existing_character_names=existing_character_names,
        rejected=rejected,
    )
    ledger_updates, ledger_evidence = _normalize_ledger_updates(
        payload.get("ledger_updates"),
        payload.get("ledger_evidence"),
        body=body_text,
        rejected=rejected,
    )
    result["ledger_updates"] = ledger_updates
    result["ledger_evidence"] = ledger_evidence
    return result


def _body_summary(body: str, *, limit: int = 240, sentence_limit: int = 3) -> str:
    text = body.strip() if isinstance(body, str) else ""
    if not text:
        return ""

    end = 0
    for index, match in enumerate(re.finditer(r"[^。！？!?]*[。！？!?]", text)):
        if index >= sentence_limit or match.end() > limit:
            break
        end = match.end()
    return text[:end].strip() if end else text[:limit].strip()


def fallback_post_draft_memory(body: str) -> dict[str, Any]:
    """Return body-derived memory without inventing character or ledger state."""

    result = _empty_result()
    result["summary"] = _body_summary(body)
    return result
