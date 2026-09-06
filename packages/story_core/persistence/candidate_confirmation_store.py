from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from packages.story_core.persistence.project_locking import with_project_update_lock
from packages.story_core.relationship_graph import graph_from_character_cards


# --- Canon registry persistence --------------------------------------------


class _NullCanonDesigner:
    """Placeholder designer used during candidate confirmation.

    The confirmation path never calls
    :meth:`CanonService.ensure_requirements`; the
    :meth:`CanonService.apply_delta` path is the only thing
    that runs, and it does not need a designer. If a future
    caller wants the confirmation to also promote / create
    the entities the director asked for, it must pass a real
    designer; the canon delta is the user-approved surface and
    must never invent new cards on the user's behalf.
    """

    def design(self, requirement: Any, registry: Any) -> Any:  # pragma: no cover
        raise RuntimeError(
            "confirmation path must not call the designer; "
            "use the preflight to add new entities before confirmation"
        )


def _registry_to_payload(registry: Any) -> dict[str, Any]:
    """Serialise a :class:`CanonRegistry` to a plain dict.

    The on-disk shape mirrors the in-memory maps so a future
    reader can stream the registry without re-deriving the
    alias / name indexes. ``_by_id`` is the source of truth;
    the name and alias indexes are rebuilt on load.
    """
    from packages.story_core.canon.contracts import Lifecycle  # noqa: F401

    by_id: dict[str, dict[str, Any]] = {}
    for entity_id, entity in registry._by_id.items():  # type: ignore[attr-defined]
        by_id[str(entity_id)] = {
            "entity_id": str(entity.entity_id),
            "kind": str(entity.kind),
            "display_name": str(entity.display_name),
            "aliases": [str(alias) for alias in entity.aliases],
            "lifecycle": str(entity.lifecycle),
            "extensions": dict(entity.extensions or {}),
        }
    relationships = [
        dict(edge)
        for edge in registry.relationships()  # type: ignore[attr-defined]
    ]
    timeline = [dict(entry) for entry in registry.timeline()]  # type: ignore[attr-defined]
    foreshadowing = [
        dict(entry) for entry in registry.foreshadowing()  # type: ignore[attr-defined]
    ]
    return {
        "schema_version": "canon-registry/v1",
        "by_id": by_id,
        "relationships": relationships,
        "timeline": timeline,
        "foreshadowing": foreshadowing,
    }


def _registry_from_payload(payload: dict[str, Any]) -> Any:
    """Rebuild a :class:`CanonRegistry` from its on-disk payload."""
    from packages.story_core.canon.registry import CanonRegistry
    from packages.story_core.canon.service import is_plausible_location

    registry = CanonRegistry()
    by_id = payload.get("by_id") or {}
    if not isinstance(by_id, dict):
        return registry
    for raw in by_id.values():
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        if not kind:
            continue
        extensions = dict(raw.get("extensions") or {})
        if "location" in extensions and not is_plausible_location(
            extensions.get("location")
        ):
            extensions.pop("location", None)
            extensions.pop("previous_location", None)
            extensions.pop("last_moved_chapter", None)
        try:
            registry.add(
                kind=kind,  # type: ignore[arg-type]
                name=str(raw.get("display_name") or raw.get("entity_id") or ""),
                aliases=[str(item) for item in (raw.get("aliases") or [])],
                entity_id=str(raw.get("entity_id") or ""),
                lifecycle=str(raw.get("lifecycle") or "proposed"),  # type: ignore[arg-type]
                extensions=extensions,
            )
        except ValueError:
            # Duplicate id / alias collision means the file
            # was hand-edited; fall through to the next
            # entry rather than abort the whole load.
            continue
    for edge in payload.get("relationships") or []:
        if not isinstance(edge, dict):
            continue
        try:
            registry.add_relationship(
                subject_id=str(edge.get("subject_id") or ""),
                predicate=str(edge.get("predicate") or ""),
                object_id=str(edge.get("object_id") or ""),
                polarity=str(edge.get("polarity") or "added"),
                chapter_number=int(edge.get("chapter_number") or 0),
                source_sentence=str(edge.get("source_sentence") or ""),
                confidence=float(edge.get("confidence") or 1.0),
            )
        except ValueError:
            continue
    for entry in payload.get("timeline") or []:
        if not isinstance(entry, dict):
            continue
        try:
            registry.add_timeline_marker(
                marker=str(entry.get("marker") or ""),
                chapter_number=int(entry.get("chapter_number") or 0),
                source_sentence=str(entry.get("source_sentence") or ""),
            )
        except ValueError:
            continue
    for entry in payload.get("foreshadowing") or []:
        if not isinstance(entry, dict):
            continue
        try:
            registry.add_foreshadowing_change(
                foreshadowing_id=str(entry.get("foreshadowing_id") or ""),
                action=str(entry.get("action") or ""),
                detail=str(entry.get("detail") or ""),
                chapter_number=int(entry.get("chapter_number") or 0),
                source_sentence=str(entry.get("source_sentence") or ""),
            )
        except ValueError:
            continue
    return registry


