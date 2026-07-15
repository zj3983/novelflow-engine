from __future__ import annotations

from copy import deepcopy
from hashlib import sha1
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field


class _GraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelationshipChange(_GraphModel):
    chapter_number: int = Field(default=0, ge=0)
    summary: str = ""
    trust: float | None = Field(default=None, ge=0, le=100)
    tension: float | None = Field(default=None, ge=0, le=100)


class RelationshipEdge(_GraphModel):
    id: str
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    relation_type: str = ""
    bond: str = ""
    origin: str = ""
    current_state: str = ""
    shared_interest_or_conflict: str = ""
    trust: float = Field(default=0, ge=0, le=100)
    tension: float = Field(default=0, ge=0, le=100)
    source_knowledge: list[str] = Field(default_factory=list)
    target_knowledge: list[str] = Field(default_factory=list)
    private_notes: list[str] = Field(default_factory=list)
    status: Literal["active", "ended", "hidden"] = "active"
    first_chapter: int = Field(default=0, ge=0)
    last_changed_chapter: int = Field(default=0, ge=0)
    changes: list[RelationshipChange] = Field(default_factory=list)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lines(value: Any) -> list[str]:
    source = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(text for item in source if (text := _text(item))))


def _pair_key(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted((_text(source), _text(target))))  # type: ignore[return-value]


def relationship_edge_id(source: str, target: str) -> str:
    left, right = _pair_key(source, target)
    digest = sha1(f"{left}\0{right}".encode("utf-8")).hexdigest()[:12]
    return f"rel-{digest}"


def _clamp_score(value: Any) -> float:
    try:
        score = float(value or 0)
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))


def _normalized_edge(raw: dict[str, Any]) -> dict[str, Any] | None:
    source = _text(raw.get("source"))
    target = _text(raw.get("target"))
    if not source or not target or source == target:
        return None
    relation_type = _text(raw.get("relation_type") or raw.get("bond"))
    payload = {
        "id": _text(raw.get("id")) or relationship_edge_id(source, target),
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "bond": _text(raw.get("bond") or relation_type),
        "origin": _text(raw.get("origin") or raw.get("history")),
        "current_state": _text(raw.get("current_state") or raw.get("current_attitude")),
        "shared_interest_or_conflict": _text(raw.get("shared_interest_or_conflict")),
        "trust": _clamp_score(raw.get("trust")),
        "tension": _clamp_score(raw.get("tension")),
        "source_knowledge": _lines(raw.get("source_knowledge")),
        "target_knowledge": _lines(raw.get("target_knowledge")),
        "private_notes": _lines(raw.get("private_notes")),
        "status": raw.get("status") if raw.get("status") in {"active", "ended", "hidden"} else "active",
        "first_chapter": max(0, int(raw.get("first_chapter") or 0)),
        "last_changed_chapter": max(0, int(raw.get("last_changed_chapter") or 0)),
        "changes": raw.get("changes") if isinstance(raw.get("changes"), list) else [],
    }
    return RelationshipEdge.model_validate(payload).model_dump(mode="json")


