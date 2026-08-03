from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.dual_state import normalize_dual_state


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
_MISSING = object()


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
            "平时不主动多说，但必要的对象、原因和决定要说完整；"
            "紧张、打断或强调时才使用自然短句，不把台词写成关键词或清单"
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


def remove_cross_character_aliases(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Do not let one confirmed card masquerade as another confirmed card."""

    copied = [deepcopy(dict(card)) for card in cards]
    names = {
        str(card.get("name") or "").strip().casefold()
        for card in copied
        if str(card.get("name") or "").strip()
    }
    for card in copied:
        own_name = str(card.get("name") or "").strip().casefold()
        identity = card.get("identity_profile")
        if not isinstance(identity, dict):
            continue
        aliases = identity.get("aliases")
        if not isinstance(aliases, list):
            continue
        next_identity = dict(identity)
        next_identity["aliases"] = [
            alias
            for alias in aliases
            if str(alias or "").strip()
            and (
                str(alias).strip().casefold() == own_name
                or str(alias).strip().casefold() not in names
            )
        ]
        card["identity_profile"] = next_identity
    return copied


_IDENTITY_ALIAS_PATTERN = re.compile(
    r"(?:现实身份|本名|真名|原名|现实姓名|游戏ID|游戏名|网名|化名)\s*[：:]?\s*"
    r"([A-Za-z0-9_\-\u4e00-\u9fff]{2,24})"
)


def _character_identity_tokens(card: dict[str, Any]) -> set[str]:
    """Collect explicit names and identity labels used to join duplicate cards."""

    tokens: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text:
            tokens.add(text.casefold())

    add(card.get("name"))
    add(card.get("game_id"))
    panel = card.get("game_panel")
    if isinstance(panel, dict):
        add(panel.get("game_id"))
    game_state = card.get("game_state")
    if isinstance(game_state, dict):
        current = game_state.get("current")
        if isinstance(current, dict):
            add(current.get("game_id"))
    identity = card.get("identity_profile")
    if isinstance(identity, dict):
        for alias in identity.get("aliases", []):
            add(alias)

    for value in (card.get("role"), (identity or {}).get("current_identity") if isinstance(identity, dict) else ""):
        text = str(value or "")
        for match in _IDENTITY_ALIAS_PATTERN.finditer(text):
            add(match.group(1))
    return tokens


def _character_card_preference(card: dict[str, Any]) -> tuple[int, int]:
    """Prefer a real-name card over a game-ID-only legacy card."""

    name = str(card.get("name") or "").strip()
    game_id = str(card.get("game_id") or "").strip()
    role = str(card.get("role") or "").strip().casefold()
    tier = str(card.get("character_tier") or "").strip().casefold()
    return (
        int(bool(game_id and game_id != name)) * 4
        + int(role in {"protagonist", "主角"} or tier in {"protagonist", "主角"}) * 2,
        -len(name),
    )


def merge_character_alias_cards(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge cards that explicitly identify the same person under different names."""

    merged_cards: list[dict[str, Any]] = []
    token_groups: list[set[str]] = []
    members: list[list[dict[str, Any]]] = []

    for raw in cards:
        if not isinstance(raw, dict):
            continue
        card = deepcopy(dict(raw))
        tokens = _character_identity_tokens(card)
        match_index = next(
            (index for index, group in enumerate(token_groups) if tokens & group),
            None,
        )
        if match_index is None:
            merged_cards.append(card)
            token_groups.append(tokens)
            members.append([card])
            continue

        group = members[match_index]
        group.append(card)
        token_groups[match_index].update(tokens)
        preferred = max(group, key=_character_card_preference)
        current = merged_cards[match_index]
        if preferred is not current:
            current = merge_character_profile(preferred, current)
        else:
            current = merge_character_profile(current, card)
        current["name"] = str(preferred.get("name") or current.get("name") or "").strip()

        identity = dict(current.get("identity_profile") or {})
        aliases: list[str] = []
        for item in group:
            item_identity = item.get("identity_profile")
            values = item_identity.get("aliases", []) if isinstance(item_identity, dict) else []
            values = [*values, item.get("name"), item.get("game_id")]
            for value in values:
                alias = str(value or "").strip()
                if alias and alias != current["name"] and alias not in aliases:
                    aliases.append(alias)
        identity["aliases"] = aliases
        current["identity_profile"] = identity
        merged_cards[match_index] = current

    return merged_cards


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
            raw["motivation"] = str(normalized.get("motivation") or normalized.get("core_motivation") or "")
        normalized[field_name] = model.model_validate(raw).model_dump()

    performance = normalized.get("performance_profile")
    performance = dict(performance) if isinstance(performance, dict) else {}
    if not performance.get("speech_style") and normalized.get("speech_style"):
        performance["speech_style"] = str(normalized["speech_style"])
    normalized["performance_profile"] = performance
    normalized.setdefault("character_tier", str(normalized.get("role") or ""))
    normalized.setdefault("first_appearance", 0)
    normalized.setdefault("dialogue_examples", [])
    normalized.setdefault("relationship_notes", [])
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
