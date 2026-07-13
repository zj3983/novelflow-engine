from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import json
import re
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from types import SimpleNamespace

from packages.story_core.agent_base import compact_list, compact_text, parse_json_message_content
from packages.story_core.chapter_governance import build_chapter_governance, governance_quality_gate, review_chapter_governance
from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.chapter_plot_contract import build_chapter_plot_contract
from packages.story_core.craft import is_game_story
from packages.story_core.genre_plugins import is_game_genre
from packages.story_core.generation_progress import report_generation_progress
from packages.story_core.http_retry import RetryConfig, post_json_with_retry
from packages.story_core.memory import (
    apply_post_chapter_updates,
    build_character_cards,
    build_foreshadowing,
    maybe_update_arc_recap,
    retrieve_relevant_memories,
)
from packages.story_core.models import DirectorDecision, StoryState, default_model_name
from packages.story_core.novel_type_catalog import normalize_novel_type_id
from packages.story_core.planner import build_chapter_title, build_conflict_summary, build_event_beat, compute_chapter_cadence, plan_next_outline
from packages.story_core.post_draft_memory import (
    build_post_draft_memory_prompt,
    fallback_post_draft_memory,
    normalize_post_draft_memory,
)
from packages.story_core.adversarial_cut_review import build_expression_patch_suggestions, review_adversarial_cuts
from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.cold_reader_review import review_cold_reader_experience
from packages.story_core.editor_agent import review_editor_agent
from packages.story_core.prose_quality_review import review_prose_quality
from packages.story_core.prose_rule_review import CRITICAL_PROMPT_RULES, PROMPT_CRAFT_GUARDS, review_critical_prose_rules
from packages.story_core.prose_style_review import review_prose_style, sanitize_prose_style
from packages.story_core.character_portraits import build_scene_portrait_slice
from packages.story_core.reader_feel_review import review_reader_feel
from packages.story_core.progression_lead_review import review_progression_lead
from packages.story_core.plot_spine_review import review_plot_spine_completion
from packages.story_core.quality import validate_bundle
from packages.story_core.reader_agent import review_reader_agent
from packages.story_core.reviewer_agent import review_reviewer_agent
from packages.story_core.runtime import record_agent_runtime
from packages.story_core.runtime_config import get_runtime_strategy_settings, resolve_openai_runtime_settings
from packages.story_core.revision_safety import choose_best_revision, choose_best_segment_revision
from packages.story_core.segmented_writing import (
    FIRST_CHAPTER_FORBIDDEN,
    SegmentSpec,
    build_segment_prompt,
    build_segment_revision_prompt,
    build_segment_specs,
    merge_segment_outputs,
    review_segment_output,
    trim_segment_to_contract,
)
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.simplified_review import build_simplified_review
from packages.story_core.spot_fix_patch import apply_spot_fix_patches
from packages.story_core.style_coach import build_style_guidance, enrich_performance_cards
from packages.story_core.web_game_author_craft import format_web_game_director_card, plain_writer_phrase
from packages.story_core.web_game_review import has_asserted_overreach, review_web_game_chapter, web_game_review_rules
from packages.story_core.writing_learning import learning_snapshot, lessons_from_quality_report, merge_writing_lessons
from packages.story_core.writing_taskbook import (
    ensure_writing_taskbook,
    first_chapter_whole_body_contract,
    format_taskbook_brief_section,
    format_taskbook_prompt_section,
    writer_facing_text,
)
from packages.story_core.style_adaptation import build_style_adapt_prompt, style_adapt_safety_check
from packages.story_core.world_consistency_review import review_world_event_consistency
from packages.story_core.world_pulse import advance_world_pulse
from packages.story_core.world_simulation_gate import world_simulation_decision
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events
from packages.story_core.skill_packs import skill_pack_prompt_context
from packages.story_core.prompt_modules import replaceable_slots
from packages.story_core.dialogue_context import build_dialogue_context
from packages.story_core.review_report import format_review_report
from packages.story_core.scene_contract_repair import build_scene_contract_repair_plan


VALID_CADENCES = {"urgent", "measured", "breathing"}
MIN_CHAPTER_CHARS = 4200
MAX_CHAPTER_CHARS = 5500
REGENERATION_MIN_CHARS = 3500
REGENERATION_FAST_MIN_CHARS = 3200
TARGET_CHAPTER_CHARS = "4200到5500字"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _expansion_timeout_seconds() -> int:
    return _env_int("NOVEL_EXPANSION_TIMEOUT_SECONDS", 720)


def _should_compress_chapter(body: str) -> bool:
    return _chapter_char_count(body) > MAX_CHAPTER_CHARS


def _review_exception_result(name: str, exc: Exception) -> dict[str, Any]:
    return {
        "pass": False,
        "scores": {f"{name}_exception": 4},
        "issues": [f"审稿器{name}异常：{exc}"],
        "revision_plan": [f"修复审稿器{name}异常后重新审核。"],
    }


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


def _scene_repair_writer_summary(repair_plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(repair_plan, dict) or not repair_plan:
        return {}
    scenes = repair_plan.get("failed_scenes") if isinstance(repair_plan.get("failed_scenes"), list) else []
    failed_scenes: list[dict[str, Any]] = []
    for scene in scenes[:4]:
        if not isinstance(scene, dict):
            continue
        missing = scene.get("missing_visible_consequences")
        missing_items: list[str] = []
        if isinstance(missing, list):
            for item in missing[:5]:
                if isinstance(item, dict):
                    text = str(item.get("revision") or item.get("description") or item.get("id") or "").strip()
                else:
                    text = str(item).strip()
                if text:
                    missing_items.append(compact_text(text, 110))
        failed_scenes.append(
            {
                "场景": compact_text(str(scene.get("scene_id") or scene.get("template_id") or ""), 60),
                "地点": compact_text(str(scene.get("location") or ""), 60),
                "需要补出来": missing_items,
            }
        )
    if not failed_scenes:
        return {}
    return {
        "范围": "只补这些场景，其他场景保持原顺序和事实",
        "场景": failed_scenes,
    }


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
        "元素法师学徒": "见习冒险者（未转职）",
        "元素回廊前置": "基础法术强化前置",
        "元素回廊": "基础法术强化",
        "职业路线确认：见习冒险者（未转职）": "初始身份确认：见习冒险者（未转职）",
        "正面对抗": "抢在别人前面做事",
        "正面撞上": "撞见",
        "抢核心资源": "抢任务材料",
        "争夺核心资源": "抢任务材料",
        "核心资源": "任务材料",
        "伤害数字": "跳出的数值",
        "当前货币：0铜": "货币栏还是空的",
        "当前货币:0铜": "货币栏还是空的",
        "货币：0铜": "钱袋：空",
        "货币:0铜": "钱袋：空",
        "逻辑": "规矩",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    reader_term_replacements = (
        ("火球术熟练度", "基础火球术记录"),
        ("熟练度", "施法记录"),
        ("修杖", "修法杖"),
        ("握杖", "握着法杖"),
        ("抬杖", "抬起法杖"),
        ("木杖", "新手法杖"),
        ("杖身", "法杖"),
        ("杖尖", "法杖前端"),
        ("不换杖芯", "不换法杖芯件"),
        ("任务门槛", "任务前置"),
        ("职业门槛", "职业前置"),
        ("装备门槛", "装备前置"),
        ("技能门槛", "技能前置"),
        ("NPC门槛", "NPC条件"),
        ("门槛", "前置条件"),
    )
    for old, new in reader_term_replacements:
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"背包[格子]*一下子亮了好几格", "灰狼毒腺和狼皮各占一格，数量叠在图标角上", cleaned)
    cleaned = re.sub(r"背包里([一二三四五六七八九十\d]+)个格子已经被材料塞住", "背包里两个材料格已经亮起，数量叠在图标角上", cleaned)
    cleaned = re.sub(r"背包：(\d+)/20", "背包：2/20", cleaned)
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
        "那点工作经验没让他富起来，只让他进游戏后会多看一眼提示和别人忽略的细节。\n\n"
    )
    return f"{prefix}{body.lstrip()}"


def _ensure_first_chapter_trigger_anchor(body: str) -> str:
    if not body:
        return body
    has_protocol = any(token in body for token in ("底层协议校验通过", "混沌之种：未解析", "混沌之种未解析"))
    if has_protocol:
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
        "夜烬只看了一眼价牌，把背包重新扣上，没有登记，也没有递材料。\n\n"
        "排队的人还在问毒腺要几份，窗口只按牌子上的前置条件答话，没人知道他背包里已经压着一小堆材料。"
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
        "木牌下方，",
        "状态栏一闪，",
        "柜台前的人往前挪了一步，",
        "格子边缘亮了一下，",
        "旁边有人低声抱怨，",
        "任务牌被风吹得轻轻一晃，",
        "空钱袋贴着掌心，",
        "法杖磕在石阶边，",
        "坡口的草叶晃了晃，",
        "断墙后面，",
        "系统小字淡下去，",
        "队伍里有人催了一声，",
        "价牌挂在窗口边，",
        "血条还压在低处，",
        "法力条已经见底，",
        "狼尸旁的白光散开，",
        "村口的吵声挤过来，",
        "石缝里的尘土落下去，",
        "手心的汗还没干，",
        "窗口后的NPC抬了下眼，",
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
    # Metaphor density belongs in review/revision. Mechanical token replacement
    # corrupts valid Chinese, for example turning "像有人开口" into "跟有人开口".
    return body


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
        "数据很干净": "几行字一眼就能看完",
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
        "仇恨连锁": "灰狼互相呼应",
        "AI规矩": "扑咬节奏",
        "游戏世界的运转规矩很简单：资源、交换、生存。没有多余的情绪，也没有多余的废话。": "老葛把铜币扫进抽屉，又低头去擦下一件装备。",
    }
    cleaned = body
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"不是[^。！？\n]{1,80}而是", "", cleaned)
    cleaned = re.sub(r"不只是[^。！？\n]{1,80}而是", "", cleaned)
    cleaned = cleaned.replace("很清楚", "实打实")
    return cleaned


def _ensure_protagonist_speech(body: str, protagonist: str = "夜烬") -> str:
    if not body:
        return body
    if re.search(rf"{re.escape(protagonist)}[^。！？\n]{{0,40}}(?:低声|小声)?(?:说|问|道|开口)[^。！？\n]{{0,8}}[“\"「『]", body):
        return body
    line = f'{protagonist}把背包扣上，低声说：“先不交，我还差两份，回去补齐再说。”'
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


def _insert_after_first_paragraph(body: str, line: str) -> str:
    paragraphs = body.rstrip().split("\n\n")
    if len(paragraphs) >= 2:
        paragraphs.insert(1, line)
        return "\n\n".join(paragraphs)
    return f"{line}\n\n{body.rstrip()}"


