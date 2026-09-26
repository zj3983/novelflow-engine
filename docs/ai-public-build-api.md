# AI 公共 Build API（public-build/v1）

Codex、MCP 工具或 CLI 可通过 HTTP 读取任务状态、阻断和下一动作，不需要模拟网页。当前服务使用已有的本地可信调用边界；本接口不新增身份认证，也不授予远程访问权限。

所有路径位于 `/file-projects/{project_id}/public-build`。先读取项目，不要自行猜测下一步；所有操作均需重新使用当前返回的 revision。

| 方法 / 子路径 | 返回 / 用途 |
| --- | --- |
| GET 空路径 | graph_revision、任务、readiness、next_actions、最新编排任务摘要 |
| GET `/readiness` | Build 必要节点是否完成、阻断代码、人工确认节点 |
| GET `/next-actions` | 当前允许的动作、任务引用、HTTP 路径和精确 revision 前置条件 |
| GET `/tasks/{task_id}` | 定义、reads / owns / forbidden_writes、状态、依赖 revision、校验代码 |
| GET `/tasks/{task_id}/artifacts/{revision}` | 指定历史产物元数据、validation；不含 payload |
| GET `/capabilities` | 图任务使用的 stage 与 writer 当前绑定的模型/协议、能力三态、来源和有效期 |
| PATCH `/tasks/{task_id}/artifact` | 提交完整任务 payload，必须携带 expected_graph_revision + expected_revision |
| POST `/next` | 执行一个已允许的 Build 任务，必须携带 task_id + expected_graph_revision；返回 job_id |

`ready` 表示 Build 定义的 required_for_readiness 节点完成且没有活动任务或来源冲突；它不是“自动确认章节”许可。`can_continue` 表示存在允许的 Build 动作。尚未初始化的项目返回 initialized=false 和 build_graph_not_initialized，不会通过 GET 初始化图。已有候选会作为 `human_confirmation` 返回候选 ID、章节号、上下文快照引用；不返回正文，且没有自动确认接口。候选确认仍由现有 candidate/confirmation 服务及人工流程负责。任务处于 review_required 时，公共编辑接口拒绝写入，不可用编辑冒充审查通过。

## CLI：只读检查

启动已配置的本地 API 后，用 PowerShell：

```powershell
$projectId = '你的项目ID'
$base = "http://127.0.0.1:8000/file-projects/$projectId/public-build"
$view = Invoke-RestMethod $base
$view.readiness | ConvertTo-Json -Depth 8
$view.next_actions | ConvertTo-Json -Depth 8
Invoke-RestMethod "$base/capabilities" | ConvertTo-Json -Depth 8
```

这里不会运行模型。端口应与现有 API 服务一致；独立测试实例可使用 8311。

## CLI：执行已允许的一步

以下操作可能调用已配置的模型，需由调用者在获准的项目上主动执行。图 revision 或任务条件发生变化会拒绝请求，调用者重新读取并决定，不应盲目重放旧请求。

```powershell
$view = Invoke-RestMethod $base
$action = $view.next_actions | Where-Object action -eq 'run_next' | Select-Object -First 1
if ($null -eq $action) { throw '没有允许的 Build 下一步；查看 readiness.blockers 和 human_confirmation' }
$body = $action.preconditions | ConvertTo-Json
$job = Invoke-RestMethod -Method Post -Uri "$base/next" -ContentType 'application/json' -Body $body
$job
# 后续查询同一投影中的 job.status 和 tasks；不要自动确认候选。
Invoke-RestMethod $base | ConvertTo-Json -Depth 8
```

提交人工或 Agent 已准备好的完整任务 JSON：

