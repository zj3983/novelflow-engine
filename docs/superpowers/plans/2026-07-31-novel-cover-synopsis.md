# Novel Cover and Synopsis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent, editable Fanqie-style synopsis generation and single-image novel cover generation to file-project overview pages, with prompt-only fallback when no image provider is configured.

**Architecture:** A focused publishing-assets domain layer builds bounded project context and validates generated synopsis/cover metadata. Separate text, image-provider, and deterministic Pillow-rendering units feed atomic persistence methods on `FileProjectStore`; FastAPI exposes those operations and the Next.js overview renders two independently stateful cards. Text generation uses the existing planner runtime, while image generation has a separately secured OpenAI-compatible runtime configuration.

**Tech Stack:** Python 3.11, Pydantic 2, FastAPI, urllib-based OpenAI-compatible HTTP, Pillow, pytest, Next.js 14, React 18, TypeScript, Playwright.

---

## File Structure

- Create `packages/story_core/publishing_assets.py`: schemas, bounded project context, Fanqie synopsis validation, synopsis generator, and cover-prompt generator.
- Create `packages/story_core/cover_image_provider.py`: independent image runtime value object, OpenAI-compatible `/images/generations` call, Base64 decoding, and response validation.
- Create `packages/story_core/cover_renderer.py`: image normalization, 3:4 crop, Chinese font resolution, title layout, and PNG output.
- Modify `packages/story_core/runtime_config.py`: persist and resolve a separate image-provider configuration.
- Modify `packages/story_core/file_project_store.py`: read/write `publishing_assets`, atomically replace cover files, and expose render paths.
- Keep `packages/story_core/file_project_creation.py` unchanged; its legacy payload contract remains the compatibility baseline.
- Modify `apps/api/routes/file_projects.py`: publishing request models, generation/edit/render/download endpoints, and response serialization.
- Modify `apps/api/routes/stories.py`: mask, restore, reveal, and save the independent image API key.
- Modify `apps/web/lib/api.ts`: publishing/config types and HTTP functions.
- Create `apps/web/components/ws/PublishingAssetsCards.tsx`: independent cover and synopsis card state machines.
- Create `apps/web/components/ws/PublishingAssetsCards.module.css`: responsive dual-card presentation.
- Modify `apps/web/app/projects/[id]/page.tsx`: mount the cards for file projects.
- Create `apps/web/components/config/CoverImageConfigCard.tsx`: separate image-model configuration form.
- Modify `apps/web/components/config/ConfigPageClient.tsx`: render and save the image configuration.
- Modify `pyproject.toml` and `uv.lock`: add Pillow.
- Modify `.env.example` and `docs/configuration.md`: document optional image model and cover font configuration.

### Task 1: Publishing asset schemas and bounded context

**Files:**
- Create: `packages/story_core/publishing_assets.py`
- Create: `tests/story_core/test_publishing_assets.py`

- [ ] **Step 1: Write failing schema and context tests**

```python
from packages.story_core.publishing_assets import FanqieSynopsis, build_publishing_context


def test_fanqie_synopsis_normalizes_unique_tags_and_requires_200_chars():
    body = "陆沉醒来后发现渡船已驶入归墟。" * 20
    synopsis = FanqieSynopsis(tags=["穿越", "成长", "穿越", "无系统", "克系"], body=body, pattern="conflict")
    assert synopsis.tags == ["穿越", "成长", "无系统", "克系"]
    assert 200 <= len(synopsis.body) <= 450


def test_publishing_context_excludes_full_chapter_bodies():
    context = build_publishing_context(
        project={"title": "归墟行舟", "world_summary": "归墟吞没所有失约者。", "character_profiles": [{"name": "陆沉", "role": "protagonist"}]},
        state={"genre": "玄幻", "outline": "寻找靠岸的方法", "history": [{"body": "不应进入提示词" * 2000}]},
        opening_brief={"idea": "亡魂渡船"},
        outline={"overall": {"main_conflict": "活着靠岸"}},
    )
    serialized = context.model_dump_json()
    assert "归墟行舟" in serialized
    assert "不应进入提示词" not in serialized
    assert len(serialized) < 12_000
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_publishing_assets.py -v`

Expected: collection fails because `packages.story_core.publishing_assets` does not exist.

