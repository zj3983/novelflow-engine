"""Author-facing descriptions. Engineering records never cross this boundary."""
from __future__ import annotations

from copy import deepcopy
import re


STATES = {
    "pending": ("尚未开始", "neutral", "准备好后，可以让 AI 完善这一部分。"),
    "ready": ("可以继续", "neutral", "所需内容已准备好，可以继续创作。"),
    "running": ("正在创作", "neutral", "正在处理，请等待完成。"),
    "completed": ("已完成", "success", "这一部分已完成，可以查看或继续。"),
    "stale": ("需要更新", "warning", "上游设定已修改，需要重新生成这一部分。"),
    "blocked": ("需要先处理", "danger", "请先完成或修改前面的相关内容。"),
    "validation_failed": ("设定还不完整", "danger", "这一部分需要补充，才能继续创作。"),
    "review_required": ("请检查内容", "warning", "请阅读这一部分，并处理需要修改的地方。"),
    "failed": ("本次未完成", "danger", "这次创作未能完成，请处理问题后重试。"),
}


def status(state, message=None):
    label, tone, default = STATES.get(state, ("请检查内容", "warning", "请检查当前内容后继续。"))
    return {"label": label, "tone": tone, "message": message or default}


def problem(value):
    """Translate known errors; never echo exception text or unknown model output."""
    text = str(value or "")
    pairs = (
        (("candidate_review_required",), "这份改稿尚未检查。", "点击重新检查，通过后再确认正文。"),
        (("candidate_review_unavailable",), "这次检查未能完成，改稿已保留。", "检查模型设置后，重新检查当前稿件。"),
        (("candidate_review_planning_missing",), "这份旧候选缺少重新检查所需的章节安排。", "请保留需要的文字，丢弃旧候选后重新生成。"),
        (("candidate_body_invalid",), "正文不能为空或过长。", "请检查输入的章节正文。"),
        (("candidate_guidance_required",), "请填写本次修改要求。", "说明希望修改的情节或表达，再让 AI 修改。"),
        (("stages.missing_change", "missing_change"), "修炼阶段缺少升级条件。", "补充各阶段的升级条件，或让 AI 修复。"),
        (("stages.missing_name",), "修炼阶段缺少名称。", "为各个阶段补充名称。"),
        (("canon.hard_blocker", "hard_block", "quality_failed", "review_result_blocked"), "正文与已确认的故事事实存在冲突。", "请先修改或重新生成候选，再进行确认。"),
        (("model_preflight", "model_request", "unsupported", "capability", "context_window", "budget"), "当前模型暂时不能完成这项创作。", "请到模型设置中重新测试或更换模型。"),
        (("revision", "source_conflict", "source_changed", "project_world_changed", "state_mismatch"), "相关内容已经修改，请重新查看后再操作。", "刷新页面，确认最新内容后再继续。"),
        (("consumed", "locked", "frozen"), "这部分内容已被正文使用，暂时不能直接修改。", "请保留已确认的故事内容，继续当前可用的创作步骤。"),
        (("outline_required", "volume_detail", "not_ready", "chapter_not_planned"), "下一章的规划尚未准备好。", "请先完成本卷规划，再生成正文。"),
        (("in_progress", "running"), "已有创作正在进行。", "请等待当前创作完成。"),
        (("invalid_power_system", "missing_sections"), "力量成长设定还不完整。", "请补充成长规则，或让 AI 修复。"),
    )
    for keys, message, suggestion in pairs:
        if any(key in text for key in keys):
            return {"message": message, "suggestion": suggestion, "tone": "danger"}
    return {"message": "这部分内容还需要检查。", "suggestion": "请补充相关设定，或让 AI 修复后重试。", "tone": "danger"}


def issues(records):
    result = []
    for record in records or []:
        item = problem(record.get("code") if isinstance(record, dict) else record)
        if isinstance(record, dict) and record.get("severity") == "warning":
            item = {**item, "tone": "warning"}
        if item not in result:
            result.append(item)
    return result


LABELS = {
    "story_core": "故事核心", "world_model": "世界设定", "world_rules": "世界规则",
    "power_system": "成长体系", "power_system_spec": "成长体系", "stages": "修炼阶段",
    "change": "升级条件", "name": "名称", "title": "标题", "description": "说明",
    "summary": "概要", "label": "名称", "content": "内容", "rules": "规则",
    "core_rules": "基本规则", "attributes": "能力属性", "limitations": "限制",
    "cost": "代价", "costs": "代价", "requirements": "所需条件", "conditions": "条件",
    "protagonist": "主角", "characters": "人物", "character": "人物", "motivation": "动机",
    "goal": "目标", "conflict": "冲突", "main_conflict": "主要冲突", "hook": "悬念",
    "opening_hook": "开篇悬念", "theme": "主题", "premise": "故事前提", "setting": "背景",
    "chapter": "章节", "chapters": "章节", "chapter_number": "章节序号", "beats": "情节节点",
    "must_not_write": "禁止内容", "must_include": "必须包含的内容", "author_constraints": "创作要求",
    "world_economy": "经济与生活", "world_society": "社会关系", "world_history": "历史背景",
    "world_geography": "地理环境", "opening_input": "创作想法", "outline_execution_contract": "章节安排",
    "overall": "全书规划", "arcs": "分卷规划", "story": "故事", "start_chapter": "起始章节",
    "end_chapter": "结束章节", "planned_hook": "本章悬念", "next_focus": "后续方向",
    "consequences": "后果", "cause": "原因", "effect": "结果", "abilities": "能力",
}


