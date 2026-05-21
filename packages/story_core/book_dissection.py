from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = "book-dissection/v1"

REFERENCE_SECTION_KEYS = (
    "章节作用",
    "爽点来源",
    "主角进展",
    "冲突推进",
    "对话功能",
    "节奏拆解",
    "结尾钩子",
    "可学习写法",
    "不能照抄",
)

PROJECT_SECTION_KEYS = (
    "主要问题",
    "不爽原因",
    "设定冲突",
    "对话问题",
    "说明感问题",
    "下一版改法",
    "可写入提示词",
)

FORBIDDEN_TERMS = ("【货币：0铜】", "怪物面板", "法师兄", "牙缝", "草屑")
COMBAT_TERMS = ("攻击", "出手", "挥", "砍", "刺", "命中", "伤害", "击杀", "刷新")
PROGRESS_TERMS = ("获得", "升级", "完成", "交付", "解锁", "材料", "经验", "铜", "任务", "装备")


def dissect_reference_text(text: str, *, genre: str = "", focus: str = "") -> dict[str, Any]:
    body = _validate_text(text)
    lines = _content_lines(body)
    sections = _empty_sections(REFERENCE_SECTION_KEYS)

    dialogue_lines = _dialogue_lines(lines)
    task_lines = [line for line in lines if _has_any(line, ("任务", "委托", "材料", "面板", "等级", "掉落"))]
    combat_lines = [line for line in lines if _has_any(line, COMBAT_TERMS)]

    sections["章节作用"].append(_chapter_function(lines, task_lines))
    sections["爽点来源"].append(_pleasure_source(body, task_lines, combat_lines))
    sections["主角进展"].append(_protagonist_progress(task_lines, body))
    sections["冲突推进"].append(_conflict_movement(combat_lines, task_lines))
    sections["对话功能"].append(_dialogue_function(dialogue_lines))
    sections["节奏拆解"].append(_pacing_read(lines, dialogue_lines, combat_lines))
    sections["结尾钩子"].append(_ending_hook(lines))
    sections["可学习写法"].append(_learnable_method(genre, focus, task_lines, dialogue_lines))
    sections["不能照抄"].append("保留结构思路，不照搬人物名、任务名、句式节奏和具体桥段。")

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "reference",
        "genre": genre,
        "focus": focus,
        "sections": sections,
    }


def diagnose_project_chapter(project_context: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(chapter, Mapping):
        raise ValueError("chapter_required")

    body = _validate_chapter_body(chapter)
    context = _as_dict(project_context)
    state = _as_dict(context.get("state"))
    sections = _empty_sections(PROJECT_SECTION_KEYS)

    _detect_setting_conflicts(body, state, sections)
    _detect_dialogue_issues(body, sections)
    _detect_exposition_issues(body, sections)
    _detect_repetitive_combat(body, sections)
    _detect_missing_progress(body, sections)

    if not sections["主要问题"]:
        sections["主要问题"].append("未发现硬性错误，但仍需要检查本章目标、成本和收益是否落到正文动作里。")
    if not sections["不爽原因"]:
        sections["不爽原因"].append("爽点需要同时具备可见阻力、明确成本和阶段性收益，避免只剩信息陈列。")
    if not sections["设定冲突"]:
        sections["设定冲突"].append("暂未命中常见硬设定冲突。")
    if not sections["对话问题"]:
        sections["对话问题"].append("暂未命中过短或重复对话问题。")
    if not sections["说明感问题"]:
        sections["说明感问题"].append("暂未命中面板直贴或后台术语问题。")
    if not sections["下一版改法"]:
        sections["下一版改法"].append("按目标-阻力-选择-代价-收益重排场景，让规则从动作和对话里露出。")
    if not sections["可写入提示词"]:
        sections["可写入提示词"].append("重写时保留本章事实，只把说明句改成可见动作、界面反馈和角色问答。")

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "project",
        "chapter_number": chapter.get("chapter_number"),
        "chapter_title": chapter.get("chapter_title", ""),
        "sections": sections,
    }


