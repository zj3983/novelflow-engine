# 原作者能力对齐矩阵

状态：**阶段 0 冻结**（2026-09-29）
基线：PR #45 `2cfa01795c0c8ba9b457379e1cd30738cab06091`
权威范围：[`original-capability-parity-revision-plan.md`](original-capability-parity-revision-plan.md) 第 2、3.A.1、3.A.2、4、5、7、8 节。本文按原作者页面和可执行操作登记；未标为已迁入的行仍是实施和验收目标。

列说明：读取来源和写入服务按当前旧页面/API 实现登记；保护条件列记录现有边界和本轮必须补齐的缺口。每行 ID 同时是该行产品投影/API 契约的验收编号，场景条件写在该行最后一列；主计划第 7 节保留跨页面的整体验收要求。`P` 表示 `/projects/[id]`。

## 作者操作迁移

| ID | 原入口与操作 | 读取来源 | 当前写入服务 | 目标入口 | 保护条件与验收 |
|---|---|---|---|---|---|
| BOOK-01 | `/projects`：浏览作品、进度和状态 | `GET /file-projects`、项目 metadata、候选与已确认章节 | 无 | 作品列表 | 活跃／归档／回收状态分开；章数和字数由已保存内容计算。验收场景：BOOK-01 |
| BOOK-02 | `P`、`P/settings`：简介、封面、篇幅目标、类型与文风 | `GET /file-projects/{id}`、出版素材、`GET /novel-types` | publishing synopsis/cover APIs；`PUT /file-projects/{id}` 对指定项目字段合并 | 作品资料；全局类型管理从作品页进入 | 生成只可显式触发；只合并目标字段并复核源状态。验收场景：BOOK-02 |
| BOOK-03 | 归档、回收、恢复、彻底删除 | `GET /file-projects` 的 lifecycle 过滤及项目 metadata | `POST /archive`、`POST /trash`、`POST /restore`、`DELETE /file-projects/{id}?confirm_title=...` | 作品管理与回收站 | 删除需完整书名、回收状态、当前身份与现有清理限制服务端复核；页面禁用不构成保护。验收场景：BOOK-03 |
| BOOK-04 | 新建、导入续写、选择故事方向 | 创建／导入服务、`GET/POST /opening-directions` | 创建／导入服务、`POST /opening-directions/{direction_id}/select` | 作品开书流程，方向选择后进入全书规划 | 续写导入与空白新建分开；选择时复核源指纹；不覆盖导入正文。验收场景：BOOK-04 |
| TYPE-01 | `/novel-types` 全局类型查看、创建、编辑、删除 | `GET /novel-types` | `POST/PUT/DELETE /novel-types` | 从作品资料可达的独立作者工具 | 沿用现有类型注册、校验和内置类型限制；项目切换不清理图鉴。验收场景：TYPE-01 |
| PLAN-01 | `P/outline`：总纲、卷规划、章节规划、编辑、采纳、下一卷 | `GET/PUT /file-projects/{id}/outline`、rolling outline、volume workflow、build graph/artifacts | outline update、opening/build-graph 服务、plan acceptance | 全书规划 | 已被正文消费的规划不可覆盖；规划变化使旧采纳失效；版本／来源复核。普通投影不得返回 Build Graph 任务。验收场景：PLAN-01 |
| PLAN-02 | `P/outline`：伏笔查看、筛选、修改和保存 | `GET /file-projects/{id}/foreshadowing` | `PUT /file-projects/{id}/foreshadowing` | 故事设定 → 伏笔线索；规划仅显示关联摘要 | 复用台账版本保护；只能显示有效章节来源。验收场景：PLAN-02 |
| WRITE-01 | `P/write`、`P/chapters`：目录、搜索、定位、阅读、复制 | 确认章节索引／文件、候选 API | 复制仅在浏览器；目录查询只读 | 写作 | 历史正文只读；搜索不改正文位置；目录滚动限于目录容器。验收场景：WRITE-01 |
| WRITE-02 | 生成候选、手改／AI 改稿、检查、丢弃、确认、确认并继续 | generation jobs、candidate store、chapter source | generation/review jobs、candidate edit/discard/confirm、continuation service | 写作 | 候选 authority、检查绑定与源状态在服务端复核；必须人工确认；下一章启动在确认事务后。验收场景：WRITE-02 |
| WRITE-03 | `P/dissection`：参考书拆解、本书章节体检、报告用于当前候选改稿 | `POST /book-dissection/reference`、`POST /file-projects/{id}/book-dissection/chapter` | 拆解服务；应用报告走现有候选改稿服务 | 写作 → 拆书与章节体检独立作者工具 | 报告不直接写约束；绑定项目、章节和正文来源；已确认章节保持只读。验收场景：WRITE-03 |
| SET-01 | `P/characters`：完整名册、筛选、稳定档案、动态状态、编辑／补全 | project `character_profiles`、current state characters、confirmed continuity | `PUT /characters/{name}`、`POST /characters/{name}/complete-portrait` | 故事设定 → 人物 | 稳定档案、当前状态、已确认事实和未来计划分开；事实仅在有章节依据时展示；并发修改拒绝覆盖。验收场景：SET-01 |
| SET-02 | `P/relationships`：新增、修改、删除、保存关系图 | project relationship graph、角色名册 | `PUT /file-projects/{id}` 的 `relationship_graph` 字段 | 故事设定 → 人物关系 | 新端点需在项目锁内做读时凭证比较并原子保存；非法端点和并发旧稿拒绝；不覆盖确认事实。验收场景：SET-02 |
| SET-03 | `P/world`：背景、规则、地点、势力编辑；AI 补全；装备／怪物图鉴 | project `world_blueprint`、world summary、world-build job | `PUT /file-projects/{id}` 指定蓝图字段；`POST /enrich-world` / world-build jobs；现有图鉴保存路径 | 故事设定 → 世界规则 | 保存时只改指定字段；AI 工作在锁外、应用前复核；手改冲突不覆盖；非网游不展示网游图鉴。验收场景：SET-03 |
| SET-04 | `P/sim`：当前快照、逐章响应、公开变化、压力、角色获知、幕后事件、隐藏信息、市场状态 | confirmed `world_snapshot` 与逐章 simulation / response bundles | 只读 | 故事设定 → 世界局面；写作显示本章摘要 | 逐章选择读取对应章节，不得总展示最新快照；预测、幕后和作者可见信息标注知情范围；原始对象、计数和未知字段不下发。验收场景：SET-04 |
| SET-05 | `P/settings`：项目类型、文风 | `world_blueprint.genre_plugin_ids`、`writing_style`、novel type catalog | `PUT /file-projects/{id}` 指定 `world_blueprint` 字段 | 作品资料；创作要求提供跳转 | 只改指定字段；版本冲突拒绝旧蓝图覆盖；影响后续生成，不改已确认正文。验收场景：SET-05 |
| PROMPT-01 | `P/prompts` 模板区：编辑、项目覆盖、更新全局、恢复全局、普通检查、深度检查 | project/global prompt-template stores；占位符定义 | 项目模板 PUT/DELETE、全局模板 PUT、普通／深度 prompt audit | 故事设定 → 创作要求 → 写作指令模板 | 项目／全局作用范围确认；并发凭证和模板内容摘要校验；检查不保存，编辑后旧检查失效；深度检查显式触发；不返回真实 prompt context 或诊断。验收场景：PROMPT-01 |
| PROMPT-02 | `P/prompts` 实际调用、上下文快照、调用日志与诊断 | prompt context / preview / call-log APIs | 无（内部调用） | 内部保留 | 不出现在普通作者产品 DTO、普通导航或模板编辑结果。验收场景：PROMPT-02 / INT-02 |
| SKILL-01 | `P/skills` 项目选择：包、根模块、子模块启用／关闭、保存 | project enabled IDs 与已安装包目录 | `PUT /file-projects/{id}` 的 `enabled_skill_ids`、`enabled_skill_module_ids` | 故事设定 → 创作要求 → 本书写作能力 | 保留旧项目默认与根／子模块语义；保存需读时版本校验、确认包和模块存在并原子提交；运行中任务用启动时快照。验收场景：SKILL-01 |
| SKILL-02 | `P/skills` 全局管理：包列表／安装、路径导入、ZIP 上传、卸载包／子模块 | `/skill-packs` registry | `/skill-packs/import`、`/upload`、DELETE 包／模块 | 独立“写作能力库管理”工具，从本书写作能力进入 | 复用路径许可、归档校验与现有卸载清理；安装不自动启用；卸载前明确全局影响并确认；不执行包内脚本。验收场景：SKILL-02 |
| REVIEW-01 | `P/review`：问题、依据、硬冲突和软建议 | 现有 chapter review / candidate review | 写作页候选审查与确认服务 | 写作问题栏 | 硬冲突仍阻断确认；软提醒需作者明确选择。验收场景：REVIEW-01 |

