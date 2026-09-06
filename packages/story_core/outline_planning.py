from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.character_profiles import (
    BackgroundProfile,
    CurrentLifeProfile,
    IdentityProfile,
    RelationshipNote,
    StoryDriveProfile,
    is_placeholder_character_name,
)
from packages.story_core.elastic_outline import DETAIL_WINDOW
from packages.story_core.models import CharacterPerformanceProfile
from packages.story_core.project_outline import (
    ArcOutline,
    ProjectOutline,
    normalize_project_outline,
    select_outline_context,
)
from packages.story_core.trope_runtime import compact_trope_candidates
from packages.story_core.volume_outline import MIN_VOLUME_CHAPTERS, validate_volume_structure


CharacterTier = Literal[
    "protagonist",
    "stage_antagonist",
    "long_term_antagonist",
    "supporting",
]

INITIAL_OUTLINE_CHAPTER_COUNT = DETAIL_WINDOW


def _volume_validation_input(
    arcs: list[Any],
    *,
    core_ending_chapter: int,
    fallback_outline: dict[str, Any] | None = None,
    committed_through_chapter: int | None = None,
    require_future_coverage: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    generated = [
        ArcOutline.model_validate(arc).model_dump(mode="json") for arc in arcs
    ]
    if not fallback_outline or not committed_through_chapter:
        return generated, core_ending_chapter

    fallback_arcs = {
        arc.id: arc.model_dump(mode="json")
        for arc in ProjectOutline.model_validate(
            {
                "overall": fallback_outline.get("overall", {}),
                "arcs": fallback_outline.get("arcs", []),
                "chapters": [],
            }
        ).arcs
    }
    immutable_ids = {
        str(arc.get("id"))
        for arc in generated
        if int(arc.get("end_chapter") or 0) <= committed_through_chapter
        and fallback_arcs.get(str(arc.get("id"))) == arc
    }
    mutable = [arc for arc in generated if str(arc.get("id")) not in immutable_ids]
    if not mutable:
        if require_future_coverage and any(
            int(arc.get("end_chapter") or 0) > committed_through_chapter
            for arc in fallback_arcs.values()
        ):
            return generated, core_ending_chapter
        return [
            {
                "id": "committed-history",
                "start_chapter": 1,
                "end_chapter": 1,
                "is_final_arc": True,
                "story_nodes": [
                    {
                        "start_chapter": 1,
                        "end_chapter": 1,
                        "objective": "Preserve committed history.",
                        "pressure": "Preserve committed history.",
                        "turn": "Preserve committed history.",
                        "payoff": "Preserve committed history.",
                        "next_effect": "Preserve committed history.",
                    }
                ],
            }
        ], 1

    immutable_end = max(
        (
            int(arc["end_chapter"])
            for arc in generated
            if str(arc.get("id")) in immutable_ids
        ),
        default=0,
    )
    if immutable_end == 0:
        return mutable, core_ending_chapter

    anchor_end = MIN_VOLUME_CHAPTERS
    offset = anchor_end - immutable_end
    projected = [
        {
            "id": "committed-history",
            "start_chapter": 1,
            "end_chapter": anchor_end,
            "is_final_arc": False,
            "story_nodes": [
                {
                    "start_chapter": start,
                    "end_chapter": min(start + 14, anchor_end),
                    "objective": "Preserve committed history.",
                    "pressure": "Preserve committed history.",
                    "turn": "Preserve committed history.",
                    "payoff": "Preserve committed history.",
                    "next_effect": "Preserve committed history.",
                }
                for start in range(1, anchor_end + 1, 15)
            ],
        }
    ]
    for arc in mutable:
        shifted = deepcopy(arc)
        shifted["start_chapter"] = int(shifted["start_chapter"]) + offset
        shifted["end_chapter"] = int(shifted["end_chapter"]) + offset
        for node in shifted.get("story_nodes", []):
            node["start_chapter"] = int(node["start_chapter"]) + offset
            node["end_chapter"] = int(node["end_chapter"]) + offset
        projected.append(shifted)
    return projected, core_ending_chapter + offset


class _PlanningModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanningCharacterCard(_PlanningModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    character_tier: CharacterTier
    first_appearance: int = Field(default=0, ge=0)
    identity_profile: IdentityProfile
    background_profile: BackgroundProfile
    current_life_profile: CurrentLifeProfile
    story_drive: StoryDriveProfile
    performance_profile: CharacterPerformanceProfile = Field(default_factory=CharacterPerformanceProfile)
    dialogue_examples: list[str] = Field(min_length=2, max_length=3)
    relationship_notes: list[RelationshipNote] = Field(default_factory=list)


class GeneratedOutlinePlan(_PlanningModel):
    outline: ProjectOutline
    characters: list[PlanningCharacterCard]


_GENERATED_OVERALL_NARRATIVE_FIELDS = (
    "story",
    "theme_statement",
    "foreground_story",
    "background_story",
    "book_objective",
    "ending_image",
    "protagonist_goal",
    "main_conflict",
    "growth_path",
    "ending_direction",
    "ending_contract",
)
_GENERATED_ARC_NARRATIVE_FIELDS = (
    "title",
    "goal",
    "obstacle",
    "payoff",
    "emotional_curve",
    "hook_plan",
    "irreversible_change",
    "end_state",
    "game_line_payoff",
    "reality_line_payoff",
)
_GENERATED_CHAPTER_NARRATIVE_FIELDS = (
    "title",
    "goal",
    "obstacle",
    "action",
    "turn",
    "payoff",
    "ending_hook",
)
_CHAPTER_CONTRACT_FIELDS = {
    "payoff_contract": (
        "need",
        "pressure",
        "hidden_advantage",
        "concrete_reward",
    ),
    "chapter_sop": (
        "opening_carry",
        "mid_feedback",
        "turn",
        "ending_hook",
    ),
}
CHAPTER_SOP_MODULE_ID = "commercial-shuangwen::chapter-sop"
_ABSTRACT_CHAPTER_CONTRACT_NOUNS = frozenset(
    {
        "压力",
        "冲突",
        "奖励",
        "工作",
        "情况",
        "问题",
        "反馈",
        "悬念",
        "进展",
        "变化",
        "收获",
        "爽点",
        "局势",
        "紧张感",
        "事情",
        "剧情",
        "伏笔",
    }
)
_GENERIC_CHAPTER_CONTRACT_ACTIONS = frozenset(
    {
        "继续",
        "进行",
        "进一步",
        "升级",
        "推进",
        "出现",
        "得到",
        "有所",
        "留下",
        "发生",
        "产生",
        "变得",
        "获得",
        "设置",
        "制造",
        "埋下",
        "提升",
        "增加",
        "加剧",
        "恶化",
        "处理",
        "发展",
        "行动",
        "调查",
        "continue",
    }
)
_GENERIC_CHAPTER_CONTRACT_MODIFIERS = frozenset(
    {
        "新的",
        "新",
        "重要",
        "更加",
        "复杂",
        "不简单",
        "待定",
        "placeholder",
        "tbd",
        "todo",
        "有",
    }
)
_GENERIC_CHAPTER_CONTRACT_FILLERS = frozenset(
    {
        "一下",
        "看看",
        "呀",
        "呢",
        "吧",
        "呗",
        "啦",
        "的",
        "了",
        "时",
        "中",
        "后",
        "以后",
        "阶段",
        "待续",
        "些",
        "化",
        "并",
        "和",
        "更多",
        "一些",
        "一点",
        "一个",
        "随后",
        "后面",
        "后续",
        "再",
        "补",
        "细节",
        "在",
        "下一",
        "一轮",
        "决定",
        "关于",
        "安排",
        "严重",
        "观察",
    }
)


def _chapter_contract_term_pattern(values: frozenset[str]) -> re.Pattern[str]:
    alternatives = "|".join(
        re.escape(value) for value in sorted(values, key=len, reverse=True)
    )
    return re.compile(alternatives, re.IGNORECASE)


_GENERIC_CHAPTER_CONTRACT_VOCABULARY_PATTERN = _chapter_contract_term_pattern(
    _GENERIC_CHAPTER_CONTRACT_ACTIONS
    | _GENERIC_CHAPTER_CONTRACT_MODIFIERS
    | _GENERIC_CHAPTER_CONTRACT_FILLERS
    | _ABSTRACT_CHAPTER_CONTRACT_NOUNS
)
_CHAPTER_CONTRACT_PUNCTUATION_PATTERN = re.compile(r"[\W_]+", re.UNICODE)
_CJK_CHARACTER_PATTERN = re.compile(r"[\u3400-\u9fff]")
_NUMBER_TOKEN = (
    r"(?:\d+(?:,\d{3})*(?:\.\d+)?[万亿]?"
    r"|[零〇一二两三四五六七八九十百千万亿]+)"
)
_PERCENTAGE_TOKEN = rf"(?:\d+(?:\.\d+)?\s*[%％]|百分之{_NUMBER_TOKEN})"
_FEE_TERM = r"(?:手续费|服务费|费率)"
_EXPLICIT_CURRENCY_PATTERN = re.compile(
    rf"{_NUMBER_TOKEN}\s*(?:金币|银币|铜币|元)"
    rf"|(?:金币|银币|铜币)\s*{_NUMBER_TOKEN}"
    rf"|(?:人民币|[￥¥])\s*{_NUMBER_TOKEN}"
)
_SMALL_CURRENCY_UNIT_PATTERN = re.compile(rf"{_NUMBER_TOKEN}\s*(块|角|分)")
_BARE_AMOUNT_TOKEN = (
    rf"{_NUMBER_TOKEN}(?![\d零〇一二两三四五六七八九十百千万亿])"
)
_FINANCIAL_AMOUNT_RELATION = (
    r"(?:为|是|达到|达|剩余|变为|还有|只剩|仅剩|需付|降至|升至|约为|约|人民币|[￥¥:：、])?"
)
_NONFINANCIAL_AMOUNT_SUFFIX = r"(?:级|章|只|件|个|次|天|小时|分钟|秒|[%％])"
_FINANCIAL_KEYWORD_AMOUNT_PATTERN = re.compile(
    rf"(?:余额|成交价|房租|最低还款|售价|单价|价格|成本|支出)"
    rf"\s*{_FINANCIAL_AMOUNT_RELATION}\s*{_BARE_AMOUNT_TOKEN}"
    rf"(?!\s*{_NONFINANCIAL_AMOUNT_SUFFIX})"
)
_INCOME_AMOUNT_PATTERN = re.compile(
    rf"收入\s*{_FINANCIAL_AMOUNT_RELATION}\s*{_BARE_AMOUNT_TOKEN}"
    rf"(?!\s*(?:名|人|位|{_NONFINANCIAL_AMOUNT_SUFFIX}))"
)
_OUTLINE_CLAUSE_SEPARATOR_PATTERN = re.compile(r"[，。；！？\n]")
_DIRECT_FEE_PERCENTAGE_PATTERN = re.compile(
    rf"{_FEE_TERM}(?:比例)?\s*(?:"
    rf"{_PERCENTAGE_TOKEN}"
    rf"|(?:为|是|高达|达到|设为|定为|不得超过|不超过|最高|最低|调整为|收取|扣除)"
    rf"\s*{_PERCENTAGE_TOKEN}"
    rf"|占.*?的?\s*{_PERCENTAGE_TOKEN}"
    rf")"
)
_FEE_COLLECTION_PERCENTAGE_PATTERN = re.compile(
    rf"{_FEE_TERM}.*?"
    rf"(?:按|按照).*?(?:"
    rf"(?:收取|扣除)\s*{_PERCENTAGE_TOKEN}"
    rf"|{_PERCENTAGE_TOKEN}.*?(?:收取|扣除)"
    rf")"
)
_PERCENTAGE_BEFORE_FEE_PATTERN = re.compile(
    rf"{_PERCENTAGE_TOKEN}\s*(?:"
    rf"的?\s*{_FEE_TERM}"
    rf"|(?:的\s*)?(?:比例\s*)?(?:收取|扣除)\s*{_FEE_TERM}"
    rf"|作为\s*{_FEE_TERM}"
    rf")"
)
_NON_FEE_METRIC_BEFORE_PERCENTAGE_PATTERN = re.compile(
    r"(?P<metric>[\u4e00-\u9fff]{1,8}(?:率|度|值)|血量|法力|伤害|经验|收益)"
    r"\s*(?:为|是|达到|达|提升|提高|恢复|降低|降至|升至)?\s*$"
)


def _require_text(value: str, error: str) -> None:
    if not str(value or "").strip():
        raise ValueError(error)


def _chapter_contract_section(chapter: Any, section_name: str) -> Any:
    if isinstance(chapter, dict):
        return chapter.get(section_name)
    return getattr(chapter, section_name, None)


def _chapter_contract_value(section: Any, field_name: str) -> Any:
    if isinstance(section, dict):
        return section.get(field_name)
    return getattr(section, field_name, None)


def _concrete_chapter_contract_residue(value: str) -> str:
    normalized = _CHAPTER_CONTRACT_PUNCTUATION_PATTERN.sub(
        "",
        unicodedata.normalize("NFKC", value).casefold(),
    )
    residue = _GENERIC_CHAPTER_CONTRACT_VOCABULARY_PATTERN.sub("", normalized)
    return "".join(_CJK_CHARACTER_PATTERN.findall(residue))


def _is_generic_chapter_contract_value(value: str) -> bool:
    return len(_concrete_chapter_contract_residue(value)) < 2


def validate_concrete_chapter_contract(
    chapter: Any,
    *,
    chapter_number: int | None = None,
) -> None:
    """Require the eight observable chapter-contract values."""

    number = chapter_number
    if number is None:
        raw_number = (
            chapter.get("chapter_number")
            if isinstance(chapter, dict)
            else getattr(chapter, "chapter_number", 0)
        )
        number = int(raw_number or 0)
    for section_name, field_names in _CHAPTER_CONTRACT_FIELDS.items():
        section = _chapter_contract_section(chapter, section_name)
        if section is None:
            raise ValueError(f"chapter_contract_missing:{number}:{section_name}")
        for field_name in field_names:
            value = _chapter_contract_value(section, field_name)
            location = f"{section_name}.{field_name}"
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"chapter_contract_missing:{number}:{location}")
            if _is_generic_chapter_contract_value(value):
                raise ValueError(
                    f"chapter_contract_not_concrete:{number}:{location}"
                )


def apply_chapter_contract_policy(
    chapter: dict[str, Any],
    *,
    require_chapter_contracts: bool,
    chapter_number: int | None = None,
) -> dict[str, Any]:
    """Return a copy with contracts strictly validated or fully removed."""

    normalized = dict(chapter)
    if require_chapter_contracts:
        validate_concrete_chapter_contract(
            normalized,
            chapter_number=chapter_number,
        )
    else:
        for section_name in _CHAPTER_CONTRACT_FIELDS:
            normalized.pop(section_name, None)
    return normalized


def _validate_generated_chapter_contracts(plan: GeneratedOutlinePlan) -> None:
    for chapter in plan.outline.chapters:
        validate_concrete_chapter_contract(chapter)


def _contains_monetary_amount(value: str) -> bool:
    explicit_currency = _EXPLICIT_CURRENCY_PATTERN.search(value)
    keyword_amount = _FINANCIAL_KEYWORD_AMOUNT_PATTERN.search(value)
    income_amount = _INCOME_AMOUNT_PATTERN.search(value)
    if explicit_currency or keyword_amount or income_amount:
        return True
    for match in _SMALL_CURRENCY_UNIT_PATTERN.finditer(value):
        unit = match.group(1)
        following = value[match.end() : match.end() + 1]
        if unit in {"块", "角"}:
            followed_by_classifier = (
                following
                and "\u4e00" <= following <= "\u9fff"
                and following != "钱"
            )
            if followed_by_classifier:
                continue
            return True
        prefix = value[max(0, match.start() - 10) : match.start()]
        remainder = value[match.end() :]
        if (
            following
            and "\u4e00" <= following <= "\u9fff"
            and following != "钱"
        ) or re.match(r"\d+\s*秒", remainder) or re.search(
            r"(?:评分|得分|分数|拿到|得到|获得).{0,8}$",
            prefix,
        ):
            continue
        return True
    return False


def _contains_financial_percentage(value: str) -> bool:
    for clause in _OUTLINE_CLAUSE_SEPARATOR_PATTERN.split(value):
        if any(
            pattern.search(clause)
            for pattern in (
                _DIRECT_FEE_PERCENTAGE_PATTERN,
                _FEE_COLLECTION_PERCENTAGE_PATTERN,
                _PERCENTAGE_BEFORE_FEE_PATTERN,
            )
        ):
            return True
        if not re.search(_FEE_TERM, clause):
            continue
        for percentage in re.finditer(_PERCENTAGE_TOKEN, clause):
            if re.match(r"\s*(?:概率|几率)", clause[percentage.end() :]):
                continue
            metric_match = _NON_FEE_METRIC_BEFORE_PERCENTAGE_PATTERN.search(
                clause[: percentage.start()]
            )
            if metric_match and "费率" not in metric_match.group("metric"):
                continue
            return True
    return False


def _sanitize_generated_narrative_value(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    if not (
        _contains_monetary_amount(normalized)
        or _contains_financial_percentage(normalized)
    ):
        return value

    cleaned = _EXPLICIT_CURRENCY_PATTERN.sub("一笔待定款项", normalized)
    cleaned = _FINANCIAL_KEYWORD_AMOUNT_PATTERN.sub("一笔待定款项", cleaned)
    cleaned = _INCOME_AMOUNT_PATTERN.sub("获得一笔待定收入", cleaned)
    clauses = re.split(r"([，。；！？\n])", cleaned)
    for index in range(0, len(clauses), 2):
        if _contains_financial_percentage(clauses[index]):
            clauses[index] = re.sub(_PERCENTAGE_TOKEN, "按平台规则", clauses[index])
    cleaned = "".join(clauses)
    if _contains_monetary_amount(cleaned) or _contains_financial_percentage(cleaned):
        return "涉及款项按既定规则结算，不在大纲中写明具体数额。"
    return cleaned


def sanitize_generated_outline_amounts(payload: Any) -> dict[str, Any]:
    """Remove accidental financial hard anchors before strict validation."""

    plan = GeneratedOutlinePlan.model_validate(payload)
    for field_name in _GENERATED_OVERALL_NARRATIVE_FIELDS:
        setattr(
            plan.outline.overall,
            field_name,
            _sanitize_generated_narrative_value(
                getattr(plan.outline.overall, field_name)
            ),
        )
    for arc in plan.outline.arcs:
        for field_name in _GENERATED_ARC_NARRATIVE_FIELDS:
            setattr(
                arc,
                field_name,
                _sanitize_generated_narrative_value(getattr(arc, field_name)),
            )
        arc.long_term_antagonist_traces = [
            _sanitize_generated_narrative_value(item)
            for item in arc.long_term_antagonist_traces
        ]
        arc.key_results = [
            _sanitize_generated_narrative_value(item)
            for item in arc.key_results
        ]
        for field_name in ("continue_route", "close_route"):
            setattr(
                arc.extension_gate,
                field_name,
                _sanitize_generated_narrative_value(
                    getattr(arc.extension_gate, field_name)
                ),
            )
    for chapter in plan.outline.chapters:
        for field_name in _GENERATED_CHAPTER_NARRATIVE_FIELDS:
            setattr(
                chapter,
                field_name,
                _sanitize_generated_narrative_value(getattr(chapter, field_name)),
            )
        for section_name, field_names in _CHAPTER_CONTRACT_FIELDS.items():
            section = getattr(chapter, section_name)
            if section is None:
                continue
            for field_name in field_names:
                setattr(
                    section,
                    field_name,
                    _sanitize_generated_narrative_value(
                        getattr(section, field_name)
                    ),
                )
    return plan.model_dump(mode="json")


def _validate_generated_narrative_value(value: str, location: str) -> None:
    normalized = unicodedata.normalize("NFKC", value)
    if _contains_monetary_amount(normalized) or _contains_financial_percentage(
        normalized
    ):
        raise ValueError(f"generated_outline_contains_monetary_amount:{location}")


def _validate_generated_outline_amounts(plan: GeneratedOutlinePlan) -> None:
    overall = plan.outline.overall
    for field_name in _GENERATED_OVERALL_NARRATIVE_FIELDS:
        _validate_generated_narrative_value(
            getattr(overall, field_name),
            f"overall:{field_name}",
        )

    for arc in plan.outline.arcs:
        for field_name in _GENERATED_ARC_NARRATIVE_FIELDS:
            _validate_generated_narrative_value(
                getattr(arc, field_name),
                f"arc:{arc.id}:{field_name}",
            )
        for index, trace in enumerate(arc.long_term_antagonist_traces):
            _validate_generated_narrative_value(
                trace,
                f"arc:{arc.id}:long_term_antagonist_traces:{index}",
            )
        for index, result in enumerate(arc.key_results):
            _validate_generated_narrative_value(
                result,
                f"arc:{arc.id}:key_results:{index}",
            )
        for field_name in ("continue_route", "close_route"):
            _validate_generated_narrative_value(
                getattr(arc.extension_gate, field_name),
                f"arc:{arc.id}:extension_gate:{field_name}",
            )

    for chapter in plan.outline.chapters:
        for field_name in _GENERATED_CHAPTER_NARRATIVE_FIELDS:
            _validate_generated_narrative_value(
                getattr(chapter, field_name),
                f"{chapter.chapter_number}:{field_name}",
            )
        for section_name, field_names in _CHAPTER_CONTRACT_FIELDS.items():
            section = getattr(chapter, section_name)
            if section is None:
                continue
            for field_name in field_names:
                _validate_generated_narrative_value(
                    getattr(section, field_name),
                    f"{chapter.chapter_number}:{section_name}.{field_name}",
                )


def validate_generated_opening_plan(
    payload: Any,
    *,
    expected_chapter_numbers: list[int] | None = None,
    trope_templates: list[dict[str, Any]] | None = None,
    expected_primary_trope_id: str | None = None,
    fallback_outline: dict[str, Any] | None = None,
    committed_through_chapter: int | None = None,
    require_chapter_contracts: bool = False,
    enforce_full_opening_roster: bool = False,
    allow_established_roster: bool = False,
) -> GeneratedOutlinePlan:
    """Validate an AI-generated opening plan without constraining manual drafts."""

    plan = GeneratedOutlinePlan.model_validate(payload)
    _validate_generated_outline_amounts(plan)
    volume_arcs, volume_ending = _volume_validation_input(
        plan.outline.arcs,
        core_ending_chapter=plan.outline.overall.core_ending_chapter,
        fallback_outline=fallback_outline,
        committed_through_chapter=(
            committed_through_chapter
            if committed_through_chapter is not None
            else (expected_chapter_numbers or [1])[0] - 1
        ),
    )
    validate_volume_structure(volume_arcs, core_ending_chapter=volume_ending)
    if require_chapter_contracts:
        _validate_generated_chapter_contracts(plan)
    overall = plan.outline.overall
    if (
        overall.planned_length > 0
        and plan.outline.arcs
        and overall.core_ending_chapter
        not in {arc.end_chapter for arc in plan.outline.arcs}
    ):
        raise ValueError("core_ending_not_arc_boundary")
    for field_name in (
        "story",
        "theme_statement",
        "foreground_story",
        "background_story",
        "book_objective",
        "ending_image",
        "protagonist_goal",
        "main_conflict",
        "growth_path",
        "ending_direction",
    ):
        _require_text(getattr(overall, field_name), f"missing_overall_field:{field_name}")

    for arc in plan.outline.arcs:
        for field_name in (
            "emotional_curve",
            "hook_plan",
            "irreversible_change",
        ):
            _require_text(
                getattr(arc, field_name),
                f"missing_arc_field:{arc.id}:{field_name}",
            )
        if len(arc.key_results) != 3 or any(not item.strip() for item in arc.key_results):
            raise ValueError(f"invalid_arc_key_results:{arc.id}")

    tier_counts = {
        tier: sum(card.character_tier == tier for card in plan.characters)
        for tier in (
            "protagonist",
            "stage_antagonist",
            "long_term_antagonist",
            "supporting",
        )
    }
    for tier in ("protagonist", "stage_antagonist", "long_term_antagonist"):
        if tier_counts[tier] < 1:
            raise ValueError(f"missing_character_tier:{tier}")
    if enforce_full_opening_roster:
        if not 10 <= len(plan.characters) <= 15:
            raise ValueError("character_count_out_of_range")
        if tier_counts["protagonist"] != 1:
            raise ValueError("invalid_protagonist_count")
        if tier_counts["supporting"] < 5:
            raise ValueError("insufficient_supporting_characters")
    elif allow_established_roster:
        # Regenerate payloads carry the book's established cast: legacy books
        # have 4-6 cards, books opened under the full-roster rule have 10-15.
        if not 4 <= len(plan.characters) <= 15:
            raise ValueError("character_count_out_of_range")
    elif not 4 <= len(plan.characters) <= 6:
        raise ValueError("character_count_out_of_range")

    names = [card.name.strip() for card in plan.characters]
    if len(names) != len(set(names)):
        raise ValueError("duplicate_character_name")
    for name in names:
        if is_placeholder_character_name(name):
            raise ValueError(f"placeholder_character_name:{name}")

    opening_arcs = [arc for arc in plan.outline.arcs if arc.start_chapter == 1]
    if not opening_arcs:
        raise ValueError("opening_arc_required")
    opening_arc = opening_arcs[0]
    if is_placeholder_character_name(opening_arc.stage_antagonist):
        raise ValueError(
            f"placeholder_arc_antagonist:{opening_arc.id}:{opening_arc.stage_antagonist}"
        )
    stage_names = {card.name for card in plan.characters if card.character_tier == "stage_antagonist"}
    if opening_arc.stage_antagonist not in stage_names:
        raise ValueError("stage_antagonist_card_mismatch")
    if not opening_arc.long_term_antagonist_traces:
        raise ValueError("long_term_antagonist_trace_required")

    expected = (
        list(range(1, 31))
        if expected_chapter_numbers is None
        else expected_chapter_numbers
    )
    chapter_numbers = [chapter.chapter_number for chapter in plan.outline.chapters]
    if chapter_numbers != expected:
        raise ValueError("generated_chapters_do_not_match_target_window")
    known_names = set(names)
    for chapter in plan.outline.chapters:
        for name in chapter.cast:
            if name not in known_names:
                raise ValueError(f"missing_character_card:{name}")

    for card in plan.characters:
        _require_text(card.identity_profile.origin, f"missing_character_origin:{card.name}")
        _require_text(card.identity_profile.current_identity, f"missing_character_identity:{card.name}")
        _require_text(card.identity_profile.occupation, f"missing_character_occupation:{card.name}")
        _require_text(card.story_drive.immediate_goal, f"missing_character_goal:{card.name}")
        _require_text(card.story_drive.failure_stakes, f"missing_character_stakes:{card.name}")
    if trope_templates is not None:
        validate_generated_trope_selection(
            plan,
            trope_templates,
            expected_primary_trope_id=expected_primary_trope_id,
            fallback_outline=fallback_outline,
            committed_through_chapter=committed_through_chapter,
        )
    return plan


def validate_generated_continuation_plan(
    payload: Any,
    *,
    expected_chapter_numbers: list[int],
    existing_character_names: set[str],
    trope_templates: list[dict[str, Any]] | None = None,
    expected_primary_trope_id: str | None = None,
    fallback_outline: dict[str, Any] | None = None,
    committed_through_chapter: int | None = None,
    require_chapter_contracts: bool = False,
) -> GeneratedOutlinePlan:
    """Validate an incremental plan without requiring opening-only structure."""

    plan = GeneratedOutlinePlan.model_validate(payload)
    _validate_generated_outline_amounts(plan)
    volume_arcs, volume_ending = _volume_validation_input(
        plan.outline.arcs,
        core_ending_chapter=plan.outline.overall.core_ending_chapter,
        fallback_outline=fallback_outline,
        committed_through_chapter=(
            committed_through_chapter
            if committed_through_chapter is not None
            else (expected_chapter_numbers or [1])[0] - 1
        ),
    )
    if volume_arcs:
        validate_volume_structure(volume_arcs, core_ending_chapter=volume_ending)
    if require_chapter_contracts:
        _validate_generated_chapter_contracts(plan)
    chapter_numbers = [chapter.chapter_number for chapter in plan.outline.chapters]
    if chapter_numbers != expected_chapter_numbers:
        raise ValueError("generated_chapters_do_not_match_target_window")

    names = [card.name.strip() for card in plan.characters]
    if len(names) != len(set(names)):
        raise ValueError("duplicate_character_name")
    existing_names = {
        str(name).strip() for name in existing_character_names if str(name).strip()
    }
    repeated = next((name for name in names if name in existing_names), None)
    if repeated is not None:
        raise ValueError(f"duplicate_existing_character_card:{repeated}")

    known_names = {*existing_names, *names}
    for chapter in plan.outline.chapters:
        for name in chapter.cast:
            if name not in known_names:
                raise ValueError(f"missing_character_card:{name}")

    for card in plan.characters:
        _require_text(card.identity_profile.origin, f"missing_character_origin:{card.name}")
        _require_text(card.identity_profile.current_identity, f"missing_character_identity:{card.name}")
        _require_text(card.identity_profile.occupation, f"missing_character_occupation:{card.name}")
        _require_text(card.story_drive.immediate_goal, f"missing_character_goal:{card.name}")
        _require_text(card.story_drive.failure_stakes, f"missing_character_stakes:{card.name}")
    if trope_templates is not None:
        validate_generated_trope_selection(
            plan,
            trope_templates,
            expected_primary_trope_id=expected_primary_trope_id,
            fallback_outline=fallback_outline,
            committed_through_chapter=committed_through_chapter,
        )
    return plan


def validate_generated_trope_selection(
    plan: Any,
    trope_templates: list[dict[str, Any]],
    expected_primary_trope_id: str | None = None,
    fallback_outline: dict[str, Any] | None = None,
    committed_through_chapter: int | None = None,
) -> GeneratedOutlinePlan:
    """Validate generated trope locks against the active project candidates."""

    validated = GeneratedOutlinePlan.model_validate(plan)
    candidates = compact_trope_candidates(trope_templates)
    candidates_by_id = {str(item["id"]): item for item in candidates}
    primary_trope_id = validated.outline.overall.primary_trope_id
    expected = str(expected_primary_trope_id or "").strip()
    if expected and primary_trope_id != expected:
        raise ValueError("unexpected_primary_trope_id")
    if not expected:
        fallback_primary = None
        if fallback_outline is not None:
            fallback_overall = (
                fallback_outline.get("overall")
                if isinstance(fallback_outline.get("overall"), dict)
                else {}
            )
            fallback_primary = fallback_overall.get("primary_trope_id")
        legacy_unlocked = (
            fallback_outline is not None
            and primary_trope_id is None
            and fallback_primary is None
        )
        if candidates_by_id and primary_trope_id not in candidates_by_id and not legacy_unlocked:
            raise ValueError("invalid_primary_trope_id")
        if not candidates_by_id and primary_trope_id is not None:
            raise ValueError("unexpected_primary_trope_id")

    fallback = (
        normalize_project_outline(fallback_outline)
        if fallback_outline is not None
        else None
    )
    fallback_arcs = {
        str(arc["id"]): arc
        for arc in (fallback or {}).get("arcs", [])
    }
    fallback_chapters = {
        int(chapter["chapter_number"]): chapter
        for chapter in (fallback or {}).get("chapters", [])
    }
    committed_through = max(0, int(committed_through_chapter or 0))

    for arc in validated.outline.arcs:
        if arc.trope_id in candidates_by_id:
            continue
        fallback_arc = fallback_arcs.get(arc.id)
        if (
            fallback_arc is not None
            and arc.trope_id == fallback_arc.get("trope_id")
        ):
            continue
        if arc.trope_id is None and not candidates_by_id:
            continue
        error = (
            "unexpected_arc_trope_id"
            if not candidates_by_id
            else "invalid_arc_trope_id"
        )
        raise ValueError(f"{error}:{arc.id}")

    outline_payload = validated.outline.model_dump(mode="json")
    if fallback is not None:
        generated_arc_ids = {str(arc["id"]) for arc in outline_payload["arcs"]}
        outline_payload = {
            **outline_payload,
            "arcs": [
                *outline_payload["arcs"],
                *(
                    arc
                    for arc in fallback["arcs"]
                    if arc.get("trope_id") is not None
                    and str(arc["id"]) not in generated_arc_ids
                ),
            ],
        }
    for chapter in validated.outline.chapters:
        beat = chapter.trope_beat
        if beat is None:
            continue
        context = select_outline_context(outline_payload, chapter.chapter_number)
        active_arc = context.get("active_arc")
        active_trope_id = (
            active_arc.get("trope_id")
            if isinstance(active_arc, dict)
            else None
        )
        fallback_chapter = fallback_chapters.get(chapter.chapter_number)
        fallback_context = (
            select_outline_context(fallback, chapter.chapter_number)
            if fallback is not None and fallback_chapter is not None
            else {}
        )
        fallback_active_arc = fallback_context.get("active_arc")
        if (
            chapter.chapter_number <= committed_through
            and fallback_chapter is not None
            and str(active_trope_id or "") not in candidates_by_id
            and beat == fallback_chapter.get("trope_beat")
            and isinstance(active_arc, dict)
            and isinstance(fallback_active_arc, dict)
            and active_arc.get("id") == fallback_active_arc.get("id")
            and active_trope_id == fallback_active_arc.get("trope_id")
        ):
            continue
        active_template = candidates_by_id.get(str(active_trope_id or ""))
        if active_template is None or beat not in active_template.get("beats", []):
            error = (
                "unexpected_chapter_trope_beat"
                if not candidates_by_id
                else "invalid_chapter_trope_beat"
            )
            raise ValueError(f"{error}:{chapter.chapter_number}")
    return validated