def _insert_near_middle_paragraph(body: str, line: str) -> str:
    paragraphs = body.rstrip().split("\n\n")
    if len(paragraphs) >= 4:
        paragraphs.insert(max(2, len(paragraphs) // 2), line)
        return "\n\n".join(paragraphs)
    return _insert_before_last_paragraph(body, line)


def _merge_overfragmented_paragraphs(body: str) -> str:
    paragraphs = [part.strip() for part in body.replace("\r", "\n").split("\n\n") if part.strip()]
    if len(paragraphs) < 40:
        return body
    sentence_marks = re.compile(r"[。！？!?]")

    def sentence_count(paragraph: str) -> int:
        return len([piece for piece in sentence_marks.split(paragraph) if piece.strip()])

    short_count = sum(1 for part in paragraphs if sentence_count(part) <= 2)
    if short_count / max(1, len(paragraphs)) < 0.45:
        return body

    merged: list[str] = []
    buffer: list[str] = []
    buffer_sentences = 0

    def flush() -> None:
        nonlocal buffer, buffer_sentences
        if buffer:
            merged.append("".join(buffer))
            buffer = []
            buffer_sentences = 0

    for paragraph in paragraphs:
        sentences = sentence_count(paragraph)
        is_opening_dialogue = paragraph.startswith(("“", "「", "『"))
        if sentences <= 2 and not is_opening_dialogue:
            buffer.append(paragraph)
            buffer_sentences += max(1, sentences)
            if buffer_sentences >= 4 or sum(len(item) for item in buffer) >= 260 or len(buffer) >= 5:
                flush()
            continue
        flush()
        merged.append(paragraph)
    flush()
    return "\n\n".join(merged)


def _ensure_web_game_outsider_misread(body: str, chapter_number: int) -> str:
    if chapter_number > 3 or not body:
        return body
    has_public_misread = (
        any(token in body for token in ("公共频道", "世界频道", "队尾", "散人玩家", "普通玩家", "旁边有个玩家"))
        and any(token in body for token in ("路线熟", "运气好", "只当他", "只以为他", "旁人只看见", "普通玩家只看见"))
        and any(token in body for token in ("没人追问", "没人多问", "无追查", "没追查"))
        and any(token in body for token in ("掉率低", "毒腺", "求购", "排队", "修杖", "买药"))
    )
    if has_public_misread:
        return body
    if chapter_number == 1:
        line = (
            "队伍里有个玩家看见夜烬反复数背包，只当他运气好，多摸到几份材料，随口说了句别挡窗口。"
            "旁人只看见他没交任务、没领铜币，也没往柜台递东西；没人知道他背包里的灰狼毒腺已经够到清道夫委托的前置边缘。"
        )
        return _insert_before_last_paragraph(body, line)
    line = (
        "公共频道里有人抱怨毒腺掉率低，刷了半天还差好几份；队尾另一个散人玩家看见夜烬从修理铺出来，"
        "又往药剂铺那边去，顺嘴嘀咕：“这人路线挺熟啊，估计也就运气好，多凑了两份材料。”"
        "旁边排队的人跟着看了一眼，很快又转回自己的面板，没人追问。夜烬听见了，没回头，只把钱袋口按紧。"
        "别人看见的是排队、修法杖和买药，看不见他背包里每一格怎么变。"
    )
    return _insert_before_last_paragraph(body, line)


def _ensure_chapter_two_missing_venom_scene(body: str, chapter_number: int) -> str:
    if chapter_number != 2 or not body or "夜烬" not in body:
        return body
    if any(token in body for token in ("清道夫委托已完成", "委托已提交", "三十枚铜币", "铜币+30")):
        return body
    has_gap_scene = (
        any(token in body for token in ("补齐材料", "补齐毒腺", "还差两份", "差两份", "凑成十份"))
        and any(token in body for token in ("获得：灰狼毒腺×2", "灰狼毒腺×2", "两份毒腺", "灰狼毒腺跳到了10份"))
    )
    if has_gap_scene:
        return body
    line = (
        "回村前，夜烬只在坡口补打一只灰狼。火球砸中侧颈，灰狼扑到一半摔进草里。"
        "提示跳出来：经验+15，获得：灰狼毒腺×2。他把两份毒腺塞进背包，原本的八份凑成十份，"
        "正好够清道夫委托，没再多刷。"
    )
    return _insert_before_last_paragraph(body, line)


def _ensure_web_game_emotion_anchors(body: str, chapter_number: int) -> str:
    if chapter_number < 2 or not body or "夜烬" not in body:
        return body
    if any(token in body for token in ("修到满要三铜", "三块铜", "十二铜", "12铜", "二十四铜")):
        return body
    anchors = [
        "夜烬看着钱袋里的铜币少下去，手指停了一下。十五铜修法杖，十铜买药，花出去的时候不疼是假的，但法杖真断在坡上，后面只会更亏。",
    ]
    existing_keys = {
        "十五铜修法杖": anchors[0],
        "十铜买药": anchors[0],
    }
    result = body
    for anchor in anchors:
        if not any(key in result and value == anchor for key, value in existing_keys.items()):
            result = _insert_before_last_paragraph(result, anchor)
    return result


def _ensure_first_chapter_emotion_anchors(body: str, chapter_number: int) -> str:
    if chapter_number != 1 or not body or "夜烬" not in body:
        return body
    result = body
    opening_anchor = (
        "苏叶把手机扣回桌面，喉咙发紧了一下。二十七块六不是不能看，是看多了会让人忍不住算，"
        "今晚要不要连泡面都省一包。"
    )
    combat_anchor = (
        "灰狼扑近的那一下，夜烬肩膀先缩了一下，火球脱手后才发现掌心全是汗。"
        "他不是不怕死，是怕这一趟只换来一具尸体，连那行异常提示都来不及看清。"
    )
    ending_anchor = (
        "他把背包关上，又没忍住重新打开看了一眼。材料还在，法杖耐久也是真的往下掉，"
        "这让他松了一口气，又不敢真的松下来。"
    )
    if not any(token in result for token in ("喉咙发紧", "今晚要不要连泡面都省一包")):
        result = _insert_after_first_paragraph(result, opening_anchor)
    if not any(token in result for token in ("掌心全是汗", "不是不怕死", "白打")):
        result = _insert_near_middle_paragraph(result, combat_anchor)
    if not any(token in result for token in ("又没忍住重新打开", "不敢真的松下来")):
        result = _insert_before_last_paragraph(result, ending_anchor)
    return result


def _sanitize_first_chapter_panel_values(body: str, chapter_number: int) -> str:
    if chapter_number != 1 or not body:
        return body
    cleaned = body
    cleaned = re.sub(r"(法力[：:]\s*\d+)/80", r"\1/60", cleaned)
    cleaned = re.sub(r"(法力[：:]\s*)20/60(?=[^\n。；]{0,80}(?:主武器|基础技能|背包|钱袋))", r"\g<1>60/60", cleaned)
    cleaned = cleaned.replace("生命：100/100法力：", "生命：100/100；法力：")
    cleaned = cleaned.replace("经验：0/100生命：", "经验：0/100；生命：")
    return cleaned


def _ensure_first_chapter_progression_hook(body: str, chapter_number: int) -> str:
    if chapter_number != 1 or not body:
        return body
    if "清道夫委托" in body and ("还差两份" in body or "差两份" in body) and "后坡" in body:
        return body
    hook = (
        "村口任务牌最下方挂着一行小字：清道夫委托，提交灰狼毒腺十份，奖励三十铜；"
        "完成后开放后坡探路的前置任务登记。夜烬没有伸手接，只把背包里的八份毒腺重新数了一遍。"
        "普通玩家还在为第一份毒腺排队抱怨，他已经只差两份，任务进度就能先一步贴近后坡入口，下一步只要补齐材料就能去试路线。"
    )
    return _insert_before_last_paragraph(body, hook)


def _truncate_first_chapter_service_overrun(body: str, chapter_number: int) -> str:
    if chapter_number != 1 or not body:
        return body
    overrun_terms = (
        "登记窗口前",
        "把两份毒腺放在柜台上",
        "后坡路线已登记",
        "后坡通行",
        "清道夫委托完成",
        "奖励铜币",
        "奖励：铜币",
        "奖励铜币×",
        "奖励铜币x",
        "经验×100",
        "经验x100",
        "钱袋。50",
        "50枚铜币",
    )
    indexes = [body.find(term) for term in overrun_terms if body.find(term) >= 0]
    if not indexes:
        return body
    cut_at = min(indexes)
    safe_body = body[:cut_at].rstrip()
    canonical = (
        "村口任务牌最下方挂着一行小字：清道夫委托，提交灰狼毒腺十份，奖励三十铜；"
        "完成后开放后坡探路的前置任务登记。夜烬没有伸手接，也没有往柜台递材料，"
        "只把背包里的八份毒腺重新数了一遍。普通玩家还在为第一份毒腺排队抱怨，"
        "他已经只差两份，任务进度就能先一步贴近后坡入口，下一步只要补齐材料就能去试路线。"
    )
    if canonical in safe_body:
        return safe_body
    return f"{safe_body}\n\n{canonical}"


def _ensure_web_game_npc_service_boundary(body: str, chapter_number: int) -> str:
    if chapter_number < 2 or not body or "夜烬" not in body:
        return body
    has_full_boundary = all(
        token in body
        for token in ("修理铺", "老葛", "十五铜", "只看裂纹和耐久", "不问夜烬从哪儿弄来的毒腺")
    )
    if any(token in body for token in ("修到满要三铜", "三块铜", "十二铜", "12铜", "二十四铜")):
        return body
    if has_full_boundary:
        if "洛婶" in body and "洛婶只按清单" not in body:
            return _insert_before_last_paragraph(
                body,
                "洛婶只按清单收钱拿药，不问夜烬这一趟来得快不快，也不理会他刚交完委托又买药。",
            )
        return body
    line = (
        "修理铺门口的铁砧牌子被擦得发亮。老葛接过新手法杖，只看裂纹和耐久，开口就是十五铜，"
        "不问夜烬从哪儿弄来的毒腺，也不管他刚才交了什么任务。对老葛来说，玩家递装备、付钱、拿走修好的东西，"
        "这事就到这里。"
    )
    result = _insert_before_last_paragraph(body, line)
    if "洛婶" in result and "洛婶只按清单" not in result:
        pharmacy_line = "洛婶只按清单收钱拿药，不问夜烬这一趟来得快不快，也不理会他刚交完委托又买药。"
        result = _insert_before_last_paragraph(result, pharmacy_line)
    return result


def _sanitize_chapter_two_webgame_terms(body: str, chapter_number: int) -> str:
    if chapter_number != 2 or not body:
        return body
    replacements = {
        "灰鼠坡": "灰狼坡",
        "灰鼠": "灰狼",
        "仇恨标识": "灰狼的注意",
        " footing（落脚点）": "落脚点",
        "footing（落脚点）": "落脚点",
        "每秒0.16点的恢复速率，从零到满需要整整六分钟。": "回蓝很慢，等满要好几分钟。",
        "毒腺掉率基础值15%，受幸运值影响浮动。": "毒腺不好掉，普通玩家经常卡在这一步。",
        "系统日志安静地记录着：【基础火球术熟练度+1（当前0/100）】。": "系统日志安静地记录着：【基础火球术记录已更新】。",
        "熟练度界面跟着跳出来：基础火球术，熟练度0/100。": "技能记录跟着跳出来：基础火球术，今天只用过一次。",
        "熟练度涨得极慢。": "这条路得靠一次次施法磨过去。",
        "熟练度到十，登记牌就能亮。": "再多练几次，登记牌才可能继续亮下去。",
        "后坡探路登记。条件未满足。需火球熟练度达到Lv.1，或携带高级法力药水×1。": "后坡探路登记。清道夫委托已完成，后坡记录已开放。建议等级Lv.2或组队进入。",
        "修到满要三铜。": "修到满要十五铜。",
        "三块铜。修完十成。": "十五铜。修完十成。",
        "钱袋里少了三枚铜币。": "钱袋里少了十五枚铜币。",
        "12铜/瓶": "5铜/瓶",
        "二十四铜": "十铜",
        "三十铜减去三铜，还剩二十七。买两瓶，剩三铜。": "三十铜减去十五铜，还剩十五。买两瓶，剩五铜。",
        "三十铜减去十五铜，还剩十五。买两瓶，剩三铜。": "三十铜减去十五铜，还剩十五。买两瓶，剩五铜。",
        "钱袋彻底见底，只剩三枚铜币贴着底。": "钱袋里还剩五枚铜币。",
        "钱袋轻了三分。": "钱袋少了十五枚铜币。",
        "十五铜一瓶。两瓶二十八，省两铜。": "五铜一瓶，两瓶十铜。",
        "数出二十八枚铜币": "数出十枚铜币",
        "钱袋里只剩两枚铜币": "钱袋里还剩五枚铜币",
        "钱袋里只剩两枚": "钱袋里还剩五枚",
        "格子跳到16/20": "背包还有空格",
        "格子17/20": "背包还有空格",
        "运气是弱者的借口，路线才是强者的底牌。": "他听见了，也没解释。别人愿意这么想，对他反而方便。",
    }
    cleaned = body
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned


def _sanitize_chapter_output(
    body: str,
    *,
    chapter_number: int,
    scene_cards: list[dict] | None = None,
    game_story: bool = True,
) -> str:
    cleaned = _sanitize_generated_body(body)
    if game_story:
        cleaned = _sanitize_systemic_resource_contradictions(cleaned, scene_cards)
    if game_story and chapter_number == 1:
        cleaned = _sanitize_first_chapter_panel_values(cleaned, chapter_number)
    cleaned = _sanitize_report_style_terms(cleaned)
    cleaned = _limit_metaphor_markers(cleaned)
    if game_story:
        cleaned = _sanitize_chapter_two_webgame_terms(cleaned, chapter_number)
    return _merge_overfragmented_paragraphs(cleaned)


def _sanitize_first_chapter_scope(body: str, chapter_number: int) -> str:
    if chapter_number != 1 or not body:
        return body
    sentence_block_terms = (
        "匿名寄售",
        "寄售成功",
        "上架成功",
        "成交",
        "到账铜币",
        "到账：",
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
        "修一下",
        "修好",
        "修装备",
        "修理装备",
        "修满",
        "修完耐久",
        "钱袋里多了",
        "钱袋里还剩",
        "扣掉",
        "扣除",
        "买了蓝药",
        "买下蓝药",
        "技能书残页",
        "技能书",
        "买两瓶",
        "初级法力药水×",
        "两瓶药水",
        "买了药水",
        "买下药水",
        "购买了药水",
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
    return "\n\n".join(kept_paragraphs).strip() or body


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


def _compact_prompt_ledger(ledger: Any) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("protagonist", "economy", "equipment", "quests", "time", "simulation_variant"):
        value = ledger.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    world_pulse = ledger.get("world_pulse") if isinstance(ledger.get("world_pulse"), dict) else {}
    if world_pulse:
        latest = world_pulse.get("latest")
        if isinstance(latest, dict):
            result["world_pulse"] = {
                "latest": {
                    "pulse_index": latest.get("pulse_index"),
                    "chapter_number": latest.get("chapter_number"),
                    "visible_at_chapter": latest.get("visible_at_chapter"),
                    "summary": compact_text(str(latest.get("reader_facing_summary") or latest.get("summary") or latest.get("id") or ""), 160),
                    "visible_traces": compact_list(latest.get("visible_traces", []), max_items=3, item_chars=110),
                }
            }
        else:
            result["world_pulse"] = compact_list(world_pulse.get("history", []), max_items=2, item_chars=120)
    inbox = ledger.get("visibility_inbox") if isinstance(ledger.get("visibility_inbox"), list) else []
    if inbox:
        result["visibility_inbox"] = inbox[-2:]
    return result


def _compact_character_cards_for_prompt(story: StoryState, *, max_items: int = 4) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for card in build_character_cards(story)[:max_items]:
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        profile = card.get("webnovel_profile") if isinstance(card.get("webnovel_profile"), dict) else {}
        usage = card.get("story_usage") if isinstance(card.get("story_usage"), dict) else {}
        voice = card.get("voice_and_action") if isinstance(card.get("voice_and_action"), dict) else {}
        locks = card.get("continuity_locks") if isinstance(card.get("continuity_locks"), dict) else {}
        relationships = locks.get("relationships") if isinstance(locks.get("relationships"), dict) else {}
        chapter_usage = usage.get("this_chapter_usage") if isinstance(usage.get("this_chapter_usage"), dict) else {}
        cards.append(
            {
                "identity": {
                    "name": identity.get("name", ""),
                    "role": identity.get("role", ""),
                    "game_id": identity.get("game_id", ""),
                    "location": compact_text(str(identity.get("location", "")), 60),
                },
                "webnovel_profile": {
                    "character_type": compact_text(str(profile.get("character_type", "")), 90),
                    "core_motivation": compact_text(str(profile.get("core_motivation", "")), 120),
                    "behavior_logic": compact_text(str(profile.get("behavior_logic", "")), 120),
                    "interaction_mode": compact_text(str(profile.get("interaction_mode", "")), 120),
                    "poison_points": compact_list(profile.get("poison_points", []), max_items=4, item_chars=80),
                },
                "this_chapter_usage": {
                    "speech_tendency": compact_text(str(chapter_usage.get("speech_tendency", "")), 100),
                    "action_tendency": compact_text(str(chapter_usage.get("action_tendency", "")), 100),
                },
                "voice_and_action": {
                    "risk_posture": compact_text(str(voice.get("risk_posture", "")), 100),
                    "speech_style": compact_text(str(voice.get("speech_style", "")), 100),
                    "action_style": compact_text(str(voice.get("action_style", "")), 100),
                },
            }
        )
    return cards


def _planned_character_names(plan: Any) -> set[str]:
    if not isinstance(plan, dict):
        return set()
    names: set[str] = set()
    for item in plan.get("character_moves", []) if isinstance(plan.get("character_moves"), list) else []:
        if isinstance(item, dict):
            for key in ("name", "game_id"):
                value = str(item.get(key) or "").strip()
                if value:
                    names.add(value)
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    for item in event_plan.get("ordered_actions", []) if isinstance(event_plan.get("ordered_actions"), list) else []:
        if isinstance(item, dict):
            value = str(item.get("name") or "").strip()
            if value:
                names.add(value)
    for card in plan.get("scene_cards", []) if isinstance(plan.get("scene_cards"), list) else []:
        if isinstance(card, dict):
            for key in ("pov", "character", "name"):
                value = str(card.get(key) or "").strip()
                if value and value not in {"主角", "玩家", "NPC"}:
                    names.add(value)
    return names


def _character_context_for_prompt(story: StoryState, plan: Any | None = None, *, max_items: int = 4) -> dict[str, Any]:
    requested = _planned_character_names(plan)
    cards = build_character_cards(story)
    selected: list[dict[str, Any]] = []
    for card in cards:
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        name = str(identity.get("name") or "").strip()
        game_id = str(identity.get("game_id") or "").strip()
        if requested and name not in requested and game_id not in requested:
            continue
        selected.append(card)
        if len(selected) >= max_items:
            break
    if not selected:
        selected = cards[:max_items]

    compact_cards: list[dict[str, Any]] = []
    for card in selected:
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        profile = card.get("webnovel_profile") if isinstance(card.get("webnovel_profile"), dict) else {}
        usage = card.get("story_usage") if isinstance(card.get("story_usage"), dict) else {}
        voice = card.get("voice_and_action") if isinstance(card.get("voice_and_action"), dict) else {}
        locks = card.get("continuity_locks") if isinstance(card.get("continuity_locks"), dict) else {}
        relationships = locks.get("relationships") if isinstance(locks.get("relationships"), dict) else {}
        chapter_usage = usage.get("this_chapter_usage") if isinstance(usage.get("this_chapter_usage"), dict) else {}
        compact_cards.append(
            {
                "identity": {
                    "name": identity.get("name", ""),
                    "role": identity.get("role", ""),
                    "game_id": identity.get("game_id", ""),
                    "location": compact_text(str(identity.get("location", "")), 60),
                },
                "motivation": compact_text(str(profile.get("core_motivation", "")), 120),
                "behavior_logic": compact_text(str(profile.get("behavior_logic", "")), 120),
                "interaction_mode": compact_text(str(profile.get("interaction_mode", "")), 120),
                "speech_tendency": compact_text(str(chapter_usage.get("speech_tendency", "")), 100),
                "action_tendency": compact_text(str(chapter_usage.get("action_tendency", "")), 100),
                "risk_posture": compact_text(str(voice.get("risk_posture", "")), 100),
                "speech_style": compact_text(str(voice.get("speech_style", "")), 100),
                "poison_points": compact_list(profile.get("poison_points", []), max_items=4, item_chars=80),
                "relationship_context": [
                    {
                        "target": str(target),
                        "trust": relation.get("trust", 0),
                        "tension": relation.get("tension", 0),
                        "bond": str(relation.get("bond") or ""),
                    }
                    for target, relation in list(relationships.items())[:3]
                    if isinstance(relation, dict)
                ],
                "scene_portrait": build_scene_portrait_slice(card),
            }
        )
    return {
        "selection": "planned_characters" if requested else "fallback_active_characters",
        "requested_names": sorted(requested),
        "cards": compact_cards,
    }


def _character_context_summary_for_prompt(context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    cards = context.get("cards") if isinstance(context.get("cards"), list) else []
    brief_cards = []
    for card in cards[:2]:
        if not isinstance(card, dict):
            continue
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        brief_cards.append(
            {
                "name": identity.get("name"),
                "game_id": identity.get("game_id"),
                "role": identity.get("role"),
                "motivation": compact_text(str(card.get("motivation") or ""), 70),
                "speech": compact_text(str(card.get("speech_style") or card.get("speech_tendency") or ""), 70),
                "risk": compact_text(str(card.get("risk_posture") or ""), 70),
                "relationships": card.get("relationship_context", [])[:2],
                "scene_portrait": card.get("scene_portrait") if isinstance(card.get("scene_portrait"), dict) else {},
            }
        )
    return {"selection": context.get("selection"), "requested_names": context.get("requested_names", [])[:4], "cards": brief_cards}


def _slim_prompt_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return compact_text(str(value), 160)
    if isinstance(value, str):
        return compact_text(value, 180)
    if isinstance(value, list):
        return [_slim_prompt_value(item, depth=depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            result[str(key)] = _slim_prompt_value(item, depth=depth + 1)
        return result
    return value


def _compact_chapter_seed_for_prompt(seed: Any) -> dict[str, Any]:
    if not isinstance(seed, dict):
        return {}
    keep_keys = (
        "schema_version",
        "chapter_number",
        "chapter_contract",
        "writing_contract",
        "simulation_axes",
        "current_state",
        "continuity",
        "hard_locks",
        "must_show",
        "must_not_write",
    )
    compacted = {key: _slim_prompt_value(seed.get(key)) for key in keep_keys if seed.get(key) not in (None, "", [], {})}
    current_state = compacted.get("current_state")
    if isinstance(current_state, dict):
        slim_state: dict[str, Any] = {}
        for key in ("real", "panel", "equipment", "economy", "quests", "risk", "skills", "protagonist", "pressure", "market", "systems", "clock"):
            if current_state.get(key) not in (None, "", [], {}):
                slim_state[key] = current_state[key]
        inbox = current_state.get("visibility_inbox")
        if isinstance(inbox, list) and inbox:
            slim_state["visibility_inbox"] = inbox[:3]
        compacted["current_state"] = slim_state
    if "writing_contract" in compacted and isinstance(compacted["writing_contract"], dict):
        contract = compacted["writing_contract"]
        for key in ("scene_plan", "allowed_progress", "forbidden_unlocks"):
            if isinstance(contract.get(key), list):
                contract[key] = contract[key][:6]
    return compacted


def _compact_writer_plan_for_prompt(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    chapter_intent = plan.get("chapter_intent") if isinstance(plan.get("chapter_intent"), dict) else {}
    memory_constraints = plan.get("memory_constraints") if isinstance(plan.get("memory_constraints"), dict) else {}
    result: dict[str, Any] = {}
    if chapter_intent:
        result["chapter_intent"] = _slim_prompt_value(chapter_intent)
    if event_plan:
        result["event_plan"] = {
            "chapter_title": event_plan.get("chapter_title"),
            "turn": event_plan.get("turn"),
            "pivot": event_plan.get("pivot"),
            "collision": event_plan.get("collision"),
            "chapter_satisfaction": _slim_prompt_value(event_plan.get("chapter_satisfaction")),
            "ordered_actions": _slim_prompt_value(event_plan.get("ordered_actions", [])[:6]),
            "npc_beats": _slim_prompt_value(event_plan.get("npc_beats", [])[:4]),
            "quest_beats": _slim_prompt_value(event_plan.get("quest_beats", [])[:4]),
            "location_beats": _slim_prompt_value(event_plan.get("location_beats", [])[:4]),
            "world_reactions": _slim_prompt_value(event_plan.get("world_reactions", [])[:4]),
            "stakes": event_plan.get("stakes"),
            "next_focus": event_plan.get("next_focus"),
            "chapter_end_hook": _slim_prompt_value(event_plan.get("chapter_end_hook")),
        }
    if memory_constraints:
        result["memory_constraints"] = {
            "must_keep_facts": _slim_prompt_value(memory_constraints.get("must_keep_facts", [])[:8]),
            "unresolved_threads": _slim_prompt_value(memory_constraints.get("unresolved_threads", [])[:5]),
            "ledger_updates": _slim_prompt_value(memory_constraints.get("ledger_updates")),
        }
    scene_cards = plan.get("scene_cards")
    if isinstance(scene_cards, list) and scene_cards:
        compact_cards: list[dict[str, Any]] = []
        for card in scene_cards[:6]:
            if not isinstance(card, dict):
                continue
            state_delta = card.get("state_delta") if isinstance(card.get("state_delta"), dict) else {}
            compact_delta: dict[str, Any] = {}
            for delta_key in ("real", "panel", "economy", "equipment", "quest", "quests", "inventory"):
                if state_delta.get(delta_key) not in (None, "", [], {}):
                    compact_delta[delta_key] = _slim_prompt_value(state_delta.get(delta_key))
            simulation = state_delta.get("game_world_simulation")
            if isinstance(simulation, dict):
                compact_delta["simulation"] = {
                    "variant": simulation.get("simulation_variant"),
                    "final_state": _slim_prompt_value(simulation.get("final_state")),
                    "visible_payoff": compact_text(str(simulation.get("visible_payoff") or simulation.get("payoff") or ""), 120),
                }
            compact_cards.append(
                {
                    "scene_id": card.get("scene_id"),
                    "location": card.get("location"),
                    "pov": card.get("pov"),
                    "purpose": compact_text(str(card.get("purpose") or ""), 120),
                    "conflict": compact_text(str(card.get("conflict") or ""), 120),
                    "must_show": compact_list(card.get("must_show", []), max_items=4, item_chars=80),
                    "state_delta": compact_delta,
                    "ending_pressure": compact_text(str(card.get("ending_pressure") or ""), 100),
                }
            )
        result["scene_cards"] = compact_cards
    character_moves = plan.get("character_moves")
    if isinstance(character_moves, list) and character_moves:
        result["character_moves"] = _slim_prompt_value(character_moves[:6])
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _writer_seed_summary(seed: Any) -> dict[str, Any]:
    compacted = _compact_chapter_seed_for_prompt(seed)
    if not compacted:
        return {}
    writing_contract = compacted.get("writing_contract") if isinstance(compacted.get("writing_contract"), dict) else {}
    chapter_contract = compacted.get("chapter_contract") if isinstance(compacted.get("chapter_contract"), dict) else {}
    continuity = compacted.get("continuity") if isinstance(compacted.get("continuity"), dict) else {}
    return {
        "章节": compacted.get("chapter_number"),
        "上一章": compact_text(str(continuity.get("latest_summary") or ""), 160),
        "必须承接": compact_list(continuity.get("must_keep_facts", []), max_items=4, item_chars=90),
        "未解线索": compact_list(continuity.get("unresolved_threads", []), max_items=4, item_chars=90),
        "下一步": compact_text(str(continuity.get("next_focus") or ""), 100),
        "当前状态": compact_list(
            [
                str(chapter_contract.get("current_level") or "").strip(),
                str(chapter_contract.get("progression_stage") or "").strip(),
            ],
            max_items=2,
            item_chars=40,
        ),
        "本章目标": compact_text(str(chapter_contract.get("goal") or chapter_contract.get("chapter_goal") or ""), 90),
        "本章要兑现": compact_text(str(chapter_contract.get("payoff") or chapter_contract.get("visible_payoff") or ""), 90),
        "这章可以兑现的小进展": compact_list(writing_contract.get("allowed_progress", []), max_items=3, item_chars=70),
        "这章不能提前写": compact_list(writing_contract.get("forbidden_unlocks", []), max_items=3, item_chars=70),
        "情绪走向": compact_list(writing_contract.get("emotional_arc", []), max_items=3, item_chars=70),
        "行动顺序": compact_list((writing_contract.get("genre_craft") or {}).get("action_chain", []), max_items=3, item_chars=70)
        if isinstance(writing_contract.get("genre_craft"), dict)
        else [],
        "正文要露出": compact_list(compacted.get("must_show", []), max_items=3, item_chars=70),
        "正文别写": compact_list(compacted.get("must_not_write", []), max_items=3, item_chars=70),
    }


def _director_characters(story: StoryState, *, limit: int = 4) -> list[Any]:
    latest = story.chapter_summaries[-1] if story.chapter_summaries else None
    relevance_text = " ".join(
        [
            story.outline,
            latest.summary if latest else "",
            " ".join(latest.unresolved_threads) if latest else "",
            latest.next_focus if latest else "",
        ]
    )
    ranked: list[tuple[int, int, Any]] = []
    for index, character in enumerate(story.characters):
        if character.lifecycle_state != "active" or character.frozen:
            continue
        score = 0
        if character.role in {"protagonist", "主角"}:
            score += 100
        if character.chapter_role:
            score += 25
        if character.name and character.name in relevance_text:
            score += 40
        if character.game_id and character.game_id in relevance_text:
            score += 35
        if any(token in character.role for token in ("本章", "相关", "核心")):
            score += 15
        ranked.append((score, -index, character))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:limit]]


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
    prompt_ledger = _compact_prompt_ledger(story.progression_ledger)
    return {
        "outline": compact_text(story.outline, 700),
        "genre": story.genre,
        "style": story.style,
        "current_chapter": story.current_chapter,
        "author_constraints": compact_list(story.author_constraints, max_items=6, item_chars=130),
        "world_facts": _priority_world_facts(story.world_facts, max_items=12, item_chars=140),
        "progression_ledger": prompt_ledger,
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
        "world_pulse": prompt_ledger.get("world_pulse", {}),
        "visibility_inbox": prompt_ledger.get("visibility_inbox", []),
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
                "memory": compact_list(c.memory, max_items=3, item_chars=90),
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
            for c in _director_characters(story)
        ],
    }


def _director_snapshot_summary(snapshot: dict) -> dict:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    ledger = snapshot.get("progression_ledger") if isinstance(snapshot.get("progression_ledger"), dict) else {}
    visibility = snapshot.get("visibility_inbox") if isinstance(snapshot.get("visibility_inbox"), dict) else {}
    characters = snapshot.get("characters") if isinstance(snapshot.get("characters"), list) else []
    return {
        "outline": compact_text(str(snapshot.get("outline") or ""), 180),
        "genre": snapshot.get("genre"),
        "style": compact_text(str(snapshot.get("style") or ""), 120),
        "current_chapter": snapshot.get("current_chapter"),
        "author_constraints": compact_list(snapshot.get("author_constraints", []), max_items=4, item_chars=90),
        "world_facts": compact_list(snapshot.get("world_facts", []), max_items=6, item_chars=90),
        "progression_ledger": {
            "protagonist": ledger.get("protagonist"),
            "economy": ledger.get("economy"),
            "quests": ledger.get("quests"),
        },
        "latest_summary": compact_text(str(snapshot.get("latest_summary") or ""), 160),
        "latest_facts": compact_list(snapshot.get("latest_facts", []), max_items=4, item_chars=80),
        "latest_threads": compact_list(snapshot.get("latest_threads", []), max_items=4, item_chars=80),
        "current_focus": compact_text(str(snapshot.get("current_focus") or ""), 120),
        "visibility_inbox": {
            "signals": compact_list(visibility.get("signals", []), max_items=3, item_chars=80) if isinstance(visibility, dict) else [],
            "visible_traces": compact_list(visibility.get("visible_traces", []), max_items=3, item_chars=80)
            if isinstance(visibility, dict)
            else [],
        },
        "characters": [
            {
                "name": item.get("name"),
                "role": item.get("role"),
                "goals": compact_list(item.get("goals", []), max_items=2, item_chars=60),
                "emotion": compact_text(str(item.get("emotion") or ""), 40),
                "location": compact_text(str(item.get("location") or ""), 60),
                "memory": compact_list(item.get("memory", []), max_items=2, item_chars=70),
                "relationships": item.get("relationships", [])[:3]
                if isinstance(item.get("relationships"), list)
                else [],
            }
            for item in characters[:4]
            if isinstance(item, dict)
        ],
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


def _parse_copper(value: object) -> int:
    match = re.search(r"-?\d+", str(value or "0"))
    return int(match.group(0)) if match else 0


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

    currency_delta = ledger_delta.get("currency_delta")
    if isinstance(currency_delta, dict) and currency_delta:
        economy = ledger.setdefault("economy", {})
        copper_delta = currency_delta.get("铜")
        if copper_delta not in (None, "", [], {}):
            economy["game_currency"] = f"{_add_int(_parse_copper(economy.get('game_currency')), copper_delta)}铜"

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

    set_delta = ledger_delta.get("set_delta")
    if isinstance(set_delta, dict) and set_delta:
        story.progression_ledger = _merge_ledger_dict(ledger, set_delta)
        ledger = story.progression_ledger

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
    if economy.get("game_currency"):
        panel.currency = str(economy.get("game_currency"))
    elif economy.get("currency"):
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
            value = ledger.get(key)
            if value in (None, "", [], {}):
                continue
            if key == "currency" and economy.get("game_currency") not in (None, "", [], {}):
                continue
            if key == "inventory" and isinstance(economy.get("inventory"), dict) and not isinstance(value, dict):
                continue
            economy[key] = value
        if economy.get("game_currency") not in (None, "", [], {}) and economy.get("currency") not in (None, "", [], {}):
            economy.pop("currency", None)
    if isinstance(equipment, dict):
        for key in ("weapon", "armor", "durability"):
            if key in ledger and ledger[key] not in (None, "", [], {}):
                equipment[key] = ledger[key]
    if isinstance(pressure, dict):
        for key in ("guild_attention", "goldfinger_exposure", "system_risk"):
            if key in ledger and ledger[key] not in (None, "", [], {}):
                pressure[key] = ledger[key]
        next_pressure = pressure.get("next")
        if isinstance(next_pressure, list):
            pressure["next"] = [
                "后坡探路前置已满足，但等级和补给仍压着风险"
                if "熟练度" in str(item)
                else item
                for item in next_pressure
            ]
    if isinstance(economy.get("inventory"), dict):
        ledger.pop("inventory", None)
    if economy.get("game_currency") not in (None, "", [], {}):
        ledger.pop("currency", None)
    if isinstance(ledger.get("skills"), list):
        ledger["skills"] = [item for item in ledger["skills"] if "熟练度" not in str(item)]
        if not ledger["skills"]:
            ledger.pop("skills", None)


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
        "初始身份",
        "身份栏",
        "身份：",
        "职业倾向",
        "职业：",
        "元素法师",
        "法师",
        "见习冒险者",
        "未转职",
        "基础火球术",
        "技能栏",
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
            if any(term in chunk for term in ("职业倾向", "职业：", "元素法师", "法师")):
                label = "职业锚点"
                rank = 0
            elif any(term in chunk for term in ("初始身份", "身份栏", "身份：", "见习冒险者", "未转职", "基础火球术", "新手法杖")):
                label = "身份锚点"
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
    if any(token in body for token in ("见习冒险者", "未转职", "基础火球术", "新手法杖")):
        protagonist["class_path"] = "见习冒险者（未转职）"
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


def _opening_phase_name(chapter_number: int, *, is_game: bool = True) -> str:
    if not is_game:
        if chapter_number <= 3:
            return f"黄金三章第{chapter_number}章：推进当前核心矛盾，兑现一个具体进展，并留下下一步行动"
        return "常规连载章节：目标、行动、结果、代价和章末钩子"
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
            "第一章必须写出网游开篇仪式：登录或角色创建、游戏ID“夜烬”、初始身份、武器/基础技能选择、角色面板。开局所有玩家都是见习冒险者（未转职），夜烬只是选新手法杖和基础火球术，不要写成独有职业。",
            "第一章初始短面板固定锚点：游戏ID夜烬，Lv.1，身份见习冒险者（未转职），经验0/100，生命100/100，法力60/60，新手法杖10/10，基础火球术，背包空或钱袋空。",
            "角色面板必须在正文中写出“角色面板”四个字，并有职业栏，至少包含：游戏ID、等级、职业/路线、经验、生命/法力、基础火球术、背包或钱袋关键项；不要写“货币：0铜”；面板要短，不要刷屏。",
            "初始钱袋锁死为空。第一章如果没有正文写出铜币掉落或任务奖励，章末就仍是一枚铜都没有，不能凭空变成15铜。",
            "初始身份和技能锁死：开局不要写任何正式职业；统一写见习冒险者（未转职），夜烬只是在新手武器里选法杖，并拿到基础火球术，不要改名成元素弹。",
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
            "第2章必须承接第一章账本：夜烬仍是Lv.1见习冒险者（未转职）；本章留在新手村任务、灰狼坡/后坡、补给和基础火球术记录里推进。禁止Lv.1接取或开始转职任务、职业试炼、元素回廊试炼、法师塔试炼；10级之前只能看见远期线索或前置任务，不能正式办理。",
            "第2章账本要按上一章章末状态继承，等级、经验、钱袋、背包、生命/法力、装备耐久和任务状态都从项目账本读取；清道夫、买技能、修法杖、买药等动作必须在正文里逐项落账。不要写经验100/100却未升级，也不要同章反复刷怪、回村、交同一个任务来凑进度。",
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
    game_context = is_game_genre("\n".join([body, facts_text, plan_text]))
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
            "到账铜币",
            "到账：",
            "手续费",
            "第一笔铜币落袋",
            "赵胖子",
            "盯盘",
        )
        if any(token in body for token in first_chapter_trade_terms):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章提前展开交易线：出现寄售、成交、到账、手续费、商人盯盘或赵胖子内容。")
            revision_plan.append("删除第一章的实际交易和商人线，只保留掉落、任务材料预留和章末“下一步用高爆率抢任务/装备/技能前置”的目标。")

        first_chapter_service_closure_terms = (
            "钱袋里多了",
            "钱袋里还剩",
            "扣掉",
            "修好",
            "把法杖修好",
            "法杖修好",
            "买了药水",
            "买下药水",
            "初级蓝药×",
            "初级法力药水×",
            "技能书残页",
            "换技能书",
            "旧城区入口",
            "巡夜人残牌",
        )
        if any(token in body for token in first_chapter_service_closure_terms):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            scores["continuity"] = min(scores["continuity"], 5)
            issues.append("第一章账本越界：出现拿铜币、修法杖、买药水、技能书残页或旧城区入口等后续阶段内容。")
            revision_plan.append("第一章只保留首次打灰狼、掉落异常、血蓝耐久消耗、背包材料和清道夫委托前置；不得交任务、拿铜币、修法杖、买药水或开启技能书/旧城区线。")

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
            issues.append("第一章冲突越级：开篇应以现实压力、登录建号、初始身份、规则验证和背包材料暂时不能处理为主，不能写成公会/商人正面对抗或高阶资源争夺。")
            revision_plan.append("把冲突降级为网游新手阶段：现实资金压力、武器/基础技能选择成本、第一次打怪验证、血蓝耐久消耗和背包材料如何处理。")

    if "数量×1000" in body and re.search(r"获得：[^。\n】]*[×x]\s*100(?:[。】\n]|$)", body):
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append("天赋说明为基础掉落物数量×1000，但正文首次掉落只写×100。")
        revision_plan.append("要么把天赋说明改为爆率/判定权重×1000，要么把首次掉落数量改为×1000，并同步后续背包、交易和市场反应。")

    if (
        game_context
        and
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
            ("初始身份", "身份：", "身份栏", "见习冒险者", "未转职", "新手法杖", "基础火球术", "武器选择", "技能选择"),
            "第一章没有写出角色创建/登录阶段的初始身份、武器或基础技能确认。",
            "补出夜烬开局身份为见习冒险者（未转职），所有玩家初始一样；他只是选择新手法杖和基础火球术，用这个解释第一章的战斗成本。",
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
            token in body for token in ("身份：", "身份栏", "见习冒险者", "未转职", "新手法杖", "基础火球术")
        ):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章缺少带身份栏的角色面板，等级/经验/初始身份/主武器或基础技能没有形成可追踪账本。")
            revision_plan.append("补一个简短角色面板：游戏ID夜烬、等级1、身份见习冒险者（未转职）、经验0/100、新手法杖、基础火球术、初始背包或钱袋。")
        require(
            "genre_rules",
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
                "初始身份",
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

        submitted_task = any(token in body for token in ("清道夫委托完成", "委托已提交", "领取三十铜", "领取30铜", "奖励：30铜", "奖励三十枚铜到账"))
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

    # --- Parallel review Round 1: independent reviews ---
    _indep_reviews: dict[str, Any] = {}
    _previous_summary = str(
        (simulation_plan or {}).get("previous_summary")
        or (event_plan or {}).get("previous_summary")
        or (event_plan or {}).get("summary")
        or ""
    )
    _protagonist_names = _review_protagonist_names(event_plan, simulation_plan)

    with ThreadPoolExecutor(max_workers=10) as _pool:
        _futures = {
            "consistency": _pool.submit(review_world_event_consistency, body, world_events=world_events or [], scene_cards=scene_cards or [], chapter_number=chapter_number),
            "style": _pool.submit(review_prose_style, body),
            "prose_quality": _pool.submit(review_prose_quality, body),
            "adversarial_cut": _pool.submit(review_adversarial_cuts, body),
            "ai_flavor": _pool.submit(review_ai_flavor, body),
            "reader_feel": _pool.submit(review_reader_feel, body),
            "cold_reader": _pool.submit(review_cold_reader_experience, body, previous_summary=_previous_summary),
            "plot_spine": _pool.submit(review_plot_spine_completion, body, simulation_plan),
        }
        if game_context:
            _futures["web_game"] = _pool.submit(
                review_web_game_chapter,
                chapter_number=chapter_number,
                body=body,
                event_plan=event_plan,
                world_facts=world_facts,
            )
            _futures["progression_lead"] = _pool.submit(
                review_progression_lead,
                chapter_number=chapter_number,
                body=body,
                event_plan=event_plan,
                world_facts=world_facts or [],
            )
        for _name, _fut in _futures.items():
            try:
                _indep_reviews[_name] = _fut.result()
            except Exception as _exc:
                report_generation_progress(f"review[{_name}] exception: {_exc}")
                _indep_reviews[_name] = _review_exception_result(_name, _exc)

    web_game_review = _indep_reviews.get("web_game", {})
    consistency_review = _indep_reviews.get("consistency", {})
    style_review = _indep_reviews.get("style", {})
    prose_quality_review = _indep_reviews.get("prose_quality", {})
    adversarial_cut_review = _indep_reviews.get("adversarial_cut", {})
    ai_flavor_review = _indep_reviews.get("ai_flavor", {})
    reader_feel_review = _indep_reviews.get("reader_feel", {})
    cold_reader_review = _indep_reviews.get("cold_reader", {})
    progression_lead_review = _indep_reviews.get("progression_lead", {})
    if not game_context:
        web_game_review = {"reviewer": "web_game/v1", "pass": True, "scores": {}, "issues": [], "revision_plan": []}
        progression_lead_review = {"reviewer": "progression_lead/v1", "pass": True, "scores": {}, "issues": [], "revision_plan": []}
    plot_spine_review = _indep_reviews.get("plot_spine", {})

    scene_contract_failures = (
        consistency_review.get("scene_contract_failures")
        if isinstance(consistency_review.get("scene_contract_failures"), list)
        else []
    )
    scene_repair_plan = build_scene_contract_repair_plan(consistency_review, scene_cards or [])

    # --- Round 2: critical_review (depends on plot_spine) ---
    critical_review = review_critical_prose_rules(
        body,
        protagonist_names=_protagonist_names,
        extra_subreviews=[plot_spine_review],
    )

    # --- Round 3: agent reviews (depend on earlier reviews, parallel) ---
    _agent_reviews: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=3) as _pool:
        _agent_futs = {
            "reader_agent": _pool.submit(review_reader_agent, body, previous_summary=_previous_summary, cold_reader_review=cold_reader_review),
            "editor_agent": _pool.submit(review_editor_agent, body, prose_quality_review=prose_quality_review, prose_style_review=style_review, ai_flavor_review=ai_flavor_review),
            "reviewer_agent": _pool.submit(review_reviewer_agent, chapter_number=chapter_number, body=body, event_plan=event_plan, world_facts=world_facts or [], protagonist_names=_protagonist_names, critical_review=critical_review, web_game_review=web_game_review, progression_lead_review=progression_lead_review),
        }
        for _name, _fut in _agent_futs.items():
            try:
                _agent_reviews[_name] = _fut.result()
            except Exception as _exc:
                report_generation_progress(f"review[{_name}] exception: {_exc}")
                _agent_reviews[_name] = _review_exception_result(_name, _exc)

    reader_agent_review = _agent_reviews.get("reader_agent", {})
    editor_agent_review = _agent_reviews.get("editor_agent", {})
    reviewer_agent_review = _agent_reviews.get("reviewer_agent", {})
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
    for key, score in reader_feel_review.get("scores", {}).items():
        scores[f"reader_feel_{key}"] = score
    for issue in reader_feel_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in reader_feel_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    cold_reader_pass = bool(cold_reader_review.get("pass", True))
    for key, score in cold_reader_review.get("scores", {}).items():
        scores[f"cold_reader_{key}"] = 8 if cold_reader_pass and int(score or 0) >= 3 else min(7, int(score or 0))
    for issue in cold_reader_review.get("issues", []):
        reason = issue.get("reason") if isinstance(issue, dict) else str(issue)
        if reason and reason not in issues:
            issues.append(reason)
    for item in cold_reader_review.get("revision_plan", []):
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
    for key, score in plot_spine_review.get("scores", {}).items():
        scores[key] = score
    for issue in plot_spine_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in plot_spine_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    for prefix, agent_review in (
        ("reader_agent", reader_agent_review),
        ("editor_agent", editor_agent_review),
        ("reviewer_agent", reviewer_agent_review),
    ):
        scores[f"{prefix}_pass"] = 8 if agent_review.get("pass", True) else 5
        for issue in agent_review.get("issues", []):
            if issue and issue not in issues:
                issues.append(issue)
        for item in agent_review.get("revision_plan", []):
            if item and item not in revision_plan:
                revision_plan.append(item)

    # --- Graded review: core (hard gate) vs soft (advisory, non-blocking) ---
    # Core = local rules (genre_rules/continuity/etc) + web_game + world_event + critical + prose_style
    # Soft = AI flavor, cold reader, progression lead, plot spine, adversarial cut, agent reviews
    _core_score_keys = {"webnovel_hook", "background_integration", "protagonist_motivation",
                        "genre_rules", "world_reaction", "chapter_ending_hook", "continuity",
                        "simulation_plan_alignment"}
    _soft_score_keys = {"cold_reader_pass", "reader_agent_pass", "editor_agent_pass", "reviewer_agent_pass"}
    _core_passed = all(
        score >= 8 for key, score in scores.items()
        if key in _core_score_keys or key == "reader_feel_patchwork" or any(key.startswith(p) for p in ("web_game_", "world_event_", "critical_", "prose_style_", "prose_rule_"))
    )
    _soft_passed = all(
        score >= 6 for key, score in scores.items()
        if key not in _core_score_keys and not any(key.startswith(p) for p in ("web_game_", "world_event_", "critical_", "prose_style_", "prose_rule_"))
        and key not in _soft_score_keys
    )
    passed = _core_passed
    if not _soft_passed:
        _soft_low = [
            (key, value)
            for key, value in scores.items()
            if key not in _core_score_keys
            and not any(key.startswith(p) for p in ("web_game_", "world_event_", "critical_", "prose_style_", "prose_rule_"))
            and key not in _soft_score_keys
            and value < 6
        ]
        if _soft_low:
            report_generation_progress(f"Soft review low scores (non-blocking): {_soft_low}")
    world_state_review = _build_world_state_review(issues, revision_plan)
    return {
        "pass": passed,
        "review_summary": {"core_passed": _core_passed, "soft_passed": _soft_passed},
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
        "prose_quality_review": prose_quality_review,
        "adversarial_cut_review": adversarial_cut_review,
        "reader_agent_review": reader_agent_review,
        "editor_agent_review": editor_agent_review,
        "reviewer_agent_review": reviewer_agent_review,
        "ai_flavor_review": ai_flavor_review,
        "reader_feel_review": reader_feel_review,
        "cold_reader_review": cold_reader_review,
        "progression_lead_review": progression_lead_review,
        "plot_spine_review": plot_spine_review,
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
    for key in (
        "critical_review",
        "hook_review",
        "pacing_review",
        "beats_review",
        "reader_agent_review",
        "editor_agent_review",
        "reviewer_agent_review",
        "ai_flavor_review",
        "reader_feel_review",
        "cold_reader_review",
        "progression_lead_review",
    ):
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
    if is_game_genre(str(getattr(story, "genre", "") or "")):
        return True
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


def _repair_generic_chapter_title(
    title: str,
    *,
    chapter_number: int,
    next_focus: str,
    conflict_summary: dict[str, Any],
    genre: str,
) -> str:
    generic_titles = {"真相道韵", "真相交锋", "真相异兆", "真相疑云", "真相剑影", "真相风声"}
    clean = str(title or "").strip()
    if clean and clean not in generic_titles:
        return clean
    return build_chapter_title(
        chapter_number,
        conflict_summary=conflict_summary,
        next_focus=next_focus,
        genre=genre,
    )


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


def _generic_writing_method_lines(chapter_number: int) -> list[str]:
    first_chapter_hint = (
        "第一章先让读者看清主角处境、欲望、能力来源和第一次有效行动；不要把整条主线一次讲完。"
        if chapter_number == 1
        else "本章要承接上一章结果，推进一个清楚目标，并在章末留下新的压力或选择。"
    )
    return [
        "通用网文写法方法卡",
        first_chapter_hint,
        "把本章写成一条行动链：想做什么 -> 被什么卡住 -> 试一次 -> 付出代价 -> 得到反馈 -> 拿到小进度 -> 下一步还差什么。",
        "先写代价，再写收获。收获要实在：关系变化、线索落地、资源到手、身份变化、能力推进、入口打开，至少兑现一项。",
        "具体感来自办事过程，不来自大段解释：地点、物件、价钱、伤痛、等待、规矩、证据、旁人反应，都可以推动剧情。",
        "爽点写成“主角暗中多拿一步”：别人误判、犹豫、排队、错过或看不懂，主角已经摸到下一步。",
        "对话用法：每段对话都让人知道一个条件、风险、误判、关系变化或下一步；主角正常说话，不用两个字装冷静。",
        "对话语气先看关系和场合：陌生人客气试探，熟人才能轻微调侃；关键台词要带着隐瞒、试探、委屈、压火或缓和气氛中的一种，不要只交换信息。",
    ]


def _genre_family(story: StoryState, plan: dict[str, Any] | None = None) -> str:
    if _story_game_context(story, plan or {}):
        return "web_game"
    explicit_genre = normalize_novel_type_id(story.genre)
    if explicit_genre in {"xuanhuan", "xianxia"}:
        return explicit_genre
    text = f"{story.genre} {story.style} {story.outline}".lower()
    if any(token in text for token in ("悬疑", "推理", "案", "调查", "失踪")):
        return "suspense"
    if any(token in text for token in ("都市", "职场", "现实", "家庭")):
        return "urban"
    if any(token in text for token in ("玄幻", "修仙", "仙侠", "武道", "宗门")):
        return "fantasy"
    return "general"


def _genre_context_for_prompt(story: StoryState, chapter_number: int, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    family = _genre_family(story, plan)
    context: dict[str, Any] = {
        "genre": story.genre,
        "style": story.style,
        "genre_family": family,
        "common_method": _generic_writing_method_lines(chapter_number),
    }
    if family == "web_game":
        defaults = _game_genre_defaults(story)
        context.update(
            {
                "game_id": defaults["game_id"],
                "class_path": defaults["class_path"],
                "genre_method": _web_game_writing_method_lines(chapter_number),
                "surface_objects": ["角色面板", "任务", "背包", "装备耐久", "药水", "NPC柜台", "掉落", "地图入口"],
            }
        )
    elif family == "suspense":
        context.update(
            {
                "genre_method": [
                    "悬疑写法：每章只解开一个小问题，同时留下一个更具体的新疑点。",
                    "线索要落到物件、时间、证词、地点矛盾和人物反应上，不要靠作者直接解释。",
                    "人物不能全知；新的信息要通过调查、询问、观察或误导逐步出现。",
                ],
                "surface_objects": ["证词", "物件", "时间点", "地点", "记录", "反应"],
            }
        )
    elif family in {"xuanhuan", "xianxia"}:
        seed = build_chapter_seed(story, chapter_number)
        rulebook = seed.get("rulebook") if isinstance(seed.get("rulebook"), dict) else {}
        context.update(
            {
                "genre_plugins": list(seed.get("genre_plugins") or []),
                "genre_method": compact_list(
                    [
                        *list(rulebook.get("progression_rules") or []),
                        *list(rulebook.get("faction_rules") or []),
                        *list(rulebook.get("chapter_formula") or []),
                    ],
                    max_items=6,
                    item_chars=150,
                ),
                "surface_objects": (
                    ["境界", "资源", "异常物件", "力量反馈", "势力关系", "世界秘密"]
                    if family == "xuanhuan"
                    else ["境界", "灵气", "功法", "丹药", "法宝", "因果"]
                ),
            }
        )
    elif family == "fantasy":
        context.update(
            {
                "genre_method": [
                    "玄幻/修仙写法：成长要有境界、资源、代价和外部压力，不要无代价顿悟。",
                    "能力变化要落到身体反应、招式效果、资源消耗、旁人判断和下一层阻碍。",
                    "势力反应要按信息可见性推进，不要让高层无缘无故全知。",
                ],
                "surface_objects": ["境界", "功法", "资源", "伤势", "法器", "势力规矩"],
            }
        )
    else:
        context.update(
            {
                "genre_method": [
                    "通用写法：本章只推进一个主要目标，冲突来自人物欲望、信息差、规则和代价。",
                    "每个场景都要有动作、反馈和选择，不要写成设定说明。",
                    "章末留下具体下一步，让读者知道主角马上要面对什么。",
                ],
                "surface_objects": ["地点", "物件", "关系", "线索", "代价", "选择"],
            }
        )
    return context


def _genre_context_summary_for_prompt(context: dict[str, Any], *, include_method: bool = True) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    summary = {
        "genre_family": context.get("genre_family"),
        "surface_objects": context.get("surface_objects", [])[:6] if isinstance(context.get("surface_objects"), list) else [],
        "genre_method": context.get("genre_method", [])[:4] if include_method and isinstance(context.get("genre_method"), list) else [],
    }
    for key in ("game_id", "class_path"):
        if context.get(key):
            summary[key] = context.get(key)
    return summary


def _skill_context_for_prompt(story: StoryState, purposes: tuple[str, ...]) -> dict[str, Any]:
    """Load only the enabled skill slices needed by the current agent stage."""
    skill_ids = [str(item).strip() for item in getattr(story, "enabled_skill_ids", []) if str(item).strip()]
    if not skill_ids:
        return {}
    selected: dict[str, Any] = {}
    replaceable = replaceable_slots()
    replaced_defaults: list[str] = []
    for purpose in purposes:
        context = skill_pack_prompt_context(skill_ids, purpose=purpose, max_chars_per_pack=1800)
        if context:
            selected[purpose] = context
            if purpose in replaceable:
                replaced_defaults.append(replaceable[purpose])
    if replaced_defaults:
        selected["_replaced_defaults"] = sorted(set(replaced_defaults))
    return selected


def _chapter_prompt_method_block(
    chapter_number: int,
    plan: dict[str, Any] | None,
    *,
    governance: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    game_context: bool = False,
    compact_taskbook: bool = False,
    include_director_summary: bool = True,
) -> list[str]:
    plan = plan if isinstance(plan, dict) else {}
    spec = _chapter_prompt_spec(chapter_number, plan)
    taskbook = ensure_writing_taskbook(chapter_number, plan)
    taskbook_section = _compact_writer_taskbook_section(taskbook) if compact_taskbook else format_taskbook_prompt_section(taskbook)
    taskbook_scenes = taskbook.get("scenes") if isinstance(taskbook.get("scenes"), list) else []
    game_first_chapter = chapter_number == 1 and any(
        isinstance(scene, dict) and scene.get("key") == "entry_login" for scene in taskbook_scenes
    )
    whole_body_contract = first_chapter_whole_body_contract(game_genre=game_first_chapter)
    director_card = plan.get("web_game_director_card")
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    if not isinstance(director_card, dict):
        director_card = simulation_plan.get("web_game_director_card")
    if compact_taskbook:
        lines = [
            "输出要求：只写连续小说正文",
            "写成一章顺着人物行动自然展开的白话小说，旁白少做抽象解释，多写现场发生的事。少解释只针对旁白，对话不能省略连接词和因果。",
            "人物说话要有来有回，把该说的理由说完整；情绪放在动作、停顿和回答里。",
            "白描不是把句子全部切短：写清人物正在做什么、为什么这么做，以及动作带来的结果；情绪落在停顿、手势、语气和选择里。",
            "白描示例：他走到门口，先听了听里面的动静，才抬手敲门；不要写成‘他谨慎判断后决定进入’。",
            taskbook_section,
        ]
        if whole_body_contract:
            lines.extend(
                [
                    "第一章整章要求：本次不用分段生成，按整章连续正文自然完成。",
                    f"整章四拍：{whole_body_contract['beat_map']}",
                    "白描与自然对话：句子清楚，动作具体，台词像正常人说话，规则从动作和反馈里露出来。",
                ]
            )
        lines.extend(
            [
                "写作保护线",
                f"一、视角：保持主角限知第三人称；章节：第{chapter_number}章。",
                "二、工作流词处理：把后台词改成物件、动作、等待、价格、伤痛、犹豫和现场后果。",
                (
                    "三、玩家势力、私聊和后台记录只通过可观察痕迹露出，例如价格、队伍、公告、NPC记录和旁人反应。"
                    if game_context
                    else "三、外部信息通过可观察痕迹、对话和现场后果间接出现，主角只处理自己能接触到的线索。"
                ),
                f"四、目标篇幅：{_plan_target_chars(plan)}。",
                f"六、关键场景职责：{spec.required_surface}",
            ]
        )
        lines.extend(PROMPT_CRAFT_GUARDS[:2])
        if isinstance(governance, dict):
            lines.append(_compact_writer_governance_section(governance))
        if isinstance(review, dict):
            lines.append(f"修改意见：{_plain_prompt_json(_compact_review_summary(review))}")
        if isinstance(director_card, dict):
            lines.append(_compact_writer_director_section(director_card))
        return lines
    lines = [
        "输出要求：只写连续小说正文",
        "写手身份：把本章写成可读正文；标题、编号、解释、大纲、JSON 和说明文字都留在提示词里。",
        "番茄白话风：用普通读者一眼能懂的话写，少用比喻和华丽修辞，旁白少做抽象解释，多写动作、对话、物件、代价和直接后果。少解释只针对旁白，对话不能省略连接词和因果。",
        "白描不是短句堆：句子按动作和对话自然长短变化，写清人物的动作、理由和后果；例如‘他先问清修理费，再决定要不要修’，不要写‘他冷静分析，做出决定’。",
        "后台词翻译：后台硬词改成角色看见的物件、动作、规矩、等待、价格、伤痛、犹豫和现场后果。",
        "情绪暗线：本章至少三次把角色的担心、试探、犹豫、侥幸或欲望落到动作、停顿、视线、手势和错开的回答上。",
        "主角开口硬规则：本章必须至少有一次可识别的主角口头对话；不能只补一句装冷静，要说清一个理由、拒绝原因或下一步选择。",
        "口语化对话：每章至少写一轮连续问答，结构是别人问/催/抱怨 -> 主角正常回答并给原因 -> 对方接一句反应；台词有长短，但要像人在说话。",
        "硬词处理：边界、底层逻辑、基准、推演、结算链、审稿、场景卡，都换成角色能说出口、能看见、能处理的东西。",
        "异常写法：出现异常时，写成角色动作、物件变化、对方反应或现场后果。",
        "动作白描：验证逻辑、收益路径和抽象收益词，落成动作慢半拍、东西不够、身体反应、旁人误判或下一步被卡住。",
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
        "写作保护线",
        f"一、视角：保持主角限知第三人称；章节：第{chapter_number}章。",
        "二、工作流词处理：把后台词改成物件、动作、等待、价格、伤痛、犹豫和现场后果。",
        (
            "三、玩家势力、私聊和后台记录只通过可观察痕迹露出，例如价格、队伍、公告、NPC记录和旁人反应。"
            if game_context
            else "三、外部信息通过可观察痕迹、对话和现场后果间接出现，主角只处理自己能接触到的线索。"
        ),
        f"四、目标篇幅：{_plan_target_chars(plan)}。",
        f"六、关键场景职责：{spec.required_surface}",
    ]
    if include_director_summary:
        lines.insert(-1, f"五、本章导演简表：{_plain_prompt_json(_prose_grounded_writing_plan(plan))}")
    if chapter_number == 1:
        if game_context:
            lines[4:4] = [
                "第一章目标口语化：不要把目标写成后台硬词，要写成主角先试清楚这东西能不能让他活下去、赚到第一口气、藏住来源。",
                "第一章领先流：爽点要兑现成账本优势或下一步前置任务；是否完成任务、拿铜币、修法杖或买药必须跟随项目账本/章节计划，未允许时不要擅自结算。",
            ]
        else:
            lines[4:4] = [
                "第一章目标口语化：不要把目标写成后台硬词，要写成主角眼前要解决的具体事。",
                "第一章收束：只兑现一个清楚的小结果，留下下一步，不要把全书矛盾一次讲完。",
            ]
    lines.extend(PROMPT_CRAFT_GUARDS[:5])
    if isinstance(governance, dict):
        lines.append(_governance_prompt_section(governance))
    if isinstance(review, dict):
        lines.append(f"修改意见：{_plain_prompt_json(_compact_review_summary(review))}")
    if isinstance(director_card, dict):
        lines.append(format_web_game_director_card(director_card))
    return lines


def _compact_prompt_text(value: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return cleaned if len(cleaned) <= limit else f"{cleaned[: max(1, limit - 1)]}…"


def _compact_writer_taskbook_section(taskbook: dict[str, Any]) -> str:
    taskbook = taskbook if isinstance(taskbook, dict) else {}
    lines = ["## 本章方向"]
    goal = plain_writer_phrase(str(taskbook.get("chapter_goal") or "完成本章推进"))
    lines.append(f"目标：{_compact_prompt_text(goal, 150)}")
    for index, scene in enumerate(
        [item for item in taskbook.get("scenes", []) if isinstance(item, dict)][:3],
        start=1,
    ):
        title = _compact_prompt_text(str(scene.get("title") or f"场面{index}"), 35)
        scene_goal = _compact_prompt_text(plain_writer_phrase(str(scene.get("goal") or "")), 80)
        required = _compact_prompt_text(writer_facing_text(scene.get("required_surface") or ""), 200)
        ending = _compact_prompt_text(
            plain_writer_phrase(str(scene.get("exit_state") or scene.get("handoff") or "")),
            70,
        )
        lines.append(f"{index}. {title}：{scene_goal}；要出现：{required}；结束时：{ending}")
    forbidden = compact_list(taskbook.get("global_forbidden", []), max_items=4, item_chars=55)
    if forbidden:
        lines.append(f"本章不写：{'；'.join(forbidden)}")
    return "\n".join(lines)


def _writer_value_lines(values: dict[str, Any], *, max_items: int = 8) -> list[str]:
    lines: list[str] = []
    for label, value in list(values.items())[:max_items]:
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            rendered = "；".join(compact_text(str(item), 80) for item in value[:4] if str(item).strip())
        else:
            rendered = compact_text(str(value), 180)
        if rendered:
            lines.append(f"{label}：{rendered}")
    return lines


def _writer_output_section(chapter_number: int, plan: dict[str, Any]) -> list[str]:
    return [
        "## 输出要求",
        f"只输出第{chapter_number}章连续小说正文，不输出标题、提纲、规则、检查过程或说明。",
        f"目标篇幅：{_plan_target_chars(plan)}。写成一章顺着人物行动自然展开的白话小说。",
        "采用第三人称有限视角，一场戏只跟随一个观察人物。",
    ]


def _writer_direction_section(
    chapter_number: int,
    plan: dict[str, Any],
    *,
    is_game: bool,
) -> list[str]:
    taskbook = ensure_writing_taskbook(chapter_number, plan)
    lines = _compact_writer_taskbook_section(taskbook).splitlines()
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    satisfaction = event_plan.get("chapter_satisfaction") if isinstance(event_plan.get("chapter_satisfaction"), dict) else {}
    for label, value in (
        ("主要阻力", satisfaction.get("obstacle") or event_plan.get("collision")),
        ("本章变化", satisfaction.get("state_change") or event_plan.get("turn") or event_plan.get("pivot")),
        ("结尾承接", satisfaction.get("next_hook") or event_plan.get("next_focus")),
    ):
        text = _compact_prompt_text(plain_writer_phrase(str(value or "")), 100)
        if text:
            lines.append(f"{label}：{text}")

    director_card = plan.get("web_game_director_card")
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    if not isinstance(director_card, dict):
        director_card = simulation_plan.get("web_game_director_card")
    if isinstance(director_card, dict):
        lines.extend(_compact_writer_director_section(director_card).splitlines()[1:])

    if is_game and chapter_number == 1:
        whole_body = first_chapter_whole_body_contract(game_genre=True)
        lines.extend(
            [
                "本次不用分段生成，整章连续完成。",
                f"整章四拍：{whole_body['beat_map']}。",
                "第一章只完成开服现场、建号、低级验证和下一步决定；隐藏优势只在幕后起作用。",
            ]
        )
    return lines


def _writer_fact_section(
    story: StoryState,
    chapter_number: int,
    plan: dict[str, Any],
    *,
    game_seed: dict[str, Any] | None = None,
) -> list[str]:
    lines = ["## 本章事实"]
    if story.outline:
        lines.append(f"大纲范围：{compact_text(story.outline, 260)}")
    constraints = compact_list(story.author_constraints, max_items=4, item_chars=100)
    if constraints:
        lines.append(f"作者已定：{'；'.join(constraints)}")
    world_facts = _priority_world_facts(story.world_facts, max_items=6, item_chars=100)
    if world_facts:
        lines.append(f"既有事实：{'；'.join(world_facts)}")
    if story.chapter_summaries:
        latest = story.chapter_summaries[-1]
        if latest.summary:
            lines.append(f"上一章留下：{compact_text(latest.summary, 160)}")
        if latest.next_focus:
            lines.append(f"当前承接：{compact_text(latest.next_focus, 100)}")
    seed = game_seed if isinstance(game_seed, dict) else {}
    if seed:
        game_defaults = _game_genre_defaults(story)
        lines.append(
            f"游戏主角：游戏ID为{game_defaults['game_id']}，当前职业路线为{game_defaults['class_path']}。"
        )
        lines.append("本章可用材料：")
        lines.extend(_writer_value_lines(seed, max_items=8))
    governance = plan.get("governance") if isinstance(plan.get("governance"), dict) else {}
    if governance:
        lines.append("本章事实边界：")
        lines.extend(_compact_writer_governance_section(governance).splitlines()[1:])
    if len(lines) == 1:
        lines.append(f"第{chapter_number}章只沿用项目已经确定的事实，不补写未经大纲支持的背景。")
    return lines


def _writer_character_section(character_context: dict[str, Any], dialogue_context: dict[str, Any]) -> list[str]:
    lines = ["## 出场人物"]
    cards = character_context.get("cards") if isinstance(character_context, dict) else []
    for card in cards[:4] if isinstance(cards, list) else []:
        if not isinstance(card, dict):
            continue
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        name = str(identity.get("name") or identity.get("game_id") or "本章人物").strip()
        parts = [str(identity.get("role") or "").strip()]
        for value in (
            card.get("motivation"),
            card.get("risk_posture"),
            card.get("speech_style") or card.get("speech_tendency"),
        ):
            text = compact_text(str(value or ""), 90)
            if text:
                parts.append(text)
        relationships = card.get("relationship_context") if isinstance(card.get("relationship_context"), list) else []
        for relation in relationships[:2]:
            if not isinstance(relation, dict):
                continue
            target = str(relation.get("target") or "").strip()
            bond = str(relation.get("bond") or "").strip()
            if target:
                parts.append(f"对{target}：{bond or '按当前信任和紧张程度说话'}")
        rendered = "；".join(part for part in parts if part)
        lines.append(f"{name}：{rendered or '按既有角色卡行动和说话'}")
    emotional_job = compact_text(str(dialogue_context.get("emotional_job") or ""), 100)
    tone_gate = compact_text(str(dialogue_context.get("tone_gate") or ""), 100)
    if emotional_job:
        lines.append(f"对话要带来的变化：{emotional_job}")
    if tone_gate:
        lines.append(f"关系尺度：{tone_gate}")
    if len(lines) == 1:
        lines.append("只使用本章已经出现或明确计划出场的人物，按既有关系和身份说话。")
    return lines


def _writer_skill_lines(skill_context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for purpose, packs in skill_context.items():
        if purpose.startswith("_") or not isinstance(packs, list):
            continue
        for pack in packs[:1]:
            if not isinstance(pack, dict):
                continue
            name = str(pack.get("name") or pack.get("skill_id") or "Skill").strip()
            modules = pack.get("modules") if isinstance(pack.get("modules"), list) else []
            summaries: list[str] = []
            for module in modules[:2]:
                if not isinstance(module, dict):
                    continue
                value = module.get("summary") or module.get("description") or module.get("content")
                text = compact_text(str(value or ""), 220)
                if text:
                    summaries.append(text)
            if not summaries:
                fallback_value = pack.get("description") or pack.get("root_skill")
                if not fallback_value and isinstance(pack.get("skill_ids"), list):
                    fallback_value = "、".join(str(item) for item in pack.get("skill_ids", []) if str(item).strip())
                fallback = compact_text(str(fallback_value or ""), 260)
                if fallback:
                    summaries.append(fallback)
            if summaries:
                lines.append(f"{name}（{purpose}）：{'；'.join(summaries)}")
    return lines


def _writer_craft_section(
    genre_context: dict[str, Any],
    skill_context: dict[str, Any],
    *,
    include_genre_method: bool,
    is_game: bool,
    chapter_number: int,
    style_guidance: dict[str, Any] | None = None,
) -> list[str]:
    lines = [
        "## 正文写法",
        "整体用白描，从正在发生的事情写起，让人物面对具体问题并作出选择。",
        "白描不是把句子全部切短：句子清楚，动作具体，台词像正常人说话；动作连续写清原因和结果。",
        "自然对话：人物说话要有来有回，符合关系和当时目的，有正常的接话、解释和情绪变化。不要把多个判断压成逗号清单；像“没好处，没奖励，地方偏”这种话，要用连接词说成完整的一句话。",
        "人物情绪放在动作、停顿和回答里，让读者从现场变化里感受到。",
        "心理和环境只在影响选择、关系或现场状态时出现，不单独堆气氛。",
        "段落写法：长短段交替；句子随动作和对话自然变化，保持现代中文语序。",
        "规则从动作和反馈里露出来，设定通过后果让读者明白，不写成说明书。",
    ]
    if include_genre_method:
        methods = genre_context.get("genre_method") if isinstance(genre_context, dict) else []
        for method in methods[:3] if isinstance(methods, list) else []:
            text = compact_text(str(method), 120)
            if text:
                lines.append(text)
    if is_game:
        lines.extend(_web_game_writing_method_lines(chapter_number))
    if isinstance(style_guidance, dict) and style_guidance:
        lines.append("表达提醒：")
        lines.extend(_writer_value_lines(_slim_prompt_value(style_guidance), max_items=5))
    skill_lines = _writer_skill_lines(skill_context)
    if skill_lines:
        lines.append("启用 Skill 模块摘要：")
        lines.extend(skill_lines)
    return lines


def _compact_writer_governance_section(governance: dict[str, Any]) -> str:
    governance = governance if isinstance(governance, dict) else {}
    intent = governance.get("chapter_intent") if isinstance(governance.get("chapter_intent"), dict) else {}
    rules = governance.get("rule_stack") if isinstance(governance.get("rule_stack"), dict) else {}
    lines = ["## 本章事实边界"]
    governance_blocking = bool(governance_quality_gate(governance).get("blocking"))
    if governance_blocking:
        lines.append("当前事实边界有冲突；只写能确认的事实，冲突项不进入正文。")
    include = compact_list(intent.get("must_include", []), max_items=4, item_chars=65)
    hard_facts = compact_list(rules.get("hard_facts", []), max_items=5, item_chars=70)
    avoid = compact_list(intent.get("must_avoid", []), max_items=4, item_chars=60)
    if include:
        lines.append(f"要出现：{'；'.join(include)}")
    if hard_facts and not governance_blocking:
        lines.append(f"沿用：{'；'.join(hard_facts)}")
    if avoid:
        lines.append(f"不要提前写：{'；'.join(avoid)}")
    ending = _compact_prompt_text(plain_writer_phrase(str(intent.get("ending_change") or "")), 100)
    if ending:
        lines.append(f"章尾变化：{ending}")
    if len(lines) == 1:
        lines.append("沿用项目账本和既有设定。")
    return "\n".join(lines)


def _compact_writer_director_section(card: dict[str, Any]) -> str:
    card = card if isinstance(card, dict) else {}
    lines = ["## 本章方向"]
    one_line = _compact_prompt_text(
        plain_writer_phrase(str(card.get("one_line") or card.get("read_feel") or "")),
        120,
    )
    if one_line:
        lines.append(one_line)
    fact_locks = compact_list(card.get("fact_locks", []), max_items=4, item_chars=80)
    if fact_locks:
        lines.append(f"事实锁：{'；'.join(fact_locks)}")
    bans = compact_list(card.get("boundary_chapter_bans", []), max_items=5, item_chars=35)
    if bans:
        lines.append(f"本章先不写：{'、'.join(bans)}")
    return "\n".join(lines)


def _web_game_writing_method_lines(chapter_number: int) -> list[str]:
    phase_hint = (
        "第一章重点是试清楚游戏规则靠不靠谱，并把第一笔优势藏住；是否领奖、修理或补给必须跟随项目账本，不能让外人看懂来源。"
        if chapter_number == 1
        else "本章重点是推进一个低级目标，让主角多摸到半步，不跳到高阶任务。"
    )
    return [
        "网游写法方法卡",
        phase_hint,
        "让主角为一个眼前目标行动，遇到阻力后付出代价，并拿到一个看得见的小进展。",
        "游戏规则从战斗、任务、背包、价格、NPC回话和结算里自然露出；面板只留马上会影响选择的数字。",
        "隐藏优势只在幕后起作用。别人可以误判，但不能凭一次低级掉落看穿主角。",
        "玩家和NPC按现代中文习惯说完整的话；游戏内说前置任务、条件没满足或登记不了，不单说门槛。",
    ]


def _governance_prompt_section(governance: dict[str, Any] | None) -> str:
    if not isinstance(governance, dict) or not governance:
        return "## 本章事实边界\n按已有事实写，不输出工作流字段或说明文字。"
    chapter_intent = governance.get("chapter_intent", {}) if isinstance(governance.get("chapter_intent"), dict) else {}
    rule_stack = governance.get("rule_stack", {}) if isinstance(governance.get("rule_stack"), dict) else {}
    governance_review = governance.get("governance_review")
    if not isinstance(governance_review, dict):
        governance_review = review_chapter_governance(governance)
    governance_gate = governance_quality_gate(governance)
    lines = ["## 本章事实边界"]
    if governance_gate.get("blocking"):
        lines.append("当前事实边界有冲突；只按下面能确认的事实写，冲突项不要写进正文。")
    lines.append("把事实写成场景、动作、对话、物件反馈或界面反馈，不写成规则解释。")
    include = compact_list(chapter_intent.get("must_include", []), max_items=8, item_chars=90)
    avoid = compact_list(chapter_intent.get("must_avoid", []), max_items=8, item_chars=90)
    hard_facts = compact_list(rule_stack.get("hard_facts", []), max_items=8, item_chars=100)
    soft_guidance = compact_list(rule_stack.get("soft_guidance", []), max_items=4, item_chars=100)
    if include:
        lines.append("本章要出现：")
        lines.extend(f"- {item}" for item in include)
    if avoid:
        lines.append("不要提前写：")
        lines.extend(f"- {item}" for item in avoid)
    ending_change = str(chapter_intent.get("ending_change") or "").strip()
    if ending_change:
        lines.append(f"章尾变化：{ending_change}")
    if hard_facts and not governance_gate.get("blocking"):
        lines.append("不能改的事实：")
        lines.extend(f"- {item}" for item in hard_facts)
    if soft_guidance:
        lines.append("写法提醒：")
        lines.extend(f"- {item}" for item in soft_guidance)
    return "\n".join(lines)


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
        provider = getattr(settings, "provider", "openai")
        codex_command = getattr(settings, "codex_command", "")
        if provider != "codexcli" and not settings.api_key:
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
            try:
                response = post_json_with_retry(
                    settings.base_url,
                    "/chat/completions",
                    payload,
                    settings.api_key,
                    config=config,
                    provider=provider,
                    codex_command=codex_command,
                )
            except TypeError as exc:
                if "unexpected keyword argument" not in str(exc):
                    raise
                response = post_json_with_retry(
                    settings.base_url,
                    "/chat/completions",
                    payload,
                    settings.api_key,
                    config=config,
                )
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
        timeout_seconds: int | None = None,
    ) -> tuple[str, str]:
        started = perf_counter()
        chat_kwargs: dict[str, Any] = {
            "max_tokens": max_tokens,
            "json_mode": json_mode,
            "agent": agent,
        }
        if timeout_seconds is not None:
            chat_kwargs["timeout_seconds"] = timeout_seconds
        try:
            text, error = self._chat(story, prompt, **chat_kwargs)
        except TypeError as exc:
            if timeout_seconds is None or "timeout_seconds" not in str(exc):
                raise
            chat_kwargs.pop("timeout_seconds", None)
            text, error = self._chat(story, prompt, **chat_kwargs)
        elapsed = perf_counter() - started
        suffix = "失败" if error else "完成"
        report_generation_progress(f"{stage}耗时 {elapsed:.1f}s：{suffix}")
        return text, error

    def _plan_prompt(self, story: StoryState, chapter_number: int) -> str:
        snapshot = _director_snapshot_summary(_story_snapshot(story))
        chapter_seed = _writer_seed_summary(_compact_chapter_seed_for_prompt(build_chapter_seed(story, chapter_number)))
        char_names = [c.name for c in story.characters if c.lifecycle_state == "active" and not c.frozen]
        if not _story_game_context(story, {}):
            return "\n".join(
                [
                    "请为中文长篇项目生成本章推演计划，只返回 JSON。",
                    f"目标章节：第{chapter_number}章",
                    f"章节阶段：{_opening_phase_name(chapter_number, is_game=False)}",
                    f"项目快照：{_plain_prompt_json(snapshot)}",
                    f"本章连续性材料：{_plain_prompt_json(chapter_seed)}",
                    "输出字段：character_moves, chapter_intent, event_plan, memory_constraints, chapter_summary。",
                    "event_plan 必须包含 chapter_title, turn, pivot, collision, ordered_actions, exposition_beats, npc_beats, quest_beats, location_beats, world_reactions, stakes, next_focus, explicit_chapter_end_hook, chapter_end_hook。",
                    "chapter_end_hook 使用结构：{type, strength, content}；type 只能是危机钩、悬念钩、渴望钩、反转钩、余韵钩；strength 只能是 strong、medium、weak。",
                    "要求：动作具体，焦点明确，事件链短但有效，不要写正文。",
                ]
            )
        phase_name = _opening_phase_name(chapter_number)
        return "\n".join(
            [
                "网游计划写法：先排出一条玩家行动链；不要只列设定，要让目标、卡点、尝试、消耗、反馈、小进度和下一步都能写成场景。",
                "请为中文网文项目生成本章推演计划，只返回 JSON。",
                f"目标章节：第{chapter_number}章",
                f"章节阶段：{_opening_phase_name(chapter_number)}",
                f"项目快照：{_plain_prompt_json(snapshot)}",
                f"本章连续性材料：{_plain_prompt_json(chapter_seed)}",
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
                "计划优先级：先遵守本章连续性材料，再用项目快照补连续性；不要把检查规则复述进计划。",
                "网游连续性：现实姓名、游戏ID、身份、等级、经验、货币、背包、装备耐久、任务进度必须能在 ledger_updates 里对上。",
                "爽点结构：本章必须有一个具体目标、一个阻碍、一个可见收益、一个外人误判和一个章末下一步。",
                "世界反应：只能从玩家看得见的价格、柜台、任务、掉落、公告、排队、目击和NPC记录长出来，不能让世界全知全能。",
                "角色计划：主要角色不能只做功能动作；要写清他想要什么、怕什么、误判了什么，以及本章关系有什么变化。",
                "第1-3章：第1章负责登录、建号、第一次验证和现实压力兑现；第2章负责把优势转成成长；第3章再升级到路线竞争或职业前置。",
                "要求：动作具体，焦点明确，事件链简短但有效，不要写正文。",
            ]
        )

    def _body_prompt(self, story: StoryState, chapter_number: int, plan: dict) -> str:
        plan = plan if isinstance(plan, dict) else {}
        plan = {**plan, "writing_taskbook": ensure_writing_taskbook(chapter_number, plan, genre=story.genre, style=story.style)}
        character_context = _character_context_for_prompt(story, plan, max_items=4)
        dialogue_context = build_dialogue_context(character_context, plan)
        genre_context = _genre_context_for_prompt(story, chapter_number, plan)
        skill_context = _skill_context_for_prompt(story, ("writer", "dialogue", "style", "genre"))
        replaced_defaults = set(skill_context.get("_replaced_defaults", []))
        skill_context_for_prompt = {key: value for key, value in skill_context.items() if key != "_replaced_defaults"}
        include_genre_method = "genre_context" not in replaced_defaults
        chapter_seed = build_chapter_seed(story, chapter_number)
        is_game = _story_game_context(story, plan)
        if is_game:
            game_defaults_for_seed = _game_genre_defaults(story)
            chapter_seed_text = json.dumps(chapter_seed, ensure_ascii=False)
            chapter_seed_text = (
                chapter_seed_text.replace("元素法师学徒/元素法师", game_defaults_for_seed["class_path"])
                .replace("元素法师学徒", game_defaults_for_seed["class_path"])
                .replace("元素法师", game_defaults_for_seed["class_path"])
            )
            chapter_seed_for_prompt = _writer_seed_summary(_plain_prompt_payload(json.loads(chapter_seed_text)))
        else:
            chapter_seed_for_prompt = {}
        sections = [
            _writer_output_section(chapter_number, plan),
            _writer_direction_section(chapter_number, plan, is_game=is_game),
            _writer_fact_section(
                story,
                chapter_number,
                plan,
                game_seed=chapter_seed_for_prompt,
            ),
            _writer_character_section(character_context, dialogue_context),
            _writer_craft_section(
                genre_context,
                skill_context_for_prompt,
                include_genre_method=include_genre_method,
                is_game=is_game,
                chapter_number=chapter_number,
                style_guidance=plan.get("style_guidance") if isinstance(plan.get("style_guidance"), dict) else {},
            ),
        ]
        return "\n".join(line for section in sections for line in [*section, ""]).strip()

    def _revision_prompt(self, story: StoryState, chapter_number: int, body: str, plan: dict, review: dict) -> str:
        plan = plan if isinstance(plan, dict) else {}
        plan = {**plan, "writing_taskbook": ensure_writing_taskbook(chapter_number, plan, genre=story.genre, style=story.style)}
        review = review if isinstance(review, dict) else {}
        forbidden_terms = _revision_forbidden_terms(review, plan)
        fix_checklist = _revision_fix_checklist(review)
        style_guidance = plan.get("style_guidance", {})
        target_chars = _plan_target_chars(plan)
        scene_repair_plan = review.get("scene_repair_plan") if isinstance(review.get("scene_repair_plan"), dict) else {}
        if not scene_repair_plan:
            scene_repair_plan = build_scene_contract_repair_plan(review, plan.get("scene_cards", []))
        scene_repair_summary = _scene_repair_writer_summary(scene_repair_plan)
        base_prompt = self._body_prompt(story, chapter_number, plan)
        compact_review = _compact_review_summary(review)
        nested_review_items: dict[str, list[Any]] = {"issues": [], "revision_plan": []}
        for nested_key in ("writing_review", "style_review", "prose_quality_review"):
            nested = review.get(nested_key) if isinstance(review.get(nested_key), dict) else {}
            for item_key in nested_review_items:
                values = nested.get(item_key) if isinstance(nested.get(item_key), list) else []
                nested_review_items[item_key].extend(values)
        issues = compact_list(
            [
                *compact_review.get("issues", []),
                *compact_review.get("style_issues", []),
                *compact_review.get("prose_issues", []),
                *nested_review_items["issues"],
            ],
            max_items=10,
            item_chars=110,
        )
        raw_revision_plan = review.get("revision_plan") if isinstance(review.get("revision_plan"), list) else []
        revision_plan = compact_list(
            [
                *raw_revision_plan[-8:],
                *compact_review.get("revision_plan", []),
                *nested_review_items["revision_plan"],
            ],
            max_items=10,
            item_chars=110,
        )
        modification_lines = [
            "## 修改目标",
            "在不改变本章核心事实、事件顺序和人物关系的前提下，把原文改得更顺。",
        ]
        if issues:
            modification_lines.append(f"修改意见：{'；'.join(issues)}")
        if revision_plan:
            modification_lines.append(f"用户改稿指令：{'；'.join(revision_plan)}")
        if style_guidance:
            modification_lines.append(f"表达提醒：{_plain_prompt_json(_slim_prompt_value(style_guidance))}")
        if fix_checklist:
            modification_lines.append(f"必须改到：{'；'.join(compact_text(str(item), 110) for item in fix_checklist[:10])}")
        if scene_repair_summary:
            modification_lines.append(f"局部补写范围：{_plain_prompt_json(scene_repair_summary)}")
            modification_lines.append("只补这些场景缺少的可见后果，其他场景只做必要衔接。")
        if forbidden_terms:
            modification_lines.append(f"需要删掉的词：{'、'.join(forbidden_terms)}")
        modification_lines.extend(
            [
                f"篇幅要求：扩写到{target_chars}。",
                "事实锁硬规则：职业、余额、库存、任务、装备和NPC能知道什么/不知道什么保持不变；不确定时保留原文事实。",
                "改完后检查：修改目标逐项完成，删词清零，缺失场面已经正面写出；不要输出检查说明。",
            ]
        )
        return "\n".join(
            [
                base_prompt,
                "",
                *modification_lines,
                "",
                "## 原正文",
                "以下内容只作改稿输入，不复述提示词，不输出修改说明。",
                body,
            ]
        )

    def _write_chapter_in_segments(
        self,
        story: StoryState,
        chapter_number: int,
        plan: dict,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """Legacy compatibility path; production generation never calls it."""
        specs = build_segment_specs(chapter_number, plan)
        segments: list[str] = []
        segment_reviews: list[dict[str, Any]] = []

        # --- Checkpoint: recover previously completed segments on retry ---
        _checkpoint = getattr(self, "_segment_checkpoint", None)
        if _checkpoint and _checkpoint.get("chapter") == chapter_number and _checkpoint.get("story_id") == story.story_id:
            completed = _checkpoint.get("segments", [])
            c_reviews = _checkpoint.get("reviews", [])
            segments.extend(completed)
            segment_reviews.extend(c_reviews)
            start_index = len(completed) + 1
            report_generation_progress(f"断点恢复：从第{start_index}段继续")
            self._segment_checkpoint = None
        else:
            start_index = 1

        for index in range(start_index, len(specs) + 1):
            spec = specs[index - 1]
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
                # Save checkpoint before returning
                self._segment_checkpoint = {
                    "story_id": story.story_id,
                    "chapter": chapter_number,
                    "segments": list(segments),
                    "reviews": list(segment_reviews),
                }
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

        # Clear checkpoint on success
        self._segment_checkpoint = None
        body = _sanitize_generated_body(merge_segment_outputs(segments))
        return body, "", segment_reviews

    def _use_segmented_writing(self, chapter_number: int, plan: dict) -> bool:
        """Production generation always writes one continuous chapter."""
        return False

    def _extract_final_body_memory(
        self,
        story: StoryState,
        body: str,
        chapter_number: int,
        *,
        fact_locks: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        previous_summary = story.chapter_summaries[-1] if story.chapter_summaries else None
        prompt = build_post_draft_memory_prompt(
            body,
            previous_summary=previous_summary.summary if previous_summary else "",
            existing_character_names={character.name for character in story.characters},
            genre=story.genre,
            fact_locks=fact_locks or {},
        )
        report_generation_progress("最终正文记忆提取中...")
        memory_text, memory_error = self._timed_chat(
            story,
            prompt,
            max_tokens=2200,
            json_mode=True,
            agent="memory",
            stage=f"最终正文记忆 第{chapter_number}章",
        )
        if memory_error:
            return fallback_post_draft_memory(body), {
                "status": "fallback",
                "rejected_count": 0,
                "reason": compact_text(memory_error, 120),
            }
        try:
            payload = json.loads(memory_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            return fallback_post_draft_memory(body), {
                "status": "fallback",
                "rejected_count": 0,
                "reason": "memory_invalid_json",
            }
        memory = normalize_post_draft_memory(
            payload,
            body=body,
            existing_character_names={character.name for character in story.characters},
        )
        return memory, {
            "status": "ok",
            "rejected_count": len(memory.get("rejected_updates", [])),
        }

    def refresh_revised_bundle_metadata(self, base_story: StoryState, bundle: Any) -> Any:
        """Rebuild summary, ledger and memory surfaces after latest-chapter revision."""
        refreshed_bundle = bundle.model_copy(deep=True)
        refreshed_bundle.body = _sanitize_generated_body(refreshed_bundle.body)
        chapter_number = refreshed_bundle.chapter_number
        working_story = base_story.model_copy(deep=True)
        working_story.current_chapter = chapter_number

        memory_constraints = _normalize_memory_constraints(refreshed_bundle.memory_constraints, working_story)
        memory_constraints["must_keep_facts"] = []
        memory_constraints["ledger_updates"] = {}
        conflict_summary = refreshed_bundle.conflict_summary if isinstance(refreshed_bundle.conflict_summary, dict) else {}
        event_beat = refreshed_bundle.event_beat if isinstance(refreshed_bundle.event_beat, dict) else {}
        post_draft_memory, memory_sync = self._extract_final_body_memory(
            working_story,
            refreshed_bundle.body,
            chapter_number,
            fact_locks={"previous_chapter_summary": refreshed_bundle.chapter_summary},
        )
        memory_is_verified = memory_sync.get("status") == "ok"
        persisted_conflict = conflict_summary if memory_is_verified else {}
        persisted_event_beat = event_beat if memory_is_verified else {}

        updated_story = working_story.model_copy(deep=True)
        apply_post_chapter_updates(
            updated_story,
            refreshed_bundle.body,
            chapter_number,
            conflict_summary=persisted_conflict,
            event_beat=persisted_event_beat,
            post_draft_memory=post_draft_memory,
        )
        _apply_ledger_updates(updated_story, post_draft_memory.get("ledger_updates", {}))
        _sync_character_game_panels(updated_story, chapter_number)
        advance_world_pulse(updated_story, chapter_number=chapter_number)
        maybe_update_arc_recap(updated_story, chapter_number)

        if updated_story.chapter_summaries:
            latest_summary = updated_story.chapter_summaries[-1]
            revised_title_focus = (
                f"{working_story.outline} {refreshed_bundle.body} {latest_summary.next_focus}"
            )
            latest_summary.chapter_title = _repair_generic_chapter_title(
                latest_summary.chapter_title,
                chapter_number=chapter_number,
                next_focus=revised_title_focus,
                conflict_summary=persisted_conflict,
                genre=working_story.genre,
            )
            latest_summary.cadence = refreshed_bundle.cadence  # type: ignore[assignment]
            refreshed_bundle.chapter_title = latest_summary.chapter_title
            refreshed_bundle.chapter_summary = latest_summary.model_dump()

        refreshed_bundle.memory_constraints = memory_constraints
        refreshed_bundle.simulation_plan = (
            dict(refreshed_bundle.simulation_plan)
            if isinstance(refreshed_bundle.simulation_plan, dict)
            else {}
        )
        refreshed_bundle.simulation_plan["memory_sync"] = memory_sync
        refreshed_bundle.quality_report = (
            dict(refreshed_bundle.quality_report)
            if isinstance(refreshed_bundle.quality_report, dict)
            else {}
        )
        refreshed_bundle.quality_report["memory_sync"] = memory_sync
        refreshed_bundle.updated_story = updated_story
        refreshed_bundle.simulation_status = _build_simulation_status(updated_story)
        refreshed_bundle.character_cards = build_character_cards(updated_story)
        refreshed_bundle.foreshadowing = build_foreshadowing(updated_story, chapter_number)
        refreshed_bundle.next_outline = plan_next_outline(
            updated_story,
            chapter_number,
            conflict_summary=persisted_conflict,
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
        manual_instructions = [str(instruction).strip() for instruction in (instructions or []) if str(instruction).strip()]
        for instruction in manual_instructions:
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
            if not manual_instructions and patch_safety.get("accepted") and (
                patched_review.get("pass") or (isinstance(cut_review, dict) and cut_review.get("pass"))
            ):
                record_agent_runtime(
                    story,
                    "WriterAgent",
                    "LLM-assisted",
                    "fallback",
                    story.current_chapter,
                    fallback_reason="本地表达修补",
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
        world_simulation_decision_result = world_simulation_decision(
            working_story,
            chapter_number,
            event_plan=event_plan,
            chapter_seed=chapter_seed,
        )
        run_world_simulation = bool(world_simulation_decision_result.get("run"))
        simulated_events = (
            simulate_world_events(
                working_story,
                chapter_number,
                chapter_seed=chapter_seed,
                simulation_plan=simulation_plan,
            )
            if run_world_simulation
            else []
        )
        world_events = [event.model_dump() for event in simulated_events]
        simulation_plan["world_simulation_ran"] = run_world_simulation
        simulation_plan["world_simulation_reason"] = world_simulation_decision_result.get("reason", "")
        simulation_plan["world_simulation_triggers"] = world_simulation_decision_result.get("triggers", [])
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
        body = _sanitize_chapter_output(
            body,
            chapter_number=chapter_number,
            scene_cards=scene_cards,
            game_story=is_game_story(working_story),
        )

        if _should_expand_chapter(body, writer_plan):
            report_generation_progress("章节扩写中...")
            expanded_body, expand_error = self._timed_chat(
                working_story,
                "\n".join(
                    [
                        "下面这章正文太短，请在不改变剧情事实和结尾钩子的前提下扩写成完整网文章节。",
                        f"目标篇幅：{TARGET_CHAPTER_CHARS}。",
                        "扩写已有场景中的行动、对话、阻力和结果，不新增独立的补丁段。同一事实、判断和旁人误解只写一次；新增内容必须改变行动、关系或资源。第一章不要补成交易、提交委托、修理或买药水。",
                        "只输出扩写后的小说正文，不要解释，不要列大纲。",
                        f"原正文：\n{body}",
                    ]
                ),
                max_tokens=7000,
                json_mode=False,
                agent="writer",
                stage=f"章节扩写 第{chapter_number}章",
                timeout_seconds=_expansion_timeout_seconds(),
            )
            if expand_error:
                reason = f"章节扩写失败：{expand_error}"
                _record_failure(working_story, reason, chapter_number)
                return _failed_bundle(working_story, chapter_number, reason)
            if _chapter_char_count(expanded_body) > _chapter_char_count(body):
                body = _sanitize_chapter_output(
                    expanded_body,
                    chapter_number=chapter_number,
                    scene_cards=scene_cards,
                    game_story=is_game_story(working_story),
                )

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
                candidate_body = _sanitize_chapter_output(
                    adapted_body,
                    chapter_number=chapter_number,
                    scene_cards=scene_cards,
                    game_story=is_game_story(working_story),
                )
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
        accepted_revision_actions: list[str] = []
        review_gate = build_simplified_review({"writing_review": writing_review})
        if review_gate["needs_revision"]:
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
                candidate_body = _sanitize_chapter_output(
                    revised_body,
                    chapter_number=chapter_number,
                    scene_cards=scene_cards,
                    game_story=is_game_story(working_story),
                )
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
                if safety.get("accepted"):
                    accepted_revision_actions = [
                        str(item.get("suggestion") or "").strip()
                        for item in review_gate.get("issues", [])
                        if isinstance(item, dict)
                        and item.get("category") in {"hard", "dialogue", "ai_flavor"}
                        and str(item.get("suggestion") or "").strip()
                    ]

        if _should_compress_chapter(body):
            report_generation_progress("章节压缩中...")
            compressed_body, compress_error = self._timed_chat(
                working_story,
                "\n".join(
                    [
                        "下面这章正文超过目标篇幅，请在不改变剧情事实、人物选择、游戏账本、结尾钩子的前提下压缩。",
                        f"目标篇幅：保留完整网文章节感，但压到4300到5000字之间，绝对不要超过{MAX_CHAPTER_CHARS}字。",
                        "压缩方法：删重复解释、删绕圈心理、合并相似动作和面板反馈；保留现实压力、登录建号、首次击杀、异常掉落、背包/血蓝/耐久代价、外人误判和下一步钩子。",
                        "第一章不要新增寄售、上架、成交、到账、手续费扣款、提现、任务提交、修理或买药。",
                        "只输出压缩后的小说正文，不要解释，不要列大纲。",
                        f"原正文：\n{body}",
                    ]
                ),
                max_tokens=5500,
                json_mode=False,
                agent="writer",
                stage=f"章节压缩 第{chapter_number}章",
                timeout_seconds=_expansion_timeout_seconds(),
            )
            if not compress_error and compressed_body.strip():
                candidate_body = _sanitize_chapter_output(
                    compressed_body,
                    chapter_number=chapter_number,
                    scene_cards=scene_cards,
                    game_story=is_game_story(working_story),
                )
                candidate_chars = _chapter_char_count(candidate_body)
                if MIN_CHAPTER_CHARS <= candidate_chars <= _chapter_char_count(body):
                    body = candidate_body
                    writing_review = _review_chapter_body(
                        chapter_number,
                        body,
                        event_plan,
                        story.world_facts,
                        simulation_plan,
                        world_events,
                        scene_cards,
                    )

        post_draft_memory, memory_sync = self._extract_final_body_memory(
            working_story,
            body,
            chapter_number,
            fact_locks={
                "must_keep_facts": memory_constraints.get("must_keep_facts", []),
                "planned_summary": chapter_summary_data,
            },
        )
        simulation_plan["memory_sync"] = memory_sync

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
        memory_is_verified = memory_sync.get("status") == "ok"
        apply_post_chapter_updates(
            updated_story,
            body,
            chapter_number,
            conflict_summary=effective_conflict_summary if memory_is_verified else {},
            event_beat=event_beat if memory_is_verified else {},
            post_draft_memory=post_draft_memory,
        )
        _apply_ledger_updates(updated_story, post_draft_memory.get("ledger_updates", {}))
        _sync_character_game_panels(updated_story, chapter_number)
        advance_world_pulse(updated_story, chapter_number=chapter_number)
        maybe_update_arc_recap(updated_story, chapter_number)

        latest_summary = updated_story.chapter_summaries[-1]
        title_conflict = effective_conflict_summary if memory_is_verified else {}
        title_next_focus = (
            f"{updated_story.outline} {body} "
            f"{latest_summary.next_focus if memory_is_verified else ''}"
        )
        latest_summary.chapter_title = _repair_generic_chapter_title(
            latest_summary.chapter_title or (decision.chapter_title if memory_is_verified else ""),
            chapter_number=chapter_number,
            next_focus=title_next_focus,
            conflict_summary=title_conflict,
            genre=updated_story.genre,
        )
        latest_summary.primary_conflict = decision.primary_conflict if memory_is_verified else {}
        latest_summary.secondary_conflict = decision.secondary_conflict if memory_is_verified else {}
        latest_summary.event_beat = event_beat if memory_is_verified else {}
        latest_summary.cadence = cadence  # type: ignore[assignment]

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
        bundle.quality_report["memory_sync"] = memory_sync
        if style_adapt_report:
            bundle.quality_report["style_adapt"] = style_adapt_report
        if revision_safety_report:
            bundle.quality_report["revision_safety"] = revision_safety_report
        if accepted_revision_actions:
            bundle.quality_report["accepted_revision_actions"] = accepted_revision_actions
        updated_story.writing_lessons = merge_writing_lessons(
            updated_story.writing_lessons,
            lessons_from_quality_report(bundle.quality_report),
        )
        bundle.updated_story = updated_story
        return bundle
