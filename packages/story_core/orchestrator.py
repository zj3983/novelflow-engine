from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import json
import re
import urllib.error
from time import perf_counter
from types import SimpleNamespace

from packages.story_core.agent_base import compact_list, compact_text, parse_json_message_content
from packages.story_core.chapter_governance import build_chapter_governance, governance_quality_gate, review_chapter_governance
from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.craft import is_game_story
from packages.story_core.generation_progress import report_generation_progress
from packages.story_core.http_retry import RetryConfig, post_json_with_retry
from packages.story_core.memory import (
    apply_post_chapter_updates,
    build_character_cards,
    build_foreshadowing,
    maybe_update_arc_recap,
    retrieve_relevant_memories,
)
from packages.story_core.models import DirectorDecision, StoryState, TimelineEvent, default_model_name
from packages.story_core.planner import build_conflict_summary, build_event_beat, compute_chapter_cadence, plan_next_outline
from packages.story_core.adversarial_cut_review import build_expression_patch_suggestions, review_adversarial_cuts
from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.prose_quality_review import review_prose_quality
from packages.story_core.prose_rule_review import CRITICAL_PROMPT_RULES, review_critical_prose_rules
from packages.story_core.prose_style_review import anti_ai_style_rules, review_prose_style, sanitize_prose_style
from packages.story_core.progression_lead_review import review_progression_lead
from packages.story_core.quality import validate_bundle
from packages.story_core.runtime import record_agent_runtime
from packages.story_core.runtime_config import get_runtime_strategy_settings, resolve_openai_runtime_settings
from packages.story_core.revision_safety import choose_best_revision, choose_best_segment_revision
from packages.story_core.segmented_writing import (
    FIRST_CHAPTER_FORBIDDEN,
    SegmentSpec,
    build_segment_prompt,
    build_segment_revision_prompt,
    build_segment_specs,
    build_style_adapt_prompt,
    merge_segment_outputs,
    review_segment_output,
    style_adapt_safety_check,
    trim_segment_to_contract,
)
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.spot_fix_patch import apply_spot_fix_patches
from packages.story_core.style_coach import build_style_guidance, enrich_performance_cards
from packages.story_core.web_game_author_craft import format_web_game_director_card, plain_writer_phrase
from packages.story_core.web_game_review import has_asserted_overreach, review_web_game_chapter, web_game_review_rules
from packages.story_core.writing_taskbook import (
    ensure_writing_taskbook,
    first_chapter_whole_body_contract,
    format_taskbook_prompt_section,
)
from packages.story_core.world_consistency_review import review_world_event_consistency
from packages.story_core.world_pulse import advance_world_pulse
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events
from packages.story_core.review_report import format_review_report
from packages.story_core.scene_contract_repair import build_scene_contract_repair_plan


VALID_CADENCES = {"urgent", "measured", "breathing"}
MIN_CHAPTER_CHARS = 4200
REGENERATION_MIN_CHARS = 3500
REGENERATION_FAST_MIN_CHARS = 3200
TARGET_CHAPTER_CHARS = "4200到5500字"


