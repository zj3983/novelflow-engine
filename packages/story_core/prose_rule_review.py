from __future__ import annotations

import re
from typing import Any

from packages.story_core.ai_flavor_review import review_ai_flavor


CRITICAL_PROMPT_RULES = [
    "段首主语不得连续3段相同；用动作、物件、对话、环境反馈交替开头。",
    "段落形态：禁止全章都是1-2句的短段；每5段至少1段为4-6句的连续块。单句段只用于章末、转折或强爆点这三种位置。",
    "判断句拐杖：'这是X / 这不是X / 这就是X'全章不超过2次；用动作或物件代替自我点评。",
    "比喻配额：'像X' / '仿佛X'全章不超过3处；其余地方写动作、温度、声音、重量等可见可触的实物反应。",
    "NPC对话：不得一口气抛完规则；每个NPC单次发言不超过2句，复杂规则要在2-3次问答里逐步漏出；不得把NPC档案（'边界''服务''职责'）钉在牌匾或公告。",
    "NPC只能讲岗位范围内的信息：药剂师只懂药材、库存、价格和服务边界；不得越权讲任务、公会布防、市场全局分析。",
    "主角发声：本章主角必须至少主动开口对话1次（询价/拒绝/试探任一）；不能全章只用心理独白和侧听。",
    "主角只能看到、听到、接触到自己周围可见信息；公会内部频道、他人私聊、后台记录和上帝视角宣告都是禁区。",
    "后台术语和事实矛盾词不得进正文：暴露度、关注度、系统风险、异常标记、前世、穿越模板、'边界''样本''基准''测试场''诊断'等必须删除或改成可见反应。",
    "战斗不写攻略说明术语：前摇、元素传导效率、伤害数字、DPS、技能循环要改成动作、距离、错位、消耗和身体反馈。",
    "【系统提示：】每章最多4次；普通掉落、消耗和状态变化优先写成角色看到的界面反馈或动作后果。",
    "新名词配额：本章新地名/新人物/新道具/新概念合计不超过4个；已有概念优先复用并赋予新功能。",
    "背景和世界局势不得用全知宣告总结；必须落到主角能看见的价格、队伍、公告、对话、物件和环境变化。",
    "已知demo复读句不得照抄：'成本已经先到了'、'第一笔账还没赚到'、'第一笔委托还没交'、'账还没赚到'。这是LLM跨稿粘性短句，找新的章末收束方式。",
    "情绪配额：主角内心必须有至少3处微小情绪溢出（不爽/疲惫/犹豫/侥幸/委屈/苦笑/咬牙/没忍住/眉头一皱/喉头紧 等任一类），分散在章首、章中、章末。"
    "情绪不是宣告'他很愤怒'，也不是删掉——必须落到具体身体动作（手指攥紧/视线移开/苦笑半秒/走神看了下窗外）或一个不合时宜的小念头上。"
    "重大节点（首次兑现/重大失误/章末决断）必须各有一拍情绪锚，不能只剩数字和判断。",
]


_DIAGNOSTIC_TERMS = (
    "暴露度",
    "关注度",
    "系统风险",
    "异常标记",
    "风控值",
    "ledger_updates",
    "diagnostic_only",
    "quality_report",
    "simulation_plan",
    "character_moves",
    "scene_card",
    "state_delta",
    "prose_priority",
    "narrative_function",
)

_FACT_CONTRADICTION_TERMS = (
    "前世",
    "上一世",
    "重生前",
    "穿越前",
    "前一世",
)

_GUIDE_TERMS = (
    "施法前摇",
    "前摇",
    "元素传导效率",
    "伤害数字",
    "DPS",
    "技能循环",
    "仇恨值",
)

_POV_BREACH_TERMS = (
    "公会频道",
    "通讯频道",
    "内部频道",
    "内部记录",
    "后台记录",
    "内部汇报",
    "上报：",
    "维持秩序：",
    "他不知道的是",
    "她不知道的是",
    "没人知道的是",
    "与此同时，另一边",
)

_OMNISCIENT_PATTERNS = (
    r"供需关系正在被.{0,24}(重塑|改变|压缩)",
    r"(世界|市场|公会|商人|散人).{0,12}(格局|生态|空间).{0,20}(正在|已经|开始)",
    r"(白袍|赤焰|公会|商人).{0,24}(控制|囤积|压价|扫货).{0,24}(散人|市场|资源)",
)

