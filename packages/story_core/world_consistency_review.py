from __future__ import annotations

from typing import Any

from packages.story_core.web_game_economy import detect_economy_boundary_violations


TRACKING_OVERREACH_TERMS = (
    "锁定他的坐标",
    "锁定坐标",
    "精确坐标",
    "实时位置",
    "现实身份",
    "真人身份",
    "隐藏天赋",
    "刷怪点",
)

WEAK_TRACE_TERMS = ("价格", "数量", "批次", "时间戳", "手续费", "到账", "小额订单")
INTERNAL_FIELD_TERMS = ("world_events", "scene_cards", "visible_to", "state_delta", "prose_priority")
UNCHECKABLE_BEAT_CHARS = "，。；：、,.!?！？"

SCENE_BEAT_ALIASES: dict[str, tuple[tuple[str, ...], ...]] = {
    "真实到账": (("真实到账", "实际到账", "到账提示", "到账通知", "银行通知", "账户收入", "到账："),),
    "现实急账处理": (("现实急账", "急账处理", "急账已解决", "补上房租", "房租已补", "最低还款", "逾期倒计时消失"),),
    "担保交易": (("担保交易", "担保平台", "匿名鉴定", "完成交割", "交割完成"),),
    "现实职业/技能来源": (
        ("风控", "测试员", "外包", "测试工作", "工作", "项目", "职业玩家", "道具估价", "交易平台"),
        (
            "概率",
            "流水",
            "模型",
            "漏洞",
            "规则",
            "数值",
            "流程测试",
            "任务条件",
            "怪物行为",
            "伤害公式",
            "测试过程",
            "测试报告",
            "法系模板",
            "施法距离",
            "技能冷却",
            "估价",
            "审核装备",
            "核价格",
        ),
    ),
    "为什么登录游戏": (("房租", "停职", "余额", "缺钱", "变现", "下个月"),),
    "主角风险偏好": (("风险", "低调", "风控", "隔离", "封号"),),
    "游戏ID": (("游戏ID", "ID：", "ID:", "夜烬", "输入名字", "角色名"),),
    "初始身份": (("见习冒险者", "未转职", "新手法杖", "基础火球术", "武器选择"),),
    "角色面板": (("角色面板", "状态面板", "面板在视野", "【等级：", "【经验：", "等级：", "经验：", "职业：", "Lv.1"),),
    "基础属性": (("基础属性", "力量：", "力量", "敏捷：", "敏捷", "智力：", "智力", "体质：", "体质", "生命：", "生命", "法力：", "法力"),),
    "主武器或基础技能": (("新手法杖", "法杖", "主武器", "基础火球术", "基础技能", "技能："),),
    "主武器": (("新手法杖", "法杖", "主武器"),),
    "基础技能": (("基础火球术", "基础技能", "技能："),),
    "低级怪物": (("灰鼠", "灰狼", "低级怪", "1级"),),
    "掉落反馈": (("掉落", "提示音", "掉出", "获得"),),
    "背包变化": (("背包",), ("跳到", "多了", "数量", "库存", "负重", "占了", "格子", "灰狼毒腺", "粗糙狼皮")),
    "小额验证": (("先试", "试一次", "验证", "不是错觉", "小额", "灰狼", "低级怪", "第一只"), ("掉落", "千倍", "背包", "获得", "多了")),
    "领先验证": (("更快", "领先", "少跑", "早一步", "任务", "门槛", "进度"), ("千倍", "掉落", "经验", "材料", "装备", "技能")),
    "进度领先反馈": (("任务", "经验", "装备", "技能", "路线", "门槛", "清道夫"), ("更快", "少跑", "提前", "早一步", "凑齐", "完成")),
    "NPC地点": (("药剂铺", "柜台", "灰烬村", "村口", "职业大厅", "仓库", "铁匠铺"),),
    "NPC地点或窗口": (("药剂铺", "柜台", "柜台窗口", "灰烬村", "村口", "职业大厅", "仓库", "铁匠铺"),),
    "服务内容": (("收购", "解毒剂", "药剂", "修理", "仓储", "任务", "价格"),),
    "价格/门槛": (("价格", "报价", "铜", "押金", "门槛", "条件", "五份", "三组", "只收"),),
    "价格/前置条件": (("价格", "报价", "铜", "押金", "奖励", "前置", "条件", "十份", "只收", "提交"),),
    "信息边界": (("不问来源", "没追问", "没再多问", "继续给药瓶贴签", "交易记录", "流水", "记录", "不能看到", "只能看到", "只管", "只收", "别问", "问不了", "不知道", "柜台规矩", "信息边界"),),
    "下一步目标": (("先交一组", "第一笔铜币", "去导师", "第二只灰鼠", "下一步", "明天", "回头", "先问", "先去", "先不卖", "先收着", "交易行", "价牌", "还差两份", "后坡探路", "前置"),),
    "材料暂不外露": (("背包", "灰狼毒腺", "粗糙狼皮", "材料", "先收着", "不卖", "不处理", "暂不处理", "收回背包"),),
    "材料处理门槛": (("材料", "背包", "毒腺", "狼皮"), ("先不卖", "先收着", "不处理", "交易行", "价牌", "排队", "押金", "明天", "下一步")),
    "领先下一步": (("下一步", "任务", "装备", "技能", "路线", "委托", "门槛", "前置", "后坡探路"), ("更快", "少跑", "提前", "早一步", "先一步", "快了一截", "凑齐", "领先", "还差两份")),
    "NPC门槛": (("五份", "三组", "按牌子走", "今天这批药房只收三组", "报价", "押金", "条件", "只收", "先交"),),
    "规则未明": (("不碰第二只", "先交一组", "灰色标记", "去导师", "没弄明白", "还没试清", "下一步", "先别"),),
    "普通玩家觉得夜烬运气好或路线熟": (
        ("普通玩家", "散人玩家", "队尾", "旁边排队", "旁边排队的人", "排队的人"),
        ("夜烬", "他"),
        ("运气好", "路线熟"),
    ),
    "NPC照规矩办事不怀疑隐藏天赋": (
        ("NPC", "办事员", "老葛", "铁匠", "修理铺", "洛婶", "药剂铺"),
        ("规矩", "只看裂纹和耐久", "不问夜烬", "没追问", "不管他刚才交了什么任务", "这事就到这里"),
    ),
    "散人玩家抱怨灰狼毒腺掉率低": (
        ("散人玩家", "公共频道", "队尾", "玩家", "有人"),
        ("抱怨", "嘀咕", "骂"),
        ("灰狼毒腺", "毒腺"),
        ("掉率低", "不好掉", "掉得少", "还差"),
    ),
    "洛婶按清单办事不理会夜烬频率": (
        ("洛婶", "药剂铺"),
        ("清单", "价牌", "收钱", "铜币", "药水"),
        ("不理会", "不问", "没追问", "只按", "照着"),
    ),
    "试打后坡→交委托→修买→探路卡住": (
        ("试打后坡", "补打一只灰狼", "坡口补打", "灰狼毒腺×2"),
        ("交委托", "清道夫委托", "委托已提交"),
        ("修杖买药", "修杖", "修理", "买药", "药水"),
        ("探路卡住", "登记牌", "后坡记录", "建议等级", "组队进入", "卡住"),
    ),
    "从野外试打转向村内结算与补给": (
        ("野外", "后坡", "坡口", "灰狼"),
        ("回村", "村内", "广场", "柜台"),
        ("结算", "交委托", "清道夫委托", "三十铜", "铜币"),
        ("补给", "修杖", "买药", "药水", "修理"),
    ),
}

