from __future__ import annotations

import re
from typing import Any


GAME_CONTEXT_TOKENS = (
    "《天启之门》",
    "VRMMO",
    "网游",
    "游戏ID",
    "交易行",
    "公会",
    "灰烬村",
    "混沌之种",
    "千倍爆率",
    "game_webnovel",
)

NAMED_NPCS = ("灰烬村村长", "药剂师洛婶", "职业导师艾伦", "仓库管理员铁栓", "修理匠老葛")
NPC_ALIASES = {
    "灰烬村村长": ("灰烬村村长", "村长"),
    "药剂师洛婶": ("药剂师洛婶", "洛婶"),
    "职业导师艾伦": ("职业导师艾伦", "艾伦"),
    "仓库管理员铁栓": ("仓库管理员铁栓", "铁栓"),
    "修理匠老葛": ("修理匠老葛", "老葛"),
}
NPC_SERVICE_ACTIONS = (
    "说",
    "问",
    "提醒",
    "报价",
    "报出",
    "收购",
    "回收",
    "出售",
    "登记",
    "发布",
    "递",
    "接过",
    "收下",
    "修理",
    "开仓",
    "办理",
    "结算",
    "说明",
)
NPC_SERVICE_OBJECTS = (
    "任务",
    "药剂",
    "修理",
    "仓库",
    "寄售",
    "职业",
    "试炼",
    "声望",
    "价格",
    "库存",
    "材料",
    "回收",
    "推荐信",
)
NPC_NEGATED_SERVICE_MARKERS = (
    "没有去",
    "没有上前",
    "没有插队",
    "没有办理",
    "没有互动",
    "没有开口",
)
NPC_SYSTEM_SIGNPOST_MARKERS = (
    "系统自动推送",
    "任务面板",
    "系统提示",
    "自动推送",
    "面板",
)
NPC_SIGNPOST_ONLY_MARKERS = (
    "木牌",
    "今日试炼名额已满",
    "请明日再来",
    "跑职业大厅排队看",
    "那张冷脸",
    "老头子挑人",
)
NPC_PERSONAL_SCENE_MARKERS = (
    "柜台",
    "窗口",
    "药剂铺",
    "职业大厅",
    "村务大厅",
    "仓库",
    "铁匠铺",
    "修理铺",
    "开口",
    "抬头",
    "递",
    "接过",
    "压低声音",
    "盯着",
)
NEGATED_OVERREACH_PREFIXES = (
    "不",
    "未",
    "无",
    "没有",
    "不会",
    "不能",
    "无法",
    "无从",
    "缺乏",
    "并非",
    "不是",
    "尚未",
    "不应",
    "不得",
)
SAFE_OVERREACH_CONTEXT_MARKERS = (
    "脱敏",
    "隐藏",
    "匿名",
    "不显示",
    "不可见",
    "仅显示",
    "遮蔽",
    "屏蔽",
)
ASSERTIVE_OVERREACH_PREFIXES = (
    "显示",
    "暴露",
    "查到",
    "公开",
    "实时",
    "直接",
    "锁定",
    "立刻",
    "马上",
    "精确",
)


def web_game_review_rules() -> list[str]:
    """Prompt-ready rules shared by writer, reviewer and revision flows."""
    return [
        "网游身份：现实姓名和游戏ID必须分层。现实段落可写苏叶；进入游戏后优先写游戏ID夜烬，交易行、论坛、公会记录不得直接暴露现实姓名。",
        "交易行逻辑：低级材料匿名上架只能形成价格、数量、批次、时间戳等弱线索；不能单次交易就锁定坐标、现实身份、刷怪点或隐藏天赋。",
        "交易行口径：交易行可以提示大致行情、价格偏低/偏高、容易/较难成交；不要给出低于均价33%、预计成交速度、精确成交概率等上帝视角预测。",
        "市场尺度：十几个低级材料、几枚铜币这种小额噪音不能触发交易行检查、商人盯盘或公会注意；旁人最多觉得主角运气好，第一卷关注必须等稀有物、榜单、连续高频记录或多源证据叠加。",
        "成长爽点：千倍爆率的主要作用不是几颗材料本身，而是让主角更快完成任务、凑齐装备/技能门槛、提前摸到下一张地图或职业路线。",
        "开篇摩擦：补给、耐久、背包容量是新手阶段的主要成本，必须服务任务/装备/技能/路线领先，不要喧宾夺主。",
        "NPC服务：第2章起每章至少让一个命名NPC或NPC服务节点影响选择；第1章可以只露出柜台、价牌、队伍或下一章门槛，不强制完整办理业务。",
        "职业选择：第一章必须在登录、建号或职业大厅阶段写出游戏职业选择，并把职业写进角色面板；职业不能只在后文账本里突然出现。",
        "职业装备：现实职业和游戏职业必须分层；夜烬游戏路线固定为元素法师学徒/元素法师，主战应围绕法杖、法术和元素试炼，短剑只能是临时工具且必须解释限制。",
        "角色面板：第一章至少出现一次简短角色面板，包含游戏ID、等级、职业/路线、经验、生命/法力、主武器或基础技能、货币/背包中的关键项；不要为了凑面板反复展开力量/敏捷/体质等易漂移属性。",
        "事实锁定：同一章的首次刷怪目标、击杀提示、尸体/掉落材料必须指向同一种怪物；灰鼠、灰狼、西林狼不能在同一战斗里混用。",
        "面板一致：同一章内生命、法力、智力、敏捷、体质等面板数值不能无解释跳变；章节末角色群像必须继承正文最终面板。",
        "法师战斗：元素法师学徒的首次战斗必须体现基础法术、法力消耗或明确说明技能未解锁；不能全程只用法杖近战敲怪。",
        "正文语气：正文只能使用角色视角和世界内表达，禁止出现爽点、钩子、节奏、读者、网文规则、生成、审稿等作者/创作术语。",
        "表达方式：规则和系统必须藏进界面提示、人物动作、交易结果、玩家闲聊和主角判断里，少用服务节点、风控模型、低权重标签等产品/工程说明腔。",
        "装备账本：购买、替换、修理、耐久变化和关键消耗品必须进入章节摘要或账本，不能上一章买了装备、下一章当没发生。",
        "NPC设定：命名NPC重点出场必须交代地点、服务/价格或门槛、利益诉求/口吻和信息边界，不能只作为任务牌子。",
        "经济规则：没有世界档案明确设定前，不得把金币直接换算成人民币；新手阶段优先使用铜币、银币、材料和市场询价。",
        "公会压迫：公会只能通过重复模式、稀有物、资源点目击、NPC任务异常、榜单或多源风控逐步逼近，不能全知全能。",
        "背景预算：第一章只完整展开现实入口、游戏入口、首次验证和领先预期；NPC服务、论坛、公会追查和实际交易后移。",
        "信息可见：交易行、论坛、公会频道和NPC记录都有可见性边界；低级交易不能直接显示卖家坐标、实时位置、现实身份或隐藏天赋。",
    ]


