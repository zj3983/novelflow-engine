# 长篇小说工作区：开发交付说明（尚未验收）

## 本轮状态与边界

本轮依据用户“先把计划里的任务都跑完，测试先不做”的指令继续实现。下文是代码接入说明与后续操作指引，**不是执行成功记录**。本轮没有运行新增测试、构建、类型检查、浏览器验收或真实模型调用。阶段 A 的历史测试不能代替本轮验证。

普通页面以作品、全书规划、写作、故事设定四页组织。页面复用同一套 `LongformWorkspace` 组件，通过独立适配器选择模拟数据或真实 API。用户状态、建议和动作由后端产品映射提供，内部机器接口继续保留。

### 入口

| 地址 | 数据与用途 |
| --- | --- |
| `/prototype/longform` | 阶段 A 独立演示；浏览器模拟数据、固定模拟结果，不调用业务 API。当前没有另建 `/demo` 别名。 |
| `/workspace` | 四页真实产品入口；读取后端项目和候选，并通过后端动作处理修改、确认与生成。 |
| `/workspace?page=planning&book=…` | 定位某作品的全书规划。作品标识应使用页面生成的链接。 |
| `/workspace?page=writing&book=…&chapter=…` | 定位正文或历史章节；历史正文只读。 |
| `/config` | 独立模型配置入口，复用已有配置能力。 |

普通 API 入口的“准备故事方向”“准备规划”“生成候选”“让 AI 修改”“重新检查”等操作可能调用配置中的模型。**本轮没有授权真实模型联调，因此当前不点击这些操作。** 下方另提供强制注入固定模型回答的独立离线入口；其实现尚未运行验收。

## 已接入的代码路径

| 页面或动作 | 实现位置与行为 |
| --- | --- |
| 作品与开书 | `/author-workspace` 投影作品，命令接口复用现有创建服务；新书目标默认 900000 字、每章 3000 字，作为创作目标。旧项目缺失目标不回填。归档、恢复和导入沿用既有入口。 |
| 故事方向与正式规划 | 方向准备与选择、开书构建和跨卷发布沿用已有服务。正式规划完成后仍需作者采纳。采纳绑定发布内容、作者要求、作者后续想法和目标，变化后需要重新采纳。 |
| 候选生成 | 新工作区强制仅保存候选并绑定审查结果，等待逐章人工确认。生成前和提交前检查规划及来源，不能借旧单章直接提交路径写入正式正文。 |
| 手工改稿 | 保存新候选，保留旧稿；不调用模型，旧审查和事实变化失效。前端保留未保存编辑草稿，并识别较早候选的草稿。 |
| 重新检查与 AI 修改 | 使用现有后台任务体系。重新检查当前正文，重新提取事实；AI 修改先保存新稿再检查。网络工作在项目锁外，回写时复查来源。检查失败保留改稿并禁止确认。 |
| 确认及继续 | 复用正式确认事务，正文、事实变化与回执一致提交。明确硬冲突不能通过；软建议必须由作者选择接受。确认成功后才预约下一章任务；失败显示本章已保存，并提供显式重试。 |
| 跨卷 | 沿用现有后续规划准备、发布与消耗保护。先查看衔接、修改允许修改的规划、采纳，再生成下一卷候选。作者的后续想法与正式规划是不同内容，保存想法不冒充修改正式细纲。 |
| 故事设定 | 聚合人物、世界、伏笔、作者要求；已有事实只读，可靠来源才提供章节入口。作者要求和后续想法走受保护的输入更新路径，不覆写已确认 Canon。 |
| 刷新与恢复 | 浏览器仅保存页面位置与未保存草稿；任务、候选、检查和确认依据存于服务端。失去执行进程的任务显示中断；读取或刷新不自动重启模型。继续生成和重审均需显式操作。 |

主要文件：

- `apps/web/components/longform/Workspace.tsx`、`product.ts`、`live-adapter.ts`、`demo-adapter.ts`。
- `apps/api/routes/longform_product.py`、`creation_product.py`、`file_projects.py`。
- `packages/story_core/candidate_editing.py`、`longform_lifecycle.py`、`opening_setup_store.py`。
- 既有 `opening_build`、候选存储、确认事务与模型路由继续承担执行责任。

### 实现约定

- 新建时明确设置每章目标的作品，写作提示范围为目标的 90%–110%，既有篇幅审查使用 80%–120% 的容差；未设置目标的旧作品继续使用原规则。这些是正文字符篇幅的编辑规则，不是 token 估计或模型输出硬上限。
- 手工与 AI 改稿后的事实变化重新提取；重审后的章节摘要使用新正文摘录和新提取结果中能在正文定位的句子，不复用旧计划的预期事件作为已写事实。
- 作者任务在阶段结束时仍保留执行位置，只有整个任务结束才释放；应用重启后只报告中断，不自动恢复模型调用。
- 使用原有单进程任务执行和项目锁。启动指令不增加多 worker，不宣称跨进程执行器协调已实现。

## 后续本地启动指引

以下命令仅供后续使用，本轮没有执行。应在本次集成分支目录运行，使用全新的临时项目根，不指向现有小说。依赖安装按仓库说明使用 Python 3.11+、Node 20；若已有环境，复用即可。

### 只打开模拟原型

```powershell
Set-Location <集成仓库目录>\apps\web
$env:NEXT_DIST_DIR = '.next-longform'
npm exec -- next dev -p 3530
```

访问 <http://127.0.0.1:3530/prototype/longform>。不需要 API。模拟内容不能证明真实生成、审查或确认已通过。

### 真实 API 页面，隔离项目存储

在仓库根目录的第一个终端设置独立数据路径：

