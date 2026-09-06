from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from packages.story_core.chapter_state_helpers import without_monster_stat_surfaces
from packages.story_core.character_profiles import is_non_character_card


class ChapterEntityProjectionMixin:
    """Project accepted chapter text into durable ledgers and entity cards."""

    def _dedupe_numbered_records(self, items: list[Any], *, limit: int = 240) -> list[Any]:
        """Keep one structured record per chapter and drop stale manual shells."""

        records: list[Any] = []
        seen_titles_by_number: dict[int, str] = {}
        for item in items:
            if isinstance(item, dict):
                try:
                    number = int(item.get("chapter_number") or 0)
                except (TypeError, ValueError):
                    number = 0
                title = str(item.get("chapter_title") or "").strip()
                if number > 0:
                    seen_titles_by_number[number] = title
                    records = [
                        existing
                        for existing in records
                        if not (
                            isinstance(existing, dict)
                            and int(existing.get("chapter_number") or 0) == number
                        )
                    ]
                    records.append(item)
                    continue
                if title and title not in seen_titles_by_number.values():
                    records.append(item)
                continue
            if isinstance(item, str) and re.match(r"^\s*chapter\s+\d+\s*:", item, re.IGNORECASE):
                continue
            records.append(item)
        numbered_titles = {title for title in seen_titles_by_number.values() if title}
        records = [
            item
            for item in records
            if not (
                isinstance(item, dict)
                and not int(item.get("chapter_number") or 0)
                and str(item.get("chapter_title") or "").strip() in numbered_titles
            )
        ]
        records.sort(key=lambda item: int(item.get("chapter_number") or 0) if isinstance(item, dict) else 0)
        return records[-limit:]

    def _derive_opening_progression_ledger(self, chapters: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
        """Rebuild the current game ledger from accepted opening chapters."""

        ledger = dict(current)
        text = "\n".join(
            str(part or "")
            for chapter in chapters
            for part in (
                chapter.get("body"),
                (chapter.get("chapter_summary") or {}).get("summary"),
                "\n".join(str(item) for item in ((chapter.get("chapter_summary") or {}).get("facts") or [])),
                (chapter.get("chapter_summary") or {}).get("next_focus"),
            )
        )
        progression_text = "\n".join(
            without_monster_stat_surfaces(str(chapter.get("body") or ""))
            for chapter in chapters
        )
        protagonist = dict(ledger.get("protagonist") or {})
        panel = dict(ledger.get("panel") or {})
        economy = dict(ledger.get("economy") or {})
        equipment = dict(ledger.get("equipment") or {})
        quests = dict(ledger.get("quests") or {})
        level_matches = re.findall(
            r"(?:等级提升至|升级到|升级至|升到|当前等级[：:]?|等级[：:]?|level\s*[:=]?)\s*(?:Lv\.?)?\s*(\d+)",
            progression_text,
            flags=re.IGNORECASE,
        )
        compact_panel_levels = re.findall(
            r"【[^】]{1,24}；\s*Lv\.?\s*(\d+)(?=[^】]{0,24}(?:经验|生命|法力|可用属性点))",
            progression_text,
            flags=re.IGNORECASE,
        )
        if compact_panel_levels:
            level_matches = compact_panel_levels
        if not level_matches and "Lv.2" in progression_text and any(
            token in progression_text for token in ("升到", "升级", "等级", "提升")
        ):
            level_matches = ["2"]
        if level_matches:
            level = f"Lv.{int(level_matches[-1])}"
            protagonist["level"] = level
            panel["level"] = level
        if "见习者" in text or "见习冒险者" in text or "未转职" in text:
            protagonist["identity"] = "见习者（未转职）"
            protagonist["class_path"] = "见习者（未转职）"
            panel["identity"] = "见习者（未转职）"

        exp_matches = re.findall(r"经验\s*([0-9]+\s*/\s*[0-9]+)", progression_text)
        if exp_matches:
            protagonist["exp"] = re.sub(r"\s+", "", exp_matches[-1])
        elif "等级升到Lv.2" in text or "Lv.2" in text:
            protagonist.setdefault("exp", "12/200")

        durability_matches = re.findall(
            r"(?:新手法杖[：:]\s*|法杖[^，。；\n]{0,12})(\d{1,2}\s*/\s*\d{1,2})",
            progression_text,
        )
        if durability_matches:
            equipment["weapon"] = "新手法杖"
            equipment["durability"] = re.sub(r"\s+", "", durability_matches[-1])
            protagonist["weapon_durability"] = f"新手法杖：{equipment['durability']}"
        elif "新手法杖" in text:
            equipment.setdefault("weapon", "新手法杖")

        inventory = self._derive_opening_inventory(chapters)
        if inventory:
            economy["inventory"] = inventory
        if "钱袋：空" in text or "钱袋空" in text or "钱袋又空" in text:
            economy["game_currency"] = "空"
        elif "30铜" in text or "三十铜" in text:
            economy["game_currency"] = "30铜"
        real_balance_matches = re.findall(
            r"(?:银行卡可用余额|现实余额|可用余额|账户余额|余额)\s*(?:[：:]\s*)?(?:只剩|还有|变成|变为|为)?\s*(\d+(?:\.\d{1,2})?)\s*元",
            text,
        )
        if real_balance_matches:
            economy["real_balance"] = f"{real_balance_matches[-1]}元"
        if "清道夫委托已提交" in text or "清道夫委托完成" in text:
            quests["清道夫委托"] = "已提交；奖励30铜已领取"
        if "后坡登记" in text:
            quests["后坡登记"] = "清道夫委托完成后已开启，夜烬已进入后坡第一段"
        if "灰石裂缝" in text:
            quests["灰石裂缝"] = "已发现；混沌之种出现第二次响应"

        if protagonist:
            ledger["protagonist"] = protagonist
        if panel:
            ledger["panel"] = panel
        if economy:
            ledger["economy"] = economy
            ledger.pop("currency", None)
            ledger.pop("inventory", None)
        if equipment:
            ledger["equipment"] = equipment
        if quests:
            ledger["quests"] = quests
        return ledger

    def _chapter_text_for_ledger(self, chapter: dict[str, Any]) -> str:
        summary = chapter.get("chapter_summary") if isinstance(chapter.get("chapter_summary"), dict) else {}
        return "\n".join(
            str(part or "")
            for part in (
                chapter.get("body"),
                summary.get("summary"),
                "\n".join(str(item) for item in (summary.get("facts") or [])),
                summary.get("next_focus"),
            )
        )

    def _derive_opening_inventory(self, chapters: list[dict[str, Any]]) -> dict[str, int]:
        inventory: dict[str, int] = {}
        tracked = {"灰狼毒腺", "粗糙狼皮", "小法力药水"}
        for chapter in sorted(chapters, key=lambda item: int(item.get("chapter_number") or 0)):
            text = self._chapter_text_for_ledger(chapter)
            scoped_backpacks = [
                item
                for item in re.findall(r"背包[^。\n】]*", text)
                if any(name in item and "×" in item for name in tracked)
            ]
            if scoped_backpacks:
                scoped: dict[str, int] = {}
                for name, count in re.findall(r"([\u4e00-\u9fa5A-Za-z0-9·]+)\s*[×xX]\s*(\d+)", scoped_backpacks[-1]):
                    if name in tracked:
                        scoped[name] = int(count)
                if scoped:
                    inventory.update(scoped)
            if "清道夫委托已提交" in text or "清道夫委托完成" in text:
                inventory["灰狼毒腺"] = 0
            if int(chapter.get("chapter_number") or 0) > 2:
                for name, count in re.findall(r"([\u4e00-\u9fa5A-Za-z0-9·]+)\s*[×xX]\s*(\d+)", text):
                    if name in {"灰狼毒腺", "粗糙狼皮"}:
                        inventory[name] = int(inventory.get(name, 0)) + int(count)
            if "喝掉了小法力药水" in text and inventory.get("小法力药水", 0) > 0:
                inventory["小法力药水"] = int(inventory["小法力药水"]) - 1
        return inventory

    def _character_names_in_chapter(self, state: dict[str, Any], chapter: dict[str, Any]) -> list[str]:
        directed_names = [
            str(move.get("name") or "").strip()
            for move in (
                chapter.get("character_moves", [])
                if isinstance(chapter.get("character_moves"), list)
                else []
            )
            if isinstance(move, dict)
            and str(move.get("kind") or "character").strip().lower() == "character"
            and str(move.get("name") or "").strip()
        ]
        if directed_names:
            return self._merge_unique([], directed_names, limit=16)
        text = "\n".join(
            [
                str(chapter.get("chapter_title") or ""),
                str(chapter.get("body") or ""),
                str((chapter.get("chapter_summary") or {}).get("summary") or ""),
            ]
        )
        names: list[str] = []
        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict):
                continue
            name = str(character.get("name") or "").strip()
            game_id = str(character.get("game_id") or (character.get("game_panel") or {}).get("game_id") or "").strip()
            aliases = [
                str(alias).strip()
                for alias in (character.get("aliases") or [])
                if str(alias).strip()
            ]
            identity = character.get("identity_profile")
            if isinstance(identity, dict):
                aliases.extend(
                    str(alias).strip()
                    for alias in (identity.get("aliases") or [])
                    if str(alias).strip()
                )
            if (
                (name and name in text)
                or (game_id and game_id in text)
                or any(alias in text for alias in aliases)
            ):
                names.append(name or game_id)
        return self._merge_unique([], names, limit=16)

    def _chapter_entity_cards(self, chapter: dict[str, Any]) -> list[dict[str, Any]]:
        """Infer trackable NPC/system cards from visible chapter text.

        Web-game chapters often introduce durable entities as services or
        information surfaces rather than named people. They still need cards so
        later simulation can remember their boundaries.
        """
        chapter_number = int(chapter.get("chapter_number") or 0)
        text = "\n".join(
            [
                str(chapter.get("chapter_title") or ""),
                str(chapter.get("body") or ""),
                str((chapter.get("chapter_summary") or {}).get("summary") or ""),
            ]
        )
        specs = [
            {
                "name": "论坛",
                "triggers": ("论坛", "帖子"),
                "role": "信息源",
                "location": "内置论坛",
                "goal": "提供玩家传闻、掉率基准、价格噪声和开服情报",
                "memory": "论坛已出现为开服信息源：掉率、坐标、材料价格和玩家抱怨都从这里进入叙事。",
                "active": True,
            },
            {
                "name": "公共频道",
                "triggers": ("公共频道", "世界频道"),
                "role": "玩家群体",
                "location": "聊天频道",
                "goal": "暴露散人玩家情绪、抢怪冲突、组队需求和即时传闻",
                "memory": "公共频道持续滚动玩家喊话，是低可信但高频的世界噪声。",
                "active": False,
            },
            {
                "name": "交易行告示牌",
                "triggers": ("交易行", "告示牌", "求购："),
                "role": "市场机制",
                "location": "起始村广场",
                "goal": "显示求购单、均价、成交量和区域材料流通预警",
                "memory": "交易行告示牌已显示灰狼毒腺求购、均价和材料流通预警，是经济线的可见界面。",
                "active": True,
            },
            {
                "name": "药剂师NPC",
                "triggers": ("药剂师", "药剂铺"),
                "role": "服务NPC",
                "location": "起始村药剂铺",
                "goal": "按规则收取任务材料、出售法力药水并提示下一环任务",
                "memory": "药剂师NPC负责委托、药水价格和材料提交，话术机械且边界明确。",
                "active": True,
            },
            {
                "name": "药剂铺老妇人",
                "triggers": ("灰头巾老妇人", "老妇人", "药剂铺"),
                "role": "服务NPC",
                "location": "起始村药剂铺",
                "goal": "执行药剂铺收货规则：十份一批，少了不收",
                "memory": "药剂铺老妇人明确毒腺十份一批，不零收；单份交易需走交易木牌。",
                "active": False,
            },
            {
                "name": "清道夫委托",
                "triggers": ("清道夫委托", "提交十份灰狼毒腺"),
                "role": "任务线",
                "location": "起始村药剂铺",
                "goal": "用灰狼毒腺回收驱动新手任务，并逐步提高材料要求",
                "memory": "清道夫委托一环需要十份灰狼毒腺，奖励三十铜；下一环需要灰狼心脏。",
                "active": True,
            },
            {
                "name": "铁匠铺自助修理台",
                "triggers": ("自助修理台", "铁匠铺", "修复新手法杖"),
                "role": "服务设施",
                "location": "起始村铁匠铺",
                "goal": "提供装备修复并扣除铜币",
                "memory": "铁匠铺自助修理台可修复新手法杖，当前修复成本为三铜。",
                "active": False,
            },
            {
                "name": "系统公告",
                "triggers": ("系统滚动条", "系统公告", "区域材料流通预警"),
                "role": "系统机制",
                "location": "玩家界面",
                "goal": "以可见公告暴露协议提示、任务进度和风险变化",
                "memory": "系统公告/滚动条已用于呈现底层协议、隐藏优势和任务/路线进度反馈。",
                "active": True,
            },
        ]
        cards: list[dict[str, Any]] = []
        for spec in specs:
            if not any(trigger and trigger in text for trigger in spec["triggers"]):
                continue
            active = bool(spec["active"])
            active_triggers = spec.get("active_triggers")
            if isinstance(active_triggers, tuple) and any(trigger and trigger in text for trigger in active_triggers):
                active = True
            cards.append(
                {
                    "name": spec["name"],
                    "role": spec["role"],
                    "game_id": "",
                    "goals": [spec["goal"]],
                    "memory": [f"第{chapter_number}章：{spec['memory']}"] if chapter_number else [spec["memory"]],
                    "relationships": {},
                    "current_emotion": "steady",
                    "location": spec["location"],
                    "secrets": [],
                    "frozen": False,
                    "lifecycle_state": "active" if active else "proposed",
                    "last_proposed_chapter": chapter_number,
                    "last_approved_chapter": chapter_number if active else 0,
                    "introduced_by": f"chapter:{chapter_number}" if chapter_number else "chapter",
                    "npc_profile": {
                        "service_role": spec["role"],
                        "authority_scope": [spec["goal"]],
                        "information_limits": ["只能提供正文已可见的信息，不替作者解释规则。"],
                        "incentives": [],
                        "interaction_rules": ["作为界面、服务或NPC边界参与推演。"],
                    },
                }
            )
        return cards

    def _outline_text_for_chapter(self, project: dict[str, Any], chapter_number: int) -> str:
        blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        opening_arc = blueprint.get("opening_arc") if isinstance(blueprint.get("opening_arc"), dict) else {}
        beats = opening_arc.get("chapter_beats") if isinstance(opening_arc.get("chapter_beats"), list) else []
        parts = [str(project.get("current_focus") or ""), str(blueprint.get("current_arc") or "")]
        for beat in beats:
            if isinstance(beat, dict) and int(beat.get("chapter") or 0) == chapter_number:
                parts.extend(str(beat.get(key) or "") for key in ("title", "required_payoff", "ending_hook"))
        return "\n".join(parts)

    def _proposed_character_cards_from_outline(self, state: dict[str, Any], project: dict[str, Any]) -> list[dict[str, Any]]:
        target = int(state.get("current_chapter") or 0) + 1
        text = self._outline_text_for_chapter(project, target)
        specs: list[dict[str, Any]] = []
        if "村长" in text:
            specs.append(
                {
                    "name": "灰烬村村长",
                    "role": "村内任务NPC",
                    "location": "灰烬村",
                    "goals": ["只按村内记录和任务前置放行，不主动透露隐藏线。"],
                    "memory": [f"第{target}章大纲可能需要村长承接灰石裂缝记录。"],
                    "character_type": "任务节点NPC",
                    "core_motivation": "维护村内任务秩序，避免异常记录扩散。",
                    "behavior_logic": "只承认可见记录，不承认玩家猜测。",
                    "interaction_mode": "说话像办手续，能给的只给一半。",
                    "story_function": "承接隐藏路线和任务权限。",
                    "chapter_role": f"第{target}章待出场",
                }
            )
        cards: list[dict[str, Any]] = []
        for spec in specs:
            cards.append(
                {
                    **spec,
                    "current_emotion": "steady",
                    "frozen": False,
                    "lifecycle_state": "proposed",
                    "last_proposed_chapter": target,
                    "last_approved_chapter": 0,
                    "introduced_by": f"outline:{target}",
                    "npc_profile": {
                        "service_role": spec["role"],
                        "authority_scope": spec["goals"],
                        "information_limits": ["出场前只作为写作包候选卡；正文未写到之前不能当成已出场事实。"],
                        "interaction_rules": ["如果本章使用这个人物，必须先按角色卡写，不得临场换身份。"],
                    },
                }
            )
        return cards

    def _canonical_character_name(self, name: str) -> str:
        aliases = {
            "药剂师NPC": "药剂师洛婶",
            "药剂师": "药剂师洛婶",
            "药剂铺老妇人": "药剂师洛婶",
            "灰头巾老妇人": "药剂师洛婶",
            "老妇人": "药剂师洛婶",
            "洛婶": "药剂师洛婶",
            "补给商·铁栓": "仓库管理员铁栓",
            "补给商铁栓": "仓库管理员铁栓",
            "铁栓": "仓库管理员铁栓",
        }
        return aliases.get(name.strip(), name.strip())

    def _is_character_card(self, card: dict[str, Any]) -> bool:
        name = self._canonical_character_name(str(card.get("name") or ""))
        role = str(card.get("role") or "").strip()
        if not name:
            return False
        if is_non_character_card({**card, "name": name, "role": role}):
            return False
        return True

    def _merge_character_cards(self, existing: list[Any], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_name: dict[str, dict[str, Any]] = {}
        for item in existing:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            name = self._canonical_character_name(str(item.get("name") or ""))
            if name:
                item["name"] = name
            if not self._is_character_card(item):
                continue
            if name:
                by_name[name] = dict(item)
        for card in additions:
            card = dict(card)
            name = self._canonical_character_name(str(card.get("name") or ""))
            if not name:
                continue
            card["name"] = name
            if not self._is_character_card(card):
                continue
            current = dict(by_name.get(name) or {"name": name})
            current["role"] = current.get("role") or card.get("role") or "NPC"
            current["game_id"] = current.get("game_id") or card.get("game_id") or ""
            if card.get("game_panel"):
                panel = dict(current.get("game_panel") or {})
                panel.update({key: value for key, value in dict(card.get("game_panel") or {}).items() if value not in (None, "", [], {})})
                current["game_panel"] = panel
            for field in (
                "character_type",
                "core_motivation",
                "behavior_logic",
                "interaction_mode",
                "story_function",
                "chapter_role",
                "social_profile",
                "psychological_profile",
                "moral_profile",
                "performance_profile",
            ):
                if field == "performance_profile" and isinstance(current.get(field), dict) and isinstance(card.get(field), dict):
                    profile = dict(current[field])
                    legacy_speech = "白话、完整、少装腔；解释选择时把原因说清。"
                    if profile.get("speech_style") == legacy_speech and card[field].get("speech_style"):
                        profile["speech_style"] = card[field]["speech_style"]
                    current[field] = profile
                    continue
                if card.get(field) and not current.get(field):
                    current[field] = card[field]
            current["goals"] = self._merge_unique(list(current.get("goals") or []), list(card.get("goals") or []), limit=8)
            current["memory"] = self._merge_unique(list(current.get("memory") or []), list(card.get("memory") or []), limit=20)
            current["poison_points"] = self._merge_unique(
                list(current.get("poison_points") or []),
                list(card.get("poison_points") or []),
                limit=8,
            )
            current["location"] = card.get("location") or current.get("location") or ""
            current["current_emotion"] = current.get("current_emotion") or card.get("current_emotion") or "steady"
            current["relationships"] = current.get("relationships") or {}
            current["secrets"] = current.get("secrets") or []
            current["frozen"] = bool(current.get("frozen") or False)
            if current.get("lifecycle_state") != "active":
                current["lifecycle_state"] = card.get("lifecycle_state") or current.get("lifecycle_state") or "proposed"
            current["last_proposed_chapter"] = max(
                int(current.get("last_proposed_chapter") or 0),
                int(card.get("last_proposed_chapter") or 0),
            )
            current["last_approved_chapter"] = max(
                int(current.get("last_approved_chapter") or 0),
                int(card.get("last_approved_chapter") or 0),
            )
            current["introduced_by"] = current.get("introduced_by") or card.get("introduced_by") or ""
            if card.get("npc_profile") and not current.get("npc_profile"):
                current["npc_profile"] = card["npc_profile"]
            by_name[name] = current
        return list(by_name.values())

    def _protagonist_character_card(self, state: dict[str, Any], project: dict[str, Any] | None = None) -> dict[str, Any] | None:
        ledger = state.get("progression_ledger") if isinstance(state.get("progression_ledger"), dict) else {}
        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
        if not protagonist:
            return None
        economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
        real = ledger.get("real") if isinstance(ledger.get("real"), dict) else {}
        equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
        quests = ledger.get("quests") if isinstance(ledger.get("quests"), dict) else {}
        project = project if isinstance(project, dict) else {}
        existing_cards = [
            item
            for item in [
                *(state.get("characters") or []),
                *(project.get("character_profiles") or []),
            ]
            if isinstance(item, dict)
        ]
        existing = next(
            (
                item
                for item in existing_cards
                if str(item.get("role") or "").strip().lower() in {"protagonist", "主角"}
            ),
            {},
        )
        name = str(protagonist.get("real_name") or existing.get("name") or "").strip()
        game_id = str(protagonist.get("game_id") or "").strip()
        if not name and not game_id:
            return None
        current_chapter = int(state.get("current_chapter") or 0)
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}
        skills = protagonist.get("skills") if isinstance(protagonist.get("skills"), list) else []
        weapon = str(equipment.get("weapon") or "").strip()
        durability = str(equipment.get("durability") or protagonist.get("weapon_durability") or "").strip()
        current_goal = "推进当前游戏目标。"
        recovered_memory: list[str] = []
        real_balance = real.get("end_balance") or real.get("balance")
        if real_balance:
            recovered_memory.append(f"当前现实余额：{real_balance}。")
        level = protagonist.get("level") or ""
        exp = protagonist.get("exp") or ""
        if level or exp:
            recovered_memory.append(f"当前游戏进度：{level}，经验{exp}。")
        card = deepcopy(existing)
        card.update({
            "name": name or game_id,
            "role": "protagonist",
            "game_id": game_id,
            "memory": recovered_memory,
            "location": str(protagonist.get("location") or state.get("current_location") or ""),
            "game_panel": {
                "game_id": game_id,
                "level": protagonist.get("level") or (ledger.get("panel") or {}).get("level"),
                "class_path": protagonist.get("class_path") or protagonist.get("identity") or "",
                "exp": protagonist.get("exp") or "",
                "hp": protagonist.get("hp") or "",
                "mp": protagonist.get("mp") or "",
                "skills": skills,
                "equipment": {
                    "武器": weapon,
                    "耐久": durability,
                    "强化": equipment.get("modifier") or "",
                },
                "inventory": inventory,
                "currency": economy.get("game_currency") or "",
                "quests": quests,
                "updated_chapter": current_chapter,
            },
            "frozen": False,
            "lifecycle_state": "active",
            "last_proposed_chapter": current_chapter,
            "last_approved_chapter": current_chapter,
            "introduced_by": str(existing.get("introduced_by") or "ledger:protagonist"),
        })
        card.setdefault("goals", [current_goal])
        card.setdefault("current_emotion", "neutral")
        card.setdefault("secrets", [])
        card.setdefault("poison_points", [])
        if real_balance:
            real_state = dict(card.get("real_state") or {})
            current_real = dict(real_state.get("current") or {})
            current_real["balance"] = real_balance
            real_state["current"] = current_real
            card["real_state"] = real_state
        return card

    def _infer_chapter_duration_minutes(self, chapter: dict[str, Any]) -> int:
        text = "\n".join([str(chapter.get("body") or ""), str((chapter.get("chapter_summary") or {}).get("summary") or "")])
        explicit_minutes = [int(value) for value in re.findall(r"(\d{1,3})\s*分钟", text)]
        if explicit_minutes:
            return max(10, min(240, explicit_minutes[-1]))
        explicit_hours = [int(value) for value in re.findall(r"(\d{1,2})\s*小时", text)]
        if explicit_hours:
            return max(30, min(360, explicit_hours[-1] * 60))
        if any(token in text for token in ("回村", "交任务", "修复", "购买", "寄售", "职业大厅")):
            return 45
        if any(token in text for token in ("灰狼坡深处", "副本", "试炼", "赶路", "采样")):
            return 60
        return 40

    def _clock_label(self, minutes_since_launch: int) -> str:
        day = minutes_since_launch // (24 * 60) + 1
        minute_of_day = minutes_since_launch % (24 * 60)
        if minute_of_day < 5 * 60:
            phase = "深夜"
        elif minute_of_day < 8 * 60:
            phase = "清晨"
        elif minute_of_day < 12 * 60:
            phase = "上午"
        elif minute_of_day < 14 * 60:
            phase = "中午"
        elif minute_of_day < 18 * 60:
            phase = "下午"
        elif minute_of_day < 21 * 60:
            phase = "傍晚"
        else:
            phase = "夜晚"
        return f"开服第{day}天{phase}"