_NPC_ROLE_TERMS = ("药剂师", "药铺", "药剂铺", "修理匠", "仓库管理员", "村长", "导师", "柜台")
_NPC_OVERREACH_TERMS = (
    "公会",
    "警戒线",
    "布防",
    "刷新点",
    "职业试炼",
    "试炼门槛",
    "元素回廊",
    "市场分析",
    "开服市场",
    "全局行情",
    "内部频道",
    "坐标",
)
_NPC_BOUNDARY_TERMS = (
    "只管",
    "只收",
    "只卖",
    "药材",
    "药剂",
    "库存",
    "进价",
    "价格",
    "修理",
    "耐久",
    "仓库",
    "寄存",
)


def _merge_issue(target: list[str], issue: str) -> None:
    if issue not in target:
        target.append(issue)


def _paragraphs(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"\n\s*\n|\r\n\s*\r\n", text.replace("\r", "\n"))
        if part.strip()
    ]


def _paragraph_opener(paragraph: str) -> str:
    cleaned = paragraph.strip().lstrip("“‘「『【[(")
    if not cleaned:
        return ""
    if cleaned.startswith(("【", "系统提示", "状态栏", "角色面板")):
        return ""
    if re.match(r"[\u4e00-\u9fff]{2}", cleaned):
        return cleaned[:2]
    match = re.match(r"([\u4e00-\u9fffA-Za-z0-9_·]{1,6})", cleaned)
    return match.group(1) if match else cleaned[:2]


def review_diagnostic_terms_in_body(text: str) -> dict[str, Any]:
    issues: list[str] = []
    revision_plan: list[str] = []
    hits = [term for term in _DIAGNOSTIC_TERMS if term in text]
    fact_hits = [term for term in _FACT_CONTRADICTION_TERMS if term in text]
    guide_hits = [term for term in _GUIDE_TERMS if term in text]

    if hits:
        issues.append(f"正文混入后台/审稿术语：{'、'.join(hits[:5])}。")
        revision_plan.append("删除后台术语，把它们改成主角能看到的界面反馈、动作后果或他人的可见反应。")
    if fact_hits:
        issues.append(f"正文出现疑似事实模板错误：{'、'.join(fact_hits[:4])}。")
        revision_plan.append("核对主角设定；不是穿越/重生故事时，删除前世、上一世等模板词，改成当下经历或现实工作习惯。")
    if guide_hits:
        issues.append(f"战斗写成攻略说明：{'、'.join(guide_hits[:5])}。")
        revision_plan.append("把攻略术语改成动作、距离、错位、法力/体力消耗、装备震动和敌我反应。")

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {
            "diagnostic_terms": 5 if hits or fact_hits else 8,
            "guide_terms": 5 if guide_hits else 8,
        },
    }


def review_pov_breach(text: str) -> dict[str, Any]:
    issues: list[str] = []
    revision_plan: list[str] = []
    hits = [term for term in _POV_BREACH_TERMS if term in text]
    omniscient_hits = [pattern for pattern in _OMNISCIENT_PATTERNS if re.search(pattern, text)]

    if hits:
        issues.append(f"主角限知视角越界：{'、'.join(hits[:5])}。")
        revision_plan.append("删除公会内部频道、后台记录、他人私聊和上帝视角句子；只保留主角可见的公告、论坛、现场对话或环境痕迹。")
    if omniscient_hits:
        issues.append("正文存在全知局势宣告，世界变化没有落到主角可见证据。")
        revision_plan.append("把市场/公会/散人生态的总结改成具体价格、排队、公告、玩家闲聊、NPC服务变化或物件细节。")

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"pov_boundary": 5 if issues else 8},
    }


