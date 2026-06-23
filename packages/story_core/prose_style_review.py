from __future__ import annotations

from typing import Any


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

MECHANICAL_EXPLANATION_TERMS = (
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
        '拒绝华丽辞藻堆砌、拒绝成语套话、拒绝书面生硬表达、拒绝流水账、不要模板化心理描写、用词口语化生活化、句子按场面自然长短、人物说话要完整自然、人物行为符合人设、前后逻辑严谨、不要重复句式。',
        "固定文风：默认偏直白爽文；如项目指定古风氛围感或细腻日常，则贴合指定风格。句子长短错落，少长难句，不用千篇一律的玄幻套话。",
        "一章分3到4个叙事段落推进：开局铺垫、冲突发生、高潮互动、结尾留钩子；不要一次性把事件压成流水账。",
        "生成后自检第一步：替换心中一紧、五味杂陈、脸色一变、眸光一凝、身形一闪、霎时间、此刻、见状、不由得、殊不知、与此同时等AI高频套话。",
        "用动作 + 微表情 + 细微生理反应替代抽象心理；例如用指尖收紧、肩线绷住、笑意变淡，而不是直接写心中一紧。",
        "打散句式：叙述可以拆短，但对话不要拆成口令；调换主语顺序，删除无意义修饰和注水形容词。",
        "增加专属生活化细节：人物小习惯、环境气味/声音/光线、道具使用痕迹、口头禅、过往小阴影或偏执小习惯。",
        "修正逻辑并防吃设定：核对实力、身份、伏笔、时间、地点、道具、装备、货币和任务状态；删除强行降智、强行巧合、强行煽情。",
        "改写对话：配角说话要符合身份，接地气，别绕太远；加说话动作，删除像念台词的空洞废话。",
        "番茄白话风：不要把后台词写进正文和标题。边界/验证/服务节点/信息边界/逻辑/模型/阈值/可见性，要换成试一把、问一嘴、柜台能不能办、先别卖、包快满、药水不够、法杖快断。",
        "修辞配额：每800字最多1个比喻，形容词不要连着堆；优先写动作、对话、面板提示、背包格、耐久和直接后果。",
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


def review_prose_style(body: str) -> dict[str, Any]:
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

    mechanical_terms = _repeated_terms(body, MECHANICAL_EXPLANATION_TERMS)
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
