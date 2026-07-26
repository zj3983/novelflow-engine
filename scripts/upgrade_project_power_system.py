from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from packages.story_core.power_systems import (  # noqa: E402
    legacy_power_summary,
    validate_power_system_spec,
)
from packages.story_core.world_blueprint_context import (  # noqa: E402
    MANAGED_MARKER,
    render_power_markdown,
)


_PATH_DETAILS = (
    {
        "name": "战士",
        "role": "前排承伤、近战压制与队伍保护",
        "core_attributes": ["力量", "体质"],
        "core_resource": "怒气：承伤与近战命中积累，脱战后逐步消退",
        "weapons": ["剑盾", "双手重武器"],
        "armor": ["重甲", "板甲"],
        "skill_categories": ["格挡嘲讽", "冲锋控制", "重击爆发"],
        "combat_loop": "贴近目标建立怒气，以控制稳住仇恨，再用防御或爆发技能收束循环",
        "strengths": ["正面承伤稳定", "近战控制可靠"],
        "weaknesses": ["远程追击能力有限", "脱离治疗后续航下降"],
        "branches": ["守护骑士", "狂战士"],
        "transfer_task": "Lv.30在守城试炼中选择护住队友或以限时斩杀证明道路，分别解锁守护骑士或狂战士",
        "advancement": ["Lv.10成为正式战士", "Lv.20完成武器或防护专精", "Lv.60通过古战场传承任务取得战争权柄"],
    },
    {
        "name": "法师",
        "role": "远程法术输出、区域控制与元素解题",
        "core_attributes": ["智力", "精神"],
        "core_resource": "法力：施法消耗，通过脱战冥想、补给与特定技能恢复",
        "weapons": ["法杖", "法典", "法器"],
        "armor": ["布甲", "法袍"],
        "skill_categories": ["元素法术", "奥术控制", "护盾与位移"],
        "combat_loop": "辨认抗性后施加元素状态，以控制创造施法窗口，再用高效法术完成爆发并管理法力",
        "strengths": ["远程爆发强", "能用元素组合处理群体与环境"],
        "weaknesses": ["近身容错低", "法力枯竭后输出显著下降"],
        "branches": ["元素宗师", "奥术贤者"],
        "transfer_task": "主角Lv.10通过元素回廊成为元素法师；Lv.20完成元素专精而不再次转职；Lv.30完成元素共鸣试炼选择元素宗师，另一分支为奥术贤者",
        "advancement": ["见习者掌握基础火球等通用法术", "Lv.10正式路线为元素法师", "Lv.20取得元素专精，不发生转职", "Lv.30进阶元素宗师", "Lv.60完成元素权柄传承"],
    },
    {
        "name": "游侠",
        "role": "远程持续输出、侦察追踪与野外控制",
        "core_attributes": ["敏捷", "感知"],
        "core_resource": "专注：保持距离、命中弱点与追踪目标时积累，被近身或失去视野时中断",
        "weapons": ["长弓", "短弓", "弩"],
        "armor": ["皮甲", "轻甲"],
        "skill_categories": ["精准射击", "陷阱追踪", "野兽协同"],
        "combat_loop": "侦察标记目标，以走位和陷阱保持射程，消耗专注连续命中弱点",
        "strengths": ["远程弓手的稳定输出", "野外追踪与地形利用优秀"],
        "weaknesses": ["狭窄地形易被贴身", "专注循环依赖视野"],
        "branches": ["神射手", "荒野猎王"],
        "transfer_task": "Lv.30完成远距弱点射击或荒野追猎试炼，选择神射手或荒野猎王；流霜现有远程弓手路线归入游侠，并在Lv.20进入猎人专精",
        "advancement": ["Lv.10成为正式游侠", "Lv.20可选择猎人专精强化追踪与材料链", "Lv.60完成群山猎印传承"],
    },
    {
        "name": "盗贼",
        "role": "潜行侦察、单体爆发与机关处理",
        "core_attributes": ["敏捷", "技巧"],
        "core_resource": "连击点：从隐蔽接敌、背击与连续命中获得，终结技消耗",
        "weapons": ["匕首", "短剑"],
        "armor": ["皮甲", "轻甲"],
        "skill_categories": ["潜行背刺", "毒药机关", "欺诈脱离"],
        "combat_loop": "隐蔽接近并制造破绽，积累连击点打出终结技，随后脱离重置",
        "strengths": ["单体爆发高", "情报与机关处理灵活"],
        "weaknesses": ["正面持久战薄弱", "显形后容易被控制"],
        "branches": ["影刃", "诡术师"],
        "transfer_task": "Lv.30在无警报潜入与误导追兵两项试炼中择一，解锁影刃或诡术师",
        "advancement": ["Lv.10成为正式盗贼", "Lv.20选择暗杀或机关专精", "Lv.60继承无面者密契"],
    },
    {
        "name": "牧师",
        "role": "治疗恢复、团队减伤与异常净化",
        "core_attributes": ["精神", "意志"],
        "core_resource": "信念：有效治疗、净化与维持戒律积累，强力祷术消耗",
        "weapons": ["权杖", "圣典"],
        "armor": ["布甲", "轻甲"],
        "skill_categories": ["治疗祷术", "护佑净化", "戒律惩击"],
        "combat_loop": "预判伤害施加护佑，以治疗和净化稳定队伍，再消耗信念处理致命窗口",
        "strengths": ["团队续航强", "能解除多类负面状态"],
        "weaknesses": ["单独输出有限", "被打断时团队风险陡增"],
        "branches": ["圣愈者", "戒律祭司"],
        "transfer_task": "Lv.30完成无减员救援或戒律审判试炼，选择圣愈者或戒律祭司",
        "advancement": ["Lv.10成为正式牧师", "Lv.20选择治疗或戒律专精", "Lv.60接受圣所传承"],
    },
    {
        "name": "召唤师",
        "role": "召唤物调度、战场牵制与多单位协同",
        "core_attributes": ["精神", "感知"],
        "core_resource": "契约槽与心神：召唤物占用契约槽，指令和维持消耗心神",
        "weapons": ["召唤杖", "契约书"],
        "armor": ["布甲", "轻甲"],
        "skill_categories": ["契约召唤", "兽群指令", "献祭增幅"],
        "combat_loop": "按敌情配置契约单位，以站位和指令形成牵制，再轮换或献祭召唤物完成压制",
        "strengths": ["战场覆盖面广", "能以不同召唤物适配敌情"],
        "weaknesses": ["本体防护较弱", "召唤物阵亡会造成资源与心神压力"],
        "branches": ["契约领主", "兽群主宰"],
        "transfer_task": "Lv.30完成平等契约或多兽统御试炼，选择契约领主或兽群主宰",
        "advancement": ["Lv.10成为正式召唤师", "Lv.20选择契约或兽群专精", "Lv.60取得万灵契约传承"],
    },
)