- [ ] **Step 3: Implement the schemas and context builder**

```python
class FanqieSynopsis(BaseModel):
    tags: list[str]
    body: str
    pattern: Literal["conflict", "contrast", "micro_scene"]
    visual_hook: str = ""

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        tags = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        if not 4 <= len(tags) <= 8:
            raise ValueError("synopsis_tags_out_of_range")
        return tags

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        body = value.strip()
        if not 200 <= len(body) <= 450:
            raise ValueError("synopsis_body_out_of_range")
        return body


class PublishingContext(BaseModel):
    title: str
    novel_type: str = ""
    opening_idea: str = ""
    world_summary: str = ""
    protagonists: list[dict[str, str]] = Field(default_factory=list)
    outline_summary: dict[str, object] = Field(default_factory=dict)


def build_publishing_context(*, project: dict, state: dict, opening_brief: dict, outline: dict) -> PublishingContext:
    protagonists = [
        {"name": str(card.get("name") or "")[:80], "role": str(card.get("role") or "")[:80], "goal": str(card.get("goal") or "")[:240]}
        for card in project.get("character_profiles", [])[:8]
        if isinstance(card, dict)
    ]
    return PublishingContext(
        title=str(project.get("title") or "未命名作品")[:120],
        novel_type=str(state.get("genre") or "")[:120],
        opening_idea=str(opening_brief.get("idea") or "")[:1000],
        world_summary=str(project.get("world_summary") or "")[:2000],
        protagonists=protagonists,
        outline_summary=_bounded_outline_summary(outline),
    )
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_publishing_assets.py -v`

Expected: all publishing schema/context tests pass.

- [ ] **Step 5: Commit the domain foundation**

```powershell
git add packages/story_core/publishing_assets.py tests/story_core/test_publishing_assets.py
git commit -m "feat: add publishing asset schemas and context"
```

### Task 2: Fanqie synopsis and cover-prompt text generation

**Files:**
- Modify: `packages/story_core/publishing_assets.py`
- Modify: `tests/story_core/test_publishing_assets.py`

- [ ] **Step 1: Add failing generator tests with injected HTTP**

```python
def test_synopsis_generator_repairs_invalid_result_once():
    valid_body = "陆沉必须替亡魂完成遗愿，才能让渡船继续靠岸。" * 14
    responses = iter([
        {"choices": [{"message": {"content": '{"tags":["玄幻"],"body":"太短","pattern":"conflict"}'}}]},
        {"choices": [{"message": {"content": json.dumps({"tags": ["穿越", "成长", "无系统", "克系"], "body": valid_body, "pattern": "conflict", "visual_hook": "亡魂渡船"}, ensure_ascii=False)}}]},
    ])
    calls = []
    generator = SynopsisGenerator(post_json=lambda base_url, path, payload, api_key, **kwargs: calls.append(payload) or next(responses))
    context = PublishingContext(title="归墟行舟", novel_type="玄幻", opening_idea="亡魂渡船")
    runtime = StageRuntimeSettings(provider="openai", model="planner", api_key="key", base_url="https://text.test/v1")
    result = generator.generate(context, runtime, guidance="突出渡船危机")
    assert result.pattern == "conflict"
    assert len(calls) == 2


def test_cover_prompt_requires_no_text_and_title_safe_area():
    response = {"choices": [{"message": {"content": "孤舟驶入金色深渊；左上留白；无文字、无标志、无水印"}}]}
    generator = CoverPromptGenerator(post_json=lambda *args, **kwargs: response)
    context = PublishingContext(title="归墟行舟", novel_type="玄幻", opening_idea="亡魂渡船")
    runtime = StageRuntimeSettings(provider="openai", model="planner", api_key="key", base_url="https://text.test/v1")
    prompt = generator.generate(context, runtime, visual_hook="亡魂渡船")
    assert "无文字" in prompt
    assert "留白" in prompt
```

