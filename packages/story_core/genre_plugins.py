from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from packages.story_core.models import NovelProject


RULEBOOK_FIELDS = (
    "progression_rules",
    "economy_rules",
    "quest_rules",
    "faction_rules",
    "panel_rules",
    "chapter_formula",
    "forbidden_breaks",
)


@dataclass(frozen=True)
class GenrePlugin:
    plugin_id: str
    name: str
    keywords: tuple[str, ...]
    core_promises: tuple[str, ...]
    ledger_fields: tuple[str, ...]
    rulebook: dict[str, tuple[str, ...]]
    quality_checks: tuple[str, ...]


GENERIC_WEBNOVEL = GenrePlugin(
    plugin_id="generic_webnovel",
    name="通用网文",
    keywords=("网文", "网络小说", "爽文", "连载", "追读"),
    core_promises=(
        "每章必须给读者一个可感知的推进：收益、反转、关系变化、谜团进展或压力升级。",
        "设定必须通过场景、对话、行动和冲突自然露出，避免百科式说明。",
        "开篇优先服务留存：快速建立代入感、阶段悬念和读者期待，不把背景一次性塞完。",
    ),
    ledger_fields=("读者期待债", "伏笔", "主线压力", "角色关系", "未兑现爽点"),
    rulebook={
        "progression_rules": (
            "主角成长必须有来源、代价和下一阶段门槛，不能凭空跳级或突然全能。",
            "每章至少推进一种进度：能力、资源、关系、情报、地位或谜团。",
        ),
        "economy_rules": (
            "任何资源收益都要考虑稀缺性、变现难度、使用代价和外部反应。",
        ),
        "quest_rules": (
            "阶段目标要清晰，读者需要知道本章在解决什么问题、欠下什么新问题。",
        ),
        "faction_rules": (
            "世界不能只围着主角静止等待，势力、配角和环境要对主角行动做出反馈。",
        ),
        "panel_rules": (
            "提示、旁白或系统信息必须短而关键，不能替代正文叙事。",
        ),
        "chapter_formula": (
            "章节结构优先使用：开场钩子、明确目标、阻力升级、行动选择、阶段兑现、章末新压力。",
            "爽点要和代价成对出现，避免只有奖励没有后果。",
            "黄金三章遵守背景预算：第一章立主角和核心钩子，第二章放大收益与压力，第三章形成小高潮并确立长期路线。",
        ),
        "forbidden_breaks": (
            "禁止摘要化正文，禁止只罗列设定，禁止角色为推动剧情突然降智。",
            "禁止无铺垫解决核心冲突，禁止忘记上一章留下的钩子和事实。",
            "禁止开篇连续堆世界史、势力史、规则表和多地点设定巡礼。",
        ),
    },
    quality_checks=("爽点闭环", "章末钩子", "设定一致", "角色动机", "连续追读"),
)


