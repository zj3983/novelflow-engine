from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Iterable, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.dual_state import normalize_dual_state


CharacterImportance = Literal["core", "major", "supporting", "minor"]
CharacterNarrativeFunction = Literal[
    "protagonist",
    "ally",
    "rival",
    "mentor",
    "love_interest",
    "stage_antagonist",
    "long_term_antagonist",
    "resource_contact",
    "other",
]
CharacterProfileStatus = Literal["stub", "ready"]


class _ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityProfile(_ProfileModel):
    aliases: list[str] = Field(default_factory=list)
    gender: str = ""
    age: int | None = Field(default=None, ge=0)
    birthplace: str = ""
    origin: str = ""
    current_identity: str = ""
    occupation: str = ""
    affiliation: str = ""


class BackgroundProfile(_ProfileModel):
    family: str = ""
    upbringing: str = ""
    education_or_training: str = ""
    formative_events: list[str] = Field(default_factory=list)
    arrival_reason: str = ""


class CurrentLifeProfile(_ProfileModel):
    residence: str = ""
    livelihood: str = ""
    economic_state: str = ""
    resources_and_ability: str = ""
    authority_scope: str = ""
    immediate_problem: str = ""


class StoryDriveProfile(_ProfileModel):
    long_term_goal: str = ""
    immediate_goal: str = ""
    motivation: str = ""
    failure_stakes: str = ""
    hidden_matters: list[str] = Field(default_factory=list)
    main_conflict_reason: str = ""


class RelationshipNote(_ProfileModel):
    target: str
    relation_type: str = ""
    history: str = ""
    current_attitude: str = ""
    shared_interest_or_conflict: str = ""
    known_facts: list[str] = Field(default_factory=list)
    unknown_facts: list[str] = Field(default_factory=list)


_NESTED_MODELS: dict[str, type[BaseModel]] = {
    "identity_profile": IdentityProfile,
    "background_profile": BackgroundProfile,
    "current_life_profile": CurrentLifeProfile,
    "story_drive": StoryDriveProfile,
}


# These entries describe a service, rule, or interface rather than a person.
# Keep them out of character cards so the writer does not invent a personality
# for a market function that should be represented by the world rules.
_NON_CHARACTER_NAMES = frozenset(
    {
        "论坛",
        "公共频道",
        "交易行告示牌",
        "清道夫委托",
        "系统公告",
        "白河仓库收购方",
    }
)
_NON_CHARACTER_ROLES = frozenset(
    {
        "信息源",
        "玩家群体",
        "市场机制",
        "任务线",
        "服务设施",
        "系统机制",
        "收购方NPC",
    }
)
_PLACEHOLDER_CHARACTER_NAMES = frozenset(
    {
        "底层执行者",
        "阶段对手",
        "阶段反派",
        "长期反派",
        "最终反派",
        "幕后黑手",
        "神秘人",
        "数据分析师",
        "开发商高层",
        "辖区民警",
    }
)
_PLACEHOLDER_CHARACTER_PREFIXES = (
    "幕后黑手（",
    "幕后黑手(",
    "阶段反派（",
    "阶段反派(",
    "长期反派（",
    "长期反派(",
)
_MISSING = object()

