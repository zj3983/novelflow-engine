# 开篇方向重新生成补充要求实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让用户在重新生成开篇方向时填写一次性补充要求，同时保证该文本不进入项目长期状态。

**Architecture:** 前端把可选 guidance 随生成请求发送给文件项目 API；API 严格校验后将它作为内存参数依次传给 FileProjectStore 和 LLMOpeningDirectionGenerator。生成器只把它加入本次模型提示上下文，任何项目 JSON 都不保存该字段。

**Tech Stack:** FastAPI、Pydantic v2、Python/pytest、Next.js 14、TypeScript、Playwright

---

### Task 1: 一次性补充要求后端链路

**Files:**
- Modify: packages/story_core/opening_directions.py
- Modify: packages/story_core/file_project_store.py
- Modify: apps/api/routes/file_projects.py
- Modify: tests/story_core/test_opening_directions.py
- Modify: tests/api/test_file_project_creation_routes.py

- [ ] **Step 1: 写生成器和存储层失败测试**

在 tests/story_core/test_opening_directions.py 增加：

~~~python
def test_generator_adds_one_time_guidance_to_prompt():
    captured = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["payload"] = payload
        return {
            "choices": [
                {"message": {"content": json.dumps({"directions": direction_set()["directions"]})}}
            ]
        }

    generator = LLMOpeningDirectionGenerator(
        post_json=fake_post,
        runtime_resolver=lambda _: OpenAIRuntimeSettings(
            provider="codexcli", base_url="http://runtime.test", codex_command="codex-test"
        ),
        strategy_resolver=lambda: AgentSettings(director_model="direction-test-model"),
    )
    generator.generate(
        OpeningBrief(novel_type_id="urban", idea="原始灵感"),
        guidance="  不要异能，三个方向差异更大  ",
    )

    prompt = json.loads(captured["payload"]["messages"][1]["content"])
    assert prompt["regeneration_guidance"] == "不要异能，三个方向差异更大"
~~~

增加存储层测试：

~~~python
def test_store_passes_guidance_without_persisting_it(tmp_path):
    store = make_opening_store(tmp_path)
    secret = "ONLY_FOR_THIS_REGENERATION"
    calls = []

    class RecordingGenerator:
        def generate(self, brief, *, guidance=""):
            calls.append(guidance)
            return direction_set()

    store.generate_opening_directions(RecordingGenerator(), guidance=f"  {secret}  ")

    assert calls == [secret]
    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in store.root.rglob("*.json")
    )
    assert secret not in persisted
~~~

- [ ] **Step 2: 运行领域测试并确认 RED**

Run:

~~~powershell
python -m pytest -q tests/story_core/test_opening_directions.py -k "guidance"
~~~

Expected: FAIL，因为 generate() 和 generate_opening_directions() 尚不接受 guidance。

- [ ] **Step 3: 实现生成器和存储层的内存参数传递**

在 packages/story_core/opening_directions.py 中增加关键字参数：

~~~python
def generate(self, brief: OpeningBrief, *, guidance: str = "") -> OpeningDirectionSet:
    validated_brief = OpeningBrief.model_validate(brief)
    genre = NOVEL_TYPE_CATALOG.get(validated_brief.novel_type_id)
    if genre is None:
        raise ValueError("invalid_novel_type")
    normalized_guidance = guidance.strip()
    if len(normalized_guidance) > 1000:
        raise ValueError("regeneration_guidance_too_long")

    prompt_context = {
        "genre_label": genre.label,
        "genre_description": genre.description,
        "working_title": validated_brief.working_title,
        "idea": validated_brief.idea,
        "regeneration_guidance": normalized_guidance,
    }
~~~

保留现有 runtime、HTTP、JSON 和输出结构异常的 opening_direction_generation_failed 边界。

在 packages/story_core/file_project_store.py 中只传参，不修改事务 payload：

~~~python
def generate_opening_directions(self, generator: Any, *, guidance: str = "") -> dict[str, Any]:
    existing = self.opening_directions()
    if existing and existing.get("selected_id"):
        raise ValueError("direction_already_selected")
    brief = OpeningBrief.model_validate(self.opening_brief())
    result = generator.generate(brief, guidance=guidance.strip())
    # 后续 project.json 与 opening_directions.json 事务保持原样
~~~

- [ ] **Step 4: 运行领域回归并确认 GREEN**

Run:

~~~powershell
python -m pytest -q tests/story_core/test_opening_directions.py tests/story_core/test_file_project_store.py
~~~

Expected: PASS。

- [ ] **Step 5: 写 API 请求失败测试**

在 tests/api/test_file_project_creation_routes.py 增加：

~~~python
def test_generate_opening_directions_accepts_trimmed_one_time_guidance(
    creation_api, monkeypatch
):
    client, _, _ = creation_api
    project, root = _create_inspiration_project(client)
    calls = []

    class RecordingGenerator:
        def generate(self, brief, *, guidance=""):
            calls.append(guidance)
            return _direction_set()

    monkeypatch.setattr(file_project_routes, "opening_direction_generator", RecordingGenerator())
    secret = "ONLY_FOR_THIS_REQUEST"
    response = client.post(
        f"/file-projects/{project['project_id']}/opening-directions",
        json={"guidance": f"  {secret}  "},
    )

    assert response.status_code == 200
    assert calls == [secret]
    assert secret not in "\n".join(
        path.read_text(encoding="utf-8") for path in root.rglob("*.json")
    )
~~~

另加三个契约断言：无请求体仍能首次生成；guidance 超过 1000 字返回 422；请求包含多余字段返回 422。

- [ ] **Step 6: 运行 API 测试并确认 RED**

Run:

~~~powershell
python -m pytest -q tests/api/test_file_project_creation_routes.py -k "guidance or no_body"
~~~