def _build_power_system_spec() -> dict[str, Any]:
    spec = {
        "name": "神域职业力量体系",
        "origin": [
            "玩家以见习者身份接入神域，力量来自职业任务授予的规则权限",
            "技能书、导师训练、装备与区域传承扩展能力，但都受等级和职业路线限制",
        ],
        "attributes": [
            {"name": "力量", "effect": "影响近战伤害、负重与部分强制对抗"},
            {"name": "体质", "effect": "影响生命、防御与异常耐受"},
            {"name": "敏捷", "effect": "影响攻速、移动、闪避与远程武器操控"},
            {"name": "智力", "effect": "影响法术强度、元素理解与法力效率"},
            {"name": "精神", "effect": "影响法力、治疗、召唤维持与意志抗性"},
            {"name": "感知", "effect": "影响命中、侦察、追踪与弱点发现"},
        ],
        "paths": deepcopy(list(_PATH_DETAILS)),
        "stages": [
            {"name": "见习者", "level": 1, "entry": "创建角色并完成新手引导", "change": "获得基础属性、通用武器和初始技能选择，尚无正式职业", "failure": "引导未完成则不能离开新手区或接取职业任务"},
            {"name": "正式职业", "level": 10, "entry": "达到Lv.10并完成所选基础职业任务；主角通过元素回廊成为元素法师", "change": "确定六大职业之一，解锁职业资源、装备适性和核心技能循环", "failure": "任务失败只会进入重试冷却并消耗已投入的任务材料，不授予职业身份"},
            {"name": "职业专精", "level": 20, "entry": "达到Lv.20并在原正式职业内完成专精试炼", "change": "强化既有职业的技能类别与属性倾向；主角取得元素专精，流霜取得猎人专精", "failure": "专精暂缓且试炼材料受损，原正式职业保持不变"},
            {"name": "进阶分支", "level": 30, "entry": "达到Lv.30并完成可验证的分支转职任务", "change": "从每条职业路线至少两个分支中锁定进阶方向；主角选择元素宗师", "failure": "分支解锁延期并承担任务冷却或声望损失，不能免费改选"},
            {"name": "传承职业", "level": 60, "entry": "达到Lv.60、满足分支成就并通过唯一性传承试炼", "change": "取得受世界规则约束的高阶职业权柄；主角完成元素权柄传承", "failure": "传承资格冻结并留下可追踪的反噬状态，需修复条件后再挑战"},
        ],
        "skills": [
            "技能通过职业导师、技能书、任务与传承获得，解锁必须记录来源和前置条件",
            "主动、被动、控制、位移与生活技能均受职业适性、冷却和资源消耗约束",
        ],
        "equipment": [
            "武器和护甲具有等级、职业适性、耐久与属性需求，越级装备不能绕过使用条件",
            "装备词条改变战斗方案但不直接授予职业身份、任务权限或永久技能",
        ],
        "resources": [
            "经验决定等级进度，技能点、职业材料、装备耐久和补给共同限制成长节奏",
            "怒气、法力、专注、连击点、信念、契约槽与心神各按职业循环产出和消耗",
        ],
        "advancement": [
            "统一里程碑为见习者 -> Lv.10正式职业 -> Lv.20职业专精 -> Lv.30进阶分支 -> Lv.60传承职业",
            "主角路线为见习者 -> 元素法师 -> 元素专精 -> 元素宗师 -> 元素权柄传承",
            "流霜的远程弓手与猎人能力归入游侠路线，Lv.20为猎人专精而非新职业",
        ],
        "costs": [
            "死亡会造成时间、耐久和状态代价，任务失败会带来冷却、材料损失或声望影响",
            "强力技能消耗职业资源并承担冷却、站位或施法窗口，传承权柄还会积累反噬",
        ],
        "counters": [
            "突进与打断克制远程蓄力，净化克制持续异常，侦察和范围技能克制潜行",
            "护甲、元素抗性、控制抗性和地形共同决定职业克制，单一等级不能抹平全部机制",
        ],
        "boundaries": [
            "等级差提供属性和技能压制；越级必须依赖情报、配装、队伍、地形或明确弱点",
            "混沌之种只改变合规掉落结果，不能赠送经验、职业身份、任务完成、NPC权限或无来源技能",
        ],
        "social_impact": [
            "公会按前排、输出、治疗、侦察和控制职责组队，稀缺专精会影响招募与副本分配",
            "职业导师、传承组织和区域声望控制高阶任务入口，失败与违约会改变NPC态度",
        ],
        "visibility": [
            "公开面板可见等级、正式职业和已展示装备，专精细节、隐藏技能与任务进度默认不可见",
            "战斗日志只能记录实际发生的技能、伤害和状态变化，推断不能当作已确认事实",
        ],
        "continuity_ledger": [
            "level", "class_path", "skills", "equipment", "resources", "conditions",
            "attribute_allocations", "advancement_tasks", "cooldowns", "reputation_permissions",
        ],
    }
    return validate_power_system_spec(spec, novel_type_id="game_webnovel")