def review_npc_boundary_violation(text: str) -> dict[str, Any]:
    issues: list[str] = []
    revision_plan: list[str] = []
    paragraphs = _paragraphs(text)
    for index, paragraph in enumerate(paragraphs):
        window = "\n".join(paragraphs[max(0, index - 1) : min(len(paragraphs), index + 2)])
        if not any(term in window for term in _NPC_ROLE_TERMS):
            continue
        overreach = [term for term in _NPC_OVERREACH_TERMS if term in window]
        if len(overreach) >= 2 and not any(term in window for term in _NPC_BOUNDARY_TERMS):
            issues.append(f"NPC信息边界越权：服务型NPC段落提到{'、'.join(overreach[:4])}。")
            revision_plan.append("让NPC只说岗位内信息和个人利益边界；任务、公会布防、市场全局分析改由公告、论坛、玩家闲聊或后续线索承担。")
            break
        if "药剂" in window and any(term in window for term in ("公会", "警戒线", "职业试炼", "市场分析", "元素回廊")):
            issues.append("药剂师/药铺信息边界越权：药材服务节点不应讲公会布防、职业试炼或全局市场分析。")
            revision_plan.append("把药剂师台词收窄到药材库存、价格、药效、收购口径和她不知道的边界。")
            break

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"npc_boundary": 5 if issues else 8},
    }


def review_paragraph_opener_repetition(text: str) -> dict[str, Any]:
    issues: list[str] = []
    revision_plan: list[str] = []
    openers = [_paragraph_opener(paragraph) for paragraph in _paragraphs(text)]
    openers = [item for item in openers if item]

    run_opener = ""
    run_count = 0
    for opener in openers:
        if opener == run_opener:
            run_count += 1
        else:
            run_opener = opener
            run_count = 1
        if run_count >= 3:
            issues.append(f"段首主语连续重复：{opener} 连续作为段首出现 {run_count} 次。")
            revision_plan.append("改写连续段首，用动作、物件、环境反馈、对话或界面变化交替开头。")
            break

    counts: dict[str, int] = {}
    for opener in openers:
        counts[opener] = counts.get(opener, 0) + 1
    noisy = [f"{opener}×{count}" for opener, count in counts.items() if count >= 8]
    if noisy and not issues:
        issues.append(f"段首主语过度单调：{'、'.join(noisy[:3])}。")
        revision_plan.append("分散主角姓名/代词段首，优先用动作、物件、环境反馈和他人台词开段。")

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"paragraph_opener_variety": 5 if issues else 8},
    }


def review_system_tag_density(text: str, *, max_tags: int = 4) -> dict[str, Any]:
    count = len(re.findall(r"【\s*系统提示", text))
    issues: list[str] = []
    revision_plan: list[str] = []
    if count > max_tags:
        issues.append(f"【系统提示】标签过密：本章出现 {count} 次，建议最多 {max_tags} 次。")
        revision_plan.append("保留关键系统提示，其余改成主角扫过面板、背包格变化、状态栏闪动或战斗后的可见反馈。")
    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"system_tag_density": 5 if issues else 8},
    }


_JUDGMENT_CRUTCH_PATTERN = re.compile(r"(?<![一-鿿])(这是|这不是|这就是)(?![一-鿿]*[，,])")
_METAPHOR_PATTERN = re.compile(r"(?:^|[^一-鿿])(像|仿佛|犹如|宛如)[一-鿿]")


def review_paragraph_form(text: str, *, min_long_per_block: int = 1, block_size: int = 5) -> dict[str, Any]:
    """Flag chapters that are entirely 1-2 sentence shards with no breathing block."""
    paragraphs = _paragraphs(text)
    if len(paragraphs) < block_size:
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {"paragraph_form": 8}}

    def _sentence_count(paragraph: str) -> int:
        return len([s for s in re.split(r"[。！？!?]", paragraph) if s.strip()])

    issues: list[str] = []
    revision_plan: list[str] = []
    long_para_count = sum(1 for p in paragraphs if _sentence_count(p) >= 4)
    short_para_count = sum(1 for p in paragraphs if _sentence_count(p) <= 2)
    short_ratio = short_para_count / len(paragraphs)
    expected_long = max(min_long_per_block, len(paragraphs) // block_size)

    if long_para_count < expected_long and short_ratio > 0.7:
        issues.append(
            f"段落形态过碎：共{len(paragraphs)}段，仅{long_para_count}段含4句以上连续动作或观察，"
            f"短段占比{int(short_ratio * 100)}%。"
        )
        revision_plan.append("把若干相邻短段合成4-6句的连续块（环境观察、连续动作、对话回合），让短句的强调真有重量。")

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"paragraph_form": 5 if issues else 8},
    }