GAME_WEBNOVEL = GenrePlugin(
    plugin_id="game_webnovel",
    name="网游升级流",
    keywords=("网游", "游戏", "系统", "等级", "副本", "爆率", "职业", "玩家", "公会", "交易行", "VRMMO"),
    core_promises=(
        "读者期待看到稳定的等级、经验、掉落、装备、任务和地图推进循环。",
        "隐藏优势的主爽点是让主角更快完成任务、凑齐装备/技能门槛，并持续领先普通玩家半步到一步。",
        "大型服务器里低级材料和小额铜币是普通噪音，旁人最多觉得主角运气好；真正关注必须等到稀有物、榜单、连续高频记录或多源证据叠加后才出现。",
    ),
    ledger_fields=("等级", "经验", "金币", "装备", "技能", "任务", "领先进度", "金手指暴露度", "外部关注度"),
    rulebook={
        "progression_rules": (
            "等级、经验、装备、技能和称号必须前后一致，任何升级都要有可见成本或明确收益来源。",
            "主角可以有隐藏优势，但优势不能自动解决所有问题，必须受到资源、情报、时间或身份暴露风险限制。",
            "第一章必须写出角色创建或登录阶段的职业选择，并把游戏职业写入角色面板；职业选择要解释后续技能、装备和试炼路线。",
            "游戏职业不是现实职业：苏叶现实职业用于解释风控/拆单能力，夜烬游戏职业必须以元素法师学徒/元素法师路线推进。",
            "每章至少形成一次小收益闭环：目标、行动、收益反馈、新压力。",
        ),
        "economy_rules": (
            "网游币制默认使用 1金币=100银币=10000铜币；新手村低级材料优先用铜币或银币计价，金币是大额单位。",
            "开服初期现实汇率尚未稳定，除非世界档案明确给出官方兑换或黑市行情，否则不得写死“1金币=多少人民币”。",
            "金币、材料、装备价格要体现供需关系，交易行、当面交易和公会垄断都会影响价格。",
            "稀有掉落不能随意变现，必须考虑买家来源、匿名出售、压价、追踪和信誉风险。",
            "主角短期变强可以靠信息差，但不能无代价暴富到破坏世界经济。",
            "低级材料不是主冲突：它们只作为任务、装备、技能或路线门槛的证据，不承担引发市场风暴或第一章服务闭环的戏剧职责。",
        ),
        "quest_rules": (
            "任务、隐藏任务、副本和职业试炼都应有触发条件、失败代价、阶段目标和可验证奖励。",
            "前几章要自然铺垫核心职业试炼或体系入口，不要突然跳到高阶内容。",
            "职业导师或职业大厅应承担职业选择、技能学习、试炼门槛和路线限制，不要让系统旁白替代职业体系运行。",
        ),
        "faction_rules": (
            "公会、商会、NPC势力和普通玩家都有利益诉求，不能只作为背景板。",
            "强势组织会通过拉拢、清场、监视、压价或封锁资源点来制造外部压力。",
            "所有追踪都要遵守信息可见性：交易记录、论坛传闻、资源点目击和NPC反馈只能逐步拼图，不能一步知道真相。",
        ),
        "panel_rules": (
            "系统面板只展示必要信息，使用短提示推进爽点，不要刷屏或替代叙事。",
            "隐藏天赋、爆率倍率、任务奖励等关键信息要分层披露，不能让全世界立刻知道。",
            "角色面板至少能稳定承载：游戏ID、等级、职业/路线、经验、主武器、基础技能、货币和关键任务；第一章必须出现一次职业栏。",
        ),
        "chapter_formula": (
            "开场用压力或收益钩子抓人，中段用行动选择推动规则运转，结尾留下更大的资源或身份压力。",
            "每章都要同时推进主角成长、世界规则展示和领先感：普通玩家还在跑重复流程时，主角已经拿到下一项任务、装备、技能或地图入口。",
            "网游第一章只聚焦一个核心事件：现实压力、登录/建号、选择游戏ID、选择职业、角色面板、首次领先验证、章末下一步目标。",
            "第一章不得实际交易或公会追踪；交易行、商人玩家、公会外围和论坛反应移到第二章以后逐步展开。",
            "第一章不得写成交任务、领取铜币、扣费修理或购买药水；只能看见这些门槛，把办理过程留到第二章。",
        ),
        "forbidden_breaks": (
            "禁止无解释跳级、无成本获得神装、NPC无理由送资源、反派突然降智。",
            "禁止把设定写成百科说明，规则必须通过场景、交易、战斗、对话或系统反馈体现。",
        ),
    },
    quality_checks=("等级经验一致", "收益代价闭环", "市场反应", "势力压迫", "信息可见性", "系统提示克制"),
)


XIANXIA = GenrePlugin(
    plugin_id="xianxia",
    name="修仙玄幻",
    keywords=("修仙", "玄幻", "灵根", "宗门", "境界", "功法", "法宝", "灵石", "渡劫", "秘境"),
    core_promises=(
        "读者期待境界突破、资源争夺、宗门压迫、因果伏笔和更高层世界逐步展开。",
        "力量体系必须有门槛、资源、心境或代价，不能无成本越阶碾压。",
    ),
    ledger_fields=("境界", "灵力", "功法", "法宝", "灵石", "宗门关系", "因果债", "秘境线索"),
    rulebook={
        "progression_rules": (
            "境界、功法、灵力和法宝必须前后一致，突破需要资源、机缘、心境或风险。",
            "越阶战斗必须有明确凭依，例如克制、地形、法宝、情报差或代价。",
        ),
        "economy_rules": (
            "丹药、灵石、材料和法宝要体现稀缺度、宗门控制和交易风险。",
        ),
        "quest_rules": (
            "秘境、试炼、宗门任务要有进入条件、竞争者、失败代价和阶段收获。",
        ),
        "faction_rules": (
            "宗门、家族、长老、同门和敌对势力要围绕资源、传承和面子做出反应。",
        ),
        "panel_rules": (
            "境界和功法信息要通过感知、战斗、传承或鉴定自然呈现。",
        ),
        "chapter_formula": (
            "每章围绕资源争夺、境界压力、关系压迫或因果伏笔形成小高潮。",
        ),
        "forbidden_breaks": (
            "禁止无代价顿悟，禁止境界体系混乱，禁止长辈无理由送核心资源。",
        ),
    },
    quality_checks=("境界一致", "资源代价", "宗门反馈", "因果伏笔", "越阶合理"),
)