_LEVEL_TWENTY = re.compile(r"(?i)(?:lv\.?\s*20|20\s*级)")
_CONTRADICTORY_LEVEL_TWENTY = re.compile(
    r"第二次\s*(?:职业)?(?:转职|晋升|进阶)|再次\s*(?:职业)?转职|二次\s*(?:职业)?转职|二转|第二职业\s*(?:晋升|进阶)"
)
_LEVEL_TEN = re.compile(r"(?i)(?:lv\.?\s*10|10\s*级)")


def _clean_outline_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        changed = False
        result = {}
        for key, item in value.items():
            cleaned, item_changed = _clean_outline_value(item)
            result[key] = cleaned
            changed = changed or item_changed
        return result, changed
    if isinstance(value, list):
        changed = False
        result = []
        for item in value:
            cleaned, item_changed = _clean_outline_value(item)
            result.append(cleaned)
            changed = changed or item_changed
        return result, changed
    if not isinstance(value, str):
        return value, False

    cleaned = value
    if _LEVEL_TWENTY.search(cleaned):
        cleaned = _CONTRADICTORY_LEVEL_TWENTY.sub("职业专精", cleaned)
    if _LEVEL_TEN.search(cleaned) and "正式法系职业" in cleaned:
        cleaned = cleaned.replace("正式法系职业", "元素法师")
    return cleaned, cleaned != value


