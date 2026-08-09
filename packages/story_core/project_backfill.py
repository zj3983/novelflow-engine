"""Read-only evidence extraction for long-running file projects."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.foreshadowing import (
    canonicalize_foreshadowing_ledger,
    normalize_foreshadowing_text,
)
from packages.story_core.models import ForeshadowingState
from packages.story_core.project_outline import normalize_outline_for_story_type
from packages.story_core.relationship_graph import normalize_relationship_graph
from packages.story_core.story_core_card import StoryCoreCard


@dataclass(frozen=True)
class ChapterEvidence:
    chapter_number: int
    title: str
    body_hash: str
    body: str
    summary: str
    timeline: tuple[Mapping[str, Any], ...]
    character_updates: tuple[Mapping[str, Any], ...]
    foreshadowing: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_number": self.chapter_number,
            "title": self.title,
            "body_hash": self.body_hash,
            "body": self.body,
            "summary": self.summary,
            "timeline": _thaw(self.timeline),
            "character_updates": _thaw(self.character_updates),
            "foreshadowing": _thaw(self.foreshadowing),
        }


@dataclass(frozen=True)
class ProjectEvidenceIndex:
    project_root: Path
    chapters: tuple[ChapterEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": str(self.project_root),
            "chapters": [chapter.to_dict() for chapter in self.chapters],
        }


@dataclass(frozen=True)
class ProjectBackfillPatch:
    """Evidence-constrained replacement data for the seven project sections."""

    story_core: Mapping[str, Any]
    master_outline: Mapping[str, Any]
    world_blueprint: Mapping[str, Any]
    characters: Mapping[str, Any]
    relationships: tuple[Mapping[str, Any], ...]
    foreshadowing: tuple[Mapping[str, Any], ...]
    continuity: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "story_core": _thaw(self.story_core),
            "master_outline": _thaw(self.master_outline),
            "world_blueprint": _thaw(self.world_blueprint),
            "characters": _thaw(self.characters),
            "relationships": _thaw(self.relationships),
            "foreshadowing": _thaw(self.foreshadowing),
            "continuity": _thaw(self.continuity),
        }


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_thaw(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _dict_entries(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _first_entries(*values: Any) -> tuple[dict[str, Any], ...]:
    for value in values:
        entries = _dict_entries(value)
        if entries:
            return entries
    return ()


def _frozen_entries(values: tuple[dict[str, Any], ...]) -> tuple[Mapping[str, Any], ...]:
    return tuple(_freeze(item) for item in values)


def _chapter_timeline(value: Any, chapter_number: int) -> tuple[dict[str, Any], ...]:
    entries = _dict_entries(value)
    scoped = tuple(
        entry
        for entry in entries
        if entry.get("chapter_number") in (None, chapter_number, str(chapter_number))
    )
    return scoped


def _summary(chapter: Mapping[str, Any]) -> str:
    chapter_summary = chapter.get("chapter_summary")
    if isinstance(chapter_summary, str):
        return chapter_summary.strip()
    summary = _mapping(chapter_summary).get("summary") or chapter.get("summary")
    return str(summary or "").strip()


def _canonical_markdown_path(
    project_root: Path,
    store: FileProjectStore,
    chapter_number: int,
    chapter: Mapping[str, Any],
) -> Path | None:
    body_path = chapter.get("body_path")
    if isinstance(body_path, str) and body_path.strip():
        path = project_root / body_path
        if path.is_file():
            return path

    title = str(chapter.get("chapter_title") or chapter.get("title") or "").strip()
    resolved = store.chapter_store.paths(chapter_number, title)["markdown"]
    if resolved.is_file():
        return resolved

    matches = sorted(store.chapter_store.markdown_directory.glob(f"{chapter_number:04d}*.md"))
    return matches[0] if len(matches) == 1 else None


def _body_hash(
    project_root: Path,
    store: FileProjectStore,
    chapter_number: int,
    chapter: Mapping[str, Any],
) -> str:
    markdown_path = _canonical_markdown_path(
        project_root,
        store,
        chapter_number,
        chapter,
    )
    if markdown_path is not None:
        return sha256(markdown_path.read_bytes()).hexdigest()
    body = chapter.get("body")
    return sha256(body.encode("utf-8")).hexdigest() if isinstance(body, str) else ""


def chapter_hashes(project_root: Path) -> dict[int, str]:
    """Return SHA-256 hashes of canonical Markdown chapter bytes."""

    root = Path(project_root).resolve()
    store = FileProjectStore(root)
    hashes: dict[int, str] = {}
    for chapter_number in store.chapter_numbers():
        chapter = store.chapter_store.read_chapter(
            chapter_number,
            default={},
            include_body=False,
        )
        if not isinstance(chapter, Mapping):
            continue
        body_hash = _body_hash(root, store, chapter_number, chapter)
        if body_hash:
            hashes[chapter_number] = body_hash
    return hashes


def _character_snapshot(chapter: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    updated_story = _mapping(chapter.get("updated_story"))
    characters = _dict_entries(updated_story.get("characters"))
    return {
        str(character.get("name") or "").strip(): character
        for character in characters
        if str(character.get("name") or "").strip()
    }


def _actual_character_evidence(
    chapter: Mapping[str, Any],
    previous_snapshot: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    chapter_summary = _mapping(chapter.get("chapter_summary"))
    state_delta = _mapping(chapter.get("state_delta"))
    explicit = _first_entries(
        chapter.get("character_updates"),
        chapter_summary.get("character_updates"),
        state_delta.get("character_updates"),
    )

    snapshot = _character_snapshot(chapter)
    changed = tuple(
        {
            "source": "updated_story.characters",
            "name": name,
            "character": character,
        }
        for name, character in snapshot.items()
        if previous_snapshot.get(name) != character
    )

    known_names = sorted(set(snapshot) | set(previous_snapshot))
    facts = chapter_summary.get("facts")
    confirmed_facts: list[dict[str, Any]] = []
    for fact in facts if isinstance(facts, (list, tuple)) else ():
        if not isinstance(fact, str):
            continue
        matched_names = [name for name in known_names if name in fact]
        if matched_names:
            confirmed_facts.append(
                {
                    "source": "chapter_summary.facts",
                    "name": matched_names[0],
                    "names": matched_names,
                    "fact": fact,
                }
            )
    return (*explicit, *changed, *confirmed_facts)


def _chapter_evidence(
    store: FileProjectStore,
    chapter_number: int,
    hashes: Mapping[int, str],
    previous_character_snapshot: Mapping[str, Mapping[str, Any]],
) -> ChapterEvidence:
    chapter = store.chapter_store.read_chapter(chapter_number, default={})
    if not isinstance(chapter, Mapping):
        chapter = {}
    chapter_summary = _mapping(chapter.get("chapter_summary"))
    state_delta = _mapping(chapter.get("state_delta"))
    updated_story = _mapping(chapter.get("updated_story"))
    timeline = _first_entries(
        chapter.get("timeline"),
        chapter_summary.get("timeline"),
        state_delta.get("timeline"),
    ) or _chapter_timeline(updated_story.get("timeline"), chapter_number)

    markdown_path = _canonical_markdown_path(store.root, store, chapter_number, chapter)
    body = (
        markdown_path.read_text(encoding="utf-8-sig")
        if markdown_path is not None
        else str(chapter.get("body") or "")
    )

    return ChapterEvidence(
        chapter_number=chapter_number,
        title=str(chapter.get("chapter_title") or chapter.get("title") or "").strip(),
        body_hash=hashes.get(chapter_number, ""),
        body=body,
        summary=_summary(chapter),
        timeline=_frozen_entries(timeline),
        character_updates=_frozen_entries(
            _actual_character_evidence(chapter, previous_character_snapshot)
        ),
        foreshadowing=_frozen_entries(
            _first_entries(
                chapter.get("foreshadowing"),
                chapter.get("foreshadowing_updates"),
                chapter_summary.get("foreshadowing"),
                state_delta.get("foreshadowing"),
            )
        ),
    )


def build_evidence_index(project_root: Path) -> ProjectEvidenceIndex:
    root = Path(project_root).resolve()
    store = FileProjectStore(root)
    hashes = chapter_hashes(root)
    chapters: list[ChapterEvidence] = []
    previous_character_snapshot: dict[str, dict[str, Any]] = {}
    for chapter_number in store.chapter_numbers():
        chapter = store.chapter_store.read_chapter(chapter_number, default={})
        chapter_mapping = chapter if isinstance(chapter, Mapping) else {}
        chapters.append(
            _chapter_evidence(
                store,
                chapter_number,
                hashes,
                previous_character_snapshot,
            )
        )
        snapshot = _character_snapshot(chapter_mapping)
        if snapshot:
            previous_character_snapshot = snapshot
    return ProjectEvidenceIndex(project_root=root, chapters=tuple(chapters))


_BACKFILL_SECTIONS = (
    "story_core",
    "master_outline",
    "world_blueprint",
    "characters",
    "relationships",
    "foreshadowing",
    "continuity",
)
_GAME_ONLY_FIELDS = frozenset(
    {
        "game_panel",
        "game_state",
        "game_id",
        "player_state",
        "monster_panel",
        "inventory_slots",
    }
)
_NON_CHARACTER_TYPES = frozenset(
    {
        "organization",
        "organisation",
        "org",
        "faction",
        "institution",
        "location",
        "place",
        "merchant",
        "shop",
        "store",
        "vendor_entity",
        "merchant_entity",
        "item",
        "equipment",
        "object",
        "artifact",
        "组织",
        "机构",
        "势力",
        "地点",
        "场所",
        "商户",
        "商店",
        "商户实体",
        "物品",
        "装备",
    }
)
_HUMAN_ROLE_TYPES = frozenset(
    {"merchant", "shopkeeper", "master", "店主", "掌柜", "师父", "宗主"}
)
_CHARACTER_TYPES = frozenset(
    {
        "character",
        "person",
        "human",
        "protagonist",
        "antagonist",
        "supporting",
        "角色",
        "人物",
        "主角",
        "反派",
        "配角",
    }
)
_CHAPTER_FIELDS = frozenset(
    {
        "chapter_number",
        "first_chapter",
        "first_appearance_chapter",
        "last_touched_chapter",
        "last_changed_chapter",
        "resolved_chapter",
    }
)
_CHARACTER_EVIDENCE_METADATA_FIELDS = frozenset(
    {"source", "name", "names", "fact", "change", "summary", "chapter_number"}
)


def _genre_text(genre: Any) -> str:
    if isinstance(genre, Mapping):
        return " ".join(_genre_text(value) for value in genre.values())
    if isinstance(genre, (list, tuple, set, frozenset)):
        return " ".join(_genre_text(value) for value in genre)
    return str(genre or "").casefold()


def _is_game_genre(genre: Any) -> bool:
    text = _genre_text(genre)
    return any(marker in text for marker in ("网游", "游戏", "game", "mmorpg"))


def _strip_foreign_genre_fields(value: Any, *, is_game_story: bool) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_foreign_genre_fields(item, is_game_story=is_game_story)
            for key, item in value.items()
            if is_game_story or str(key).casefold() not in _GAME_ONLY_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [
            _strip_foreign_genre_fields(item, is_game_story=is_game_story)
            for item in value
        ]
    return deepcopy(value)


def _required_sections(generated: Any) -> dict[str, Any]:
    if not isinstance(generated, Mapping):
        raise ValueError("invalid_backfill_payload")
    for section in _BACKFILL_SECTIONS:
        if section not in generated:
            raise ValueError(f"missing_backfill_section:{section}")
    for section in ("story_core", "master_outline", "world_blueprint", "continuity"):
        if not isinstance(generated.get(section), Mapping):
            raise ValueError(f"invalid_backfill_section:{section}")
    characters = generated.get("characters")
    if not isinstance(characters, (Mapping, list, tuple)):
        raise ValueError("invalid_backfill_section:characters")
    for section in ("relationships", "foreshadowing"):
        if not isinstance(generated.get(section), (list, tuple)):
            raise ValueError(f"invalid_backfill_section:{section}")
    return deepcopy(dict(generated))


def _chapter_limit(index: ProjectEvidenceIndex) -> int:
    return max((chapter.chapter_number for chapter in index.chapters), default=0)


def _validate_chapter_fields(
    value: Any,
    *,
    maximum: int,
    error: str,
    allow_unknown_zero: bool = False,
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _CHAPTER_FIELDS and item is not None:
                if (
                    not isinstance(item, int)
                    or isinstance(item, bool)
                    or item < 0
                    or (item == 0 and not allow_unknown_zero)
                    or item > maximum
                ):
                    raise ValueError(error)
            _validate_chapter_fields(
                item,
                maximum=maximum,
                error=error,
                allow_unknown_zero=allow_unknown_zero,
            )
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_chapter_fields(
                item,
                maximum=maximum,
                error=error,
                allow_unknown_zero=allow_unknown_zero,
            )


def _character_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        rows = []
        for name, card in value.items():
            if isinstance(card, Mapping):
                row = deepcopy(dict(card))
                row.setdefault("name", str(name))
                rows.append(row)
        return rows
    return [deepcopy(dict(item)) for item in value if isinstance(item, Mapping)]


def _text_list(value: Any) -> list[str]:
    source = value if isinstance(value, (list, tuple)) else [value]
    return list(
        dict.fromkeys(
            text
            for item in source
            if (text := str(item or "").strip())
        )
    )


def _evidence_character_facts(
    index: ProjectEvidenceIndex,
) -> tuple[
    set[str],
    dict[str, int],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    names: set[str] = set()
    first_seen: dict[str, int] = {}
    latest_cards: dict[str, dict[str, Any]] = {}
    canonical_by_alias: dict[str, str] = {}
    for chapter in sorted(index.chapters, key=lambda item: item.chapter_number):
        for update in chapter.character_updates:
            update_names = _text_list(update.get("names"))
            name = str(update.get("name") or "").strip()
            if name:
                update_names.insert(0, name)
            character = update.get("character")
            if isinstance(character, Mapping):
                character_name = str(character.get("name") or "").strip()
                if character_name:
                    update_names.insert(0, character_name)
            for item in dict.fromkeys(update_names):
                names.add(item)
                first_seen.setdefault(item, chapter.chapter_number)
            direct_state = any(
                key not in _CHARACTER_EVIDENCE_METADATA_FIELDS
                for key in update
            )
            evidence_card = (
                character
                if isinstance(character, Mapping)
                else update if direct_state else None
            )
            evidence_name = str(
                (evidence_card or {}).get("name") or name
            ).strip()
            if isinstance(evidence_card, Mapping) and evidence_name:
                plain_card = dict(_thaw(evidence_card))
                canonical = str(
                    plain_card.get("canonical_name") or evidence_name
                ).strip()
                evidence_aliases = _text_list(plain_card.get("aliases"))
                for alias in dict.fromkeys((canonical, *update_names, *evidence_aliases)):
                    names.add(alias)
                    first_seen.setdefault(alias, chapter.chapter_number)
                    canonical_by_alias.setdefault(alias, canonical)
                latest_cards[canonical] = plain_card
    return names, first_seen, latest_cards, canonical_by_alias


def _is_character_entity(card: Mapping[str, Any], evidence_names: set[str]) -> bool:
    entity_type = str(card.get("entity_type") or "").strip().casefold()
    kind = str(card.get("kind") or "").strip().casefold()
    role = str(card.get("role") or "").strip().casefold()
    if entity_type in _CHARACTER_TYPES:
        return True
    if entity_type in _NON_CHARACTER_TYPES:
        return False
    if kind in _CHARACTER_TYPES:
        return True
    if kind in _NON_CHARACTER_TYPES:
        return False
    if role in _CHARACTER_TYPES or role in _HUMAN_ROLE_TYPES:
        return True
    return str(card.get("name") or "").strip() in evidence_names


def _merge_card(existing: dict[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    for key, value in incoming.items():
        if key in {"name", "aliases"} or value in (None, "", [], {}):
            continue
        if key == "current_state" and isinstance(value, Mapping):
            state = dict(merged.get(key) or {})
            state.update(deepcopy(dict(value)))
            merged[key] = state
        elif merged.get(key) in (None, "", [], {}):
            merged[key] = deepcopy(value)
    return merged


def _normalize_characters(
    value: Any,
    index: ProjectEvidenceIndex,
    maximum: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    (
        evidence_names,
        first_seen,
        latest_cards,
        evidence_canonical,
    ) = _evidence_character_facts(index)
    rows = [
        row
        for row in _character_rows(value)
        if str(row.get("name") or "").strip()
        and _is_character_entity(row, evidence_names)
    ]

    parent: dict[str, str] = {}

    def find(name: str) -> str:
        parent.setdefault(name, name)
        if parent[name] != name:
            parent[name] = find(parent[name])
        return parent[name]

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for row in rows:
        identities = _text_list(
            [row.get("name"), row.get("canonical_name"), *(_text_list(row.get("aliases")))]
        )
        for identity in identities:
            union(identities[0], identity)
    for alias, canonical in evidence_canonical.items():
        union(alias, canonical)

    components: dict[str, set[str]] = {}
    for identity in parent:
        components.setdefault(find(identity), set()).add(identity)

    alias_to_name: dict[str, str] = {}
    for members in components.values():
        evidence_choices = sorted(
            {
                evidence_canonical[member]
                for member in members
                if member in evidence_canonical
            },
            key=lambda name: (first_seen.get(name, maximum + 1), name),
        )
        explicit_choices = sorted(
            {
                str(row.get("canonical_name") or "").strip()
                for row in rows
                if str(row.get("name") or "").strip() in members
                and str(row.get("canonical_name") or "").strip()
            }
        )
        canonical = (
            evidence_choices[0]
            if evidence_choices
            else explicit_choices[0] if explicit_choices else min(members)
        )
        for member in members:
            alias_to_name[member] = canonical

    cards: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        aliases = [alias for alias in _text_list(row.get("aliases")) if alias != name]
        canonical = alias_to_name.get(name, name)
        card = cards.get(canonical, {"name": canonical, "aliases": []})
        card = _merge_card(card, row)
        card["aliases"] = list(
            dict.fromkeys(
                [
                    *card.get("aliases", []),
                    *(item for item in (name, *aliases) if item != canonical),
                ]
            )
        )
        cards[canonical] = card
        for item in (canonical, name, *aliases):
            alias_to_name.setdefault(item, canonical)

    for evidence_name in sorted(evidence_names):
        canonical = alias_to_name.get(evidence_name, evidence_name)
        if canonical not in cards:
            cards[canonical] = {"name": canonical, "aliases": []}
            alias_to_name[evidence_name] = canonical

    canonical_first_seen: dict[str, int] = {}
    for evidence_name, chapter_number in first_seen.items():
        canonical = alias_to_name.get(evidence_name, evidence_name)
        canonical_first_seen[canonical] = min(
            canonical_first_seen.get(canonical, chapter_number),
            chapter_number,
        )
    for canonical, chapter_number in canonical_first_seen.items():
        cards[canonical]["first_appearance_chapter"] = chapter_number
    for evidence_name, evidence_card in latest_cards.items():
        canonical = alias_to_name.get(evidence_name, evidence_name)
        card = cards[canonical]
        for key, value in evidence_card.items():
            if key in {"name", "aliases", "first_appearance_chapter"}:
                continue
            if value not in (None, "", [], {}):
                card[key] = deepcopy(value)
    _validate_chapter_fields(cards, maximum=maximum, error="character_chapter_out_of_range")
    return cards, alias_to_name


def _canonical_name(name: Any, aliases: Mapping[str, str]) -> str:
    text = str(name or "").strip()
    return aliases.get(text, text)


def _normalize_relationships(
    value: Any,
    aliases: Mapping[str, str],
    maximum: int,
) -> list[dict[str, Any]]:
    rows = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        row = deepcopy(dict(raw))
        row["source"] = _canonical_name(row.get("source"), aliases)
        row["target"] = _canonical_name(row.get("target"), aliases)
        rows.append(row)
    _validate_chapter_fields(
        rows,
        maximum=maximum,
        error="relationship_chapter_out_of_range",
        allow_unknown_zero=True,
    )
    normalized = normalize_relationship_graph(rows)
    _validate_chapter_fields(
        normalized,
        maximum=maximum,
        error="relationship_chapter_out_of_range",
        allow_unknown_zero=True,
    )
    return normalized


def _evidence_foreshadowing(
    index: ProjectEvidenceIndex,
) -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    for chapter in sorted(index.chapters, key=lambda item: item.chapter_number):
        for raw in chapter.foreshadowing:
            text = str(raw.get("text") or raw.get("summary") or "").strip()
            key = normalize_foreshadowing_text(text)
            if not key:
                continue
            fact = facts.setdefault(
                key,
                {
                    "text": text,
                    "first_chapter": chapter.chapter_number,
                    "last_touched_chapter": chapter.chapter_number,
                    "status": "open",
                    "payoff_plan": "",
                    "resolved_chapter": None,
                },
            )
            fact["last_touched_chapter"] = chapter.chapter_number
            if raw.get("status") in {"open", "reinforced", "resolved", "expired"}:
                fact["status"] = raw["status"]
            if str(raw.get("payoff_plan") or "").strip():
                fact["payoff_plan"] = str(raw["payoff_plan"]).strip()
            if fact["status"] == "resolved":
                fact["resolved_chapter"] = chapter.chapter_number
    return facts


def _normalize_foreshadowing(
    value: Any,
    index: ProjectEvidenceIndex,
    maximum: int,
) -> list[dict[str, Any]]:
    evidence = _evidence_foreshadowing(index)
    rows: dict[str, dict[str, Any]] = {}
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        row = deepcopy(dict(raw))
        text = str(row.get("text") or "").strip()
        key = normalize_foreshadowing_text(text)
        if not key:
            continue
        if key in evidence:
            evidence_row = evidence[key]
            row.update(
                {
                    "text": evidence_row["text"],
                    "first_chapter": evidence_row["first_chapter"],
                    "last_touched_chapter": evidence_row["last_touched_chapter"],
                    "status": evidence_row["status"],
                    "payoff_plan": evidence_row["payoff_plan"],
                    "resolved_chapter": evidence_row["resolved_chapter"],
                }
            )
        rows[key] = row
    for key, evidence_row in evidence.items():
        rows.setdefault(key, deepcopy(evidence_row))
    _validate_chapter_fields(
        list(rows.values()),
        maximum=maximum,
        error="foreshadowing_chapter_out_of_range",
    )
    ledger = [ForeshadowingState.model_validate(row) for row in rows.values()]
    return [
        item.model_dump(mode="json")
        for item in canonicalize_foreshadowing_ledger(ledger)
    ]


def build_backfill_patch(
    index: ProjectEvidenceIndex,
    generated: Any,
    genre: Any,
) -> ProjectBackfillPatch:
    """Normalize generated backfill data while making chapter evidence authoritative."""

    payload = _required_sections(generated)
    maximum = _chapter_limit(index)
    if maximum < 1:
        raise ValueError("empty_project_evidence")
    is_game_story = _is_game_genre(genre)
    payload = _strip_foreign_genre_fields(payload, is_game_story=is_game_story)

    story_core = StoryCoreCard.model_validate(payload["story_core"]).model_dump(mode="json")
    master_outline = normalize_outline_for_story_type(
        payload["master_outline"],
        is_game_story=is_game_story,
    )
    characters, aliases = _normalize_characters(payload["characters"], index, maximum)
    relationships = _normalize_relationships(payload["relationships"], aliases, maximum)
    foreshadowing = _normalize_foreshadowing(
        payload["foreshadowing"],
        index,
        maximum,
    )
    continuity = deepcopy(dict(payload["continuity"]))
    continuity["current_chapter"] = maximum
    _validate_chapter_fields(
        continuity,
        maximum=maximum,
        error="continuity_chapter_out_of_range",
    )

    return ProjectBackfillPatch(
        story_core=_freeze(story_core),
        master_outline=_freeze(master_outline),
        world_blueprint=_freeze(payload["world_blueprint"]),
        characters=_freeze(characters),
        relationships=tuple(_freeze(item) for item in relationships),
        foreshadowing=tuple(_freeze(item) for item in foreshadowing),
        continuity=_freeze(continuity),
    )


__all__ = [
    "ChapterEvidence",
    "ProjectBackfillPatch",
    "ProjectEvidenceIndex",
    "build_backfill_patch",
    "build_evidence_index",
    "chapter_hashes",
]