def _validate_text(text: str) -> str:
    if not text or not text.strip():
        raise ValueError("text_required")
    if len(text) > 50000:
        raise ValueError("text_too_long")
    return text.strip()


def _validate_chapter_body(chapter: Mapping[str, Any]) -> str:
    body = chapter.get("body")
    if body is None:
        raise ValueError("body_required")
    if not isinstance(body, str):
        raise ValueError("body_must_be_string")
    if not body.strip():
        raise ValueError("body_required")
    if len(body) > 50000:
        raise ValueError("text_too_long")
    return body.strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _empty_sections(keys: tuple[str, ...]) -> dict[str, list[str]]:
    return {key: [] for key in keys}


def _content_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _dialogue_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "：" in line or ":" in line or "\"" in line or "“" in line]


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _chapter_function(lines: list[str], task_lines: list[str]) -> str:
    if task_lines:
        return "本段用任务、材料或界面信息给章节建立可执行目标。"
    return f"本段承担场景展示和人物状态交代，共{len(lines)}个有效段落。"


def _pleasure_source(body: str, task_lines: list[str], combat_lines: list[str]) -> str:
    if task_lines and combat_lines:
        return "爽点来自先判断目标再动手，战斗收益和任务进度形成闭环。"
    if task_lines:
        return "爽点来自任务条件、资源差额和下一步收益的清晰可见。"
    if "落单" in body or "绕开" in body:
        return "爽点来自主角避开正面对抗，用选择和时机降低风险。"
    return "爽点来自人物做出可辨认选择，而不是作者直接宣布结果。"


def _protagonist_progress(task_lines: list[str], body: str) -> str:
    if task_lines:
        return f"主角进展被压到具体事项上：{task_lines[-1][:40]}。"
    if _has_any(body, PROGRESS_TERMS):
        return "主角有收益或状态变化，但还需要把数量和代价写清。"
    return "主角进展偏隐性，学习时应补出本章得到什么、失去什么。"


def _conflict_movement(combat_lines: list[str], task_lines: list[str]) -> str:
    if combat_lines:
        return "冲突从观察目标推进到出手，适合学习小阻力推动小收益。"
    if task_lines:
        return "冲突由任务门槛推动，材料差额天然制造下一场行动。"
    return "冲突推进较轻，需要检查是否有明确对手、门槛或时间压力。"


def _dialogue_function(dialogue_lines: list[str]) -> str:
    if dialogue_lines:
        return "对话承担询问、解释目标和暴露资源状态的功能。"
    return "对话较少，主要靠行动叙述推进。"


def _pacing_read(lines: list[str], dialogue_lines: list[str], combat_lines: list[str]) -> str:
    parts = []
    if combat_lines:
        parts.append("动作")
    if dialogue_lines:
        parts.append("问答")
    parts.append("信息")
    return f"节奏由{'-'.join(parts)}组成，{len(lines)}个短段适合快速建立目标。"


def _ending_hook(lines: list[str]) -> str:
    tail = lines[-1] if lines else ""
    if _has_any(tail, ("还差", "需要", "任务", "委托", "材料")):
        return "结尾钩子落在未完成的任务条件上，读者知道下一步要追什么。"
    return "结尾钩子应从最后一个未解决问题里提炼，避免只停在气氛。"


def _learnable_method(genre: str, focus: str, task_lines: list[str], dialogue_lines: list[str]) -> str:
    labels = "、".join(part for part in (genre, focus) if part) or "同类型"
    if task_lines:
        return f"{labels}可学习把任务条件拆成可见差额，再用行动补足差额。"
    if dialogue_lines:
        return f"{labels}可学习让对话服务选择、成本和下一步，而不是闲聊。"
    return f"{labels}可学习先给目标和限制，再写主角如何绕开限制。"