def _review_reports_enabled() -> bool:
    value = os.getenv("NOVEL_AUTOGROWTH_REVIEW_REPORTS", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _review_report_output_dir() -> Path:
    configured = os.getenv("NOVEL_AUTOGROWTH_REVIEW_REPORTS_DIR", "").strip()
    return Path(configured) if configured else Path("chapter_exports")


def _persist_review_report(chapter_number: int, body: str, writing_review: dict[str, Any]) -> Path | None:
    if not _review_reports_enabled():
        return None
    try:
        output_dir = _review_report_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"review_ch{int(chapter_number):04d}.md"
        output_path.write_text(
            format_review_report(writing_review, chapter_number=chapter_number, body_chars=len(str(body or ""))),
            encoding="utf-8",
        )
        return output_path
    except Exception:
        return None


def _extract_text_message(response: dict) -> str:
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    content = message.get("content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        return str(content.get("text", "")).strip()
    return str(content).strip()


def _chapter_char_count(text: str) -> int:
    return len("".join(text.split()))


def _scene_card_writing_protocol(scene_cards: list[dict[str, Any]] | None) -> str:
    """Compile scene cards into a reader-facing prose contract for the writer."""

    if not scene_cards:
        return "无 scene_cards：按 event_plan 写连续正文，但不得输出大纲、规则条目或后台字段。"
    lines = [
        "按 scene_cards 顺序写正文；每张卡必须成为一个可读场景或连续段落，不要写成规则解释。",
        "每个场景至少包含：地点、视角角色、行动选择、即时阻力、可见反馈和进入下一场的压力。",
        "第2章起若有命名NPC重点出场，必须在同一场里写清地点、服务/价格或前置条件、口吻/利益诉求、信息边界；NPC只按岗位知道柜台、库存、任务或修理记录。",
        "至少写一次外人误判：旁人只能看见排队、修理、买药、登记、刷怪或运气好，不能知道隐藏机制、完整掉落和主角账本。",
        "段首不要反复使用“这一次、下一刻、很快、片刻后、转眼、眼前”；多用动作、物件、队伍、价牌、背包格或NPC台词自然起段。",
    ]
    for index, card in enumerate(scene_cards, start=1):
        if not isinstance(card, dict):
            continue
        template_id = str(card.get("template_id") or card.get("scene_id") or "scene")
        location = str(card.get("location") or "当前场景")
        purpose = str(card.get("purpose") or "推进本章目标")
        conflict = str(card.get("conflict") or "形成场景阻力")
        must_show = compact_list(
            [str(item) for item in card.get("must_show", []) if str(item).strip()]
            if isinstance(card.get("must_show"), list)
            else [],
            max_items=8,
            item_chars=28,
        )
        must_not_explain = compact_list(
            [str(item) for item in card.get("must_not_explain", []) if str(item).strip()]
            if isinstance(card.get("must_not_explain"), list)
            else [],
            max_items=6,
            item_chars=32,
        )
        write_as = compact_list(
            [str(item) for item in card.get("write_as", []) if str(item).strip()]
            if isinstance(card.get("write_as"), list)
            else [],
            max_items=6,
            item_chars=28,
        )
        avoid = compact_list(
            [str(item) for item in card.get("avoid", []) if str(item).strip()]
            if isinstance(card.get("avoid"), list)
            else [],
            max_items=6,
            item_chars=32,
        )
        fact_locks = compact_list(
            [str(item) for item in card.get("fact_locks", []) if str(item).strip()]
            if isinstance(card.get("fact_locks"), list)
            else [],
            max_items=8,
            item_chars=36,
        )
        forbidden_items = [*must_not_explain, *avoid]
        lines.append(
            f"场景{index} [{template_id}] 地点：{location}；目的：{purpose}；阻力：{conflict}；"
            f"必须表面化：{'、'.join(must_show) if must_show else '地点、行动、反馈'}；"
            f"写法：{'、'.join(write_as) if write_as else '动作、界面、对话、环境反馈'}；"
            f"事实锁：{'、'.join(fact_locks) if fact_locks else '保持账本、面板、NPC可见信息不变'}；"
            f"禁止写成后台解释：{'、'.join(forbidden_items) if forbidden_items else '规则字段、审稿词、作者说明'}。"
        )
    return "\n".join(lines)


def _revision_forbidden_terms(review: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for card in plan.get("scene_cards", []) if isinstance(plan.get("scene_cards"), list) else []:
        if not isinstance(card, dict):
            continue
        raw_terms = card.get("must_not_explain", [])
        if isinstance(raw_terms, list):
            terms.extend(str(term).strip() for term in raw_terms if str(term).strip())
    review_text = json.dumps(review, ensure_ascii=False)
    for term in FIRST_CHAPTER_FORBIDDEN:
        if term in review_text and term not in terms:
            terms.append(term)
    if "第一章提前展开交易线" in review_text:
        for term in ("匿名寄售", "寄售成功", "上架成功", "成交", "到账", "手续费", "第一笔铜币落袋", "赵胖子", "盯盘", "商人"):
            if term not in terms:
                terms.append(term)
    if "第一章外部压力过早" in review_text:
        for term in ("白袍", "公会", "论坛", "清场", "后勤", "异常低价", "观察名单", "商人脚本"):
            if term not in terms:
                terms.append(term)
    for term in ("爽点", "钩子", "节奏", "读者", "网文规则", "生成", "审稿", "质量报告", "剧情需要", "下一阶段剧情"):
        if term in review_text and term not in terms:
            terms.append(term)
    return compact_list(terms, max_items=32, item_chars=24)


def _revision_fix_checklist(review: dict[str, Any]) -> list[str]:
    checklist: list[str] = []
    for item in [*review.get("issues", []), *review.get("revision_plan", [])]:
        text = str(item).strip()
        if text and text not in checklist:
            checklist.append(text)
    return compact_list(checklist, max_items=18, item_chars=180)


def _normalize_web_game_terms(body: str) -> str:
    """Keep reader-facing terminology stable while preserving numeric formulas."""
    normalized = body
    replacements = (
        ("1000倍爆率", "千倍爆率"),
        ("1000 倍爆率", "千倍爆率"),
        ("一千倍爆率", "千倍爆率"),
        ("放大了1000倍", "放大到了千倍"),
        ("放大 1000 倍", "放大到千倍"),
        ("放大1000倍", "放大到千倍"),
        ("提升了1000倍", "提升到了千倍"),
        ("提升1000倍", "提升到千倍"),
        ("乘以1000倍", "放大到千倍"),
    )
    for old, new in replacements:
        normalized = normalized.replace(old, new)
    return normalized


def _sanitize_generated_body(body: str) -> str:
    cleaned = _normalize_web_game_terms(sanitize_prose_style(body))
    cleaned = cleaned.replace("基准", "参照")
    replacements = {
        "施法前摇": "抬手那一下",
        "前摇": "抬手",
        "验证逻辑": "试出来的规矩",
        "验证路线": "下一步走法",
        "收益路径": "换东西的路",
        "收益曲线": "东西变多的样子",
        "撕扯判定": "狼爪撕过来",
        "伤害数字": "跳出的数值",
        "当前货币：0铜": "货币栏还是空的",
        "当前货币:0铜": "货币栏还是空的",
        "货币：0铜": "钱袋：空",
        "货币:0铜": "钱袋：空",
        "获得：30铜": "奖励栏还没亮",
        "获得:30铜": "奖励栏还没亮",
        "奖励三十铜": "奖励还没领取",
        "奖励30铜": "奖励还没领取",
        "扣除：30铜": "没有扣费",
        "扣除:30铜": "没有扣费",
        "逻辑": "规矩",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    # Some model/API combinations occasionally turn UI quotes or line breaks into
    # lone ASCII question marks. Remove only question marks embedded in CJK prose.
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff。！？】》])\?(?=[\u4e00-\u9fff【《])", "", cleaned)
    return cleaned


def _scene_cards_spend_resource(scene_cards: list[dict] | None, resource: str) -> bool:
    def visit(value: Any) -> bool:
        if isinstance(value, dict):
            cost_delta = value.get("cost_delta") if isinstance(value.get("cost_delta"), dict) else {}
            if int(cost_delta.get(resource) or 0) < 0:
                return True
            return any(visit(item) for item in value.values())
        if isinstance(value, list):
            return any(visit(item) for item in value)
        return False

    return visit(scene_cards or [])


def _scene_cards_need_npc_window(scene_cards: list[dict] | None) -> bool:
    for card in scene_cards or []:
        if not isinstance(card, dict):
            continue
        scene_id = str(card.get("scene_id") or card.get("template_id") or "")
        must_show = card.get("must_show") if isinstance(card.get("must_show"), list) else []
        must_text = " ".join(str(item) for item in must_show)
        if scene_id == "s4-c1-npc-service":
            return True
        if all(token in must_text for token in ("NPC地点", "服务内容", "信息边界")):
            return True
    return False


def _scene_cards_need_reality_skill_source(scene_cards: list[dict] | None) -> bool:
    for card in scene_cards or []:
        if not isinstance(card, dict):
            continue
        scene_id = str(card.get("scene_id") or card.get("template_id") or "")
        must_show = card.get("must_show") if isinstance(card.get("must_show"), list) else []
        if scene_id == "s1-c1-reality-entry" or "现实职业/技能来源" in {str(item) for item in must_show}:
            return True
    return False


def _body_has_reality_skill_source(body: str) -> bool:
    return any(term in body for term in ("风控", "测试员", "外包", "工作", "项目")) and any(
        term in body for term in ("概率", "流水", "模型", "漏洞", "规则")
    )


def _ensure_first_chapter_reality_skill_source(body: str, scene_cards: list[dict] | None) -> str:
    if not body or not _scene_cards_need_reality_skill_source(scene_cards) or _body_has_reality_skill_source(body):
        return body
    prefix = (
        "苏叶以前接过游戏外包测试员的活，白天照表点功能，晚上核对几笔小流水。"
        "那点工作经验没让他富起来，只让他习惯先看余额、先问价钱，再动手。\n\n"
    )
    return f"{prefix}{body.lstrip()}"


def _ensure_first_chapter_trigger_anchor(body: str) -> str:
    if not body:
        return body
    has_finger = any(token in body for token in ("千倍爆率", "混沌之种", "隐藏天赋", "爆率修正"))
    has_trigger = any(
        token in body
        for token in (
            "旧头盔",
            "异常邀请码",
            "神经接驳",
            "接驳",
            "协议异常",
            "角色创建",
            "创建角色",
            "登录入口",
            "登录界面",
            "开服倒计时",
            "触发条件",
            "底层日志",
            "灰色日志",
        )
    )
    if not has_finger or has_trigger:
        return body
    prefix = (
        "旧头盔接上电源时，登录界面先卡了一下。角落里闪过一行灰色日志："
        "底层协议校验通过，混沌之种：未解析。苏叶没急着点确认，只把这行字看完，才进入角色创建。\n\n"
    )
    return f"{prefix}{body.lstrip()}"


def _body_has_npc_window_surface(body: str) -> bool:
    return (
        any(term in body for term in ("药剂铺", "柜台", "柜台窗口", "职业大厅", "仓库", "铁匠铺", "任务牌", "价牌"))
        and any(term in body for term in ("服务", "价格", "前置", "条件", "只收", "报价", "收购"))
        and any(term in body for term in ("不问来源", "没追问", "不能看到", "只能看到", "只管", "不知道", "柜台规矩", "信息边界"))
    )


def _ensure_first_chapter_npc_window(body: str, scene_cards: list[dict] | None) -> str:
    if not body or not _scene_cards_need_npc_window(scene_cards) or _body_has_npc_window_surface(body):
        return body
    window = (
        "村口的任务牌旁边开着一个小柜台窗口，木牌上只写服务内容和前置条件：灰狼毒腺可以登记，"
        "补给价格另看柜台价牌。\n\n"
        "窗口后的NPC没抬头，只管把牌子扶正，不问来源，也不知道谁的背包里有多少材料。"
        "夜烬低声道：“先交一份，别的我再看看。”\n\n"
        "他只递出够数的一小包材料，剩下的重新扣进背包。窗口按牌价结了一笔，排队的人只当他运气不错。"
    )
    return f"{body.rstrip()}\n\n{window}"


def _sanitize_systemic_resource_contradictions(body: str, scene_cards: list[dict] | None) -> str:
    cleaned = body
    if _scene_cards_spend_resource(scene_cards, "mp"):
        for old in ("法力满格", "法力满", "满蓝", "法力充足"):
            cleaned = cleaned.replace(old, "法力只剩一截")
    if _scene_cards_spend_resource(scene_cards, "durability"):
        for old in ("法杖完好", "耐久没掉", "耐久未损"):
            cleaned = cleaned.replace(old, "法杖耐久发红")
    if _scene_cards_spend_resource(scene_cards, "hp"):
        for old in ("毫发无伤", "生命满", "血量满"):
            cleaned = cleaned.replace(old, "血量掉了一截")
    return cleaned


def _soften_repeated_paragraph_openers(body: str) -> str:
    parts = re.split(r"(\n\s*\n)", body.replace("\r", "\n"))
    counts: dict[str, int] = {}
    run_opener = ""
    run_count = 0
    prefixes = (
        "夜烬停了停，",
        "他把面板关掉，",
        "柜台前的人往前挪了一步，",
        "背包格子亮了一下，",
        "旁边有人低声抱怨，",
        "任务牌被风吹得轻轻一晃，",
        "钱袋在掌心沉了一下，",
        "法杖磕在石阶边，",
    )
    prefix_index = 0
    softened: list[str] = []

    for part in parts:
        stripped = part.strip()
        if not stripped or part.startswith("\n"):
            softened.append(part)
            continue
        match = re.match(r"([\u4e00-\u9fff]{2})", stripped.lstrip("“‘「『【("))
        opener = match.group(1) if match else ""
        if opener:
            counts[opener] = counts.get(opener, 0) + 1
            if opener == run_opener:
                run_count += 1
            else:
                run_opener = opener
                run_count = 1
        needs_prefix = bool(opener and (counts.get(opener, 0) > 6 or run_count >= 3))
        if needs_prefix:
            prefix = prefixes[prefix_index % len(prefixes)]
            prefix_index += 1
            leading = part[: len(part) - len(part.lstrip())]
            part = f"{leading}{prefix}{part.lstrip()}"
            run_opener = prefix[:2]
            run_count = 1
        softened.append(part)
    return "".join(softened)


def _limit_metaphor_markers(body: str, *, max_like: int = 2) -> str:
    if not body:
        return body
    cleaned = body.replace("仿佛", "").replace("犹如", "").replace("宛如", "")
    seen = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal seen
        seen += 1
        return "像" if seen <= max_like else "跟"

    return re.sub("像", repl, cleaned)


def _sanitize_report_style_terms(body: str) -> str:
    replacements = {
        "数据模型": "账本记录",
        "收益曲线": "东西变多的样子",
        "路线规划": "路线选择",
        "控制变量": "先少做一步",
        "计算力": "注意力",
        "成本曲线": "花费变化",
        "衰减曲线": "声音慢慢变低",
        "测试用例": "旧活儿",
        "数据流": "暖流",
        "概率": "运气",
        "变量": "麻烦",
        "边界": "规矩",
        "溢出": "多出来",
        "意味着": "",
        "测试员的职业病": "以前那点测试经验",
        "把收益拉到最高": "多拿一点是一点",
        "风控": "记录",
        "模型": "说法",
        "仇恨值": "灰狼的注意",
        "游戏世界的运转规矩很简单：资源、交换、生存。没有多余的情绪，也没有多余的废话。": "老葛把铜币扫进抽屉，又低头去擦下一件装备。",
    }
    cleaned = body
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    return cleaned


def _ensure_protagonist_speech(body: str, protagonist: str = "夜烬") -> str:
    if not body or protagonist not in body:
        return body
    if re.search(rf"{re.escape(protagonist)}[^。！？\n]{{0,40}}(?:低声|小声)?(?:说|问|道|开口)", body):
        return body
    line = f'{protagonist}把背包扣上，低声说：“先修杖，再去坡口试一只。”'
    paragraphs = body.rstrip().split("\n\n")
    if len(paragraphs) >= 2:
        paragraphs.insert(-1, line)
        return "\n\n".join(paragraphs)
    return f"{body.rstrip()}\n\n{line}"


def _insert_before_last_paragraph(body: str, line: str) -> str:
    paragraphs = body.rstrip().split("\n\n")
    if len(paragraphs) >= 2:
        paragraphs.insert(-1, line)
        return "\n\n".join(paragraphs)
    return f"{body.rstrip()}\n\n{line}"


def _ensure_web_game_outsider_misread(body: str, chapter_number: int) -> str:
    if chapter_number < 2 or not body or "夜烬" not in body:
        return body
    if any(token in body for token in ("路线熟", "运气好", "只当他", "只以为他", "旁人只看见", "普通玩家只看见")):
        return body
    line = (
        "队尾有个玩家看见夜烬从修理铺出来，又往药剂铺那边去，顺嘴嘀咕了一句："
        "“这人路线挺熟啊，估计也就运气好，多凑了两份材料。”"
        "夜烬听见了，没回头，只把钱袋口按紧。别人看见的是排队、修杖和买药，看不见他背包里每一格怎么变。"
    )
    return _insert_before_last_paragraph(body, line)


def _ensure_web_game_emotion_anchors(body: str, chapter_number: int) -> str:
    if chapter_number < 2 or not body or "夜烬" not in body:
        return body
    anchors = [
        "夜烬看着钱袋里的铜币少下去，手指停了一下。十五铜修杖，十铜买药，花出去的时候不疼是假的，但法杖真断在坡上，后面只会更亏。",
        "他把第二瓶药水塞进背包时，肩膀慢慢松了一点，又很快绷回去。现实里的二十七块六还在那儿，游戏里这点铜币只能让他多走一步。",
    ]
    existing_keys = {
        "十五铜修杖": anchors[0],
        "十铜买药": anchors[0],
        "二十七块六": anchors[1],
        "27.60": anchors[1],
    }
    result = body
    for anchor in anchors:
        if not any(key in result and value == anchor for key, value in existing_keys.items()):
            result = _insert_before_last_paragraph(result, anchor)
    return result


def _ensure_web_game_npc_service_boundary(body: str, chapter_number: int) -> str:
    if chapter_number < 2 or not body or "夜烬" not in body:
        return body
    has_full_boundary = (
        any(name in body for name in ("修理匠老葛", "药剂师洛婶", "老葛", "洛婶"))
        and any(place in body for place in ("修理铺", "药剂铺", "柜台"))
        and any(price in body for price in ("十五铜", "十铜", "五铜", "价格", "价牌"))
        and any(limit in body for limit in ("不知道", "只看", "只按", "不问"))
    )
    if has_full_boundary:
        return body
    line = (
        "修理铺门口的铁砧牌子被擦得发亮。老葛接过新手法杖，只看裂纹和耐久，开口就是十五铜，"
        "不问夜烬从哪儿弄来的毒腺，也不管他刚才交了什么任务。对老葛来说，玩家递装备、付钱、拿走修好的东西，"
        "这事就到这里。"
    )
    return _insert_before_last_paragraph(body, line)


def _sanitize_chapter_output(body: str, *, chapter_number: int, scene_cards: list[dict] | None = None) -> str:
    cleaned = _sanitize_first_chapter_scope(_sanitize_generated_body(body), chapter_number)
    cleaned = _sanitize_systemic_resource_contradictions(cleaned, scene_cards)
    if chapter_number == 1:
        cleaned = _ensure_first_chapter_trigger_anchor(cleaned)
        cleaned = _ensure_first_chapter_reality_skill_source(cleaned, scene_cards)
        cleaned = _ensure_first_chapter_npc_window(cleaned, scene_cards)
    cleaned = _sanitize_report_style_terms(cleaned)
    cleaned = _limit_metaphor_markers(cleaned)
    cleaned = _ensure_protagonist_speech(cleaned)
    cleaned = _ensure_web_game_outsider_misread(cleaned, chapter_number)
    cleaned = _ensure_web_game_emotion_anchors(cleaned, chapter_number)
    cleaned = _ensure_web_game_npc_service_boundary(cleaned, chapter_number)
    return _soften_repeated_paragraph_openers(cleaned)


def _sanitize_first_chapter_scope(body: str, chapter_number: int) -> str:
    if chapter_number != 1 or not body:
        return body
    sentence_block_terms = (
        "匿名寄售",
        "寄售成功",
        "上架成功",
        "成交",
        "到账",
        "手续费",
        "第一笔铜币落袋",
        "赵胖子",
        "盯盘",
        "白袍",
        "公会",
        "论坛",
        "清场",
        "后勤",
        "异常低价",
        "观察名单",
        "商人脚本",
        "锁定坐标",
        "精确坐标",
        "精准定位",
        "现实身份",
        "隐藏天赋",
    )
    service_closure_terms = (
        "交清道夫委托",
        "提交清道夫委托",
        "任务完成",
        "任务已完成",
        "奖励三十铜",
        "奖励30铜",
        "领取三十铜",
        "领取30铜",
        "获得：30铜",
        "获得:30铜",
        "扣除：30铜",
        "扣除:30铜",
        "当前货币：0铜",
        "当前货币:0铜",
        "修理铺",
        "修理匠",
        "修装备",
        "修理装备",
        "修满",
        "修完耐久",
        "买两瓶",
        "初级法力药水",
        "两瓶药水",
        "买药水",
        "购买药水",
    )
    npc_alias_groups = (
        ("灰烬村村长", "村长"),
        ("药剂师洛婶", "洛婶"),
        ("职业导师艾伦", "艾伦"),
        ("仓库管理员铁栓", "铁栓"),
        ("修理匠老葛", "老葛"),
    )
    kept_npc_group: tuple[str, ...] | None = None

    def piece_npc_groups(piece: str) -> list[tuple[str, ...]]:
        return [group for group in npc_alias_groups if any(alias in piece for alias in group)]

    def is_negated(piece: str, term: str) -> bool:
        index = piece.find(term)
        if index < 0:
            return False
        window = piece[max(0, index - 4) : index]
        return any(negator in window for negator in ("不", "未", "没", "没有", "别"))

    kept_paragraphs: list[str] = []
    for paragraph in re.split(r"\n{2,}", body):
        pieces = re.findall(r"[^。！？\n]+[。！？]?", paragraph)
        kept: list[str] = []
        for piece in pieces:
            if any(term in piece for term in sentence_block_terms):
                continue
            if any(term in piece and not is_negated(piece, term) for term in service_closure_terms):
                continue
            groups = piece_npc_groups(piece)
            if groups:
                if kept_npc_group is None:
                    kept_npc_group = groups[0]
                elif any(group != kept_npc_group for group in groups):
                    continue
            kept.append(piece)
        cleaned = "".join(kept).strip()
        if cleaned:
            kept_paragraphs.append(cleaned)
    sanitized = "\n\n".join(kept_paragraphs).strip()
    if sanitized and (
        ("掉落判定×1000" in sanitized or "千倍爆率" in sanitized or "混沌之种" in sanitized)
        and not any(term in sanitized for term in ("元素回廊", "技能书", "路线", "前置", "条件", "快一步", "领先"))
    ):
        sanitized = (
            sanitized.rstrip()
            + "\n\n夜烬没有急着把材料全交出去。他站在村口，看见职业导师那边的木牌被玩家围住，"
            "上面写着基础技能书和后坡登记的价钱。别人还在坡下等第一份毒腺，他的背包已经快满了。"
            "他先把多余材料压在背包底下，只交够一份任务。旁人看见的只是普通结算，看不见他还留着下一轮的底。"
            "普通玩家还在等掉落，他已经能先一步去问技能书和入口前置任务。"
        )
    if sanitized and _chapter_char_count(sanitized) < REGENERATION_FAST_MIN_CHARS and (
        "掉落判定×1000" in sanitized or "千倍爆率" in sanitized or "混沌之种" in sanitized
    ):
        sanitized = (
            sanitized.rstrip()
            + "\n\n他重新拉开面板。\n\n"
            "等级还是Lv.1，钱袋仍是空的。血条、法力和法杖耐久都不好看，"
            "背包格子却已经被低级掉落挤得发红。别人打一轮只攒两三份材料，他已经能凑出一份清道夫委托。\n\n"
            "夜烬把面板关掉，先没往柜台挤。他看了一眼坡下的人群，又看了一眼职业导师门口排起的队。"
            "任务奖励、修理费和技能书价钱都要算清楚，下一步才不会把刚到手的铜币花错。"
        )
    return sanitized or body


def _priority_world_facts(facts: list[str], *, max_items: int, item_chars: int) -> list[str]:
    priority_tokens = (
        "NPC：",
        "NPC规则",
        "任务网络",
        "任务类型",
        "任务奖励规则",
        "服务器阶段",
        "服务器频道",
        "寄售限制",
        "地图生态",
        "黄金三章",
        "背景预算",
        "玩家生态",
        "信息可见",
        "世界反应阶梯",
        "第1章背景节拍",
        "经济规则",
        "交易行",
        "公会",
    )
    priority = [fact for fact in facts if any(token in fact for token in priority_tokens)]
    others = [fact for fact in facts if fact not in priority]
    return compact_list([*priority, *others], max_items=max_items, item_chars=item_chars)


def _story_snapshot(story: StoryState) -> dict:
    latest = story.chapter_summaries[-1] if story.chapter_summaries else None
    memory_query = " ".join(
        [
            story.outline,
            latest.next_focus if latest else "",
            latest.summary if latest else "",
            " ".join(story.world_facts[:8]),
        ]
    )
    relevant_memories = retrieve_relevant_memories(story, memory_query, limit=6)
    return {
        "outline": compact_text(story.outline, 700),
        "genre": story.genre,
        "style": story.style,
        "current_chapter": story.current_chapter,
        "author_constraints": compact_list(story.author_constraints, max_items=16, item_chars=180),
        "world_facts": _priority_world_facts(story.world_facts, max_items=42, item_chars=190),
        "progression_ledger": story.progression_ledger,
        "relevant_memories": [
            {
                "chapter_number": entry.chapter_number,
                "chapter_title": entry.chapter_title,
                "summary": compact_text(entry.summary, 160),
                "tags": entry.tags[:8],
                "characters": entry.characters[:6],
                "locations": entry.locations[:6],
                "factions": entry.factions[:6],
                "quests": entry.quests[:6],
                "items": entry.items[:6],
                "unresolved_threads": compact_list(entry.unresolved_threads, max_items=3, item_chars=90),
            }
            for entry in relevant_memories
        ],
        "arc_recaps": [
            {
                "range": f"{recap.start_chapter}-{recap.end_chapter}",
                "recap": compact_text(recap.recap, 220),
                "key_threads": compact_list(recap.key_threads, max_items=6, item_chars=90),
                "open_threads": compact_list(recap.open_threads, max_items=6, item_chars=90),
                "character_changes": compact_list(recap.character_changes, max_items=6, item_chars=90),
                "ledger_snapshot": recap.ledger_snapshot,
            }
            for recap in story.arc_recaps[-3:]
        ],
        "latest_summary": compact_text(latest.summary if latest else "", 200),
        "latest_facts": compact_list(latest.facts if latest else [], max_items=8, item_chars=130),
        "latest_threads": compact_list(latest.unresolved_threads if latest else [], max_items=3, item_chars=70),
        "current_focus": compact_text(latest.next_focus if latest else "", 120),
        "world_pulse": story.progression_ledger.get("world_pulse", {})
        if isinstance(story.progression_ledger, dict)
        else {},
        "visibility_inbox": story.progression_ledger.get("visibility_inbox", [])[-12:]
        if isinstance(story.progression_ledger, dict) and isinstance(story.progression_ledger.get("visibility_inbox"), list)
        else [],
        "characters": [
            {
                "name": c.name,
                "game_id": c.game_id,
                "game_panel": c.game_panel.model_dump(),
                "role": c.role,
                "goals": compact_list(c.goals, max_items=3, item_chars=90),
                "emotion": c.current_emotion,
                "location": compact_text(c.location, 80),
                "secrets": compact_list(c.secrets, max_items=3, item_chars=80),
                "memory": compact_list(c.memory, max_items=5, item_chars=120),
                "relationships": [
                    {
                        "target": relation.target,
                        "bond": compact_text(relation.bond, 80),
                        "trust": relation.trust,
                        "tension": relation.tension,
                    }
                    for relation in list(c.relationships.values())[:4]
                ],
            }
            for c in story.characters[:6]
            if c.lifecycle_state == "active" and not c.frozen
        ],
        "character_cards": build_character_cards(story)[:6],
    }


def _normalize_moves(raw_moves: object) -> list[dict]:
    moves: list[dict] = []
    if not isinstance(raw_moves, list):
        return moves
    for item in raw_moves[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        moves.append(
            {
                "name": name,
                "goal": compact_text(str(item.get("goal", "")).strip() or "推进当前主线", 80),
                "emotion": str(item.get("emotion", "")).strip() or "alert",
                "action": compact_text(str(item.get("action", "")).strip() or "继续推进当前主线", 120),
                "priority": int(item.get("priority", 0) or 0),
                "new_character_candidates": compact_list(
                    item.get("new_character_candidates", []),
                    max_items=4,
                    item_chars=60,
                ),
            }
        )
    return moves


def _normalize_cadence(raw: object) -> str:
    cleaned = str(raw).strip().lower()
    if cleaned in VALID_CADENCES:
        return cleaned
    if any(word in cleaned for word in ("快", "急", "紧迫", "紧张", "urgent")):
        return "urgent"
    if any(word in cleaned for word in ("缓", "慢", "平稳", "从容", "breathing")):
        return "breathing"
    return "measured"


def _normalize_intent(raw_intent: object) -> dict:
    if not isinstance(raw_intent, dict):
        return {}
    return {
        "chapter_title": compact_text(str(raw_intent.get("chapter_title", "")).strip(), 60),
        "cadence": _normalize_cadence(raw_intent.get("cadence", "measured")),
        "next_focus": compact_text(str(raw_intent.get("next_focus", "")).strip(), 160),
        "primary_conflict": raw_intent.get("primary_conflict", {}) if isinstance(raw_intent.get("primary_conflict"), dict) else {},
        "secondary_conflict": raw_intent.get("secondary_conflict", {}) if isinstance(raw_intent.get("secondary_conflict"), dict) else {},
        "approved_new_characters": raw_intent.get("approved_new_characters", [])
        if isinstance(raw_intent.get("approved_new_characters", []), list)
        else [],
        "deferred_characters": raw_intent.get("deferred_characters", [])
        if isinstance(raw_intent.get("deferred_characters", []), list)
        else [],
        "rejected_characters": raw_intent.get("rejected_characters", [])
        if isinstance(raw_intent.get("rejected_characters", []), list)
        else [],
    }


def _normalize_event_plan(raw_event_plan: object, chapter_number: int, story: StoryState) -> dict:
    def _normalize_chapter_end_hook(raw_hook: object) -> dict[str, str | None] | None:
        if not isinstance(raw_hook, dict):
            return None
        hook_type = str(raw_hook.get("type", "")).strip() or None
        strength = str(raw_hook.get("strength", "")).strip().lower() or None
        content = compact_text(str(raw_hook.get("content", "")).strip(), 180)
        return {"type": hook_type, "strength": strength, "content": content}

    if not isinstance(raw_event_plan, dict):
        return {
            "chapter_number": chapter_number,
            "ordered_actions": [],
            "world_reactions": [],
            "exposition_beats": [],
            "npc_beats": [],
            "quest_beats": [],
            "location_beats": [],
            "explicit_chapter_end_hook": "",
            "chapter_end_hook": None,
            "author_constraints": list(story.author_constraints),
        }
    return {
        "chapter_number": chapter_number,
        "chapter_title": compact_text(str(raw_event_plan.get("chapter_title", "")).strip(), 60),
        "turn": compact_text(str(raw_event_plan.get("turn", "")).strip(), 120),
        "pivot": compact_text(str(raw_event_plan.get("pivot", "")).strip(), 160),
        "collision": compact_text(str(raw_event_plan.get("collision", "")).strip(), 160),
        "ordered_actions": _normalize_moves(raw_event_plan.get("ordered_actions")),
        "exposition_beats": compact_list(raw_event_plan.get("exposition_beats", []), max_items=8, item_chars=180),
        "npc_beats": compact_list(raw_event_plan.get("npc_beats", []), max_items=6, item_chars=180),
        "quest_beats": compact_list(raw_event_plan.get("quest_beats", []), max_items=6, item_chars=180),
        "location_beats": compact_list(raw_event_plan.get("location_beats", []), max_items=6, item_chars=180),
        "world_reactions": compact_list(raw_event_plan.get("world_reactions", []), max_items=6, item_chars=160),
        "stakes": compact_text(str(raw_event_plan.get("stakes", "")).strip(), 140),
        "next_focus": compact_text(str(raw_event_plan.get("next_focus", "")).strip(), 160),
        "explicit_chapter_end_hook": compact_text(str(raw_event_plan.get("explicit_chapter_end_hook", "")).strip(), 180),
        "chapter_end_hook": _normalize_chapter_end_hook(raw_event_plan.get("chapter_end_hook")),
        "author_constraints": list(story.author_constraints),
    }


def _normalize_memory_constraints(raw_memory: object, story: StoryState) -> dict:
    if not isinstance(raw_memory, dict):
        return {
            "must_keep_facts": [],
            "unresolved_threads": [],
            "protected_characters": [],
            "protected_foreshadowing": [],
            "author_constraints": list(story.author_constraints),
            "current_focus": "",
            "conflict_anchor": "",
            "event_guardrail": "",
            "ledger_updates": {},
        }
    return {
        "must_keep_facts": compact_list(raw_memory.get("must_keep_facts", []), max_items=8, item_chars=140),
        "unresolved_threads": compact_list(raw_memory.get("unresolved_threads", []), max_items=4, item_chars=90),
        "protected_characters": [str(v).strip() for v in raw_memory.get("protected_characters", []) if str(v).strip()][:4],
        "protected_foreshadowing": raw_memory.get("protected_foreshadowing", [])[:3] if isinstance(raw_memory.get("protected_foreshadowing"), list) else [],
        "author_constraints": compact_list(raw_memory.get("author_constraints", []), max_items=16, item_chars=180) or list(story.author_constraints),
        "current_focus": compact_text(str(raw_memory.get("current_focus", "")).strip(), 160),
        "conflict_anchor": compact_text(str(raw_memory.get("conflict_anchor", "")).strip(), 160),
        "event_guardrail": compact_text(str(raw_memory.get("event_guardrail", "")).strip(), 160),
        "ledger_updates": raw_memory.get("ledger_updates", {}) if isinstance(raw_memory.get("ledger_updates"), dict) else {},
    }


def _merge_ledger_dict(base: dict, updates: dict) -> dict:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_ledger_dict(result[key], value)
        elif value not in (None, "", [], {}):
            result[key] = value
    return result


def _apply_ledger_updates(story: StoryState, ledger_updates: dict) -> None:
    if not isinstance(ledger_updates, dict) or not ledger_updates:
        return
    story.progression_ledger = _merge_ledger_dict(story.progression_ledger or {}, ledger_updates)
    _normalize_progression_ledger(story.progression_ledger)


def _collect_state_deltas(items: list[dict] | None) -> list[dict]:
    deltas: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        delta = item.get("state_delta")
        if isinstance(delta, dict) and delta:
            deltas.append(delta)
    return deltas


def _add_int(base: object, delta: object) -> int:
    try:
        return int(base or 0) + int(delta or 0)
    except (TypeError, ValueError):
        return int(delta or 0) if isinstance(delta, int) else 0


def _add_mapping_counts(base: dict, updates: dict) -> dict:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, (int, float)) or str(value).lstrip("-").isdigit():
            result[key] = _add_int(result.get(key), value)
        elif value not in (None, "", [], {}):
            result[key] = value
    return result


def _systemic_ledger_delta(delta: dict) -> dict:
    game_world = delta.get("game_world_simulation") if isinstance(delta, dict) else None
    if not isinstance(game_world, dict):
        return {}
    ledger_delta = game_world.get("ledger_delta")
    return ledger_delta if isinstance(ledger_delta, dict) else {}


def _apply_systemic_ledger_delta(story: StoryState, ledger_delta: dict) -> None:
    if not isinstance(ledger_delta, dict) or not ledger_delta:
        return
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}

    inventory_delta = ledger_delta.get("inventory_delta")
    if isinstance(inventory_delta, dict) and inventory_delta:
        economy = ledger.setdefault("economy", {})
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}
        economy["inventory"] = _add_mapping_counts(inventory, inventory_delta)

    cost_delta = ledger_delta.get("cost_delta")
    if isinstance(cost_delta, dict) and cost_delta:
        protagonist = ledger.setdefault("protagonist", {})
        protagonist["cost_delta"] = dict(cost_delta)

    market_delta = ledger_delta.get("market_delta")
    if isinstance(market_delta, dict) and market_delta:
        market_root = ledger.get("market") if isinstance(ledger.get("market"), dict) else {}
        ledger["market"] = market_root
        market = market_root.get("newbie_materials") if isinstance(market_root.get("newbie_materials"), dict) else {}
        market_root["newbie_materials"] = market
        if "material_supply" in market_delta:
            market["supply"] = _add_int(market.get("supply"), market_delta.get("material_supply"))
        if market_delta.get("price_copper") not in (None, "", [], {}):
            market["price_copper"] = market_delta["price_copper"]

    hidden_delta = ledger_delta.get("hidden_system_delta")
    if isinstance(hidden_delta, dict) and hidden_delta:
        systems = ledger.get("systems") if isinstance(ledger.get("systems"), dict) else {}
        ledger["systems"] = systems
        chaos = systems.get("chaos_seed") if isinstance(systems.get("chaos_seed"), dict) else {}
        systems["chaos_seed"] = chaos
        if hidden_delta.get("chaos_seed_anomaly_score") not in (None, "", [], {}):
            chaos["anomaly_score"] = _add_int(chaos.get("anomaly_score"), hidden_delta["chaos_seed_anomaly_score"])

    if ledger_delta.get("clock_minutes") not in (None, "", [], {}):
        clock = ledger.setdefault("clock", {})
        clock["elapsed_minutes"] = _add_int(clock.get("elapsed_minutes"), ledger_delta["clock_minutes"])

    next_pressure = ledger_delta.get("next_pressure")
    if isinstance(next_pressure, list) and next_pressure:
        pressure = ledger.setdefault("pressure", {})
        pressure["next"] = [str(item) for item in next_pressure if str(item).strip()]

    story.progression_ledger = ledger
    _normalize_progression_ledger(story.progression_ledger)


