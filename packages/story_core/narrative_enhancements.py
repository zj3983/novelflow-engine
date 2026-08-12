from __future__ import annotations

from dataclasses import dataclass

from packages.story_core.skill_packs import SkillPack


COMMERCIAL_SHUANGWEN_SKILL_ID = "commercial-shuangwen"
COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_PURPOSES = {
    "plot-engine": frozenset({"outline"}),
    "chapter-sop": frozenset({"chapter_plan"}),
    "writer-execution": frozenset({"writer"}),
    "review-checklist": frozenset({"reviewer"}),
    "genre-examples": frozenset({"outline", "chapter_plan", "writer"}),
}
COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_IDS = frozenset(
    COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_PURPOSES
)
NARRATIVE_ENHANCEMENT_REQUIREMENTS = {
    COMMERCIAL_SHUANGWEN_SKILL_ID: COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_PURPOSES,
}


@dataclass(frozen=True)
class NarrativeModulePurposeMismatch:
    module_id: str
    required_purposes: tuple[str, ...]
    actual_purposes: tuple[str, ...]
    missing_purposes: tuple[str, ...]
    unexpected_purposes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "module_id": self.module_id,
            "required_purposes": list(self.required_purposes),
            "actual_purposes": list(self.actual_purposes),
            "missing_purposes": list(self.missing_purposes),
            "unexpected_purposes": list(self.unexpected_purposes),
        }


@dataclass(frozen=True)
class NarrativeEnhancementStatus:
    skill_id: str
    status: str
    reason: str
    missing_module_ids: tuple[str, ...] = ()
    purpose_mismatches: tuple[NarrativeModulePurposeMismatch, ...] = ()

    @property
    def available(self) -> bool:
        return self.status == "available"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "missing_module_ids": list(self.missing_module_ids),
            "purpose_mismatches": [
                mismatch.as_dict() for mismatch in self.purpose_mismatches
            ],
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
        str(module.module_id).strip(): module
        for module in pack.modules
        if str(module.module_id).strip() and str(module.module_id).strip() != "root"
    }
    missing = tuple(sorted(set(required) - set(installed)))
    purpose_mismatches: list[NarrativeModulePurposeMismatch] = []
    for module_id, required_purposes in required.items():
        module = installed.get(module_id)
        if module is None:
            continue
        raw_purposes = getattr(module, "purposes", ())
        if isinstance(raw_purposes, str):
            actual_purposes = {
                item.strip() for item in raw_purposes.split(",") if item.strip()
            }
        else:
            actual_purposes = {
                str(item).strip() for item in raw_purposes if str(item).strip()
            }
        missing_purposes = required_purposes - actual_purposes
        unexpected_purposes = actual_purposes - required_purposes
        if missing_purposes or unexpected_purposes:
            purpose_mismatches.append(
                NarrativeModulePurposeMismatch(
                    module_id=module_id,
                    required_purposes=tuple(sorted(required_purposes)),
                    actual_purposes=tuple(sorted(actual_purposes)),
                    missing_purposes=tuple(sorted(missing_purposes)),
                    unexpected_purposes=tuple(sorted(unexpected_purposes)),
                )
            )
    if missing:
        return NarrativeEnhancementStatus(
            skill_id=skill_id,
            status="incomplete",
            reason="missing_required_modules",
            missing_module_ids=missing,
            purpose_mismatches=tuple(purpose_mismatches),
        )
    if purpose_mismatches:
        return NarrativeEnhancementStatus(
            skill_id=skill_id,
            status="incomplete",
            reason="invalid_module_purposes",
            purpose_mismatches=tuple(purpose_mismatches),
        )
    return NarrativeEnhancementStatus(
        skill_id=skill_id,
        status="available",
        reason="",
    )


__all__ = [
    "COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_IDS",
    "COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_PURPOSES",
    "COMMERCIAL_SHUANGWEN_SKILL_ID",
    "NARRATIVE_ENHANCEMENT_REQUIREMENTS",
    "NarrativeEnhancementStatus",
    "NarrativeModulePurposeMismatch",
    "inspect_narrative_enhancement",
]