def _detect_setting_conflicts(body: str, state: dict[str, Any], sections: dict[str, list[str]]) -> None:
    ledger = _as_dict(state.get("progression_ledger"))
    protagonist = _as_dict(ledger.get("protagonist"))
    level = str(protagonist.get("level", ""))
    level_one = "Lv.1" in level or re.search(r"(?:^|[^0-9])1级", body)
    if level_one and "转职任务" in body:
        _add_issue(sections, "设定冲突", "Lv.1直接接转职任务过早，转职门槛需要前置等级、导师或试炼条件。")
        _add_issue(sections, "主要问题", "等级进度与转职节点冲突。")
        _add_issue(sections, "不爽原因", "读者还没看到积累和门槛，提前转职会像跳进度。")
        _add_issue(sections, "下一版改法", "把转职改成听到线索、看到大厅门槛或领取前置试炼。")


def _detect_dialogue_issues(body: str, sections: dict[str, list[str]]) -> None:
    quoted = re.findall(r"[\"“](.*?)[\"”]", body)
    short_quotes = [quote for quote in quoted if len(quote.strip()) <= 2]
    if len(short_quotes) >= 2:
        _add_issue(sections, "对话问题", "连续短句对话过短，不像角色在交换目标、价格或风险。")
        _add_issue(sections, "主要问题", "对话只剩应答，没有推动选择。")
        _add_issue(sections, "下一版改法", "让每句对话至少带出一个态度、条件、价格或误解。")
        _add_issue(sections, "可写入提示词", "避免连续“行/好/嗯”式短答，把短答扩成带动作和信息量的角色回应。")


def _detect_exposition_issues(body: str, sections: dict[str, list[str]]) -> None:
    hits = [term for term in FORBIDDEN_TERMS if term in body]
    for term in hits:
        _add_issue(sections, "说明感问题", f"正文出现{term}，说明感过重或命中禁用表达。")
    if hits:
        _add_issue(sections, "主要问题", "面板和禁用词直接进正文。")
        _add_issue(sections, "不爽原因", "信息被贴出来而不是被主角看见、判断和使用。")
        _add_issue(sections, "下一版改法", "把面板直贴改成钱包、背包、NPC报价或界面一闪而过的反馈。")
        _add_issue(sections, "可写入提示词", "禁用【货币：0铜】、怪物面板等直白面板词，改写成角色可见的资源反馈。")


def _detect_repetitive_combat(body: str, sections: dict[str, list[str]]) -> None:
    combat_hits = sum(body.count(term) for term in COMBAT_TERMS)
    distinct_hits = sum(1 for term in COMBAT_TERMS if term in body)
    if combat_hits >= 8 and distinct_hits <= 3:
        _add_issue(sections, "主要问题", "战斗动作重复，缺少距离、消耗、失误和收益变化。")
        _add_issue(sections, "不爽原因", "重复打怪会稀释收益感，读者看不到策略升级。")
        _add_issue(sections, "下一版改法", "每轮战斗至少改变一个变量：位置、蓝量、怪物反应、掉落或围观者判断。")


def _detect_missing_progress(body: str, sections: dict[str, list[str]]) -> None:
    if not _has_any(body, PROGRESS_TERMS):
        _add_issue(sections, "主要问题", "本章缺少明确进展，读者不容易判断主角推进了什么。")
        _add_issue(sections, "不爽原因", "没有可见收益或新门槛，章节读完容易像原地打转。")
        _add_issue(sections, "下一版改法", "补出至少一个可记账变化：材料、经验、任务阶段、装备耐久或NPC态度。")
        _add_issue(sections, "可写入提示词", "章节末必须写清本章新增收益、剩余缺口和下一步行动。")


def _add_issue(sections: dict[str, list[str]], key: str, message: str) -> None:
    if message not in sections[key]:
        sections[key].append(message)