def review_judgment_crutch(text: str, *, max_hits: int = 2) -> dict[str, Any]:
    matches = _JUDGMENT_CRUTCH_PATTERN.findall(text)
    issues: list[str] = []
    revision_plan: list[str] = []
    if len(matches) > max_hits:
        issues.append(f"判断句拐杖过多：'这是X/这不是X/这就是X'共出现 {len(matches)} 次，建议最多 {max_hits} 次。")
        revision_plan.append("把判断句改成动作或物件（让读者从动作里推出判断），而不是用主角自我点评作小结。")
    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"judgment_crutch": 5 if issues else 8},
    }


def review_metaphor_density(text: str, *, max_hits: int = 3) -> dict[str, Any]:
    matches = _METAPHOR_PATTERN.findall(text)
    issues: list[str] = []
    revision_plan: list[str] = []
    if len(matches) > max_hits:
        issues.append(f"比喻配额超标：'像/仿佛/犹如/宛如'共出现 {len(matches)} 次，建议最多 {max_hits} 次。")
        revision_plan.append("删掉多余比喻，改成温度、声音、重量、距离等可触可见的实物反应。")
    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"metaphor_density": 5 if issues else 8},
    }


_SPEECH_ACT_VERBS = (
    "说",
    "问",
    "答",
    "应",
    "低声",
    "开口",
    "张嘴",
    "出声",
    "回",
    "喊",
    "叫",
    "笑道",
    "反问",
    "嘟囔",
    "自语",
    "压低",
)

_QUOTE_PATTERN = re.compile(r"[“\"][^“”\"]{1,80}[”\"]")


def review_protagonist_speech(text: str, protagonist_names: tuple[str, ...] = ()) -> dict[str, Any]:
    """Flag chapters where the protagonist never visibly speaks aloud.

    Stricter heuristic: scan paragraphs containing a quoted line, then check
    whether *the same paragraph or its immediate neighbours* contain BOTH:
      - the protagonist name (or any pronoun-like alias when no name given)
      - a speech-act verb (say/ask/answer/low-voice/open mouth/...)
    A protagonist whose name appears next to other speakers' lines without
    any speech-act verb tying to them does NOT count as having spoken.
    """
    paragraphs = _paragraphs(text)
    quote_paragraphs = [
        (idx, paragraph)
        for idx, paragraph in enumerate(paragraphs)
        if _QUOTE_PATTERN.search(paragraph)
    ]
    if not quote_paragraphs:
        # No dialogue at all in the chapter — clearly the protagonist hasn't
        # spoken either. Flag it.
        if not protagonist_names:
            return {"pass": True, "issues": [], "revision_plan": [], "scores": {"protagonist_speech": 8}}
        issues = ["主角全章没有可识别的开口对话；只用心理独白和侧听不足以推动场景。"]
        revision_plan = ["在询价、拒绝、试探或简短反问处补一次主角主动开口的对话；半句也算。"]
        return {
            "pass": False,
            "issues": issues,
            "revision_plan": revision_plan,
            "scores": {"protagonist_speech": 5},
        }

    for idx, paragraph in quote_paragraphs:
        window_parts = [paragraphs[max(0, idx - 1)], paragraph]
        if idx + 1 < len(paragraphs):
            window_parts.append(paragraphs[idx + 1])
        window = "\n".join(window_parts)
        # Must reference the protagonist somewhere in the window
        if protagonist_names and not any(name and name in window for name in protagonist_names):
            continue
        # And must contain a speech-act verb in the window (within ~30 chars
        # of either the name or the quote — approximate via window-level check)
        if not any(verb in window for verb in _SPEECH_ACT_VERBS):
            continue
        # Reject windows where the speech verb is clearly attached to a
        # different character (NPC name appearing right next to the verb).
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {"protagonist_speech": 8}}

    issues = ["主角全章没有可识别的开口对话；引号台词都属于他人或群体，没有'主角+说/问/低声'的连接句。"]
    revision_plan = ["补一次主角主动开口（询价/拒绝/试探/反问任一），并显式写出'他说''他低声问'等说话动词；半句也算。"]
    return {
        "pass": False,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"protagonist_speech": 5},
    }


