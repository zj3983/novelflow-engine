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
        "严禁与全书已有的任何历史章节标题重名。"
        f"当前题材可用词汇：{terms}。"
    )


def select_previous_chapter_titles(
    chapters: Sequence[Mapping[str, Any]],
    *,
    target_start: int,
) -> list[dict[str, Any]]:
    titles_by_number: dict[int, str] = {}
    eligible_numbers = {target_start - 2, target_start - 1}
    for chapter in chapters:
        number = chapter.get("chapter_number")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number not in eligible_numbers
        ):
            continue
        title = str(
            chapter.get("title") or chapter.get("chapter_title") or ""
        ).strip()
        if title:
            titles_by_number[number] = title

    latest_number = target_start - 1
    latest_title = titles_by_number.get(latest_number)
    if not latest_title:
        return []
    selected = [{"chapter_number": latest_number, "title": latest_title}]
    earlier_number = target_start - 2
    earlier_title = titles_by_number.get(earlier_number)
    if earlier_title:
        selected.insert(
            0,
            {"chapter_number": earlier_number, "title": earlier_title},
        )
    return selected


def select_chapter_titles(
    chapters: Sequence[Mapping[str, Any]],
    *,
    start_chapter: int,
    end_chapter: int,
) -> list[dict[str, Any]]:
    titles_by_number: dict[int, str] = {}
    for chapter in chapters:
        number = chapter.get("chapter_number")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number < start_chapter
            or number > end_chapter
        ):
            continue
        title = str(
            chapter.get("title") or chapter.get("chapter_title") or ""
        ).strip()
        if title:
            titles_by_number[number] = title
    return [
        {"chapter_number": number, "title": titles_by_number[number]}
        for number in sorted(titles_by_number)
    ]


def select_all_existing_chapter_titles(
    *sources: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    titles_by_number: dict[int, str] = {}
    for source in sources:
        if not source:
            continue
        for chapter in source:
            if not isinstance(chapter, Mapping):
                continue
            number = chapter.get("chapter_number")
            if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                continue
            title = str(
                chapter.get("title") or chapter.get("chapter_title") or ""
            ).strip()
            if title:
                titles_by_number[number] = title
    return [
        {"chapter_number": number, "title": titles_by_number[number]}
        for number in sorted(titles_by_number)
    ]


def select_adjacent_chapter_titles(
    chapters: Sequence[Mapping[str, Any]],
    *,
    generated_chapter_numbers: Sequence[int],
    max_items: int = 6,
) -> list[dict[str, Any]]:
    generated_numbers = {
        number
        for number in generated_chapter_numbers
        if isinstance(number, int) and not isinstance(number, bool)
    }
    if not generated_numbers or max_items <= 0:
        return []
    adjacent = [
        chapter
        for chapter in chapters
        if isinstance(chapter.get("chapter_number"), int)
        and not isinstance(chapter.get("chapter_number"), bool)
        and chapter["chapter_number"] not in generated_numbers
        and any(
            abs(chapter["chapter_number"] - generated_number) <= 2
            for generated_number in generated_numbers
        )
    ]
    return list(adjacent[:max_items])


def select_chapter_title_neighbors(
    chapters: Sequence[Mapping[str, Any]],
    *,
    generated_chapter_numbers: Sequence[int],
) -> list[dict[str, Any]]:
    generated_numbers = {
        number
        for number in generated_chapter_numbers
        if isinstance(number, int) and not isinstance(number, bool)
    }
    if not generated_numbers:
        return []
    candidates = select_chapter_titles(
        chapters,
        start_chapter=min(generated_numbers) - 2,
        end_chapter=max(generated_numbers) + 2,
    )
    return [
        chapter
        for chapter in candidates
        if any(
            abs(chapter["chapter_number"] - generated_number) <= 2
            for generated_number in generated_numbers
        )
    ]


_WRAPPER_CHARS = " \t\r\n《》〈〉「」『』【】（）()[]｛{}“”‘’\"'"


def normalize_title_text(title: str) -> str:
    text = re.sub(
        r"^第\s*[一二三四五六七八九十百千万零两\d\s]+章[：:\s]*",
        "",
        str(title or "").strip(),
    )
    return text.strip(_WRAPPER_CHARS)


def _title_shape(title: str) -> str:
    text = normalize_title_text(title)
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
    known_chapters: Sequence[Mapping[str, Any]] = (),
    generated_chapter_numbers: Sequence[int] | set[int] | None = None,
) -> None:
    del genre_id
    generated_numbers = (
        {
            number
            for number in generated_chapter_numbers
            if isinstance(number, int) and not isinstance(number, bool)
        }
        if generated_chapter_numbers is not None
        else {
            chapter["chapter_number"]
            for chapter in chapters
            if isinstance(chapter.get("chapter_number"), int)
            and not isinstance(chapter.get("chapter_number"), bool)
        }
    )
    titles_by_number: dict[int, str] = {}
    for source in (previous_chapters, known_chapters, chapters):
        for chapter in source:
            number = chapter.get("chapter_number")
            if not isinstance(number, int) or isinstance(number, bool):
                continue
            title = str(
                chapter.get("title") or chapter.get("chapter_title") or ""
            ).strip()
            if title:
                titles_by_number[number] = title

    # 1. Deterministic duplicate check across generated chapters and known history
    for gen_number in sorted(generated_numbers):
        if gen_number not in titles_by_number:
            continue
        gen_title = titles_by_number[gen_number]
        norm_gen = normalize_title_text(gen_title)
        if not norm_gen:
            continue
        # Check against earlier chapters first (whether historical or within current batch)
        for other_number in sorted(titles_by_number):
            if other_number >= gen_number:
                continue
            other_title = titles_by_number[other_number]
            if normalize_title_text(other_title) == norm_gen:
                raise ValueError(
                    f"duplicate_chapter_title:{gen_number}:{other_number}:{gen_title}"
                )
        # Check against future fixed chapters (not in generated batch)
        for other_number in sorted(titles_by_number):
            if other_number <= gen_number or other_number in generated_numbers:
                continue
            other_title = titles_by_number[other_number]
            if normalize_title_text(other_title) == norm_gen:
                raise ValueError(
                    f"duplicate_chapter_title:{gen_number}:{other_number}:{gen_title}"
                )

    # 2. Window shape check (no 3 consecutive questions or exclamations)
    for start in sorted(titles_by_number):
        numbers = (start, start + 1, start + 2)
        if not all(number in titles_by_number for number in numbers):
            continue
        if not generated_numbers.intersection(numbers):
            continue
        shape = _title_shape(titles_by_number[start])
        if shape in {"question", "exclamation"} and all(
            _title_shape(titles_by_number[number]) == shape
            for number in numbers[1:]
        ):
            raise ValueError(
                f"repeated_chapter_title_shape:{shape}:"
                f"{numbers[0]}-{numbers[2]}"
            )
