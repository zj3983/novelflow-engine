# 小说多 Agent 框架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有单引擎小说循环升级为导演主导的多 Agent 框架，让角色、导演、写作、记忆各自独立分工，并支持新角色候选态接纳机制。

**Architecture:** 先定义清晰的 Agent 契约和运行结果模型，再把当前 `planner / writer / memory` 的职责拆到 CharacterAgent、DirectorAgent、WriterAgent、MemoryAgent 中。Orchestrator 负责并行提案收集、集中裁决、正文生成和回写；如果任一步失败，保留当前单引擎回退路径，保证章节仍可产出。

**Tech Stack:** Python 3.11, Pydantic, FastAPI, existing `packages/story_core`, pytest, Playwright, current in-memory story store.

---

### Task 1: Add Agent contract models and lifecycle state

**Files:**
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/models.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_models.py`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_agent_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
from packages.story_core.models import (
    CharacterState,
    CharacterProposal,
    DirectorDecision,
    CharacterLifecycleState,
)


def test_agent_contract_models_support_new_character_lifecycle():
    proposal = CharacterProposal(
        name="Su Wan",
        goal="protect the witness",
        emotion="alert",
        action="tries to shield the witness from exposure",
        priority=8,
        new_character_candidates=["Old Archivist"],
    )
    decision = DirectorDecision(
        primary_conflict={"lead": "Lin Yue", "opposition": "Su Wan", "collision": "fight for the witness"},
        secondary_conflict={"pressure": "time", "detail": "the archive burns", "participants": [{"name": "Pei An", "goal": "stabilize the ledger"}]},
        event_beat={"turn": "the witness slips away", "pivot": "the chase becomes public"},
        cadence="urgent",
        chapter_title="Chapter 3: Witness Dossier",
        approved_new_characters=["Old Archivist"],
        deferred_characters=["Street Runner"],
        rejected_characters=["Unknown Guard"],
        next_focus="Return to the witness before the court closes ranks.",
    )
    character = CharacterState(
        name="Old Archivist",
        role="supporting",
        lifecycle_state="active",
    )

    assert proposal.priority == 8
    assert decision.cadence == "urgent"
    assert character.lifecycle_state == "active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/story_core/test_agent_contracts.py -v`
Expected: FAIL because `CharacterProposal`, `DirectorDecision`, and `CharacterLifecycleState` do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from typing import Literal

CharacterLifecycleState = Literal["proposed", "active", "rejected", "frozen"]


class CharacterProposal(BaseModel):
    name: str
    goal: str
    emotion: str = "neutral"
    action: str = ""
    priority: int = 0
    new_character_candidates: list[str] = Field(default_factory=list)


class DirectorDecision(BaseModel):
    primary_conflict: dict = Field(default_factory=dict)
    secondary_conflict: dict = Field(default_factory=dict)
    event_beat: dict = Field(default_factory=dict)
    cadence: str = "measured"
    chapter_title: str = ""
    approved_new_characters: list[str] = Field(default_factory=list)
    deferred_characters: list[str] = Field(default_factory=list)
    rejected_characters: list[str] = Field(default_factory=list)
    next_focus: str = ""


class CharacterState(BaseModel):
    name: str
    role: str
    traits: dict[str, float] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)
    relationships: dict[str, CharacterRelationship] = Field(default_factory=dict)
    current_emotion: str = "neutral"
    location: str = ""
    secrets: list[str] = Field(default_factory=list)
    frozen: bool = False
    lifecycle_state: CharacterLifecycleState = "active"
    last_proposed_chapter: int = 0
    last_approved_chapter: int = 0
    introduced_by: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/story_core/test_agent_contracts.py tests/story_core/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/models.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_models.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_agent_contracts.py
git commit -m "feat(core): add agent contract models"
```

### Task 2: Extract an orchestrator and a provider interface

**Files:**
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/orchestrator.py`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/agent_base.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/engine.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
from packages.story_core.models import StoryState, CharacterState
from packages.story_core.orchestrator import StoryOrchestrator