def _read_json(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), raw


def _serialization_style(raw: bytes) -> tuple[int | str | None, str, bool, bool]:
    decoded = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in decoded else "\n"
    match = re.search(r"(?:\r?\n)([ \t]+)\"", decoded)
    indent: int | str | None
    if match:
        whitespace = match.group(1)
        indent = "\t" if "\t" in whitespace else len(whitespace)
    else:
        indent = None
    return indent, newline, decoded.endswith(("\n", "\r")), raw.startswith(b"\xef\xbb\xbf")


def _encode_json(value: Any, source: bytes) -> bytes:
    indent, newline, trailing_newline, bom = _serialization_style(source)
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    if newline != "\n":
        text = text.replace("\n", newline)
    if trailing_newline:
        text += newline
    encoded = text.encode("utf-8")
    return (b"\xef\xbb\xbf" + encoded) if bom else encoded


def _is_managed_markdown(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return handle.readline().rstrip("\r\n") == MANAGED_MARKER
    except UnicodeDecodeError:
        return False


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _backup(metadata_dir: Path, project_bytes: bytes, outline_bytes: bytes) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = metadata_dir / "backups" / f"power-system-{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "project.json").write_bytes(project_bytes)
    (destination / "outline.json").write_bytes(outline_bytes)
    return destination


def upgrade_project(
    project_dir: str | Path, *, check: bool = False, backup: bool = True
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "changed": False,
        "valid": False,
        "backup_path": None,
        "changes": [],
    }
    try:
        root = Path(project_dir).resolve()
        metadata = root / ".webnovel"
        project_path = metadata / "project.json"
        outline_path = metadata / "outline.json"
        project, project_bytes = _read_json(project_path)
        outline, outline_bytes = _read_json(outline_path)
        if not isinstance(project, dict) or not isinstance(outline, (dict, list)):
            raise ValueError("project.json and outline.json must contain JSON objects or arrays")

        migrated_project = deepcopy(project)
        blueprint = migrated_project.setdefault("world_blueprint", {})
        if not isinstance(blueprint, dict):
            raise ValueError("project.json world_blueprint must be an object")
        spec = _build_power_system_spec()
        blueprint["power_system_spec"] = spec
        blueprint["power_system"] = legacy_power_summary(spec)
        validate_power_system_spec(blueprint["power_system_spec"], novel_type_id="game_webnovel")

        migrated_outline, outline_changed = _clean_outline_value(outline)
        expected_project_bytes = _encode_json(migrated_project, project_bytes)
        expected_outline_bytes = (
            _encode_json(migrated_outline, outline_bytes) if outline_changed else outline_bytes
        )
        project_changed = expected_project_bytes != project_bytes
        outline_file_changed = expected_outline_bytes != outline_bytes

        power_path = root / "设定集" / "力量体系.md"
        expected_power = render_power_markdown(project.get("title"), blueprint).encode("utf-8")
        power_exists = power_path.exists()
        power_managed = power_exists and _is_managed_markdown(power_path)
        current_power = power_path.read_bytes() if power_exists else None
        power_changed = (not power_exists or power_managed) and current_power != expected_power

        changes: list[str] = []
        if project_changed:
            changes.append("project.json: power system upgraded")
        if outline_file_changed:
            changes.append("outline.json: contradictory progression wording updated")
        if power_changed:
            changes.append(
                "设定集/力量体系.md: refreshed" if power_exists else "设定集/力量体系.md: created"
            )
        elif power_exists and not power_managed:
            changes.append("设定集/力量体系.md: skipped unmanaged")

        will_write = project_changed or outline_file_changed or power_changed
        result.update(changed=will_write, valid=True, changes=changes)
        if check or not will_write:
            return result

        if backup:
            backup_path = _backup(metadata, project_bytes, outline_bytes)
            result["backup_path"] = str(backup_path)
        if project_changed:
            _atomic_write(project_path, expected_project_bytes)
        if outline_file_changed:
            _atomic_write(outline_path, expected_outline_bytes)
        if power_changed:
            _atomic_write(power_path, expected_power)
        return result
    except Exception as exc:
        return {
            "changed": False,
            "valid": False,
            "backup_path": result.get("backup_path"),
            "changes": [f"error: {type(exc).__name__}: {exc}"],
        }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Upgrade a legacy file project's power system")
    parser.add_argument("project_dir")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args(argv)
    result = upgrade_project(args.project_dir, check=args.check, backup=not args.no_backup)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
