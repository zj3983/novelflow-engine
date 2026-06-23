from packages.story_core.writing_taskbook import (
    build_writing_taskbook,
    ensure_writing_taskbook,
    format_taskbook_prompt_section,
    taskbook_segment_specs,
)


def test_first_chapter_taskbook_keeps_only_three_useful_scenes():
    taskbook = build_writing_taskbook(
        chapter_number=1,
        plan={
            "target_chars": {"min": 3200, "max": 4200},
            "event_plan": {"chapter_title": "两只灰狼，掉了五份毒腺"},
            "scene_cards": [
                {"template_id": "single_npc_service", "location": "药剂铺", "must_show": ["洛婶报价"]},
            ],
        },
        genre="网游",
        style="白话爽文",
    )

    scenes = taskbook["scenes"]
    assert [scene["key"] for scene in scenes] == ["entry_login", "small_verification", "decision_hook"]
    assert "NPC" not in scenes[2]["goal"]
    assert "不要展开力量/敏捷/体质/智力" in scenes[0]["required_surface"]
    assert "底层协议校验通过" in scenes[1]["required_surface"]
    assert "至少兑现一项" in scenes[2]["required_surface"]
    assert "交易、论坛、公会追查后移" in " ".join(taskbook["global_required"])
    assert "材料公开处理成大钱" in taskbook["global_forbidden"]
    assert "公开扣费或大额收款反馈" in taskbook["global_forbidden"]


def test_taskbook_compiles_scene_cards_for_later_chapters():
    plan = {
        "target_chars": 3600,
        "scene_cards": [
            {
                "template_id": "npc-counter",
                "location": "药剂铺",
                "purpose": "让洛婶只给药材报价",
                "conflict": "她不回答公会消息",
                "must_show": ["库存", "报价"],
                "avoid": ["公会内部频道"],
                "ending_pressure": "苏叶必须决定卖不卖",
            }
        ],
    }

    specs = taskbook_segment_specs(2, plan)

    assert len(specs) == 1
    assert specs[0]["key"] == "npc-counter"
    assert "药剂铺" in specs[0]["title"]
    assert "库存" in specs[0]["required_surface"]
    assert "公会内部频道" in specs[0]["forbidden_surface"]
    assert "苏叶必须决定卖不卖" in specs[0]["exit_state"]


def test_taskbook_prompt_section_is_writer_facing_not_json_dump():
    taskbook = ensure_writing_taskbook(
        1,
        {
            "unused_big_blob": "NOISE" * 500,
            "event_plan": {"chapter_title": "两只灰狼"},
            "scene_cards": [{"template_id": "single_npc_service", "must_show": ["洛婶报价"]}],
        },
        genre="网游",
        style="白话爽文",
    )

    section = format_taskbook_prompt_section(taskbook, segment_key="small_verification")

    assert "## 写作任务书" in section
    assert "只按这份任务书写正文" in section
    assert "低级怪小验证" in section
    assert "NOISENOISE" not in section
    assert "unused_big_blob" not in section
    assert "scene_cards" not in section


def test_taskbook_turns_plot_simulation_into_narrative_spine():
    taskbook = build_writing_taskbook(
        chapter_number=2,
        plan={
            "target_chars": 3600,
            "simulation_plan": {
                "chapter_goal": "完成清道夫委托",
                "plot_simulation": {
                    "reader_hook": "读者要看到夜烬暗中把优势滚起来。",
                    "chapter_desire": "夜烬想补齐清道夫委托还差的两份毒腺。",
                    "obstacle_chain": ["蓝量不够", "法杖耐久快见底", "旁边玩家会误判他的路线"],
                    "choice_point": "他要决定先交任务，还是先把来源藏住。",
                    "payoff": "清道夫委托进度必须有明确变化。",
                    "cost": "至少付出蓝量、耐久或铜币中的一项。",
                    "emotional_turn": "从缺资源的紧绷转成小领先后的警惕。",
                    "outsider_misread": "外人只能以为他运气好。",
                    "ending_hook": "章末落到后坡巡查前置任务。",
                },
            },
        },
        genre="网游",
        style="白描",
    )

    required = "\n".join(taskbook["global_required"])
    scenes = "\n".join(scene["goal"] + "\n" + scene["required_surface"] + "\n" + scene["exit_state"] for scene in taskbook["scenes"])

    assert "剧情主线：读者要看到夜烬暗中把优势滚起来。" in required
    assert "主角目标：夜烬想补齐清道夫委托还差的两份毒腺。" in required
    assert "阻碍：蓝量不够；法杖耐久快见底；旁边玩家会误判他的路线" in required
    assert "夜烬想补齐清道夫委托还差的两份毒腺" in scenes
    assert "清道夫委托进度必须有明确变化" in scenes
    assert "章末落到后坡巡查前置任务" in scenes


def test_taskbook_prompt_uses_plot_words_not_backend_key():
    taskbook = ensure_writing_taskbook(
        2,
        {
            "simulation_plan": {
                "chapter_goal": "完成清道夫委托",
                "plot_simulation": {
                    "reader_hook": "读者要看到具体领先。",
                    "chapter_desire": "夜烬想补齐材料。",
                    "payoff": "任务进度变化。",
                    "ending_hook": "后坡巡查前置任务露出。",
                },
            }
        },
        genre="网游",
        style="白描",
    )

    section = format_taskbook_prompt_section(taskbook)

    assert "剧情主线" in section
    assert "读者要看到具体领先" in section
    assert "plot_simulation" not in section
