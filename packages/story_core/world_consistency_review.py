from __future__ import annotations

from typing import Any


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
    "现实职业/技能来源": (("风控", "测试员", "外包", "工作", "项目"), ("概率", "流水", "模型", "漏洞", "规则")),
    "为什么登录游戏": (("房租", "停职", "余额", "缺钱", "变现", "下个月"),),
    "主角风险偏好": (("风险", "低调", "风控", "隔离", "封号"),),
    "职业选择": (("职业列表", "职业选择", "点向法师", "选择职业", "元素法师学徒"),),
    "角色面板": (("角色面板", "状态面板", "面板在视野", "【等级：", "【经验："),),
    "基础属性": (("基础属性", "力量：", "力量", "敏捷：", "敏捷", "智力：", "智力", "体质：", "体质", "生命：", "生命", "法力：", "法力"),),
    "低级怪物": (("灰鼠", "灰狼", "低级怪", "1级"),),
    "掉落反馈": (("掉落", "提示音", "掉出", "获得"),),
    "背包变化": (("背包",), ("跳到", "多了", "数量", "库存", "负重")),
    "小额验证": (("先试", "试一次", "验证", "不是错觉", "小额"),),
    "NPC地点": (("药剂铺", "柜台", "灰烬村", "村口", "职业大厅", "仓库", "铁匠铺"),),
    "服务内容": (("收购", "解毒剂", "药剂", "修理", "仓储", "任务", "价格"),),
    "信息边界": (("不问来源", "没追问", "没再多问", "继续给药瓶贴签", "交易记录", "流水", "记录", "不能看到", "只能看到", "信息边界"),),
    "下一步目标": (("先交一组", "第一笔铜币", "去导师", "第二只灰鼠"),),
    "材料暂不外露": (("往后压", "别人看不见", "不卖", "收回背包"),),
    "NPC门槛": (("五份", "三组", "按牌子走", "今天这批药房只收三组"),),
    "规则未明": (("不碰第二只", "先交一组", "灰色标记", "去导师"),),
}

EVENT_ACTION_ALIASES: tuple[tuple[tuple[str, ...], tuple[tuple[str, ...], ...]], ...] = (
    (
        ("登录游戏", "进入游戏", "游戏内身份", "现实压力"),
        (("出租屋", "催租", "余额", "账单", "头盔"), ("登录", "角色创建", "游戏ID", "职业")),
    ),
    (
        ("低级怪物", "任务材料", "千倍爆率", "小额验证"),
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


def _missing_scene_card_beats(body: str, scene_cards: list[dict[str, Any]]) -> dict[str, list[str]]:
    missing_by_scene: dict[str, list[str]] = {}
    for card in scene_cards:
        if not isinstance(card, dict):
            continue
        raw_beats = card.get("must_show", [])
        if not isinstance(raw_beats, list):
            continue
        missing = [
            beat
            for beat in (str(item).strip() for item in raw_beats)
            if _checkable_scene_beat(beat) and not _beat_is_visible(body, beat)
        ]
        if missing:
            scene_id = str(card.get("scene_id") or card.get("template_id") or "scene")
            missing_by_scene[scene_id] = missing
    return missing_by_scene


def review_world_event_consistency(
    body: str,
    *,
    world_events: list[dict[str, Any]] | None = None,
    scene_cards: list[dict[str, Any]] | None = None,
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
    }
    issues: list[str] = []
    revision_plan: list[str] = []

    market_events = [
        event
        for event in world_events
        if "交易行" in _event_text(event) or "market_trace" in str(event.get("state_delta", ""))
    ]
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

    missing_by_scene = _missing_scene_card_beats(body, scene_cards)
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

    return {
        "pass": all(score >= 8 for score in scores.values()) and not issues,
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
    }