- [ ] **Step 2: Verify the generator tests fail**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_publishing_assets.py -k "generator or cover_prompt" -v`

Expected: FAIL because the generator classes are undefined.

- [ ] **Step 3: Implement strict JSON generation and one repair pass**

Implement `SynopsisGenerator.generate(context, runtime, guidance="") -> FanqieSynopsis` using `/chat/completions`, `parse_json_message_content`, and `FanqieSynopsis.model_validate`. On the first validation error, make exactly one repair request containing the validation message and original JSON. Implement `CoverPromptGenerator.generate(context, runtime, visual_hook="", guidance="") -> str`, append the fixed suffix `适合3:4小说封面，书名区域低细节留白，无文字、无字母、无标志、无水印`, and cap the saved prompt at 2000 characters.

```python
class SynopsisGenerator:
    def __init__(self, post_json=post_json_with_retry):
        self._post_json = post_json

    def generate(self, context: PublishingContext, runtime: StageRuntimeSettings, guidance: str = "") -> FanqieSynopsis:
        first = self._request(context, runtime, guidance=guidance)
        try:
            return FanqieSynopsis.model_validate(first)
        except ValidationError as exc:
            repaired = self._repair(first, str(exc), runtime)
            return FanqieSynopsis.model_validate(repaired)


class CoverPromptGenerator:
    def __init__(self, post_json=post_json_with_retry):
        self._post_json = post_json

    def generate(self, context: PublishingContext, runtime: StageRuntimeSettings, visual_hook: str = "", guidance: str = "") -> str:
        generated = self._request(context, runtime, visual_hook=visual_hook, guidance=guidance).strip()
        return f"{generated}；适合3:4小说封面，书名区域低细节留白，无文字、无字母、无标志、无水印"[:2000]
```

- [ ] **Step 4: Verify generation behavior is green**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_publishing_assets.py -v`

Expected: all tests pass and the repair test records exactly two requests.

- [ ] **Step 5: Commit text generation**

```powershell
git add packages/story_core/publishing_assets.py tests/story_core/test_publishing_assets.py
git commit -m "feat: generate Fanqie synopsis and cover prompts"
```

### Task 3: Independent image runtime configuration and provider

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `packages/story_core/runtime_config.py`
- Create: `packages/story_core/cover_image_provider.py`
- Modify: `tests/story_core/test_runtime_config.py`
- Create: `tests/story_core/test_cover_image_provider.py`

- [ ] **Step 1: Add Pillow through the project package manager**

Run: `uv add "pillow>=10.4"`

Expected: `pyproject.toml` and `uv.lock` include Pillow without modifying unrelated dependencies.

- [ ] **Step 2: Write failing configuration and provider tests**

```python
def test_image_runtime_is_independent_and_secret_is_protected(tmp_path):
    path = tmp_path / "runtime.json"
    config = RuntimeConfiguration.model_validate({
        "image": {"enabled": True, "api_key": "image-secret", "base_url": "https://images.test/v1", "model": "image-1"}
    })
    save_runtime_configuration(config, path)
    assert "image-secret" not in path.read_text(encoding="utf-8")
    assert load_runtime_configuration(path).image.model == "image-1"


def test_image_provider_accepts_only_base64_images():
    png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    provider = OpenAICompatibleCoverImageProvider(post_json=lambda *args, **kwargs: {"data": [{"b64_json": png_b64}]})
    image = provider.generate("无字封面", ImageRuntimeSettings(enabled=True, api_key="key", base_url="https://images.test/v1", model="image-1"))
    assert image.mime_type == "image/png"
    assert image.data.startswith(b"\x89PNG")
```

