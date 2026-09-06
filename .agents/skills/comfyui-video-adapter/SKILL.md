---
name: comfyui-video-adapter
description: Adapts Hell Grind cinematic prompts (Cinedance, Acting, Lira) for ComfyUI AI video workflows including Wan2.1, HunyuanVideo, LTX-Video, CogVideoX, FLUX+AnimateDiff. Guides text prompt node mapping, I2V first-frame setup, and JSON/node parameters.
---

# ComfyUI AI Video Adapter Skill

This skill translates Hell Grind cinematic Prompt Director specifications into ComfyUI workflow nodes and text formats.

## 1. ComfyUI Model Mapping

| Hell Grind Conceptual Component | ComfyUI Equivalent Nodes & Models |
| :--- | :--- |
| **Cinedance Camera & Physics Prompt** | `CLIP Text Encode (Positive)` for Wan2.1 T2V / HunyuanVideo / LTX-Video |
| **First-Frame Occupancy Lock (I2V)** | `Load Image` (Frame 0 reference) + `Wan2.1 Image-to-Video` / `HunyuanVideo I2V` |
| **Negative Constraints Lock** | `CLIP Text Encode (Negative)` |
| **Soul ID / Character Reference** | `IPAdapter` / `PuLID` / `InstantID` / `FLUX Redux` nodes |
| **Optics & Resolution Control** | `Empty Latent Video` (Width, Height, Frame Count, FPS) + `Sampler` (Steps, CFG) |

## 2. Text Prompt Structuring for ComfyUI Nodes

### Positive Prompt Node Format (T2V)
When wiring into `CLIP Text Encode (Positive)` for video models (Wan2.1 / HunyuanVideo / LTX-Video):

```text
[SCENE SUMMARY & SUBJECT]: High-budget cinematic film shot. @HERO1 (broad-shouldered wounded man in blood-streaked grey hoodie) stands within 1 meter of a burned-out car in heavy rain.
[SPATIAL & EYE LINE]: First frame already contains @HERO1. He faces camera-right, eyes locked on screen-left.
[OPTICS & CAMERA]: 47° diagonal field of view, standard normal lens, camera 3m away at eye level, subtle handheld operator breath sway.
[ACTION & TIMING]: 0-3s: He raises a dented steel pipe with his left hand. 3-6s: He holds the pipe steady, breathing heavily through his nose.
[PHYSICS & LIGHTING]: Heavy rain drops with parabolic physics, wet specular reflections, backlit morning sun from camera-right creating strong rim light along shoulder, face in deep shadow. Kodak Vision3 500T film texture.
```

### Positive Prompt Node Format (I2V / Image-to-Video)
When frame 0 is already loaded into `Load Image` node:

```text
Cinematic video motion: The wounded man slowly raises the dented steel pipe in his left hand, his eyes staying locked on screen-left. Heavy rain pouring, wet specular highlights shifting on the scorched hood. Camera handheld with organic operator weight shift. Backlit rim light, deep facial shadows preserved. Smooth natural momentum, real mass and inertia.
```

### Negative Prompt Node Format
When wiring into `CLIP Text Encode (Negative)`:

```text
empty first frame, character delayed appearance, reverse gaze line, morphing, body turning opposite direction, floating feet, weightless objects, smooth plastic skin, flat studio front lighting, oversaturated colors, jitter, camera distortion, text, watermark, subtitles.
```

## 3. Workflow Best Practices in ComfyUI

1. **CFG Scale & Steps**:
   - Wan2.1 / HunyuanVideo: CFG 5.0 - 6.0, Steps 25-30, Shift 5.0-7.0.
   - LTX-Video: CFG 3.0 - 3.5, Steps 20-25.
2. **Text Encoder Alignment**:
   - Modern video models (Wan2.1 / HunyuanVideo) use **UMT5 / T5-XXL** text encoders which excel at understanding detailed English physical prose, spatial prepositions, and timing descriptions.
   - Do NOT abbreviate physics and spatial blocking into tags — write natural, precise physical English sentences.
