from __future__ import annotations

from dataclasses import dataclass

from packages.story_core.skill_packs import SkillPack


COMMERCIAL_SHUANGWEN_SKILL_ID = "commercial-shuangwen"
COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_IDS = frozenset(
    {
        "plot-engine",
        "chapter-sop",
        "writer-execution",
        "review-checklist",
        "genre-examples",
    }
)
NARRATIVE_ENHANCEMENT_REQUIREMENTS = {
    COMMERCIAL_SHUANGWEN_SKILL_ID: COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_IDS,
}


@dataclass(frozen=True)
class NarrativeEnhancementStatus:
    skill_id: str
    status: str
    reason: str
    missing_module_ids: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.status == "available"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "missing_module_ids": list(self.missing_module_ids),
        }


def inspect_narrative_enhancement(
    skill_id: str,
    pack: SkillPack | None,
) -> NarrativeEnhancementStatus:
    required = NARRATIVE_ENHANCEMENT_REQUIREMENTS.get(skill_id)
    if required is None:
        return NarrativeEnhancementStatus(
            skill_id=skill_id,
            status="unknown",
            reason="unknown_narrative_enhancement",
        )
    if pack is None:
        return NarrativeEnhancementStatus(
            skill_id=skill_id,
            status="unavailable",
            reason="skill_pack_missing",
        )

    installed = {
        str(module.module_id).strip()
        for module in pack.modules
        if str(module.module_id).strip() and str(module.module_id).strip() != "root"
    }
    missing = tuple(sorted(required - installed))
    if missing:
        return NarrativeEnhancementStatus(
            skill_id=skill_id,
            status="incomplete",
            reason="missing_required_modules",
            missing_module_ids=missing,
        )
    return NarrativeEnhancementStatus(
        skill_id=skill_id,
        status="available",
        reason="",
    )


__all__ = [
    "COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_IDS",
    "COMMERCIAL_SHUANGWEN_SKILL_ID",
    "NARRATIVE_ENHANCEMENT_REQUIREMENTS",
    "NarrativeEnhancementStatus",
    "inspect_narrative_enhancement",
]