def _has_game_context(body: str, event_plan: dict[str, Any], world_facts: list[str] | None) -> bool:
    plan_text = str(event_plan)
    facts_text = "\n".join(world_facts or [])
    return any(token in body or token in plan_text or token in facts_text for token in GAME_CONTEXT_TOKENS)


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _has_asserted_plain_term(text: str, term: str) -> bool:
    start = 0
    while True:
        index = text.find(term, start)
        if index < 0:
            return False
        prefix = text[max(0, index - 4):index]
        if not any(marker in prefix for marker in ("不", "没", "未", "禁止", "不要")):
            return True
        start = index + len(term)


def _first_chapter_anchor_issues(body: str) -> list[tuple[str, str, str]]:
    """Return hard continuity issues for the current web-game opening contract."""

    issues: list[tuple[str, str, str]] = []
    if "千倍爆率" not in body:
        issues.append(
            (
                "class_equipment",
                "第一章缺少长期金手指名“千倍爆率”；只写异常或×1000会让后续框架断裂。",
                "补出“千倍爆率”四个字，并让它和掉落判定×1000指向同一个可见结果。",
            )
        )
    if "混沌之种" not in body or "未解析" not in body:
        issues.append(
            (
                "class_equipment",
                "第一章缺少“混沌之种：未解析”钩子；长期金手指没有留下可承接入口。",
                "在首次掉落异常后补一个短面板：混沌之种：未解析，保持主角不知道真相。",
            )
        )
    if "底层协议校验通过" not in body:
        issues.append(
            (
                "class_equipment",
                "第一章缺少“底层协议校验通过”触发锚点，金手指显得像凭空出现。",
                "把旧头盔/接驳异常和底层协议校验通过连起来，再进入千倍爆率验证。",
            )
        )
    if "基础火球术" not in body:
        issues.append(
            (
                "class_equipment",
                "元素法师学徒的初始技能漂移：第一章没有写“基础火球术”。",
                "统一技能名为基础火球术；不要改成元素弹、微光弹或其他临时技能名。",
            )
        )
    if "元素弹" in body or "微光弹" in body:
        issues.append(
            (
                "class_equipment",
                "元素法师学徒的初始技能被改名，和长期职业账本冲突。",
                "把元素弹/微光弹改回基础火球术，并同步法力消耗和技能栏。",
            )
        )
    if re.search(r"(?:货币|铜币栏|钱袋|余额)[：: ]*15铜", body):
        issues.append(
            (
                "economy_rules",
                "第一章铜币账本漂移：没有写铜币获得过程，却出现15铜或类似余额。",
                "初始货币锁为0铜；没有铜币掉落或任务奖励时，章末仍应是0铜。",
            )
        )
    if "0铜" not in body and "零铜" not in body:
        issues.append(
            (
                "economy_rules",
                "第一章缺少初始0铜锚点，后续修理、寄存和交易门槛无法闭合。",
                "在角色面板或钱袋里写清货币0铜，并用它压住章末选择。",
            )
        )
    if ("二十七块六" in body or "27.60" in body) and not _has_any(body, ("余额", "银行卡", "可用")):
        issues.append(
            (
                "economy_rules",
                "现实金钱语义漂移：二十七块六必须是余额/可用钱，不是轻飘飘的最低还款额。",
                "把27.60写成银行卡余额或可用余额；信用卡最低还款只保留倒计时压力，不写成金额很低。",
            )
        )
    if not _has_any(body, ("任务进度", "任务门槛", "装备门槛", "技能门槛", "路线", "领先", "更快", "少跑", "早一步", "提前凑齐")):
        issues.append(
            (
                "progression_payoff",
                "第一章缺少进度领先钩子；千倍爆率不能只落在几颗材料上，必须让读者看到它会缩短任务、装备、技能或路线门槛。",
                "补一个下一步成长目标：例如清道夫委托少跑几趟、装备材料提前凑齐、技能前置更早满足或下一张地图路线更早打开。",
            )
        )
    actual_trade_terms = ("寄售成功", "上架成功", "成交", "到账", "手续费", "已售出")
    actual_trade_hit = any(_has_asserted_plain_term(body, term) for term in actual_trade_terms)
    if actual_trade_hit:
        issues.append(
            (
                "market_logic",
                "第一章提前完成交易闭环；当前目标是试清楚游戏里的路，不是把材料换成钱。",
                "删除寄售成功、成交、到账和手续费，只保留价格入口或下一章处理材料的念头。",
            )
        )
    return issues


