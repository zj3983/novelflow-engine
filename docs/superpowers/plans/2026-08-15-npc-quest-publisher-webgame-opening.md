# NPC任务发布者网游开书实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按已确认设计建立一部完全独立的网游新书，补齐开书资料、首卷大纲和细纲，并生成一章可验收的正文。

**Architecture:** 通过现有文件项目 API 完成开书，不直接手改项目数据。每个阶段读取上一步保存的正式产物；生成第一章前必须确认首卷细纲完整，生成后先保留候选稿，人工验收通过后才确认为正式章节。

**Tech Stack:** FastAPI 文件项目接口、`FileProjectStore`、现有开书方向生成器、世界补全器、大纲规划器、卷细纲生成器、模块化正文流水线。

---

## 文件与产物

- 读取：`docs/superpowers/specs/2026-08-15-npc-quest-publisher-webgame-design.md`
- 创建：`data/exported-projects/$projectIdWithoutPrefix/`
- 检查：`data/exported-projects/$projectIdWithoutPrefix/.webnovel/project.json`
- 检查：`data/exported-projects/$projectIdWithoutPrefix/.webnovel/state.json`
- 检查：`data/exported-projects/$projectIdWithoutPrefix/.webnovel/outline.json`
- 检查：`data/exported-projects/$projectIdWithoutPrefix/.story-system/MASTER_SETTING.json`
- 检查：`data/exported-projects/$projectIdWithoutPrefix/.story-system/generation-jobs/`

### Task 1: 开书前检查

- [ ] **Step 1: 确认前后端服务可用**

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:3000/projects -UseBasicParsing
```

Expected: 后端返回健康状态，前端返回 HTTP 200。

- [ ] **Step 2: 记录开书前项目列表**

```powershell
Invoke-RestMethod http://127.0.0.1:8000/file-projects |
  Select-Object project_id,title
```

Expected: 记录当前项目，后续能够证明新项目使用了新的 `project_id`。

### Task 2: 创建独立项目并选择开书方向

- [ ] **Step 1: 创建网游灵感项目**

```powershell
$idea = @'
虚拟现实网游《万象》。主角周行，24岁，前职业战队替补，游戏ID行舟。战队解散后靠陪练和代打生活，只分到一台旧游戏舱。他进入游戏打算建立稳定收入，意外发现自己能向NPC发布任务。奖励必须真实支付，NPC可以拒绝，任务失败会损失奖励、信誉或阵营关系。主角靠职业操作、判断和任务设计破局，不懂游戏开发内幕。首章从战队清算与新手镇资源拥挤开始，第一次用一顿饭向流浪NPC发布寻路任务，找到废弃水道，并收到区域最终敌人的异常任务申请。
'@
$created = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/file-projects `
  -ContentType 'application/json; charset=utf-8' `
  -Body (@{
    mode = 'inspiration'
    title = '网游：全服只有我能给NPC发任务'
    novel_type_id = 'game_webnovel'
    idea = $idea
    narrative_enhancement_ids = @()
  } | ConvertTo-Json -Depth 8)
$created | ConvertTo-Json -Depth 8
```

Expected: HTTP 201；返回新的 `project_id`，`current_chapter` 为 0，题材为网游，未默认启用 Skill。

- [ ] **Step 2: 生成开书方向**

```powershell
$projectId = $created.project_id
$directions = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/file-projects/$projectId/opening-directions" `
  -ContentType 'application/json; charset=utf-8' `
  -Body (@{ guidance = '严格采用已给定的周行人设、NPC任务发布能力和第一章事件，不替换主角，不改成开发者或重生者。' } | ConvertTo-Json)
$directions | ConvertTo-Json -Depth 12
```

Expected: 返回若干具体方向；至少一个方向保留周行、行舟、前职业替补和NPC任务发布能力。

- [ ] **Step 3: 人工选择最符合设计的方向**

```powershell
$selectedDirection = $directions.directions |
  Where-Object {
    ($_.protagonist_profile + $_.hook + $_.logline) -match '周行|行舟' -and
    ($_.core_advantage.ability + $_.hook) -match '发布任务|向NPC'
  } |
  Select-Object -First 1
if (-not $selectedDirection) {
  throw '三个方向均未保留确认过的人设与核心能力，停止开书。'
}
$directionId = $selectedDirection.id
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/file-projects/$projectId/opening-directions/$directionId/select"
```

Expected: 方向被锁定；故事核心不包含旧书的夜烬、灰狼坡、千倍爆率或元素法师。

### Task 3: 补齐世界、人物和总纲

- [ ] **Step 1: 补全世界资料**

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/file-projects/$projectId/enrich-world"
```

Expected: 世界背景、游戏规则、经济与任务体系、周行角色卡写入项目；周行现实身份和游戏ID保存在同一张角色卡内。

- [ ] **Step 2: 生成初始大纲**

```powershell
$outline = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/file-projects/$projectId/outline/generate" `
  -ContentType 'application/json; charset=utf-8' `
  -Body (@{
    mode = 'initial'
    guidance = '首卷不少于50章；每15章形成一个完整小循环；第一卷完成新手地区冲突并进入第一座主城。保持任务能力有成本、NPC可拒绝、现实线持续推进。'
  } | ConvertTo-Json)
$outline | ConvertTo-Json -Depth 20
```

