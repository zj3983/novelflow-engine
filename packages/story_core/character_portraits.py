from __future__ import annotations

from typing import Any

from packages.story_core.models import CharacterState, PersonalityPortrait


_PROTAGONIST_ROLES = ("protagonist", "lead", "主角", "男主", "女主")
_RECURRING_ROLES = ("recurring", "long-term", "long term", "长期", "常驻")
_SERVICE_IDENTITIES = (
    "service npc",
    "service-npc",
    "clerk",
    "vendor",
    "merchant",
    "receptionist",
    "guard",
    "repairer",
    "mechanic",
    "药剂师",
    "商人",
    "登记员",
    "修理匠",
    "店员",
    "掌柜",
    "前台",
    "门卫",
    "守卫",
)
_SERVICE_DUTIES = (
    "archive clerk",
    "service counter",
    "registration desk",
    "档案登记",
    "登记服务",
    "柜台办理",
    "试炼办理",
    "办理试炼",
    "授课岗位",
)


def _first(*values: str, fallback: str) -> str:
    return next((value.strip() for value in values if value and value.strip()), fallback)


def _portrait_kind(character: CharacterState, story_function: str) -> str:
    role = character.role.casefold()
    character_type = character.character_type.casefold()
    function_context = " ".join(
        value.casefold()
        for value in (story_function, character.story_function)
        if value and value.strip()
    )
    if any(marker in role for marker in _PROTAGONIST_ROLES):
        return "protagonist"
    if any(marker in role or marker in character_type for marker in _RECURRING_ROLES):
        return "recurring_support"
    has_service_identity = any(
        marker in role or marker in function_context for marker in _SERVICE_IDENTITIES
    )
    has_service_duty = any(marker in function_context for marker in _SERVICE_DUTIES)
    if character.npc_profile.service_role or has_service_identity or has_service_duty:
        return "service_npc"
    return "recurring_support"


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
        fallback=character.role or "推动当前人物关系",
    )
    motivation = _first(
        character.core_motivation,
        "；".join(character.goals),
        fallback=f"完成其作为{function}的当前目标",
    )
    behavior = _first(
        character.behavior_logic,
        performance.action_style,
        fallback="先判断自身代价和可用信息，再采取行动",
    )
    setting = genre.strip() or "当前题材"
    triggers = list(performance.emotional_triggers) or ["核心目标被阻断", "底线受到试探"]
    return {
        "function": function,
        "motivation": motivation,
        "behavior": behavior,
        "setting": setting,
        "triggers": triggers,
        "speech": _first(performance.speech_style, fallback="说具体的话，不替作者解释性格"),
        "risk": _first(performance.risk_posture, fallback="风险越高，越会先确认退路"),
        "decision": "；".join(performance.decision_rules) or behavior,
        "avoided": list(performance.reveal_limits) or list(performance.voice.taboo),
        "common_words": list(performance.voice.signature_phrases) or list(performance.voice.lexicon),
        "sentence_habit": _first(
            performance.voice.sentence_rhythm,
            performance.speech_style,
            fallback="先说结论，再补必要事实",
        ),
    }