URBAN = GenrePlugin(
    plugin_id="urban",
    name="都市现代",
    keywords=("都市", "职场", "豪门", "商业", "娱乐圈", "直播", "校园", "现代", "公司", "资本"),
    core_promises=(
        "读者期待现实压力下的资源翻盘、人际博弈、身份反差和阶段性打脸兑现。",
    ),
    ledger_fields=("金钱", "人脉", "事业阶段", "舆论", "身份秘密", "对手压力"),
    rulebook={
        "progression_rules": (
            "事业、财富、人脉和名声的提升必须有事件来源和现实阻力。",
        ),
        "economy_rules": (
            "合同、资金、流量、资源置换和商业利益必须符合现实逻辑。",
        ),
        "quest_rules": (
            "每个阶段目标要能落在项目、比赛、合同、舆论或关系节点上。",
        ),
        "faction_rules": (
            "公司、家族、平台、媒体和竞争者要对主角行动产生真实反馈。",
        ),
        "panel_rules": (
            "现实题材少用说明书旁白，优先通过对话、信息差和现场压力展示规则。",
        ),
        "chapter_formula": (
            "用现实困境开场，通过选择和博弈制造反转，结尾留下更高层对手或更大机会。",
        ),
        "forbidden_breaks": (
            "禁止无逻辑暴富，禁止所有人突然配合主角，禁止现实系统失真。",
        ),
    },
    quality_checks=("现实逻辑", "利益闭环", "反转可信", "人际压力", "舆论反馈"),
)


ROMANCE = GenrePlugin(
    plugin_id="romance",
    name="言情关系流",
    keywords=("言情", "甜宠", "虐恋", "婚恋", "总裁", "古言", "宫斗", "宅斗", "替身", "追妻", "女频"),
    core_promises=(
        "读者期待关系拉扯、情绪递进、误会与靠近交替发生，不能跳过情感成本。",
    ),
    ledger_fields=("关系阶段", "亲密度", "误会", "情绪债", "身份压力", "外部阻碍"),
    rulebook={
        "progression_rules": (
            "关系推进必须有情绪触发、行为证据和心理变化，不能突然相爱或突然决裂。",
        ),
        "economy_rules": (
            "婚约、家族、地位、资源和名声会影响关系选择，不能只当背景。",
        ),
        "quest_rules": (
            "每章要推进一个情绪节点：靠近、误会、试探、吃醋、保护、摊牌或退让。",
        ),
        "faction_rules": (
            "家庭、宫廷、职场、闺蜜、情敌和利益方要对关系产生压力。",
        ),
        "panel_rules": (
            "情绪变化优先通过动作、停顿、细节和潜台词呈现，少用直白解释。",
        ),
        "chapter_formula": (
            "开场给情绪钩子，中段制造选择和误读，结尾留下关系问题或身份压力。",
        ),
        "forbidden_breaks": (
            "禁止无铺垫强行误会，禁止关系跳级，禁止角色为虐而虐或为甜而降智。",
        ),
    },
    quality_checks=("情绪递进", "关系拉扯", "误会合理", "潜台词", "外部阻碍"),
)


SUSPENSE = GenrePlugin(
    plugin_id="suspense",
    name="悬疑推理",
    keywords=("悬疑", "推理", "案件", "侦探", "凶手", "线索", "诡计", "调查", "谜团"),
    core_promises=(
        "读者期待公平线索、持续反转、调查推进和真相逼近，不能靠临时乱编解谜。",
    ),
    ledger_fields=("案件时间线", "线索", "嫌疑人", "证据", "误导", "真相碎片"),
    rulebook={
        "progression_rules": (
            "每章必须推进调查、排除嫌疑、揭示新线索或改变读者判断。",
        ),
        "economy_rules": (
            "信息就是资源，关键线索的获得需要行动成本和风险。",
        ),
        "quest_rules": (
            "调查目标要具体，询问、取证、追踪、复盘都要留下可验证结果。",
        ),
        "faction_rules": (
            "嫌疑人、警方、受害者关系网和幕后势力都要有自保或误导动机。",
        ),
        "panel_rules": (
            "推理过程要展示证据链，不要用作者旁白直接宣布真相。",
        ),
        "chapter_formula": (
            "开场抛异常，中段追线索并反转判断，结尾给更危险或更矛盾的新证据。",
        ),
        "forbidden_breaks": (
            "禁止关键证据凭空出现，禁止凶手临时更换，禁止用巧合解决核心谜题。",
        ),
    },
    quality_checks=("公平线索", "时间线一致", "嫌疑动机", "反转可信", "钩子强度"),
)