Expected: 同时生成故事核心、总纲、角色阵容和首卷规划；第一卷不少于50章，不能把15章小循环误当成整卷。

- [ ] **Step 3: 检查项目隔离和资料完整性**

```powershell
$root = Join-Path 'data/exported-projects' ($projectId -replace '^file:','')
rg -n '夜烬|灰狼坡|千倍爆率|元素法师|苏叶' $root
Get-Content "$root/.webnovel/project.json" -Raw
Get-Content "$root/.webnovel/outline.json" -Raw
```

Expected: `rg` 无旧书命中；项目包含周行、行舟、《万象》、任务发布能力、首卷目标和现实线目标。

### Task 4: 生成完整首卷细纲

- [ ] **Step 1: 查询第一章对应卷状态**

```powershell
$workflow = Invoke-RestMethod `
  "http://127.0.0.1:8000/file-projects/$projectId/outline/volume-workflow?target_chapter=1"
$workflow | ConvertTo-Json -Depth 12
```

Expected: 返回首卷 ID；若状态不是 `ready`，明确要求生成卷细纲。

- [ ] **Step 2: 为整卷生成细纲**

```powershell
$volumeId = $workflow.volume.id
$detail = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/file-projects/$projectId/outline/volumes/$volumeId/detail" `
  -ContentType 'application/json; charset=utf-8' `
  -Body (@{ guidance = '细纲覆盖完整首卷，不少于50章。每章必须有具体事件、冲突、结果、出场人物和章末推动；第一章严格采用一顿饭发布寻路任务的开局。' } | ConvertTo-Json)
$detail | ConvertTo-Json -Depth 20
```

Expected: 首卷每章都有章节标题和可执行细纲，不出现“未命名”、`continue` 或抽象的“继续施压”。

- [ ] **Step 3: 再次查询卷状态**

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8000/file-projects/$projectId/outline/volume-workflow?target_chapter=1" |
  ConvertTo-Json -Depth 12
```

Expected: 状态为 `ready`；正文入口不再要求返回大纲页。

### Task 5: 生成并验收第一章

- [ ] **Step 1: 启动第一章生成任务**

```powershell
$job = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/file-projects/$projectId/generation-jobs" `
  -ContentType 'application/json; charset=utf-8' `
  -Body (@{ chapter_number = 1 } | ConvertTo-Json)
$job | ConvertTo-Json -Depth 12
```

Expected: 返回新任务 ID；没有 `volume_detail_incomplete`、`invalid_primary_trope_id` 或跨项目标题。

- [ ] **Step 2: 等待任务完成并查看各阶段产物**

```powershell
do {
  Start-Sleep -Seconds 5
  $status = Invoke-RestMethod `
    "http://127.0.0.1:8000/file-projects/$projectId/generation-jobs/$($job.job_id)"
  $status.status
} while ($status.status -in @('queued','running'))
$status | ConvertTo-Json -Depth 20
```

Expected: 状态为候选稿待确认；日志能看到导演读取细纲、角色卡、世界规则和事实，写手读取导演产物。

- [ ] **Step 3: 人工验收候选稿**

验收以下内容，任一硬伤存在则不确认：

1. 主角是周行，游戏ID是行舟，现实与游戏身份没有拆成两个人。
2. 开局事件符合细纲，没有换成旧书场景或其他外挂。
3. 对话使用自然完整的现代中文，不靠连续短句装高手。
4. 任务发布有真实奖励、NPC动机和接受过程，不写成无条件控制。
5. 游戏数值、货币、物品、任务和人物状态前后一致。
6. 正文达到项目字数要求，面板和解释没有混写成说明书。
7. 标题来自首卷细纲，写手没有另造标题。

- [ ] **Step 4: 验收通过后确认正式章节**

```powershell
$candidateId = $status.candidate.candidate_id
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/file-projects/$projectId/candidates/$candidateId/confirm"
```

Expected: 第1章成为正式章节，`current_chapter` 更新为1；角色、物品、任务和世界事实同步保存。

### Task 6: 最终回归检查

- [ ] **Step 1: 检查项目页面和第一章页面**

```powershell
$encoded = [uri]::EscapeDataString($projectId)
Invoke-WebRequest "http://127.0.0.1:3000/projects/$encoded" -UseBasicParsing
Invoke-WebRequest "http://127.0.0.1:3000/projects/$encoded/write?chapter=1" -UseBasicParsing
```

Expected: 两个页面均返回 HTTP 200，项目可从作品列表打开。

- [ ] **Step 2: 汇报真实结果**

记录新项目链接、书名、主角、首卷章节范围、第一章标题与字数、候选稿是否确认，以及发现的所有质量问题。不得把未确认候选稿报告为正式章节。