def apply_simulated_state_deltas(
    story: StoryState,
    *,
    world_events: list[dict] | None = None,
    scene_cards: list[dict] | None = None,
    chapter_number: int | None = None,
) -> None:
    """Persist state changes created by the simulation layer."""

    for delta in [*_collect_state_deltas(world_events), *_collect_state_deltas(scene_cards)]:
        ledger_update = {key: value for key, value in delta.items() if key != "game_world_simulation"}
        _apply_ledger_updates(story, ledger_update)
        _apply_systemic_ledger_delta(story, _systemic_ledger_delta(delta))
    _sync_character_game_panels(story, chapter_number)


def _pick_protagonist(story: StoryState):
    return next(
        (
            character
            for character in story.characters
            if character.role in ("protagonist", "主角") or character.name in ("苏叶", "夜烬")
        ),
        story.characters[0] if story.characters else None,
    )


def _clean_mapping(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _clean_identity_placeholder(value: object) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or set(cleaned) <= {"?", "？", "�"}:
        return ""
    return cleaned


def _clean_game_id(value: object, character_name: str) -> str:
    cleaned = _clean_identity_placeholder(value)
    if cleaned and (cleaned == character_name or cleaned == "苏叶"):
        return ""
    return cleaned


def _sync_character_game_panels(story: StoryState, chapter_number: int | None = None) -> None:
    """Mirror the persistent progression ledger into the protagonist character card."""
    if not story.characters or not isinstance(story.progression_ledger, dict):
        return
    character = _pick_protagonist(story)
    if character is None:
        return

    ledger = story.progression_ledger
    protagonist = _clean_mapping(ledger.get("protagonist"))
    economy = _clean_mapping(ledger.get("economy"))
    equipment = _clean_mapping(ledger.get("equipment"))
    skills = ledger.get("skills")
    quests = ledger.get("quests")
    pressure = _clean_mapping(ledger.get("pressure"))

    panel = character.game_panel
    panel.game_id = (
        _clean_game_id(protagonist.get("game_id"), character.name)
        or _clean_game_id(panel.game_id, character.name)
        or _clean_game_id(character.game_id, character.name)
    )
    if not panel.game_id and character.name == "苏叶":
        panel.game_id = "夜烬"
    if panel.game_id:
        character.game_id = panel.game_id
    if protagonist.get("level") not in (None, "", [], {}):
        panel.level = protagonist.get("level")
    if protagonist.get("class_path"):
        panel.class_path = str(protagonist.get("class_path"))
    if protagonist.get("exp"):
        panel.exp = str(protagonist.get("exp"))
    if protagonist.get("hp"):
        panel.hp = str(protagonist.get("hp"))
    if protagonist.get("mp"):
        panel.mp = str(protagonist.get("mp"))
    if isinstance(protagonist.get("attributes"), dict):
        panel.attributes = dict(protagonist["attributes"])

    if character.name == "苏叶" and (panel.class_path or story.genre in {"网游", "web game", "game fantasy"}):
        if not panel.hp:
            panel.hp = "92/100" if str(panel.exp or "") not in {"", "0/100"} else "100/100"
        if not panel.mp:
            panel.mp = "61/80" if str(panel.exp or "") not in {"", "0/100"} else "80/80"
        if not panel.attributes:
            panel.attributes = {"力量": 3, "敏捷": 4, "智力": 9, "体质": 5}

    if isinstance(skills, dict):
        values: list[str] = []
        for value in skills.values():
            if isinstance(value, list):
                values.extend(str(item) for item in value if str(item).strip())
            elif value not in (None, "", {}, []):
                values.append(str(value))
        if values:
            panel.skills = values[:12]
    elif isinstance(skills, list):
        panel.skills = [str(item) for item in skills if str(item).strip()][:12]

    if equipment:
        panel.equipment = equipment
    if character.name == "苏叶" and panel.equipment and any("补给前置" in str(value) or "补给门槛" in str(value) for value in panel.equipment.values()):
        durability = str(panel.equipment.get("durability") or panel.equipment.get("耐久") or "94/100")
        panel.equipment = {"主武器": "新手法杖", "护甲": "粗布衣", "耐久": durability}
    if economy.get("inventory") not in (None, "", [], {}):
        panel.inventory = _clean_mapping(economy.get("inventory"))
    if character.name == "苏叶" and not panel.inventory and str(panel.exp or "") not in {"", "0/100"}:
        panel.inventory = {"灰鼠毒腺": "18份", "灰鼠皮": "3张"}
    if economy.get("currency"):
        panel.currency = str(economy.get("currency"))
    elif ledger.get("currency"):
        panel.currency = str(ledger.get("currency"))

    if isinstance(quests, dict):
        panel.quests = dict(quests)
    elif isinstance(quests, list):
        panel.quests = {"active": list(quests)}
    if pressure:
        panel.risk = pressure
    if chapter_number is not None:
        panel.updated_chapter = chapter_number

    summary_parts = [
        f"ID {panel.game_id}" if panel.game_id else "",
        f"Lv.{panel.level}" if panel.level not in (None, "") else "",
        panel.class_path,
        f"经验{panel.exp}" if panel.exp else "",
        panel.currency,
    ]
    summary = " / ".join(part for part in summary_parts if part)
    if summary:
        memory = f"角色面板：{summary}"
        character.memory = [memory, *[item for item in character.memory if not item.startswith("角色面板：")]][:12]


def _normalize_progression_ledger(ledger: dict) -> None:
    """Keep legacy flat ledger keys mirrored into the structured game ledger."""
    if not isinstance(ledger, dict):
        return
    protagonist = ledger.setdefault("protagonist", {})
    economy = ledger.setdefault("economy", {})
    equipment = ledger.setdefault("equipment", {})
    pressure = ledger.setdefault("pressure", {})
    if isinstance(protagonist, dict):
        for key in ("level", "exp", "class_path", "location"):
            if key in ledger and ledger[key] not in (None, "", [], {}):
                protagonist[key] = ledger[key]
    if isinstance(economy, dict):
        for key in ("currency", "inventory", "market_anomaly"):
            if key in ledger and ledger[key] not in (None, "", [], {}):
                economy[key] = ledger[key]
    if isinstance(equipment, dict):
        for key in ("weapon", "armor", "durability"):
            if key in ledger and ledger[key] not in (None, "", [], {}):
                equipment[key] = ledger[key]
    if isinstance(pressure, dict):
        for key in ("guild_attention", "goldfinger_exposure", "system_risk"):
            if key in ledger and ledger[key] not in (None, "", [], {}):
                pressure[key] = ledger[key]


def _merge_unique_compact(existing: object, additions: object, *, max_items: int = 8, item_chars: int = 140) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for source in (existing, additions):
        if isinstance(source, str):
            values = [source]
        elif isinstance(source, list):
            values = source
        else:
            values = []
        for value in values:
            clean = compact_text(str(value).strip(), item_chars)
            if not clean:
                continue
            key = re.sub(r"\s+", "", clean)
            if key in seen:
                continue
            seen.add(key)
            merged.append(clean)
            if len(merged) >= max_items:
                return merged
    return merged


def _economy_anchor_rank(text: str) -> int:
    if any(token in text for token in ("市场价", "均价", "挂牌均价", "回收单价", "定价", "单价", "价格")):
        return 0
    if any(token in text for token in ("手续费", "单笔上架上限", "单笔寄售上限", "流水风控", "风控阈值")):
        return 1
    if any(token in text for token in ("到账", "当前余额", "账户余额", "铜币余额", "货币：", "货币:")):
        return 2
    if any(token in text for token in ("掉落判定", "获得：", "背包：", "库存", "数量：")):
        return 3
    return 4


def _extract_economy_anchors(body: str, *, max_items: int = 8) -> list[str]:
    """Extract concrete price/currency anchors that must survive into later chapters."""
    if not body:
        return []
    economy_terms = (
        "市场价",
        "均价",
        "挂牌均价",
        "回收单价",
        "定价",
        "单价",
        "价格",
        "手续费",
        "到账",
        "当前余额",
        "账户余额",
        "铜币余额",
        "货币：",
        "货币:",
        "单笔上架上限",
        "单笔寄售上限",
        "流水风控",
        "风控阈值",
        "掉落判定",
        "获得：",
        "背包：",
    )
    value_terms = ("金币", "银币", "铜币", "毒腺", "狼牙", "狼皮", "材料", "交易行", "寄售", "上架", "回收")
    normalized = body.replace("\r", "\n").replace("`", "")
    candidates: list[tuple[int, int, str]] = []
    order = 0
    for line in normalized.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        for chunk in re.split(r"(?<=[。！？；])\s*", line):
            chunk = chunk.strip(" ，,")
            if not chunk:
                continue
            if any(term in chunk for term in economy_terms) and any(term in chunk for term in value_terms):
                candidates.append((_economy_anchor_rank(chunk), order, f"经济锚点：{compact_text(chunk, 130)}"))
                order += 1
    candidates.sort(key=lambda item: (item[0], item[1]))
    return _merge_unique_compact([], [candidate for _, _, candidate in candidates], max_items=max_items, item_chars=150)


def _extract_system_anchors(body: str, *, max_items: int = 10) -> list[str]:
    """Extract class, equipment and NPC service facts for long-form continuity."""
    if not body:
        return []
    normalized = body.replace("\r", "\n").replace("`", "")
    anchor_terms = (
        "职业倾向",
        "职业路线",
        "职业：",
        "元素法师",
        "法师学徒",
        "基础火球术",
        "元素亲和",
        "武器栏",
        "装备栏",
        "装备",
        "法杖",
        "短剑",
        "布衣",
        "护甲",
        "耐久",
        "修理",
        "购买",
        "药剂师洛婶",
        "职业导师艾伦",
        "仓库管理员铁栓",
        "修理匠老葛",
        "灰烬村村长",
    )
    candidates: list[tuple[int, int, str]] = []
    order = 0
    for line in normalized.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        for chunk in re.split(r"(?<=[。！？；])\s*", line):
            chunk = chunk.strip(" ，,")
            if not chunk or not any(term in chunk for term in anchor_terms):
                continue
            if any(term in chunk for term in ("职业倾向", "职业路线", "职业：", "元素法师", "法师学徒", "基础火球术", "元素亲和")):
                label = "职业锚点"
                rank = 0
            elif any(term in chunk for term in ("武器栏", "装备栏", "装备", "法杖", "短剑", "布衣", "护甲", "耐久", "修理", "购买")):
                label = "装备锚点"
                rank = 1
            else:
                label = "NPC锚点"
                rank = 2
            candidates.append((rank, order, f"{label}：{compact_text(chunk, 130)}"))
            order += 1
    candidates.sort(key=lambda item: (item[0], item[1]))
    return _merge_unique_compact([], [candidate for _, _, candidate in candidates], max_items=max_items, item_chars=150)


def _extract_equipment_ledger_updates(body: str) -> dict:
    updates: dict[str, dict] = {}
    if not body:
        return updates
    protagonist: dict[str, str | int] = {}
    economy: dict[str, object] = {}
    equipment: dict[str, str] = {}
    if any(token in body for token in ("元素法师", "法师学徒", "基础火球术", "元素亲和", "元素回廊")):
        protagonist["class_path"] = "元素法师学徒"
    level_matches = re.findall(r"(?:当前等级|等级)[：:]\s*(\d{1,3})", body)
    if level_matches:
        protagonist["level"] = int(level_matches[-1])
    exp_matches = re.findall(r"(?:经验|当前经验)[：:]\s*(\d+\s*/\s*\d+)", body)
    if exp_matches:
        protagonist["exp"] = re.sub(r"\s+", "", exp_matches[-1])
    currency_matches = re.findall(
        r"(?:当前资产|当前余额|账户余额|余额栏跳动|余额跳动|余额|货币)[：:]\s*([^\n。】]*(?:金币|银币|铜币)[^\n。】]*)",
        body,
    )
    if currency_matches:
        currency_text = currency_matches[-1]
        money = re.search(r"(?:(\d+)\s*金币)?\s*(?:(\d+)\s*银币)?\s*(?:(\d+)\s*铜币)?", currency_text)
        if money:
            gold = int(money.group(1) or 0)
            silver = int(money.group(2) or 0)
            copper = int(money.group(3) or 0)
            economy["currency"] = f"{gold}金币{silver}银币{copper}铜币"
    weapon_matches = re.findall(r"【([^】]*(?:法杖|短剑|剑|杖)[^】]*)】", body)
    if weapon_matches:
        preferred = next((item for item in reversed(weapon_matches) if "法杖" in item or "杖" in item), weapon_matches[-1])
        equipment["weapon"] = compact_text(preferred, 60)
    durability_matches = re.findall(r"(?:耐久度?[:：]\s*|耐久(?:恢复至|已降至|降至|：|:)?\s*)(\d{1,3}%|\d+/\d+|正常)", body)
    if durability_matches:
        equipment["durability"] = durability_matches[-1]
    if "布衣" in body and "armor" not in equipment:
        equipment["armor"] = "布衣"
    inventory_matches = re.findall(r"背包[：:]\s*([^\n】]+)", body)
    if inventory_matches:
        inventory: dict[str, str | int] = {}
        latest_inventory = inventory_matches[-1]
        for item, count in re.findall(r"([\u4e00-\u9fa5A-Za-z0-9·]+)\s*[×xX*＊]\s*(\d+)", latest_inventory):
            inventory[item] = int(count)
        if (
            inventory.get("灰狼毒腺") == 5
            and re.search(r"(?:递过去的五份毒腺|提交[^。]{0,12}五份毒腺|已提交5/5)", body)
        ):
            inventory["灰狼毒腺"] = 0
        if inventory:
            economy["inventory"] = inventory
    skill_matches = re.findall(r"(?:基础技能|技能)[：:]\s*([^\n】]+)", body)
    if skill_matches:
        updates["skills"] = [compact_text(skill_matches[-1], 80)]
    if protagonist:
        updates["protagonist"] = protagonist
    if economy:
        updates["economy"] = economy
        if "currency" in economy:
            updates["currency"] = economy["currency"]
    if equipment:
        updates["equipment"] = equipment
    return updates


def _inject_continuity_anchors(memory_constraints: dict, chapter_summary_data: dict, body: str) -> list[str]:
    anchors = _merge_unique_compact(
        _extract_economy_anchors(body, max_items=8),
        _extract_system_anchors(body, max_items=10),
        max_items=14,
        item_chars=150,
    )
    if not anchors:
        return []
    memory_constraints["must_keep_facts"] = _merge_unique_compact(
        memory_constraints.get("must_keep_facts", []),
        anchors,
        max_items=14,
        item_chars=150,
    )
    chapter_summary_data["facts"] = _merge_unique_compact(
        chapter_summary_data.get("facts", []),
        anchors,
        max_items=14,
        item_chars=150,
    )
    equipment_updates = _extract_equipment_ledger_updates(body)
    if equipment_updates:
        current_updates = memory_constraints.get("ledger_updates", {})
        memory_constraints["ledger_updates"] = _merge_ledger_dict(
            current_updates if isinstance(current_updates, dict) else {},
            equipment_updates,
        )
    return anchors


def _normalize_chapter_summary(raw_summary: object, chapter_number: int) -> dict:
    if not isinstance(raw_summary, dict):
        return {
            "chapter_number": chapter_number,
            "summary": "",
            "facts": [],
            "unresolved_threads": [],
            "next_focus": "",
            "chapter_title": "",
        }
    return {
        "chapter_number": chapter_number,
        "summary": compact_text(str(raw_summary.get("summary", "")).strip(), 260),
        "facts": compact_list(raw_summary.get("facts", []), max_items=8, item_chars=120),
        "unresolved_threads": compact_list(raw_summary.get("unresolved_threads", []), max_items=5, item_chars=90),
        "next_focus": compact_text(str(raw_summary.get("next_focus", "")).strip(), 160),
        "chapter_title": compact_text(str(raw_summary.get("chapter_title", "")).strip(), 60),
    }


def _opening_phase_name(chapter_number: int) -> str:
    if chapter_number == 1:
        return "黄金三章第1章：立世界、立主角、立核心能力、完成第一次有效验证"
    if chapter_number == 2:
        return "黄金三章第2章：把千倍爆率转成任务、装备或路线领先"
    if chapter_number == 3:
        return "黄金三章第3章：第一个小高潮、明确敌对压力、确立长期成长路线"
    return "常规连载章节：目标、行动、收益、压力、钩子循环"


def _opening_writer_rules(chapter_number: int) -> list[str]:
    if chapter_number == 1:
        return [
            "第一章承担读者入门职责：必须自然交代现实压力、游戏入口、主角技能来源、金手指首次露头和下一步领先目标。",
            "500字内要出现强钩子；1000字内要让读者知道主角缺什么、怕什么、想要什么。",
            "番茄长篇节奏：第一章目标篇幅按4200到5500字写，不要压缩成3000字以内的信息摘要。",
            "游戏背景要通过登录界面、系统公告、玩家闲聊、路牌或柜台观察写出来，不要用百科段落硬讲。",
            "主角背景要通过现实账单、出租屋细节、职业/工作状态、短暂记忆、行为习惯或心理压迫露出，不能只贴标签。",
            "必须说明主角现实职业、失业/兼职/外包状态或现实技能来源，并让这解释他为什么会谨慎、会算账、会拆单或熟悉网游经济。",
            "第一章必须写出网游开篇仪式：登录或角色创建、游戏ID“夜烬”、职业选择、角色面板。夜烬应选择元素法师学徒/元素法师路线，并说明这决定法杖、基础法术和10级元素回廊试炼前置。",
            "角色面板必须在正文中写出“角色面板”四个字，并有职业栏，至少包含：游戏ID、等级、职业/路线、经验、生命/法力、基础火球术、背包或钱袋关键项；不要写“货币：0铜”；面板要短，不要刷屏。",
            "初始钱袋锁死为空。第一章如果没有正文写出铜币掉落或任务奖励，章末就仍是一枚铜都没有，不能凭空变成15铜。",
            "职业和技能锁死：职业列表只点到战士、游侠、法师/元素法师学徒即可；初始技能统一写“基础火球术”，不要改名成元素弹。",
            "现实钱语义锁死：27.60是银行卡余额或可用余额，不是最低还款额；不要把现实压力写轻。",
            "金手指不能凭空弹出：必须先有旧头盔/底层日志/接驳异常等触发，再出现“底层协议校验通过”和“混沌之种：未解析”。",
            "统一术语：本项目隐藏优势必须出现“千倍爆率”四个字；可以同时写掉落判定×1000，但不能只写异常或不正常。",
            "第一章冲突是现实缺钱、旧设备、首次验证成本和主角意识到自己能比普通玩家快一步；不要把焦点写成几颗材料怎么处理。",
            "第一章禁止越级冲突：公会不能精准锁定坐标/现实身份，不能围杀主角，不能直接抢世界BOSS或高阶副本。",
            "第一章不要完成公开交易或结算闭环：禁止寄售成功、成交、到账、手续费扣款、材料换成人民币；是否提交低级任务、拿铜币、修理或买药，必须跟随项目账本/章节计划，不得凭空补收益。",
            "下一步钩子要落在进度领先上：主角意识到这些掉落能更快交任务、换装备、学技能或摸到下一条路线，而不是纠结几颗材料值多少钱。",
            "金手指首次验证必须同时带来收益和代价：掉落变多的爽点要指向任务/装备/技能领先，血量、法力、耐久和背包只作为节奏摩擦。",
            "第一章必须收敛：NPC、柜台、价牌和队伍只作为环境入口或下一章目标，不强制完整服务出场；如果出现命名NPC，只能一笔带过。",
            "第一章NPC信息边界：药剂师/药铺只能讲药材、库存、价格和她不知道的边界；不得由药剂师发布职业任务、讲职业试炼、解释全局市场或玩家生态。职业路线和技能前置优先交给角色面板、职业导师木牌或任务牌。",
            "第一章NPC窗口要求：可以写任务牌、柜台窗口或职业导师木牌来满足服务入口；是否办理业务由本书账本决定。若账本未允许，就只看见前置条件、价格或队伍，不提交、不到账。",
            "第一章禁止赵胖子正面登场、禁止白袍据点视角、禁止公会完整追查戏；商人和公会不要出场，最多留一个交易行价牌弱钩子。",
            "第一章不要连续写药剂铺、职业大厅、修理铺、公会据点等多视角场景；优先完成现实压力、登录、首次验证和下一步领先钩子。",
        ]
    if chapter_number in (2, 3):
        return [
            f"{_opening_phase_name(chapter_number)}。",
            "继续补足世界运行规则，但只通过行动、界面、对话、论坛、公告、交易记录和冲突自然露出。",
            "冲突必须按阶段升级：第2章偏任务领先、装备前置和新路线入口；第3章再写更具体的资源点竞争或职业试炼前置。",
            "第2章必须承接第一章账本：夜烬仍是Lv.1元素法师学徒；本章留在新手村任务、灰狼坡/后坡、补给和基础火球术记录里推进。禁止Lv.1接取或开始转职任务、职业试炼、元素回廊试炼、法师塔试炼；10级之前只能看见远期线索或前置任务，不能正式办理。",
            "第2章账本要按上一章章末状态继承，等级、经验、钱袋、背包、生命/法力、装备耐久和任务状态都从项目账本读取；清道夫、买技能、修杖、买药等动作必须在正文里逐项落账。不要写经验100/100却未升级，也不要同章反复刷怪、回村、交同一个任务来凑进度。",
            "禁止越级：不要让敌人单次交易就知道隐藏天赋，不要让公会会长亲自围杀新手散人，不要提前写成服务器级大战。",
            "每个背景信息都必须服务当前目标、压力或爽点，不要停下来写设定说明书。",
        ]
    return [
        "优先保持连载节奏：目标明确、行动具体、收益有代价、章末有新压力。",
        "必要背景只在影响本章选择、冲突或收益时补充。",
    ]


def _review_protagonist_names(event_plan: dict[str, Any], simulation_plan: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Extract likely protagonist names for local prose reviewers.

    The prose-rule reviewer can only detect "the protagonist never speaks" if
    it knows which names belong to the lead. Director plans already carry this
    in ordered_actions; keep the extraction narrow so NPC names do not flood
    the speech gate.
    """

    names: list[str] = []

    def add(value: object) -> None:
        name = str(value or "").strip()
        if not name or len(name) > 12:
            return
        if name in {"主角", "玩家", "散人", "NPC", "系统", "旁人", "众人"}:
            return
        if name not in names:
            names.append(name)

    def scan_plan(plan: dict[str, Any]) -> None:
        primary = plan.get("primary_conflict")
        if isinstance(primary, dict):
            add(primary.get("lead"))
        for action in plan.get("ordered_actions") or []:
            if isinstance(action, dict):
                add(action.get("name"))

    if isinstance(event_plan, dict):
        scan_plan(event_plan)
    if isinstance(simulation_plan, dict):
        nested_event_plan = simulation_plan.get("event_plan")
        if isinstance(nested_event_plan, dict):
            scan_plan(nested_event_plan)
        performance = simulation_plan.get("character_performance")
        if isinstance(performance, dict):
            for name in performance.keys():
                add(name)

    return tuple(names[:4])


def _review_chapter_body(
    chapter_number: int,
    body: str,
    event_plan: dict,
    world_facts: list[str] | None = None,
    simulation_plan: dict | None = None,
    world_events: list[dict] | None = None,
    scene_cards: list[dict] | None = None,
) -> dict:
    compact_body = "".join(body.split())
    facts_text = "\n".join(world_facts or [])
    plan_text = json.dumps(event_plan, ensure_ascii=False)
    game_context = any(
        token in body or token in facts_text or token in plan_text
        for token in (
            "《天启之门》",
            "VRMMO",
            "网游",
            "交易行",
            "混沌之种",
            "千倍爆率",
            "低级材料",
            "game_webnovel",
            "职业：",
            "Lv.",
            "转职任务",
            "职业试炼",
            "法师塔",
            "清道夫委托",
            "灰狼坡",
            "钱袋",
            "基础火球术",
            "后坡入口",
        )
    )
    simulation_plan = simulation_plan or {}
    min_chapter_chars = _chapter_review_min_chars(simulation_plan)
    issues: list[str] = []
    revision_plan: list[str] = []
    scores = {
        "webnovel_hook": 8 if len(compact_body) >= min_chapter_chars else 5,
        "background_integration": 8,
        "protagonist_motivation": 8,
        "genre_rules": 8,
        "world_reaction": 8 if event_plan.get("world_reactions") else 4,
        "chapter_ending_hook": 8 if event_plan.get("next_focus") or event_plan.get("stakes") else 5,
        "continuity": 8,
    }

    def require(label: str, keywords: tuple[str, ...], issue: str, plan: str) -> None:
        if not any(keyword in body for keyword in keywords):
            scores[label] = min(scores[label], 5)
            issues.append(issue)
            revision_plan.append(plan)

    if len(compact_body) < min_chapter_chars:
        scores["webnovel_hook"] = min(scores["webnovel_hook"], 5)
        issues.append(f"章节字数偏少：当前约{len(compact_body)}字，番茄长篇建议至少{min_chapter_chars}字。")
        revision_plan.append(f"扩写到{TARGET_CHAPTER_CHARS}，补足场景、对话、心理、交易过程、NPC服务边界和章末弱钩子，避免摘要化。")

    if chapter_number == 1 and game_context:
        game_id_markers = ("游戏ID", "游戏昵称", "角色名", "网名", "ID：", "ID:", "夜烬", "铁算盘")
        if not any(marker in body or marker in plan_text or marker in facts_text for marker in game_id_markers):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            scores["background_integration"] = min(scores["background_integration"], 5)
            issues.append("第一章缺少游戏ID/网名身份层；网游文需要区分现实姓名和游戏内ID。")
            revision_plan.append("在角色创建或登录界面补入苏叶的游戏ID“夜烬”，游戏内交易、论坛、公会观察优先称呼夜烬，现实场景才用苏叶。")

    if "1000倍爆率" in body or "1000 倍爆率" in body or "1000倍" in body and "千倍" in body:
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append("千倍爆率写法不统一：正文混用了“千倍”和“1000倍/1000倍爆率”。")
        revision_plan.append("统一改为“千倍爆率”；如需面板数值，使用“掉落判定×1000”而不是“1000倍爆率”。")

    forbids_fixed_exchange_rate = "不得写死" in facts_text and "汇率" in facts_text
    has_explicit_exchange_rate = not forbids_fixed_exchange_rate and any(
        token in facts_text for token in ("稳定汇率", "金币=人民币", "金币兑人民币")
    )
    invented_exchange_rate = re.search(
        r"(?:1|一)\s*(?:枚)?金币\s*(?:=|约等于|等于|能换|可以换|折合)\s*\d+(?:\.\d+)?\s*(?:元|人民币|RMB)",
        body,
    )
    if invented_exchange_rate and not has_explicit_exchange_rate:
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append("章节写死了金币与人民币汇率，但世界档案没有明确官方兑换或黑市行情。")
        revision_plan.append("删除固定现实汇率，改写为开服期行情未稳、商人询价、游戏内铜币/银币/金币价格或市场猜测。")

    for match in re.finditer(r"(\d+)\s*铜币[（(]\s*(?:(\d+)\s*金)?\s*(?:(\d+)\s*银)?\s*(?:(\d+)\s*铜)?\s*[）)]", body):
        copper_total = int(match.group(1))
        gold = int(match.group(2) or 0)
        silver = int(match.group(3) or 0)
        copper = int(match.group(4) or 0)
        converted_total = gold * 10000 + silver * 100 + copper
        if converted_total != copper_total:
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append(f"章节币制换算错误：{match.group(0)} 不符合 1金币=100银币=10000铜币。")
            revision_plan.append("按 1金币=100银币=10000铜币 重算交易金额；低级材料收益优先写银币/铜币，不要把千铜级收益写成金币级暴富。")
            break

    decimal_currency = re.search(r"(?:\d+\.\d+\s*(?:金币|银币|铜币)|(?:金币|银币|铜币)\s*\d+\.\d+)", body)
    if decimal_currency:
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append(f"游戏币显示不应出现小数：{decimal_currency.group(0)}。")
        revision_plan.append("把金币/银币/铜币金额改为整数并按 1金币=100银币=10000铜币 进位显示；材料均价可写“约8.5铜”，但到账和余额必须是整数货币。")

    if "单笔限额50" in body or any("单笔限额50" in fact for fact in (world_facts or [])):
        for match in re.finditer(r"(?:上架|寄售)[^。\n】]*[×x]\s*(\d+)", body):
            amount = int(match.group(1))
            if amount > 50:
                scores["genre_rules"] = min(scores["genre_rules"], 5)
                issues.append(f"交易行单笔限额为50，但正文出现单笔上架/寄售 {amount} 单位。")
                revision_plan.append("把交易行挂单拆成不超过50单位的小单，并同步重算手续费与到账金额。")
                break
    listed_amount = re.search(r"上架数量[：:]\s*(\d+)", body)
    single_limit = re.search(r"单笔上架数量限制[：:]\s*(\d+)", body)
    if listed_amount and single_limit and int(listed_amount.group(1)) > int(single_limit.group(1)):
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append(f"交易行规则自相矛盾：单笔限制 {single_limit.group(1)}，但正文一次上架 {listed_amount.group(1)}。")
        revision_plan.append("删除自相矛盾的单笔限制，或把上架改成分批挂单；每笔数量不得超过正文界面写出的单笔限制。")
    elif listed_amount and int(listed_amount.group(1)) > 50:
        scores["genre_rules"] = min(scores["genre_rules"], 6)
        issues.append(f"低级材料一次上架 {listed_amount.group(1)} 单位过大，容易破坏交易行寄售限制。")
        revision_plan.append("把低级材料改为多笔分批寄售，并写清拆单带来的时间、手续费或等待代价。")

    low_tier_market_terms = ("低级材料", "腐皮", "毒腺", "草药", "狼皮", "狼牙", "毒蜥", "毒蛙")
    immediate_tracking_terms = (
        "坐标已标记",
        "锁定坐标",
        "精确坐标",
        "暴露现实身份",
        "锁定现实身份",
        "显示现实身份",
        "真人身份已确认",
        "直接定位",
        "立刻锁定坐标",
        "马上锁定坐标",
    )
    if any(token in body for token in low_tier_market_terms) and has_asserted_overreach(body, immediate_tracking_terms):
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append("低级材料交易被写成单次上架就暴露坐标/身份，追踪强度不符合常规网游交易行逻辑。")
        revision_plan.append("改成分层可见：低级材料只造成价格波动、时间戳和商人脚本弱线索；公会需要重复模式、稀有物、玩家目击、NPC任务异常或多处线索汇总后才能缩小范围。")

    if chapter_number == 1 and game_context:
        pacing_groups = (
            ("登录", "上线", "进入游戏"),
            ("混沌之种", "千倍爆率", "隐藏天赋"),
            ("刷怪", "灰狼", "出村"),
            ("回村", "返回灰烬村", "回到灰烬村", "回到村", "村口结算"),
            ("交易行", "寄售", "拆单", "成交", "到账"),
        )
        pacing_hits = sum(1 for group in pacing_groups if any(token in body for token in group))
        merchant_direct_pressure = any(
            token in body
            for token in (
                "赵胖子",
                "铁算盘",
                "商人当场",
                "商人正面",
                "当场登场试探",
                "试探价格",
                "商人压价",
                "压价试探",
                "私聊",
            )
        )
        guild_direct_pressure = any(token in body for token in ("白袍", "公会")) and has_asserted_overreach(
            body,
            ("追查货源", "观察名单", "锁定坐标", "锁定身份", "锁定刷怪点", "围住", "通缉"),
        )
        if (merchant_direct_pressure or guild_direct_pressure) and pacing_hits >= 5:
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章节奏过载：登录、金手指、刷怪、回村交易、商人登场和公会追查被压进同一章。")
            revision_plan.append("拆分开篇节奏：第一章只保留现实压力、登录建号、职业面板、金手指伏笔和首次领先验证；交易成交、商人正面试探、公会追查、论坛围观全部放到后面，并且必须等稀有物、榜单或多源证据出现后再升级。")

        first_chapter_trade_terms = (
            "匿名寄售",
            "寄售成功",
            "上架成功",
            "成交",
            "到账",
            "手续费",
            "第一笔铜币落袋",
            "赵胖子",
            "盯盘",
        )
        if any(token in body for token in first_chapter_trade_terms):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章提前展开交易线：出现寄售、成交、到账、手续费、商人盯盘或赵胖子内容。")
            revision_plan.append("删除第一章的实际交易和商人线，只保留掉落、任务材料预留和章末“下一步用高爆率抢任务/装备/技能前置”的目标。")

        first_chapter_pressure_terms = ("白袍", "公会", "论坛", "清场", "后勤", "异常低价", "观察名单")
        if any(token in body for token in first_chapter_pressure_terms):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章外部压力过早：公会、论坛、商人脚本或清场信息提前介入。")
            revision_plan.append("把公会、论坛和商人脚本反应全部移到第二章以后；第一章只让主角自己意识到材料需要处理，外部世界暂不正式发现。")

        opening_overreach_terms = (
            "正面撞上",
            "正面对决",
            "当场围住",
            "围杀",
            "截杀",
            "追杀",
            "杀人夺宝",
            "抢核心资源",
            "争夺核心资源",
            "世界BOSS",
            "高阶副本",
            "公会会长",
        )
        if any(token in body for token in opening_overreach_terms):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章冲突越级：开篇应以现实压力、登录建号、职业选择、规则验证和背包材料暂时不能处理为主，不能写成公会/商人正面对抗或高阶资源争夺。")
            revision_plan.append("把冲突降级为网游新手阶段：现实资金压力、职业选择成本、第一次打怪验证、血蓝耐久消耗和背包材料如何处理。")

    if "数量×1000" in body and re.search(r"获得：[^。\n】]*[×x]\s*100(?:[。】\n]|$)", body):
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append("天赋说明为基础掉落物数量×1000，但正文首次掉落只写×100。")
        revision_plan.append("要么把天赋说明改为爆率/判定权重×1000，要么把首次掉落数量改为×1000，并同步后续背包、交易和市场反应。")

    if (
        chapter_number in (2, 3)
        and ("NPC：" in facts_text or event_plan.get("npc_beats"))
        and not any(token in body for token in ("灰烬村村长", "药剂师洛婶", "职业导师艾伦", "仓库管理员铁栓", "修理匠老葛", "村长", "洛婶", "艾伦", "铁栓", "老葛"))
    ):
        scores["background_integration"] = min(scores["background_integration"], 5)
        issues.append("网游开篇缺少已建档命名 NPC 的服务、任务发布或职业导师互动，世界像只有玩家和系统。")
        revision_plan.append("补入至少一场已建档命名 NPC 互动，例如灰烬村村长、药剂师洛婶、职业导师艾伦、仓库管理员铁栓或修理匠老葛，并让其服务/任务/信息边界推动本章选择。")

    if chapter_number == 1 and game_context:
        require(
            "background_integration",
            ("《天启之门》", "全沉浸", "VRMMO", "开服"),
            "第一章缺少足够清晰的游戏背景入口。",
            "在开头或登录场景中补入《天启之门》的全沉浸、开服和玩家涌入背景。",
        )
        require(
            "protagonist_motivation",
            ("出租屋", "账单", "欠", "现实", "缺钱", "房租", "医疗", "债"),
            "第一章缺少主角现实压力或行动动机。",
            "用现实账单、出租屋、债务或生活压力补出苏叶必须低调变强/变现的原因。",
        )
        require(
            "protagonist_motivation",
            ("职业", "工作", "打工", "失业", "外包", "测试", "客服", "程序", "网管", "代练", "陪练", "简历", "工位"),
            "第一章没有交代主角现实职业、工作状态或现实技能来源。",
            "补出苏叶在现实里的职业/工作状态，以及这份经历为什么让他擅长低调计算、刷怪路线、交易拆单或风险控制。",
        )
        require(
            "genre_rules",
            ("职业选择", "选择职业", "职业：", "职业栏", "职业路线", "元素法师学徒", "法师学徒", "职业大厅", "职业导师", "艾伦"),
            "第一章没有写出角色创建/登录阶段的职业选择或职业路线确认。",
            "补出夜烬选择元素法师学徒/元素法师路线的过程，并让该选择关联法杖、基础法术、10级元素回廊试炼和后续成长前置。",
        )
        panel_surface_markers = (
            "角色面板",
            "角色状态",
            "个人面板",
            "属性面板",
            "状态面板",
            "面板在视野",
            "【等级：",
            "【经验：",
            "【生命：",
        )
        if not any(token in body for token in panel_surface_markers) or not any(
            token in body for token in ("职业：", "职业栏", "职业路线", "元素法师学徒", "法师学徒")
        ):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章缺少带职业栏的角色面板，等级/经验/职业/主武器或基础技能没有形成可追踪账本。")
            revision_plan.append("补一个简短角色面板：游戏ID夜烬、等级1、职业元素法师学徒、经验0/100、新手法杖、基础火球术或技能未解锁、初始货币/背包。")
        require(
            "webnovel_hook",
            ("混沌之种", "千倍", "爆率", "隐藏天赋"),
            "第一章金手指钩子不够明确。",
            "在前1000字内明确展示混沌之种/千倍爆率的首次验证和代价。",
        )
        if any(token in body for token in ("隐藏天赋", "混沌之种", "千倍爆率", "爆率修正")) and not any(
            token in body
            for token in (
                "异常邀请码",
                "旧头盔",
                "内测",
                "职业选择",
                "神经接驳",
                "接驳",
                "协议异常",
                "角色创建",
                "创建角色",
                "登录入口",
                "登录界面",
                "开服倒计时",
                "触发条件",
                "底层日志",
                "灰色日志",
            )
        ):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章金手指出现缺少触发条件或前置伏笔，读起来像凭空弹出。")
            revision_plan.append("在金手指正式显示前补一个可感知触发：旧头盔/异常邀请码/神经接驳协议异常/角色创建选择/底层日志闪烁，并让主角先怀疑再验证。")
        if "正面撞上" in plan_text or "核心资源的控制权" in plan_text:
            scores["continuity"] = min(scores["continuity"], 5)
            issues.append("第一章冲突被计划成直接对抗或争夺核心资源，和低调开局不匹配。")
            revision_plan.append("把第一章主冲突改成现实资金压力与低调变现之间的矛盾；赵胖子/白袍只能通过价格、时间戳、交易记录形成间接压力。")

    if game_context:
        level_matches = re.findall(
            r"(?:当前等级|等级)[：:]?\s*(?:Lv\.?)?\s*(\d{1,3})|Lv\.?\s*(\d{1,3})",
            "\n".join([body, facts_text]),
            flags=re.IGNORECASE,
        )
        surfaced_levels = [int(left or right) for left, right in level_matches if left or right]
        current_level = min(surfaced_levels) if surfaced_levels else None
        transfer_or_trial_start = any(
            marker in body
            for marker in (
                "开始转职任务",
                "接取转职任务",
                "转职任务已接取",
                "职业试炼已开启",
                "开始职业试炼",
                "进入元素试炼",
                "元素试炼区域",
                "法师塔一层",
                "进入法师塔",
                "开启元素回廊试炼",
            )
        )
        if current_level is not None and current_level < 10 and transfer_or_trial_start:
            scores["continuity"] = min(scores["continuity"], 5)
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append(
                f"低等级越级：当前只有Lv.{current_level}，10级前不能正式接取或开始转职任务、职业试炼、元素试炼、法师塔试炼。"
            )
            revision_plan.append("把本章改回新手村任务、低级地图、补给、耐久、材料和基础技能记录；高阶任务只能作为远期前置或被拒绝的登记。")

    if chapter_number == 2 and game_context:
        corridor_complete = "元素回廊前置" in body and any(
            marker in body for marker in ("任务完成", "进度：10/10", "进度:10/10", "前置材料已提交", "已完成")
        )
        level_up = any(marker in body for marker in ("等级提升", "当前等级：2", "等级：2", "等级2"))
        level_one_surface = any(marker in body or marker in facts_text for marker in ("Lv.1", "Lv1", "等级1", "等级：1"))
        if level_one_surface and transfer_or_trial_start:
            scores["continuity"] = min(scores["continuity"], 5)
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("Lv.1越级：第二章仍是新手村阶段，不能接取或开始转职任务、职业试炼、元素试炼、法师塔试炼。")
            revision_plan.append("把第二章改回清道夫、后坡入口、修理、药水、基础火球术命中记录等新手村可见进度；高阶任务只能作为远期线索。")
        if corridor_complete or level_up:
            scores["continuity"] = min(scores["continuity"], 5)
            issues.append("第二章推进过快：从第一章账本直接完成元素回廊前置或升级，材料、经验、耐久和消耗过程不足。")
            revision_plan.append("把第二章收束为材料、经验、补给或技能前置推进；继承上一章章末账本，不重造铜币、库存、血蓝或耐久，本章只推进到新的阶段目标，不直接完成元素回廊前置或升到2级。")

    if game_context:
        unresolved_full_exp = re.search(
            r"经验[：:]\s*100\s*/\s*100[^\n。]*(?:未升级|没跳|卡住|卡在)|经验条[^\n。]*(?:卡在|卡住)\s*100\s*/\s*100",
            body,
        )
        if unresolved_full_exp and not any(token in body for token in ("回村登记升级", "手动升级", "升级登记", "晋级登记")):
            scores["continuity"] = min(scores["continuity"], 5)
            issues.append("经验账本不清：正文写到100/100却又说未升级或没跳，读者会以为等级规则坏了。")
            revision_plan.append("把经验改成未满，或明确写出需要回村登记/手动升级的规则，并让角色按这个规则行动。")

        submitted_task = any(token in body for token in ("清道夫委托完成", "奖励三十铜", "奖励30铜", "奖励：30铜", "奖励三十枚铜"))
        says_not_submitted = any(token in body for token in ("清道夫委托也没有提交", "清道夫委托没提交", "没有提交清道夫"))
        if submitted_task and says_not_submitted:
            scores["continuity"] = min(scores["continuity"], 5)
            issues.append("任务账本自相矛盾：同章既说清道夫委托没提交，又写完成或领取奖励。")
            revision_plan.append("确定本章只办理一次清道夫结算；如果已经领奖，就删除未提交说法，并同步经验、铜币和背包材料。")

        rejected_currency_panel = re.search(r"(?:当前货币|货币)[：:]\s*0\s*铜", body)
        if rejected_currency_panel:
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("面板写法回退：不要写“货币：0铜”或“当前货币：0铜”。")
            revision_plan.append("把初始余额改成“钱袋：空”或用正文写一枚铜都没有，避免机械面板腔。")

    if chapter_number in (1, 2, 3) and game_context:
        task_completion_count = body.count("清道夫委托完成")
        if any(token in body for token in ("材料收走", "铜币从窗口", "铜币落进钱袋", "铜币落入")):
            task_completion_count += 1
        village_loop_count = sum(body.count(token) for token in ("回村", "回到灰烬村", "村口的任务牌", "任务牌前"))
        if task_completion_count >= 2 and village_loop_count >= 3:
            scores["chapter_ending_hook"] = min(scores["chapter_ending_hook"], 5)
            scores["continuity"] = min(scores["continuity"], 5)
            issues.append("新手章流程重复：同章反复刷怪、回村、交同一个清道夫任务，会把爽点写成流水账。")
            revision_plan.append("保留一次完整结算，把第二轮压成章末目标或下一章开场；用技能、修理、入口前置或旁人反应承接爽点。")

    web_game_review = review_web_game_chapter(
        chapter_number=chapter_number,
        body=body,
        event_plan=event_plan,
        world_facts=world_facts,
    )
    consistency_review = review_world_event_consistency(
        body,
        world_events=world_events or [],
        scene_cards=scene_cards or [],
        chapter_number=chapter_number,
    )
    scene_contract_failures = (
        consistency_review.get("scene_contract_failures")
        if isinstance(consistency_review.get("scene_contract_failures"), list)
        else []
    )
    scene_repair_plan = build_scene_contract_repair_plan(consistency_review, scene_cards or [])
    style_review = review_prose_style(body)
    prose_quality_review = review_prose_quality(body)
    adversarial_cut_review = review_adversarial_cuts(body)
    ai_flavor_review = review_ai_flavor(body)
    progression_lead_review = review_progression_lead(
        chapter_number=chapter_number,
        body=body,
        event_plan=event_plan,
        world_facts=world_facts or [],
    )
    critical_review = review_critical_prose_rules(
        body,
        protagonist_names=_review_protagonist_names(event_plan, simulation_plan),
    )
    if simulation_plan:
        scores["simulation_plan_alignment"] = 8
        missing_review_focus = not simulation_plan.get("review_focus")
        missing_performance = not simulation_plan.get("character_performance")
        if missing_review_focus or missing_performance:
            scores["simulation_plan_alignment"] = 6
            issues.append("统一场景推演/表演蓝图不完整：缺少角色表演或审稿重点，后续章节容易变成只有事件、没有角色反应。")
            revision_plan.append("补齐 simulation_plan.character_performance 与 simulation_plan.review_focus，再让正文按角色行事习惯、NPC边界和信息可见性展开。")
        if game_context and not simulation_plan.get("information_visibility"):
            scores["simulation_plan_alignment"] = min(scores["simulation_plan_alignment"], 6)
            issues.append("统一蓝图缺少信息可见性边界，网游章节容易写成交易行、公会或NPC全知全能。")
            revision_plan.append("在 simulation_plan.information_visibility 中写清交易行、公会、论坛、NPC记录分别能看到什么，不能看到什么。")
        forbidden_moves = [str(item).strip() for item in simulation_plan.get("forbidden_moves", []) if str(item).strip()]
        if game_context and not forbidden_moves:
            scores["simulation_plan_alignment"] = min(scores["simulation_plan_alignment"], 6)
            issues.append("统一蓝图缺少禁写项，无法约束低级材料扰乱全服、NPC越权、交易行暴露身份等常见网游逻辑问题。")
            revision_plan.append("在 simulation_plan.forbidden_moves 中加入NPC不得全知、低级材料不能扰乱全服、交易行不得暴露坐标/现实身份等禁写边界。")
    for key, score in web_game_review.get("scores", {}).items():
        scores[f"web_game_{key}"] = score
    for issue in web_game_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in web_game_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    for key, score in consistency_review.get("scores", {}).items():
        scores[f"world_event_{key}"] = score
    for issue in consistency_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in consistency_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    for key, score in style_review.get("scores", {}).items():
        scores[f"prose_style_{key}"] = score
    for issue in style_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in style_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    for key, score in critical_review.get("scores", {}).items():
        scores[f"critical_{key}"] = score
    for issue in critical_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in critical_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    for key, score in ai_flavor_review.get("scores", {}).items():
        scores[f"ai_flavor_{key}"] = score
    for issue in ai_flavor_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in ai_flavor_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    for key, score in progression_lead_review.get("scores", {}).items():
        scores[f"progression_lead_{key}"] = score
    for issue in progression_lead_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in progression_lead_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)

    passed = all(score >= 8 for score in scores.values()) and not issues
    world_state_review = _build_world_state_review(issues, revision_plan)
    return {
        "pass": passed,
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
        "prose_quality_review": prose_quality_review,
        "adversarial_cut_review": adversarial_cut_review,
        "ai_flavor_review": ai_flavor_review,
        "progression_lead_review": progression_lead_review,
        "critical_review": critical_review,
        "world_state_review": world_state_review,
        "scene_contract_failures": scene_contract_failures,
        "scene_repair_plan": scene_repair_plan,
    }


def _merge_writing_review_quality(quality: dict, writing_review: dict) -> dict:
    merged = dict(quality)
    issues = list(merged.get("issues") or [])
    scores = writing_review.get("scores", {}) if isinstance(writing_review.get("scores"), dict) else {}
    hard_review_prefixes = ("web_game_", "prose_style_", "prose_quality_")
    writing_review_failed = not bool(writing_review.get("pass", True)) or bool(writing_review.get("issues")) or any(
        str(key).startswith(hard_review_prefixes) and int(value or 0) < 8 for key, value in scores.items()
    )
    if writing_review_failed:
        merged["ok"] = False
        if "writing_review" not in issues:
            issues.append("writing_review")
    merged["issues"] = issues
    merged["writing_review"] = writing_review
    for key in ("critical_review", "hook_review", "pacing_review", "beats_review", "ai_flavor_review", "progression_lead_review"):
        if isinstance(writing_review.get(key), dict):
            merged[key] = writing_review[key]
    return merged


def apply_expression_patches_from_review(body: str, writing_review: dict) -> tuple[str, dict[str, Any]]:
    """Apply expression-only patch suggestions from adversarial cut review."""

    cut_review = writing_review.get("adversarial_cut_review", {}) if isinstance(writing_review, dict) else {}
    patches = build_expression_patch_suggestions(cut_review if isinstance(cut_review, dict) else {})
    result = apply_spot_fix_patches(body, patches)
    return str(result.get("revised_content", body)), {
        "reviewer": "expression_patch/v1",
        "patches": patches,
        **result,
    }


def _story_game_context(story: StoryState, plan: dict[str, Any] | None = None) -> bool:
    plan = plan if isinstance(plan, dict) else {}
    return is_game_story(
        story,
        plan.get("event_plan", {}),
        plan.get("simulation_plan", {}),
        plan.get("scene_cards", []),
        plan.get("craft_pack", {}),
    )


def _plan_target_chars(plan: dict[str, Any] | None) -> str:
    plan = plan if isinstance(plan, dict) else {}
    target = plan.get("target_chars")
    if isinstance(target, dict):
        minimum = target.get("min")
        maximum = target.get("max")
        if minimum and maximum:
            return f"{minimum}到{maximum}字"
        if minimum:
            return f"不少于{minimum}字"
        if maximum:
            return f"不超过{maximum}字"
    if isinstance(target, int) and target > 0:
        return f"约{target}字"
    return TARGET_CHAPTER_CHARS


def _compact_review_summary(review: dict[str, Any] | None) -> dict[str, Any]:
    review = review if isinstance(review, dict) else {}
    style_review = review.get("style_review") if isinstance(review.get("style_review"), dict) else {}
    prose_review = review.get("prose_quality_review") if isinstance(review.get("prose_quality_review"), dict) else {}
    summary: dict[str, Any] = {
        "issues": compact_list(review.get("issues", []), max_items=6, item_chars=90),
        "revision_plan": compact_list(review.get("revision_plan", []), max_items=6, item_chars=90),
    }
    scene_failures = compact_list(review.get("scene_contract_failures", []), max_items=6, item_chars=180)
    scene_repair_plan = review.get("scene_repair_plan") if isinstance(review.get("scene_repair_plan"), dict) else {}
    if scene_failures:
        summary["scene_contract_failures"] = scene_failures
    if scene_repair_plan:
        summary["scene_repair_plan"] = scene_repair_plan
    style_issues = compact_list(style_review.get("issues", []), max_items=4, item_chars=90)
    prose_issues = compact_list(prose_review.get("issues", []), max_items=4, item_chars=90)
    if style_issues:
        summary["style_issues"] = style_issues
    if prose_issues:
        summary["prose_issues"] = prose_issues
    return summary


def _plain_prompt_payload(value: Any) -> Any:
    """Remove writer-dangerous backend wording from structured prompt payloads."""

    if isinstance(value, str):
        return plain_writer_phrase(value)
    if isinstance(value, list):
        return [_plain_prompt_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain_prompt_payload(item) for key, item in value.items()}
    return value


def _plain_prompt_json(value: Any) -> str:
    return json.dumps(_plain_prompt_payload(value), ensure_ascii=False)


def _chapter_prompt_spec(chapter_number: int, plan: dict[str, Any] | None) -> SegmentSpec:
    plan = plan if isinstance(plan, dict) else {}
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    title = compact_text(str(event_plan.get("chapter_title", "本章正文")).strip() or "本章正文", 60)
    scene_cards = plan.get("scene_cards") if isinstance(plan.get("scene_cards"), list) else []
    required_surface: list[str] = []
    locations: list[str] = []
    for card in scene_cards[:4]:
        if not isinstance(card, dict):
            continue
        if card.get("location"):
            locations.append(str(card.get("location")))
        must_show = card.get("must_show") if isinstance(card.get("must_show"), list) else []
        for item in must_show:
            text = str(item).strip()
            if text and text not in required_surface:
                required_surface.append(text)
    event_actions = event_plan.get("ordered_actions") if isinstance(event_plan.get("ordered_actions"), list) else []
    actions = [compact_text(str(item.get("action") if isinstance(item, dict) else item).strip(), 60) for item in event_actions[:5] if str(item).strip()]
    required = required_surface[:6] or actions[:4] or [title]
    forbidden_moves = compact_list((plan.get("simulation_plan", {}) or {}).get("forbidden_moves", []), max_items=6, item_chars=40)
    return SegmentSpec(
        key="chapter_body",
        title=plain_writer_phrase(title),
        goal=plain_writer_phrase(compact_text(str((plan.get("simulation_plan", {}) or {}).get("chapter_goal") or event_plan.get("next_focus") or title), 160)),
        required_surface=plain_writer_phrase("、".join(required)),
        forbidden_surface="、".join(forbidden_moves),
        entry_state="；".join(locations[:3]) or "沿用本章计划开场状态。",
        exit_state=plain_writer_phrase(compact_text(str(event_plan.get("next_focus") or event_plan.get("stakes") or "留下下一章压力或新前置任务。"), 140)),
        handoff="本章收束后必须留下下一步压力，不得用总结句替代场景结尾。",
        target_chars=max(1200, int(plan.get("target_chars", {}).get("min", MIN_CHAPTER_CHARS)) // 4) if isinstance(plan.get("target_chars"), dict) else 1400,
    )


def _prose_grounded_writing_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    scene_cards = plan.get("scene_cards") if isinstance(plan.get("scene_cards"), list) else []
    scene_flow: list[str] = []
    for item in event_plan.get("ordered_actions", []) if isinstance(event_plan.get("ordered_actions"), list) else []:
        text = str(item.get("action") if isinstance(item, dict) else item).strip()
        if text:
            scene_flow.append(plain_writer_phrase(compact_text(text, 80)))
    for card in scene_cards[:4]:
        if not isinstance(card, dict):
            continue
        pieces = [str(card.get("location", "")).strip(), str(card.get("purpose", "")).strip(), str(card.get("ending_pressure", "")).strip()]
        text = "｜".join(piece for piece in pieces if piece)
        if text:
            scene_flow.append(plain_writer_phrase(compact_text(text, 100)))
    packet = {
        "chapter_number": plan.get("chapter_number") or event_plan.get("chapter_number"),
        "chapter_title": plain_writer_phrase(compact_text(str(event_plan.get("chapter_title", "")).strip(), 60)),
        "scene_flow": scene_flow[:8],
        "world_signals": [plain_writer_phrase(item) for item in compact_list(event_plan.get("world_reactions", []), max_items=6, item_chars=80)],
        "required_beats": [plain_writer_phrase(item) for item in compact_list(simulation_plan.get("required_beats", []), max_items=6, item_chars=80)],
        "forbidden_moves": [plain_writer_phrase(item) for item in compact_list(simulation_plan.get("forbidden_moves", []), max_items=6, item_chars=80)],
    }
    return {key: value for key, value in packet.items() if value not in (None, "", [], {})}


def _simulation_variant_from_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    simulation_variant = (
        simulation_plan.get("simulation_variant") if isinstance(simulation_plan.get("simulation_variant"), dict) else {}
    )
    return simulation_variant


def _simulation_variant_from_simulation_plan(simulation_plan: dict[str, Any] | None) -> dict[str, Any]:
    simulation_plan = simulation_plan if isinstance(simulation_plan, dict) else {}
    simulation_variant = (
        simulation_plan.get("simulation_variant") if isinstance(simulation_plan.get("simulation_variant"), dict) else {}
    )
    return simulation_variant


def _should_expand_chapter(body: str, plan: dict[str, Any] | None) -> bool:
    if _simulation_variant_from_plan(plan).get("skip_expansion"):
        return False
    return _chapter_char_count(body) < MIN_CHAPTER_CHARS


def _chapter_review_min_chars(simulation_plan: dict[str, Any] | None) -> int:
    variant = _simulation_variant_from_simulation_plan(simulation_plan)
    if variant.get("skip_expansion"):
        return REGENERATION_FAST_MIN_CHARS
    if variant:
        return REGENERATION_MIN_CHARS
    return MIN_CHAPTER_CHARS


def _style_adapt_enabled(plan: dict[str, Any] | None) -> bool:
    plan = plan if isinstance(plan, dict) else {}
    if str(plan.get("write_mode", "")).strip().lower() in {"fast", "speed", "rough"}:
        return False
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    if _simulation_variant_from_plan(plan).get("skip_style_adapt"):
        return False
    return bool(
        plan.get("style_adapt", True)
        and (
            plan.get("web_game_director_card")
            or simulation_plan.get("web_game_director_card")
            or simulation_plan.get("chapter_goal")
        )
    )


def _segment_needs_model_revision(review: dict[str, Any]) -> bool:
    """Only spend another writer call on hard segment failures."""

    if not isinstance(review, dict):
        return False
    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    if int(scores.get("segment_scope", 8) or 0) < 8:
        return True
    if int(scores.get("segment_surface", 8) or 0) < 8:
        return True
    critical = review.get("critical_review") if isinstance(review.get("critical_review"), dict) else {}
    severity = critical.get("severity_summary") if isinstance(critical.get("severity_summary"), dict) else {}
    return bool(critical.get("hard_issues") or severity.get("has_hard_violation"))


def _game_genre_defaults(story: StoryState) -> dict[str, str]:
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    protagonist_ledger = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
    protagonist = next((c for c in story.characters if c.role == "protagonist"), None)
    game_id = str(protagonist_ledger.get("game_id") or "").strip()
    if not game_id and protagonist is not None:
        game_id = str(getattr(protagonist, "game_id", "") or "").strip()
    if not game_id:
        game_id = "未命名角色"
    class_path = str(protagonist_ledger.get("class_path") or "").strip()
    if not class_path:
        panel = getattr(protagonist, "game_panel", None) if protagonist is not None else None
        class_path = str(getattr(panel, "profession", "") or "").strip()
    if not class_path:
        class_path = "当前职业"
    return {"game_id": game_id, "class_path": class_path}


def _chapter_prompt_method_block(
    chapter_number: int,
    plan: dict[str, Any] | None,
    *,
    governance: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
) -> list[str]:
    plan = plan if isinstance(plan, dict) else {}
    spec = _chapter_prompt_spec(chapter_number, plan)
    taskbook = ensure_writing_taskbook(chapter_number, plan)
    taskbook_section = format_taskbook_prompt_section(taskbook)
    taskbook_scenes = taskbook.get("scenes") if isinstance(taskbook.get("scenes"), list) else []
    game_first_chapter = chapter_number == 1 and any(
        isinstance(scene, dict) and scene.get("key") == "entry_login" for scene in taskbook_scenes
    )
    whole_body_contract = first_chapter_whole_body_contract(game_genre=game_first_chapter)
    director_card = plan.get("web_game_director_card")
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    if not isinstance(director_card, dict):
        director_card = simulation_plan.get("web_game_director_card")
    lines = [
        "OUTPUT CONTRACT: prose only",
        "写手身份：你只负责把本章写成可读正文，不输出标题、编号、解释、大纲、JSON 或审稿结论。",
        "番茄白话风：用普通读者一眼能懂的话写，少用比喻和华丽修辞，少解释，多写动作、对话、面板、背包、耐久、药水和直接后果。",
        "后台词翻译：不要在正文或标题里写后台硬词；把它们改成“试一把、问一嘴、分开交、绕个柜台、包快满、药水不够、法杖快断”。",
        "情绪暗线：本章至少三次把角色的担心、试探、犹豫、侥幸或欲望落到动作、停顿、视线、手势和错开的回答上。",
        "主角开口硬规则：本章必须至少有一次可识别的主角口头对话，用“夜烬问/说/低声道”连接台词；不能只补一句装冷静，要说清一个理由、拒绝原因或下一步选择。",
        "口语化对话硬规则：每章至少写一轮连续问答，结构是别人问/催/抱怨 -> 夜烬正常回答并给原因 -> 对方接一句反应；台词可以短，但不能断成口令，不能每句都只有几个字。",
        "硬词清零：不要写“边界、底层逻辑、基准、推演、结算链、审稿、场景卡”。用“能不能走、规矩、底价、试一把、柜台说法”替代。",
        "职业背景落地：苏叶做过外包测试，只能体现为先看余额、数铜币、看蓝耗、摸法杖耐久、停一下再问价；不要把职业背景直接写成报表口吻、现金流、可量化、概率、止损线、变量、算法或后台数据异常。",
        "技术腔禁用：正文不要写测试员的职业病、边界、溢出、概率、变量、数据流、衰减曲线、测试用例、把收益拉到最高；改成看余额、问价、数铜、等蓝、摸耐久、背包快满。",
        "报告腔禁用：不要写“意味着、这说明、规则被撬开、常规掉落池、系统把溢出部分折算、模型跑不动”。发现异常时，写成背包格变满、提示闪一下、手指停住、旁人看不懂或主角先收东西。",
        "战斗白描禁词：不要写施法前摇、验证路线、验证逻辑、收益路径或抽象收益词；改成抬手慢半拍、蓝条少一截、背包快满、任务牌上还差几份。",
        "比喻限额：全章最多1处使用“像”，不要写仿佛、犹如、宛如；能写动作就写动作。",
        "写法施工单",
        "本章按“进入压力 -> 尝试动作 -> 即时反馈 -> 选择代价 -> 余波/小钩子”推进",
        "抽象判断必须落到具体物件或动作；对话必须改变筹码、知道的信息、价格、信任或能办的事。",
        taskbook_section,
        *(
            [
                "第一章整章写法契约：本次不用分段生成，按整章连续正文自然完成。",
                f"整章四拍：{whole_body_contract['beat_map']}",
                f"四拍要求：{_plain_prompt_json(whole_body_contract['beats'])}",
                f"白描与自然对话：{_plain_prompt_json([*whole_body_contract['style'], *whole_body_contract['dialogue']])}",
                f"整章禁区：{_plain_prompt_json(whole_body_contract['avoid'])}",
                "NPC窗口补足：章末必须有一个可见窗口，例如任务牌、修理铺、药剂柜台或职业导师木牌；主角可以办一件小事，但要像普通玩家一样排队、付费、拿东西，不公开异常来源。",
            ]
            if whole_body_contract
            else []
        ),
        "硬性质量闸门",
        f"一、视角：保持主角限知第三人称；章节：第{chapter_number}章。",
        "二、后台术语和事实矛盾词不得进正文。审核术语、规则术语、推演词不得入正文。",
        "三、主角不能听见玩家势力内部频道、他人私聊、后台记录或上帝视角宣告；这些信息只能通过可观察痕迹间接出现。",
        f"四、目标篇幅：{_plan_target_chars(plan)}。",
        f"五、本章导演简表：{_plain_prompt_json(_prose_grounded_writing_plan(plan))}",
        f"六、关键场景职责：{spec.required_surface}",
    ]
    if chapter_number == 1:
        lines[4:4] = [
            "第一章目标口语化：不要把目标写成后台硬词，要写成苏叶先试清楚这东西能不能让他活下去、赚到第一口气、藏住来源。",
            "第一章领先流：爽点要兑现成账本优势或下一步前置任务；是否完成任务、拿铜币、修杖或买药必须跟随项目账本/章节计划，未允许时不要擅自结算。",
        ]
    lines.extend(CRITICAL_PROMPT_RULES[:4])
    if isinstance(governance, dict):
        lines.append(_governance_prompt_section(governance))
    if isinstance(review, dict):
        lines.append(f"审稿摘要：{_plain_prompt_json(_compact_review_summary(review))}")
    if isinstance(director_card, dict):
        lines.append(format_web_game_director_card(director_card))
    return lines


def _web_game_writing_method_lines(chapter_number: int) -> list[str]:
    phase_hint = (
        "第一章重点是试清楚游戏规则靠不靠谱，并把第一笔优势藏住；是否领奖、修理或补给必须跟随项目账本，不能让外人看懂来源。"
        if chapter_number == 1
        else "本章重点是推进一个低级目标，让主角多摸到半步，不跳到高阶任务。"
    )
    return [
        "网游写法方法卡",
        phase_hint,
        "把本章写成一条玩家行动链：想做什么 -> 被什么卡住 -> 试一次 -> 花掉什么 -> 看见反馈 -> 拿到小进度 -> 下一步还差什么。",
        "游戏感来自办事过程，不来自大段解释：排队、价牌、药水冷却、法杖耐久、背包格、任务牌、NPC一句拒绝，都可以推动剧情。",
        "爽点写成“我已经暗中多拿一步”：别人还在排队、凑材料、缺蓝或误判，主角已经交掉一项、修好一件、买到补给或摸到新入口。",
        "面板用法：只显示本场马上要用的数字；提示后面接动作或后果，不接作者说明。",
        "对话用法：每段对话都让人知道一个价钱、前置条件、风险、误判或下一步；主角正常说话，不用两个字装冷静。玩家可以顺嘴抱怨，NPC可以把价钱、数量和后果说完整一点。游戏内人物不要说“门槛”，改说“前置任务”“条件没满足”“登记不了”。",
        "小样例：不要写“夜烬一直不交任务，只看门槛。”要写“夜烬排到柜台前，只交够清道夫的一份，把多出的毒腺留在背包底下。铜币到账后，他绕去修理铺补好法杖，又买了一瓶蓝药。旁边的人只当他运气好凑齐了材料，没人知道他背包里还压着下一轮路费。”",
    ]


def _governance_prompt_section(governance: dict[str, Any] | None) -> str:
    if not isinstance(governance, dict) or not governance:
        return "章节输入治理：未提供。表达层仍必须遵守推演事实，不得输出后台字段或审稿术语。"
    chapter_intent = governance.get("chapter_intent", {}) if isinstance(governance.get("chapter_intent"), dict) else {}
    rule_stack = governance.get("rule_stack", {}) if isinstance(governance.get("rule_stack"), dict) else {}
    runtime_context = governance.get("runtime_context", {}) if isinstance(governance.get("runtime_context"), dict) else {}
    governance_review = governance.get("governance_review")
    if not isinstance(governance_review, dict):
        governance_review = review_chapter_governance(governance)
    governance_gate = governance_quality_gate(governance)
    gate_instruction = (
        "治理门禁：先修治理层；当前 governance pass=false，不能把错误治理词、审稿词或后台标签带入正文。"
        if governance_gate.get("blocking")
        else "治理门禁：通过，可以进入正文写作或局部改稿。"
    )
    return "\n".join(
        [
            "## 章节输入治理",
            f"治理层审计：{json.dumps(governance_review, ensure_ascii=False)}",
            f"治理门禁：{json.dumps(governance_gate, ensure_ascii=False)}",
            gate_instruction,
            "表达权不等于事实权：推演层事实不可改，写作层只负责把事实写成场景、动作、对话、界面反馈。",
            f"本章必须写到：{json.dumps(chapter_intent.get('must_include', []), ensure_ascii=False)}",
            f"禁止提前写：{json.dumps(chapter_intent.get('must_avoid', []), ensure_ascii=False)}",
            f"章尾必须发生的改变：{chapter_intent.get('ending_change', '')}",
            f"运行上下文 runtime_context：{json.dumps(runtime_context, ensure_ascii=False)}",
            f"硬事实 hard_facts：{json.dumps(rule_stack.get('hard_facts', []), ensure_ascii=False)}",
            f"软建议 soft_guidance：{json.dumps(rule_stack.get('soft_guidance', []), ensure_ascii=False)}",
            f"诊断词禁止入正文 diagnostic_only：{json.dumps(rule_stack.get('diagnostic_only', []), ensure_ascii=False)}",
        ]
    )


def _governance_bundle_view(chapter_number: int, plan: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        chapter_number=chapter_number,
        chapter_title=str(plan.get("event_plan", {}).get("chapter_title", "")) if isinstance(plan.get("event_plan"), dict) else "",
        event_plan=plan.get("event_plan", {}) if isinstance(plan.get("event_plan"), dict) else {},
        next_outline=str(plan.get("event_plan", {}).get("next_focus", "")) if isinstance(plan.get("event_plan"), dict) else "",
        body="",
        chapter_summary={},
    )


def _build_world_state_review(issues: list[str], revision_plan: list[str]) -> dict[str, Any]:
    surfaces: dict[str, dict[str, Any]] = {}

    def add(surface: str, issue: str, patch: str) -> None:
        entry = surfaces.setdefault(surface, {"surface": surface, "issues": [], "suggested_patch": patch})
        if issue not in entry["issues"]:
            entry["issues"].append(issue)

    for issue in issues:
        text = str(issue)
        if any(token in text for token in ("汇率", "人民币", "金币", "银币", "铜币", "价格", "材料", "交易行", "市场", "手续费")):
            add(
                "economy",
                text,
                "更新 world_blueprint.living_world.economy 与 progression_ledger.economy，固化币制、价格锚点、手续费、库存和现实兑换边界。",
            )
        if any(token in text for token in ("坐标", "现实身份", "真人身份", "信息可见", "锁定", "隐藏天赋", "刷怪点")):
            add(
                "information_visibility",
                text,
                "更新 world_blueprint.living_world.information_visibility_rules，明确交易行/论坛/公会/NPC记录只能逐步暴露弱线索。",
            )
        if any(token in text for token in ("NPC", "洛婶", "艾伦", "铁栓", "老葛", "村长", "服务", "任务")):
            add(
                "npc_system",
                text,
                "更新 world_blueprint.npc_system，补齐命名NPC的地点、服务、价格/前置条件、利益诉求、口吻和信息边界。",
            )
        if any(token in text for token in ("职业", "装备", "法师", "短剑", "法杖", "等级", "经验", "耐久", "背包")):
            add(
                "progression_ledger",
                text,
                "更新 progression_ledger.protagonist/equipment，固化职业路线、等级经验、装备、耐久、技能和消耗品变化。",
            )
        if any(token in text for token in ("第一章", "节奏", "背景", "黄金三章", "冲突越级", "开篇")):
            add(
                "opening_arc",
                text,
                "更新 world_blueprint.opening_arc，收窄黄金三章背景预算、必写层、可写层和禁写层。",
            )

    patch_plan: list[str] = []
    for entry in surfaces.values():
        patch = str(entry["suggested_patch"])
        if patch not in patch_plan:
            patch_plan.append(patch)
    for item in revision_plan:
        text = str(item)
        if any(token in text for token in ("世界档案", "账本", "world_blueprint", "progression_ledger")) and text not in patch_plan:
            patch_plan.append(text)

    return {
        "pass": not surfaces,
        "issues": list(surfaces.values()),
        "patch_plan": patch_plan[:8],
        "affected_surfaces": list(surfaces.keys()),
    }


def _record_success(story: StoryState) -> None:
    for agent_name in ("CharacterAgent", "DirectorAgent", "WriterAgent", "MemoryAgent"):
        record_agent_runtime(story, agent_name, story.agent_settings.mode, "llm", story.current_chapter)


def _record_failure(story: StoryState, reason: str, chapter_number: int) -> None:
    for agent_name in ("CharacterAgent", "DirectorAgent", "WriterAgent", "MemoryAgent"):
        record_agent_runtime(story, agent_name, story.agent_settings.mode, "fallback", chapter_number, reason)


def _build_simulation_status(story: StoryState) -> dict:
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    agent_entries = {
        "character": story.agent_runtime.character_agent.model_dump(),
        "director": story.agent_runtime.director_agent.model_dump(),
        "writer": story.agent_runtime.writer_agent.model_dump(),
        "memory": story.agent_runtime.memory_agent.model_dump(),
    }
    fallback_agents = [name for name, entry in agent_entries.items() if entry.get("source") == "fallback"]
    return {
        "ok": not fallback_agents,
        "mode": "full" if not fallback_agents else "degraded",
        "fallback_agents": fallback_agents,
        "recent_events": list(story.agent_runtime.recent_events),
        "agents": agent_entries,
        "world_pulse": ledger.get("world_pulse", {}),
        "visibility_inbox": ledger.get("visibility_inbox", [])[-12:]
        if isinstance(ledger.get("visibility_inbox"), list)
        else [],
    }


def _failed_bundle(story: StoryState, chapter_number: int, reason: str = ""):
    from packages.story_core.engine import ChapterBundle

    bundle = ChapterBundle(
        chapter_number=chapter_number,
        body=f"生成失败：{reason}" if reason else "",
        chapter_title=f"第{chapter_number}章生成失败" if reason else "",
        cadence="measured",
        chapter_intent={},
        character_moves=[],
        memory_constraints={},
        event_plan={},
        chapter_seed=build_chapter_seed(story, chapter_number),
        simulation_plan={},
        world_events=[],
        scene_cards=[],
        simulation_status=_build_simulation_status(story),
        action_briefs=[],
        conflict_summary={},
        event_beat={},
        character_cards=build_character_cards(story),
        foreshadowing=build_foreshadowing(story, chapter_number),
        next_outline="",
        updated_story=story,
        chapter_summary={},
    )
    bundle.quality_report = validate_bundle(bundle.model_dump())
    if reason:
        bundle.quality_report["ok"] = False
        issues = list(bundle.quality_report.get("issues") or [])
        issues.append(reason)
        bundle.quality_report["issues"] = issues
    return bundle


class StoryOrchestrator:
    def _chat(
        self,
        story: StoryState,
        prompt: str,
        *,
        max_tokens: int,
        json_mode: bool,
        agent: str = "director",
        stage: str = "",
        timeout_seconds: int | None = None,
    ) -> tuple[str, str]:
        settings = resolve_openai_runtime_settings(agent)
        if not settings.api_key:
            return "", "Missing OPENAI_API_KEY"

        strategy = get_runtime_strategy_settings()
        model_by_agent = {
            "director": strategy.director_model or strategy.global_model or story.agent_settings.director_model,
            "writer": strategy.writer_model or strategy.global_model or story.agent_settings.writer_model,
            "memory": strategy.memory_model or strategy.global_model or story.agent_settings.memory_model,
        }
        model = model_by_agent.get(agent) or strategy.global_model or story.agent_settings.global_model or default_model_name()
        temperature = float(strategy.temperature) if strategy.temperature > 0 else float(story.agent_settings.temperature)
        if json_mode and max_tokens < 2000:
            max_tokens = 2000

        system_msg = "You are a novel simulation engine."
        if json_mode:
            system_msg += " Respond in json format only."
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "parameters": {
                "enable_thinking": False,
                "thinking_budget": 64,
            },
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        config = RetryConfig()
        if timeout_seconds is not None:
            config.timeout = int(timeout_seconds)
        if stage:
            report_generation_progress(f"{stage}：模型请求中（timeout={config.timeout}s）")

        try:
            response = post_json_with_retry(settings.base_url, "/chat/completions", payload, settings.api_key, config=config)
            if json_mode:
                parsed = parse_json_message_content(response)
                if parsed is None:
                    return "", "计划返回内容不是有效 JSON"
                if stage:
                    report_generation_progress(f"{stage}：模型返回")
                return json.dumps(parsed, ensure_ascii=False), ""
            text = _extract_text_message(response)
            if stage and text:
                report_generation_progress(f"{stage}：模型返回")
            return text, "" if text else "正文返回为空"
        except urllib.error.HTTPError as exc:
            if stage:
                error = f"{stage} model_request_failed:模型 HTTP {exc.code}"
                report_generation_progress(f"模型请求失败：{error}")
                return "", error
            return "", f"模型 HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            if stage:
                error = f"{stage} model_request_failed:{exc}"
                report_generation_progress(f"模型请求失败：{error}")
                return "", error
            return "", f"模型请求失败：{exc}"

    def _timed_chat(
        self,
        story: StoryState,
        prompt: str,
        *,
        max_tokens: int,
        json_mode: bool,
        agent: str = "director",
        stage: str,
    ) -> tuple[str, str]:
        started = perf_counter()
        text, error = self._chat(
            story,
            prompt,
            max_tokens=max_tokens,
            json_mode=json_mode,
            agent=agent,
        )
        elapsed = perf_counter() - started
        suffix = "失败" if error else "完成"
        report_generation_progress(f"{stage}耗时 {elapsed:.1f}s：{suffix}")
        return text, error

    def _plan_prompt(self, story: StoryState, chapter_number: int) -> str:
        snapshot = _story_snapshot(story)
        chapter_seed = build_chapter_seed(story, chapter_number)
        char_names = [c.name for c in story.characters if c.lifecycle_state == "active" and not c.frozen]
        if not _story_game_context(story, {}):
            return "\n".join(
                [
                    "请为中文长篇项目生成本章推演计划，只返回 JSON。",
                    f"目标章节：第{chapter_number}章",
                    f"章节阶段：{_opening_phase_name(chapter_number)}",
                    f"项目快照：{_plain_prompt_json(snapshot)}",
                    "输出字段：character_moves, chapter_intent, event_plan, memory_constraints, chapter_summary。",
                    "event_plan 必须包含 chapter_title, turn, pivot, collision, ordered_actions, exposition_beats, npc_beats, quest_beats, location_beats, world_reactions, stakes, next_focus, explicit_chapter_end_hook, chapter_end_hook。",
                    "chapter_end_hook 使用结构：{type, strength, content}；type 只能是危机钩、悬念钩、渴望钩、反转钩、余韵钩；strength 只能是 strong、medium、weak。",
                    "要求：动作具体，焦点明确，事件链短但有效，不要写正文。",
                ]
            )
        web_game_rules = web_game_review_rules()
        phase_name = _opening_phase_name(chapter_number)
        return "\n".join(
            [
                "网游计划写法：先按 writing_contract.genre_craft.action_chain 排出一条玩家行动链；不要只列设定，要让目标、卡点、尝试、消耗、反馈、小进度和下一步都能写成场景。",
                "请为中文网文项目生成本章推演计划，只返回 JSON。",
                f"目标章节：第{chapter_number}章",
                f"章节阶段：{_opening_phase_name(chapter_number)}",
                f"项目快照：{_plain_prompt_json(snapshot)}",
                f"生成前世界推演契约：{_plain_prompt_json(chapter_seed)}",
                "输出字段如下，注意 character_moves 必须是对象数组：",
                '  character_moves: [{"name": "角色名", "goal": "目标", "emotion": "情绪", "action": "行动", "priority": 数字}]',
                "  chapter_intent: {chapter_title, cadence, next_focus, primary_conflict, secondary_conflict}",
                "  event_plan.chapter_satisfaction: {emotion_target, core_event, obstacle, visible_payoff, outsider_misread, state_change, next_hook}",
                "  event_plan.chapter_end_hook: {type: 危机钩|悬念钩|渴望钩|反转钩|余韵钩, strength: strong|medium|weak, content: 章末具体诱饵}",
                "  event_plan: {chapter_title, turn, pivot, collision, ordered_actions: [{name, goal, emotion, action, priority}], exposition_beats: [本章要自然写进正文的背景节拍], npc_beats: [NPC服务/信息边界/任务钩子], quest_beats: [任务链阶段/奖励/代价], location_beats: [地图资源/风险/玩家密度], world_reactions: [世界会如何反应], stakes, next_focus}",
                "  memory_constraints: {must_keep_facts, unresolved_threads, protected_characters, protected_foreshadowing, author_constraints, current_focus, conflict_anchor, event_guardrail, ledger_updates}",
                "  chapter_summary: {summary, facts, unresolved_threads, next_focus, chapter_title}",
                "JSON长度要求：所有数组每项不超过80字；不要输出推理过程、不要重复字段、不要补充说明。",
                f"活跃角色：{', '.join(char_names)}",
                f"网游插件审稿规则：{_plain_prompt_json(web_game_rules)}",
                "硬性要求：必须使用 world_facts 里的黄金三章、活世界和世界制度信息。",
                "硬性要求：必须优先遵守生成前世界推演契约里的 writing_contract、chapter_contract、simulation_axes、current_state 和 continuity。",
                "写作合同用法：event_plan 的 ordered_actions、npc_beats、quest_beats、location_beats、next_focus 先服务 writing_contract.satisfaction_loop、current_level、progression_stage、action_chain 和 emotional_arc，再处理 allowed_progress 与 forbidden_unlocks。",
                "爽文结构硬规则：chapter_satisfaction 必须写清本章交付的情绪、具体事件、阻碍、可见收益、外人误判、状态变化和章尾下一步；没有这七项就不要进入正文。",
                "情绪计划用法：character_moves 和 ordered_actions 不要只写功能性动作；把 emotional_arc 拆进章首、章中、章末，落到动作、停顿、视线、花钱肉疼、怕亏、后怕或松一口气。",
                "背景预算硬规则：必须遵守 world_facts 里的第N章背景预算；只展开必写层和少量可写层，禁写层不得进入本章正戏。",
                "信息可见硬规则：计划里的市场柜台、公共频道、玩家势力频道、NPC记录只能暴露规则允许的信息，不得直接公开坐标、现实身份或隐藏天赋。",
                "长篇要求：必须参考 world_facts 里的第一卷规划、卷纲阶段、长期线索和成长/经济/压力/任务账本；不要只顾本章爽点破坏长期路线。",
                "ledger_updates 必须只记录本章结束后的状态变化，例如等级、经验、游戏币、装备耐久、任务进度、势力关注、市场异常、金手指暴露度。",
                "角色面板硬规则：主角最新游戏面板属于角色群像的一部分；每章结束必须让 ledger_updates 能同步出等级、职业、经验、货币、装备、背包、任务和风险状态。",
                "经济连续性硬规则：必须继承 latest_facts、relevant_memories、progression_ledger 里的材料价格锚点、主角处理价格、扣费、最终余额和库存；不得重新发明“昨天价格”或把价格锚点改成另一套。",
                "职业连续性硬规则：现实职业和游戏职业必须分层；苏叶现实职业固定为前外包测试员，夜烬游戏路线固定为元素法师学徒/元素法师，不得写成战士、刺客或短剑主战。",
                "装备账本硬规则：任何购买、替换、修理、耐久变化、消耗品购买和关键掉落，都必须写入 ledger_updates.equipment 或 ledger_updates.economy.inventory，并在章节摘要留下事实。",
                "NPC设定硬规则：命名NPC首次或重点出场必须交代地点、职责/服务、利益诉求或口吻、能知道什么/不知道什么；NPC不能只是发任务的牌子。",
                "章节摘要硬规则：chapter_summary.facts 与 memory_constraints.must_keep_facts 必须记录本章出现的关键进度/职业/装备/NPC锚点，包括任务进度、经验变化、关键库存、职业路线、装备耐久、下一步前置任务和NPC能办什么。",
                "冲突阶段硬规则：必须优先遵守 world_facts 里的“第N章冲突模式/禁止冲突”；冲突要从游戏规则、资源稀缺、前置任务、可见痕迹、玩家势力利益和NPC柜台规矩长出来，不要套玄幻式抢机缘。",
                "第1-3章必须按黄金三章职责设计，尤其第1章要给出至少4条 exposition_beats：现实压力、主角工作背景、登录建号、游戏ID/职业面板、第一次领先验证、下一步成长目标。",
                "第一章主角背景必须包含现实职业/工作状态/现实技能来源；不要只写缺钱、房租、医疗账单。",
                "第一章金手指必须先铺触发条件或伏笔，再首次验证；不能开场直接出现完整隐藏面板。",
                "网游身份硬规则：计划中必须区分现实姓名和游戏ID；第1章要在登录/建号/角色面板里写出主角游戏ID，游戏内称呼优先使用游戏ID。",
                "第一章冲突不要设计成正面对抗或争核心资源，应设计成现实压力、隐藏优势靠不靠谱、第一次领先验证和下一步任务/装备/技能前置。",
                "第一章表面必写：短角色面板必须出现职业栏、等级、经验、生命/法力、新手法杖或基础技能；首次试怪必须出现“千倍爆率”或“掉落判定×1000”的可见马脚。",
                "第一章领先流硬规则：低级材料必须转成账本优势或下一步前置任务；是否交任务、拿铜币、修装备、买药水必须跟随项目账本/章节计划，未允许时只写前置条件和预期。",
                "第一章收敛硬规则：NPC、交易行、论坛和公会不能看懂隐藏机制；NPC是否办理小额任务、修理或补给由项目账本决定，交易行和公会只能作为弱线索或环境压力。",
                "第一章禁止规划现实债主正面登场、玩家势力据点视角、完整追查、修理铺/药剂铺/职业大厅多视角连环戏。",
                "第一章节奏必须留白：不要把登录、金手指发现、大量刷怪、完整材料处理、市场玩家正面登场、玩家势力追过来全部压进一章；本章只完成第一次领先验证和一个下一步成长目标。",
                "术语统一：隐藏优势统一写“千倍爆率”；不要输出“1000倍爆率”。若必须表示计算倍率，写“掉落判定×1000”。",
                "第2章冲突优先从刷怪路线、补给/耐久、NPC任务前置、装备/技能前置、普通玩家进度对比生成；第3章再升级到路线竞争、职业试炼前置、资源点秩序或玩家势力外围试探。",
                "市场可见性规则：低级材料是大型服务器噪音，只暴露普通价格、数量和时间戳等弱线索；不能单次暴露坐标、身份或刷怪点。玩家势力介入必须来自重复模式、稀有物、公告榜单、资源点目击、NPC任务异常或多源记录汇总。",
                "exposition_beats 必须能被写作 Agent 写成登录界面、现实细节、公共频道零散噪音、任务柜台界面、玩家闲聊、公告或场景观察。",
                "必须给出至少2条 world_reactions，但第1章只允许普通玩家表层误读、队伍/背包/前置任务等环境阻力，不允许正式市场/玩家势力/公共频道追过来。",
                "如果题材是网游/游戏系统流，第2章起 event_plan 必须给出至少1条 npc_beats、1条 quest_beats、1条 location_beats；NPC不能只讲设定，必须提供服务、前置条件、任务反馈或能知道什么/不知道什么。",
                "NPC硬规则：只能优先使用 world_facts 已建档的命名 NPC，例如灰烬村村长、药剂师洛婶、职业导师艾伦、仓库管理员铁栓、修理匠老葛；不要发明“新手村导师”“杂货商老约翰”这类无档案泛 NPC。",
                "角色要求：每个主要角色都必须有私心、误判、底线或恐惧；character_moves 不能只写功能性动作，必须体现角色档案里的动机、秘密、关系张力和说话/处事方式。",
                "关系要求：如果角色之间已有 trust/tension/bond，本章计划必须让至少一组关系发生可感知变化，例如试探、拉拢、隐瞒、交易、误会或威胁。",
                "不要让世界全知全能，反应必须通过可观察痕迹逐步逼近主角。",
                "要求：动作具体，焦点明确，事件链简短但有效，不要写正文。",
            ]
        )

    def _body_prompt(self, story: StoryState, chapter_number: int, plan: dict) -> str:
        plan = plan if isinstance(plan, dict) else {}
        plan = {**plan, "writing_taskbook": ensure_writing_taskbook(chapter_number, plan, genre=story.genre, style=story.style)}
        hard_rules = compact_list(story.author_constraints, max_items=18, item_chars=220)
        living_world = _priority_world_facts(story.world_facts, max_items=42, item_chars=220)
        chapter_seed = build_chapter_seed(story, chapter_number)
        opening_rules = _opening_writer_rules(chapter_number)
        web_game_rules = web_game_review_rules()
        style_rules = anti_ai_style_rules()
        style_guidance = plan.get("style_guidance", {})
        is_game = _story_game_context(story, plan)
        if is_game:
            game_defaults_for_seed = _game_genre_defaults(story)
            chapter_seed_text = json.dumps(chapter_seed, ensure_ascii=False)
            chapter_seed_text = (
                chapter_seed_text.replace("元素法师学徒/元素法师", game_defaults_for_seed["class_path"])
                .replace("元素法师学徒", game_defaults_for_seed["class_path"])
                .replace("元素法师", game_defaults_for_seed["class_path"])
            )
            chapter_seed_for_prompt = _plain_prompt_payload(json.loads(chapter_seed_text))
        else:
            chapter_seed_for_prompt = {}
        opening_rules = _opening_writer_rules(chapter_number) if is_game else []
        if is_game:
            game_defaults_for_rules = _game_genre_defaults(story)
            opening_rules = [
                str(rule)
                .replace("元素法师学徒/元素法师", game_defaults_for_rules["class_path"])
                .replace("元素法师学徒", game_defaults_for_rules["class_path"])
                .replace("元素法师", game_defaults_for_rules["class_path"])
                for rule in opening_rules
            ]

        method_block = _chapter_prompt_method_block(
            chapter_number,
            plan,
            governance=plan.get("governance"),
        )
        if is_game:
            method_block = [
                *method_block[:3],
                *_web_game_writing_method_lines(chapter_number),
                *method_block[3:],
            ]

        game_specific: list[str] = []
        if is_game:
            game_defaults = _game_genre_defaults(story)
            web_game_rules_for_prompt = [
                str(rule)
                .replace("元素法师学徒/元素法师", game_defaults["class_path"])
                .replace("元素法师学徒", game_defaults["class_path"])
                .replace("元素法师", game_defaults["class_path"])
                .replace("法师战斗", "职业战斗")
                for rule in web_game_rules
            ]
            game_specific.extend(
                [
                    f"游戏主角默认信息：游戏ID={game_defaults['game_id']}；职业路线={game_defaults['class_path']}。战斗、任务和成长必须围绕该职业路线展开，不得写成固定职业模板。",
                    f"网游插件审稿规则：{_plain_prompt_json(web_game_rules_for_prompt)}",
                    "原始推演结构已经压缩进写作任务书；不要读取或复述后台结构名。",
                    (
                        "第一章网游要求：NPC、交易行、论坛、公会只作为下一章钩子或环境入口，不强制正面出场；本章只写登录、小验证和下一步决定。"
                        if chapter_number == 1
                        else "网游插件要求：每章至少出现一个能改变局势的 NPC 或 NPC 柜台；NPC要有自己的口吻、职责、可见信息和限制，不能全知全能。"
                    ),
                    f"术语统一要求：正文统一写“千倍爆率”，不要混用“1000倍爆率”；计算提示可写“掉落判定×1000”。",
                ]
            )

        phase_name = _opening_phase_name(chapter_number) if is_game else (
            "开篇章节：立人物、立处境、立目标、完成第一次有效行动"
            if chapter_number == 1
            else "常规连载章节：目标、行动、反馈和章末新压力"
        )

        return "\n".join(
            [
                "根据下面的推演计划，写出一章完整中文网文正文。",
                *method_block,
                f"题材：{story.genre}",
                f"风格：{story.style}",
                f"章节阶段：{phase_name}",
                f"生成前世界推演契约：{_plain_prompt_json(chapter_seed_for_prompt)}",
                f"硬性世界规则与写作约束：{_plain_prompt_json(hard_rules)}",
                f"活世界状态、黄金三章和反应机制：{_plain_prompt_json(living_world)}",
                f"黄金三章/开篇写作规则：{_plain_prompt_json(opening_rules)}",
                f"反AI味写作协议：{_plain_prompt_json(style_rules)}",
                f"写作教练 Style Coach：{_plain_prompt_json(style_guidance)}",
                *game_specific,
                "网游章节写法：正文按 writing_contract.genre_craft.action_chain 走，先写代价，再写收获；每个面板/提示后面接主角选择或现场后果。",
                "本章写作合同用法：执行生成前世界推演契约里的 writing_contract.satisfaction_loop、scene_plan、emotional_arc 和 genre_craft；正文按 current_level 和 progression_stage 写，只写 allowed_progress；条件不满足时只能看见、询问或被拒。",
                "爽点落地写法：每章必须有一个可见收益闭环，一个外人误判，一个章末下一步。收益要写成动作和结果，例如递材料、收铜、修好、买入、技能入包、入口试通；不要写成路线分析或报告口吻。",
                "情绪落点写法：每个主要场景至少一拍情绪，但不要抒情；用停顿、看余额、数铜币、摸耐久、话说一半、没忍住回头、松一口气又收住来写。",
                f"篇幅要求：{_plan_target_chars(plan)}，不要写成摘要，不要只写几个片段。",
                "必须把计划里的事件完整写成连续正文，可以分段，但不要输出大纲、标题列表、JSON 或解释。",
            ]
        )

    def _revision_prompt(self, story: StoryState, chapter_number: int, body: str, plan: dict, review: dict) -> str:
        plan = plan if isinstance(plan, dict) else {}
        plan = {**plan, "writing_taskbook": ensure_writing_taskbook(chapter_number, plan, genre=story.genre, style=story.style)}
        review = review if isinstance(review, dict) else {}
        forbidden_terms = _revision_forbidden_terms(review, plan)
        fix_checklist = _revision_fix_checklist(review)
        style_guidance = plan.get("style_guidance", {})
        governance_section = _governance_prompt_section(plan.get("governance"))
        target_chars = _plan_target_chars(plan)
        scene_repair_plan = review.get("scene_repair_plan") if isinstance(review.get("scene_repair_plan"), dict) else {}
        if not scene_repair_plan:
            scene_repair_plan = build_scene_contract_repair_plan(review, plan.get("scene_cards", []))

        method_block = _chapter_prompt_method_block(
            chapter_number,
            plan,
            governance=plan.get("governance"),
            review=review,
        )

        game_specific_revision = _story_game_context(story, plan)
        game_revision_lines = (
            [
                "改稿限制：不得随意改变等级、经验、货币、掉落和任务结果；但如果是第一章节奏过载，必须删除或后移材料处理、市场玩家、玩家势力、公共频道等越界世界反应。",
                "第一章改稿保护：修领先流问题时，不得删除现实职业来源、登录/建号、游戏ID夜烬、职业选择、元素法师学徒、短角色面板、基础火球术、混沌之种或掉落判定×1000。",
            ]
            if game_specific_revision
            else ["改稿限制：不得随意改变已建立的人物、地点、时间、物件、承诺和事件结果。"]
        )

        return "\n".join(
            [
                "下面这章小说正文没有通过审稿，请在不改变核心剧情事实的前提下自动改稿。",
                *method_block,
                f"章节：第{chapter_number}章",
                governance_section,
                f"审稿摘要：{_plain_prompt_json(_compact_review_summary(review))}",
                f"写作教练 Style Coach：{_plain_prompt_json(style_guidance)}",
                f"硬性修复清单：{_plain_prompt_json(fix_checklist)}",
                f"scene_contract_repair_plan：{_plain_prompt_json(scene_repair_plan)}",
                f"正文禁词清单（逐字删除，不能照抄到改稿正文）：{json.dumps(forbidden_terms, ensure_ascii=False)}",
                f"写作任务书改稿协议：\n{format_taskbook_prompt_section(plan.get('writing_taskbook'), include_all_scenes=True)}",
                f"推演简表：{_plain_prompt_json(_prose_grounded_writing_plan(plan))}",
                f"篇幅要求：扩写到{target_chars}。",
                *game_revision_lines,
                "事实锁硬规则：任务书和场景事实里的职业、余额、库存、任务、装备和NPC能知道什么/不知道什么不得被润色改动；若不能确定，保留原文事实。",
                "如果审稿指出字数偏少，必须扩写到目标篇幅，增加场景、对话、行动过程、心理和题材规则细节，不要只重复原文。",
                "如果 scene_contract_repair_plan 非空，必须只重写失败场景：只补 failed_scenes 对应场景缺失的可见后果，其他场景保持事实、顺序和账本不变，只做必要衔接。",
                "如果审稿指出情绪锚点不足，改稿必须新增至少三处分散情绪锚：章首怕亏或肉疼，中段受伤/排队/NPC规矩带来的烦躁或迟疑，章末松一口气又不敢松；每处都必须落到动作、停顿、看余额、摸耐久、数铜币或半句对话。",
                "如果审稿指出命名NPC服务缺失，改稿必须补一个有姓名和岗位边界的柜台场景：登记员、修理匠、药剂师或职业导师只能办理自己岗位内的事，并通过一句自然对话改变主角下一步选择。",
                "如果审稿指出场景卡缺失，改稿必须把缺失短语对应事件正面写出来，不能用一句总结带过；例如连杀两只怪、交任务换铜币、修理扣费、买药水，都要有动作、对话、面板或背包变化。",
                "如果正文禁词清单非空，改稿后必须逐项自检，保证禁词不再出现在小说正文里；只能保留在本提示词中，不能输出到正文。",
                "改完后自检：硬性修复清单逐条完成；正文禁词清单逐项清零；任务书必写内容必须全部表面化；不要输出自检说明。",
                "只输出改稿后的完整小说正文，不要解释，不要列大纲。",
                f"原正文：\n{body}",
            ]
        )

    def _write_chapter_in_segments(
        self,
        story: StoryState,
        chapter_number: int,
        plan: dict,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        specs = build_segment_specs(chapter_number, plan)
        segments: list[str] = []
        segment_reviews: list[dict[str, Any]] = []

        for index, spec in enumerate(specs, start=1):
            report_generation_progress(f"分段写作中 {index}/{len(specs)}：{spec.title}")
            segment_text, segment_error = self._timed_chat(
                story,
                build_segment_prompt(
                    chapter_number=chapter_number,
                    spec=spec,
                    plan=plan,
                    previous_segments=segments,
                ),
                max_tokens=2600,
                json_mode=False,
                agent="writer",
                stage=f"分段写作 {index}/{len(specs)}：{spec.title}",
            )
            if segment_error or not segment_text.strip():
                return "", segment_error or f"segment_empty:{spec.key}", segment_reviews

            segment_text = trim_segment_to_contract(
                spec,
                _sanitize_generated_body(segment_text),
                chapter_number=chapter_number,
            )
            review = review_segment_output(spec, segment_text, chapter_number=chapter_number)
            if not review.get("pass") and _segment_needs_model_revision(review):
                report_generation_progress(f"局部改稿中 {index}/{len(specs)}：{spec.title}")
                original_segment_text = segment_text
                original_segment_review = review
                revised_text, revised_error = self._timed_chat(
                    story,
                    build_segment_revision_prompt(
                        spec,
                        segment_text,
                        review,
                        previous_segments=segments,
                        governance=plan.get("governance") if isinstance(plan, dict) else None,
                    ),
                    max_tokens=2600,
                    json_mode=False,
                    agent="writer",
                    stage=f"局部改稿 {index}/{len(specs)}：{spec.title}",
                )
                if not revised_error and revised_text.strip():
                    candidate_segment_text = trim_segment_to_contract(
                        spec,
                        _sanitize_generated_body(revised_text),
                        chapter_number=chapter_number,
                    )
                    candidate_segment_review = review_segment_output(spec, candidate_segment_text, chapter_number=chapter_number)
                    segment_safety = choose_best_segment_revision(
                        original_text=original_segment_text,
                        original_review=original_segment_review,
                        candidate_text=candidate_segment_text,
                        candidate_review=candidate_segment_review,
                    )
                    segment_text = str(segment_safety["text"])
                    review = dict(segment_safety["review"])
                    review["segment_revision_safety"] = segment_safety["report"]

            segment_reviews.append(review)
            segments.append(segment_text)

        body = _sanitize_generated_body(merge_segment_outputs(segments))
        return body, "", segment_reviews

    def _use_segmented_writing(self, chapter_number: int, plan: dict) -> bool:
        """Segment drafting is opt-in only.

        Segmenting remains available for experiments and focused tests, but the
        production default is whole-chapter drafting. The segment pipeline has a
        failure mode where later segments restart the chapter and merge into a
        duplicated draft, so it should not be the default writer path.
        """

        settings = plan.get("writing_settings") if isinstance(plan, dict) else None
        if isinstance(settings, dict):
            return bool(settings.get("use_segmented_writing"))
        return False

    def refresh_revised_bundle_metadata(self, base_story: StoryState, bundle: Any) -> Any:
        """Rebuild summary, ledger and memory surfaces after latest-chapter revision."""
        refreshed_bundle = bundle.model_copy(deep=True)
        refreshed_bundle.body = _sanitize_generated_body(refreshed_bundle.body)
        chapter_number = refreshed_bundle.chapter_number
        working_story = base_story.model_copy(deep=True)
        working_story.current_chapter = chapter_number

        memory_constraints = _normalize_memory_constraints(refreshed_bundle.memory_constraints, working_story)
        # Revision can invalidate old planned facts and ledger values; rebuild them from the revised body.
        memory_constraints["must_keep_facts"] = []
        memory_constraints["ledger_updates"] = {}
        chapter_summary_data = _normalize_chapter_summary(refreshed_bundle.chapter_summary, chapter_number)
        continuity_anchors = _inject_continuity_anchors(memory_constraints, chapter_summary_data, refreshed_bundle.body)

        updated_story = working_story.model_copy(deep=True)
        conflict_summary = refreshed_bundle.conflict_summary if isinstance(refreshed_bundle.conflict_summary, dict) else {}
        event_beat = refreshed_bundle.event_beat if isinstance(refreshed_bundle.event_beat, dict) else {}
        apply_post_chapter_updates(
            updated_story,
            refreshed_bundle.body,
            chapter_number,
            conflict_summary=conflict_summary,
            event_beat=event_beat,
        )
        _apply_ledger_updates(updated_story, memory_constraints.get("ledger_updates", {}))
        _sync_character_game_panels(updated_story, chapter_number)
        advance_world_pulse(updated_story, chapter_number=chapter_number)
        maybe_update_arc_recap(updated_story, chapter_number)

        if updated_story.chapter_summaries:
            latest_summary = updated_story.chapter_summaries[-1]
            latest_summary.summary = chapter_summary_data.get("summary") or compact_text(refreshed_bundle.body, 220)
            latest_summary.facts = _merge_unique_compact([], continuity_anchors or latest_summary.facts, max_items=14, item_chars=150)
            latest_summary.unresolved_threads = chapter_summary_data.get("unresolved_threads") or latest_summary.unresolved_threads
            latest_summary.next_focus = chapter_summary_data.get("next_focus") or latest_summary.next_focus
            latest_summary.chapter_title = chapter_summary_data.get("chapter_title") or latest_summary.chapter_title
            if isinstance(refreshed_bundle.chapter_intent, dict):
                primary = refreshed_bundle.chapter_intent.get("primary_conflict")
                secondary = refreshed_bundle.chapter_intent.get("secondary_conflict")
                if isinstance(primary, dict):
                    latest_summary.primary_conflict = primary
                if isinstance(secondary, dict):
                    latest_summary.secondary_conflict = secondary
            latest_summary.event_beat = event_beat
            latest_summary.cadence = refreshed_bundle.cadence  # type: ignore[assignment]
            refreshed_bundle.chapter_title = latest_summary.chapter_title
            refreshed_bundle.chapter_summary = latest_summary.model_dump()

        refreshed_bundle.memory_constraints = memory_constraints
        refreshed_bundle.updated_story = updated_story
        refreshed_bundle.simulation_status = _build_simulation_status(updated_story)
        refreshed_bundle.character_cards = build_character_cards(updated_story)
        refreshed_bundle.foreshadowing = build_foreshadowing(updated_story, chapter_number)
        refreshed_bundle.next_outline = plan_next_outline(
            updated_story,
            chapter_number,
            conflict_summary=conflict_summary,
            cadence=refreshed_bundle.cadence,
        )
        return refreshed_bundle

    def revise_chapter_body(
        self,
        story: StoryState,
        bundle,
        review: dict,
        instructions: list[str] | None = None,
    ) -> tuple[str, dict, str]:
        revision_review = dict(review or {})
        revision_plan = list(revision_review.get("revision_plan") or [])
        for instruction in instructions or []:
            clean = str(instruction).strip()
            if clean and clean not in revision_plan:
                revision_plan.append(clean)
        revision_review["revision_plan"] = revision_plan
        original_quality_seed = bundle.model_dump()
        original_quality = _merge_writing_review_quality(validate_bundle(original_quality_seed), revision_review)
        plan = {
            "character_moves": bundle.character_moves,
            "chapter_intent": bundle.chapter_intent,
            "event_plan": bundle.event_plan,
            "memory_constraints": bundle.memory_constraints,
            "chapter_seed": getattr(bundle, "chapter_seed", {}),
            "governance": build_chapter_governance(story, bundle, chapter_number=bundle.chapter_number),
        }
        patched_body, patch_report = apply_expression_patches_from_review(bundle.body, revision_review)
        if patch_report.get("applied"):
            patched_body = _sanitize_generated_body(patched_body)
            quality_seed = bundle.model_dump()
            quality_seed["body"] = patched_body
            patched_review = _review_chapter_body(
                bundle.chapter_number,
                patched_body,
                bundle.event_plan,
                story.world_facts,
                getattr(bundle, "simulation_plan", {}),
                getattr(bundle, "world_events", []),
                getattr(bundle, "scene_cards", []),
            )
            patched_review["expression_patch_report"] = patch_report
            patched_quality = _merge_writing_review_quality(validate_bundle(quality_seed), patched_review)
            patch_safety = choose_best_revision(
                original_body=bundle.body,
                original_quality=original_quality,
                candidate_body=patched_body,
                candidate_quality=patched_quality,
            )
            selected_patch_quality = dict(patch_safety["quality"])
            selected_patch_quality["revision_safety"] = patch_safety["report"]
            patched_body = str(patch_safety["body"])
            patched_quality = selected_patch_quality
            cut_review = patched_review.get("adversarial_cut_review", {})
            if patch_safety.get("accepted") and (patched_review.get("pass") or (isinstance(cut_review, dict) and cut_review.get("pass"))):
                record_agent_runtime(
                    story,
                    "ExpressionPatch",
                    "deterministic",
                    "local",
                    story.current_chapter,
                )
                return patched_body, patched_quality, ""

        revised_body, error = self._timed_chat(
            story,
            self._revision_prompt(story, bundle.chapter_number, bundle.body, plan, revision_review),
            max_tokens=7000,
            json_mode=False,
            agent="writer",
            stage=f"自动改稿 第{bundle.chapter_number}章",
        )
        if error or not revised_body.strip():
            return "", {}, error or "revision_empty"

        revised_body = _sanitize_generated_body(revised_body)
        quality_seed = bundle.model_dump()
        quality_seed["body"] = revised_body
        writing_review = _review_chapter_body(
            bundle.chapter_number,
            revised_body,
            bundle.event_plan,
            story.world_facts,
            getattr(bundle, "simulation_plan", {}),
            getattr(bundle, "world_events", []),
            getattr(bundle, "scene_cards", []),
        )
        quality_report = _merge_writing_review_quality(validate_bundle(quality_seed), writing_review)
        safety = choose_best_revision(
            original_body=bundle.body,
            original_quality=original_quality,
            candidate_body=revised_body,
            candidate_quality=quality_report,
        )
        selected_quality = dict(safety["quality"])
        selected_quality["revision_safety"] = safety["report"]
        revised_body = str(safety["body"])
        quality_report = selected_quality
        record_agent_runtime(
            story,
            "WriterAgent",
            story.agent_settings.mode,
            "llm",
            story.current_chapter,
        )
        return revised_body, quality_report, ""

    def generate_next_chapter(self, story: StoryState):
        from packages.story_core.engine import ChapterBundle

        chapter_number = story.current_chapter + 1
        working_story = story.model_copy(deep=True)
        working_story.current_chapter = chapter_number

        report_generation_progress("剧情计划生成中...")
        plan_text, plan_error = self._timed_chat(
            working_story,
            self._plan_prompt(working_story, chapter_number),
            max_tokens=8000,
            json_mode=True,
            agent="director",
            stage="剧情计划生成",
        )
        if plan_error:
            _record_failure(working_story, f"统一推演计划失败：{plan_error}", chapter_number)
            return _failed_bundle(working_story, chapter_number)

        plan = json.loads(plan_text)
        action_briefs = _normalize_moves(plan.get("character_moves"))
        chapter_intent = _normalize_intent(plan.get("chapter_intent"))
        event_plan = _normalize_event_plan(plan.get("event_plan"), chapter_number, working_story)
        memory_constraints = _normalize_memory_constraints(plan.get("memory_constraints"), working_story)
        chapter_summary_data = _normalize_chapter_summary(plan.get("chapter_summary"), chapter_number)
        chapter_seed = build_chapter_seed(working_story, chapter_number)
        simulation_plan = build_chapter_simulation_plan(
            working_story,
            chapter_number,
            event_plan=event_plan,
            memory_constraints=memory_constraints,
            chapter_seed=chapter_seed,
        ).model_dump()
        simulated_events = simulate_world_events(
            working_story,
            chapter_number,
            chapter_seed=chapter_seed,
            simulation_plan=simulation_plan,
        )
        world_events = [event.model_dump() for event in simulated_events]
        scene_cards = [
            card.model_dump()
            for card in select_scene_cards(
                simulated_events,
                chapter_seed=chapter_seed,
                simulation_plan=simulation_plan,
            )
        ]
        style_guidance = build_style_guidance(
            genre=working_story.genre,
            chapter_number=chapter_number,
            world_events=world_events,
            scene_cards=scene_cards,
        )
        scene_cards = enrich_performance_cards(scene_cards, style_guidance)
        simulation_plan = {
            **simulation_plan,
            "style_guidance": style_guidance,
        }

        conflict_summary = build_conflict_summary(working_story, action_briefs)
        cadence = chapter_intent.get("cadence") or compute_chapter_cadence(working_story, action_briefs, conflict_summary)
        event_beat = build_event_beat(conflict_summary)

        writer_plan = {
            "character_moves": action_briefs,
            "chapter_intent": chapter_intent,
            "event_plan": event_plan,
            "memory_constraints": memory_constraints,
            "chapter_seed": chapter_seed,
            "simulation_plan": simulation_plan,
            "world_events": world_events,
            "scene_cards": scene_cards,
            "style_guidance": style_guidance,
        }
        writer_plan["governance"] = build_chapter_governance(
            working_story,
            _governance_bundle_view(chapter_number, writer_plan),
            chapter_number=chapter_number,
        )
        writer_plan["writing_taskbook"] = ensure_writing_taskbook(
            chapter_number,
            writer_plan,
            genre=working_story.genre,
            style=working_story.style,
        )

        report_generation_progress("正文生成中...")
        report_generation_progress("整章正文生成中...")
        segment_reviews: list[dict[str, Any]] = []
        segment_pipeline_used = self._use_segmented_writing(chapter_number, writer_plan)
        if segment_pipeline_used:
            body, body_error, segment_reviews = self._write_chapter_in_segments(
                working_story,
                chapter_number,
                writer_plan,
            )
        else:
            body, body_error = "", ""
        if body_error or not body.strip():
            segment_reviews = []
            if segment_pipeline_used:
                report_generation_progress("分段生成失败，回退整章生成中...")
            segment_pipeline_used = False
            body, body_error = self._timed_chat(
                working_story,
                self._body_prompt(
                    working_story,
                    chapter_number,
                    writer_plan,
                ),
                max_tokens=7000,
                json_mode=False,
                agent="writer",
                stage=f"整章写作 第{chapter_number}章",
            )
        if body_error or not body.strip():
            _record_failure(working_story, f"统一写作失败：{body_error or '正文为空'}", chapter_number)
            return _failed_bundle(working_story, chapter_number)
        body = _sanitize_chapter_output(body, chapter_number=chapter_number, scene_cards=scene_cards)

        if _should_expand_chapter(body, writer_plan):
            report_generation_progress("章节扩写中...")
            expanded_body, expand_error = self._timed_chat(
                working_story,
                "\n".join(
                    [
                        "下面这章正文太短，请在不改变剧情事实和结尾钩子的前提下扩写成完整网文章节。",
                        f"目标篇幅：{TARGET_CHAPTER_CHARS}。",
                        "扩写重点：补足场景调度、战斗过程、任务/装备/技能/路线前置任务、人物对话、心理活动、系统面板反馈、背景节拍和章末压力；第一章不要补成交易、提交委托、修理或买药水。",
                        "只输出扩写后的小说正文，不要解释，不要列大纲。",
                        f"原正文：\n{body}",
                    ]
                ),
                max_tokens=7000,
                json_mode=False,
                agent="writer",
                stage=f"章节扩写 第{chapter_number}章",
            )
            if not expand_error and _chapter_char_count(expanded_body) > _chapter_char_count(body):
                body = _sanitize_chapter_output(expanded_body, chapter_number=chapter_number, scene_cards=scene_cards)

        style_adapt_report = None
        if _style_adapt_enabled(writer_plan):
            report_generation_progress("风格适配中...")
            adapted_body, adapt_error = self._timed_chat(
                working_story,
                build_style_adapt_prompt(body, writer_plan),
                max_tokens=7000,
                json_mode=False,
                agent="writer",
                stage=f"风格适配 第{chapter_number}章",
            )
            if not adapt_error and adapted_body.strip():
                candidate_body = _sanitize_chapter_output(adapted_body, chapter_number=chapter_number, scene_cards=scene_cards)
                style_adapt_report = style_adapt_safety_check(body, candidate_body)
                if style_adapt_report.get("accept"):
                    body = candidate_body
            else:
                style_adapt_report = {"accept": False, "reason": adapt_error or "candidate_empty"}

        writing_review = _review_chapter_body(
            chapter_number,
            body,
            event_plan,
            story.world_facts,
            simulation_plan,
            world_events,
            scene_cards,
        )
        revision_safety_report = None
        if not writing_review.get("pass"):
            report_generation_progress("审稿改稿中...")
            pre_revision_body = body
            pre_revision_review = writing_review
            pre_revision_quality = {
                "ok": bool(pre_revision_review.get("pass")),
                "issues": pre_revision_review.get("issues", []),
                "writing_review": pre_revision_review,
            }
            revised_body, revision_error = self._timed_chat(
                working_story,
                self._revision_prompt(
                    working_story,
                    chapter_number,
                    body,
                    writer_plan,
                    writing_review,
                ),
                max_tokens=7000,
                json_mode=False,
                agent="writer",
                stage=f"审稿改稿 第{chapter_number}章",
            )
            if not revision_error and revised_body.strip():
                candidate_body = _sanitize_chapter_output(revised_body, chapter_number=chapter_number, scene_cards=scene_cards)
                candidate_review = _review_chapter_body(
                    chapter_number,
                    candidate_body,
                    event_plan,
                    story.world_facts,
                    simulation_plan,
                    world_events,
                    scene_cards,
                )
                candidate_quality = {
                    "ok": bool(candidate_review.get("pass")),
                    "issues": candidate_review.get("issues", []),
                    "writing_review": candidate_review,
                }
                safety = choose_best_revision(
                    original_body=pre_revision_body,
                    original_quality=pre_revision_quality,
                    candidate_body=candidate_body,
                    candidate_quality=candidate_quality,
                )
                body = str(safety["body"])
                selected_quality = safety["quality"] if isinstance(safety.get("quality"), dict) else pre_revision_quality
                selected_review = selected_quality.get("writing_review") if isinstance(selected_quality.get("writing_review"), dict) else pre_revision_review
                writing_review = selected_review
                revision_safety_report = safety["report"]

        continuity_anchors = _inject_continuity_anchors(memory_constraints, chapter_summary_data, body)

        decision = DirectorDecision(
            primary_conflict=chapter_intent.get("primary_conflict", {}) or conflict_summary.get("primary_conflict", {}),
            secondary_conflict=chapter_intent.get("secondary_conflict", {}) or conflict_summary.get("secondary_conflict", {}),
            event_beat=event_beat,
            cadence=cadence,  # type: ignore[arg-type]
            chapter_title=chapter_intent.get("chapter_title", "") or chapter_summary_data.get("chapter_title", ""),
            next_focus=chapter_intent.get("next_focus", "") or chapter_summary_data.get("next_focus", ""),
            approved_new_characters=[
                str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip()
                for item in chapter_intent.get("approved_new_characters", [])
                if (str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip())
            ],
            deferred_characters=[
                str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip()
                for item in chapter_intent.get("deferred_characters", [])
                if (str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip())
            ],
            rejected_characters=[
                str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip()
                for item in chapter_intent.get("rejected_characters", [])
                if (str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip())
            ],
        )

        updated_story = working_story.model_copy(deep=True)
        effective_conflict_summary = {
            **conflict_summary,
            "primary_conflict": decision.primary_conflict,
            "secondary_conflict": decision.secondary_conflict,
        }

        report_generation_progress("记忆回写中...")
        apply_post_chapter_updates(
            updated_story,
            body,
            chapter_number,
            conflict_summary=effective_conflict_summary,
            event_beat=event_beat,
        )
        apply_simulated_state_deltas(
            updated_story,
            world_events=world_events,
            scene_cards=scene_cards,
            chapter_number=chapter_number,
        )
        _apply_ledger_updates(updated_story, memory_constraints.get("ledger_updates", {}))
        _sync_character_game_panels(updated_story, chapter_number)
        maybe_update_arc_recap(updated_story, chapter_number)

        latest_summary = updated_story.chapter_summaries[-1]
        latest_summary.summary = chapter_summary_data.get("summary") or compact_text(body, 220)
        latest_summary.facts = chapter_summary_data.get("facts") or latest_summary.facts
        if continuity_anchors:
            latest_summary.facts = _merge_unique_compact(latest_summary.facts, continuity_anchors, max_items=14, item_chars=150)
        latest_summary.unresolved_threads = chapter_summary_data.get("unresolved_threads") or latest_summary.unresolved_threads
        latest_summary.next_focus = chapter_summary_data.get("next_focus") or decision.next_focus or latest_summary.next_focus
        latest_summary.chapter_title = chapter_summary_data.get("chapter_title") or decision.chapter_title or latest_summary.chapter_title
        latest_summary.primary_conflict = decision.primary_conflict
        latest_summary.secondary_conflict = decision.secondary_conflict
        latest_summary.event_beat = event_beat
        latest_summary.cadence = cadence  # type: ignore[assignment]

        if updated_story.timeline:
            updated_story.timeline[-1] = TimelineEvent(
                chapter_number=chapter_number,
                summary=compact_text(chapter_summary_data.get("summary") or latest_summary.summary, 160),
                impact=compact_text(event_plan.get("stakes", "") or "本章推动了主线局势。", 160),
            )

        conflict_participants = {
            decision.primary_conflict.get("lead"),
            decision.primary_conflict.get("opposition"),
            *[
                participant.get("name")
                for participant in decision.secondary_conflict.get("participants", [])
                if isinstance(participant, dict)
            ],
        } - {None, ""}
        for move in action_briefs:
            for character in updated_story.characters:
                if character.name == move["name"]:
                    if character.name in conflict_participants:
                        break
                    character.current_emotion = move.get("emotion", character.current_emotion)
                    if move.get("goal"):
                        character.goals = [move["goal"], *[goal for goal in character.goals if goal != move["goal"]]]
                    break

        _record_success(updated_story)

        bundle = ChapterBundle(
            chapter_number=chapter_number,
            body=body,
            chapter_title=latest_summary.chapter_title,
            cadence=cadence,
            chapter_intent={
                "chapter_title": latest_summary.chapter_title,
                "cadence": cadence,
                "next_focus": latest_summary.next_focus,
                "primary_conflict": decision.primary_conflict,
                "secondary_conflict": decision.secondary_conflict,
                "approved_new_characters": decision.approved_new_characters,
                "deferred_characters": decision.deferred_characters,
                "rejected_characters": decision.rejected_characters,
            },
            character_moves=action_briefs,
            memory_constraints=memory_constraints,
            event_plan=event_plan,
            chapter_seed=chapter_seed,
            simulation_plan=simulation_plan,
            world_events=world_events,
            scene_cards=scene_cards,
            simulation_status=_build_simulation_status(updated_story),
            action_briefs=action_briefs,
            conflict_summary={
                **effective_conflict_summary,
                "approved_new_characters": decision.approved_new_characters,
                "deferred_characters": decision.deferred_characters,
                "rejected_characters": decision.rejected_characters,
            },
            event_beat=event_beat,
            character_cards=build_character_cards(updated_story),
            foreshadowing=build_foreshadowing(updated_story, chapter_number),
            next_outline=plan_next_outline(
                updated_story,
                chapter_number,
                conflict_summary=effective_conflict_summary,
                cadence=cadence,
            ),
            updated_story=updated_story,
            chapter_summary=latest_summary.model_dump(),
        )
        report_generation_progress("质量检查中...")
        bundle.quality_report = _merge_writing_review_quality(validate_bundle(bundle.model_dump()), writing_review)
        if style_adapt_report:
            bundle.quality_report["style_adapt"] = style_adapt_report
        if revision_safety_report:
            bundle.quality_report["revision_safety"] = revision_safety_report
        if segment_pipeline_used and segment_reviews:
            bundle.quality_report["segment_pipeline"] = {
                "enabled": True,
                "segments": segment_reviews,
                "pass": all(review.get("pass") for review in segment_reviews),
            }
        return bundle
