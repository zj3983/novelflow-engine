from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from typing import Any

from packages.story_core.generation_progress import report_generation_progress
from packages.story_core.progression_lead_review import review_progression_lead
from packages.story_core.web_game_economy import first_chapter_market_exchange_authorized
from packages.story_core.web_game_review import has_asserted_overreach, review_web_game_chapter


_FORBIDDEN_REAL_CURRENCY_NAME = "\u4eba\u6c11\u5e01"


def _has_completed_term(text: str, term: str) -> bool:
    future_or_negated = (
        "\u5c06", "\u6ca1", "\u672a", "\u4e0d\u8981", "\u4e0d\u80fd", "\u63a5\u4e0b\u6765",
        "\u4e0b\u4e00\u6b65", "\u51c6\u5907", "\u6253\u7b97", "\u8ba1\u5212", "\u8981\u5148", "\u4e4b\u540e\u518d",
    )
    start = 0
    while True:
        index = text.find(term, start)
        if index < 0:
            return False
        prefix = text[max(0, index - 18) : index]
        if not any(marker in prefix for marker in future_or_negated):
            return True
        start = index + len(term)


def _review_exception_result(name: str, exc: Exception) -> dict[str, Any]:
    reviewer_name = name.removesuffix("_review")
    return {
        "reviewer": f"{name}/exception",
        "pass": False,
        "scores": {f"{name}_exception": 4},
        "issues": [f"\u5ba1\u7a3f\u5668{reviewer_name}\u5f02\u5e38\uff1a{exc}"],
        "revision_plan": [f"\u4fee\u590d\u5ba1\u7a3f\u5668{reviewer_name}\u5f02\u5e38\u540e\u91cd\u65b0\u5ba1\u6838\u3002"],
    }


def _merge_subreview(
    *,
    prefix: str,
    review: dict[str, Any],
    scores: dict[str, int],
    issues: list[str],
    revision_plan: list[str],
) -> None:
    for key, score in review.get("scores", {}).items():
        scores[f"{prefix}_{key}"] = score
    for issue in review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)


def _build_game_world_state_review(
    issues: list[str], revision_plan: list[str]
) -> dict[str, Any]:
    surfaces: dict[str, dict[str, Any]] = {}

    def add(surface: str, issue: str, patch: str) -> None:
        entry = surfaces.setdefault(
            surface,
            {"surface": surface, "issues": [], "suggested_patch": patch},
        )
        if issue not in entry["issues"]:
            entry["issues"].append(issue)

    for issue in issues:
        text = str(issue)
        if any(token in text for token in ("汇率", _FORBIDDEN_REAL_CURRENCY_NAME, "金币", "银币", "铜币", "价格", "材料", "交易行", "市场", "手续费")):
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

    patch_plan = [str(entry["suggested_patch"]) for entry in surfaces.values()]
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