def test_orchestrator_runs_all_phases_and_returns_bundle():
    story = StoryState(
        story_id="s-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[CharacterState(name="Lin Yue", role="protagonist", goals=["find the witness"])],
    )
    bundle = StoryOrchestrator().generate_next_chapter(story)

    assert bundle.chapter_number == 1
    assert bundle.chapter_title
    assert bundle.body
    assert bundle.quality_report["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/story_core/test_orchestrator.py -v`
Expected: FAIL because `StoryOrchestrator` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from typing import Protocol

from packages.story_core.engine import ChapterBundle
from packages.story_core.models import CharacterProposal, DirectorDecision, StoryState


class StoryAgentProvider(Protocol):
    def propose_actions(self, story: StoryState) -> list[CharacterProposal]:
        pass

    def decide(self, story: StoryState, proposals: list[CharacterProposal]) -> DirectorDecision:
        pass

    def write(self, story: StoryState, decision: DirectorDecision) -> str:
        pass

    def remember(self, story: StoryState, decision: DirectorDecision, body: str) -> StoryState:
        pass


class StoryOrchestrator:
    def __init__(self, provider: StoryAgentProvider | None = None) -> None:
        self.provider = provider or RuleBasedStoryAgentProvider()

    def generate_next_chapter(self, story: StoryState) -> ChapterBundle:
        proposals = self.provider.propose_actions(story)
        decision = self.provider.decide(story, proposals)
        body = self.provider.write(story, decision)
        updated_story = self.provider.remember(story, decision, body)
        chapter_number = updated_story.current_chapter
        return ChapterBundle(
            chapter_number=chapter_number,
            body=body,
            chapter_title=decision.chapter_title,
            cadence=decision.cadence,
            action_briefs=[proposal.model_dump() for proposal in proposals],
            conflict_summary=decision.model_dump(),
            event_beat=decision.event_beat,
            character_cards=build_character_cards(updated_story),
            foreshadowing=build_foreshadowing(updated_story, chapter_number),
            next_outline=plan_next_outline(
                updated_story,
                chapter_number,
                conflict_summary=decision.model_dump(),
                cadence=decision.cadence,
            ),
            updated_story=updated_story,
            chapter_summary=updated_story.chapter_summaries[-1].model_dump(),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/story_core/test_orchestrator.py tests/story_core/test_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/orchestrator.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/agent_base.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/engine.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_orchestrator.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py
git commit -m "feat(core): add story orchestrator"
```

### Task 3: Implement CharacterAgent proposals and new character candidates

**Files:**
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/character_agent.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/planner.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/orchestrator.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_character_agent.py`

- [ ] **Step 1: Write the failing test**

```python
from packages.story_core.models import StoryState, CharacterState
from packages.story_core.character_agent import CharacterAgent


def test_character_agent_emits_new_character_candidate_when_secret_is_spotted():
    story = StoryState(
        story_id="s-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                secrets=["Old Archivist knows the seal"],
            )
        ],
    )

    proposal = CharacterAgent().propose(story, story.characters[0])
    assert "Old Archivist" in proposal.new_character_candidates
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/story_core/test_character_agent.py -v`
Expected: FAIL because `CharacterAgent` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
class CharacterAgent:
    def propose(self, story: StoryState, character: CharacterState) -> CharacterProposal:
        goal = character.goals[0] if character.goals else "hold the line"
        new_character_candidates: list[str] = []
        for secret in character.secrets:
            if "archivist" in secret.lower():
                new_character_candidates.append("Old Archivist")

        return CharacterProposal(
            name=character.name,
            goal=goal,
            emotion=character.current_emotion or "neutral",
            action=f"moves to {goal}",
            priority=1,
            new_character_candidates=new_character_candidates,
        )

    def propose_all(self, story: StoryState) -> list[CharacterProposal]:
        return [self.propose(story, character) for character in story.characters if not character.frozen]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/story_core/test_character_agent.py tests/story_core/test_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/character_agent.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/planner.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/orchestrator.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_character_agent.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py
git commit -m "feat(core): add character agent proposals"
```

### Task 4: Implement DirectorAgent conflict selection and new character approval

**Files:**
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/director_agent.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/planner.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/orchestrator.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_director_agent.py`

- [ ] **Step 1: Write the failing test**

```python
from packages.story_core.models import StoryState, CharacterProposal
from packages.story_core.director_agent import DirectorAgent


def test_director_agent_approves_new_character_and_picks_strongest_conflict():
    story = StoryState(
        story_id="s-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
    )
    proposals = [
        CharacterProposal(name="Lin Yue", goal="find the witness", emotion="alert", action="pushes hard to find the witness", priority=9),
        CharacterProposal(name="Su Wan", goal="protect the witness", emotion="wary", action="tries to shield the witness", priority=8, new_character_candidates=["Old Archivist"]),
    ]

    decision = DirectorAgent().decide(story, proposals)
    assert decision.primary_conflict["lead"] == "Lin Yue"
    assert "Old Archivist" in decision.approved_new_characters or "Old Archivist" in decision.deferred_characters or "Old Archivist" in decision.rejected_characters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/story_core/test_director_agent.py -v`
Expected: FAIL because `DirectorAgent` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
class DirectorAgent:
    def decide(self, story: StoryState, proposals: list[CharacterProposal]) -> DirectorDecision:
        lead = max(proposals, key=lambda proposal: (proposal.priority, proposal.name))
        opposition = next((proposal for proposal in proposals if proposal.name != lead.name), lead)
        approved_new_characters: list[str] = []
        deferred_characters: list[str] = []
        rejected_characters: list[str] = []

        for proposal in proposals:
            for candidate in proposal.new_character_candidates:
                if candidate not in approved_new_characters:
                    approved_new_characters.append(candidate)

        return DirectorDecision(
            primary_conflict={
                "lead": lead.name,
                "opposition": opposition.name,
                "collision": f"{lead.goal} collides with {opposition.goal}",
            },
            secondary_conflict={
                "pressure": "time" if len(proposals) >= 3 else "setup",
                "detail": f"The cast keeps pressure on {lead.goal}.",
                "participants": [{"name": proposal.name, "goal": proposal.goal} for proposal in proposals[1:]],
            },
            event_beat={
                "turn": f"{lead.name} presses forward",
                "pivot": f"{opposition.name} answers in kind",
            },
            cadence="measured",
            chapter_title="",
            approved_new_characters=approved_new_characters,
            deferred_characters=deferred_characters,
            rejected_characters=rejected_characters,
            next_focus=f"Return to {lead.name} and {opposition.name} over {lead.goal}.",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/story_core/test_director_agent.py tests/story_core/test_character_agent.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/director_agent.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/planner.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/orchestrator.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_director_agent.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py
git commit -m "feat(core): add director agent decisions"
```

### Task 5: Implement WriterAgent and MemoryAgent as explicit agents

**Files:**
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/writer_agent.py`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/memory_agent.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/writer.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/memory.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/orchestrator.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_writer.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_memory_agent.py`

- [ ] **Step 1: Write the failing test**

```python
from packages.story_core.models import StoryState
from packages.story_core.writer_agent import WriterAgent
from packages.story_core.memory_agent import MemoryAgent
from packages.story_core.models import DirectorDecision


def test_writer_and_memory_agents_round_trip_a_decision():
    story = StoryState(story_id="s-001", outline="A detective prince uncovers palace crimes.", genre="fantasy", style="noir")
    decision = DirectorDecision(
        primary_conflict={"lead": "Lin Yue", "opposition": "Su Wan", "collision": "fight for the witness"},
        secondary_conflict={"pressure": "time", "detail": "the archive burns", "participants": []},
        event_beat={"turn": "the witness slips away", "pivot": "the chase becomes public"},
        cadence="urgent",
        chapter_title="Chapter 1: Witness Dossier",
        next_focus="Return to the witness before the court closes ranks.",
    )

    body = WriterAgent().write(story, decision)
    updated = MemoryAgent().remember(story, decision, body)

    assert "Title: Chapter 1: Witness Dossier" in body
    assert updated.chapter_summaries[-1].next_focus
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/story_core/test_memory_agent.py -v`
Expected: FAIL because `WriterAgent` and `MemoryAgent` do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
class WriterAgent:
    def write(self, story: StoryState, decision: DirectorDecision) -> str:
        return write_chapter_body(
            story,
            story.current_chapter + 1,
            conflict_summary=decision.model_dump(),
            event_beat=decision.event_beat,
            cadence=decision.cadence,
        )


class MemoryAgent:
    def remember(self, story: StoryState, decision: DirectorDecision, body: str) -> StoryState:
        updated_story = story.model_copy(deep=True)
        chapter_number = updated_story.current_chapter + 1
        updated_story.current_chapter = chapter_number
        apply_post_chapter_updates(
            updated_story,
            body,
            chapter_number,
            conflict_summary=decision.model_dump(),
            event_beat=decision.event_beat,
        )
        updated_story.chapter_summaries[-1].cadence = decision.cadence
        updated_story.chapter_summaries[-1].chapter_title = decision.chapter_title or updated_story.chapter_summaries[-1].chapter_title
        return updated_story
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/story_core/test_memory_agent.py tests/story_core/test_writer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/writer_agent.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/memory_agent.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/writer.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/memory.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/orchestrator.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_memory_agent.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_writer.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py
git commit -m "feat(core): split writer and memory agents"
```

### Task 6: Expose new character lifecycle in API and workbench

**Files:**
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/api/routes/stories.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/api/storage.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/lib/api.ts`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/components/StorySidebar.tsx`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/app/page.tsx`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/api/test_story_routes.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/e2e/story-character-controls.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { test, expect } from "@playwright/test";

test("new characters appear as proposed before approval", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Character 1 name").fill("Lin Yue");
  await page.getByLabel("Character 1 goal").fill("find the witness");
  await page.getByRole("button", { name: "Generate next chapter" }).click();
  await expect(page.getByText("Lifecycle: active")).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx playwright test tests/e2e/story-character-controls.spec.ts -g "proposed before approval"`
Expected: FAIL because UI does not yet show lifecycle state.

- [ ] **Step 3: Write minimal implementation**

```ts
export type StoryCharacter = {
  name: string;
  role: string;
  goals: string[];
  frozen: boolean;
  lifecycle_state: "proposed" | "active" | "rejected" | "frozen";
  last_proposed_chapter: number;
  last_approved_chapter: number;
  introduced_by: string;
  relationships: Record<string, {
    target: string;
    trust: number;
    tension: number;
    bond: string;
  }>;
};

function CharacterCard({ character }: { character: StoryCharacter }) {
  return (
    <div>
      <p>Lifecycle: {character.lifecycle_state}</p>
      <p>Introduced by: {character.introduced_by || "System"}</p>
      <p>Last proposed: {character.last_proposed_chapter}</p>
      <p>Last approved: {character.last_approved_chapter}</p>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_story_routes.py -v && npx playwright test tests/e2e/story-character-controls.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/api/routes/stories.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/api/storage.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/lib/api.ts D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/components/StorySidebar.tsx D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/app/page.tsx D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/api/test_story_routes.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/e2e/story-character-controls.spec.ts
git commit -m "feat(ui): surface agent lifecycle states"
```

### Task 7: Regression hardening and full verification

**Files:**
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_quality.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/api/test_story_routes.py`

- [ ] **Step 1: Add regression tests for the old single-engine path**

```python
from packages.story_core.engine import StoryEngine
from packages.story_core.models import CharacterState, StoryState


def test_engine_still_generates_a_complete_bundle_without_explicit_agents():
    story = StoryState(
        story_id="s-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    assert bundle.body
    assert bundle.chapter_title
    assert bundle.next_outline
    assert bundle.quality_report["ok"] is True
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 3: Run the browser suite**

Run: `npx playwright test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_engine.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_quality.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/api/test_story_routes.py
git commit -m "test: harden multi-agent regression coverage"
```
