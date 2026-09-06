---
name: lira-image-prompt
description: Image Prompt Optimization & Model Routing skill for Soul 2.0, Soul Cinema, ComfyUI FLUX/SDXL, Nano Banana Pro (NBP), Seedream 4.5, and GPT Image 2. Generates character reference sheets, cinematic stills, prop shots, and frame edits. Use when building image prompts or ComfyUI text nodes.
---

# LIRA — Image Prompt Optimization & Model Routing

Master prompt-optimization system for AI image generation and ComfyUI text nodes.

## Model Routing Matrix

| Task | Primary Model / ComfyUI Node | Technique |
| :--- | :--- | :--- |
| Character Sheet / Consistency | Soul 2.0 / FLUX Realism / SDXL Character | 3-panel sheet, Soul ID / IPAdapter, minimal facial anchors |
| Location / Cinematic Still | Soul Cinema / FLUX Cine / Hunyuan T2I | 21:9 framing, 60/30/10 palette split, camera angle, light & texture |
| Prop / Product Sheet | NBP / GPT Image 2 / FLUX Product | Studio framing, neutral background, anti-text rendering |
| Image Editing / Post-processing | Nano Banana Pro / ComfyUI Inpaint | Minimal CHANGE block + Exhaustive PRESERVE EXACTLY block |
| AI Texture Cleanup | Seedream 4.5 / ControlNet Tile | Texture pass (skin, fabric, surface refinement) |

## Anti-Fail Rules

1. **Natural Prose over Keyword Spam**: No "4k, masterpiece, trending". Use concrete technical light, material names, and optics.
2. **Positive Substitution**: No negative prompts in generation text; replace unwanted states with positive desired states (e.g. "clean dry skin" instead of "no acne").
3. **60/30/10 Palette Control**: Specify palette as proportions (e.g. "60% warm ochre, 30% deep charcoal, 10% rust-red").
4. **ComfyUI Inpaint Edit Discipline**: Explicitly specify what to CHANGE and what to PRESERVE EXACTLY.
