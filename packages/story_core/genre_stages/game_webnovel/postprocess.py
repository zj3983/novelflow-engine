from __future__ import annotations

import re
from typing import Any

from packages.story_core.genre_stages.postprocess import (
    PostprocessContext,
    normalize_generated_body,
)


def _repair_outline_amount_anchors(body: str, anchor: Any) -> str:
    if not isinstance(anchor, dict) or not str(body or "").strip():
        return body
    repaired = str(body)
    opening = str(anchor.get("opening_balance") or "").strip()
    arrival = str(anchor.get("trade_arrival") or "").strip()
    ending = str(anchor.get("ending_balance") or "").strip()

    balance_pattern = re.compile(
        r"((?:余额\s*(?:(?:只剩|还有|变成|变为|停在|为)\s*)?)|"
        r"(?:(?:银行卡|账户)(?:里|中)\s*(?:(?:只剩|还有|停在|为)\s*)?))"
        r"(?:[：:。]\s*)?"
        r"(?:\d+(?:\.\d{1,2})?\s*元|[零〇一二两三四五六七八九十百千万点块元毛角分]+)"
    )
    if opening:
        balance_matches = list(balance_pattern.finditer(repaired))
        if balance_matches:
            match = balance_matches[0]
            repaired = repaired[: match.start()] + f"{match.group(1)}{opening}" + repaired[match.end() :]
        elif opening not in repaired[:1200]:
            repaired = f"苏叶登录游戏前，账户余额{opening}。\n\n{repaired.lstrip()}"
    arrival_pattern = re.compile(
        r"(?P<label>预计到账(?:金额)?|实际到账(?:金额)?|现实账户(?:收到|到账)|"
        r"(?:现实)?账户(?:收到|到账|收入)|"
        r"手机(?:银行)?(?:提示|弹出提示|收到提示)?(?:进账|到账)|到账金额|实收|到账)"
        r"(?P<separator>\s*(?:[：:]\s*)?)"
        r"(?P<amount>\d+(?:\.\d{1,2})?\s*元)"
    )
    urgency_pattern = re.compile(
        r"(?:付清|处理|缴清|还清)[^。！？\n]{0,50}(?:现实急账|急账|房租|账单|最低还款)"
        r"|(?:现实急账|急账|账单)[^。！？\n]{0,30}(?:付清|处理|缴清|还清)"
    )

    def sentence_start(text: str, index: int) -> int:
        return max(
            text.rfind("。", 0, index),
            text.rfind("！", 0, index),
            text.rfind("？", 0, index),
            text.rfind("!", 0, index),
            text.rfind("?", 0, index),
            text.rfind("\n", 0, index),
        ) + 1

    def remove_minimal_phrases(text: str, matches: list[re.Match[str]]) -> str:
        for match in reversed(matches):
            start, end = match.span()
            exchange_prefix = re.search(
                r"官方兑换(?:完成|成功)[ \t]*[，,][ \t]*$",
                text[:start],
            )
            if exchange_prefix:
                start = exchange_prefix.start()
            own_sentence_start = sentence_start(text, start)
            sentence_ends = [
                position
                for marker in ("。", "！", "？", "!", "?", "\n")
                if (position := text.find(marker, end)) >= 0
            ]
            own_sentence_end = min(sentence_ends) if sentence_ends else len(text)
            owns_sentence = (
                not text[own_sentence_start:start].strip()
                and not text[end:own_sentence_end].strip()
            )
            if owns_sentence:
                start = own_sentence_start
                end = own_sentence_end + (1 if own_sentence_end < len(text) else 0)
                while end < len(text) and text[end].isspace():
                    end += 1
            elif end < len(text) and text[end] in "，,":
                end += 1
            elif exchange_prefix and end < len(text) and text[end] in "。！？!?":
                end += 1
            elif start > 0 and text[start - 1] in "，,":
                start -= 1
            text = text[:start] + text[end:]
        return text

    def insert_exchange_before(text: str, index: int, paragraph: str) -> str:
        insert_at = sentence_start(text, index)
        prefix = text[:insert_at]
        suffix = text[insert_at:]
        before = "" if not prefix or prefix.endswith("\n") else "\n\n"
        after = "" if not suffix or suffix.startswith("\n") else "\n\n"
        return f"{prefix}{before}{paragraph}{after}{suffix}"

    if arrival:
        repaired = arrival_pattern.sub(
            lambda match: f"{match.group('label')}{match.group('separator')}{arrival}",
            repaired,
        )
        arrival_matches = list(arrival_pattern.finditer(repaired))
        receipt_matches = [
            match
            for match in arrival_matches
            if not match.group("label").startswith("预计")
        ]
        synthetic_exchange = (
            "他离开交易行，打开独立官方兑换页面。"
            f"页面显示兑换价、额度、手续费和预计到账；确认兑换后，现实账户收到{arrival}。"
        )
        if len(receipt_matches) >= 2 and synthetic_exchange in repaired:
            repaired = repaired.replace(f"\n\n{synthetic_exchange}", "", 1)
            receipt_matches = [
                match
                for match in arrival_pattern.finditer(repaired)
                if not match.group("label").startswith("预计")
            ]
        urgency_match = urgency_pattern.search(repaired)
        late_receipts = (
            [match for match in receipt_matches if match.start() > urgency_match.start()]
            if urgency_match
            else []
        )
        has_receipt_before_urgency = bool(
            urgency_match
            and any(match.start() < urgency_match.start() for match in receipt_matches)
        )
        needs_exchange_scene = not receipt_matches
        if late_receipts:
            repaired = remove_minimal_phrases(repaired, late_receipts)
            needs_exchange_scene = not has_receipt_before_urgency

        if needs_exchange_scene:
            exchange_paragraph = (
                "他离开交易行，打开独立官方兑换页面。"
                f"页面显示兑换价、额度、手续费和预计到账；确认兑换后，现实账户收到{arrival}。"
            )
            urgency_match = urgency_pattern.search(repaired)
            if urgency_match:
                repaired = insert_exchange_before(
                    repaired,
                    urgency_match.start(),
                    exchange_paragraph,
                )
            else:
                balance_matches = list(balance_pattern.finditer(repaired))
                insert_at = balance_matches[-1].start() if len(balance_matches) >= 2 else len(repaired)
                repaired = insert_exchange_before(repaired, insert_at, exchange_paragraph)
    if ending:
        balance_matches = list(balance_pattern.finditer(repaired))
        actual_receipts = [
            match
            for match in arrival_pattern.finditer(repaired)
            if not match.group("label").startswith("预计")
        ]
        first_receipt_start = actual_receipts[0].start() if actual_receipts else -1
        repeated_opening = [
            match
            for match in balance_matches
            if opening
            and match.start() > first_receipt_start >= 0
            and opening in re.sub(r"\s+", "", match.group(0))
        ]
        if repeated_opening:
            match = repeated_opening[-1]
            repaired = repaired[: match.start()] + f"{match.group(1)}{ending}" + repaired[match.end() :]
        elif len(balance_matches) >= 2:
            match = balance_matches[-1]
            repaired = repaired[: match.start()] + f"{match.group(1)}{ending}" + repaired[match.end() :]
        elif ending not in repaired[-1600:]:
            repaired = f"{repaired.rstrip()}\n\n付清现实急账后，账户余额{ending}。"
        if repaired.count(ending) > 1:
            repaired = repaired.replace(f"\n\n付清现实急账后，账户余额{ending}。", "")
    return repaired



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



