from __future__ import annotations

import re
from typing import Any

from packages.story_core.novel_type_catalog import normalize_novel_type_ids


COMMON_HOOK_TERMS = ("下一章", "下一步", "目标", "线索", "期限", "约定", "决定")
COMMON_CARE_TERMS = ("代价", "失去", "保护", "责任", "困境", "必须", "只剩", "承诺")
COMMON_PAYOFF_TERMS = ("发现", "获得", "成功", "揭开", "确认", "改变")
COMMON_REPETITIVE_MARKERS = ("反复", "再次", "仍旧", "来回")

GENRE_PROFILES: dict[str, dict[str, Any]] = {
    "game": {
        "ids": ("game_webnovel",),
        "aliases": ("网游", "游戏", "虚拟现实", "vrmmo", "web_game"),
        "hook_terms": (
            "任务",
            "交易行",
            "装备",
            "材料",
            "掉落",
            "现实期限",
            "散人",
            "收购",
            "黑市",
            "委托",
            "公会",
            "倒计时",
            "未鉴定",
            "提示",
        ),
        "care_terms": (
            "房租",
            "账单",
            "催租",
            "停职",
            "失业",
            "欠",
            "倒计时",
            "余额",
            "现实",
            "药水",
            "耐久",
        ),
        "payoff_terms": (
            "稀有",
            "未鉴定",
            "晶核",
            "额外",
            "千倍",
            "异常",
            "隐藏",
            "掉落",
            "装备",
            "协议",
        ),
        "overload_terms": (
            "隐藏优势",
            "底层协议",
            "灰烬王庭",
            "星门议会",
            "灵魂链路",
            "七阶职业",
            "天启拍卖行",
            "白塔公会",
            "神格碎片",
            "深渊税则",
        ),
        "repetitive_markers": ("打开面板", "查面板", "刷了", "成本已经先到了"),
        "hook_suggestion": "把结尾落到可执行目标：交易行、散人渠道、NPC委托、公会门槛、材料异动或现实倒计时。",
        "care_suggestion": "补一根现实期限或游戏代价线，让读者知道任务收益为什么重要、失败会损失什么。",
        "loop_suggestion": "至少让一段验证出现质变：异常掉落、耐久骤降、怪物反扑、路线变化或NPC门槛。",
    },
    "xuanhuan": {
        "ids": ("xuanhuan", "xianxia"),
        "aliases": ("玄幻", "东方玄幻", "仙侠", "修仙", "修真", "xuanhuan", "xianxia", "cultivation", "fantasy"),
        "hook_terms": ("修炼", "突破", "势力", "宗门", "宗门差事", "资格", "线索", "时限"),
        "care_terms": ("人物处境", "瓶颈", "寿元", "危机", "牵连", "修为", "境界", "师门"),
        "payoff_terms": ("突破", "晋升", "领悟", "传承", "机缘", "认可", "洗清", "脱困"),
        "overload_terms": ("天命道骨", "太虚剑宗", "九幽魔域", "无相灵根", "归墟古印", "万劫天经", "上古神庭"),
        "repetitive_markers": ("运转功法", "重复吐纳", "再次冲关", "境界仍旧未动"),
        "hook_suggestion": "把结尾落到修炼突破、势力变化、宗门差事、资格争夺、关键线索或迫近时限。",
        "care_suggestion": "补清人物处境、修炼目标或突破代价，让读者知道成败会改变谁的命运。",
        "loop_suggestion": "至少让一段修炼出现质变：突破受阻、代价显现、势力介入或人物关系改变。",
    },
}

GENERIC_HOOK_SUGGESTION = "把结尾落到明确的下一步目标、待解线索、迫近期限或人物选择。"
GENERIC_CARE_SUGGESTION = "补清人物目标和失败代价，让读者知道这次行动为什么重要。"
GENERIC_LOOP_SUGGESTION = "至少让一段重复行动出现质变：结果改变、代价升级、关系转折或新阻碍介入。"


def _genre_profile(genre_context: Any) -> dict[str, Any] | None:
    if hasattr(genre_context, "model_dump"):
        genre_context = genre_context.model_dump(mode="json")
    if isinstance(genre_context, dict):
        normalized_ids = set(normalize_novel_type_ids(genre_context.get("genre_plugin_ids")))
        if normalized_ids:
            for profile in GENRE_PROFILES.values():
                if normalized_ids.intersection(profile["ids"]):
                    return profile
            return None
        genre = str(genre_context.get("genre") or "").strip()
    elif isinstance(genre_context, str):
        genre = genre_context.strip()
    else:
        return None

    normalized_genre_ids = set(normalize_novel_type_ids(genre))
    lowered_genre = genre.casefold()
    for profile in GENRE_PROFILES.values():
        if normalized_genre_ids.intersection(profile["ids"]):
            return profile
        if lowered_genre in {alias.casefold() for alias in profile["aliases"]}:
            return profile
    return None


