"""Replayable history for the canonical registry.

``registry.json`` is a materialized projection.  This module keeps the
small, explicit history needed to rebuild that projection after a chapter
replacement.  It deliberately does not try to undo a Canon mutation: every
rebuild starts with a baseline and applies the confirmed deltas forward in
their original order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from packages.story_core.canon.registry import CanonRegistry
from packages.story_core.canon.service import CanonService
from packages.story_core.continuity.delta import ContinuityDelta


CANON_BASELINE_SCHEMA = "canon-baseline/v1"
CANON_HISTORY_SCHEMA = "canon-history/v1"

_DELTA_SECTIONS = (
    "entity_additions",
    "entity_updates",
    "relationship_changes",
    "inventory_changes",
    "task_progressions",
    "location_movements",
    "timeline_advances",
    "foreshadowing_changes",
)


def _stable(value: Any) -> Any:
    """Sort mapping keys without changing the order of effect lists."""

    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, list):
        return [_stable(item) for item in value]
    if isinstance(value, tuple):
        return [_stable(item) for item in value]
    return value


def _delta_semantic_payload(delta: ContinuityDelta | dict[str, Any] | None) -> dict[str, Any] | None:
    if delta is None:
        return None
    parsed = delta if isinstance(delta, ContinuityDelta) else ContinuityDelta.model_validate(delta)
    payload: dict[str, Any] = {}
    for section in _DELTA_SECTIONS:
        payload[section] = [
            _stable(item.model_dump(mode="json", exclude={"chapter_number", "source_sentence", "confidence"}))
            for item in getattr(parsed, section)
        ]
    return payload


def delta_semantic_hash(delta: ContinuityDelta | dict[str, Any] | None) -> str:
    """Hash canonical effects while ignoring unstable provenance."""

    payload = _delta_semantic_payload(delta) or {section: [] for section in _DELTA_SECTIONS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def registry_to_payload(registry: CanonRegistry) -> dict[str, Any]:
    """Serialize a registry using the existing ``registry.json`` shape."""

    by_id: dict[str, dict[str, Any]] = {}
    for entity_id, entity in registry._by_id.items():  # noqa: SLF001 - projection boundary
        by_id[str(entity_id)] = {
            "entity_id": str(entity.entity_id),
            "kind": str(entity.kind),
            "display_name": str(entity.display_name),
            "aliases": [str(alias) for alias in entity.aliases],
            "lifecycle": str(entity.lifecycle),
            "extensions": dict(entity.extensions or {}),
        }
    return {
        "schema_version": "canon-registry/v1",
        "by_id": by_id,
        "relationships": [dict(edge) for edge in registry.relationships()],
        "timeline": [dict(entry) for entry in registry.timeline()],
        "foreshadowing": [dict(entry) for entry in registry.foreshadowing()],
    }


def registry_from_payload(payload: dict[str, Any] | None) -> CanonRegistry:
    """Load a registry payload without accepting a second history format."""

    registry = CanonRegistry()
    if not isinstance(payload, dict):
        return registry
    by_id = payload.get("by_id") or {}
    if isinstance(by_id, dict):
        for raw in by_id.values():
            if not isinstance(raw, dict):
                continue
            try:
                registry.add(
                    kind=str(raw.get("kind") or ""),  # type: ignore[arg-type]
                    name=str(raw.get("display_name") or raw.get("entity_id") or ""),
                    aliases=[str(item) for item in (raw.get("aliases") or [])],
                    entity_id=str(raw.get("entity_id") or ""),
                    lifecycle=str(raw.get("lifecycle") or "proposed"),  # type: ignore[arg-type]
                    extensions=dict(raw.get("extensions") or {}),
                )
            except (TypeError, ValueError):
                continue
    for raw in payload.get("relationships") or []:
        if not isinstance(raw, dict):
            continue
        try:
            registry.add_relationship(
                subject_id=str(raw.get("subject_id") or ""),
                predicate=str(raw.get("predicate") or ""),
                object_id=str(raw.get("object_id") or ""),
                polarity=str(raw.get("polarity") or "added"),
                chapter_number=int(raw.get("chapter_number") or 0),
                source_sentence=str(raw.get("source_sentence") or ""),
                confidence=float(raw.get("confidence") or 1.0),
            )
        except (TypeError, ValueError):
            continue
    for raw in payload.get("timeline") or []:
        if not isinstance(raw, dict):
            continue
        try:
            registry.add_timeline_marker(
                marker=str(raw.get("marker") or ""),
                chapter_number=int(raw.get("chapter_number") or 0),
                source_sentence=str(raw.get("source_sentence") or ""),
            )
        except (TypeError, ValueError):
            continue
    for raw in payload.get("foreshadowing") or []:
        if not isinstance(raw, dict):
            continue
        try:
            registry.add_foreshadowing_change(
                foreshadowing_id=str(raw.get("foreshadowing_id") or ""),
                action=str(raw.get("action") or ""),
                detail=str(raw.get("detail") or ""),
                chapter_number=int(raw.get("chapter_number") or 0),
                source_sentence=str(raw.get("source_sentence") or ""),
            )
        except (TypeError, ValueError):
            continue
    return registry


@dataclass(frozen=True)
class CanonHistoryEvent:
    event_id: str
    chapter_number: int
    candidate_id: str
    delta_semantic_hash: str
    continuity_delta: dict[str, Any]
    confirmed_at: str
    sequence: int

    @classmethod
    def from_delta(
        cls,
        delta: ContinuityDelta,
        *,
        candidate_id: str,
        sequence: int,
        confirmed_at: str | None = None,
    ) -> "CanonHistoryEvent":
        semantic_hash = delta_semantic_hash(delta)
        stable_candidate = str(candidate_id or f"chapter-{delta.chapter_number}")
        return cls(
            event_id=f"canon-event:{stable_candidate}:{semantic_hash[:20]}",
            chapter_number=int(delta.chapter_number),
            candidate_id=str(candidate_id or ""),
            delta_semantic_hash=semantic_hash,
            continuity_delta=delta.model_dump(mode="json"),
            confirmed_at=confirmed_at or datetime.now(timezone.utc).isoformat(),
            sequence=int(sequence),
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CanonHistoryEvent":
        if not raw.get("event_id") or not raw.get("candidate_id") or not raw.get("delta_semantic_hash"):
            raise ValueError("canon_history_event_identity_missing")
        delta = ContinuityDelta.model_validate(raw.get("continuity_delta") or {})
        event = cls(
            event_id=str(raw.get("event_id") or ""),
            chapter_number=int(raw.get("chapter_number") or delta.chapter_number),
            candidate_id=str(raw.get("candidate_id") or ""),
            delta_semantic_hash=str(raw.get("delta_semantic_hash") or delta_semantic_hash(delta)),
            continuity_delta=delta.model_dump(mode="json"),
            confirmed_at=str(raw.get("confirmed_at") or ""),
            sequence=int(raw.get("sequence") or 0),
        )
        expected = CanonHistoryEvent.from_delta(
            delta,
            candidate_id=event.candidate_id,
            sequence=event.sequence,
            confirmed_at=event.confirmed_at or None,
        )
        if event.event_id and event.event_id != expected.event_id:
            raise ValueError("canon_history_event_id_mismatch")
        if event.delta_semantic_hash != expected.delta_semantic_hash:
            raise ValueError("canon_history_delta_hash_mismatch")
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "chapter_number": self.chapter_number,
            "candidate_id": self.candidate_id,
            "delta_semantic_hash": self.delta_semantic_hash,
            "continuity_delta": self.continuity_delta,
            "confirmed_at": self.confirmed_at,
            "sequence": self.sequence,
        }

    def delta(self) -> ContinuityDelta:
        return ContinuityDelta.model_validate(self.continuity_delta)


@dataclass
class CanonHistory:
    baseline_revision: str = "baseline-1"
    latest_confirmed_chapter: int = 0
    events: list[CanonHistoryEvent] = field(default_factory=list)
    confirmed_candidates: dict[str, str] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = CANON_HISTORY_SCHEMA

    @classmethod
    def empty(cls, *, baseline_revision: str = "baseline-1") -> "CanonHistory":
        return cls(baseline_revision=baseline_revision)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "CanonHistory":
        if not isinstance(raw, dict) or raw.get("schema_version") not in {None, CANON_HISTORY_SCHEMA}:
            raise ValueError("canon_history_schema_unsupported")
        events = [CanonHistoryEvent.from_dict(item) for item in (raw.get("events") or []) if isinstance(item, dict)]
        if len({event.event_id for event in events}) != len(events):
            raise ValueError("canon_history_duplicate_event")
        candidate_ids = [event.candidate_id for event in events if event.candidate_id]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("canon_history_duplicate_candidate")
        latest = max((event.chapter_number for event in events), default=0)
        stored_latest = int(raw.get("latest_confirmed_chapter") or 0)
        if stored_latest and stored_latest != latest:
            raise ValueError("canon_history_latest_mismatch")
        return cls(
            baseline_revision=str(raw.get("baseline_revision") or "baseline-1"),
            latest_confirmed_chapter=latest,
            events=events,
            confirmed_candidates={str(k): str(v) for k, v in (raw.get("confirmed_candidates") or {}).items()},
            audit=[dict(item) for item in (raw.get("audit") or []) if isinstance(item, dict)],
        )

    def to_dict(self) -> dict[str, Any]:
        ordered_events = sorted(
            self.events,
            key=lambda event: (event.chapter_number, event.sequence, event.event_id),
        )
        return {
            "schema_version": self.schema_version,
            "baseline_revision": self.baseline_revision,
            "latest_confirmed_chapter": max((event.chapter_number for event in ordered_events), default=0),
            "events": [event.to_dict() for event in ordered_events],
            "confirmed_candidates": dict(self.confirmed_candidates),
            "audit": [dict(item) for item in self.audit],
        }

    def event_for_candidate(self, candidate_id: str) -> CanonHistoryEvent | None:
        matches = [event for event in self.events if event.candidate_id == str(candidate_id)]
        if len(matches) > 1:
            raise ValueError("canon_history_duplicate_candidate")
        return matches[0] if matches else None

    def events_through(self, chapter_number: int) -> list[CanonHistoryEvent]:
        return sorted(
            [event for event in self.events if event.chapter_number <= int(chapter_number)],
            key=lambda event: (event.chapter_number, event.sequence, event.event_id),
        )


@dataclass(frozen=True)
class CanonReplayFinding:
    code: str
    message: str
    chapter_number: int
    candidate_id: str = ""
    event_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": "error",
            "message": self.message,
            "chapter": self.chapter_number,
            "candidate_id": self.candidate_id,
            "event_id": self.event_id,
        }


@dataclass
class CanonReplayResult:
    status: str
    registry: CanonRegistry | None = None
    first_finding: CanonReplayFinding | None = None
    findings: list[CanonReplayFinding] = field(default_factory=list)
    replayed_event_ids: list[str] = field(default_factory=list)

    @property
    def first_conflict_chapter(self) -> int | None:
        return self.first_finding.chapter_number if self.first_finding else None


@dataclass
class CanonHistoryPlan:
    """Read-only staged result consumed by the project confirmation path."""

    status: str
    mode: str
    rewrite_chapter: int
    latest_confirmed_chapter: int
    baseline_payload: dict[str, Any] | None = None
    history_payload: dict[str, Any] | None = None
    registry_payload: dict[str, Any] | None = None
    findings: list[CanonReplayFinding] = field(default_factory=list)
    replacement_event_id: str = ""
    replayed_event_ids: list[str] = field(default_factory=list)
    old_event_id: str = ""
    bootstrap: bool = False

    @property
    def first_finding(self) -> CanonReplayFinding | None:
        return self.findings[0] if self.findings else None

    def to_result_dict(self) -> dict[str, Any]:
        first = self.first_finding
        return {
            "status": self.status,
            "mode": self.mode,
            "rewrite_chapter": self.rewrite_chapter,
            "replayed_through_chapter": self.latest_confirmed_chapter,
            "first_conflict_chapter": first.chapter_number if first else None,
            "findings": [item.to_dict() for item in self.findings],
            "old_event_id": self.old_event_id,
            "replacement_event_id": self.replacement_event_id,
            "replayed_event_ids": list(self.replayed_event_ids),
            "bootstrap": self.bootstrap,
        }


class _ReplayDesigner:
    def design(self, requirement: Any, registry: Any) -> Any:  # pragma: no cover
        raise RuntimeError("canon replay must not design entities")


def _finding(event: CanonHistoryEvent, code: str, message: str) -> CanonReplayFinding:
    return CanonReplayFinding(
        code=code,
        message=message,
        chapter_number=event.chapter_number,
        candidate_id=event.candidate_id,
        event_id=event.event_id,
    )


def strict_validate_delta(registry: CanonRegistry, event: CanonHistoryEvent) -> CanonReplayFinding | None:
    """Preflight every dependency before the permissive service is called."""

    delta = event.delta()
    known_ids = {entity.entity_id for entity in registry.list_all()}
    names_by_kind: dict[tuple[str, str], str] = {}
    for entity in registry.list_all():
        names_by_kind[(str(entity.kind), entity.display_name.strip().lower())] = entity.entity_id
        for alias in entity.aliases:
            names_by_kind[(str(entity.kind), str(alias).strip().lower())] = entity.entity_id

    for addition in delta.entity_additions:
        if not str(addition.entity_id).strip() or not str(addition.canonical_name or addition.entity_id).strip():
            return _finding(event, "CANON_RECONCILIATION_HISTORY_UNSUPPORTED", "entity addition has no stable id or name")
        existing = registry.get(addition.entity_id)
        if existing is not None:
            if (
                str(existing.kind) != str(addition.kind)
                or existing.display_name != str(addition.canonical_name or addition.entity_id)
            ):
                return _finding(event, "CANON_RECONCILIATION_ALIAS_CONFLICT", f"entity id {addition.entity_id} conflicts with an existing Canon entity")
            known_ids.add(addition.entity_id)
            continue
        for name in [addition.canonical_name, *addition.aliases]:
            owner = names_by_kind.get((str(addition.kind), str(name).strip().lower()))
            if owner is not None and owner != addition.entity_id:
                return _finding(event, "CANON_RECONCILIATION_ALIAS_CONFLICT", f"{addition.kind}:{name} is already owned by {owner}")
        known_ids.add(addition.entity_id)
        names_by_kind[(str(addition.kind), addition.canonical_name.strip().lower())] = addition.entity_id
        for alias in addition.aliases:
            names_by_kind[(str(addition.kind), alias.strip().lower())] = addition.entity_id

    def require(entity_id: str, code: str, label: str) -> CanonReplayFinding | None:
        if entity_id not in known_ids:
            return _finding(event, code, f"{label} {entity_id} is not present at replay boundary")
        return None

    # CanonService applies entity additions, then entity updates, and only
    # then location movements.  Keep a local projection of the location
    # field so an event containing A -> B followed by B -> C is validated in
    # the same order without mutating the replay registry during preflight.
    staged_locations: dict[str, str] = {}
    for entity in registry.list_all():
        if isinstance(entity.extensions, dict) and entity.extensions.get("location") is not None:
            staged_locations[entity.entity_id] = str(entity.extensions["location"])
    created_addition_ids: set[str] = set()
    for addition in delta.entity_additions:
        # CanonService ignores a re-add whose entity_id is already present;
        # only a genuinely new entity gets the addition attributes before
        # later operations in this same delta run.
        if registry.get(addition.entity_id) is not None:
            continue
        if addition.entity_id in created_addition_ids:
            continue
        created_addition_ids.add(addition.entity_id)
        if isinstance(addition.attributes, dict) and addition.attributes.get("location") is not None:
            staged_locations[addition.entity_id] = str(addition.attributes["location"])

    for update in delta.entity_updates:
        result = require(update.entity_id, "CANON_RECONCILIATION_ENTITY_MISSING", "entity")
        if result:
            return result
        if isinstance(update.changes, dict) and "location" in update.changes:
            location = update.changes.get("location")
            if location is None:
                staged_locations.pop(update.entity_id, None)
            else:
                staged_locations[update.entity_id] = str(location)
    for change in delta.relationship_changes:
        if not str(change.predicate).strip():
            return _finding(event, "CANON_RECONCILIATION_RELATIONSHIP_ENDPOINT_MISSING", "relationship predicate is empty")
        result = require(change.subject_id, "CANON_RECONCILIATION_RELATIONSHIP_ENDPOINT_MISSING", "relationship subject")
        if result:
            return result
        result = require(change.object_id, "CANON_RECONCILIATION_RELATIONSHIP_ENDPOINT_MISSING", "relationship object")
        if result:
            return result
    for change in delta.inventory_changes:
        result = require(change.entity_id, "CANON_RECONCILIATION_INVENTORY_ENTITY_MISSING", "inventory entity")
        if result:
            return result
    for task in delta.task_progressions:
        result = require(task.task_id, "CANON_RECONCILIATION_TASK_MISSING", "task")
        if result:
            return result
    for movement in delta.location_movements:
        result = require(movement.entity_id, "CANON_RECONCILIATION_LOCATION_ENTITY_MISSING", "location entity")
        if result:
            return result
        if movement.from_location is not None:
            current_location = staged_locations.get(movement.entity_id)
            if current_location is not None and str(current_location) != str(movement.from_location):
                return _finding(
                    event,
                    "CANON_RECONCILIATION_LOCATION_STATE_MISMATCH",
                    f"location movement expects {movement.from_location}, current state is {current_location}",
                )
        staged_locations[movement.entity_id] = str(movement.to_location)

    foreshadowing_ids = {str(item.get("foreshadowing_id")) for item in registry.foreshadowing()}
    for change in delta.foreshadowing_changes:
        action = str(change.action)
        if action == "planted":
            foreshadowing_ids.add(str(change.foreshadowing_id))
        elif str(change.foreshadowing_id) not in foreshadowing_ids:
            return _finding(event, "CANON_RECONCILIATION_FORESHADOWING_INVALID", f"foreshadowing {change.foreshadowing_id} has no prior planted state")
    for marker in delta.timeline_advances:
        if not str(marker.marker).strip():
            return _finding(event, "CANON_RECONCILIATION_HISTORY_UNSUPPORTED", "timeline marker is empty")
    return None


def replay_canon_history(
    baseline_payload: dict[str, Any],
    events: Iterable[CanonHistoryEvent],
    *,
    as_of_chapter: int | None = None,
    strict: bool = True,
) -> CanonReplayResult:
    """Rebuild a registry by applying journal events in stable order."""

    registry = registry_from_payload(baseline_payload)
    ordered = sorted(
        [event for event in events if as_of_chapter is None or event.chapter_number <= int(as_of_chapter)],
        key=lambda event: (event.chapter_number, event.sequence, event.event_id),
    )
    service = CanonService(registry=registry, designer=_ReplayDesigner())
    applied: list[str] = []
    for event in ordered:
        if event.delta().chapter_number != event.chapter_number:
            finding = _finding(event, "CANON_RECONCILIATION_HISTORY_UNSUPPORTED", "event chapter and continuity delta chapter differ")
            return CanonReplayResult(status="UNSUPPORTED", registry=None, first_finding=finding, findings=[finding], replayed_event_ids=applied)
        if strict:
            finding = strict_validate_delta(registry, event)
            if finding is not None:
                return CanonReplayResult(status="CONFLICT", registry=None, first_finding=finding, findings=[finding], replayed_event_ids=applied)
        try:
            service.apply_delta(event.delta())
        except (TypeError, ValueError) as exc:
            finding = _finding(event, "CANON_RECONCILIATION_HISTORY_UNSUPPORTED", str(exc))
            return CanonReplayResult(status="UNSUPPORTED", registry=None, first_finding=finding, findings=[finding], replayed_event_ids=applied)
        applied.append(event.event_id)
    return CanonReplayResult(status="CLEAR", registry=registry, replayed_event_ids=applied)


def semantic_registry_payload(registry: CanonRegistry) -> Any:
    """Return a stable comparison form without changing list order."""

    return _stable(registry_to_payload(registry))


def semantic_registry_hash(registry: CanonRegistry) -> str:
    encoded = json.dumps(semantic_registry_payload(registry), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "CANON_BASELINE_SCHEMA",
    "CANON_HISTORY_SCHEMA",
    "CanonBaseline",
    "CanonHistory",
    "CanonHistoryEvent",
    "CanonHistoryPlan",
    "CanonReplayFinding",
    "CanonReplayResult",
    "delta_semantic_hash",
    "registry_from_payload",
    "registry_to_payload",
    "replay_canon_history",
    "semantic_registry_hash",
    "semantic_registry_payload",
    "strict_validate_delta",
]


@dataclass(frozen=True)
class CanonBaseline:
    registry: dict[str, Any]
    baseline_revision: str = "baseline-1"
    schema_version: str = CANON_BASELINE_SCHEMA

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CanonBaseline":
        if raw.get("schema_version") not in {None, CANON_BASELINE_SCHEMA}:
            raise ValueError("canon_baseline_schema_unsupported")
        registry = raw.get("registry")
        if not isinstance(registry, dict):
            raise ValueError("canon_baseline_registry_missing")
        return cls(
            registry=registry,
            baseline_revision=str(raw.get("baseline_revision") or "baseline-1"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "baseline_revision": self.baseline_revision,
            "registry": self.registry,
            "registry_semantic_hash": semantic_registry_hash(registry_from_payload(self.registry)),
        }