- [ ] **Step 3: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_runtime_config.py tests/story_core/test_cover_image_provider.py -v`

Expected: FAIL because image configuration/provider types do not exist.

- [ ] **Step 4: Add image config and Base64-only provider**

Add `ImageRuntimeConfiguration(enabled=False, api_key="", base_url="", model="")` to `RuntimeConfiguration`, include it in `_configuration_storage_data` and `_configuration_runtime_data`, and expose `resolve_image_runtime()`. Implement provider payload:

```python
class ImageRuntimeSettings(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    model: str = ""


payload = {"model": runtime.model, "prompt": prompt, "n": 1, "response_format": "b64_json"}
response = self._post_json(runtime.base_url, "/images/generations", payload, runtime.api_key, config=RetryConfig(timeout=180))
item = (response.get("data") or [{}])[0]
if item.get("url") and not item.get("b64_json"):
    raise CoverImageError("unsupported_image_response")
return validate_image_bytes(base64.b64decode(item["b64_json"], validate=True))
```

Map HTTP 401/403 to `image_provider_unauthorized`, timeouts to `image_generation_timeout`, and malformed data to `invalid_image_payload`. Enforce supported MIME, 20 MB encoded bytes, and 40 megapixels.

- [ ] **Step 5: Verify config/provider tests pass**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_runtime_config.py tests/story_core/test_cover_image_provider.py -v`

Expected: all tests pass; URL-only responses are rejected.

- [ ] **Step 6: Commit image runtime and provider**

```powershell
git add pyproject.toml uv.lock packages/story_core/runtime_config.py packages/story_core/cover_image_provider.py tests/story_core/test_runtime_config.py tests/story_core/test_cover_image_provider.py
git commit -m "feat: add independent cover image provider"
```

### Task 4: Deterministic 3:4 cover renderer

**Files:**
- Create: `packages/story_core/cover_renderer.py`
- Create: `tests/story_core/test_cover_renderer.py`

- [ ] **Step 1: Write failing crop, title, and font tests**

```python
def test_render_cover_outputs_768_by_1024_png(tmp_path, chinese_font_path):
    source = io.BytesIO()
    Image.new("RGB", (1200, 900), "navy").save(source, format="JPEG")
    rendered = render_cover(source.getvalue(), "归墟行舟", font_path=chinese_font_path)
    image = Image.open(io.BytesIO(rendered))
    assert image.size == (768, 1024)
    assert image.format == "PNG"


def test_missing_chinese_font_is_explicit(monkeypatch):
    monkeypatch.delenv("NOVEL_COVER_FONT_PATH", raising=False)
    monkeypatch.setattr("packages.story_core.cover_renderer.SYSTEM_FONT_CANDIDATES", ())
    with pytest.raises(CoverRenderError, match="cover_font_unavailable"):
        source = io.BytesIO()
        Image.new("RGB", (768, 1024), "navy").save(source, format="PNG")
        render_cover(source.getvalue(), "归墟行舟")
```

Define `chinese_font_path` in the same test file by choosing the first existing entry from `SYSTEM_FONT_CANDIDATES`; call `pytest.skip("Chinese test font unavailable")` when the test host has none. The missing-font test remains mandatory on every host.

- [ ] **Step 2: Verify renderer tests fail**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_cover_renderer.py -v`

Expected: collection fails because `cover_renderer` does not exist.

- [ ] **Step 3: Implement crop and title layout**

Implement `render_cover(base_bytes: bytes, title: str, font_path: str | Path | None = None) -> bytes`. Use `ImageOps.fit(source.convert("RGB"), (768, 1024), method=Image.Resampling.LANCZOS)`, vertical glyph placement for 2–6 Chinese characters, wrapped horizontal lines for longer titles, a two-pixel stroke, a soft shadow layer, and PNG output through `BytesIO`. Resolve `NOVEL_COVER_FONT_PATH` before Windows and Noto/Source Han candidates, and verify the selected font can render every non-whitespace title character.

```python
def render_cover(base_bytes: bytes, title: str, font_path: str | Path | None = None) -> bytes:
    with Image.open(io.BytesIO(base_bytes)) as source:
        canvas = ImageOps.fit(source.convert("RGB"), (768, 1024), method=Image.Resampling.LANCZOS)
    resolved_font = resolve_cover_font(title, explicit_path=font_path)
    draw_title(canvas, title.strip(), resolved_font)
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
```

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_cover_renderer.py -v`

Expected: crop, short-title, long-title, and missing-font tests pass.

```powershell
git add packages/story_core/cover_renderer.py tests/story_core/test_cover_renderer.py
git commit -m "feat: render titled novel covers"
```

### Task 5: Atomic file-project publishing persistence

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Create: `tests/story_core/test_file_project_publishing_assets.py`

- [ ] **Step 1: Write failing persistence tests**

```python
def test_legacy_project_reads_empty_publishing_assets(file_project_root):
    store = FileProjectStore(file_project_root)
    assert store.publishing_assets() == {"schema_version": "publishing-assets/v1", "synopsis": None, "cover": None}


def test_cover_files_and_metadata_replace_atomically(file_project_root, monkeypatch):
    store = FileProjectStore(file_project_root)
    store.save_cover(prompt="无字孤舟", base_image=sample_png_bytes(), rendered_image=sample_png_bytes(), model="image-1")
    old = store.cover_path.read_bytes()
    monkeypatch.setattr(store, "_replace_asset", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(ValueError, match="publishing_asset_write_failed"):
        store.save_cover(prompt="新提示词", base_image=sample_png_bytes(color="red"), rendered_image=sample_png_bytes(color="red"), model="image-1")
    assert store.cover_path.read_bytes() == old
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_file_project_publishing_assets.py -v`

Expected: FAIL because publishing persistence methods do not exist.

- [ ] **Step 3: Implement store methods**

Add `publishing_assets()`, `save_synopsis()`, `save_cover_prompt()`, `save_cover()`, `rendered_cover_path`, and `cover_base_path`. Save the title used by the renderer as `cover.rendered_title`. Normalize missing assets to the v1 empty response and preserve `publishing_assets` through every `update_project` path. For the two-file cover transaction, write and `fsync` both temporary assets first, copy existing targets to sibling rollback files, replace both targets, and restore both rollback files if either replacement or metadata write fails. Remove rollback files only after `.webnovel/project.json` and `.story-system/MASTER_SETTING.json` are both updated successfully.

The exact public signatures are `publishing_assets(self) -> dict[str, Any]`, `save_synopsis(self, synopsis: dict[str, Any]) -> dict[str, Any]`, `save_cover_prompt(self, prompt: str) -> dict[str, Any]`, and `save_cover(self, *, prompt: str, base_image: bytes, rendered_image: bytes, model: str) -> dict[str, Any]`. `cover_base_path` returns `.webnovel/assets/cover-base.png`; `rendered_cover_path` returns `.webnovel/assets/cover.png`.

- [ ] **Step 4: Verify store and legacy creation tests**

Run: `.venv\Scripts\python.exe -m pytest tests/story_core/test_file_project_publishing_assets.py tests/story_core/test_file_project_creation.py tests/story_core/test_file_project_store.py -v`

Expected: all tests pass and legacy project payload equality remains unchanged.

- [ ] **Step 5: Commit persistence**

```powershell
git add packages/story_core/file_project_store.py tests/story_core/test_file_project_publishing_assets.py
git commit -m "feat: persist file project publishing assets"
```

### Task 6: Publishing APIs and secure image configuration responses

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `apps/api/routes/stories.py`
- Create: `tests/api/test_publishing_asset_routes.py`
- Modify: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing route tests**

```python
def test_generate_cover_returns_prompt_ready_without_image_provider(client, file_project):
    response = client.post(f"/file-projects/{file_project}/publishing/cover", json={"guidance": "突出孤舟"})
    assert response.status_code == 200
    assert response.json()["status"] == "prompt_ready"
    assert response.json()["reason"] == "image_provider_not_configured"


def test_download_cover_sets_attachment_header(client, file_project_with_cover):
    response = client.get(f"/file-projects/{file_project_with_cover}/publishing/cover.png?download=1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert "attachment" in response.headers["content-disposition"]
```

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_publishing_asset_routes.py -v`

Expected: all new endpoints return 404.

- [ ] **Step 3: Implement request models and endpoints**

Add strict request models `PublishingGenerationRequest(guidance: str = Field(max_length=1000))`, `SynopsisUpdateRequest(tags: list[str] = Field(min_length=4, max_length=8), body: str = Field(min_length=1, max_length=2000))`, and `CoverPromptUpdateRequest(prompt: str = Field(min_length=1, max_length=2000))`. Add the five mutation endpoints and PNG GET endpoint from the design. Manual synopsis edits therefore keep non-empty/max-length safety without the generated 200-character minimum. Resolve planner runtime for text, resolve image runtime separately, use injected module-level generators/providers for route tests, return `prompt_ready` on missing image config, and use `FileResponse` with ETag and optional attachment filename.

Use handler names `generate_file_project_synopsis`, `update_file_project_synopsis`, `generate_file_project_cover`, `update_file_project_cover_prompt`, and `render_file_project_cover_title`, each returning a typed JSON dictionary and delegating persistence to `FileProjectStore`.

Extend `_project_payload(store)` with `"publishing_assets": store.publishing_assets()`.

- [ ] **Step 4: Mask and restore image secrets**

Extend `_serialize_runtime_settings` and `_restore_masked_api_keys` for `configuration.image.api_key`. Extend reveal request handling with `provider: "image"` without changing text-provider selection. Add API assertions that GET/PUT return `********` and never plaintext.

- [ ] **Step 5: Run route and configuration regressions**

Run: `.venv\Scripts\python.exe -m pytest tests/api/test_publishing_asset_routes.py tests/api/test_story_routes.py tests/api/test_file_project_creation_routes.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit APIs**

```powershell
git add apps/api/routes/file_projects.py apps/api/routes/stories.py tests/api/test_publishing_asset_routes.py tests/api/test_story_routes.py
git commit -m "feat: expose publishing asset APIs"
```

### Task 7: Web API contract and image configuration card

**Files:**
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/components/config/CoverImageConfigCard.tsx`
- Modify: `apps/web/components/config/ConfigPageClient.tsx`
- Modify: `apps/web/tests/config-page.spec.ts`

- [ ] **Step 1: Add a failing Playwright configuration test**

Add `image: { enabled: true, api_key: "********", base_url: "https://images.test/v1", model: "image-1" }` to the fixture, then assert the separate card edits `封面图片模型`, reveals the image key through `{ provider: "image" }`, and preserves text provider values when saving.

- [ ] **Step 2: Verify the configuration test fails**

Run from `apps/web`: `npm run test:e2e -- config-page.spec.ts`

Expected: FAIL because the image configuration controls are absent.

- [ ] **Step 3: Add web types, normalization, and API functions**

Extend `RuntimeSettings` with:

```ts
image: { enabled: boolean; api_key: string; base_url: string; model: string };
```

Update defaults and `normalizeRuntimeSettings`. Generalize `revealRuntimeApiKey` to accept `RuntimeProvider | "image"`. Add exact publishing response types for `SynopsisAsset`, `CoverAsset`, and `PublishingAssets` so later components do not use `Record<string, unknown>`.

- [ ] **Step 4: Implement and mount `CoverImageConfigCard`**

Render enabled toggle, Base URL, model, password input, reveal/hide button, and stored-key badge. Use immutable updates of `settings.image`; do not route image settings through `settings.providers`. Mount it between `GlobalApiConfigCard` and `RuntimeStrategyCard`.

- [ ] **Step 5: Verify TypeScript and Playwright**

Run from `apps/web`: `npx tsc --noEmit`

Run from `apps/web`: `npm run test:e2e -- config-page.spec.ts`

Expected: TypeScript exits 0 and configuration tests pass.

- [ ] **Step 6: Commit web configuration**

```powershell
git add apps/web/lib/api.ts apps/web/components/config/CoverImageConfigCard.tsx apps/web/components/config/ConfigPageClient.tsx apps/web/tests/config-page.spec.ts
git commit -m "feat: configure cover image models"
```

### Task 8: Independent cover and synopsis cards

**Files:**
- Create: `apps/web/components/ws/PublishingAssetsCards.tsx`
- Create: `apps/web/components/ws/PublishingAssetsCards.module.css`
- Modify: `apps/web/app/projects/[id]/page.tsx`
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/tests/publishing-assets.spec.ts`

- [ ] **Step 1: Write failing dual-card browser tests**

Cover these behaviors in one mocked file project: both empty cards render; clicking `生成简介` sends only the synopsis request; cover generation locks only the cover card; `prompt_ready` exposes copy/configure actions; editing saves without generation; a failed re-generation keeps the previous content visible; `下载` requests `cover.png?download=1`.

- [ ] **Step 2: Verify RED**

Run from `apps/web`: `npm run test:e2e -- publishing-assets.spec.ts`

Expected: FAIL because the cards are absent.

- [ ] **Step 3: Add publishing API functions**

Implement `generateSynopsis`, `updateSynopsis`, `generateCover`, `updateCoverPrompt`, `renderCoverTitle`, and `coverImageUrl`. Use 180-second generation timeouts, 30-second save timeouts, encoded file project IDs, and structured error messages from `tryFetchJson`.

```ts
export async function generateSynopsis(projectId: string, guidance = ""): Promise<SynopsisAsset>;
export async function updateSynopsis(projectId: string, payload: Pick<SynopsisAsset, "tags" | "body">): Promise<SynopsisAsset>;
export async function generateCover(projectId: string, guidance = ""): Promise<CoverGenerationResponse>;
export async function updateCoverPrompt(projectId: string, prompt: string): Promise<CoverAsset>;
export async function renderCoverTitle(projectId: string): Promise<CoverAsset>;
export function coverImageUrl(projectId: string, version: string, download = false): string;
```

- [ ] **Step 4: Implement the independent card state machines**

`PublishingAssetsCards` receives `projectId`, `title`, `assets`, and `onChanged`. Maintain separate cover/synopsis status, guidance, edit drafts, and errors. Keep rendered old values during requests. When `assets.cover.rendered_title !== title`, show “书名已变化，重新排版” without calling the image model. On success call `onChanged()` so `ProjectWorkspaceProvider.refresh({ invalidateChapter: false })` reloads project metadata without refetching chapter bodies.

```ts
type PublishingAssetsCardsProps = {
  projectId: string;
  title: string;
  assets: PublishingAssets;
  onChanged: () => void;
};

type CardRequestState = "idle" | "generating" | "saving" | "error";
```

- [ ] **Step 5: Mount and style the cards**

Render only for `project.storage_source === "file"` or `project.project_id.startsWith("file:")`. Place the cards after the status section and before chapters. Use a two-column grid above 900 px, one column below, a 3:4 image frame, keyboard-accessible dialogs/forms, and existing `ws-btn` visual tokens.

- [ ] **Step 6: Verify browser, type, and existing overview regressions**

Run from `apps/web`: `npm run test:e2e -- publishing-assets.spec.ts story-workbench.spec.ts`

Run from `apps/web`: `npx tsc --noEmit`

Expected: all selected tests pass and TypeScript exits 0.

- [ ] **Step 7: Commit the overview UI**

```powershell
git add apps/web/components/ws/PublishingAssetsCards.tsx apps/web/components/ws/PublishingAssetsCards.module.css apps/web/app/projects/[id]/page.tsx apps/web/lib/api.ts apps/web/tests/publishing-assets.spec.ts
git commit -m "feat: add cover and synopsis workbench cards"
```

### Task 9: Documentation and full verification

**Files:**
- Modify: `.env.example`
- Modify: `docs/configuration.md`

- [ ] **Step 1: Document optional configuration**

Add `NOVEL_COVER_FONT_PATH=` to `.env.example`. Document that image key/base URL/model are normally stored through `/config`, image generation accepts Base64 OpenAI-compatible responses only, prompt-only mode remains available without configuration, and `NOVEL_COVER_FONT_PATH` overrides system font discovery.

```dotenv
# Optional path to a Chinese TrueType/OpenType font used for cover title rendering.
NOVEL_COVER_FONT_PATH=
```

- [ ] **Step 2: Run focused Python suites**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_publishing_assets.py tests/story_core/test_cover_image_provider.py tests/story_core/test_cover_renderer.py tests/story_core/test_file_project_publishing_assets.py tests/story_core/test_runtime_config.py tests/api/test_publishing_asset_routes.py tests/api/test_story_routes.py tests/api/test_file_project_creation_routes.py -v
```

Expected: zero failures.

- [ ] **Step 3: Run the complete Python suite**

Run: `.venv\Scripts\python.exe -m pytest`

Expected: zero failures.

- [ ] **Step 4: Run complete web checks**

Run from `apps/web`:

```powershell
npx tsc --noEmit
npm run test:e2e
npm run build
```

Expected: all Playwright tests pass, TypeScript exits 0, and Next.js build exits 0.

- [ ] **Step 5: Review the final diff against the design**

Run:

```powershell
git diff --check HEAD~9..HEAD
git status --short
```

Confirm the diff contains no API keys, generated cover images, `.superpowers` visual files, runtime config files, or unrelated user changes. Confirm every completion criterion in `docs/superpowers/specs/2026-07-31-novel-cover-synopsis-design.md` maps to a passing automated test.

- [ ] **Step 6: Commit documentation**

```powershell
git add .env.example docs/configuration.md
git commit -m "docs: configure novel cover generation"
```
