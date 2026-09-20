"""Adapt modular-agent output to the legacy workbench bundle contract."""

from __future__ import annotations

from typing import Any

from packages.story_core.chapter_history import apply_chapter_history
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import StoryState


def adapt_modular_bundle_to_legacy(
    *,
    story: StoryState,
    modular_bundle: Any,
    chapter_number: int,
) -> ChapterBundle:
    """Convert one completed modular pipeline result without side effects."""

    director_artifact = modular_bundle.director_artifact
    chapter_title = str(director_artifact.chapter_title or "").strip() or (
        f"第{chapter_number}章"
    )
    scene_beats = list(director_artifact.scene_beats or [])
    character_moves = [
        {
            "name": str(intent.name or ""),
            "goal": str(intent.want or ""),
            "target": str(intent.target or ""),
            "emotion": str(intent.emotion or ""),
            "action": str(intent.move or ""),
            "speech_strategy": str(intent.speech_strategy or ""),
            "withhold": str(intent.withhold or ""),
            "reaction": str(intent.reaction or ""),
            "dramatic_function": str(intent.dramatic_function or ""),
            "scene_order": int(beat.order or 0),
            "importance": 5,
            "kind": "character",
        }
        for beat in scene_beats
        for intent in (beat.character_intents or [])
        if str(intent.name or "").strip()
    ]
    if not character_moves:
        character_moves = [
            {
                "name": str(requirement.name or ""),
                "importance": int(requirement.importance or 5),
                "action": "按导演场景计划参与本章",
                "kind": "character",
            }
            for requirement in (director_artifact.entity_requirements or [])
            if str(requirement.kind or "") == "character"
            and str(requirement.name or "").strip()
        ]
    scene_cards = [
        {
            "scene_id": f"director-{chapter_number}-{int(beat.order or 0)}",
            "location": str(beat.location or ""),
            "purpose": str(beat.purpose or ""),
            "conflict": str(beat.conflict or ""),
            "participants": list(beat.participants or []),
            "character_intents": [
                intent.model_dump(mode="json")
                for intent in (beat.character_intents or [])
            ],
            "action": str(beat.action or ""),
            "result": str(beat.result or ""),
            "emotional_turn": str(beat.emotional_turn or ""),
            "relationship_shift": str(beat.relationship_shift or ""),
            "ending_pressure": str(beat.ending_pressure or ""),
            "order": int(beat.order or 0),
        }
        for beat in scene_beats
    ]
    chapter_intent = {
        "chapter_title": chapter_title,
        "primary_conflict": {"summary": director_artifact.chapter_goal},
        "secondary_conflict": {},
        "next_focus": str(director_artifact.hook or ""),
        "approved_new_characters": [
            str(requirement.name or "")
            for requirement in director_artifact.entity_requirements
        ],
        "deferred_characters": [],
        "rejected_characters": [],
    }
    event_plan = {
        "chapter_title": chapter_title,
        "scene_chain": scene_cards,
        "ordered_actions": [
            {
                "order": int(beat.order or 0),
                "location": str(beat.location or ""),
                "action": str(beat.action or ""),
                "change": str(beat.result or ""),
                "next": str(director_artifact.hook or ""),
            }
            for beat in scene_beats
        ],
    }

    raw_findings = list(
        getattr(modular_bundle, "consistency_findings", []) or []
    )
    blocking_findings = [
        finding for finding in raw_findings if bool(finding.get("blocking"))
    ]
    non_blocking_findings = [
        finding for finding in raw_findings if not bool(finding.get("blocking"))
    ]
    issues = [str(finding.get("code") or "") for finding in blocking_findings]
    writing_review_pass = not blocking_findings
    continuity_delta = getattr(modular_bundle, "continuity_delta", None)
    writer_context = getattr(modular_bundle, "writer_context", None)
    writer_character_cards = list(
        getattr(writer_context, "character_cards", []) or []
    )
    body_folded = str(modular_bundle.body or "").casefold()
    required_character_names = {
        str(move.get("name") or "").strip().casefold()
        for move in character_moves
        if str(move.get("kind") or "character").strip().lower() == "character"
        and str(move.get("name") or "").strip()
    }
    character_cards = []
    for card in writer_character_cards:
        if not isinstance(card, dict):
            continue
        names = [str(card.get("name") or "").strip()]
        names.extend(
            str(alias).strip()
            for alias in (card.get("aliases") or [])
            if str(alias).strip()
        )
        if (
            any(name and name.casefold() in required_character_names for name in names)
            if required_character_names
            else any(name and name.casefold() in body_folded for name in names)
        ):
            character_cards.append(dict(card))
    quality_report: dict[str, Any] = {
        "ok": writing_review_pass,
        "schema_version": "file-writing-review/v1",
        "writing_review": {
            "pass": writing_review_pass,
            "issues": issues,
            "blocking": [
                {
                    "code": str(finding.get("code") or ""),
                    "message": str(finding.get("message") or ""),
                    "source": str(finding.get("source") or "consistency"),
                }
                for finding in blocking_findings
            ],
            "warnings": [
                {
                    "code": str(finding.get("code") or ""),
                    "message": str(finding.get("message") or ""),
                    "source": str(finding.get("source") or "consistency"),
                }
                for finding in non_blocking_findings
            ],
            "source": "modular_pipeline",
        },
        "modular_pipeline": {
            "director_artifact_present": True,
            "fact_extractor_chapter": (
                continuity_delta.chapter_number
                if continuity_delta is not None
                else None
            ),
            "canon_preflight": dict(modular_bundle.canon_preflight or {}),
            "canon_review_snapshot": {
                "schema_version": str(
                    (getattr(modular_bundle, "canon_review_snapshot", {}) or {}).get(
                        "schema_version", ""
                    )
                ),
                "as_of_chapter": (
                    getattr(modular_bundle, "canon_review_snapshot", {}) or {}
                ).get("as_of_chapter"),
                "state_source": str(
                    (getattr(modular_bundle, "canon_review_snapshot", {}) or {}).get(
                        "state_source", ""
                    )
                ),
                "historical_rewrite": bool(
                    (getattr(modular_bundle, "canon_review_snapshot", {}) or {}).get(
                        "historical_rewrite", False
                    )
                ),
                "bounded_state_available": bool(
                    (getattr(modular_bundle, "canon_review_snapshot", {}) or {}).get(
                        "bounded_state_available", False
                    )
                ),
            },
        },
    }
    scene_results = [
        str(beat.result or "").strip()
        for beat in scene_beats
        if str(beat.result or "").strip()
    ]
    summary_text = "；".join(scene_results) or str(
        director_artifact.chapter_goal or ""
    ).strip()
    next_outline = str(
        director_artifact.hook or director_artifact.ending_state or ""
    ).strip()
    chapter_summary = {
        "chapter_number": chapter_number,
        "chapter_title": chapter_title,
        "cadence": "measured",
        "summary": summary_text,
        "facts": scene_results,
        "unresolved_threads": [next_outline] if next_outline else [],
        "resolved_threads": [],
        "next_focus": next_outline,
        "primary_conflict": {
            "summary": str(director_artifact.chapter_goal or "").strip()
        },
        "secondary_conflict": {},
        "event_beat": {"turn": next_outline},
    }
    updated_story_payload = apply_chapter_history(
        story.model_dump(mode="json"),
        chapter_summary,
    )
    working_story = StoryState.model_validate(updated_story_payload)

    return ChapterBundle(
        chapter_number=chapter_number,
        body=modular_bundle.body,
        chapter_title=chapter_title,
        cadence="measured",
        chapter_intent=chapter_intent,
        character_moves=character_moves,
        memory_constraints={"must_keep_facts": [], "ledger_updates": {}},
        event_plan=event_plan,
        chapter_seed={},
        simulation_plan={},
        world_events=[],
        scene_cards=scene_cards,
        simulation_status={"status": "skipped", "reason": "modular_pipeline"},
        action_briefs=character_moves,
        conflict_summary={},
        event_beat={"turn": str(director_artifact.hook or "")},
        character_cards=character_cards,
        foreshadowing=list(working_story.foreshadowing or []),
        next_outline=next_outline,
        updated_story=working_story,
        chapter_summary=chapter_summary,
        quality_report=quality_report,
        pipeline_stages=[
            "character_intent",
            "director",
            "canon_preflight",
            "writer",
            "fact_extractor",
        ],
        context_snapshot_id=f"modular-pipeline:chapter-{chapter_number}",
        continuity_delta=continuity_delta,
    )
