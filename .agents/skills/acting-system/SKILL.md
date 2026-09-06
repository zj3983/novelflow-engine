---
name: acting-system
description: Character Performance System for AI Video Generation. Implements dramatic acting principles (Objective, Obstacle, Tactics, Beats, Subtext), physical body biography, eye-life micro-saccades, and ComfyUI/Seedance character motion prompts. Use when defining character acting or performance.
---

# ACTING SYSTEM — Character Performance for AI Video

**Core Axiom: Acting is BEHAVIOR under pressure, not a display of emotion.**

A character wants something (Objective), something interferes (Obstacle/Stakes), and they act to get it (Tactics). Emotion is a byproduct of that struggle.

## The 5 Pillars

1. **Objective**: Verb aimed at the partner right now ("make him confess", "beg for time").
2. **Obstacle & Stakes**: What prevents getting it? What happens if they fail?
3. **Tactics**: Active methods (to press, to charm, to shame, to threaten). Must change when failed.
4. **Beats**: Smallest action unit. Every beat change MUST be visible in behavior (pause, posture shift, gaze shift).
5. **Subtext**: Inner thought leaking through opposite words/actions.

## Key Performance Rules

- **Eye Life (Mandatory)**: Micro-saccades, gaze targeting, controlled blinks, live catchlights. Eyes lead the thought before the head turns.
- **Physical Life**: Center of gravity (high=aggression, low=fatigue), tempo, openness, breath.
- **Business (Doing)**: Characters do physical tasks (fix engine, wipe glass) while talking. **Interrupted Action** (stopping the task) marks major accents.
- **Status & Proxemics**: Distance graph (intimate <0.5m, personal 0.5-1.2m, social 1.2m+). High status = still, quiet, slow. Low status = fidgety, loud.
- **Two-Truths Rule (Magnet Acting)**: At peak performance, character plays TWO truths simultaneously (e.g. apologizes while defending; helps while hating it).

## Profile Structure

```text
CHARACTER MASTER PROFILE:
[Name, Age, physique, posture carrying biography] -> [Inner drive] -> [Vocal profile] -> [Tics with triggers] -> [Named Gait] -> [Transformation mask crack "However, when X..."] -> [Eye Life].

VOICE PROMPT (Audio Field):
"A [age]-year-old [origin]. [Timbre]; [pace]; [emotional shift under pressure]."
```