def has_asserted_overreach(body: str, phrases: tuple[str, ...]) -> bool:
    """Return true only when an overreach phrase is asserted, not denied as a rule."""
    for phrase in phrases:
        start = 0
        while True:
            index = body.find(phrase, start)
            if index < 0:
                break
            prefix = body[max(0, index - 12):index]
            suffix = body[index + len(phrase):index + len(phrase) + 24]
            context = body[max(0, index - 16):index + len(phrase) + 24]
            is_denied_or_bounded = any(marker in prefix for marker in NEGATED_OVERREACH_PREFIXES) or any(
                marker in suffix for marker in SAFE_OVERREACH_CONTEXT_MARKERS
            )
            if not is_denied_or_bounded:
                if (
                    not phrase.startswith(ASSERTIVE_OVERREACH_PREFIXES)
                    and any(marker in context for marker in SAFE_OVERREACH_CONTEXT_MARKERS)
                ):
                    start = index + len(phrase)
                    continue
                return True
            start = index + len(phrase)
    return False


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


def _context_windows(text: str, token: str, *, radius: int = 90) -> list[str]:
    windows: list[str] = []
    for match in re.finditer(re.escape(token), text):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        windows.append(text[start:end])
    return windows


def _has_full_npc_service_scene(body: str, npc_name: str) -> bool:
    aliases = NPC_ALIASES.get(npc_name, (npc_name,))
    for alias in aliases:
        for window in _context_windows(body, alias, radius=60):
            if _has_any(window, NPC_SIGNPOST_ONLY_MARKERS):
                continue
            has_action = _has_any(window, NPC_SERVICE_ACTIONS)
            has_service_object = _has_any(window, NPC_SERVICE_OBJECTS)
            is_negated_service = _has_any(window, NPC_NEGATED_SERVICE_MARKERS)
            if has_action and has_service_object and not is_negated_service:
                is_task_panel_reference = _has_any(window, NPC_SYSTEM_SIGNPOST_MARKERS) and (
                    f"{alias}发布前置任务" in window or f"{alias}发布" in window and "任务" in window
                )
                if is_task_panel_reference:
                    continue
                if _has_any(window, NPC_SYSTEM_SIGNPOST_MARKERS) and not _has_any(window, NPC_PERSONAL_SCENE_MARKERS):
                    continue
                return True
    return False


def _full_service_npcs(body: str) -> list[str]:
    return [npc for npc in NAMED_NPCS if _has_full_npc_service_scene(body, npc)]


def _invalid_currency_displays(body: str) -> list[str]:
    invalid: list[str] = []
    for match in re.finditer(r"\d+\s*金币\s*(?P<silver>\d+)\s*银币\s*(?P<copper>\d+)\s*铜币", body):
        silver = int(match.group("silver"))
        copper = int(match.group("copper"))
        if silver >= 100 or copper >= 100:
            invalid.append(match.group(0))
    return invalid[:3]


