from __future__ import annotations

from typing import Any

from packages.story_core.models import CharacterState, PersonalityPortrait


_PROTAGONIST_LABELS = {
    "protagonist",
    "main character",
    "lead character",
    "主角",
    "男主",
    "女主",
    "男主角",
    "女主角",
}
_RECURRING_LABELS = {
    "recurring",
    "recurring npc",
    "long-term npc",
    "long term npc",
    "长期配角",
    "长期npc",
    "常驻配角",
    "常驻npc",
}
_SERVICE_ROLE_LABELS = {
    "service npc",
    "service-npc",
    "clerk",
    "vendor",
    "merchant",
    "receptionist",
    "guard",
    "repairer",
    "mechanic",
    "apothecary",
    "药剂师",
    "商人",
    "登记员",
    "修理匠",
    "店员",
    "掌柜",
    "前台",
    "门卫",
    "守卫",
}
_SERVICE_DUTY_PHRASES = (
    "archive clerk",
    "service counter",
    "registration desk",
    "equipment repair service",
    "trial registration",
    "course administration",
    "档案登记",
    "登记服务",
    "柜台办理",
    "试炼办理",
    "办理试炼",
    "授课岗位",
    "装备修理服务",
)


def _clean(value: str) -> str:
    return value.strip() if value else ""


def _normalize_label(value: str) -> str:
    return " ".join(_clean(value).casefold().replace("_", " ").split())


