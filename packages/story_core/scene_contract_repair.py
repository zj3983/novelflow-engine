from __future__ import annotations

from typing import Any


def build_scene_contract_repair_plan(review: dict[str, Any], scene_cards: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    review = review if isinstance(review, dict) else {}
    failures = review.get("scene_contract_failures") if isinstance(review.get("scene_contract_failures"), list) else []
    if not failures:
        return {}

    cards_by_id = {
        str(card.get("scene_id") or ""): card
        for card in (scene_cards or [])
        if isinstance(card, dict) and str(card.get("scene_id") or "").strip()
    }
    grouped: dict[str, dict[str, Any]] = {}
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        scene_id = str(failure.get("scene_id") or "").strip()
        if not scene_id:
            continue
        card = cards_by_id.get(scene_id, {})
        scene_entry = grouped.setdefault(
            scene_id,
            {
                "scene_id": scene_id,
                "template_id": str(card.get("template_id") or ""),
                "location": str(card.get("location") or ""),
                "purpose": str(card.get("purpose") or ""),
                "rewrite_scope": "scene_only",
                "missing_visible_consequences": [],
                "repair_instructions": [],
            },
        )
        consequence = {
            "id": str(failure.get("consequence_id") or "visible_consequence"),
            "description": str(failure.get("description") or ""),
            "requires_any": [str(item) for item in failure.get("requires_any", []) if str(item).strip()]
            if isinstance(failure.get("requires_any"), list)
            else [],
            "revision": str(failure.get("revision") or ""),
        }
        scene_entry["missing_visible_consequences"].append(consequence)
        if consequence["revision"] and consequence["revision"] not in scene_entry["repair_instructions"]:
            scene_entry["repair_instructions"].append(consequence["revision"])

    failed_scenes = list(grouped.values())
    if not failed_scenes:
        return {}
    return {
        "schema_version": "scene-contract-repair/v1",
        "rewrite_scope": "failed_scenes_only",
        "preserve_other_scenes": True,
        "failed_scenes": failed_scenes,
        "global_rule": (
            "Only rewrite failed scenes enough to surface the missing visible consequences; "
            "preserve other scenes, ledger facts, order, names, and world-state decisions."
        ),
    }