EVENT_ACTION_ALIASES: tuple[tuple[tuple[str, ...], tuple[tuple[str, ...], ...]], ...] = (
    (
        ("登录游戏", "进入游戏", "游戏内身份", "现实压力"),
        (("出租屋", "催租", "余额", "账单", "头盔"), ("登录", "角色创建", "游戏ID", "职业")),
    ),
    (
        ("低级怪物", "任务材料", "千倍爆率", "领先验证"),
        (("灰狼", "低级怪", "火苗术", "击杀"), ("掉落", "背包", "提示音", "获得", "千倍")),
    ),
    (
        ("交易行", "寄售", "弱线索"),
        (("交易行", "寄售", "挂牌"), ("批次", "时间戳", "手续费", "到账", "价格")),
    ),
    (
        ("NPC", "服务", "任务"),
        (("柜台", "村长", "药剂师", "导师", "仓库", "修理匠"), ("价格", "门槛", "任务", "收购", "服务")),
    ),
    (
        ("普通玩家觉得夜烬运气好或路线熟", "普通玩家觉得夜烬路线熟或运气好", "路线熟或运气好", "运气好或路线熟"),
        (
            ("普通玩家", "散人玩家", "队尾", "旁边排队", "排队的人", "有人低声", "旁边的人"),
            ("运气好", "路线熟"),
            ("没人追问", "没人多问", "无追查", "没追查", "转回自己的面板"),
        ),
    ),
)