```powershell
$authorRunRoot = Join-Path $env:TEMP ('novelflow-author-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $authorRunRoot 'projects'), (Join-Path $authorRunRoot 'config') -Force
$env:NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR = Join-Path $authorRunRoot 'projects'
$env:NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS = $env:NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR
$env:NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH = Join-Path $authorRunRoot 'config\runtime_config.json'
$env:NOVEL_AUTOGROWTH_DB_PATH = Join-Path $authorRunRoot 'config\workspace.sqlite3'
$env:NOVEL_AUTOGROWTH_CORS_ORIGINS = 'http://127.0.0.1:3530'
$env:NOVEL_AUTOGROWTH_FRONTEND_URL = 'http://127.0.0.1:3530'
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

第二个终端在 `apps/web`：

```powershell
$env:NEXT_PUBLIC_API_BASE_URL = 'http://127.0.0.1:8000'
$env:NEXT_DIST_DIR = '.next-longform'
npm exec -- next dev -p 3530
```

访问 <http://127.0.0.1:3530/workspace>。这是实际 API 页面，**不是自动注入模型的演示**；当前仅作为启动说明，不在本轮运行或执行其中的模型动作。隔离文件路径不会自动替换模型运行时，也不构成禁止外网调用的测试替身。

### 优先用于后续验收：真实 API 加离线模型回答

新增 `apps/api/longform_synthetic.py`，不改变原集成套件。需要仓库开发依赖；它导入已有合成规划数据工厂，不运行测试函数。第一个终端在仓库根目录：

```powershell
$env:NOVELFLOW_LONGFORM_SYNTHETIC = '1'
$env:NOVELFLOW_LONGFORM_SYNTHETIC_ROOT = Join-Path $env:TEMP ('novelflow-longform-' + [guid]::NewGuid().ToString('N'))
# 保存打印出的路径；要体验重启恢复，重启时使用同一个路径。
$env:NOVELFLOW_LONGFORM_SYNTHETIC_FAIL_ONCE = 'writer:17,consistency:18'
uv run python -m uvicorn apps.api.longform_synthetic:app --host 127.0.0.1 --port 8531
```

第二个终端在 `apps/web`：

```powershell
$env:NEXT_PUBLIC_API_BASE_URL = 'http://127.0.0.1:8531'
$env:NEXT_DIST_DIR = '.next-longform'
npm exec -- next dev -p 3530
```

访问 <http://127.0.0.1:3530/workspace>。只开放工作区产品 API 和健康检查；配置、导入及其他机器接口在此专用环境关闭。模型传输由内存回答替换，禁止外连及 CLI 进程，保留 Windows 事件循环所需的本机回环连接。项目、模型配置、缓存与日志都位于专用目录；入口拒绝非空且没有专用标记的目录，不删除旧目录。

离线模型仅提供通用网文样例、两卷 1–50/51–100 章的规划响应。没有预填任何正文，每章仍需真实任务生成、检查并人工确认。第 17 章写作、第 18 章检查的一次性失败记录在专用目录，可显式重试；删除故障环境变量可取消后续尚未发生的注入。固定审查回答不证明文本质量、任意作者硬要求或真实模型能力。该入口本轮没有启动，不是 60 章通过证据。

## 获准验收后的点击顺序

使用上方专用离线入口，先验证注入覆盖和隔离边界。随后在该隔离环境按以下顺序验收：

1. 作品 → 开新书 → 填写书名、类型、想法、篇幅和要求 → 创建。
2. 全书规划 → 准备故事方向 → 选择方向 → 准备正式规划 → 查看全书、首卷与近期章节 → 采纳当前规划。
3. 写作 → 生成候选 → 阅读正文、审查问题和可靠依据。
4. 我来改写 → 保存改稿 → 重新检查；另走一次“让 AI 修改”，确认检查通过后才能采用。
5. 分别验收“只确认本章”和“确认并继续下一章”；有软建议时明确接受，硬冲突应保持阻断。
6. 注入下一章启动失败，确认当前章仍已保存；刷新后显式重试，检查没有重复确认或重复生成。
7. 故事设定 → 查看四个标签 → 修改作者要求与后续想法；检查事实保持只读、规划需重新采纳、旧候选检查不再可用。
8. 卷末 → 准备下一卷 → 查看前文衔接与新规划 → 调整合法内容 → 采纳 → 继续生成；前卷正文和事实应保持不变。

上述步骤尚未执行，本节不能作为验收证据。

## 仍需执行的验收

- Core/API：候选另存、旧检查拒绝、硬冲突、软建议显式选择、来源漂移、确认事务与下一章失败隔离。
- 任务恢复：进程中断、检查中断、重复点击、请求重试、并发标签、保留编辑草稿和无自动模型恢复。
- 四页操作：正常与异常状态、桌面与窄屏、目录独立滚动、只读历史章节、前端无工程详情入口。
- 真实 FastAPI 与浏览器的合成联调：使用更新后的注入环境，不能沿用旧套件成绩作为本轮结果。
- 从空项目通过实际 API 和注入模型逐章生成并人工确认至少 60 章，跨越 50→51，途中注入失败和改稿；不得用预填 50 章替代。
- 类型检查、生产构建、最终提交的 Python/Web CI。
- 四张设计稿的页面截图对照、正常与异常流程截图、独立复审。

设计原稿在 `references/writing.png`、`books.png`、`planning.png`、`story.png`。这些是设计依据，不是本轮页面截图。本轮没有生成新的实拍页面证据。阶段 A 的浏览器权限验证故障仍列为待复核，不能以已实现代码替代视觉验收。

最终 Draft PR、HEAD 和 CI 链接由集成方完成交付时补充；本文件不虚构 PR 或检查结果。真实模型下的连续性、文本质量、速度和依赖安全仍需独立授权与验收。