def _profile_terms(profile: dict[str, Any] | None, key: str) -> tuple[str, ...]:
    if profile is None:
        return ()
    return tuple(profile.get(key) or ())


def _score_presence(body: str, terms: tuple[str, ...], *, base: int = 2, cap: int = 5) -> int:
    hits = sum(1 for term in terms if term in body)
    return max(1, min(cap, base + hits))


def _issue(issue_type: str, reason: str, suggestion: str) -> dict[str, str]:
    return {"type": issue_type, "reason": reason, "suggestion": suggestion}


def _unknown_concept_count(body: str, overload_terms: tuple[str, ...]) -> int:
    return sum(1 for term in overload_terms if term in body)


def _sentence_count(body: str) -> int:
    return len([item for item in re.split(r"[。！？\n]+", body) if item.strip()])


def review_cold_reader_experience(
    body: str,
    *,
    previous_summary: str = "",
    genre_context: Any = None,
) -> dict[str, Any]:
    """Review a chapter as a cold reader who cannot see outline or world bible."""

    body = str(body or "")
    profile = _genre_profile(genre_context)
    hook_terms = COMMON_HOOK_TERMS + _profile_terms(profile, "hook_terms")
    care_terms = COMMON_CARE_TERMS + _profile_terms(profile, "care_terms")
    payoff_terms = COMMON_PAYOFF_TERMS + _profile_terms(profile, "payoff_terms")
    repetitive_markers = COMMON_REPETITIVE_MARKERS + _profile_terms(profile, "repetitive_markers")
    issues: list[dict[str, str]] = []
    concept_count = _unknown_concept_count(body, _profile_terms(profile, "overload_terms"))

    scores = {
        "page_turn": _score_presence(body, hook_terms, base=1),
        "cognitive_load": 5 if concept_count <= 3 else 2 if concept_count <= 6 else 1,
        "empathy_connection": _score_presence(body, care_terms, base=1),
        "pace_feel": 4,
    }

    if not body.strip():
        return {
            "reviewer": "cold_reader/v1",
            "pass": False,
            "scores": {key: 0 for key in scores},
            "issues": [
                _issue("empty_body", "正文为空，冷读者没有可评估内容。", "补齐章节正文后再进行冷读者审查。")
            ],
            "revision_plan": ["补写完整章节正文。"],
            "previous_summary_used": bool(previous_summary.strip()),
        }

    if scores["page_turn"] <= 2:
        issues.append(
            _issue(
                "missing_specific_hook",
                "章末缺少具体下一步诱饵，冷读者不知道下一章要看什么。",
                str((profile or {}).get("hook_suggestion") or GENERIC_HOOK_SUGGESTION),
            )
        )

    if scores["empathy_connection"] <= 2:
        issues.append(
            _issue(
                "weak_why_care",
                "正文没有把主角收益和人物目标或明确代价挂起来。",
                str((profile or {}).get("care_suggestion") or GENERIC_CARE_SUGGESTION),
            )
        )

    if concept_count > 3:
        issues.append(
            _issue(
                "cognitive_overload",
                f"冷读者一次看到 {concept_count} 个陌生高概念，认知负担过高。",
                "删减或后移未服务当前冲突的概念；第一章最多保留1个新概念，并先用场景呈现。",
            )
        )

    repetitive_hits = sum(1 for marker in repetitive_markers if marker in body)
    short_sentences = _sentence_count(body)
    if repetitive_hits >= 3 and short_sentences <= 8:
        scores["pace_feel"] = 2
        issues.append(
            _issue(
                "repetitive_loop",
                "场景推进像重复动作清单，缺少质变事件或决策升级。",
                str((profile or {}).get("loop_suggestion") or GENERIC_LOOP_SUGGESTION),
            )
        )

    if any(term in body for term in payoff_terms):
        scores["page_turn"] = max(scores["page_turn"], 4)

    pass_review = not issues and all(score >= 3 for score in scores.values())
    return {
        "reviewer": "cold_reader/v1",
        "pass": pass_review,
        "scores": scores,
        "issues": issues,
        "revision_plan": [issue["suggestion"] for issue in issues],
        "previous_summary_used": bool(previous_summary.strip()),
    }