def normalize_relationship_graph(edges: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in edges if isinstance(edges, list) else []:
        if not isinstance(raw, dict):
            continue
        edge = _normalized_edge(raw)
        if edge is not None:
            normalized = merge_relationship_graph(normalized, [edge])
    return normalized


def _orient_like(edge: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    if edge["source"] == reference["source"]:
        return edge
    oriented = dict(edge)
    oriented["source"], oriented["target"] = edge["target"], edge["source"]
    oriented["source_knowledge"], oriented["target_knowledge"] = (
        edge.get("target_knowledge", []),
        edge.get("source_knowledge", []),
    )
    return oriented


def _prefer_existing(existing: Any, incoming: Any) -> Any:
    if existing not in (None, "", [], {}, 0, 0.0):
        return deepcopy(existing)
    return deepcopy(incoming)


def merge_relationship_graph(existing: Any, incoming: Any) -> list[dict[str, Any]]:
    result = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    by_pair = {_pair_key(item.get("source", ""), item.get("target", "")): index for index, item in enumerate(result)}
    for raw in incoming if isinstance(incoming, list) else []:
        edge = _normalized_edge(raw) if isinstance(raw, dict) else None
        if edge is None:
            continue
        key = _pair_key(edge["source"], edge["target"])
        if key not in by_pair:
            by_pair[key] = len(result)
            result.append(edge)
            continue
        index = by_pair[key]
        current = RelationshipEdge.model_validate(result[index]).model_dump(mode="json")
        edge = _orient_like(edge, current)
        merged = {
            field: _prefer_existing(current.get(field), edge.get(field))
            for field in RelationshipEdge.model_fields
        }
        for field in ("source_knowledge", "target_knowledge", "private_notes"):
            merged[field] = list(dict.fromkeys([*current.get(field, []), *edge.get(field, [])]))
        changes = [*current.get("changes", []), *edge.get("changes", [])]
        merged["changes"] = list(
            {
                (int(item.get("chapter_number") or 0), _text(item.get("summary"))): item
                for item in changes
                if isinstance(item, dict)
            }.values()
        )
        merged["first_chapter"] = min(
            [number for number in (int(current.get("first_chapter") or 0), int(edge.get("first_chapter") or 0)) if number > 0]
            or [0]
        )
        merged["last_changed_chapter"] = max(
            int(current.get("last_changed_chapter") or 0), int(edge.get("last_changed_chapter") or 0)
        )
        result[index] = RelationshipEdge.model_validate(merged).model_dump(mode="json")
    return result


def apply_relationship_updates(existing: Any, updates: Any) -> list[dict[str, Any]]:
    result = normalize_relationship_graph(existing)
    by_pair = {_pair_key(item["source"], item["target"]): index for index, item in enumerate(result)}
    dynamic_fields = ("relation_type", "bond", "current_state", "trust", "tension", "status")
    for raw in updates if isinstance(updates, list) else []:
        edge = _normalized_edge(raw) if isinstance(raw, dict) else None
        if edge is None:
            continue
        key = _pair_key(edge["source"], edge["target"])
        if key not in by_pair:
            result = merge_relationship_graph(result, [edge])
            by_pair[key] = len(result) - 1
            continue
        index = by_pair[key]
        current = result[index]
        edge = _orient_like(edge, current)
        merged = dict(current)
        for field in dynamic_fields:
            if field in raw and raw.get(field) not in (None, ""):
                merged[field] = edge[field]
        merged["last_changed_chapter"] = max(
            int(current.get("last_changed_chapter") or 0), int(edge.get("last_changed_chapter") or 0)
        )
        merged["changes"] = merge_relationship_graph([current], [edge])[0]["changes"]
        result[index] = RelationshipEdge.model_validate(merged).model_dump(mode="json")
    return result


def graph_from_character_cards(cards: Any) -> list[dict[str, Any]]:
    graph: list[dict[str, Any]] = []
    for card in cards if isinstance(cards, list) else []:
        if not isinstance(card, dict) or not (source := _text(card.get("name"))):
            continue
        for note in card.get("relationship_notes", []) if isinstance(card.get("relationship_notes"), list) else []:
            if not isinstance(note, dict) or not (target := _text(note.get("target"))):
                continue
            edge = {
                "source": source,
                "target": target,
                "relation_type": note.get("relation_type"),
                "origin": note.get("history"),
                "current_state": note.get("current_attitude"),
                "shared_interest_or_conflict": note.get("shared_interest_or_conflict"),
                "source_knowledge": note.get("known_facts", []),
                "private_notes": note.get("unknown_facts", []),
            }
            graph = merge_relationship_graph(graph, [edge])
        relationships = card.get("relationships")
        if isinstance(relationships, dict):
            relationship_items = relationships.items()
        elif isinstance(relationships, list):
            relationship_items = (("", relation) for relation in relationships)
        else:
            relationship_items = []
        for fallback_target, relation in relationship_items:
            if not isinstance(relation, dict):
                continue
            target = _text(relation.get("target") or relation.get("name") or fallback_target)
            if not target:
                continue
            graph = merge_relationship_graph(
                graph,
                [
                    {
                        "source": source,
                        "target": target,
                        "relation_type": relation.get("relation_type"),
                        "bond": relation.get("bond"),
                        "current_state": relation.get("current_state"),
                        "trust": relation.get("trust"),
                        "tension": relation.get("tension"),
                    }
                ],
            )
    return graph


def select_relationship_subgraph(edges: Any, character_names: Iterable[str]) -> list[dict[str, Any]]:
    names = {_text(name) for name in character_names if _text(name)}
    selected: list[dict[str, Any]] = []
    for edge in normalize_relationship_graph(edges):
        if edge["source"] not in names or edge["target"] not in names:
            continue
        projected = {key: deepcopy(value) for key, value in edge.items() if key != "private_notes"}
        selected.append(projected)
    return selected