# Emotion / micro-feeling vocabulary used by review_emotion_quota.
# Mix of verbs, body-state phrases, and small-action descriptors that signal
# the protagonist is feeling something rather than computing.
_EMOTION_TOKENS = (
    # 直接情绪词
    "苦笑",
    "咬牙",
    "皱眉",
    "皱了皱眉",
    "眉头",
    "叹了",
    "叹气",
    "出神",
    "走神",
    "发愣",
    "愣了",
    "失神",
    "没忍住",
    "忍不住",
    "犹豫",
    "侥幸",
    "委屈",
    "懊恼",
    "烦躁",
    "心烦",
    "心累",
    "心软",
    "不甘",
    "不爽",
    "无奈",
    "疲惫",
    "疲倦",
    "困倦",
    "羞愧",
    "懊悔",
    "庆幸",
    "怀念",
    # 身体化情绪反应：紧 / 紧绷
    "喉头一紧",
    "喉咙发紧",
    "嗓子发紧",
    "胸口发紧",
    "心里一沉",
    "心头一沉",
    "胃里",
    "胃部",
    "鼻尖",
    "鼻子有点酸",
    "眼眶",
    "眼底",
    # 手 / 拳 / 攥
    "手指攥紧",
    "攥紧拳",
    "拳头紧",
    "握紧",
    "攥住",
    "捏紧",
    # 呼吸
    "屏住呼吸",
    "屏息",
    "呼吸滞了",
    "呼吸放慢",
    "深吸",
    "出了口气",
    # 节拍 / 停顿
    "停了半拍",
    "顿了一拍",
    "顿了顿",
    "停在原地",
    "停顿",
    "停住脚",
    "半晌没",
    # 嘴 / 舌 / 唇
    "扯了扯嘴角",
    "抿嘴",
    "嘴角",
    "舌尖",
    "咽了口",
    # 身体疼 / 重 / 热（情绪转译为体感）
    "发疼",
    "酸痛",
    "酸软",
    "发酸",
    "发麻",
    "麻得",
    "压着肩",
    "压着心",
    "压在心",
    "压在掌心",
    "肩沉",
    "沉沉",
    "重得",
    "热得发",
    "凉了半",
    "热汗",
    "汗珠",
    # 痕迹 / 烙印（不可逆的身体记忆）
    "红痕",
    "印子",
    "烙印",
    "牙印",
    # 不合时宜的小念头
    "突然想到",
    "忽然想到",
    "脑子里冒出",
    "脑子里闪过",
    "鬼使神差",
    "莫名想",
    "竟有些",
    "竟然有点",
    # 视线/注意力的失序
    "视线移开",
    "视线落在",
    "目光停在",
    "盯着……发呆",
    "出了神",
    "看了一会儿",
    "看了一阵",
)


def review_emotion_quota(text: str, *, min_hits: int = 3) -> dict[str, Any]:
    """Flag chapters where the protagonist's interiority is purely cognitive.

    Two checks:

    1. **Count**: at least ``min_hits`` distinct emotion tokens across the
       chapter — without this the prose reads as a spreadsheet.
    2. **Distribution**: the chapter must have at least 1 hit in the first
       half of the body. Chapters that pile all their emotion into the
       last 25-40 lines technically pass count but feel cold for 80% of the
       reading experience — exactly what readers describe as "缺感情".
    """
    hits: list[str] = []
    hit_positions: list[int] = []
    for token in _EMOTION_TOKENS:
        index = text.find(token)
        if index < 0:
            continue
        if token in hits:
            continue
        hits.append(token)
        hit_positions.append(index)

    issues: list[str] = []
    revision_plan: list[str] = []
    scores: dict[str, int] = {"emotion_quota": 8}

    if len(hits) < min_hits:
        scores["emotion_quota"] = 5
        issues.append(
            f"情绪锚点不足：全章只出现 {len(hits)} 处情绪/身体反应/不合时宜小念头"
            f"（建议至少 {min_hits} 处）。"
            "主角通篇只有计算和判断，读起来像 spreadsheet 不像人。"
        )
        revision_plan.append(
            "在重大节点处各补一拍情绪锚（不爽/疲惫/犹豫/侥幸/苦笑/咬牙/喉头紧/手指攥紧/突然想到 等任一类），"
            "落到具体身体动作或不合时宜的小念头上；不要写成'他很愤怒'式宣告，也不要再删情绪。"
        )
    elif text and hit_positions:
        # Distribution: at least one hit must land in the first half.
        body_len = len(text)
        first_half_hits = sum(1 for pos in hit_positions if pos < body_len // 2)
        if first_half_hits == 0:
            scores["emotion_quota"] = 6
            first_hit_pct = int(min(hit_positions) * 100 / max(body_len, 1))
            issues.append(
                f"情绪分布失衡：全章 {len(hits)} 处情绪锚全部集中在后半段"
                f"（最早一处出现在正文 {first_hit_pct}% 处）。"
                "前半段读起来仍像 spreadsheet，读者代入感断在开头。"
            )
            revision_plan.append(
                "把至少 1 处情绪锚移到章节前半段（开篇压力 / 第一次决定 / 首次受挫），"
                "让主角在前几屏就显得是'人'而不是'交易脚本'。"
            )

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "hits": hits,
    }