_LEGACY_TIER_TAXONOMY: dict[str, tuple[CharacterImportance, CharacterNarrativeFunction]] = {
    "protagonist": ("core", "protagonist"),
    "stage_antagonist": ("major", "stage_antagonist"),
    "long_term_antagonist": ("core", "long_term_antagonist"),
    "supporting": ("supporting", "other"),
    "recurring": ("supporting", "other"),
    "recurring_npc": ("supporting", "other"),
}
_NARRATIVE_FUNCTION_MARKERS: tuple[tuple[CharacterNarrativeFunction, tuple[str, ...]], ...] = (
    ("protagonist", ("protagonist", "主角")),
    ("long_term_antagonist", ("long_term_antagonist", "long term antagonist", "长期反派", "最终反派", "幕后反派")),
    ("stage_antagonist", ("stage_antagonist", "stage antagonist", "阶段反派", "阶段对手")),
    ("mentor", ("mentor", "导师", "师父", "师傅")),
    ("love_interest", ("love_interest", "love interest", "感情线", "恋爱对象")),
    ("rival", ("rival", "竞争者", "竞争对手", "宿敌")),
    ("ally", ("ally", "盟友", "伙伴", "队友")),
    ("resource_contact", ("resource_contact", "resource contact", "资源联系人", "情报联系人")),
)
_GENERIC_CHARACTER_CONTENT = frozenset(
    {
        "不断成长",
        "继续成长",
        "变得更强",
        "为了变强",
        "提升实力",
        "推动剧情",
        "推进剧情",
        "关系复杂",
        "双方存在矛盾",
        "存在矛盾",
        "会很惨",
        "承担代价",
        "面对挑战",
        "解决问题",
        "完成目标",
        "获得成长",
        "待补充",
        "待定",
        "tbd",
        "todo",
        "placeholder",
        "冷静聪明谨慎",
        "冷静谨慎",
        "观察后行动",
        "不善言辞",
    }
)
_QUALITY_FIELDS = (
    ("identity_profile", "current_identity"),
    ("current_life_profile", "immediate_problem"),
    ("story_drive", "long_term_goal"),
    ("story_drive", "immediate_goal"),
    ("story_drive", "motivation"),
    ("story_drive", "failure_stakes"),
    ("story_drive", "main_conflict_reason"),
)


def is_placeholder_character_name(value: Any) -> bool:
    """Return whether a generated name is only a role or occupation label."""

    name = unicodedata.normalize("NFKC", str(value or "")).strip()
    return name in _PLACEHOLDER_CHARACTER_NAMES or name.startswith(
        _PLACEHOLDER_CHARACTER_PREFIXES
    )


def is_non_character_card(card: dict[str, Any] | None) -> bool:
    """Return whether a record is a functional entity, not a person."""

    if not isinstance(card, dict):
        return False
    name = str(card.get("name") or "").strip()
    role = str(card.get("role") or "").strip()
    return name in _NON_CHARACTER_NAMES or role in _NON_CHARACTER_ROLES