class CandidateConfirmationStoreMixin:
    """Candidate confirmation, discard, canon updates, and rollback boundaries."""

    @with_project_update_lock
    def confirm_candidate(self, candidate_id: str, *, accept_quality_warnings: bool = False) -> dict[str, Any]:
        candidate = self.candidate_store.get(candidate_id)
        if candidate is None:
            raise FileNotFoundError("candidate_not_found")
        project = self.project()
        project_id = str(
            project.get("project_id")
            or project.get("active_story_id")
            or self.state().get("story_id")
            or self.root.name
        )
        if candidate.project_id != project_id:
            raise FileNotFoundError("candidate_not_found")
        if candidate.status == "confirmed":
            return {"schema_version": "file-project-candidate-confirm/v1", "candidate": candidate.to_dict()}
        if candidate.status != "pending":
            raise ValueError("candidate_not_pending")
        payload = dict(candidate.submission_payload)
        if not payload:
            raise ValueError("candidate_submission_payload_missing")
        payload["body"] = candidate.body
        payload["chapter_title"] = candidate.chapter_title or payload.get("chapter_title")

        # The confirmation is the single atomic boundary the user
        # can trust. The body runs the legacy ``persist_bundle``
        # (which writes the chapter JSON, the markdown body, the
        # state / project ledgers, the per-chapter review, and the
        # commit log) and then the snapshot / stale-marker
        # writes. A partial failure rolls every managed file back
        # to the pre-confirmation state so the candidate stays
        # ``pending`` and the user can re-confirm or discard
        # without ever having had a "confirmed" candidate they
        # could not trust.
        from packages.story_core.persistence.project_transaction import (
            ProjectTransaction,
        )

        with ProjectTransaction.create(
            self.root,
            snapshot_store=self.snapshot_store,
            managed_paths=self._managed_paths_for_transaction(),
            managed_directories=self._managed_directories_for_transaction(),
        ):
            self.persist_bundle(
                payload,
                operation=candidate.operation,
                accept_quality_warnings=accept_quality_warnings,
            )
            # Apply the candidate's continuity delta to the
            # project canon so the next chapter's director
            # context sees the characters, items, relationships,
            # and facts the user just confirmed. The
            # apply happens *inside* the transaction so a
            # mid-flight failure rolls the canon write back
            # alongside the chapter / state / project writes.
            self._apply_candidate_canon_delta(candidate)
            self._sync_candidate_character_additions(candidate)
            self._wrap_confirmation_in_transaction(candidate)
        candidate.confirm()
        self.candidate_store.save(candidate)
        return {"schema_version": "file-project-candidate-confirm/v1", "candidate": candidate.to_dict()}

    # --- Transaction-managed paths -----------------------------------------

    def _managed_paths_for_transaction(self) -> list[Path]:
        """The explicit files a candidate confirmation touches.

        These are the top-level metadata documents plus the
        per-chapter review. Chapter JSONs and continuity
        snapshots live in directories that are tracked via
        :meth:`_managed_directories_for_transaction` so the
        transaction picks up additions made during the body.
        """
        return [
            self.webnovel_dir / "state.json",
            self.webnovel_dir / "project.json",
            self.story_system_dir / "MASTER_SETTING.json",
            self.story_system_dir / "chapter-index.json",
        ]

    def _managed_directories_for_transaction(self) -> list[Path]:
        """The directories a candidate confirmation writes into.

        Every file inside these directories is part of the
        transaction's recovery snapshot, so a fresh snapshot
        file or a regenerated commit log is rolled back when
        the body raises.
        """
        return [
            self.story_system_dir / "chapters",
            self.story_system_dir / "reviews",
            self.story_system_dir / "continuity",
            self.story_system_dir / "commits",
            self.story_system_dir / "canon",
            self.chapters_dir,
        ]

    # --- Canon delta application -------------------------------------------

    def _apply_candidate_canon_delta(self, candidate: Any) -> dict[str, int]:
        """Apply a candidate's ``continuity_delta`` to the project canon.

        The user feedback after Tasks 10-14 called out that the
        delta was only written as a snapshot summary — it never
        actually touched the characters, items, relationships,
        or facts the chapter was about. This helper is the
        missing link: it loads any existing canon registry,
        applies the candidate's delta, and persists the
        updated registry so the next chapter's director context
        sees the world the user confirmed.

        Returns the per-operation apply count so the
        ``_wrap_confirmation_in_transaction`` hook can surface
        it on the snapshot summary. A candidate with no delta
        returns zero counts and leaves the registry untouched.
        """
        delta = getattr(candidate, "continuity_delta", None)
        if delta is None:
            return {
                "entity_additions": 0,
                "entity_updates": 0,
                "relationship_changes": 0,
                "inventory_changes": 0,
                "task_progressions": 0,
                "location_movements": 0,
                "timeline_advances": 0,
                "foreshadowing_changes": 0,
            }

        from packages.story_core.canon.service import CanonService

        registry = self._load_canon_registry()
        service = CanonService(
            registry=registry, designer=_NullCanonDesigner()
        )
        counts = service.apply_delta(delta)
        self._save_canon_registry(registry)
        return counts

    def _sync_candidate_character_additions(self, candidate: Any) -> None:
        """Expose confirmed new characters on the normal character-card page."""
        delta = getattr(candidate, "continuity_delta", None)
        additions = list(getattr(delta, "entity_additions", []) or [])
        existing_names = {
            str(card.get("name") or "").strip()
            for source in (
                self.project().get("character_profiles", []),
                self.state().get("characters", []),
            )
            for card in (source if isinstance(source, list) else [])
            if isinstance(card, dict) and str(card.get("name") or "").strip()
        }
        generated: list[dict[str, Any]] = []
        for addition in additions:
            if str(getattr(addition, "kind", "")) != "character":
                continue
            name = str(getattr(addition, "canonical_name", "") or "").strip()
            if not name or name in existing_names:
                continue
            attributes = dict(getattr(addition, "attributes", {}) or {})
            occupation = str(attributes.get("occupation_or_role") or "").strip()
            current_state = str(attributes.get("current_state") or "").strip()
            generated.append(
                {
                    "name": name,
                    "role": occupation or "配角",
                    "character_tier": "supporting",
                    "aliases": list(getattr(addition, "aliases", []) or []),
                    "identity_profile": {
                        "aliases": list(getattr(addition, "aliases", []) or []),
                        "current_identity": str(attributes.get("identity") or ""),
                        "occupation": occupation,
                        "origin": str(attributes.get("origin") or ""),
                    },
                    "background_profile": {
                        "upbringing": str(attributes.get("origin") or ""),
                    },
                    "story_drive": {
                        "immediate_goal": str(attributes.get("present_goal") or ""),
                        "motivation": str(attributes.get("present_goal") or ""),
                        "failure_stakes": str(
                            attributes.get("fear_or_weakness") or ""
                        ),
                    },
                    "performance_profile": {
                        "behavior_patterns": [
                            str(attributes.get("behavioral_habits") or "")
                        ]
                        if str(attributes.get("behavioral_habits") or "").strip()
                        else [],
                        "speech_style": str(
                            attributes.get("speech_tendency") or ""
                        ),
                    },
                    "knowledge_boundary": list(
                        attributes.get("knowledge_boundary") or []
                    ),
                    "current_state": {"summary": current_state}
                    if current_state
                    else {},
                    "change_arc": str(attributes.get("change_arc") or ""),
                }
            )
        if not generated:
            return
        cards = self._merge_generated_character_cards(generated)
        project = self.project()
        state = self.state()
        project["character_profiles"] = deepcopy(cards)
        project["relationship_graph"] = graph_from_character_cards(cards)
        state["characters"] = deepcopy(cards)
        self._write_json(self.webnovel_dir / "project.json", project)
        self._write_json(self.webnovel_dir / "state.json", state)

    def _load_canon_registry(self) -> Any:
        """Read the on-disk canon registry, or return a fresh one.

        The registry is intentionally not versioned through the
        candidate confirmation transaction: a partial apply
        from a previous failed run is recoverable, and a
        missing file is the common case for a project that has
        not yet had any candidates confirmed.
        """
        from packages.story_core.canon.registry import CanonRegistry

        target = self.story_system_dir / "canon" / "registry.json"
        if not target.is_file():
            return CanonRegistry()
        try:
            payload = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError):
            return CanonRegistry()
        if not isinstance(payload, dict):
            return CanonRegistry()
        return _registry_from_payload(payload)

    def _save_canon_registry(self, registry: Any) -> Path:
        """Write the in-memory canon registry back to disk atomically."""
        from packages.story_core.continuity.snapshot import ChapterSnapshot  # noqa: F401  (typing only)
        from packages.story_core.persistence.snapshot_store import SnapshotStore

        target = self.story_system_dir / "canon" / "registry.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = _registry_to_payload(registry)
        # The transaction is already guarding this write; a
        # direct atomic write keeps the on-disk format
        # consistent without a second rollback layer.
        SnapshotStore().write_json_atomic(target, payload)
        return target

    def _wrap_confirmation_in_transaction(self, candidate: Any) -> None:
        """Attach the chapter snapshot (and stale markers) to a confirmed candidate.

        Called from ``confirm_candidate`` after ``persist_bundle``
        has already written the chapter JSON, the markdown body, and
        the state / project ledgers. The wrapper is intentionally
        idempotent: re-confirming the same candidate replaces the
        snapshot in place.
        """
        from packages.story_core.persistence.project_transaction import (
            build_chapter_snapshot,
            slice_state_for_snapshot,
            summarise_continuity_delta,
        )

        chapter_number = int(getattr(candidate, "chapter_number", 0) or 0)
        if chapter_number <= 0:
            return

        # The post-confirm state is the source-of-truth for
        # regenerations, so the snapshot stores a small slice of it.
        post_state = self.state()
        snapshot = build_chapter_snapshot(
            chapter_number=chapter_number,
            candidate_id=str(getattr(candidate, "candidate_id", "")),
            operation=str(getattr(candidate, "operation", "generate")),
            body=str(getattr(candidate, "body", "") or ""),
            state_after=slice_state_for_snapshot(post_state),
            continuity_delta_summary=summarise_continuity_delta(
                getattr(candidate, "continuity_delta", None)
            ),
        )
        self.continuity_store.write_snapshot(snapshot)

        if str(getattr(candidate, "operation", "generate")) == "regenerate":
            stale = [
                number
                for number in self.chapter_numbers()
                if number > chapter_number
            ]
            if stale:
                self.continuity_store.mark_stale(stale)

    @with_project_update_lock
    def discard_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Discard a pending candidate without touching confirmed state."""
        candidate = self.candidate_store.get(candidate_id)
        if candidate is None:
            raise FileNotFoundError("candidate_not_found")
        project = self.project()
        project_id = str(
            project.get("project_id")
            or project.get("active_story_id")
            or self.state().get("story_id")
            or self.root.name
        )
        if candidate.project_id != project_id:
            raise FileNotFoundError("candidate_not_found")
        if candidate.status == "discarded":
            return {
                "schema_version": "file-project-candidate-discard/v1",
                "candidate": candidate.to_dict(),
            }
        candidate.discard()
        self.candidate_store.save(candidate)
        return {
            "schema_version": "file-project-candidate-discard/v1",
            "candidate": candidate.to_dict(),
        }
