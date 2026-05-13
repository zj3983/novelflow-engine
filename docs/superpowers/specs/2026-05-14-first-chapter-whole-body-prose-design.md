# First Chapter Whole-Body Prose Upgrade

## Goal

Improve the first chapter of web-game openings when the system generates a whole chapter body. The change should reduce AI/report voice, avoid checklist prose, and make the opening read more like a concrete Tomato-style webnovel scene.

This design explicitly does not use segmented generation.

## Scope

The first pass will target whole-chapter prompts and whole-chapter writing packets:

- `packages/story_core/orchestrator.py`
- `packages/story_core/writing_packet.py`
- `packages/story_core/writing_taskbook.py`

The world simulation, director planning, review pipeline, and segmented-writing path stay unchanged except for any shared writer-facing taskbook text they already consume.

## Reader-Facing Contract

For chapter 1 of a web-game story, the whole chapter should naturally contain four beats:

1. Real-life pressure: a concrete money, rent, device, or body-detail moment that explains why the protagonist logs in now.
2. Login and character creation: game ID, class choice, level 1 panel, initial weapon or skill, and opening-world texture.
3. Low-level verification: one small fight or test that shows visible cost and feedback through HP/MP, durability, inventory, drops, task progress, and other players' slower baseline.
4. Next-step hook: the protagonist does not cash out; the chapter ends with a specific task, equipment, skill, map, or NPC-service threshold that can pull chapter 2 forward.

The first chapter payoff is "I am one step ahead and can reach the next gate faster", not "I already made money and the world noticed".

## Anti-AI-Voice Rules

The whole-chapter prompt should convert abstract instructions into concrete prose method:

- Do not write backend terms such as boundary, inference, review, scene card, baseline, model, algorithm, variable, or rule being opened.
- Do not explain that something "means" or "proves" a rule. Show it through panel feedback, inventory change, NPC response, price tag, task text, pain, hesitation, or another player's contrast.
- Do not let professional background become report prose. A risk-control/testing background should surface as checking balance, counting copper, watching MP, touching staff durability, pausing before asking price, or refusing to cash out early.
- Every major beat needs visible feedback and a small cost.

## Implementation Shape

Update the whole-chapter `_body_prompt` in `StoryOrchestrator` so its first-chapter web-game method is explicit before guardrails. It should keep the current "OUTPUT CONTRACT: prose only" behavior and continue using the taskbook section.

Update the writing taskbook and writing packet so manual and whole-body flows share the same chapter-1 prose contract:

- Stronger first-chapter global requirements.
- A compact "whole chapter beat map" for chapter 1.
- Clear prohibition against first-chapter cash-out, completed transaction, public channel spread, forum explosion, guild chase, or market-player pursuit.
- Writer-facing examples of concrete replacements for abstract report language.

## Testing

Add focused tests that do not call external models:

- Whole-body prompt for chapter 1 web-game stories includes the four-beat method and says not to use segmented generation.
- Whole-body prompt places prose method before hard guardrails.
- Writing packet exposes the same whole-chapter chapter-1 contract for manual drafting.
- Existing segmented tests should continue to pass, but no new segmented behavior is required.

## Non-Goals

- No new model call.
- No new style-adaptation pass.
- No rewrite of world simulation or director planning.
- No change to historical chapters.
- No automatic commit of generated prose.