def _clean_list(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


def _join_unique(values: list[str]) -> str:
    return "；".join(dict.fromkeys(value for value in values if value))


def _first(*values: str, fallback: str) -> str:
    return next((cleaned for value in values if (cleaned := _clean(value))), fallback)


def _portrait_kind(character: CharacterState, story_function: str) -> str:
    role = _normalize_label(character.role)
    character_type = _normalize_label(character.character_type)
    service_role = _clean(character.npc_profile.service_role)
    if service_role:
        return "service_npc"
    if role in _PROTAGONIST_LABELS or character_type in _PROTAGONIST_LABELS:
        return "protagonist"
    if role in _RECURRING_LABELS or character_type in _RECURRING_LABELS:
        return "recurring_support"
    if role in _SERVICE_ROLE_LABELS or character_type in _SERVICE_ROLE_LABELS:
        return "service_npc"
    function_context = " ".join(
        _normalize_label(value)
        for value in (story_function, character.story_function)
        if _clean(value)
    )
    if any(phrase in function_context for phrase in _SERVICE_DUTY_PHRASES):
        return "service_npc"
    return "recurring_support"


def _genre_behavior(genre: str) -> tuple[str, str]:
    normalized = _normalize_label(genre)
    profiles = (
        (
            ("修仙", "仙侠", "xianxia", "cultivation"),
            "压力下先核对资源、境界差距与门规后果，再决定投入多少",
            "在资源积累、境界进展和门规代价之间选择当前行动",
        ),
        (
            ("悬疑", "推理", "mystery", "suspense"),
            "压力下先保护证据、控制口风并评估暴露风险",
            "优先选择能验证证据且不会无谓扩大暴露风险的行动",
        ),
        (
            ("网游", "游戏", "web game", "online game"),
            "压力下先检查任务条件、资源消耗和信息可见范围",
            "在任务收益、资源消耗和信息暴露之间选择当前行动",
        ),
        (
            ("都市", "urban"),
            "压力下先衡量关系、现实规则和直接后果",
            "优先选择兼顾现实后果、关系成本和当前目标的行动",
        ),
    )
    for markers, pressure_mode, decision_tendency in profiles:
        if any(marker in normalized for marker in markers):
            return pressure_mode, decision_tendency
    return (
        "压力下仍围绕当前目标行动，并根据新信息调整投入",
        "按当前目标、自身利益、关系和可见后果选择行动",
    )


def _service_role_for(character: CharacterState, function: str) -> str:
    explicit = _clean(character.npc_profile.service_role)
    if explicit:
        return explicit
    if _normalize_label(character.role) in _SERVICE_ROLE_LABELS:
        return _clean(character.role)
    if _normalize_label(character.character_type) in _SERVICE_ROLE_LABELS:
        return _clean(character.character_type)
    return function


def _shared_inputs(
    character: CharacterState,
    *,
    genre: str,
    story_function: str,
) -> dict[str, str | list[str]]:
    performance = character.performance_profile
    function = _first(
        story_function,
        character.story_function,
        character.npc_profile.service_role,
        fallback=_clean(character.role) or "当前人物职责",
    )
    goals = _clean_list(character.goals)
    incentives = _clean_list(character.npc_profile.incentives)
    motivation_parts = [_clean(character.core_motivation), *goals, *incentives]
    motivation = _join_unique(motivation_parts) or f"围绕{function}行动"
    behavior = _first(
        character.behavior_logic,
        performance.action_style,
        fallback="围绕当前目标行动，并根据结果调整下一步",
    )
    genre_pressure, genre_decision = _genre_behavior(genre)
    decision_rules = _clean_list(performance.decision_rules)
    triggers = _clean_list(performance.emotional_triggers) or [
        "当前目标受阻",
        "自身利益或重要关系受到影响",
    ]
    return {
        "function": function,
        "service_role": _service_role_for(character, function),
        "motivation": motivation,
        "incentives": incentives,
        "behavior": behavior,
        "setting": _clean(genre) or "当前题材",
        "triggers": triggers,
        "speech": _first(performance.speech_style, fallback="根据身份和当前关系说具体的话"),
        "pressure": _first(performance.risk_posture, fallback=genre_pressure),
        "decision": _join_unique(decision_rules) or genre_decision,
        "avoided": _clean_list(performance.reveal_limits) or _clean_list(performance.voice.taboo),
        "common_words": _clean_list(performance.voice.signature_phrases)
        or _clean_list(performance.voice.lexicon),
        "sentence_habit": _first(
            performance.voice.sentence_rhythm,
            performance.speech_style,
            fallback="句子长短随压力和关系变化，不固定使用一种腔调",
        ),
    }


def _protagonist_template(inputs: dict[str, str | list[str]]) -> PersonalityPortrait:
    motivation = str(inputs["motivation"])
    function = str(inputs["function"])
    return PersonalityPortrait.model_validate(
        {
            "temperament": {
                "outward_impression": f"在{inputs['setting']}中围绕{motivation}采取行动",
                "core_traits": [f"以{motivation}为当前驱动力", "会根据行动结果调整选择"],
                "inner_contradiction": "个人目标、关系和环境代价之间可能发生冲突",
                "values": ["当前目标", "行动产生的实际反馈"],
                "bottom_line": "不会无依据背离已经确立的目标和行为逻辑",
            },
            "psychology": {
                "desire": motivation,
                "fear": f"{function}受阻并产生难以挽回的后果",
                "blind_spot": "对自身选择造成的连带影响可能判断不足",
                "defense": "受到压力时会沿用自己最熟悉的处理方式",
                "shame_point": "不愿面对自己在核心目标上的失败或动摇",
            },
            "behavior": {
                "normal_mode": inputs["behavior"],
                "pressure_mode": inputs["pressure"],
                "conflict_response": "根据目标、对方反应和可承担后果选择交涉、回避或对抗",
                "failure_response": "先处理直接后果，再根据失败暴露的信息调整下一步",
                "decision_tendency": inputs["decision"],
            },
            "emotion": {
                "triggers": inputs["triggers"],
                "restraint_style": "是否克制取决于当前目标、关系和公开表达的代价",
                "loss_of_control": "压力越过承受范围时会放大其既有行为倾向",
                "mannerisms": ["做决定前确认当前最重要的目标", "受到刺激时重复惯用动作"],
            },
            "social": {
                "strangers": "按当前利益、风险和对方表现决定距离",
                "friends": "按既有关系和共同经历回应，不默认亲近或疏离",
                "authority": "根据权力关系、规则后果和个人目标决定配合程度",
                "enemies": "围绕冲突目标行动，不无依据增加私人道德判断",
            },
            "voice": {
                "common_words": inputs["common_words"] or ["先看现在怎么办", "把情况说清楚"],
                "sentence_habit": inputs["sentence_habit"],
                "avoided_topics": inputs["avoided"] or ["尚未准备公开的目标和代价"],
                "lying_style": "是否隐瞒以及如何隐瞒取决于目标、风险和已有行为逻辑",
                "anger_style": "生气时延续既有说话方式，但内容更直接指向冲突目标",
                "relaxed_style": "放松时减少对当前风险的防备，表达更贴近日常习惯",
            },
            "growth": {
                "initial_flaw": "当前处理方式尚不能覆盖所有关系和环境变化",
                "invariants": [f"核心驱动力保持为：{motivation}", "变化必须由经历和后果推动"],
                "change_conditions": ["原有做法造成明确代价", "新的关系或信息改变其判断依据"],
                "stage_direction": f"围绕{function}逐步调整目标、关系与行动方式",
            },
            "writing_limits": [
                "不能无铺垫地改变核心目标",
                "不能用作者总结代替具体选择",
                "不能为制造冲突突然失去已有行为逻辑",
            ],
        }
    )


def _recurring_support_template(inputs: dict[str, str | list[str]]) -> PersonalityPortrait:
    motivation = str(inputs["motivation"])
    function = str(inputs["function"])
    return PersonalityPortrait.model_validate(
        {
            "temperament": {
                "outward_impression": f"在{inputs['setting']}中以{function}的立场参与局面",
                "core_traits": ["有独立目标", "按自身利益和关系反应"],
                "inner_contradiction": "个人目标可能与当前关系或剧情职责发生冲突",
                "values": [motivation, "自身利益与既有关系"],
                "bottom_line": "不会无依据放弃自身目标或变成只服务他人的工具",
            },
            "psychology": {
                "desire": motivation,
                "fear": "自身目标、利益或重要关系受到不可逆影响",
                "blind_spot": "可能只从自己的位置理解局面",
                "defense": "压力下会回到最熟悉的关系和行动模式",
                "shame_point": "不愿公开承认自己真正看重的目标或关系",
            },
            "behavior": {
                "normal_mode": inputs["behavior"],
                "pressure_mode": inputs["pressure"],
                "conflict_response": "按自身目标、关系和现实后果决定合作、拒绝或对抗",
                "failure_response": "根据损失和新信息调整行动，不自动等待主角解决",
                "decision_tendency": inputs["decision"],
            },
            "emotion": {
                "triggers": inputs["triggers"],
                "restraint_style": "是否表达情绪取决于关系距离和表达后的现实影响",
                "loss_of_control": "压力过高时会放大原有利益选择或关系倾向",
                "mannerisms": ["互动前判断对方与自身目标的关系", "紧张时重复熟悉的小动作"],
            },
            "social": {
                "strangers": "根据自身利益、风险和对方表现决定回应程度",
                "friends": "根据既有关系投入，不默认无条件帮助",
                "authority": "结合规则后果和自身处境决定配合、周旋或拒绝",
                "enemies": "围绕实际冲突和关系历史回应，不自动升级为全面敌对",
            },
            "voice": {
                "common_words": inputs["common_words"] or ["这和我有什么关系", "先把情况说清楚"],
                "sentence_habit": inputs["sentence_habit"],
                "avoided_topics": inputs["avoided"] or ["尚未公开的个人目标"],
                "lying_style": "隐瞒方式取决于其目标、关系和已有说话习惯",
                "anger_style": "生气时更直接表达自身利益或关系受到的影响",
                "relaxed_style": "放松时更多表现日常兴趣和原有关系习惯",
            },
            "growth": {
                "initial_flaw": "现有目标与关系处理方式仍有未验证的局限",
                "invariants": [f"保留独立驱动力：{motivation}", "不会无依据变成主角附属"],
                "change_conditions": ["自身选择造成明确后果", "关系或环境提供新的判断依据"],
                "stage_direction": f"围绕{function}调整个人目标与关系位置",
            },
            "writing_limits": ["不能只负责递送信息", "不能无条件赞同主角", "行动应有目标、利益或关系依据"],
        }
    )


def _service_npc_template(inputs: dict[str, str | list[str]]) -> PersonalityPortrait:
    service_role = str(inputs["service_role"])
    motivation = str(inputs["motivation"])
    incentives = _join_unique(list(inputs["incentives"])) or motivation
    function = str(inputs["function"])
    role_decision = f"围绕{service_role}职责和{incentives}作出选择"
    return PersonalityPortrait.model_validate(
        {
            "temperament": {
                "outward_impression": f"在{inputs['setting']}中以{service_role}身份处理{function}",
                "core_traits": [f"熟悉{service_role}相关事务", f"会按{incentives}调整选择"],
                "inner_contradiction": f"{service_role}职责、自身利益和当前关系可能互相冲突",
                "values": [incentives, f"{service_role}职责"],
                "bottom_line": f"不会无依据违背{service_role}职责或自身利益",
            },
            "psychology": {
                "desire": motivation,
                "fear": f"{service_role}相关利益、资源或关系受到不可承受的损失",
                "blind_spot": "可能只从自己的职责和利益位置理解来访者",
                "defense": "压力下会优先使用其岗位经验和熟悉的处理方式",
                "shame_point": f"不愿暴露自己无法完成{service_role}职责的部分",
            },
            "behavior": {
                "normal_mode": inputs["behavior"],
                "pressure_mode": f"{inputs['pressure']}；优先处理与{service_role}直接相关的风险",
                "conflict_response": f"按{service_role}职责、自身利益和对方行为决定继续、拒绝或寻求帮助",
                "failure_response": f"先处理{service_role}相关损失，再根据结果调整后续互动",
                "decision_tendency": f"{role_decision}；{inputs['decision']}",
            },
            "emotion": {
                "triggers": inputs["triggers"],
                "restraint_style": f"根据{service_role}场景和表达后的利益影响决定是否克制",
                "loss_of_control": f"压力超过承受范围时会放大其对{service_role}利益的保护",
                "mannerisms": [f"互动时先确认与{service_role}有关的事项", "压力下重复熟悉的岗位动作"],
            },
            "social": {
                "strangers": f"根据{service_role}职责、利益和对方表现决定提供多少帮助",
                "friends": f"会考虑既有关系，但仍受{service_role}处境和自身利益影响",
                "authority": f"结合上位者对{service_role}处境的实际影响决定回应方式",
                "enemies": f"围绕{service_role}相关冲突回应，不自动提供额外帮助",
            },
            "voice": {
                "common_words": inputs["common_words"] or [f"这件事和{service_role}有关", "先说具体要做什么"],
                "sentence_habit": inputs["sentence_habit"],
                "avoided_topics": inputs["avoided"] or [f"可能损害{service_role}利益的信息"],
                "lying_style": f"隐瞒方式取决于{service_role}利益、当前风险和已有说话习惯",
                "anger_style": f"生气时更直接指出对{service_role}职责或利益的影响",
                "relaxed_style": "放松时减少岗位防备，表现日常说话和关系习惯",
            },
            "growth": {
                "initial_flaw": f"现有{service_role}处理方式难以覆盖所有关系和环境变化",
                "invariants": [f"保留{service_role}身份带来的现实利益", f"核心驱动力保持为：{motivation}"],
                "change_conditions": ["利益结构或职责发生明确变化", "持续互动改变其关系判断"],
                "stage_direction": f"随{service_role}处境、利益和关系变化调整帮助范围",
            },
            "writing_limits": [
                f"不能脱离{service_role}职责和自身利益强行推动剧情",
                "不能无依据提供全部信息或资源",
                "态度变化需要利益、职责或关系依据",
            ],
        }
    )


def _fill_empty(existing: Any, defaults: Any) -> Any:
    if isinstance(existing, dict) and isinstance(defaults, dict):
        return {
            key: _fill_empty(existing.get(key), value)
            for key, value in defaults.items()
        }
    if isinstance(existing, str):
        return existing if existing.strip() else defaults
    if isinstance(existing, list):
        return existing if existing else defaults
    return defaults if existing is None else existing


def complete_character_portrait(
    character: CharacterState,
    genre: str = "",
    story_function: str = "",
) -> CharacterState:
    """Fill empty portrait fields with deterministic local rules."""

    inputs = _shared_inputs(character, genre=genre, story_function=story_function)
    kind = _portrait_kind(character, story_function)
    template_builder = {
        "protagonist": _protagonist_template,
        "service_npc": _service_npc_template,
        "recurring_support": _recurring_support_template,
    }[kind]
    defaults = template_builder(inputs)
    completed = PersonalityPortrait.model_validate(
        _fill_empty(
            character.personality_portrait.model_dump(),
            defaults.model_dump(),
        )
    )
    return character.model_copy(
        update={"personality_portrait": completed},
        deep=True,
    )


def build_scene_portrait_slice(card: dict[str, Any], *, max_chars: int = 480) -> dict[str, Any]:
    """Extract only the behavior needed for the current scene prompt."""

    portrait = card.get("personality_portrait") if isinstance(card.get("personality_portrait"), dict) else {}
    behavior = portrait.get("behavior") if isinstance(portrait.get("behavior"), dict) else {}
    emotion = portrait.get("emotion") if isinstance(portrait.get("emotion"), dict) else {}
    social = portrait.get("social") if isinstance(portrait.get("social"), dict) else {}
    voice = portrait.get("voice") if isinstance(portrait.get("voice"), dict) else {}
    usage = card.get("story_usage") if isinstance(card.get("story_usage"), dict) else {}
    chapter_usage = usage.get("this_chapter_usage") if isinstance(usage.get("this_chapter_usage"), dict) else {}
    performance = card.get("voice_and_action") if isinstance(card.get("voice_and_action"), dict) else {}

    result = {
        "drive": str(chapter_usage.get("drive") or card.get("webnovel_profile", {}).get("core_motivation") or "").strip(),
        "current_emotion": str(usage.get("current_emotion") or chapter_usage.get("status") or "neutral").strip(),
        "pressure_behavior": str(behavior.get("pressure_mode") or performance.get("action_style") or "").strip(),
        "conflict_response": str(behavior.get("conflict_response") or "").strip(),
        "social_stance": str(social.get("authority") or social.get("strangers") or "").strip(),
        "triggers": [str(item).strip() for item in emotion.get("triggers", []) if str(item).strip()][:3],
        "mannerisms": [str(item).strip() for item in emotion.get("mannerisms", []) if str(item).strip()][:3],
        "voice": str(voice.get("sentence_habit") or performance.get("speech_style") or "").strip(),
        "writing_limits": [str(item).strip() for item in portrait.get("writing_limits", []) if str(item).strip()][:4],
    }
    # Keep each signal present and bounded without changing the structured card.
    string_limits = {
        "drive": 90,
        "current_emotion": 30,
        "pressure_behavior": 100,
        "conflict_response": 90,
        "social_stance": 70,
        "voice": 100,
    }
    for key, limit in string_limits.items():
        result[key] = result[key][:limit]
    result["triggers"] = [item[:40] for item in result["triggers"]]
    result["mannerisms"] = [item[:40] for item in result["mannerisms"]]
    result["writing_limits"] = [item[:55] for item in result["writing_limits"]]
    return result