RULES_MYSTERY = GenrePlugin(
    plugin_id="rules_mystery",
    name="规则怪谈",
    keywords=("规则怪谈", "怪谈", "禁忌", "规则", "污染", "异常", "诡异", "副本规则"),
    core_promises=(
        "读者期待规则逐条验证、禁忌代价、异常污染和规则背后真相逐步揭开。",
    ),
    ledger_fields=("已知规则", "可疑规则", "违规代价", "污染度", "安全区", "异常实体"),
    rulebook={
        "progression_rules": (
            "规则必须被验证、误读或反转，不能只作为气氛文本。",
        ),
        "economy_rules": (
            "安全信息、道具、时间和信任都是稀缺资源，使用必须有代价。",
        ),
        "quest_rules": (
            "每章要验证至少一条规则或发现一条规则的漏洞、代价或例外。",
        ),
        "faction_rules": (
            "异常实体、幸存者、管理员或幕后机制都应围绕规则产生行为逻辑。",
        ),
        "panel_rules": (
            "规则文本要简短、明确、可疑，正文通过行动验证其真实含义。",
        ),
        "chapter_formula": (
            "开场给禁忌，中段测试规则并付出代价，结尾揭示规则矛盾或更高层规则。",
        ),
        "forbidden_breaks": (
            "禁止规则随意改口，禁止没有代价的试错，禁止用梦境或幻觉轻易取消危机。",
        ),
    },
    quality_checks=("规则验证", "禁忌代价", "污染递进", "异常逻辑", "真相碎片"),
)


PLUGIN_REGISTRY: tuple[GenrePlugin, ...] = (
    GAME_WEBNOVEL,
    XIANXIA,
    URBAN,
    ROMANCE,
    SUSPENSE,
    RULES_MYSTERY,
)


def _project_text(project: NovelProject) -> str:
    return " ".join(
        [
            project.title,
            project.seed_outline,
            project.world_summary,
            project.current_focus,
            " ".join(project.author_constraints),
            json.dumps(project.world_blueprint, ensure_ascii=False),
        ]
    )


def select_genre_plugins(project: NovelProject, *, max_plugins: int = 2, min_score: int = 2) -> list[GenrePlugin]:
    text = _project_text(project)
    explicit_ids = project.world_blueprint.get("genre_plugin_ids") if isinstance(project.world_blueprint, dict) else None
    selected: list[GenrePlugin] = []
    if isinstance(explicit_ids, list):
        for plugin_id in explicit_ids:
            match = next((plugin for plugin in PLUGIN_REGISTRY if plugin.plugin_id == plugin_id), None)
            if match and match not in selected:
                selected.append(match)
            if len(selected) >= max_plugins:
                break
        if selected:
            return [GENERIC_WEBNOVEL, *selected]

    if len(selected) < max_plugins:
        scored: list[tuple[int, GenrePlugin]] = []
        for plugin in PLUGIN_REGISTRY:
            score = sum(1 for keyword in plugin.keywords if keyword and keyword in text)
            if score >= min_score:
                scored.append((score, plugin))
        for _, plugin in sorted(scored, key=lambda item: item[0], reverse=True):
            if plugin not in selected:
                selected.append(plugin)
            if len(selected) >= max_plugins:
                break

    return [GENERIC_WEBNOVEL, *selected]


def is_game_genre(text: str) -> bool:
    haystack = str(text or "")
    strong_tokens = ("网游", "VRMMO", "交易行", "爆率", "铜币", "game_webnovel")
    weak_tokens = ("游戏", "系统", "等级", "面板", "背包", "NPC", "玩家", "公会")
    if any(token in haystack for token in strong_tokens):
        return True
    return sum(1 for token in weak_tokens if token in haystack) >= 2