def _protagonist_template(inputs: dict[str, str | list[str]]) -> PersonalityPortrait:
    motivation = str(inputs["motivation"])
    behavior = str(inputs["behavior"])
    function = str(inputs["function"])
    return PersonalityPortrait.model_validate(
        {
            "temperament": {
                "outward_impression": f"在{inputs['setting']}环境中显得克制、警觉，遇事先看后果",
                "core_traits": ["主动承担", "谨慎判断", "不轻易服输"],
                "inner_contradiction": "想掌握局面，却必须依赖自己无法完全控制的人和规则",
                "values": ["行动要有代价意识", "承诺必须兑现"],
                "bottom_line": "不拿无辜者当成达成目标的耗材",
            },
            "psychology": {
                "desire": motivation,
                "fear": f"没能完成{function}，并让信任自己的人承担后果",
                "blind_spot": "容易把求助误认为软弱，把责任全部揽到自己身上",
                "defense": "用分析、行动和控制细节代替暴露真实不安",
                "shame_point": "害怕别人发现自己并没有表面上那么有把握",
            },
            "behavior": {
                "normal_mode": behavior,
                "pressure_mode": str(inputs["risk"]),
                "conflict_response": "先辨认对方真正要什么；谈不拢时用行动争取主动权",
                "failure_response": "先处理损失和连带后果，独处时才复盘自己的错误",
                "decision_tendency": str(inputs["decision"]),
            },
            "emotion": {
                "triggers": inputs["triggers"],
                "restraint_style": "情绪越重，语气越短，手上的事做得越具体",
                "loss_of_control": "底线连续被踩时会放弃周旋，直接承担高风险后果",
                "mannerisms": ["思考时确认出口和周围人的位置", "做决定前短暂停顿"],
            },
            "social": {
                "strangers": "礼貌但保留信息，先观察对方是否言行一致",
                "friends": "会用解决实际问题代替直白安慰",
                "authority": "尊重有效规则，不因身份本身停止质疑",
                "enemies": "不做无谓羞辱，优先拆掉对方的筹码和退路",
            },
            "voice": {
                "common_words": inputs["common_words"] or ["先等等", "把条件说清楚"],
                "sentence_habit": inputs["sentence_habit"],
                "avoided_topics": inputs["avoided"] or ["自己的恐惧", "尚未兑现的承诺"],
                "lying_style": "尽量说字面为真的片段，通过省略关键因果误导对方",
                "anger_style": "不提高音量，减少解释，问题会问得更直接",
                "relaxed_style": "句子变长，偶尔拿共同经历开轻微的玩笑",
            },
            "growth": {
                "initial_flaw": "把独自承受一切当成可靠",
                "invariants": ["不主动牺牲无辜者", "关键承诺不会因得失改变"],
                "change_conditions": ["独自控制局面造成真实损失", "他人以行动证明值得托付"],
                "stage_direction": f"在承担{function}的过程中学会区分责任与控制欲",
            },
            "writing_limits": [
                "不能无铺垫地放弃核心目标",
                "不能用作者总结代替具体选择",
                "不能为制造冲突突然失去基本判断力",
            ],
        }
    )


def _recurring_support_template(inputs: dict[str, str | list[str]]) -> PersonalityPortrait:
    function = str(inputs["function"])
    return PersonalityPortrait.model_validate(
        {
            "temperament": {
                "outward_impression": f"在{inputs['setting']}语境中以{function}的立场观察局面，不会自动围着主角转",
                "core_traits": ["有自己的利害判断", "重视关系中的对等"],
                "inner_contradiction": "需要合作，又担心合作会损害自己的长期利益",
                "values": ["互惠", "保留选择权"],
                "bottom_line": "不接受被当成随叫随到的工具",
            },
            "psychology": {
                "desire": str(inputs["motivation"]),
                "fear": "失去自己在关系和局势中的独立位置",
                "blind_spot": "容易高估自己保持中立的能力",
                "defense": "用交换条件和半开玩笑的试探保护真实立场",
                "shame_point": "不愿承认自己已经对某段关系投入过深",
            },
            "behavior": {
                "normal_mode": str(inputs["behavior"]),
                "pressure_mode": str(inputs["risk"]),
                "conflict_response": "先划清各自责任，再决定帮到哪一步",
                "failure_response": "表面维持正常，随后调整合作条件并寻找补救",
                "decision_tendency": str(inputs["decision"]),
            },
            "emotion": {
                "triggers": inputs["triggers"],
                "restraint_style": "用转移话题或处理手边事务争取冷静时间",
                "loss_of_control": "被反复利用时会突然收回原本提供的帮助",
                "mannerisms": ["谈条件时反复确认措辞", "紧张时整理手边物品"],
            },
            "social": {
                "strangers": "保持客气，只提供与当前交换相称的信息",
                "friends": "愿意额外承担一次风险，但会记住对方是否回应",
                "authority": "先判断对方能兑现什么，再决定服从或周旋",
                "enemies": "避免正面交底，优先保住自己的资源和关系网",
            },
            "voice": {
                "common_words": inputs["common_words"] or ["这要看条件", "我只能帮到这里"],
                "sentence_habit": inputs["sentence_habit"],
                "avoided_topics": inputs["avoided"] or ["真正站队的原因"],
                "lying_style": "把个人选择包装成客观条件限制",
                "anger_style": "语气变得公事公办，逐条重算彼此欠下的账",
                "relaxed_style": "会主动分享无关紧要的小事，试探关系是否安全",
            },
            "growth": {
                "initial_flaw": "过度依赖交换来确认关系安全",
                "invariants": ["保留自身利益和判断", "不会无条件服从任何一方"],
                "change_conditions": ["长期互惠被证明可靠", "旧有中立策略造成不可挽回的代价"],
                "stage_direction": f"围绕{function}逐步明确自己真正愿意承担的立场",
            },
            "writing_limits": ["不能只负责递送信息", "不能无条件赞同主角", "每次帮助都应有动机或关系依据"],
        }
    )


