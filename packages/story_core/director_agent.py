from __future__ import annotations

from packages.story_core.models import (
    CharacterProposal,
    DirectorDecision,
    NewCharacterPolicy,
    StoryState,
)
from packages.story_core.planner import build_chapter_title, select_primary_pair


def _character_candidates(
    proposals: list[CharacterProposal],
    policy: NewCharacterPolicy,
) -> tuple[list[str], list[str], list[str]]:
    approved: list[str] = []
    deferred: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()

    for proposal in proposals:
        for candidate in proposal.new_character_candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if policy == "Manual review":
                deferred.append(candidate)
                continue
            if policy == "Auto-approve named candidates":
                approved.append(candidate)
                continue

            # Default: director review keeps a conservative allow-list.
            if candidate == "Old Archivist":
                approved.append(candidate)
            else:
                deferred.append(candidate)

    return approved, deferred, rejected


class DirectorAgent:
    def decide(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> DirectorDecision:
        action_briefs = [proposal.model_dump() for proposal in proposals]
        lead, rival = select_primary_pair(action_briefs)

        primary = conflict_summary.get("primary_conflict", {}).copy()
        secondary = conflict_summary.get("secondary_conflict", {}).copy()
        if lead:
            primary["lead"] = lead.get("name", primary.get("lead", ""))
            if rival:
                primary["opposition"] = rival.get("name", primary.get("opposition", ""))

        approved, deferred, rejected = _character_candidates(
            proposals,
            story.agent_settings.new_character_policy,
        )
        next_focus = story.chapter_summaries[-1].next_focus if story.chapter_summaries else ""
        chapter_title = build_chapter_title(
            story.current_chapter,
            conflict_summary,
            next_focus,
        )
        return DirectorDecision(
            primary_conflict=primary,
            secondary_conflict=secondary,
            event_beat=event_beat,
            cadence=cadence,
            chapter_title=chapter_title,
            approved_new_characters=approved,
            deferred_characters=deferred,
            rejected_characters=rejected,
            next_focus=next_focus,
        )