_CN_NUMERAL_VALUES = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_count(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value in _CN_NUMERAL_VALUES:
        return _CN_NUMERAL_VALUES[value]
    if "十" in value:
        left, _, right = value.partition("十")
        tens = _CN_NUMERAL_VALUES.get(left, 1 if left == "" else None)
        ones = _CN_NUMERAL_VALUES.get(right, 0 if right == "" else None)
        if tens is not None and ones is not None:
            return tens * 10 + ones
    return None


def _material_inventory_issues(body: str) -> list[str]:
    """Catch deterministic inventory contradictions that LLM review often misses."""
    events: list[tuple[int, str, int, str]] = []
    count_pattern = r"(?P<count>\d+|[一二两三四五六七八九十]{1,3})"
    material_pattern = r"(?:灰狼)?毒腺"
    event_patterns = [
        ("gain", rf"获得[：:][^。】\n]*{material_pattern}\s*[×xX*＊]\s*{count_pattern}"),
        ("set", rf"背包里[^。】\n]*(?:多了|有了|装着)\s*{count_pattern}\s*份[^。】\n]*{material_pattern}"),
        ("set", rf"背包[：:][^。】\n]*{material_pattern}\s*[×xX*＊]\s*{count_pattern}"),
        ("spend", rf"上架成功[：:][^。】\n]*{material_pattern}\s*[×xX*＊]\s*{count_pattern}"),
        ("spend", rf"(?:卖出|出售|寄售|挂单)[^。】\n]*{material_pattern}\s*[×xX*＊]\s*{count_pattern}"),
        ("spend", rf"(?:递过去|提交|交给|交了|回收)[^。】\n]*{count_pattern}\s*份[^。】\n]*{material_pattern}"),
        ("spend", rf"{count_pattern}\s*份[^。】\n]*{material_pattern}[^。】\n]*(?:递过去|提交|交给|交了|回收)"),
    ]
    for kind, pattern in event_patterns:
        for match in re.finditer(pattern, body):
            count = _parse_count(match.group("count"))
            if count is None:
                continue
            events.append((match.start(), kind, count, match.group(0)))
    events.sort(key=lambda item: item[0])

    balance: int | None = None
    issues: list[str] = []
    for _, kind, count, text in events:
        if kind == "gain":
            balance = (balance or 0) + count
            continue
        if kind == "set":
            balance = count
            continue
        if kind == "spend":
            if balance is not None and count > balance:
                issues.append(f"毒腺支出超过库存：当前推算库存{balance}份，但正文写成{text}。")
            if balance is not None:
                balance -= count

    return issues[:3]


def _trade_payout_issues(body: str) -> list[str]:
    """Catch obvious market-accounting contradictions in low-level material sales."""
    issues: list[str] = []
    total_match = re.search(r"([一二两三四五六七八九十\d]{1,4})\s*枚[^。\n]{0,8}毒腺", body)
    price_match = re.search(r"单价(?:填)?\s*(\d+)\s*铜", body)
    final_matches = re.findall(r"(?:数字停在|货币：)\s*(\d+)\s*铜", body)
    if total_match and price_match and final_matches:
        total = _parse_count(total_match.group(1))
        price = int(price_match.group(1))
        final_balance = int(final_matches[-1])
        if total is not None:
            gross = total * price
            # Allow fees and small wording differences, but not an order-of-magnitude ledger break.
            if gross >= 100 and final_balance < int(gross * 0.8):
                issues.append(
                    f"交易到账账本不一致：正文写{total}枚毒腺按{price}铜寄售，毛收入约{gross}铜，但最终余额只有{final_balance}铜。"
                )

    progress_match = re.search(r"任务进度[：:]\s*(\d+)\s*/\s*(\d+)", body)
    reserved_ten = re.search(r"(?:划出|提交|放进任务栏)[^。\n]{0,12}(?:十|10)\s*枚", body)
    if reserved_ten and progress_match and int(progress_match.group(1)) < 10 <= int(progress_match.group(2)):
        issues.append("任务材料账本不一致：正文写已划出/提交10枚毒腺，但后文任务进度仍低于10/10。")

    return issues[:3]


def _precise_market_prediction_issues(body: str) -> list[str]:
    issues: list[str] = []
    precise_patterns = (
        r"低于均价\s*\d+\s*%",
        r"高于均价\s*\d+\s*%",
        r"预计成交速度[：:]\s*\S+",
        r"成交概率[：:]\s*\d+\s*%",
        r"预计\d+分钟内成交",
    )
    for pattern in precise_patterns:
        match = re.search(pattern, body)
        if match:
            issues.append(f"交易行提示过于精确：{match.group(0)}。")
            break
    return issues


def _has_class_equipment_conflict(body: str) -> bool:
    mage_route = _has_any(body, ("元素法师", "法师学徒", "基础火球术", "元素亲和", "法力", "元素回廊"))
    if not mage_route or "短剑" not in body:
        return False
    temporary_markers = ("备用", "临时", "工具", "不得近战", "只能应急", "不作为主战")
    protagonist_sword_patterns = (
        r"(?:夜烬|苏叶|他)[^。！？\n]{0,80}(?:抽出|拔出|握紧|收起|用|买了|换了一把|修理|递给|扣住)[^。！？\n]{0,40}短剑",
        r"短剑[^。！？\n]{0,80}(?:刺|劈|斩|收回|压在掌心|剑柄)",
        r"铁质短剑[^。！？\n]{0,80}(?:重量|耐久|掌心|剑柄)",
    )
    for pattern in protagonist_sword_patterns:
        for match in re.finditer(pattern, body):
            window = body[max(0, match.start() - 80) : match.end() + 80]
            if not _has_any(window, temporary_markers):
                return True
    return False


def _monster_consistency_issues(body: str) -> list[str]:
    issues: list[str] = []
    mouse_surface = _has_any(body, ("灰鼠", "灰鼠坡", "灰鼠毒腺", "灰鼠皮", "击杀灰鼠"))
    wolf_combat_surface = _has_any(
        body,
        (
            "狼爪",
            "狼嚎",
            "狼尸",
            "狼的侧颈",
            "狼的肋骨",
            "狼的鼻梁",
            "砸狼",
            "灰狼生命",
            "击杀灰狼",
            "灰狼倒",
        ),
    )
    if mouse_surface and wolf_combat_surface:
        issues.append("本章怪物对象不一致：灰鼠坡/击杀灰鼠与狼爪、狼尸、狼的部位描写混用。")

    explicit_kills = set(re.findall(r"击杀(灰鼠|灰狼|西林狼|狼)", body))
    if len(explicit_kills) >= 2:
        issues.append(f"本章击杀提示混用多个怪物：{'、'.join(sorted(explicit_kills))}。")
    return issues[:2]


def _panel_value_drift_issues(body: str) -> list[str]:
    keys = ("生命", "法力", "智力", "敏捷", "体质", "力量", "精神")
    drift: list[str] = []
    hp_change_explained = _has_any(body, ("受伤", "抓破", "擦过", "血量", "生命下降", "生命值下降", "发麻", "疼痛"))
    mp_change_explained = _has_any(body, ("施法", "法力消耗", "法力被", "法力池", "火苗", "火球", "元素弹", "冷却"))
    for key in keys:
        values = re.findall(rf"{key}\s*[：:]\s*(\d+\s*/\s*\d+|\d+)", body)
        normalized: list[str] = []
        for value in values:
            cleaned = value.replace(" ", "")
            if cleaned not in normalized:
                normalized.append(cleaned)
        if len(normalized) >= 2:
            if key == "生命" and hp_change_explained:
                continue
            if key == "法力" and mp_change_explained:
                continue
            drift.append(f"{key}{'/'.join(normalized[:3])}")
    if drift:
        return [f"角色面板数值前后不一致且缺少解释：{'、'.join(drift[:5])}。"]
    return []


def _mage_staff_melee_without_spell_reason(body: str) -> bool:
    mage_route = _has_any(body, ("元素法师学徒", "元素法师", "法师学徒", "法力", "元素回廊"))
    staff_melee = _has_any(body, ("杖尖砸", "杖尖对准", "杖尾压", "杖头磕", "法杖砸", "法杖敲", "杖尾", "杖头"))
    spell_text = body.replace("没有施法", "").replace("未施法", "").replace("没有用法术", "").replace("不用法术", "")
    spell_surface = _has_any(spell_text, ("火球", "火苗", "电弧", "冰箭", "施法", "吟唱", "法术", "法力消耗", "魔法弹"))
    reason_surface = _has_any(body, ("技能未解锁", "尚未解锁", "无法施法", "法力不足", "冷却", "只能应急", "距离太近"))
    return mage_route and staff_melee and not (spell_surface or reason_surface)


def _has_equipment_change_without_ledger(body: str) -> bool:
    equipment_change = _has_any(
        body,
        (
            "买了",
            "购买",
            "换上",
            "装备上",
            "修理",
            "耐久恢复",
            "耐久已降至",
            "耐久度",
            "武器栏",
            "装备栏",
        ),
    ) and _has_any(body, ("法杖", "短剑", "护甲", "布衣", "绷带", "磨刀石", "生命药剂", "法力药水", "抗毒药剂"))
    ledger_surface = _has_any(body, ("当前装备", "装备栏", "武器栏", "背包", "耐久度", "账本", "当前状态"))
    return equipment_change and not ledger_surface


def _has_defined_npc_scene(body: str, npc_name: str) -> bool:
    aliases = NPC_ALIASES.get(npc_name, (npc_name,))
    location_terms = {
        "灰烬村村长": ("村务大厅", "灰烬村广场", "广场", "村长"),
        "药剂师洛婶": ("药剂铺", "柜台", "火漆印", "解毒剂", "毒腺"),
        "职业导师艾伦": ("职业大厅", "回廊", "棱镜", "试炼", "元素"),
        "仓库管理员铁栓": ("仓库", "邮件", "流水", "保管费", "寄存"),
        "修理匠老葛": ("铁匠铺", "修理铺", "铁砧", "耐久", "修理"),
    }.get(npc_name, ())
    agenda_or_boundary_terms = (
        "只知道",
        "看不到",
        "不能",
        "不会",
        "无法",
        "只收",
        "不收",
        "规矩",
        "压价",
        "报价",
        "砸盘",
        "利润",
        "库存",
        "材料",
        "价格",
        "门槛",
        "登记",
        "记录",
        "不问",
        "信息",
        "边界",
        "品质",
        "失败",
        "代价",
    )
    for alias in aliases:
        start = body.find(alias)
        while start != -1:
            window = body[max(0, start - 120) : start + 260]
            has_location = _has_any(window, location_terms)
            has_service = _has_any(window, NPC_SERVICE_ACTIONS) and _has_any(window, NPC_SERVICE_OBJECTS)
            has_agenda_or_boundary = _has_any(window, agenda_or_boundary_terms)
            if has_location and has_service and has_agenda_or_boundary:
                return True
            start = body.find(alias, start + len(alias))
    return False


def review_web_game_chapter(
    *,
    chapter_number: int,
    body: str,
    event_plan: dict[str, Any] | None = None,
    world_facts: list[str] | None = None,
) -> dict[str, Any]:
    """Review web-game fiction rules that are independent from general prose quality."""
    event_plan = event_plan or {}
    scores = {
        "identity_layer": 8,
        "market_logic": 8,
        "npc_service": 8,
        "economy_rules": 8,
        "class_equipment": 8,
        "guild_pressure": 8,
        "background_budget": 8,
        "information_visibility": 8,
        "prose_surface": 8,
    }
    issues: list[str] = []
    revision_plan: list[str] = []

    if not _has_game_context(body, event_plan, world_facts):
        return {"pass": True, "scores": scores, "issues": issues, "revision_plan": revision_plan}

    facts_text = "\n".join(world_facts or [])
    plan_text = str(event_plan)
    combined = "\n".join([body, plan_text, facts_text])
    requires_opening_anchors = chapter_number == 1 and _has_any(
        "\n".join([plan_text, facts_text]),
        ("长期核心", "底层协议校验通过", "初始0铜", "余额27.60", "基础火球术、初始0铜"),
    )
    if requires_opening_anchors:
        for score_key, issue, plan in _first_chapter_anchor_issues(body):
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key=score_key,
                issue=issue,
                plan=plan,
            )
    gray_wolf_planned = "灰狼" in "\n".join([plan_text, facts_text])
    if gray_wolf_planned:
        wrong_gray_mouse_terms = [term for term in ("灰鼠", "灰鼠坡", "灰鼠毒腺", "鼠皮", "毒囊") if term in body]
        if wrong_gray_mouse_terms:
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="prose_surface",
                issue=f"推演事实漂移：计划锁定灰狼/灰狼坡/灰狼毒腺，正文却出现 {'、'.join(wrong_gray_mouse_terms[:5])}。",
                plan="把本章首次验证对象统一改回灰狼，地点统一灰狼坡，材料统一灰狼毒腺和粗糙狼皮；不要沿用旧版灰鼠模板。",
            )

    stray_background_terms = [term for term in ("前世", "穿越", "靶向药", "重病", "住院费", "网贷") if term in body]
    if chapter_number == 1 and stray_background_terms and not _has_any(facts_text, stray_background_terms):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="background_budget",
            issue=f"现实背景擅自扩写：正文新增 {'、'.join(stray_background_terms[:5])}，但世界档案没有这些事实。",
            plan="删除未授权的前世、穿越、疾病、网贷等背景；现实压力只写既有房租、宽带、信用卡最低还款和工作技能来源。",
        )

    boundary_chapter = chapter_number == 1 and _has_any(
        combined,
        ("确认边界", "边界章", "验证边界", "试探边界", "不是赚钱", "不换钱", "not money", "boundary"),
    )
    if boundary_chapter:
        drift_terms = [
            term
            for term in ("寄售", "成交", "到账", "手续费", "换钱", "换人民币")
            if _has_asserted_plain_term(body, term)
        ]
        if drift_terms:
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="market_logic",
                issue=f"边界章目标漂移：第一章应确认规则边界，不应进入交易/变现正文，出现 {'、'.join(drift_terms[:5])}。",
                plan="把寄售、成交、到账、手续费、换钱和交易行操作后移；第一章只写登录、职业、一次低级验证、背包/血蓝/耐久代价和下一章材料处理条件。",
            )

    game_id_markers = ("游戏ID", "游戏昵称", "角色名", "网名", "ID：", "ID:", "夜烬", "铁算盘")
    if chapter_number == 1 and not _has_any(combined, game_id_markers):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="identity_layer",
            issue="第一章缺少游戏ID/网名身份层；网游文需要区分现实姓名和游戏内ID。",
            plan="在登录、建号或角色面板里补出苏叶的游戏ID“夜烬”，游戏内交易、论坛和公会观察优先称呼夜烬。",
        )

    class_choice_markers = (
        "职业选择",
        "选择职业",
        "职业栏",
        "职业：",
        "职业路线",
        "法师学徒",
        "元素法师学徒",
        "元素法师",
        "职业大厅",
        "职业导师",
        "艾伦",
    )
    panel_markers = ("角色面板", "角色状态", "个人面板", "属性面板", "状态面板", "等级：", "经验：")
    needs_class_panel = chapter_number == 1 and (
        _has_any(facts_text, ("职业规则", "职业选择", "角色面板", "职业栏", "元素法师"))
        or _has_any(plan_text, ("职业选择", "角色面板", "职业栏", "元素法师"))
    )
    if needs_class_panel and not _has_any(body, class_choice_markers):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="class_equipment",
            issue="第一章缺少职业选择/职业路线确认；网游开篇需要让读者看到夜烬为什么走元素法师学徒路线。",
            plan="在登录建号、职业大厅或角色创建界面补出职业选择：夜烬选择元素法师学徒，并交代该选择对应法杖、基础法术、10级元素回廊试炼门槛。",
        )
    if needs_class_panel and not (_has_any(body, panel_markers) and _has_any(body, ("职业", "法师", "等级", "经验"))):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="class_equipment",
            issue="第一章缺少带职业栏的角色面板；当前等级、职业、经验、主武器/基础技能没有形成可追踪账本。",
            plan="补一个克制的角色面板，包含游戏ID夜烬、等级1、职业元素法师学徒、经验0/100、新手法杖、基础火球术或未解锁技能、初始货币/背包。",
        )
    if needs_class_panel and _has_any(body, panel_markers) and not _has_any(
        body,
        ("属性", "力量", "体质", "敏捷", "智力", "精神", "幸运", "生命", "法力", "HP", "MP"),
    ):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="class_equipment",
            issue="角色面板缺少生命/法力或战斗成本；只有等级、职业和背包，读者无法判断首次战斗能消耗什么。",
            plan="在角色面板中补入生命/法力、主武器和基础技能即可；不要反复展开力量、体质、敏捷等扩展属性，避免前后数值漂移。",
        )

    meta_terms = ("爽点", "节奏", "读者", "网文规则", "审稿", "质量报告", "剧情需要")
    if _has_any(body, meta_terms):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="prose_surface",
            issue="正文出现作者/创作层术语，破坏沉浸感，读起来不像角色正在经历事件。",
            plan="删除爽点、钩子、节奏、读者、生成、审稿等出戏词，改成世界内表达，例如收益到账、风险浮现、下一步必须更隐蔽。",
        )

    real_name_leak = (
        _has_any(body, ("交易行", "论坛", "公会", "玩家频道", "寄售", "私聊"))
        and "苏叶" in body
        and not _has_any(body, ("夜烬", "游戏ID", "网名"))
    )
    if real_name_leak:
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="identity_layer",
            issue="游戏内场景混用了现实姓名和游戏ID；交易行、论坛、公会记录不应直接暴露苏叶的现实姓名。",
            plan="把游戏内称呼改为夜烬，现实姓名苏叶只留在出租屋、现实回忆或旁白解释里。",
        )

    low_tier_market = _has_any(body, ("低级材料", "狼皮", "狼牙", "毒腺", "草药", "铜币", "银币", "匿名上架", "匿名寄售"))
    single_trade_overclaim = _has_any(
        body,
        (
            "单次交易",
            "只看了一笔",
            "一笔交易就",
            "第一笔交易就",
        ),
    )
    direct_tracking_overreach = has_asserted_overreach(
        body,
        (
            "立刻锁定坐标",
            "马上锁定坐标",
            "精确坐标",
            "锁定坐标",
            "锁定他的坐标",
            "锁定现实身份",
            "锁定刷怪点",
            "知道混沌之种",
            "已经知道混沌之种",
        ),
    )
    if low_tier_market and (direct_tracking_overreach or (single_trade_overclaim and "锁定" in body)):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="market_logic",
            issue="低级材料交易被写成单次上架就锁定坐标、现实身份、刷怪点或隐藏天赋，追踪强度不符合网游交易行逻辑。",
            plan="改成弱线索递进：价格波动、数量批次、时间戳、商人脚本、资源点目击和NPC任务异常多源汇总后才逐步缩小范围。",
        )
    micro_trade = _has_any(body, ("十几个低级材料", "几枚铜币", "小额材料", "小额交易"))
    micro_overreaction = _has_any(body, ("交易行检查", "风控记录", "商人盯上", "公会也开始注意", "白袍公会也开始注意"))
    if micro_trade and micro_overreaction and not _has_any(body, ("没有触发风控", "没有公会注意", "普通行情")):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="market_logic",
            issue="小额低级材料交易反应过度：十几个低级材料、几枚铜币只应是普通噪音，不能立刻触发交易行检查、商人盯盘或公会注意。",
            plan="把外部反应降级为普通流水或匿名记录，把本章压力改回补给、耐久、背包和下一步验证成本。",
        )

    visibility_surface = _has_any(body, ("交易行", "寄售", "论坛", "公会频道", "玩家频道", "NPC记录", "仓库流水", "寄售流水"))
    visibility_overreach = has_asserted_overreach(
        body,
        (
            "显示卖家坐标",
            "卖家坐标",
            "显示坐标",
            "实时位置",
            "公开坐标",
            "显示真人身份",
            "显示现实身份",
            "暴露现实身份",
            "查到现实身份",
            "直接显示身份",
            "直接显示混沌之种",
            "显示隐藏天赋",
        ),
    )
    if visibility_surface and visibility_overreach:
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="information_visibility",
            issue="信息可见性越界：交易行、论坛、公会频道或NPC记录不应直接显示卖家坐标、实时位置、现实身份或隐藏天赋。",
            plan="把可见信息降级为价格、数量、批次、时间戳、手续费、匿名流水、资源点目击或论坛传闻；坐标和身份只能通过后续多源线索逐步逼近。",
        )

    fixed_exchange_rate_forbidden = "不得把金币直接换算成人民币" in facts_text or "汇率" in facts_text
    explicit_exchange_rate = _has_any(facts_text, ("官方兑换", "黑市行情", "稳定汇率", "金币=人民币"))
    invented_exchange_rate = re.search(
        r"(?:1|一)\s*金(?:币)?\s*(?:=|等于|约等于|能换|可以换|折合)\s*\d+(?:\.\d+)?\s*(?:元|人民币|RMB)",
        body,
    )
    if invented_exchange_rate and (fixed_exchange_rate_forbidden or not explicit_exchange_rate):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="economy_rules",
            issue="章节写死了金币与人民币汇率，但世界档案没有明确官方兑换或黑市行情。",
            plan="删除固定现实汇率，改写为开服期行情未稳、玩家询价、游戏内铜币/银币/金币价格或市场猜测。",
        )

    invalid_currency = _invalid_currency_displays(body)
    if invalid_currency:
        examples = "、".join(invalid_currency)
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="economy_rules",
            issue=f"章节货币显示未按 1金币=100银币=10000铜币 归一，出现 {examples} 这类余额。",
            plan="重算并归一显示余额：铜币满100应进位为银币，银币满100应进位为金币；同时同步修正交易到账、支出和剩余金额。",
        )

    material_issues = _material_inventory_issues(body)
    if material_issues:
        examples = "；".join(material_issues)
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="economy_rules",
            issue=f"章节材料账本不闭合：{examples}",
            plan="重写本章毒腺等关键材料流水：先明确获得总数，再分别扣除寄售、提交任务、回收或保留库存；最终面板中的背包数量必须与正文流水一致。",
        )
    payout_issues = _trade_payout_issues(body)
    if payout_issues:
        examples = "；".join(payout_issues)
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="economy_rules",
            issue=f"章节交易/任务账本存在硬性算术矛盾：{examples}",
            plan="重算毒腺库存、任务预留/提交数量、寄售数量、手续费、到账金额和最终余额；任务进度与货币余额必须能从正文流水推出来。",
        )

    precise_market_issues = _precise_market_prediction_issues(body)
    if precise_market_issues:
        examples = "；".join(precise_market_issues)
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="market_logic",
            issue=examples,
            plan="把交易行精确预测改成模糊行情提示，例如价格偏低、容易出手、同类材料询价变多；不要写低于均价百分比、预计成交速度或成交概率。",
        )

    monster_issues = _monster_consistency_issues(body)
    if monster_issues:
        examples = "；".join(monster_issues)
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="prose_surface",
            issue=f"怪物对象连续性错误：{examples}",
            plan="统一本章首次验证目标：如果地点是灰鼠坡，发现、战斗、击杀提示、尸体、掉落和NPC口径都改成灰鼠；不要混入狼爪、狼尸或灰狼材料。",
        )

    panel_drift_issues = _panel_value_drift_issues(body)
    if panel_drift_issues:
        examples = "；".join(panel_drift_issues)
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="class_equipment",
            issue=examples,
            plan="统一角色创建面板与章末面板；若生命、法力或属性变化，必须在正文写清楚升级、装备、受伤、消耗或异常惩罚的原因。",
        )

    if _has_class_equipment_conflict(body):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="class_equipment",
            issue="职业与装备路线不一致：夜烬是元素法师学徒/元素法师路线，却被写成短剑主战或修剑主战。",
            plan="把战斗核心改回法杖、基础火球术、元素亲和和试炼门槛；短剑只能作为临时备用工具，并写清它不替代法师路线。",
        )
    if _mage_staff_melee_without_spell_reason(body):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="class_equipment",
            issue="法师战斗方式不成立：元素法师学徒全程用法杖物理敲击，没有基础法术、法力消耗或技能未解锁解释。",
            plan="改写首次战斗：至少写出基础火苗/火球术/元素弹的一次施放、命中、冷却或法力消耗；如果不用法术，必须明确技能未解锁或距离太近只能应急。",
        )

    if _has_equipment_change_without_ledger(body):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="class_equipment",
            issue="章节出现装备购买、修理、耐久或消耗品变化，但没有同步交代当前装备/背包/耐久账本。",
            plan="补写当前装备状态，例如武器、护甲、耐久、消耗品数量和支出，并让章节摘要或ledger_updates记录这些变化。",
        )

    needs_npc = chapter_number in (2, 3) or (chapter_number > 1 and (bool(event_plan.get("npc_beats")) or "NPC" in facts_text))
    service_npcs = _full_service_npcs(body)
    if needs_npc and not service_npcs:
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="npc_service",
            issue="网游章节缺少命名NPC的服务、任务、价格、仓储、修理或职业门槛，世界像只有玩家和系统。",
            plan="补入至少一个命名NPC服务节点，例如灰烬村村长、药剂师洛婶、职业导师艾伦、仓库管理员铁栓或修理匠老葛，并让其服务边界影响本章选择。",
        )
    elif service_npcs and not any(_has_defined_npc_scene(body, npc) for npc in service_npcs):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="npc_service",
            issue="命名NPC出场缺少完整设定：需要交代地点、服务/价格或门槛、利益诉求/口吻和信息边界。",
            plan="补足NPC场景，让NPC以药剂、仓储、修理、职业试炼或村务规则影响主角选择，并说明NPC只能看到哪些记录、不能知道隐藏天赋。",
        )

    if chapter_number == 1:
        if len(service_npcs) > 1:
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="background_budget",
                issue="第一章背景预算超载：多个命名NPC服务节点被完整展开，容易把黄金三章写成设定巡礼。",
                plan="第一章删到0-1个轻量NPC入口；命名NPC完整服务、职业大厅、仓库和修理铺等完整场景移到第2-3章。",
            )

    guild_omniscience = _has_any(body, ("公会会长亲自", "全服通缉", "直接知道真相", "立刻知道真相", "已经知道混沌之种"))
    if chapter_number <= 3 and guild_omniscience:
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="guild_pressure",
            issue="开篇公会压力越级：公会不能在前三章直接知道隐藏天赋真相或由会长亲自下场。",
            plan="把公会反应降级为外围成员、商人账本、论坛传闻或资源点秩序试探，真相只能通过多源线索逐步逼近。",
        )

    return {
        "pass": all(score >= 8 for score in scores.values()) and not issues,
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
    }
