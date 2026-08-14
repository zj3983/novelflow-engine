# 连续生成章节设计

## 目标

在文件小说项目的写作页提供连续生成。用户选择目标章数后，系统按顺序生成新章节、通过现有质量检查、自动确认并写入正式正文，再继续下一章。连续生成只处理新章节，不自动重写已有章节。

## 用户操作

- 写作页增加“连续生成”入口。
- 可选择 2、5、10、20 章，默认 5 章。
- 开始后显示目标数量、当前章节、已完成数量和最近一步状态。
- 运行中提供“停止生成”。停止是协作式停止：当前模型调用完成后不再启动下一章，不强行中断正在写入的数据。
- 页面关闭或刷新不影响后端任务；重新进入页面后恢复任务状态。
- 同一本书同一时间只允许一个普通生成、重写、扩写或连续生成任务。

## 后端结构

新增项目级连续生成任务，持久化到：

`<project>/.story-system/continuous-generation-jobs/<job_id>.json`

任务至少记录：

- `job_id`、`project_id`
- `status`: `queued | running | stopping | completed | stopped | failed`
- `requested_count`、`completed_count`
- `start_chapter`、`current_chapter`、`completed_chapters`
- `stop_requested`
- `progress`、`stop_reason`、`error`
- `created_at`、`updated_at`

提供接口：

- `POST /file-projects/{project_id}/continuous-generation-jobs`
- `GET /file-projects/{project_id}/continuous-generation-jobs/current`
- `GET /file-projects/{project_id}/continuous-generation-jobs/{job_id}`
- `POST /file-projects/{project_id}/continuous-generation-jobs/{job_id}/stop`

创建参数只有 `count`，取值限制为 2、5、10、20。

## 每章执行流程

1. 读取项目当前正式章节号，确定下一章。
2. 调用现有卷流程检查。只有 `detail_complete` 才能继续。
3. 调用现有单章生成能力，不绕过导演、写手、事实一致性和质量检查。
4. 生成候选稿后自动执行普通确认，不使用强制确认。
5. 普通确认成功后，将章节加入 `completed_chapters`，再计算下一章。
6. 达到目标数量后标记 `completed`。

连续任务不得调用重写、扩写或自动改稿接口，也不得在质量失败后自行再生成一个版本。

## 停止条件

出现以下任一情况立即停止，不启动下一章：

- 用户请求停止：`stopped`，原因 `user_stopped`。
- 下一卷不存在：`stopped`，原因 `next_volume_required`。
- 当前卷细纲未完成：`stopped`，原因 `volume_detail_required`。
- 候选稿普通确认失败或需要强制确认：`stopped`，原因 `candidate_confirmation_required`，保留候选稿供用户处理。
- 模型调用、质量检查、保存或状态更新失败：`failed`，保存可读错误。
- 检测到其他活跃生成任务：创建时返回冲突，不创建第二个任务。

已经正式确认的章节不回滚。失败章节如果形成候选稿则保留，不覆盖正式正文。

## 恢复策略

- 后端启动或首次读取任务时，将磁盘中 `queued`、`running`、`stopping` 的任务重新装载。
- 根据正式章节和 `completed_chapters` 对账，避免重复生成已经确认的章节。
- 若无法安全判断上一步是否完成，将任务标记为 `stopped`，原因 `recovery_confirmation_required`，不自动重跑。

## 前端状态

- 未运行：显示章数选择和“连续生成”。
- 运行中：禁用普通生成、重写、扩写和再次连续生成，显示“正在生成第 N 章”。
- 已停止：显示已完成章节及明确原因；细纲不足时链接到对应卷的大纲页。
- 确认受阻：链接到待确认候选稿。
- 完成：刷新章节列表并打开最后完成的章节。

前端只负责启动、轮询、停止和展示，不负责在浏览器内循环生成。

## 测试与验收

- 后端单元测试覆盖数量校验、顺序生成、自动普通确认、用户停止、卷边界、细纲不足、确认受阻、失败保留和重启恢复。
- API 测试覆盖创建、冲突、查询、停止及持久化。
- 前端测试覆盖入口、进度、停止、刷新恢复、完成跳转和错误引导。
- 验收场景：选择连续生成 5 章，任务按顺序写入 5 章；中途不存在任何自动重写；在第 3 章遇到细纲缺失时保留前 2 章并停止。