def part_title(task_id, title):
    if task_id.startswith("chapter_outline_"):
        return f"第 {task_id.removeprefix('chapter_outline_')} 章规划"
    if task_id in LABELS:
        return LABELS[task_id]
    # Titles are definition-owned, but old definitions occasionally embed engine names.
    if re.search(r"[A-Za-z_]|契约|物化|诊断|校验|快照|引擎|兼容层", str(title)):
        return "故事内容"
    return str(title or "故事内容")


def editable_payload(payload, diagnostics):
    result = deepcopy(payload)
    codes = str([item.get("code") for item in diagnostics or []])

    def visit(value):
        if isinstance(value, dict):
            for stage in value.get("stages", []) if isinstance(value.get("stages"), list) else []:
                if isinstance(stage, dict):
                    if "missing_change" in codes:
                        stage.setdefault("change", "")
                    if "missing_name" in codes:
                        stage.setdefault("name", "")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(result)
    return result


def editable_fields(payload, key_for):
    """Flatten content into author fields; structural paths stay server-side."""
    fields, paths = [], {}

    def walk(value, path, labels):
        if isinstance(value, dict):
            for name, item in value.items():
                if name.startswith("_") or name in {"schema_version", "task_id", "artifact_revision", "graph_revision", "prompt_call_id", "provider", "protocol", "metadata"}:
                    continue
                walk(item, path + [name], labels + [LABELS.get(name, "内容")])
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, path + [i], labels + [f"第 {i + 1} 项"])
        elif value is None or isinstance(value, (str, int, float, bool)):
            if isinstance(value, str) and re.fullmatch(r"[a-z]+(?:_[a-z0-9]+)+", value):
                return  # Internal identifiers remain untouched in the saved payload.
            key = key_for(path)
            paths[key] = (path, type(value))
            display = "是" if value is True else "否" if value is False else "" if value is None else str(value)
            fields.append({"key": key, "label": " · ".join(labels[-3:]) or "内容", "value": display,
                           "type": "number" if type(value) in (int, float) else "textarea"})

    walk(payload, [], [])
    return fields, paths


def apply_fields(payload, paths, values):
    if set(values) - set(paths):
        raise ValueError("revision_conflict")
    result = deepcopy(payload)
    for key, text in values.items():
        path, value_type = paths[key]
        value = text
        if value_type is bool:
            if text not in {"是", "否"}:
                raise ValueError("invalid_field")
            value = text == "是"
        elif value_type in (int, float):
            value = value_type(text)
        parent = result
        for part in path[:-1]:
            parent = parent[part]
        if path:
            parent[path[-1]] = value
    return result


def author_advice(quality):
    """Keep actual author advice, excluding diagnostic IDs and transport details."""
    review = quality.get("writing_review") or {}
    findings = [*(review.get("warnings") or []), *(review.get("blocking") or []),
                *((quality.get("review_result") or {}).get("issues") or [])]
    output = []
    forbidden = re.compile(r"artifact|revision|stale|validation_failed|provenance|preflight|canon|json|provider|protocol|authorization|api.?key|https?://|[a-z]+\.[a-z_]+|[A-Za-z0-9_-]{24}", re.I)
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        message = str(finding.get("message") or "").strip()
        if not message or len(message) > 1000 or not re.search(r"[\u4e00-\u9fff]", message) or forbidden.search(message):
            continue
        item = {"message": message, "tone": "danger" if finding.get("blocking") else "warning"}
        if item not in output:
            output.append(item)
    return output


def candidate_review(candidate, *, store=None):
    from packages.story_core.candidate_editing import assert_review_current, review_digest
    if candidate.review_binding:
        try:
            if store is not None:
                assert_review_current(store, candidate)
            elif (candidate.review_binding.get("state") != "checked"
                  or candidate.review_binding.get("result") != review_digest(candidate)):
                raise ValueError("candidate_review_required")
        except ValueError as exc:
            issue = problem(exc)
            return {"label": "需要重新检查", "tone": "warning", "message": issue["message"]}, [issue], True, False
    from packages.story_core.file_project_store import _assert_explicit_quality_blocking, _assert_auto_chapter_quality
    quality = deepcopy(candidate.quality_report or {})
    blocked = False
    try:
        _assert_explicit_quality_blocking(quality, operation=candidate.operation)
        _assert_explicit_quality_blocking(candidate.submission_payload.get("quality_report"), operation=candidate.operation)
        _assert_auto_chapter_quality(quality, operation=candidate.operation)
    except ValueError:
        blocked = True
    if blocked:
        return {"label": "需要修改", "tone": "danger", "message": "正文与已确认的故事事实存在冲突，暂时不能采用。"}, [problem("canon.hard_blocker"), *author_advice(quality)], True, False
    review = quality.get("review_result") or quality.get("writing_review") or {}
    warning = bool(quality.get("ok") is False or review.get("status") in {"warning", "needs_revision"} or quality.get("quality_warning"))
    if warning:
        return {"label": "请复核", "tone": "warning", "message": "正文有修改建议，请阅读后决定是否采用。"}, author_advice(quality) or [
            {"message": "这份候选仍有需要打磨的地方。", "suggestion": "请检查情节衔接和人物表现，再决定是否采用。", "tone": "warning"}
        ], False, True
    return {"label": "等待你确认", "tone": "success", "message": "请阅读正文。只有你确认后，才会加入正式章节。"}, [], False, False