def _apply_game_term_repairs(body: str) -> str:
    cleaned = _normalize_web_game_terms(body)
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
    )
    for old, new in reader_term_replacements:
        cleaned = cleaned.replace(old, new)
    cleaned = cleaned.replace("用法法杖", "用法杖").replace("法杖末端端", "法杖末端")
    cleaned = re.sub(r"背包[格子]*一下子亮了好几格", "灰狼毒腺和狼皮各占一格，数量叠在图标角上", cleaned)
    cleaned = re.sub(r"背包里([一二三四五六七八九十\d]+)个格子已经被材料塞住", "背包里两个材料格已经亮起，数量叠在图标角上", cleaned)

    def repair_stack_slots(match: re.Match[str]) -> str:
        occupied = int(match.group(1))
        window = cleaned[max(0, match.start() - 100) : min(len(cleaned), match.end() + 100)]
        stacks = re.findall(r"([\u4e00-\u9fffA-Za-z0-9·]+)\s*[×xX*＊]\s*(\d+)", window)
        unique_stacks = {name for name, _ in stacks}
        item_total = sum(int(amount) for _, amount in stacks)
        if len(unique_stacks) >= 2 and occupied == item_total:
            return f"背包：{len(unique_stacks)}/20"
        return match.group(0)

    cleaned = re.sub(r"背包：(\d+)/20", repair_stack_slots, cleaned)

    def compact_system_panel_group(match: re.Match[str]) -> str:
        entries = [item.strip() for item in re.findall(r"【([^】\n]+)】", match.group(0)) if item.strip()]
        return f"【{'；'.join(entries)}】" if entries else match.group(0)

    cleaned = re.sub(
        r"(?:【[^】\n]{1,100}】\s*){2,}",
        compact_system_panel_group,
        cleaned,
    )
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



def _sanitize_first_chapter_panel_values(body: str, chapter_number: int) -> str:
    if chapter_number != 1 or not body:
        return body
    cleaned = body
    cleaned = re.sub(r"(法力[：:]\s*\d+)/80", r"\1/60", cleaned)
    cleaned = re.sub(r"(法力[：:]\s*)20/60(?=[^\n。；]{0,80}(?:主武器|基础技能|背包|钱袋))", r"\g<1>60/60", cleaned)
    cleaned = cleaned.replace("生命：100/100法力：", "生命：100/100；法力：")
    cleaned = cleaned.replace("经验：0/100生命：", "经验：0/100；生命：")
    return cleaned



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


def postprocess_game_body(*, context: PostprocessContext) -> str:
    cleaned = normalize_generated_body(context=context)
    cleaned = _apply_game_term_repairs(cleaned)
    cleaned = _sanitize_systemic_resource_contradictions(cleaned, context.scene_cards)
    if context.chapter_number == 1:
        cleaned = _sanitize_first_chapter_panel_values(cleaned, context.chapter_number)
    cleaned = _sanitize_report_style_terms(cleaned)
    cleaned = _sanitize_chapter_two_webgame_terms(cleaned, context.chapter_number)
    return _repair_outline_amount_anchors(cleaned, context.outline_anchor)