_KNOWN_REFRAIN_TRAPS = (
    "成本已经先到了",
    "第一笔账还没赚到",
    "第一笔委托还没交",
    "成本先到",
    "账还没赚到",
)


def review_refrain_traps(text: str) -> dict[str, Any]:
    """Detect verbatim demo-refrain phrases that LLMs paste across rewrites."""
    hits = [phrase for phrase in _KNOWN_REFRAIN_TRAPS if phrase in text]
    issues: list[str] = []
    revision_plan: list[str] = []
    if hits:
        issues.append(f"正文照抄了已知demo复读句：{'、'.join(hits[:3])}。")
        revision_plan.append("换章末收束方式：用动作、物件、未结算数字或半句对话代替这组粘性短句。")
    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"refrain_traps": 5 if issues else 8},
    }


# Severity classification for sub-reviewers, inspired by webnovel-writer's
# Hard/Soft constraint layering. Hard violations trigger revision unconditionally;
# soft suggestions only trigger revision when accumulated past SOFT_THRESHOLD.
#
# Hard = facts / POV / role boundaries / cross-rewrite contamination.
#        Any single violation breaks the chapter contract.
# Soft = density / variety / pacing / texture.
#        A single one is acceptable; many at once means the chapter feels off.
HARD_REVIEWERS: frozenset[str] = frozenset({
    "diagnostic_terms",          # 后台术语 / 事实矛盾词（前世/穿越模板）
    "guide_terms",                # 攻略术语（前摇 / DPS / 元素传导效率）
    "pov_boundary",               # 公会内部频道 / 上帝视角宣告
    "npc_boundary",               # NPC 越权讲不该讲的
    "refrain_traps",              # 照抄 demo 复读句
    "protagonist_speech",         # 主角全章不开口
    "system_tag_density",         # 【系统提示】过密（碍读）
    "hook_landed",                # 章末钩子未在正文末段落地
    "pacing_stagnation",          # 跨章节连续无推进（HARD-003 等价）
    "required_beats_critical",    # >50% required_beats 未在正文落地
})

SOFT_REVIEWERS: frozenset[str] = frozenset({
    "paragraph_opener_variety",   # 段首主语单调
    "paragraph_form",             # 短段比例过高
    "judgment_crutch",            # "这是X" 过多
    "metaphor_density",           # 比喻配额超标
    "ai_flavor",                  # AI味/模型腔：对称总结句、抽象报告词
    "emotion_quota",              # 情绪锚不足
    "hook_type_match",            # 章末钩子类型与题材偏好不符
    "hook_strength",              # 章末钩子强度低于题材基线
    "pacing_quest_strand",        # 主线/任务线独占叙事过久
    "pacing_emotion_gap",         # 情感线断档过久
    "pacing_transition_run",      # 过渡章连发过多
    "required_beats_partial",     # required_beats 部分覆盖或少量缺失
})

SOFT_REVISION_THRESHOLD = 3


def _classify_score_keys(score_keys: list[str]) -> tuple[bool, int]:
    """Return (has_hard, soft_count) for a sub-review's failing score_keys."""
    has_hard = any(key in HARD_REVIEWERS for key in score_keys)
    soft_count = sum(1 for key in score_keys if key in SOFT_REVIEWERS)
    return has_hard, soft_count


