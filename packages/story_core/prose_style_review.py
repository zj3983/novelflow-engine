from __future__ import annotations

import re
from typing import Any

from packages.story_core.genre_plugins import is_game_genre_context
from packages.story_core.web_game_economy import detect_economy_boundary_violations


AI_CLICHE_TERMS = (
    "心中一紧",
    "五味杂陈",
    "脸色一变",
    "眸光一凝",
    "身形一闪",
    "霎时间",
    "此刻",
    "见状",
    "不由得",
    "殊不知",
    "与此同时",
    "爽感",
    "很爽",
    "太爽",
    "轻松",
    "牛逼",
)

META_LANGUAGE_TERMS = (
    "爽点",
    "钩子",
    "读者",
    "网文规则",
    "生成",
    "审稿",
    "质量报告",
    "剧情需要",
    "下一阶段剧情",
)

STIFF_DIALOGUE_TERMS = (
    "吾等",
    "尔等",
    "休要",
    "岂能",
    "诸位且听我一言",
)

MODERN_CHINESE_DIALOGUE_PROBLEMS = (
    "先试，不深入",
    "先试，不进",
    "先看，不打",
    "先报我",
    "暂缓提交",
    "确认收益",
    "验证路线",
    "柜台不认",
    "系统不允许",
    "条件未满足",
    "背包里没有",
)

DIALOGUE_TELEGRAPHY_HINTS = (
    "没油水",
    "没记功",
    "不许",
    "先报",
    "先说",
    "先交",
    "先放",
    "先走",
)

DIALOGUE_COMMAND_SNIPPETS = (
    "先试，不深入",
    "先试，不进",
    "先报我",
    "先交",
    "先放",
    "先走",
    "先说",
    "先来",
    "你先",
    "我先",
    "不许",
    "别乱",
)

_COMMAND_LINE_RE = re.compile(r"^(你|我|你们|我们)?先(?:报|交|说|放|走|来|拿|看|去|做|告|开|试|探|测|等|停|等着)[^，,。！？!?]*$")
_DIALOGUE_SNIPPET_RE = (
    r"[“\"]([^”\"]{1,300})[”\"]",
    r"‘([^’]{1,300})’",
    r"『([^』]{1,300})』",
    r"「([^」]{1,300})」",
)
_DIALOGUE_COLON_LINE_RE = re.compile(r"[^\n。！？!?]{0,6}[：:]+\s*([^\n。！？!?，,]{2,90})")

_SHORT_CLAUSE_ACTION_VERBS = re.compile(
    r"(说|问|答|回|告诉|回应|交|拿|给|把|去|来|看|提|放|开|关|扔|丢|打|抛|跑|走|进|出|坐|站|停|盯|收|买|卖|修|做|想|听|见|见到|拿到|先)"
)

OLD_SLOGAN_PAYOFF_TERMS = (
    "三十年河东",
    "三十年河西",
    "莫欺少年穷",
    "今日之辱",
    "来日必还",
    "终有一日",
    "我命由我不由天",
)

MECHANICAL_EXPLANATION_TERMS = (
    "这说明",
    "这意味着",
    "也就是说",
    "换句话说",
    "这代表",
    "他立即明白",
    "他立刻明白",
    "夜烬立即明白",
    "夜烬立刻明白",
    "意味着",
    "理由很直接",
    "很清楚",
    "很干净",
    "不会引起",
    "不能全卖",
    "也不能不卖",
    "风险也是",
    "规则写得",
    "数据",
    "模型",
    "异常",
    "等于",
)

PANEL_EXPLANATION_TERMS = (
    "这说明",
    "这意味着",
    "也就是说",
    "换句话说",
    "这代表",
    "规则是",
    "规则在",
    "异常只",
    "机制是",
)

TRANSACTION_PROCESS_EXPLANATION_TERMS = (
    "提交鉴定后",
    "系统给出",
    "求购匹配",
    "求购方看不到",
    "卖家ID",
    "掉落分片",
    "平台验货",
    "封存交割",
    "无法看到卖家",
    "不会显示卖家",
)