def _event_text(event: dict[str, Any]) -> str:
    parts = [
        str(event.get("event_id", "")),
        str(event.get("actor", "")),
        str(event.get("action", "")),
        str(event.get("location", "")),
        " ".join(str(item) for item in event.get("visible_to", []) if str(item).strip())
        if isinstance(event.get("visible_to"), list)
        else "",
        " ".join(str(item) for item in event.get("consequences", []) if str(item).strip())
        if isinstance(event.get("consequences"), list)
        else "",
    ]
    return "\n".join(parts)


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


def _scene_forbidden_terms(scene_cards: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for card in scene_cards:
        raw_terms = card.get("must_not_explain", []) if isinstance(card, dict) else []
        if isinstance(raw_terms, list):
            terms.extend(str(term).strip() for term in raw_terms if str(term).strip())
    for term in INTERNAL_FIELD_TERMS:
        if term not in terms:
            terms.append(term)
    return terms


def _checkable_scene_beat(beat: str) -> bool:
    beat = beat.strip()
    if not beat or len(beat) > 16:
        return False
    return not any(char in beat for char in UNCHECKABLE_BEAT_CHARS)


def _beat_is_visible(body: str, beat: str) -> bool:
    alias_groups = SCENE_BEAT_ALIASES.get(beat)
    if alias_groups:
        return all(any(term in body for term in group) for group in alias_groups)
    parts = [part.strip() for part in beat.split("/") if part.strip()]
    if not parts:
        return False
    return all(part in body for part in parts)


def _event_action_is_visible(body: str, action: str) -> bool:
    for action_terms, body_groups in EVENT_ACTION_ALIASES:
        if any(term in action for term in action_terms):
            return all(any(term in body for term in group) for group in body_groups)
    return False


def _missing_scene_card_beats(body: str, scene_cards: list[dict[str, Any]], chapter_number: int | None = None) -> dict[str, list[str]]:
    missing_by_scene: dict[str, list[str]] = {}
    for card in scene_cards:
        if not isinstance(card, dict):
            continue
        raw_beats = card.get("must_show", [])
        if not isinstance(raw_beats, list):
            continue
        beats = [str(item).strip() for item in raw_beats]
        if chapter_number == 1:
            beats = [
                beat
                for beat in beats
                if beat not in {"NPC门槛", "一个NPC服务节点", "信息边界", "规则未明", "主角风险偏好"}
            ]
        missing = [beat for beat in beats if _checkable_scene_beat(beat) and not _beat_is_visible(body, beat)]
        if missing:
            scene_id = str(card.get("scene_id") or card.get("template_id") or "scene")
            missing_by_scene[scene_id] = missing
    return missing_by_scene


def _systemic_blocks(scene_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for card in scene_cards:
        if not isinstance(card, dict):
            continue
        state_delta = card.get("state_delta") if isinstance(card.get("state_delta"), dict) else {}
        game_world = state_delta.get("game_world_simulation") if isinstance(state_delta.get("game_world_simulation"), dict) else {}
        systemic = game_world.get("systemic_simulation") if isinstance(game_world.get("systemic_simulation"), dict) else {}
        if systemic:
            blocks.append(systemic)
    return blocks


def _scene_contracts(scene_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for card in scene_cards:
        if not isinstance(card, dict):
            continue
        contract = card.get("scene_contract") if isinstance(card.get("scene_contract"), dict) else {}
        if contract:
            contract = {**contract, "_scene_id": str(card.get("scene_id") or contract.get("scene_id") or "scene")}
            contracts.append(contract)
    return contracts


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _has_asserted_sensitive_exposure(body: str) -> bool:
    asserted_phrases = (
        "locked his coordinates",
        "locked the coordinates",
        "identified his hidden talent",
        "identified the hidden talent",
        "revealed his real identity",
        "锁定坐标",
        "锁定他的坐标",
        "查到现实身份",
        "确认现实身份",
        "识别出现实身份",
        "公开现实身份",
        "暴露现实身份",
        "查到隐藏天赋",
        "确认隐藏天赋",
        "识别出隐藏天赋",
        "公开隐藏天赋",
        "暴露隐藏天赋",
    )
    negation_markers = ("不", "没", "未", "无", "不能", "不会", "无法", "不可", "没有", "并未", "并不")
    lowered = body.lower()
    for phrase in asserted_phrases:
        start = 0
        needle = phrase.lower()
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            prefix = lowered[max(0, index - 16):index]
            if not any(marker in prefix for marker in negation_markers):
                return True
            start = index + len(needle)
    return False


def _review_scene_contract_consumption(
    body: str,
    scene_cards: list[dict[str, Any]],
    *,
    issues: list[str],
    revision_plan: list[str],
    scores: dict[str, int],
    scene_contract_failures: list[dict[str, Any]],
) -> None:
    for contract in _scene_contracts(scene_cards):
        scene_id = str(contract.get("_scene_id") or contract.get("scene_id") or "scene")
        visible_items = contract.get("visible_consequences") if isinstance(contract.get("visible_consequences"), list) else []
        for item in visible_items:
            if not isinstance(item, dict):
                continue
            requires_any = item.get("requires_any") if isinstance(item.get("requires_any"), list) else []
            terms = tuple(str(term) for term in requires_any if str(term).strip())
            if not terms or _contains_any(body, terms):
                continue
            consequence_id = str(item.get("id") or "visible_consequence")
            description = str(item.get("description") or consequence_id)
            revision = str(
                item.get("revision")
                or "Add visible prose evidence for this scene contract consequence before the scene can pass."
            )
            scene_contract_failures.append(
                {
                    "scene_id": scene_id,
                    "consequence_id": consequence_id,
                    "description": description,
                    "requires_any": list(terms),
                    "revision": revision,
                    "rewrite_scope": "scene_only",
                }
            )
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="scene_contract_consumption",
                issue=f"Scene contract not consumed: {scene_id} missing {consequence_id} ({description}).",
                plan=revision,
                score=5,
            )


def _review_systemic_consistency(
    body: str,
    scene_cards: list[dict[str, Any]],
    *,
    issues: list[str],
    revision_plan: list[str],
    scores: dict[str, int],
) -> None:
    for systemic in _systemic_blocks(scene_cards):
        ledger_delta = systemic.get("ledger_delta") if isinstance(systemic.get("ledger_delta"), dict) else {}
        cost_delta = ledger_delta.get("cost_delta") if isinstance(ledger_delta.get("cost_delta"), dict) else {}
        visibility_layers = systemic.get("visibility_layers") if isinstance(systemic.get("visibility_layers"), dict) else {}

        if int(cost_delta.get("mp") or 0) < 0 and _contains_any(
            body,
            ("full mana", "mana was full", "mana stayed full", "法力充足", "法力满", "满蓝"),
        ):
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="systemic_consistency",
                issue="Systemic ledger break: prose says mana is full after the simulation spent mana.",
                plan="Show the simulated mana cost on page: low mana, emptied mana, or a panel/resource check that matches cost_delta.",
                score=5,
            )

        if int(cost_delta.get("durability") or 0) < 0 and _contains_any(
            body,
            ("undamaged staff", "undamaged weapon", "durability untouched", "法杖完好", "耐久没掉", "耐久未损"),
        ):
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="systemic_consistency",
                issue="Systemic ledger break: prose says the weapon is undamaged after durability was spent.",
                plan="Reflect the simulated durability cost through a red durability line, repair pressure, or a damaged weapon detail.",
                score=5,
            )

        if int(cost_delta.get("hp") or 0) < 0 and _contains_any(
            body,
            ("full health", "unhurt", "not a scratch", "毫发无伤", "生命满", "血量满"),
        ):
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="systemic_consistency",
                issue="Systemic ledger break: prose erases simulated HP cost.",
                plan="Reflect the HP loss through wound feedback, a panel change, or a cautious retreat decision.",
                score=5,
            )

        if visibility_layers.get("guild") and _has_asserted_sensitive_exposure(body):
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="systemic_consistency",
                issue="Systemic visibility break: guild knowledge exceeds the simulation visibility layer.",
                plan="Limit guild/public knowledge to route noise, timestamps, batches, prices, weak public traces, or repeated later evidence.",
                score=5,
            )

        if visibility_layers.get("npc") and _contains_any(
            body,
            (
                "npc knew hidden talent",
                "npc knew his real identity",
                "npc identified",
                "NPC知道隐藏天赋",
                "NPC知道现实身份",
            ),
        ):
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="systemic_consistency",
                issue="Systemic visibility break: NPC knowledge exceeds the service boundary.",
                plan="Keep NPC knowledge inside service inputs, posted thresholds, inventory, queue behavior, and public records.",
                score=5,
            )


