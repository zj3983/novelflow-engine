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
    "章节作用",
    "爽点来源",
    "主角进展",
    "冲突推进",
    "主要问题",
    "不爽原因",
    "设定冲突",
    "对话问题",
    "说明感问题",
    "下一版改法",
    "可写入提示词",
)

FORBIDDEN_TERMS = ("【货币：0铜】", "法师兄", "牙缝", "草屑")
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

    _extract_project_craft_read(body, sections)
    _detect_setting_conflicts(body, state, sections)
    _detect_dialogue_issues(body, sections)
    _detect_exposition_issues(body, sections)
    _detect_repetitive_combat(body, sections)
    _detect_missing_progress(body, sections)

    has_concrete_read = any(sections[key] for key in ("章节作用", "爽点来源", "主角进展", "冲突推进"))
    has_problem = any(sections[key] for key in ("主要问题", "设定冲突", "对话问题", "说明感问题"))
    if not sections["章节作用"]:
        sections["章节作用"].append("本章需要明确承担开局、过渡、兑现收益或抬高冲突中的一种作用。")
    if not sections["爽点来源"]:
        sections["爽点来源"].append("爽点还需要落到可见的进度、收益、领先或反差上。")
    if not sections["主角进展"]:
        sections["主角进展"].append("没有抽取到明确的经验、材料、任务或装备变化。")
    if not sections["冲突推进"]:
        sections["冲突推进"].append("冲突推进不够清楚，需要写出还差什么、卡在哪里、下一步怎么做。")
    if has_problem and not sections["不爽原因"]:
        sections["不爽原因"].append("爽点需要同时具备可见阻力、明确成本和阶段性收益，避免只剩信息陈列。")
    if not sections["下一版改法"] and (has_problem or not has_concrete_read):
        sections["下一版改法"].append("按目标-阻力-选择-代价-收益重排场景，让规则从动作和对话里露出。")
    if not sections["可写入提示词"] and (has_problem or not has_concrete_read):
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
        return "冲突由任务前置推动，材料差额天然制造下一场行动。"
    return "冲突推进较轻，需要检查是否有明确对手、前置条件或时间压力。"


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
        _add_issue(sections, "设定冲突", "Lv.1直接接转职任务过早，转职需要前置等级、导师或试炼条件。")
        _add_issue(sections, "主要问题", "等级进度与转职节点冲突。")
        _add_issue(sections, "不爽原因", "读者还没看到积累和前置条件，提前转职会像跳进度。")
        _add_issue(sections, "下一版改法", "把转职改成听到线索、看到大厅条件或领取前置试炼。")


def _extract_project_craft_read(body: str, sections: dict[str, list[str]]) -> None:
    if _extract_project_craft_read_chinese(body, sections):
        return
    exp = _last_match(body, r"经验[:：]?(\d+/\d+)")
    hp = _last_match(body, r"生命[:：]?(\d+/\d+)")
    mp = _last_match(body, r"法力[:：]?(\d+/\d+)")
    durability = _first_match(body, r"新手法杖(\d+/\d+)")
    venom = _extract_count(body, "灰狼毒腺")
    pelt = _extract_count(body, "粗糙狼皮")
    quest_need = _extract_count(body, "提交灰狼毒腺")
    has_drop_boost = "掉落判定×1000" in body
    has_protocol = "底层协议校验通过" in body
    has_seed = "混沌之种：未解析" in body

    if exp or venom is not None or pelt is not None:
        parts = []
        if exp:
            parts.append(f"经验{exp}")
        if hp:
            parts.append(f"生命{hp}")
        if mp:
            parts.append(f"法力{mp}")
        if durability:
            parts.append(f"新手法杖{durability}")
        if venom is not None:
            parts.append(f"灰狼毒腺{venom}")
        if pelt is not None:
            parts.append(f"粗糙狼皮{pelt}")
        _add_issue(sections, "主角进展", "本章进展已经落到具体账本：" + "，".join(parts) + "。")

    if "清道夫委托" in body and quest_need:
        if venom is not None and quest_need > venom:
            _add_issue(sections, "冲突推进", f"清道夫委托前置任务需要{quest_need}份灰狼毒腺，当前毒腺{venom}，还差{quest_need - venom}份，下一章目标清楚。")
        else:
            _add_issue(sections, "冲突推进", f"清道夫委托前置任务需要{quest_need}份灰狼毒腺，下一步条件已经露出。")

    if has_drop_boost:
        _add_issue(sections, "爽点来源", "掉落判定×1000已经露出，爽点来自隐藏优势被主角确认，但还没有公开暴露。")
    if has_protocol or has_seed:
        _add_issue(sections, "章节作用", "本章承担开局验证作用：现实压力、游戏身份、五只灰狼样本和混沌之种异常都已经落地。")
    if exp and venom is not None and quest_need and quest_need > venom:
        _add_issue(sections, "下一版改法", f"下一章先承接空蓝和耐久压力，等法力回复后补齐{quest_need - venom}份灰狼毒腺，再处理清道夫委托。")
        _add_issue(sections, "可写入提示词", f"承接章末账本：经验{exp}、灰狼毒腺{venom}、清道夫委托还差{quest_need - venom}份，不要跳到转职或高阶任务。")