def review_game_chapter(*, context: Any) -> dict[str, Any]:
    chapter_number = int(context["chapter_number"])
    body = str(context["body"])
    event_plan = context.get("event_plan") or {}
    world_facts = context.get("world_facts") or []
    simulation_plan = context.get("simulation_plan") or {}
    protagonist_aliases = context.get("protagonist_aliases") or ()
    character_names = context.get("character_names") or ()

    facts_text = "\n".join(world_facts)
    plan_text = json.dumps(event_plan, ensure_ascii=False)
    game_context = True
    project_specific_game_context = any(
        token in f"{facts_text}\n{plan_text}\n{body}"
        for token in ("千倍爆率", "混沌之种", "清道夫委托", "夜烬", "元素回廊")
    )
    chapter_one_trade_payoff = (
        chapter_number == 1
        and first_chapter_market_exchange_authorized(event_plan, world_facts)
    )
    issues: list[str] = []
    revision_plan: list[str] = []
    scores = {
        "background_integration": 8,
        "protagonist_motivation": 8,
        "genre_rules": 8,
        "chapter_ending_hook": 8,
        "continuity": 8,
        "simulation_plan_alignment": 8,
    }

    def require(label: str, keywords: tuple[str, ...], issue: str, plan: str) -> None:
        if not any(keyword in body for keyword in keywords):
            scores[label] = min(scores[label], 5)
            issues.append(issue)
            revision_plan.append(plan)

    if chapter_one_trade_payoff:
        anchor_text = f"{plan_text}\n{facts_text}"
        expected_arrivals = re.findall(r"到账\s*[：:]?\s*(\d+(?:\.\d{1,2})?)\s*元", anchor_text)
        body_arrivals = re.findall(r"(\d+(?:\.\d{1,2})?)\s*元", body)

        def normalized_amounts(values: list[str]) -> set[Decimal]:
            normalized: set[Decimal] = set()
            for value in values:
                try:
                    normalized.add(Decimal(value))
                except InvalidOperation:
                    continue
            return normalized

        missing_amounts = normalized_amounts(expected_arrivals) - normalized_amounts(body_arrivals)
        if missing_amounts:
            expected_text = "、".join(f"{amount:.2f}元" for amount in sorted(missing_amounts))
            scores["continuity"] = min(scores["continuity"], 4)
            issues.append(f"大纲金额不一致：正文必须保留明确到账金额{expected_text}。")
            revision_plan.append(
                f"把官方兑换后的现实账户到账金额改为{expected_text}，并同步核对支付急账后的现实余额；不要自行改价或手续费。"
            )
        opening_matches = re.findall(r"最后\s*(\d+(?:\.\d{1,2})?)\s*元", anchor_text)
        if opening_matches and not any(f"{value}元" in body[:1200] for value in opening_matches):
            expected_opening = f"{opening_matches[0]}元"
            scores["continuity"] = min(scores["continuity"], 4)
            issues.append(f"开篇余额不一致：正文开篇必须保留{expected_opening}。")
            revision_plan.append(f"把登录游戏前的现实余额改回{expected_opening}，不要沿用旧稿数字。")
        ending_matches = re.findall(
            r"余额(?:变为|变成|为)?\s*(\d+(?:\.\d{1,2})?)\s*元",
            anchor_text,
        )
        if ending_matches and not any(f"{value}元" in body[-1600:] for value in ending_matches):
            expected_ending = f"{ending_matches[-1]}元"
            scores["continuity"] = min(scores["continuity"], 4)
            issues.append(f"章末余额不一致：付清急账后的现实余额必须是{expected_ending}。")
            revision_plan.append(f"把章末现实余额改回{expected_ending}，并删除与该结果冲突的分项金额。")

        expected_arrival_value = expected_arrivals[-1] if expected_arrivals else ""
        expected_ending_value = ending_matches[-1] if ending_matches else ""
        if expected_arrival_value and expected_ending_value:
            def equivalent_amount_pattern(value: str) -> str:
                normalized = format(Decimal(value), "f").rstrip("0").rstrip(".")
                if "." in normalized:
                    return rf"{re.escape(normalized)}0*"
                return rf"{re.escape(normalized)}(?:\.0+)?"

            arrival_amount_pattern = re.compile(
                rf"{equivalent_amount_pattern(expected_arrival_value)}\s*元"
            )
            ending_balance_pattern = re.compile(
                rf"(?:银行卡|账户|现实)?余额(?:变为|变成|为)?\s*{equivalent_amount_pattern(expected_ending_value)}\s*元"
            )
            arrival_occurrence = arrival_amount_pattern.search(body)
            if arrival_occurrence:
                after_arrival = body[arrival_occurrence.end() :]
                ending_occurrence = ending_balance_pattern.search(after_arrival)
                payment_occurrence = re.search(
                    r"(?:(?:支付|转出|转账|付清|还清|还款成功)[^。]{0,20}(?:房租|最低还款|信用卡|账单)|"
                    r"(?:房租|最低还款|信用卡|账单)[^。]{0,28}(?:转出|转账|支付|付清|还清|还款成功)|"
                    r"确认支付|完成还款|付清|缴清)",
                    after_arrival,
                )
                if ending_occurrence and payment_occurrence and ending_occurrence.start() < payment_occurrence.start():
                    prefix = after_arrival[max(0, ending_occurrence.start() - 24) : ending_occurrence.start()]
                    if not any(marker in prefix for marker in ("预计", "算过", "付完会剩", "支付后", "还清后")):
                        scores["continuity"] = min(scores["continuity"], 4)
                        issues.append("现实余额出现顺序错误：章末余额在房租或还款实际支付前已经出现。")
                        revision_plan.append(
                            "保留登录前余额和净到账金额；到账后先写转账/还款动作及成功反馈，最后再写章末余额。"
                        )
                if opening_matches and payment_occurrence:
                    opening_amount_pattern = equivalent_amount_pattern(opening_matches[0])
                    stale_balance = re.search(
                        rf"(?:银行卡|账户|现实)?余额(?:变为|变成|为)?\s*{opening_amount_pattern}\s*元",
                        after_arrival[: payment_occurrence.start()],
                    )
                    if stale_balance:
                        scores["continuity"] = min(scores["continuity"], 4)
                        issues.append("到账后余额仍停在登录前金额：交易收入没有进入现实账户流水。")
                        revision_plan.append(
                            "到账提示后不要重复登录前余额；先写收入进入账户，再写房租和还款，最后落章末余额。"
                        )

            amount_value_pattern = rf"{equivalent_amount_pattern(expected_arrival_value)}\s*元"
            gross_uses_net = re.search(rf"成交价\s*[：:]?\s*{amount_value_pattern}", body)
            net_arrival_uses_net = re.search(
                rf"(?:预计|实际)?到账(?:金额)?\s*[：:]?\s*{amount_value_pattern}|{amount_value_pattern}\s*到账",
                body,
            )
            fee_match = re.search(r"(?:服务费|手续费)\s*[：:]?\s*(\d+(?:\.\d{1,2})?)\s*元", body)
            if gross_uses_net and net_arrival_uses_net and fee_match and Decimal(fee_match.group(1)) > 0:
                scores["continuity"] = min(scores["continuity"], 4)
                issues.append("交易金额流水矛盾：成交总价和扣费后的净到账写成了同一个金额。")
                revision_plan.append(
                    "净到账金额沿用大纲；如正文另写手续费，成交总价必须等于净到账加手续费，不能把净到账同时标成成交价。"
                )

    if chapter_number == 1 and game_context:
        game_id_markers = ("游戏ID", "游戏昵称", "角色名", "网名", "ID：", "ID:", "夜烬", "铁算盘")
        if not any(marker in body or marker in plan_text or marker in facts_text for marker in game_id_markers):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            scores["background_integration"] = min(scores["background_integration"], 5)
            issues.append("第一章缺少游戏ID/网名身份层；网游文需要区分现实姓名和游戏内ID。")
            revision_plan.append("在角色创建或登录界面补入角色卡中的游戏ID；游戏内称呼使用游戏ID，现实场景才使用现实姓名。")

    if "1000倍爆率" in body or "1000 倍爆率" in body or "1000倍" in body and "千倍" in body:
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append("千倍爆率写法不统一：正文混用了“千倍”和“1000倍/1000倍爆率”。")
        revision_plan.append("统一改为“千倍爆率”；如需面板数值，使用“掉落判定×1000”而不是“1000倍爆率”。")

    forbids_fixed_exchange_rate = "不得写死" in facts_text and "汇率" in facts_text
    has_explicit_exchange_rate = not forbids_fixed_exchange_rate and any(
        token in facts_text
        for token in ("稳定汇率", "金币=现实货币", "金币兑现实货币", f"金币={_FORBIDDEN_REAL_CURRENCY_NAME}", f"金币兑{_FORBIDDEN_REAL_CURRENCY_NAME}")
    )
    invented_exchange_rate = re.search(
        rf"(?:1|一)\s*(?:枚)?金币\s*(?:=|约等于|等于|能换|可以换|折合)\s*\d+(?:\.\d+)?\s*(?:元|{_FORBIDDEN_REAL_CURRENCY_NAME}|RMB)",
        body,
    )
    if invented_exchange_rate and not has_explicit_exchange_rate:
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append("章节写死了游戏币与现实货币的汇率，但世界档案没有明确官方兑换行情。")
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

    if chapter_number == 1 and game_context and project_specific_game_context:
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
        if not chapter_one_trade_payoff and any(token in body for token in first_chapter_trade_terms):
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
        service_terms = first_chapter_service_closure_terms
        if chapter_one_trade_payoff:
            service_terms = tuple(token for token in service_terms if token != "扣掉")
        if any(_has_completed_term(body, token) for token in service_terms):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            scores["continuity"] = min(scores["continuity"], 5)
            issues.append("第一章账本越界：出现拿铜币、修法杖、买药水、技能书残页或旧城区入口等后续阶段内容。")
            revision_plan.append("第一章只保留首次打灰狼、掉落异常、血蓝耐久消耗、背包材料和清道夫委托前置；不得交任务、拿铜币、修法杖、买药水或开启技能书/旧城区线。")

        first_chapter_pressure_terms = ("白袍", "公会", "论坛", "清场", "后勤", "异常低价", "观察名单")
        early_external_pressure = has_asserted_overreach(body, first_chapter_pressure_terms)
        if chapter_one_trade_payoff:
            early_external_pressure = has_asserted_overreach(
                body,
                ("白袍", "论坛", "清场", "后勤", "异常低价", "观察名单"),
            ) or bool(
                re.search(r"公会[^。！？\n]{0,24}(?:追查|盯上|锁定|调查|围堵|清场)", body)
            )
        if early_external_pressure:
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章外部压力过早：公会、论坛、商人脚本或清场信息提前介入。")
            revision_plan.append("把公会、论坛和商人脚本反应全部移到第二章以后；第一章只让主角自己意识到材料需要处理，外部世界暂不正式发现。")

        opening_overreach_terms = (
            "正面撞上",
            "正面对决",
            "当场围住",
            "杀人夺宝",
            "抢核心资源",
            "争夺核心资源",
            "世界BOSS",
            "高阶副本",
            "公会会长",
        )
        protagonist_targeted_attack = bool(
            re.search(r"(?:围杀|截杀|追杀)[^。！？\n]{0,16}(?:苏叶|夜烬)", body)
            or re.search(r"(?:苏叶|夜烬)[^。！？\n]{0,16}(?:被围杀|被截杀|被追杀)", body)
        )
        if protagonist_targeted_attack or any(token in body for token in opening_overreach_terms):
            scores["genre_rules"] = min(scores["genre_rules"], 5)
            issues.append("第一章冲突越级：开篇应以现实压力、登录建号、初始身份、规则验证和背包材料暂时不能处理为主，不能写成公会/商人正面对抗或高阶资源争夺。")
            revision_plan.append("把冲突降级为网游新手阶段：现实资金压力、武器/基础技能选择成本、第一次打怪验证、血蓝耐久消耗和背包材料如何处理。")

    if project_specific_game_context and "数量×1000" in body and re.search(r"获得：[^。\n】]*[×x]\s*100(?:[。】\n]|$)", body):
        scores["genre_rules"] = min(scores["genre_rules"], 5)
        issues.append("天赋说明为基础掉落物数量×1000，但正文首次掉落只写×100。")
        revision_plan.append("要么把天赋说明改为爆率/判定权重×1000，要么把首次掉落数量改为×1000，并同步后续背包、交易和市场反应。")

    if (
        project_specific_game_context
        and
        chapter_number in (2, 3)
        and ("NPC：" in facts_text or event_plan.get("npc_beats"))
        and not any(token in body for token in ("灰烬村村长", "药剂师洛婶", "职业导师艾伦", "仓库管理员铁栓", "修理匠老葛", "村长", "洛婶", "艾伦", "铁栓", "老葛"))
    ):
        scores["background_integration"] = min(scores["background_integration"], 5)
        issues.append("网游开篇缺少已建档命名 NPC 的服务、任务发布或职业导师互动，世界像只有玩家和系统。")
        revision_plan.append("补入至少一场已建档命名 NPC 互动，例如灰烬村村长、药剂师洛婶、职业导师艾伦、仓库管理员铁栓或修理匠老葛，并让其服务/任务/信息边界推动本章选择。")

    if chapter_number == 1 and game_context and project_specific_game_context:
        require(
            "background_integration",
            ("游戏名", "《神域》", "全沉浸", "VRMMO", "开服"),
            "第一章缺少足够清晰的游戏背景入口。",
            "在开头或登录场景中写出本书设定的游戏名、开服状态和玩家涌入背景。",
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
            revision_plan.append("补一个简短面板，正文中明确写出“角色面板”：游戏ID夜烬、等级1、身份见习冒险者（未转职）、经验0/100、新手法杖、基础火球术、初始背包或钱袋。")
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

    if game_context and project_specific_game_context:
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

    if chapter_number == 2 and game_context and project_specific_game_context:
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


    if simulation_plan:
        if game_context and not simulation_plan.get("information_visibility"):
            scores["simulation_plan_alignment"] = min(scores["simulation_plan_alignment"], 6)
            issues.append("统一蓝图缺少信息可见性边界，网游章节容易写成交易行、公会或NPC全知全能。")
            revision_plan.append("在 simulation_plan.information_visibility 中写清交易行、公会、论坛、NPC记录分别能看到什么，不能看到什么。")
        forbidden_moves = [str(item).strip() for item in simulation_plan.get("forbidden_moves", []) if str(item).strip()]
        if game_context and not forbidden_moves:
            scores["simulation_plan_alignment"] = min(scores["simulation_plan_alignment"], 6)
            issues.append("统一蓝图缺少禁写项，无法约束低级材料扰乱全服、NPC越权、交易行暴露身份等常见网游逻辑问题。")
            revision_plan.append("在 simulation_plan.forbidden_moves 中加入NPC不得全知、低级材料不能扰乱全服、交易行不得暴露坐标/现实身份等禁写边界。")
    subreviews: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            "web_game_review": pool.submit(
                review_web_game_chapter,
                chapter_number=chapter_number,
                body=body,
                event_plan=event_plan,
                world_facts=world_facts,
                protagonist_aliases=protagonist_aliases,
                character_names=character_names,
            ),
            "progression_lead_review": pool.submit(
                review_progression_lead,
                chapter_number=chapter_number,
                body=body,
                event_plan=event_plan,
                world_facts=world_facts,
            ),
        }
        for name, future in futures.items():
            try:
                subreviews[name] = future.result()
            except Exception as exc:
                report_generation_progress(f"review[{name}] exception: {exc}")
                subreviews[name] = _review_exception_result(name, exc)

    web_game_review = subreviews["web_game_review"]
    progression_lead_review = subreviews["progression_lead_review"]
    _merge_subreview(
        prefix="web_game",
        review=web_game_review,
        scores=scores,
        issues=issues,
        revision_plan=revision_plan,
    )
    _merge_subreview(
        prefix="progression_lead",
        review=progression_lead_review,
        scores=scores,
        issues=issues,
        revision_plan=revision_plan,
    )
    return {
        "pass": bool(web_game_review.get("pass", True)),
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
        "active_genre_reviews": subreviews,
        "world_state_review": _build_game_world_state_review(issues, revision_plan),
    }