def review_world_event_consistency(
    body: str,
    *,
    world_events: list[dict[str, Any]] | None = None,
    scene_cards: list[dict[str, Any]] | None = None,
    chapter_number: int | None = None,
) -> dict[str, Any]:
    """Review whether prose obeys simulated world-event boundaries."""

    world_events = world_events or []
    scene_cards = scene_cards or []
    scores = {
        "visibility_boundary": 8,
        "event_coverage": 8,
        "state_delta_surface": 8,
        "scene_card_coverage": 8,
        "surface_terms": 8,
        "systemic_consistency": 8,
        "scene_contract_consumption": 8,
    }
    issues: list[str] = []
    revision_plan: list[str] = []
    scene_contract_failures: list[dict[str, Any]] = []

    for violation in detect_economy_boundary_violations(body):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="systemic_consistency",
            issue=f"[必须修复]经济边界：{violation.issue}",
            plan=violation.revision,
            score=3,
        )

    market_events = [
        event
        for event in world_events
        if "交易行" in _event_text(event) or "market_trace" in str(event.get("state_delta", ""))
    ]
    if chapter_number == 1:
        market_events = []
    if market_events and any(term in body for term in TRACKING_OVERREACH_TERMS):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="visibility_boundary",
            issue="可见性越界：交易行小额寄售被正文升级成坐标、现实身份、隐藏天赋或刷怪点暴露。",
            plan="把外部可见信息降回价格、数量、批次和时间戳；公会或商人只能看到弱线索，不能直接锁定坐标、现实身份或隐藏天赋。",
        )

    for event in sorted(world_events, key=lambda item: int(item.get("prose_priority", 0) or 0), reverse=True)[:3]:
        action = str(event.get("action", "")).strip()
        location = str(event.get("location", "")).strip()
        actor = str(event.get("actor", "")).strip()
        visible_markers = [marker for marker in (actor, location) if marker and marker in body]
        if action and not visible_markers and not _event_action_is_visible(body, action):
            _append_issue(
                issues=issues,
                revision_plan=revision_plan,
                scores=scores,
                score_key="event_coverage",
                issue=f"推演事件未被正文场景化：{action}",
                plan="把该推演事件写成具体场景，至少交代地点、行动、角色反应和阶段结果，而不是让它只停留在计划里。",
                score=6,
            )

    state_delta_events = [event for event in world_events if isinstance(event.get("state_delta"), dict) and event.get("state_delta")]
    if state_delta_events and not any(term in body for term in ("面板", "背包", "金币", "银币", "铜币", "经验", "装备", "到账")):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="state_delta_surface",
            issue="状态变化没有正文表面：推演事件包含 state_delta，但正文缺少面板、背包、货币、经验、装备或到账等可见结果。",
            plan="把状态变化写成读者可见的角色面板、交易到账、背包数量、经验/等级或装备耐久变化。",
            score=6,
        )

    forbidden_terms = _scene_forbidden_terms(scene_cards)
    leaked_terms = [term for term in forbidden_terms if term and term in body]
    if leaked_terms:
        sample = "、".join(leaked_terms[:5])
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="surface_terms",
            issue=f"场景卡禁写词进入正文：{sample}。",
            plan="删除场景卡、推演字段名、审稿词和创作术语，改成角色视角内能看到、能听到、能判断的内容。",
        )

    missing_by_scene = _missing_scene_card_beats(body, scene_cards, chapter_number)
    for scene_id, missing in missing_by_scene.items():
        sample = "、".join(missing[:6])
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="scene_card_coverage",
            issue=f"场景卡必写内容缺失：{scene_id} 缺少 {sample}。",
            plan=f"补写 {scene_id} 的必写内容：{sample}；必须写成界面、动作、对话或角色观察，不要写成规则条目。",
            score=6,
        )

    if market_events and not any(term in body for term in WEAK_TRACE_TERMS) and not any(
        issue.startswith("可见性越界") for issue in issues
    ):
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="visibility_boundary",
            issue="交易行事件缺少弱线索表面：正文没有写出价格、数量、批次、时间戳、手续费或到账反馈。",
            plan="补出交易行界面能显示的弱线索，例如价格、数量、批次、手续费、到账提示和时间戳。",
            score=6,
        )

    _review_systemic_consistency(
        body,
        scene_cards,
        issues=issues,
        revision_plan=revision_plan,
        scores=scores,
    )
    _review_scene_contract_consumption(
        body,
        scene_cards,
        issues=issues,
        revision_plan=revision_plan,
        scores=scores,
        scene_contract_failures=scene_contract_failures,
    )

    return {
        "pass": all(score >= 8 for score in scores.values()) and not issues,
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
        "scene_contract_failures": scene_contract_failures,
    }