```powershell
$view = Invoke-RestMethod $base
$taskId = 'world_economy' # 从 next_actions 中选择真实可编辑的 task_id
$action = $view.next_actions | Where-Object { $_.action -eq 'edit_artifact' -and $_.task_id -eq $taskId } | Select-Object -First 1
if ($null -eq $action) { throw '该任务当前不允许编辑' }
$body = @{
  expected_graph_revision = $action.preconditions.expected_graph_revision
  expected_revision = $action.preconditions.expected_revision
  payload = Get-Content './task-payload.json' -Raw | ConvertFrom-Json
} | ConvertTo-Json -Depth 40
Invoke-RestMethod -Method Patch -Uri "$base/tasks/$taskId/artifact" -ContentType 'application/json' -Body $body
```

## Codex / MCP 的可执行适配示例

下列 Python 标准库函数可直接用作 Codex 的本地命令，或注册为 MCP 的 read_build / run_next 工具处理器。它不是新的 MCP 服务或另一个任务状态机。MCP 主机仍应对 run_next 设置写入权限；不要把 human_confirmation 节点转成自动工具调用。

```python
import json
from urllib.request import Request, urlopen
from urllib.parse import quote


def read_build(project_id, origin="http://127.0.0.1:8000"):
    path = f"/file-projects/{quote(project_id, safe='')}/public-build"
    with urlopen(origin + path) as response:
        return json.load(response)


def run_next(project_id, action, origin="http://127.0.0.1:8000"):
    assert action["action"] == "run_next"
    assert not action["requires_human_confirmation"]
    path = f"/file-projects/{quote(project_id, safe='')}/public-build/next"
    request = Request(origin + path, method="POST",
                      data=json.dumps(action["preconditions"]).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request) as response:
        return json.load(response)

# snapshot = read_build("your-project-id")
# print(json.dumps(snapshot["readiness"], ensure_ascii=False))
# 仅在获得执行授权后：
# action = next(a for a in snapshot["next_actions"] if a["action"] == "run_next")
# result = run_next("your-project-id", action)
```

## 错误和权限契约

- `409 / build_revision_conflict`：graph 或 artifact revision 已变。响应携带允许公开的 expected/current revision；未提交候选写入。
- `422 / validation_failed`：现有领域 validator 拒绝，诊断只包含 code/severity。现有正文与产物保持原状态。
- `403 / build_task_not_editable`：imported / deterministic 任务不允许直接编辑。
- `403 / human_review_required`：需要人工审查，不能通过本入口自行接受。
- `403 / opening_consumed_planning_locked`：已用于正式章节的开书规划被现有服务锁定。
- `409 / build_no_allowed_action`：没有匹配 task_id 的当前下一动作；检查阻断和人工确认节点。
- `503 / public_adapter_dependency_update_required`：现有 Web handler 新增了依赖，适配器保守拒绝，需明确适配依赖后才能开放。

写入复用实际注册的 Web handler → BuildGraph / opening / candidate 边界，保留校验、来源检查、materialization 失效和 stale 传播。公共层额外在相同的 active-job → project 锁顺序内检查 graph revision；没有第二套状态机或 last-write-wins。服务器的现有进程内锁语义继续适用，部署时应使用当前支持的单进程写服务。

公共响应不返回 artifact payload、候选正文、质量报告自由文本、prompt_call_id、raw prompt/response、validator message/path/details、provider endpoint、key、header 或 capability note。能力值仅公开 tri-state 和已知的数值 limits；未知值保持 unknown。CLI output budget 标记 best_effort，不宣称硬上限。能力接口只读当前运行时配置与缓存，不进行网络 discovery、probe 或刷新。

## 合成契约测试

```powershell
python -m pytest tests/api/test_build_public_routes.py tests/story_core/test_build_public.py tests/api/test_build_workbench_route.py tests/api/test_build_workbench_edit_route.py tests/api/test_opening_build_routes.py -q
```

覆盖只读不写盘、stale/review_required/validation_failed、并发 revision 冲突、权限、消耗后的 opening 写锁、候选项目归属与人工确认边界、能力来源和脱敏。所有数据为临时合成项目，模型调用采用注入实现或捕获调度，不调用真实 provider。