def filter_character_cards(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only person-like cards while preserving input order and data."""

    return [
        deepcopy(dict(card))
        for card in cards
        if isinstance(card, dict) and not is_non_character_card(card)
    ]


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _taxonomy_token(value: Any) -> str:
    return re.sub(
        r"[_\s-]+",
        "_",
        unicodedata.normalize("NFKC", str(value or "")).strip().casefold(),
    ).strip("_")


def infer_character_taxonomy(
    card: dict[str, Any],
) -> tuple[CharacterImportance, CharacterNarrativeFunction]:
    """Infer the two-axis taxonomy without destroying legacy ``character_tier`` data."""

    legacy_tier = _taxonomy_token(card.get("character_tier"))
    inferred_importance, inferred_function = _LEGACY_TIER_TAXONOMY.get(
        legacy_tier,
        ("supporting", "other"),
    )

    role_text = unicodedata.normalize("NFKC", str(card.get("role") or "")).strip().casefold()
    role_token = _taxonomy_token(role_text)
    role_candidates = (role_text, role_token)
    for narrative_function, markers in _NARRATIVE_FUNCTION_MARKERS:
        if any(marker.casefold() in candidate for marker in markers for candidate in role_candidates):
            inferred_function = narrative_function
            break

    if inferred_function in {"protagonist", "long_term_antagonist"}:
        inferred_importance = "core"
    elif inferred_function in {"stage_antagonist", "mentor", "love_interest"} and not legacy_tier:
        inferred_importance = "major"

    explicit_importance = _taxonomy_token(card.get("importance"))
    if explicit_importance in {"core", "major", "supporting", "minor"}:
        inferred_importance = explicit_importance  # type: ignore[assignment]

    explicit_function = _taxonomy_token(card.get("narrative_function"))
    if explicit_function in {
        "protagonist",
        "ally",
        "rival",
        "mentor",
        "love_interest",
        "stage_antagonist",
        "long_term_antagonist",
        "resource_contact",
        "other",
    }:
        inferred_function = explicit_function  # type: ignore[assignment]

    return inferred_importance, inferred_function


def _profile_field(card: dict[str, Any], section: str, field: str) -> str:
    raw_section = card.get(section)
    if not isinstance(raw_section, dict):
        return ""
    return str(raw_section.get(field) or "").strip()


def _looks_generic_character_content(value: Any) -> bool:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if not text:
        return False
    compact = re.sub(r"[\s，。！？、；;,.!?：:（）()\-_]+", "", text)
    return compact in _GENERIC_CHARACTER_CONTENT


def is_generic_character_content(value: Any) -> bool:
    """Public predicate used by seed-level quality gates."""

    return _looks_generic_character_content(value)


def character_profile_quality_issues(card: dict[str, Any]) -> list[str]:
    """Return actionable quality failures for a concrete, writer-usable character card.

    This validator deliberately targets obvious emptiness and placeholder language rather
    than trying to judge prose style. ``stub`` cards may be incomplete by design; they are
    still checked for mechanically duplicated motivation so bad generated data is visible.
    """

    importance, narrative_function = infer_character_taxonomy(card)
    status = _taxonomy_token(card.get("profile_status"))
    issues: list[str] = []

    immediate_goal = _profile_field(card, "story_drive", "immediate_goal")
    motivation = _profile_field(card, "story_drive", "motivation")
    if immediate_goal and motivation and _taxonomy_token(immediate_goal) == _taxonomy_token(motivation):
        issues.append("motivation_duplicates_immediate_goal")

    for section, field in _QUALITY_FIELDS:
        value = _profile_field(card, section, field)
        if value and _looks_generic_character_content(value):
            issues.append(f"generic:{section}.{field}")

    if status != "stub" and importance in {"core", "major"}:
        required = [
            ("identity_profile", "current_identity"),
            ("current_life_profile", "immediate_problem"),
            ("story_drive", "immediate_goal"),
            ("story_drive", "motivation"),
            ("story_drive", "failure_stakes"),
        ]
        if narrative_function in {"protagonist", "long_term_antagonist"}:
            required.append(("story_drive", "long_term_goal"))
        for section, field in required:
            if not _profile_field(card, section, field):
                issues.append(f"missing:{section}.{field}")


    if status != "stub":
        function_required: list[tuple[str, str]] = []
        if narrative_function == "protagonist":
            function_required = [
                ("identity_profile", "origin"),
                ("performance_profile", "speech_style"),
                ("performance_profile", "action_style"),
            ]
        elif narrative_function == "stage_antagonist":
            function_required = [
                ("current_life_profile", "authority_scope"),
                ("story_drive", "main_conflict_reason"),
                ("performance_profile", "action_style"),
            ]
        elif narrative_function == "long_term_antagonist":
            function_required = [
                ("current_life_profile", "authority_scope"),
                ("story_drive", "long_term_goal"),
                ("story_drive", "main_conflict_reason"),
            ]
        elif importance in {"supporting", "minor"}:
            function_required = [("identity_profile", "current_identity")]
        for section, field in function_required:
            if not _profile_field(card, section, field):
                issues.append(f"missing:{section}.{field}")

        if narrative_function in {"protagonist", "long_term_antagonist"}:
            drive = card.get("story_drive")
            hidden = drive.get("hidden_matters", []) if isinstance(drive, dict) else []
            if not any(str(item).strip() for item in hidden):
                issues.append("missing:story_drive.hidden_matters")

        if not any(
            isinstance(item, dict) and str(item.get("target") or "").strip()
            for item in card.get("relationship_notes", [])
        ):
            issues.append("missing:relationship_notes")
        if importance in {"core", "major"} and len(
            [item for item in card.get("dialogue_examples", []) if str(item).strip()]
        ) < 2:
            issues.append("missing:dialogue_examples")

    return issues


def character_profile_completeness(card: dict[str, Any]) -> int:
    """Return a conservative 0-100 completeness score for workbench status display."""

    values = [_profile_field(card, section, field) for section, field in _QUALITY_FIELDS]
    dialogue = [str(item).strip() for item in card.get("dialogue_examples", []) if str(item).strip()]
    relations = [item for item in card.get("relationship_notes", []) if isinstance(item, dict)]
    checks = [*map(bool, values), bool(dialogue), bool(relations)]
    return round(sum(checks) * 100 / len(checks)) if checks else 0


def infer_character_profile_status(card: dict[str, Any]) -> CharacterProfileStatus:
    """Treat incomplete important characters as stubs instead of completed detail cards."""

    explicit = _taxonomy_token(card.get("profile_status"))
    if explicit in {"stub", "ready"}:
        return explicit  # type: ignore[return-value]

    importance, narrative_function = infer_character_taxonomy(card)
    if importance in {"core", "major"}:
        required = [
            ("identity_profile", "current_identity"),
            ("current_life_profile", "immediate_problem"),
            ("story_drive", "immediate_goal"),
            ("story_drive", "motivation"),
            ("story_drive", "failure_stakes"),
        ]
        if narrative_function in {"protagonist", "long_term_antagonist"}:
            required.append(("story_drive", "long_term_goal"))
        if not all(_profile_field(card, section, field) for section, field in required):
            return "stub"
        if character_profile_quality_issues({**card, "profile_status": "ready"}):
            return "stub"
        return "ready"

    identity = card.get("identity_profile")
    identity = identity if isinstance(identity, dict) else {}
    has_identity = any(str(identity.get(key) or "").strip() for key in ("current_identity", "occupation", "origin"))
    drive = card.get("story_drive")
    drive = drive if isinstance(drive, dict) else {}
    has_drive = any(str(drive.get(key) or "").strip() for key in ("immediate_goal", "long_term_goal", "motivation"))
    return "ready" if has_identity and has_drive else "stub"


def find_character_homogeneity_issues(cards: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    """Flag exact repeated generated traits across different characters.

    Exact normalized duplicates are intentionally used for the first guardrail: they are
    deterministic, cheap, and avoid false positives from semantically similar but genuinely
    distinct people. More advanced similarity scoring can be layered on later.
    """

    prepared = [dict(card) for card in cards if isinstance(card, dict)]
    fields = (
        ("story_drive", "motivation"),
        ("story_drive", "long_term_goal"),
        ("performance_profile", "speech_style"),
        ("performance_profile", "action_style"),
    )
    issues: dict[str, list[str]] = {}
    for section, field in fields:
        owners: dict[str, list[str]] = {}
        for card in prepared:
            value = _profile_field(card, section, field)
            token = _taxonomy_token(value)
            if len(token) < 4:
                continue
            owners.setdefault(token, []).append(str(card.get("name") or "").strip() or "<unnamed>")
        for names in owners.values():
            unique_names = list(dict.fromkeys(names))
            if len(unique_names) < 2:
                continue
            issue = f"duplicate:{section}.{field}"
            for name in unique_names:
                issues.setdefault(name, []).append(issue)
    return issues


def normalize_speech_style_for_writing(value: Any) -> str:
    """Keep professional voice without turning every line into a checklist."""

    speech = str(value or "").strip()
    professional_markers = ("核对条款", "流程", "数据", "时间节点", "公文", "口径")
    if "核对条款" in speech or sum(marker in speech for marker in professional_markers) >= 3:
        return (
            "会追问具体依据和时间，情绪上来时语速变快；专业内容只在必要时说，"
            "和熟人交谈仍用完整日常口语，不连续罗列术语或材料。"
        )
    short_markers = (
        "\u77ed\u53e5\u504f\u591a",
        "\u77ed\u53e5\u4f18\u5148",
        "\u5c11\u8bf4\u8bdd",
        "\u53e5\u5b50\u77ed",
        "\u60dc\u5b57\u5982\u91d1",
        "\u8a00\u7b80\u610f\u8d45",
        "\u8bdd\u4e0d\u591a",
        "\u77ed\u53e5\u8d77\u6b65",
        "\u5be1\u8a00",
        "\u4e0d\u7231\u8bf4\u8bdd",
    )
    if any(marker in speech for marker in short_markers):
        cleaned = speech
        for marker in short_markers:
            cleaned = cleaned.replace(marker, "")
        cleaned = re.sub(r"[，,、；;]+", "，", cleaned).strip("，,、；; 。.!！?？")
        complete_dialogue = (
            "保留角色克制的表达习惯，但必要的对象、原因和决定要说完整。"
        )
        return f"{cleaned}；{complete_dialogue}" if cleaned else complete_dialogue
    return speech


def _merge_prefer_existing(existing: Any, generated: Any) -> Any:
    if generated is _MISSING:
        return deepcopy(existing)
    if existing is _MISSING:
        return deepcopy(generated)
    if isinstance(existing, dict) and isinstance(generated, dict):
        keys = list(existing)
        keys.extend(key for key in generated if key not in existing)
        return {
            key: _merge_prefer_existing(
                existing.get(key, _MISSING),
                generated.get(key, _MISSING),
            )
            for key in keys
        }
    return deepcopy(generated) if _is_empty(existing) else deepcopy(existing)


def merge_character_profile(existing: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    """Fill blank character fields without replacing author-confirmed content."""

    return _merge_prefer_existing(dict(existing), dict(generated))


def normalize_character_profile(
    card: dict[str, Any],
    *,
    is_game_story: bool = False,
) -> dict[str, Any]:
    """Add concrete profile defaults while preserving legacy and extension fields."""

    normalized = deepcopy(dict(card))
    for field_name, model in _NESTED_MODELS.items():
        raw = normalized.get(field_name)
        raw = dict(raw) if isinstance(raw, dict) else {}
        if field_name == "story_drive" and not raw.get("motivation"):
            raw["motivation"] = str(
                normalized.get("motivation") or normalized.get("core_motivation") or ""
            )
        normalized[field_name] = model.model_validate(raw).model_dump()

    performance = normalized.get("performance_profile")
    performance = dict(performance) if isinstance(performance, dict) else {}
    speech_style = performance.get("speech_style") or normalized.get("speech_style")
    if speech_style:
        performance["speech_style"] = normalize_speech_style_for_writing(speech_style)
    normalized["performance_profile"] = performance
    normalized.setdefault("character_tier", str(normalized.get("role") or ""))
    normalized.setdefault("first_appearance", 0)
    normalized.setdefault("dialogue_examples", [])
    normalized.setdefault("relationship_notes", [])

    importance, narrative_function = infer_character_taxonomy(normalized)
    normalized["importance"] = importance
    normalized["narrative_function"] = narrative_function
    normalized["profile_status"] = infer_character_profile_status(normalized)
    normalized["profile_completeness"] = character_profile_completeness(normalized)

    if is_game_story:
        normalized = normalize_dual_state(normalized, is_game_story=True)
    return normalized


def project_character_for_writer(
    card: dict[str, Any],
    *,
    allowed_reveals: Iterable[str] = (),
) -> dict[str, Any]:
    """Return a scene-safe copy of a card without unrevealed private facts."""

    projected = normalize_character_profile(card)
    allowed = {str(item).strip() for item in allowed_reveals if str(item).strip()}
    drive = dict(projected.get("story_drive") or {})
    drive["hidden_matters"] = [
        item for item in drive.get("hidden_matters", []) if str(item).strip() in allowed
    ]
    projected["story_drive"] = drive
    projected["secrets"] = [
        item for item in projected.get("secrets", []) if str(item).strip() in allowed
    ]
    relationship_notes: list[dict[str, Any]] = []
    for item in projected.get("relationship_notes", []):
        if not isinstance(item, dict):
            continue
        note = dict(item)
        note["unknown_facts"] = [
            fact for fact in note.get("unknown_facts", []) if str(fact).strip() in allowed
        ]
        relationship_notes.append(note)
    projected["relationship_notes"] = relationship_notes
    return projected


def remove_cross_character_aliases(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prevent one character's canonical name from becoming another card's alias."""

    result = [deepcopy(dict(card)) for card in cards if isinstance(card, dict)]
    names = {str(card.get("name") or "").strip() for card in result}
    for card in result:
        own_name = str(card.get("name") or "").strip()
        identity = card.get("identity_profile")
        if not isinstance(identity, dict):
            continue
        aliases = identity.get("aliases")
        if not isinstance(aliases, list):
            continue
        identity["aliases"] = [
            alias
            for alias in aliases
            if str(alias).strip() == own_name or str(alias).strip() not in names
        ]
    return result


def merge_character_alias_cards(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge a game-ID card into the same person's real-name card."""

    result = [deepcopy(dict(card)) for card in cards if isinstance(card, dict)]
    index_by_name = {
        str(card.get("name") or "").strip(): index
        for index, card in enumerate(result)
        if str(card.get("name") or "").strip()
    }
    removed: set[int] = set()
    for real_index, real_card in enumerate(result):
        game_id = str(real_card.get("game_id") or "").strip()
        if not game_id:
            game_state = real_card.get("game_state")
            current = game_state.get("current") if isinstance(game_state, dict) else None
            game_id = str(current.get("game_id") or "").strip() if isinstance(current, dict) else ""
        alias_index = index_by_name.get(game_id)
        if not game_id or alias_index is None or alias_index == real_index:
            continue
        merged = merge_character_profile(real_card, result[alias_index])
        merged["name"] = str(real_card.get("name") or "").strip()
        merged["game_id"] = game_id
        identity = merged.get("identity_profile")
        identity = dict(identity) if isinstance(identity, dict) else {}
        aliases = [str(alias).strip() for alias in identity.get("aliases", []) if str(alias).strip()]
        if game_id not in aliases:
            aliases.append(game_id)
        identity["aliases"] = aliases
        merged["identity_profile"] = identity
        result[real_index] = merged
        removed.add(alias_index)
    return [card for index, card in enumerate(result) if index not in removed]


def record_character_appearances(
    cards: Iterable[dict[str, Any]],
    *,
    chapter_number: int,
    visible_names: Iterable[str],
) -> list[dict[str, Any]]:
    """Record actual prose appearances without advancing unseen characters."""

    visible = {str(name).strip() for name in visible_names if str(name).strip()}
    result: list[dict[str, Any]] = []
    for raw_card in cards:
        if not isinstance(raw_card, dict):
            continue
        card = deepcopy(dict(raw_card))
        name = str(card.get("name") or "").strip()
        if chapter_number > 0 and name in visible:
            first = int(card.get("first_appearance_chapter") or 0)
            card["first_appearance_chapter"] = (
                min(first, chapter_number) if first > 0 else chapter_number
            )
            card["latest_chapter"] = max(
                int(card.get("latest_chapter") or 0),
                chapter_number,
            )
        result.append(card)
    return result


def reconcile_character_appearance_history(
    cards: Iterable[dict[str, Any]],
    memory_index: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project first/latest appearance markers from committed chapter memory."""

    appearances: dict[str, list[int]] = {}
    for entry in memory_index:
        if not isinstance(entry, dict):
            continue
        chapter_number = int(entry.get("chapter_number") or 0)
        if chapter_number <= 0:
            continue
        for raw_name in entry.get("characters", []) or []:
            name = str(raw_name or "").strip()
            if name:
                appearances.setdefault(name, []).append(chapter_number)

    result: list[dict[str, Any]] = []
    for raw_card in cards:
        if not isinstance(raw_card, dict):
            continue
        card = deepcopy(dict(raw_card))
        chapters = appearances.get(str(card.get("name") or "").strip())
        if chapters:
            card["first_appearance_chapter"] = min(chapters)
            card["latest_chapter"] = max(chapters)
        result.append(card)
    return result
