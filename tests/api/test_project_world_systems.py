from apps.api.storage import _project_world_facts
from packages.story_core.models import NovelProject


def test_project_world_facts_include_formal_world_systems():
    project = NovelProject(
        project_id="p-world-systems",
        title="Formal World",
        world_summary="A rule-bound world.",
        world_blueprint={
            "world_systems": {
                "material_base": ["Starter economy depends on wolf hides and auction fees."],
                "institutions": [{"name": "Auction House", "description": "Tracks abnormal listing volume."}],
                "conflict_engines": ["Rare drops create profit, market anomaly, and identity risk."],
                "causal_loops": [{"name": "Market Trace", "description": "Cheap listings lead merchants toward the source."}],
            }
        },
    )

    facts = _project_world_facts(project)

    assert "资源基础：Starter economy depends on wolf hides and auction fees." in facts
    assert "制度机构：Auction House - Tracks abnormal listing volume." in facts
    assert "冲突引擎：Rare drops create profit, market anomaly, and identity risk." in facts
    assert "因果链：Market Trace - Cheap listings lead merchants toward the source." in facts


def test_project_world_facts_include_game_plugin_modules():
    project = NovelProject(
        project_id="p-game-modules",
        title="Game Modules",
        world_blueprint={
            "npc_system": {
                "npcs": [
                    {
                        "name": "职业导师艾伦",
                        "role": "法师导师",
                        "location": "职业大厅",
                        "services": ["技能学习", "转职试炼登记"],
                        "knowledge_limit": "只能看见面板异常，不能确认隐藏天赋。",
                        "quest_hooks": ["元素回廊前置"],
                    }
                ],
                "rules": ["NPC 服务会留下任务、声望或流水痕迹。"],
            },
            "quest_network": {
                "active_chains": [
                    {
                        "name": "元素回廊前置",
                        "description": "Lv10 法师试炼前置。",
                        "stages": ["登记", "提交火种碎片"],
                        "npc_links": ["职业导师艾伦"],
                    }
                ],
                "reward_rules": ["隐藏任务不能跳过职业试炼。"],
            },
            "server_runtime": {
                "phase": "开服初期",
                "channels": ["世界频道", "交易行寄售记录"],
                "anti_cheat_rules": ["异常寄售会提高风控关注。"],
            },
            "map_ecology": {
                "zones": [
                    {
                        "name": "灰烬村",
                        "description": "新手村安全区。",
                        "resources": ["任务", "补给"],
                        "npcs": ["职业导师艾伦"],
                        "risk": "信息暴露。",
                    }
                ]
            },
        },
    )

    facts = _project_world_facts(project)

    assert any(fact.startswith("NPC：职业导师艾伦") for fact in facts)
    assert any(fact.startswith("任务网络：元素回廊前置") for fact in facts)
    assert "服务器阶段：开服初期" in facts
    assert any(fact.startswith("地图生态：灰烬村") for fact in facts)


def test_project_world_facts_include_longform_framework():
    project = NovelProject(
        project_id="p-longform",
        title="Longform",
        world_blueprint={
            "longform_framework": {
                "target_words": 1000000,
                "series_premise": "主角从灰烬村小额验证开始，逐步卷入服务器、现实资本和世界权限争夺。",
                "volume_ladder": [
                    {
                        "chapters": "1-30",
                        "name": "灰烬村蛰伏",
                        "unlocks": ["1-10级", "千倍爆率小额验证"],
                        "pressure_cap": "只能出现商人盯盘和公会外围弱试探",
                    }
                ],
                "progression_ladder": ["1-10级只处理新手村职业入口。"],
                "faction_ladder": ["白袍公会前30章只能作为外围压力。"],
                "economy_ladder": ["第一卷只允许铜币/银币级别收益。"],
                "reality_ladder": ["前三章不写官方兑换汇率。"],
                "mystery_ladder": ["混沌之种第一卷只验证收益异常。"],
                "map_ladder": ["第一卷地图限制在灰烬村、幽暗林地和交易节点。"],
                "npc_evolution_ladder": ["第一卷NPC只体现服务边界和轻微异常。"],
                "simulation_rules": ["每章只允许解锁当前卷范围内的世界层级。"],
            }
        },
    )

    facts = _project_world_facts(project)

    assert "百万字框架：目标约1000000字，章节推演必须服从长期解锁顺序与阶段上限。" in facts
    assert "百万字总前提：主角从灰烬村小额验证开始，逐步卷入服务器、现实资本和世界权限争夺。" in facts
    assert any(fact.startswith("长期卷阶梯：1-30 - 灰烬村蛰伏") for fact in facts)
    assert "长期成长阶梯：1-10级只处理新手村职业入口。" in facts
    assert "长期推演规则：每章只允许解锁当前卷范围内的世界层级。" in facts