STIFF_WEBNOVEL_OUTPUT_TERMS = (
    "验边界",
    "边界验证",
    "确认边界",
    "信息边界",
    "服务边界",
    "岗位边界",
    "服务节点",
    "验证规则",
    "底层逻辑",
    "运行逻辑",
    "可见性",
    "阈值",
    "基准",
    "诊断",
    "负载分片",
    "承载节点",
    "区域分片",
    "巡查资格",
    "登记巡查资格",
    "配方验证",
    "平台封存",
    "封存交割",
    "现实结算",
    "字段权限",
)

BAD_STAFF_TERMS = (
    "木杖",
    "修杖",
    "握杖",
    "杖身",
    "杖尖",
    "杖尾",
    "杖头",
)

SAFE_META_REPLACEMENTS = (
    ("修杖", "修法杖"),
    ("握杖", "握着法杖"),
    ("木杖", "新手法杖"),
    ("杖身", "法杖表面"),
    ("杖尖", "法杖前端"),
    ("杖尾", "法杖末端"),
    ("杖头", "法杖前端"),
    ("这一段爽点已经兑现，", ""),
    ("爽点已经兑现，", ""),
    ("爽点", "收获"),
    ("爽感", "踏实感"),
    ("很爽", "心里有了底"),
    ("太爽", "来得太快"),
    ("牛逼", "离谱"),
    ("轻松解决", "勉强解决"),
    ("生成的节奏", "事情推进"),
    ("节奏", "推进"),
    ("生成", "写下"),
    ("审稿", "复核"),
    ("质量报告", "记录"),
    ("下一阶段剧情", "下一步"),
    ("读者会明白", "旁人能看出来"),
    ("读者", "旁人"),
    ("网文规则", "规矩"),
    ("确认边界", "试清楚能不能走"),
    ("验边界", "试一把"),
    ("边界验证", "试一把"),
    ("服务节点", "柜台"),
    ("信息边界", "知道多少"),
    ("服务边界", "能办什么、不能办什么"),
    ("阈值", "那条线"),
)


def anti_ai_style_rules() -> list[str]:
    """Prompt-ready anti-AI prose rules shared by generation and revision."""

    return [
        "避免书面生硬、流水账、模板化心理和重复句式；人物说话完整自然，行为符合人设，前后逻辑严谨。",
        "不要把句子全部切短：写清人物正在做什么、为什么这么做，以及动作带来的结果；情绪放在停顿、手势、语气和选择里。",
        "动作示例：他走到门口，先听了听里面的动静，才抬手敲门；不要写成‘他谨慎判断后决定进入’。",
        "一章分3到4个叙事段落推进：开局铺垫、冲突发生、高潮互动、结尾留钩子；不要一次性把事件压成流水账。",
        "生成后自检第一步：替换心中一紧、五味杂陈、脸色一变、眸光一凝、身形一闪、霎时间、此刻、见状、不由得、殊不知、与此同时等AI高频套话。",
        "用动作 + 微表情 + 细微生理反应替代抽象心理；例如用指尖收紧、肩线绷住、笑意变淡，而不是直接写心中一紧。",
        "打散句式：叙述可以拆短，但对话不要拆成口令；调换主语顺序，删除无意义修饰和注水形容词。",
        "少解释只针对旁白：对白不能省略连接词和因果，不要写成‘窗坏、瓦落、门锁坏，先报我’这类名词清单加命令的电报句。",
        "增加专属生活化细节：人物小习惯、环境气味/声音/光线、道具使用痕迹、口头禅、过往小阴影或偏执小习惯。",
        "修正逻辑并防吃设定：核对实力、身份、伏笔、时间、地点、道具、装备、货币和任务状态；删除强行降智、强行巧合、强行煽情。",
        "改写对话：配角说话要符合身份，接地气，别绕太远；加说话动作，删除像念台词的空洞废话。",
        "对白结构要求：对方先说一句（催/抱怨/提醒），主角一句完整回应（说清原因和选择），对方再有一句真实反应；别让一段台词只剩命令和短语。",
        "不要把后台词写进正文和标题。边界/验证/服务节点/信息边界/逻辑/模型/阈值/可见性，要换成角色能说出口、能看见、能处理的具体事情。",
        "交易、鉴定和任务办理也要写现场：写角色点了什么、界面弹出什么、物品或钱怎样变化；不要旁白解释平台怎样验货、谁能看见哪些字段或后台怎样流转。",
        "不要连续堆形容词；网游场景中的信息优先落到动作、对话、面板提示、背包格、耐久和直接后果。",
    ]