def merge_plugin_rulebooks(plugins: list[GenrePlugin]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {field: [] for field in RULEBOOK_FIELDS}
    for plugin in plugins:
        for field in RULEBOOK_FIELDS:
            for rule in plugin.rulebook.get(field, ()):
                if rule not in merged[field]:
                    merged[field].append(rule)
    return merged


def plugin_simulation_blueprint(plugins: list[GenrePlugin]) -> dict[str, object]:
    plugin_ids = {plugin.plugin_id for plugin in plugins}
    if "game_webnovel" not in plugin_ids:
        return {}
    return {
        "plugin_id": "game_webnovel",
        "opening_scene_templates": [
            {
                "id": "reality_entry",
                "location": "现实出租屋",
                "purpose": "交代现实职业、压力、登录动机和主角的谨慎计算。",
                "conflict": "现实压力迫使主角进入游戏试机会，但不能立刻解决现实债务。",
                "must_show": ["现实职业/技能来源", "为什么登录游戏"],
            },
            {
                "id": "character_creation",
                "location": "角色创建界面",
                "purpose": "建立游戏ID、职业选择和第一版角色面板。",
                "conflict": "职业选择必须解释后续战斗、装备和试炼路线。",
                "must_show": ["游戏ID", "职业选择", "角色面板", "生命/法力", "主武器或基础技能"],
            },
            {
                "id": "small_verification",
                "location": "灰烬村外",
                "purpose": "用低级怪物验证千倍爆率会把普通流程压短，让主角比别人更快完成任务或凑到下一步门槛。",
                "conflict": "收益让主角确认优势，但规模不足以惊动全服，旁人最多觉得他运气好或路线熟。",
                "must_show": ["低级怪物", "掉落反馈", "背包变化", "进度领先反馈"],
            },
            {
                "id": "single_npc_service",
                "location": "灰烬村",
                "purpose": "只轻量露出一个NPC服务入口或任务窗口。",
                "conflict": "NPC只提供岗位范围内的服务、报价、任务或门槛，不替主角解释全局规则。",
                "must_show": ["NPC地点或窗口", "服务内容", "价格/门槛"],
            },
            {
                "id": "chapter_1_next_step",
                "location": "灰烬村内",
                "purpose": "只作为章末下一步目标，不展开实际寄售、成交、到账或商人盘点。",
                "conflict": "下一步目标已经出现：主角知道这些掉落能让他更快交任务、换装备或摸到下一条路线，但第一章只收在谨慎决定上。",
                "must_show": ["下一步目标", "领先下一步"],
            },
        ],
        "conflict_ladders": {
            "chapter_1": ["现实压力", "职业选择", "领先验证", "下一步任务/装备门槛", "下一步目标"],
            "chapter_2": ["刷怪路线", "补给/耐久", "NPC任务前置", "装备或技能门槛", "普通玩家对比"],
            "chapter_3": ["资源点秩序", "职业试炼门槛", "路线竞争", "玩家传闻", "小高潮"],
        },
        "forbidden_conflict_modes": {
            "chapter_1": [
                "market_overreaction",
                "guild_omniscience",
                "real_identity_exposure",
                "coordinate_lock",
                "multi_npc_tour",
            ]
        },
        "visibility_matrix": {
            "trade_house": {
                "can_see": ["价格", "数量", "批次", "时间戳", "手续费", "匿名卖家ID"],
                "cannot_see": ["现实身份", "实时坐标", "隐藏天赋", "完整刷怪点", "真实姓名"],
            },
            "guild": {
                "can_see": ["论坛传闻", "资源点目击", "榜单变化", "重复交易模式", "NPC任务异常"],
                "cannot_see": ["隐藏天赋真相", "现实身份", "系统底层倍率", "交易行后台全量数据"],
            },
            "npc": {
                "can_see": ["岗位记录", "任务提交", "公开交易", "眼前行为"],
                "cannot_see": ["现实身份", "隐藏天赋", "玩家完整背包", "未公开意图"],
            },
        },
    }


def plugin_prompt_guide(plugins: list[GenrePlugin]) -> str:
    payload = [
        {
            "id": plugin.plugin_id,
            "name": plugin.name,
            "core_promises": list(plugin.core_promises),
            "ledger_fields": list(plugin.ledger_fields),
            "quality_checks": list(plugin.quality_checks),
        }
        for plugin in plugins
    ]
    return json.dumps(payload, ensure_ascii=False)