Expected: guidance 用例 FAIL，因为路由尚未接收请求体。

- [ ] **Step 7: 实现严格且向后兼容的 API 请求模型**

在 apps/api/routes/file_projects.py 增加：

~~~python
class OpeningDirectionGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    guidance: str = Field(default="", max_length=1000)

    @field_validator("guidance", mode="before")
    @classmethod
    def trim_guidance(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value
~~~

更新路由，并兼容旧客户端的无请求体 POST：

~~~python
@router.post("/file-projects/{project_id}/opening-directions")
def generate_opening_directions(
    project_id: str,
    payload: OpeningDirectionGenerationRequest | None = None,
) -> dict[str, Any]:
    try:
        guidance = payload.guidance if payload is not None else ""
        return _store_for(project_id).generate_opening_directions(
            opening_direction_generator,
            guidance=guidance,
        )
    except ValueError as exc:
        status_code = 502 if str(exc) == "opening_direction_generation_failed" else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
~~~

补齐 ConfigDict、Field 和 field_validator import。

- [ ] **Step 8: 运行后端定向回归并提交**

Run:

~~~powershell
python -m pytest -q tests/story_core/test_opening_directions.py tests/story_core/test_file_project_store.py tests/api/test_file_project_creation_routes.py
git diff --check
~~~

Expected: PASS。

Commit:

~~~powershell
git add packages/story_core/opening_directions.py packages/story_core/file_project_store.py apps/api/routes/file_projects.py tests/story_core/test_opening_directions.py tests/api/test_file_project_creation_routes.py
git commit -m "feat: accept one-time opening regeneration guidance"
~~~

### Task 2: 重新生成补充要求页面交互

**Files:**
- Modify: apps/web/lib/api.ts
- Modify: apps/web/app/projects/[id]/setup/page.tsx
- Modify: apps/web/app/globals.css
- Modify: apps/web/tests/story-workbench.spec.ts

- [ ] **Step 1: 写 Playwright 失败测试**

在 apps/web/tests/story-workbench.spec.ts 增加测试：已有三个候选时显示“本次补充要求”，填写后重新生成，请求体等于 { guidance: "不要异能，三个方向差异更大" }，成功后输入框清空。

再增加两个断言：
- 生成返回 502 后输入内容仍保留。
- 首次无候选页面不显示“本次补充要求”。

复用现有 opening setup route mock，不新建第二套 helper。

- [ ] **Step 2: 运行页面测试并确认 RED**

Run:

~~~powershell
cd apps/web
npx playwright test tests/story-workbench.spec.ts -g "opening setup.*guidance"
~~~

Expected: FAIL，因为输入框和请求体尚不存在。

- [ ] **Step 3: 更新前端 API**

在 apps/web/lib/api.ts 中更新：

~~~typescript
export async function generateOpeningDirections(
  projectId: string,
  guidance = "",
): Promise<OpeningSetup> {
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/opening-directions`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ guidance }),
    },
    180000,
  )) as OpeningSetup;
}
~~~

不增加 mock fallback，不捕获 API 错误。

- [ ] **Step 4: 实现页面状态与输入框**

在 setup/page.tsx 增加：

~~~tsx
const [guidance, setGuidance] = useState("");
const showGuidance = directions.length > 0 || errorSource === "generate";
~~~

生成时传值，并只在成功后清空：

~~~tsx
const response = await generateOpeningDirections(projectId, guidance.trim());
if (!isCurrentRequest(requestToken, requestProjectId)) return;
setSetup(response);
setGuidance("");
setSelectedId("");
setPhase(response.directions.length > 0 ? "candidates" : "no-candidates");
~~~

在重新生成操作附近加入：

~~~tsx
{showGuidance ? (
  <label className="ws-opening-guidance">
    <span>本次补充要求</span>
    <textarea
      value={guidance}
      maxLength={1000}
      rows={3}
      disabled={requestPending}
      onChange={(event) => setGuidance(event.target.value)}
      placeholder="例如：不要异能，三个方向差异更大"
    />
  </label>
) : null}
~~~

输入框不是卡片。apps/web/app/globals.css 只补布局、focus 和 width: 100%，移动端不得横向溢出。

- [ ] **Step 5: 运行页面回归和生产构建**

Run:

~~~powershell
cd apps/web
npx playwright test tests/story-workbench.spec.ts -g "opening setup"
npm.cmd run build
~~~

Expected: 所有 opening setup 测试和 Next.js 构建 PASS。

- [ ] **Step 6: 提交页面改动**

~~~powershell
git add apps/web/lib/api.ts apps/web/app/projects/[id]/setup/page.tsx apps/web/app/globals.css apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add opening regeneration guidance input"
~~~

### Task 3: 集成验证与服务更新

**Files:**
- No source changes expected

- [ ] **Step 1: 运行完整后端测试**

Run:

~~~powershell
python -m pytest -q
~~~

Expected: 全部测试 PASS。

- [ ] **Step 2: 运行关键浏览器流程和构建**

Run:

~~~powershell
cd apps/web
npx playwright test tests/story-workbench.spec.ts -g "opening setup|projects page creates"
npm.cmd run build
~~~

Expected: 浏览器流程及生产构建 PASS。

- [ ] **Step 3: 验证补充要求不落盘**

用临时 NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR 创建灵感项目并发送唯一补充文本。检查项目目录下所有 JSON，确认该文本不存在；响应仍返回三个方向。

- [ ] **Step 4: 完成分支合并和服务重启**

按 superpowers:finishing-a-development-branch 流程合并功能分支。重启 127.0.0.1:8000 API 和 localhost:3000 Web，分别验证 HTTP 200，并确认方向页面可加载。