def sanitize_prose_style(body: str) -> str:
    """Remove safe-to-rewrite meta wording that should never remain in prose."""

    cleaned = body
    for old, new in SAFE_META_REPLACEMENTS:
        cleaned = cleaned.replace(old, new)
    return cleaned


def _append_issue(
    *,
    issues: list[str],
    revision_plan: list[str],
    scores: dict[str, int],
    score_key: str,
    issue: str,
    plan: str,
    score: int = 5,
) -> None:
    if issue in issues:
        return
    scores[score_key] = min(scores.get(score_key, 8), score)
    issues.append(issue)
    revision_plan.append(plan)


def _repeated_terms(body: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in body]


def _modern_chinese_dialogue_problems(body: str) -> list[str]:
    dialogue_source = re.sub(r"【[^】]*】", "", body)
    problems = _repeated_terms(dialogue_source, MODERN_CHINESE_DIALOGUE_PROBLEMS)
    quoted_lines: list[str] = []
    for pattern in _DIALOGUE_SNIPPET_RE:
        quoted_lines.extend(re.findall(pattern, dialogue_source, flags=re.DOTALL))
    quoted_lines.extend(match.group(1).strip() for match in _DIALOGUE_COLON_LINE_RE.finditer(dialogue_source))
    dialogue_lines = [line.strip() for line in quoted_lines if line.strip()]

    def _looks_like_command_snippet(sentence: str) -> bool:
        compact = re.sub(r"\s+", "", sentence)
        if not compact or len(compact) > 22:
            return False
        if compact.startswith("别抢") and "我先" in compact:
            return False
        for snippet in DIALOGUE_COMMAND_SNIPPETS:
            if snippet in compact:
                return True
        if _COMMAND_LINE_RE.search(compact):
            return True
        if re.fullmatch(r"先(?:报|交|说|放|走|来|拿|看|去|做|告|开|试|探|测|等|等着)[^，,。！？!?]*", compact):
            return True
        if re.fullmatch(r"你先[^，,。？！!？]*", compact) and len(compact) <= 12:
            return True
        return False

    def _is_telegraphic_dialogue(sentence: str) -> bool:
        compact = re.sub(r"\s+", "", sentence)
        if not compact:
            return False
        for hint in DIALOGUE_TELEGRAPHY_HINTS:
            if hint in compact:
                return True
        if re.fullmatch(
            r"[\u4e00-\u9fff]{2,5}[，,][\u4e00-\u9fff]{2,5}(?:[，,][\u4e00-\u9fff]{2,5})+",
            compact,
        ):
            return True
        fragments = [part.strip() for part in re.split(r"[，,、。；;！!？?]", compact) if part.strip()]
        if len(fragments) < 3:
            return False
        if compact.count("、") >= 2:
            return True
        short_clause_count = sum(1 for item in fragments if 1 <= len(item) <= 6)
        if short_clause_count >= 2 and short_clause_count == len(fragments) and not any(
            _SHORT_CLAUSE_ACTION_VERBS.search(item) for item in fragments
        ):
            return True
        return False

    for line in dialogue_lines:
        inner = line.strip()
        if re.fullmatch(r"[\u4e00-\u9fff]{2,4}[，,][\u4e00-\u9fff]{2,4}", inner):
            problems.append(inner)
        for sentence in re.split(r"[。！？!?]", inner):
            compact_sentence = re.sub(r"\s+", "", sentence).strip("—-…‘’“”\"'")
            if re.fullmatch(r"[一二三四五六七八九十](?:、[一二三四五六七八九十])+", compact_sentence):
                continue
            if sentence.count("、") >= 2 and sentence.count("，") >= 2:
                problems.append(f"清单式短句“{sentence}”")
                continue
            fragments = [fragment.strip() for fragment in re.split(r"[，,、]", sentence) if fragment.strip()]
            compact_fragments = [re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", fragment) for fragment in fragments]
            if len(compact_fragments) >= 3 and all(1 <= len(fragment) <= 6 for fragment in compact_fragments):
                problems.append(f"清单式短句“{sentence.strip()}”")
            if _looks_like_command_snippet(sentence):
                problems.append(f"电报码式台词“{sentence.strip()}”")
            if _is_telegraphic_dialogue(sentence):
                problems.append(f"电报码式台词“{sentence.strip()}”")
    result: list[str] = []
    for item in problems:
        if item not in result:
            result.append(item)
    return result


def _mechanical_short_paragraph_ratio(body: str) -> float:
    paragraphs = []
    for paragraph in (paragraph.strip() for paragraph in body.split("\n\n") if paragraph.strip()):
        compact = paragraph.strip()
        if compact.startswith("【") and compact.endswith("】"):
            continue
        if compact.startswith(("“", "「", "『")) and compact.endswith(("”", "」", "』")):
            continue
        paragraphs.append(compact)
    if len(paragraphs) < 20:
        return 0.0
    short_count = sum(1 for paragraph in paragraphs if len(paragraph) <= 28)
    return short_count / len(paragraphs)


def _panel_explanation_problems(body: str) -> list[str]:
    """Catch a UI panel followed by an author-facing explanation.

    A panel is a reader-visible event. Repeating its meaning in a sentence
    immediately after the block is the main way backend notes leak into prose.
    Keep the check local so ordinary explanatory dialogue is not penalized.
    """
    problems: list[str] = []
    panel_markers = ("角色面板", "怪物面板", "状态面板", "属性面板")
    sentences = re.split(r"(?<=[。！？!?])", body)
    for index, sentence in enumerate(sentences):
        if not any(marker in sentence for marker in panel_markers):
            continue
        window = "".join(sentences[index : index + 3])
        hits = [term for term in PANEL_EXPLANATION_TERMS if term in window]
        if hits:
            problems.append(f"面板后重复解释：{'、'.join(hits[:3])}")
    return problems


def _transaction_process_explanation_problems(body: str) -> list[str]:
    """Catch backend transaction rules narrated instead of shown on screen."""

    problems: list[str] = []
    sentences = [item for item in re.split(r"(?<=[。！？!?])", body) if item.strip()]
    for index in range(len(sentences)):
        window = "".join(sentences[index : index + 2])
        hits = [term for term in TRANSACTION_PROCESS_EXPLANATION_TERMS if term in window]
        if len(hits) >= 3:
            problems.append(f"交易流程说明：{'、'.join(hits[:4])}")
    return problems


def review_prose_style(body: str, *, genre_context: Any = None) -> dict[str, Any]:
    """Review whether prose avoids common AI-fiction texture problems."""

    scores = {
        "cliche_terms": 8,
        "meta_language": 8,
        "dialogue_texture": 8,
        "mechanical_texture": 8,
        "game_term_precision": 8,
    }
    issues: list[str] = []
    revision_plan: list[str] = []

    if is_game_genre_context(body, genre_context):
        for violation in detect_economy_boundary_violations(body):
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="game_term_precision",
                issue=f"[必须修复]经济边界：{violation.issue}",
                plan=violation.revision,
                score=3,
            )

    cliches = _repeated_terms(body, AI_CLICHE_TERMS)
    if cliches:
        sample = "、".join(cliches[:6])
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="cliche_terms",
            issue=f"AI高频套话进入正文：{sample}。",
            plan="删除这些套话，用动作、微表情和细微生理反应替代抽象心理；同时拆短长句，减少工整对仗。",
        )

    meta_terms = _repeated_terms(body, META_LANGUAGE_TERMS)
    if meta_terms:
        sample = "、".join(meta_terms[:6])
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="meta_language",
            issue=f"创作层术语进入正文：{sample}。",
            plan="删掉爽点、钩子、节奏、读者、生成、审稿等出戏词，改成角色能看见、听见或判断出的世界内信息。",
        )

    stiff_dialogue = _repeated_terms(body, STIFF_DIALOGUE_TERMS)
    if stiff_dialogue:
        sample = "、".join(stiff_dialogue[:4])
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="dialogue_texture",
            issue=f"对话偏书面或模板化：{sample}。",
            plan="按角色身份改写对白：口语、带动作、意思完整；莽夫别文绉绉，商人要算账，NPC要有岗位口吻。",
            score=6,
        )

    modern_dialogue = _modern_chinese_dialogue_problems(body)
    if modern_dialogue:
        sample = "、".join(modern_dialogue[:6])
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="dialogue_texture",
            issue=f"现代中文对话不自然：{sample}。台词像提纲句、翻译腔或系统说明，不像人物顺嘴说话。",
            plan="少解释只针对旁白，不是让人物省略连接词。对白/台词要完整说出原因和决策，再带一个动作。把清单式短句改成完整口语；例如“窗坏、瓦落、门锁坏，先报我”改成“要是窗子、屋瓦或者门锁出了问题，你先来报我”。“先试，不深入”改成“我就在坡口打两只看看，不往里走”；“柜台不认”改成“你手里没毒腺，接了也交不了”。",
            score=5,
        )

    old_slogans = _repeated_terms(body, OLD_SLOGAN_PAYOFF_TERMS)
    if old_slogans:
        sample = "、".join(old_slogans[:6])
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="dialogue_texture",
            issue=f"章末反打写成旧式口号：{sample}。这类句子脱离当章具体矛盾，容易显得装。",
            plan="改成白话、贴当章具体矛盾的压句；例如从材料、任务牌、抢怪、前置任务或误判里落一句，不套成语、不喊口号。",
            score=5,
        )

    mechanical_terms = _repeated_terms(body, MECHANICAL_EXPLANATION_TERMS)
    panel_explanations = _panel_explanation_problems(body)
    if panel_explanations:
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="mechanical_texture",
            issue="；".join(panel_explanations[:2]),
            plan="面板只保留角色当场看见的字段；面板结束后直接接动作、选择或对话，删掉重复解释数字和规则的句子。",
            score=5,
        )
    transaction_explanations = _transaction_process_explanation_problems(body)
    if transaction_explanations:
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="mechanical_texture",
            issue="；".join(transaction_explanations[:2]),
            plan="把交易规则说明改成角色当场的点击、反馈和物品变化；界面只显示必要状态，不解释平台后台流程和信息权限。",
            score=5,
        )
    short_ratio = _mechanical_short_paragraph_ratio(body)
    if short_ratio >= 0.5 or (short_ratio >= 0.38 and len(mechanical_terms) >= 2) or len(mechanical_terms) >= 6:
        sample = "、".join(mechanical_terms[:6]) or f"短段比例{short_ratio:.0%}"
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="mechanical_texture",
            issue=f"正文有机械切段或解释腔，读起来像模型在拆规则：{sample}。",
            plan="合并连续省略段，删掉“意味着/很直接/很清楚/不能/需要”等报告式判断；把规则变成动作、对话、犹豫、环境反馈和具体代价。",
            score=5,
        )

    stiff_terms = _repeated_terms(body, STIFF_WEBNOVEL_OUTPUT_TERMS)
    if stiff_terms:
        sample = "、".join(stiff_terms[:6])
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="plain_tomato_language",
            issue=f"正文带出后台硬词，不像番茄白话文：{sample}。",
            plan="把这类硬词换成读者能直接看懂的动作和物件：试一把、问一嘴、包快满、药水不够、法杖快断、柜台不给办。",
            score=5,
        )

    bad_staff_terms = _repeated_terms(body, BAD_STAFF_TERMS)
    if bad_staff_terms:
        sample = "、".join(bad_staff_terms[:6])
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="game_term_precision",
            issue=f"装备称呼不自然：{sample}。普通叙述应写“法杖”或“新手法杖”，不要单说“杖”。",
            plan="把修杖、握杖、杖身、杖尖、木杖等改成修法杖、握着法杖、法杖表面/杖芯道具名等自然说法；裂纹杖芯这类固定道具名保留。",
            score=5,
        )

    return {
        "pass": all(score >= 8 for score in scores.values()) and not issues,
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
    }