## 内部保留与不迁移操作

| ID | 原入口 | 处理 | 边界与验收 |
|---|---|---|---|
| INT-01 | `P/build` | 普通作者使用规划内容与动作；Build Graph 任务、artifact、revision、stale、validation 记录留在机器接口 | 普通产品 API 仅映射作者规划和可执行动作。验收场景：INT-01 |
| INT-02 | `P/log`、prompt context/call log | 内部诊断直达路由保留，不加入普通导航或作者投影 | 不向普通 Web 返回 raw diagnostics、provider/model/protocol 信息、私密上下文。验收场景：PROMPT-02 / INT-02 |

## 固定页面基准

视觉对照固定使用 `references/books.png`、`references/planning.png`、`references/writing.png`、`references/story.png`。布局验收尺寸为桌面 1487px 和窄屏 390px；变更需记录相对这四张参考图的布局偏差。现有 `evidence/browser-2026-09-28/` 截图是此前实现记录，不替代参考图，也不作为本轮功能通过证明。

## 冻结规则

- 本矩阵冻结的是来源、去向、写入边界和保护要求；不表示任何未勾选的迁移验收已经完成。
- 若实现时源代码与登记不符，先将证据和差异写入变更记录，再更新对应行；禁止因旧页仍可访问而删除该能力。
- 验收项编号与主计划第 7 节保持同步。新增验收不改变四页产品边界，不引入第二套存储、模型调用或调度流程。