def _extract_project_craft_read_chinese(body: str, sections: dict[str, list[str]]) -> bool:
    if not any(token in body for token in ("经验", "生命", "法力", "背包", "清道夫委托", "后坡巡查")):
        return False

    exp = _last_match(body, r"经验[：:]?\s*(\d+\s*/\s*\d+)")
    hp = _last_match(body, r"生命[：:]?\s*(\d+\s*/\s*\d+)")
    mp = _last_match(body, r"法力[：:]?\s*(\d+\s*/\s*\d+)")
    durability = _last_match(body, r"新手法杖[：:]?\s*(\d+\s*/\s*\d+)")
    backpack_line = _last_match(body, r"背包[：:]\s*([^\n。]+)")

    inventory: dict[str, int] = {}
    if backpack_line:
        for item, count in re.findall(r"([\u4e00-\u9fffA-Za-z0-9_]+)\s*[×xX*]\s*(\d+)", backpack_line):
            inventory[item] = int(count)
    for item, unit in (("灰狼毒腺", "份"), ("粗糙狼皮", "张")):
        count = _last_chinese_item_count(body, item, unit)
        if count is not None and item not in inventory:
            inventory[item] = count
    if "清道夫委托已完成" in body and "灰狼毒腺" not in inventory:
        inventory["灰狼毒腺"] = 0

    parts: list[str] = []
    if exp:
        parts.append(f"经验{exp.replace(' ', '')}")
    if hp:
        parts.append(f"生命{hp.replace(' ', '')}")
    if mp:
        parts.append(f"法力{mp.replace(' ', '')}")
    if durability:
        parts.append(f"新手法杖{durability.replace(' ', '')}")
    for item in ("灰狼毒腺", "粗糙狼皮", "小法力药水"):
        if item in inventory:
            parts.append(f"{item}{inventory[item]}")
    if parts:
        _add_issue(sections, "主角进展", "本章进展落到章末账本：" + "，".join(parts) + "。")

    if "清道夫委托已完成" in body:
        _add_issue(sections, "章节作用", "本章兑现第一章留下的清道夫委托：补齐毒腺、领取30铜，再把收益拆成修法杖、蓝药和后坡押金。")
        _add_issue(sections, "爽点来源", "爽点来自隐藏爆率带来的任务领先，但表面上只像会挑残血、会省耐久和运气好。")

    patrol_progress = _last_match(body, r"后坡巡查[：:]\s*(\d+\s*/\s*\d+)")
    if patrol_progress:
        _add_issue(sections, "章节作用", f"本章把后坡巡查推进到{patrol_progress.replace(' ', '')}，同时保留血蓝、药水和钱袋压力。")

    quest_need = _last_chinese_item_count(body, "提交灰狼毒腺", "份") or _last_numeric_item_count(body, "提交灰狼毒腺")
    if patrol_progress and patrol_progress.replace(" ", "") != "3/3":
        _add_issue(
            sections,
            "冲突推进",
            f"后坡巡查卡在{patrol_progress.replace(' ', '')}：章末血蓝低、药水用完、钱袋为空，下一步必须先补给或等恢复，再进第一格内侧刻标记。",
        )
        _add_issue(
            sections,
            "可写入提示词",
            f"下一章承接：夜烬仍是Lv.1，后坡巡查{patrol_progress.replace(' ', '')}，钱袋空，血蓝不足；先解决补给，再完成最后一段。",
        )
    elif "后坡巡查未登记" in body or ("失败不退押金" in body and "倒木" in body):
        _add_issue(
            sections,
            "冲突推进",
            "冲突已经从清道夫委托转到后坡巡查：押金已交、钱袋归零、血蓝未满、倒木旁两只狼卡路，下一步要等蓝后摸路牌碎片。",
        )
    elif quest_need and inventory.get("灰狼毒腺", 0) < quest_need:
        missing = quest_need - inventory.get("灰狼毒腺", 0)
        _add_issue(sections, "冲突推进", f"清道夫委托需要{quest_need}份灰狼毒腺，当前灰狼毒腺{inventory.get('灰狼毒腺', 0)}，还差{missing}份，下一步目标清楚。")
        _add_issue(sections, "下一版改法", f"下一章先承接空蓝和耐久压力，等法力恢复后补齐{missing}份灰狼毒腺，再处理清道夫委托。")
    elif "清道夫委托" in body:
        _add_issue(sections, "冲突推进", "清道夫委托作为本章前置任务推动行动，材料、修理费和药水价格共同限制下一步。")

    if "掉落判定×1000" in body:
        _add_issue(sections, "爽点来源", "掉落判定×1000仍只对夜烬可见，旁人只能从排队、残血捡漏和运气好来误判。")
    elif "混沌之种" in body:
        _add_issue(sections, "爽点来源", "混沌之种异常仍只对夜烬可见，旁人只能从排队、残血捡漏和运气好来误判。")

    if "后坡巡查未登记" in body:
        _add_issue(sections, "可写入提示词", "下一章承接：夜烬仍是Lv.1，钱袋0铜，法力12/60，后坡巡查未登记；先等蓝，再试倒木旁路牌碎片。")
    return True