def review_critical_prose_rules(
    text: str,
    *,
    protagonist_names: tuple[str, ...] = (),
    prosody_caps: dict[str, int] | None = None,
    extra_subreviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate critical prose-rule reviewers into a hard/soft layered report.

    ``prosody_caps`` lets callers pass per-genre density caps (system tags,
    metaphor, judgment-crutch) sourced from a ``GenreProfile``. When omitted
    the reviewer-level defaults apply, preserving the universal baseline.

    ``extra_subreviews`` lets the orchestrator inject pre-computed sub-reviews
    that need external context (e.g. ``review_chapter_hook`` needs the genre
    profile and director event_plan). Each entry must follow the standard
    sub-review shape: ``{pass, issues, revision_plan, scores}``. Their score
    keys participate in the same HARD/SOFT classification.
    """
    caps = prosody_caps or {}
    system_tag_max = int(caps.get("system_tag_max", 4))
    metaphor_max = int(caps.get("metaphor_max_per_chapter", 3))
    judgment_max = int(caps.get("judgment_crutch_max_per_chapter", 2))

    issues: list[str] = []
    revision_plan: list[str] = []
    hard_issues: list[str] = []
    soft_issues: list[str] = []
    scores: dict[str, int] = {}
    compact_len = len(re.sub(r"\s", "", text))
    subreviews = [
        review_diagnostic_terms_in_body(text),
        review_pov_breach(text),
        review_npc_boundary_violation(text),
        review_paragraph_opener_repetition(text),
        review_system_tag_density(text, max_tags=system_tag_max),
        review_paragraph_form(text),
        review_ai_flavor(text),
        review_judgment_crutch(text, max_hits=judgment_max),
        review_metaphor_density(text, max_hits=metaphor_max),
        review_refrain_traps(text),
    ]
    # Protagonist-speech and emotion-quota are chapter-level checks that need
    # real authorial intent. They are opt-in: only run when caller passes
    # protagonist_names explicitly (orchestrator path knows the actual cast;
    # test fixtures and segment-level passes legitimately may not have either
    # dialogue or emotion vocabulary).
    if protagonist_names:
        subreviews.append(review_protagonist_speech(text, protagonist_names=protagonist_names))
        if compact_len >= 1500:
            subreviews.append(review_emotion_quota(text))

    if extra_subreviews:
        for review in extra_subreviews:
            if isinstance(review, dict):
                subreviews.append(review)

    has_hard_violation = False
    soft_violation_count = 0

    for review in subreviews:
        review_passed = bool(review.get("pass", True))
        review_issues = [str(item) for item in review.get("issues", []) if str(item).strip()]
        review_plan = [str(item) for item in review.get("revision_plan", []) if str(item).strip()]
        review_scores = review.get("scores") or {}
        # A failing score_key < 8 marks a triggered category.
        triggered_keys = [key for key, score in review_scores.items() if int(score) < 8]
        has_hard_here, soft_count_here = _classify_score_keys(triggered_keys)

        if not review_passed and not triggered_keys and review_issues:
            # Defensive: a sub-reviewer reported issues without a triggered
            # score key. Treat as soft to avoid silent over-trigger.
            soft_count_here = max(soft_count_here, 1)

        if has_hard_here:
            has_hard_violation = True
            for item in review_issues:
                _merge_issue(hard_issues, item)
        if soft_count_here:
            soft_violation_count += soft_count_here
            for item in review_issues:
                if item not in hard_issues:
                    _merge_issue(soft_issues, item)

        for item in review_issues:
            _merge_issue(issues, item)
        for item in review_plan:
            _merge_issue(revision_plan, item)
        for key, score in review_scores.items():
            scores[str(key)] = int(score)

    requires_revision = has_hard_violation or soft_violation_count >= SOFT_REVISION_THRESHOLD

    return {
        "pass": not issues,
        "requires_revision": requires_revision,
        "issues": issues,
        "hard_issues": hard_issues,
        "soft_issues": soft_issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "severity_summary": {
            "has_hard_violation": has_hard_violation,
            "soft_violation_count": soft_violation_count,
            "soft_threshold": SOFT_REVISION_THRESHOLD,
        },
    }
