from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re
from typing import Any

from packages.story_core.novel_type_catalog import resolve_novel_type_id


_GENRE_TERMS = {
    "game_webnovel": ("首杀", "副本", "Boss", "全服", "公会", "技能", "等级"),
    "xuanhuan": ("境界", "宗门", "功法", "秘境", "血脉", "因果"),
    "xianxia": ("境界", "宗门", "功法", "天劫", "飞升", "因果"),
    "urban": ("身份", "职业", "利益", "关系", "合同", "证据"),
    "suspense": ("证据", "证词", "嫌疑人", "时间线", "失踪", "真相"),
    "rules_mystery": ("规则", "禁忌", "代价", "污染", "倒计时", "异常"),
    "romance": ("关系", "误会", "选择", "承诺", "边界", "秘密"),
    "generic_webnovel": ("身份", "目标", "危机", "选择", "代价", "真相"),
}

_GAME_EXAMPLES = (
    "《网游：满级魔龙？给我回滚成野狗！》",
    "《让你玩游戏，你把世界底层代码黑了？》",
    "《地球旧服即将删档，我成了唯一管理员》",
)


def _normalize_genre_id(genre_id: str) -> str:
    return resolve_novel_type_id(genre_id) or "generic_webnovel"


def _normalize_extra_terms(extra_terms: Iterable[str] | str) -> tuple[str, ...]:
    raw_terms = (extra_terms,) if isinstance(extra_terms, str) else extra_terms
    return tuple(str(item).strip() for item in raw_terms if str(item).strip())


def _terms(
    genre_id: str,
    extra_terms: Iterable[str] | str = (),
) -> tuple[str, ...]:
    base = _GENRE_TERMS.get(genre_id, _GENRE_TERMS["generic_webnovel"])
    return tuple(dict.fromkeys((*base, *_normalize_extra_terms(extra_terms))))


def build_book_title_guidance(
    genre_id: str,
    *,
    extra_terms: Iterable[str] | str = (),
) -> str:
    normalized_genre_id = _normalize_genre_id(genre_id)
    terms = "、".join(_terms(normalized_genre_id, extra_terms))
    examples = "\n".join(f"- {item}" for item in _GAME_EXAMPLES)
    example_section = (
        f"\n结构示例（只学结构，不得照抄）：\n{examples}"
        if normalized_genre_id == "game_webnovel"
        else ""
    )
    return (
        "书名从核心卖点或特殊能力、主角身份或反差、爽点或后果中选取两到三项，"
        "按自然中文重新组织，不要机械拼接标签。\n"
        f"当前题材可用词汇：{terms}。不要使用其他题材的专属词汇。"
        f"{example_section}"
    )


def build_chapter_title_guidance(
    genre_id: str,
    *,
    extra_terms: Iterable[str] | str = (),
) -> str:
    terms = "、".join(_terms(_normalize_genre_id(genre_id), extra_terms))
    return (
        "章节标题必须对应本章真实发生的事件，从危机、反击、反差、悬念或不可逆转折中选一种。"
        "禁止使用‘新的开始’‘危机来临’等抽象概括，不得虚构正文不存在的卖点。"
        "默认不超过二十个汉字，不要重复写章节编号。"
        "相邻三章不要连续使用同一种问句或感叹句结构。"
        f"当前题材可用词汇：{terms}。"
    )


def _title_shape(title: str) -> str:
    text = re.sub(
        r"^第\s*[一二三四五六七八九十百千万\d]+\s*章[：:\s]*",
        "",
        title.strip(),
    )
    text = text.rstrip(" \t\r\n》〉」』】）)]｝}”’\"'")
    if text.endswith(("？", "?")):
        return "question"
    if text.endswith(("！", "!")):
        return "exclamation"
    return "statement"


def validate_chapter_title_window(
    chapters: Sequence[Mapping[str, Any]],
    *,
    genre_id: str,
    previous_chapters: Sequence[Mapping[str, Any]] = (),
) -> None:
    del genre_id
    chapter_window = [*list(previous_chapters)[-2:], *chapters]
    shapes = [
        (
            _title_shape(str(item.get("title") or item.get("chapter_title") or "")),
            int(item.get("chapter_number") or 0),
        )
        for item in chapter_window
    ]
    for index in range(2, len(shapes)):
        window = shapes[index - 2 : index + 1]
        shape = window[0][0]
        if shape == window[1][0] == window[2][0] and shape in {
            "question",
            "exclamation",
        }:
            raise ValueError(
                f"repeated_chapter_title_shape:{shape}:"
                f"{window[0][1]}-{window[2][1]}"
            )