def _last_numeric_item_count(text: str, label: str) -> int | None:
    values = [int(match.group(1)) for match in re.finditer(rf"{re.escape(label)}\s*[×xX*]\s*(\d+)", text)]
    return values[-1] if values else None


def _last_chinese_item_count(text: str, label: str, unit: str) -> int | None:
    pattern = rf"{re.escape(label)}\s*([零一二三四五六七八九十两\d]+)\s*{re.escape(unit)}"
    values: list[int] = []
    for match in re.finditer(pattern, text):
        prefix = text[max(0, match.start() - 8) : match.start()]
        if "获得" in prefix:
            continue
        raw = match.group(1)
        parsed = int(raw) if raw.isdigit() else _parse_simple_chinese_number(raw)
        if parsed is not None:
            values.append(parsed)
    return values[-1] if values else None


def _parse_simple_chinese_number(value: str) -> int | None:
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value.isdigit():
        return int(value)
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        tens = digits.get(left, 1 if not left else 0)
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return digits.get(value)


def _detect_dialogue_issues(body: str, sections: dict[str, list[str]]) -> None:
    quoted = re.findall(r"[\"“](.*?)[\"”]", body)
    short_quotes = [quote for quote in quoted if len(quote.strip()) <= 2]
    if len(short_quotes) >= 2:
        _add_issue(sections, "对话问题", "连续省略回答过多，不像角色在交换目标、价格或风险。")
        _add_issue(sections, "主要问题", "对话只剩应答，没有推动选择。")
        _add_issue(sections, "下一版改法", "让每句对话至少带出一个态度、条件、价格或误解。")
        _add_issue(sections, "可写入提示词", "避免连续“行/好/嗯”式省略回答，把回答扩成带动作和信息量的角色回应。")


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def _last_match(text: str, pattern: str) -> str:
    matches = list(re.finditer(pattern, text))
    return matches[-1].group(1) if matches else ""


def _extract_count(text: str, label: str) -> int | None:
    patterns = (
        rf"{re.escape(label)}[×xX]?(\d+)",
        rf"{re.escape(label)}([一二三四五六七八九十]+)份",
        rf"{re.escape(label)}([一二三四五六七八九十]+)张",
    )
    values: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            prefix = text[max(0, match.start() - 4) : match.start()]
            if "提交" in prefix:
                continue
            raw = match.group(1)
            parsed = int(raw) if raw.isdigit() else _chinese_number(raw)
            if parsed is not None:
                values.append((match.start(), parsed))
    return max(values, key=lambda item: item[0])[1] if values else None


def _chinese_number(value: str) -> int | None:
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if value.startswith("十") and len(value) == 2:
        return 10 + digits.get(value[1], 0)
    if value.endswith("十") and len(value) == 2:
        return digits.get(value[0], 0) * 10
    if "十" in value and len(value) == 3:
        return digits.get(value[0], 0) * 10 + digits.get(value[2], 0)
    return digits.get(value)


def _detect_exposition_issues(body: str, sections: dict[str, list[str]]) -> None:
    hits = [term for term in FORBIDDEN_TERMS if term in body]
    for term in hits:
        _add_issue(sections, "说明感问题", f"正文出现{term}，说明感过重或命中禁用表达。")
    if hits:
        _add_issue(sections, "主要问题", "禁用表达直接进入正文。")
        _add_issue(sections, "不爽原因", "信息被贴出来而不是被主角看见、判断和使用。")
        _add_issue(sections, "下一版改法", "把生硬提示改成钱包、背包、NPC报价或角色能直接使用的界面反馈。")
        _add_issue(sections, "可写入提示词", "禁用【货币：0铜】等生硬提示，改写成角色可见的资源反馈。")


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
        _add_issue(sections, "不爽原因", "没有可见收益或新条件，章节读完容易像原地打转。")
        _add_issue(sections, "下一版改法", "补出至少一个可记账变化：材料、经验、任务阶段、装备耐久或NPC态度。")
        _add_issue(sections, "可写入提示词", "章节末必须写清本章新增收益、剩余缺口和下一步行动。")


def _add_issue(sections: dict[str, list[str]], key: str, message: str) -> None:
    if message not in sections[key]:
        sections[key].append(message)
