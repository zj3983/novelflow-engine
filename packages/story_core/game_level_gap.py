from __future__ import annotations

from dataclasses import dataclass
import re


MAX_NORMAL_LEVEL_GAP = 2

SPECIAL_REASON_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("party", ("组队", "队友", "合力", "小队")),
    ("quest_item", ("任务道具", "任务物品", "压制道具")),
    ("counter", ("属性克制", "弱点克制", "明确克制")),
    ("equipment", ("特殊装备", "套装效果", "临时装备效果")),
    ("terrain", ("地形机关", "坠落伤害", "预设陷阱", "环境陷阱")),
    ("wounded", ("怪物残血", "怪物重伤", "只剩一成生命")),
    ("established_power", ("此前已解锁", "既有特殊能力", "此前获得的能力")),
)

COST_MARKERS = (
    "受伤",
    "生命下降",
    "法力耗尽",
    "药水耗尽",
    "耗尽药水",
    "补给耗尽",
    "耗尽补给",
    "装备损坏",
    "耐久归零",
    "失败风险",
    "被迫撤退",
)


@dataclass(frozen=True)
class LevelGapAssessment:
    allowed: bool
    gap: int
    requires_special_reason: bool
    reason_codes: tuple[str, ...] = ()
    has_visible_cost: bool = False


@dataclass(frozen=True)
class LevelGapCase:
    player_level: int
    monster_level: int
    evidence_text: str
    cost_text: str


def assess_level_gap(
    *,
    player_level: int,
    monster_level: int,
    evidence_text: str,
    cost_text: str | None = None,
) -> LevelGapAssessment:
    gap = monster_level - player_level
    if gap <= MAX_NORMAL_LEVEL_GAP:
        return LevelGapAssessment(allowed=True, gap=gap, requires_special_reason=False)

    reasons = tuple(
        code
        for code, markers in SPECIAL_REASON_MARKERS
        if any(marker in evidence_text for marker in markers)
    )
    has_cost = any(marker in (cost_text if cost_text is not None else evidence_text) for marker in COST_MARKERS)
    return LevelGapAssessment(
        allowed=bool(reasons) and has_cost,
        gap=gap,
        requires_special_reason=True,
        reason_codes=reasons,
        has_visible_cost=has_cost,
    )


def _panel_owner_levels(body: str) -> list[tuple[str, int, int]]:
    panels = list(re.finditer(r"【\s*([^】]+?)\s*】", body))
    results: list[tuple[str, int, int]] = []
    field_prefixes = ("等级", "生命", "法力", "经验", "攻击方式", "技能", "特性", "职业", "背包", "钱袋")
    for index, panel in enumerate(panels):
        content = panel.group(1).strip()
        level_match = re.search(r"等级\s*[：:]\s*(?:Lv\.?\s*)?(\d+)", content, re.I)
        if not level_match:
            continue
        owner = ""
        for previous in reversed(panels[max(0, index - 4) : index]):
            candidate = previous.group(1).strip()
            if not candidate.startswith(field_prefixes):
                owner = candidate
                break
        if owner:
            results.append((owner, int(level_match.group(1)), panel.end()))
    return results


def extract_level_gap_case(body: str, context_text: str = "") -> LevelGapCase | None:
    owner_levels = _panel_owner_levels(body)
    player = next(
        ((owner, level, end) for owner, level, end in owner_levels if any(token in owner for token in ("夜烬", "游戏ID", "玩家", "角色"))),
        None,
    )
    if player is not None:
        for owner, monster_level, panel_end in owner_levels:
            if (owner, monster_level, panel_end) == player or panel_end <= player[2]:
                continue
            owner_name = re.split(r"[（(【\s]", owner, maxsplit=1)[0].strip()
            kill_match = re.search(rf"击杀(?:了)?[^。！？\n]{{0,12}}{re.escape(owner_name)}|击杀", body[panel_end:])
            if not kill_match:
                continue
            kill_start = panel_end + kill_match.start()
            sentence_end = re.search(r"[。！？\n]", body[kill_start:])
            cost_end = kill_start + (sentence_end.end() if sentence_end else min(160, len(body) - kill_start))
            evidence = "\n".join(item for item in (context_text.strip(), body[:kill_start]) if item)
            return LevelGapCase(
                player_level=player[1],
                monster_level=monster_level,
                evidence_text=evidence,
                cost_text=body[:cost_end],
            )

    player_levels: list[tuple[int, int]] = []
    for pattern in (
        r"角色面板[^。！？\n]{0,220}?等级\s*(?:Lv\.?\s*)?(\d+)",
        r"等级提升至\s*(?:Lv\.?\s*)?(\d+)",
        r"当前等级\s*[：:]?\s*(?:Lv\.?\s*)?(\d+)",
    ):
        player_levels.extend((match.start(), int(match.group(1))) for match in re.finditer(pattern, body, re.I))

    monster_pattern = re.compile(
        r"(?:系统(?:弹出)?信息|怪物信息)\s*[：:]\s*([^，,。！？\n]{1,40})[，,]\s*等级\s*(?:Lv\.?\s*)?(\d+)",
        re.I,
    )
    for monster in monster_pattern.finditer(body):
        prior_levels = [(position, level) for position, level in player_levels if position < monster.start()]
        if not prior_levels:
            continue
        owner_name = re.split(r"[（(\s]", monster.group(1).strip(), maxsplit=1)[0]
        kill_match = re.search(rf"击杀(?:了)?[^。！？\n]{{0,12}}{re.escape(owner_name)}|击杀", body[monster.end() :])
        if not kill_match:
            continue
        kill_start = monster.end() + kill_match.start()
        sentence_end = re.search(r"[。！？\n]", body[kill_start:])
        cost_end = kill_start + (sentence_end.end() if sentence_end else min(160, len(body) - kill_start))
        evidence = "\n".join(item for item in (context_text.strip(), body[:kill_start]) if item)
        return LevelGapCase(
            player_level=max(prior_levels, key=lambda item: item[0])[1],
            monster_level=int(monster.group(2)),
            evidence_text=evidence,
            cost_text=body[:cost_end],
        )
    return None


def level_gap_rule_text() -> str:
    return (
        "怪物等级高出1至2级可以挑战，但要体现难度和消耗；高出3级及以上默认不能正常单杀，"
        "只有提前建立的组队、任务道具、明确克制、特殊装备、地形机关、怪物残血或既有特殊能力才能例外，"
        "并且必须写出受伤、补给或装备消耗。走位、计算和操作不能单独构成越级理由。"
    )
