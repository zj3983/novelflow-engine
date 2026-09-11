const ERROR_MESSAGES: Array<[string, string]> = [
  ["director_artifact_missing_dialogue_task", "章节规划没有写清人物如何交流，请重新生成。"],
  ["director_artifact_insufficient_beats", "章节规划的场景不足，请重新生成。"],
  ["director_artifact_incomplete_beat", "章节规划缺少场景行动或结果，请重新生成。"],
  ["director_artifact_missing_state", "章节规划缺少开场或收尾状态，请重新生成。"],
  ["director_response_missing_scene_beats", "章节规划没有生成可用场景，请重新生成。"],
  ["director_response_missing_chapter_number", "章节规划缺少章节编号，请重新生成。"],
  ["director_response_not_dict", "章节规划返回格式不正确，请重新生成。"],
  ["invalid_primary_trope_id", "题材套路配置已失效，请重新选择后再生成。"],
  ["combined_outline_validation_failed", "大纲内容校验未通过，请检查题材配置后重新生成。"],
  ["outline_planning_generation_failed", "大纲生成失败，请重试。"],
  ["opening_direction_generation_failed", "开篇方向生成失败，请重试。"],
  ["volume_detail_generation_failed", "本卷细纲生成失败，请重试。"],
  ["volume_detail_continuity_invalid", "本卷细纲前后衔接不完整，请重新生成。"],
  ["volume_detail_publish_validation_failed", "本卷细纲还没有通过完整性检查。"],
  ["rolling_outline_missing", "还没有可用的滚动细纲，请先补全本卷。"],
  ["rolling_outline_write_failed", "细纲保存失败，请重试。"],
  ["world_context_required", "世界观资料不完整，请先补充世界背景和规则。"],
  ["next_volume_required", "当前卷已经结束，请先设计下一卷。"],
  ["volume_detail_incomplete", "本卷章节细纲不完整，请先补全细纲。"],
  ["volume_detail_required", "本卷章节细纲不完整，请先补全细纲。"],
  ["chapter_outline_required", "当前章节没有细纲，请先生成细纲。"],
  ["candidate_above_chapter_maximum", "候选稿章节号超出当前规划范围，请检查大纲后重试。"],
  ["project_generation_in_progress", "当前已有生成任务正在运行，请等待完成后再试。"],
  ["body_required", "模型没有返回正文，请重新生成。"],
  ["api_key_required", "请先填写 API Key。"],
  ["api_key_not_configured", "请先配置 API Key。"],
  ["unknown_provider", "当前模型服务商配置无效，请重新选择。"],
  ["provider_account_missing", "当前模型服务商还没有配置账号。"],
  ["model_required", "请先选择模型。"],
  ["invalid_base_url", "接口地址格式不正确，请检查后重试。"],
  ["rate_limited", "模型请求过于频繁，请稍后再试。"],
  ["file_project_not_found", "没有找到这部小说，可能已被删除或移动。"],
  ["project_not_found", "没有找到这部小说，可能已被删除或移动。"],
  ["file_story_not_found", "这部小说还没有可用的正文资料。"],
  ["story_not_found", "没有找到正文资料。"],
  ["chapter_not_found", "没有找到这一章。"],
  ["outline_not_found", "还没有大纲，请先生成或补充大纲。"],
  ["candidate_not_found", "没有找到这份候选稿，可能已经处理过。"],
  ["candidate_not_pending", "这份候选稿已经处理过，不能重复操作。"],
  ["candidate_confirmation_required", "有一章需要人工确认，请打开候选稿。"],
  ["recovery_confirmation_required", "任务恢复状态不明确，请检查正文和候选稿。"],
  ["continuous_generation_job_not_found", "没有找到这次连续生产任务，可能已被清理。"],
  ["file_generation_job_not_found", "没有找到这次生成任务，可能已被清理。"],
  ["generation_job_not_found", "没有找到这次生成任务，可能已被清理。"],
  ["consistency_replan_attempt_limit", "这次任务的重新规划次数已用完，请返回修改或确认继续。"],
  ["consistency_replan_not_available", "当前任务暂时不能重新规划，请刷新后查看状态。"],
  ["consistency_replan_plan_unavailable", "原章节计划未能保存，请返回修改后重新生成。"],
  ["consistency_replan_failed", "重新规划失败，原计划仍然保留。"],
  ["skill_pack_not_found", "没有找到这个 Skill，可能已被卸载。"],
  ["provider_not_found", "没有找到这个模型服务商配置。"],
  ["model_discovery_failed", "获取模型列表失败，请检查接口地址和账号。"],
  ["publishing_asset_stale_synopsis", "简介已在其他页面更新，请刷新后再保存。"],
  ["publishing_asset_stale_cover", "封面资料已在其他页面更新，请刷新后再保存。"],
  ["publishing_asset_stale_base", "作品资料已更新，请刷新页面后再操作。"],
  ["publishing_asset_write_failed", "作品发布资料保存失败，请重试。"],
  ["publishing_asset_read_failed", "作品发布资料读取失败，请刷新页面。"],
  ["synopsis_generation_failed", "简介生成失败，请重试。"],
  ["cover_prompt_generation_failed", "封面方案生成失败，请重试。"],
  ["cover_generation_failed", "封面生成失败，请重试。"],
  ["invalid_novel_type", "小说类型配置无效，请重新选择。"],
  ["invalid_writing_style", "文风配置无效，请重新选择。"],
  ["project_is_trashed", "这部小说已在回收站中，请先恢复。"],
  ["analysis_not_ready", "导入分析还没有完成，请稍后再试。"],
  ["analysis_confirmation_required", "请先确认导入分析结果。"],
  ["continuation_conversion_in_progress", "续写项目正在转换，请不要重复提交。"],
  ["source_path_not_found", "没有找到导入文件，请重新选择。"],
  ["unsupported_source_type", "暂不支持这种文件格式。"],
];

export function userFacingErrorMessage(
  error: unknown,
  fallback = "操作失败，请稍后重试。",
): string {
  const text = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  if (!text) return fallback;
  for (const [code, message] of ERROR_MESSAGES) {
    if (text.includes(code)) return message;
  }
  if (text.includes("CanonEntity") && text.includes("no attribute")) {
    return "角色或物品资料读取失败，请重新生成。";
  }
  if (text.toLowerCase().includes("timeout") || text.includes("超时")) {
    return "请求超时，请重新尝试。";
  }
  // A leading Chinese context label (e.g. "故事加载失败：") is useful to the
  // reader even when the technical suffix falls back to a generic message.
  const contextPrefix = /^[一-龥][^\n：:]{1,20}[：:]/.exec(text)?.[0] ?? "";
  if (/^[A-Za-z]+Error:/.test(text) || /[a-z]{3,}_[a-z_]{3,}/.test(text)) {
    return contextPrefix ? `${contextPrefix}${fallback}` : fallback;
  }
  if (/^https?:\/\//.test(text) && text.includes(" failed:")) {
    return contextPrefix ? `${contextPrefix}${fallback}` : fallback;
  }
  return text;
}