def _service_npc_template(inputs: dict[str, str | list[str]]) -> PersonalityPortrait:
    function = str(inputs["function"])
    motivation = str(inputs["motivation"])
    behavior = str(inputs["behavior"])
    return PersonalityPortrait.model_validate(
        {
            "temperament": {
                "outward_impression": f"在{inputs['setting']}环境中以{function}的岗位标准待人，熟练但不额外热情",
                "core_traits": ["重视岗位利益", "按权限办事", "会看人调整态度"],
                "inner_contradiction": "既想把事情快速办完，又不愿为陌生人承担越权风险",
                "values": ["手续清楚", "责任可追溯"],
                "bottom_line": f"不为人情突破{function}的权限边界",
            },
            "psychology": {
                "desire": f"{motivation}；同时守住{function}的岗位利益，让当班事务顺利结束",
                "fear": "替别人背下越权或失职的责任",
                "blind_spot": "容易把不熟悉流程的人也视作潜在麻烦",
                "defense": "反复引用流程、权限和上级要求，把个人判断藏在岗位话术后面",
                "shame_point": "不愿被看出自己其实没有处理特殊情况的权限",
            },
            "behavior": {
                "normal_mode": behavior,
                "pressure_mode": "先保住记录、物资和责任凭据，再决定是否叫上级处理",
                "conflict_response": "先重申权限边界；对方继续施压时中止服务并寻找见证人",
                "failure_response": "立即补记录、上报并把责任节点说清楚",
                "decision_tendency": "优先选择可交代、可留痕、不会让自己单独担责的方案",
            },
            "emotion": {
                "triggers": inputs["triggers"],
                "restraint_style": "把不满压进更标准、更重复的岗位话术里",
                "loss_of_control": "被逼迫越权时会直接停止交流并启动上报流程",
                "mannerisms": ["回答前先看一眼登记或库存", "说到权限时会敲一下台面或记录册"],
            },
            "social": {
                "strangers": "先问来意和凭据，只提供权限内的标准信息",
                "friends": "可以提醒流程漏洞，但不会公开替对方违规",
                "authority": "态度更简短恭敬，优先确认口头要求能否留下记录",
                "enemies": "严格按最低服务标准办事，不主动提供额外便利",
            },
            "voice": {
                "common_words": inputs["common_words"] or ["按规定", "我这里只能办到这一步"],
                "sentence_habit": inputs["sentence_habit"],
                "avoided_topics": inputs["avoided"] or ["内部责任归属", "自己曾经通融过的事"],
                "lying_style": "不直接编造事实，而是用权限不足和流程未完来拖延回答",
                "anger_style": "重复同一句规定，称呼变得正式，不再解释原因",
                "relaxed_style": "会抱怨重复劳动，也会顺口透露不敏感的岗位见闻",
            },
            "growth": {
                "initial_flaw": "把规避责任当成唯一安全方式",
                "invariants": ["优先维护岗位生计", "不会轻易替陌生人越权"],
                "change_conditions": ["对方提供可信凭据或对等回报", "上级明确授权并承担责任"],
                "stage_direction": "只在持续互动改变利益和信任后扩大帮助范围",
            },
            "writing_limits": ["不能无理由泄露全部信息", "不能替主角免费解决权限障碍", "不能脱离岗位利益强行推动剧情"],
        }
    )


def _fill_empty(existing: Any, defaults: Any) -> Any:
    if isinstance(existing, dict) and isinstance(defaults, dict):
        return {
            key: _fill_empty(existing.get(key), value)
            for key, value in defaults.items()
        }
    if isinstance(existing, str):
        return existing if existing else defaults
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
