from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.genre_plugins import is_game_genre


CLICHE_BLACKLIST = [
    "心头一震",
    "不知不觉",
    "仿佛过了一个世纪",
    "眼眸深邃",
    "嘴角微微上扬",
    "一股暖流",
    "说不出的感觉",
    "莫名其妙",
    "命运的齿轮",
    "空气仿佛凝固",
]


SOFT_ABSTRACTION_WORDS = ["仿佛", "似乎", "某种", "隐隐", "莫名", "说不清", "很", "非常"]


# LLM 跨章 / 跨稿常复用的金句，第一次写 ch1 时 chapter_summaries 是空的，
# 这组 fallback 让 watch_phrases 永远不为空。
KNOWN_REPEAT_TRAPS = [
    "成本已经先到了",
    "第一笔账还没赚到",
    "第一笔委托还没交",
    "成本先到",
    "账还没赚到",
]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any, *, max_items: int = 8, item_chars: int = 100) -> list[str]:
    if not isinstance(value, list):
        return []
    return compact_list([str(item) for item in value if str(item).strip()], max_items=max_items, item_chars=item_chars)


def _story_text(story: Any, *extra: Any) -> str:
    chunks = [
        str(getattr(story, "genre", "") or ""),
        str(getattr(story, "style", "") or ""),
        str(getattr(story, "outline", "") or ""),
        "\n".join(str(item) for item in (getattr(story, "world_facts", []) or [])[:60]),
    ]
    for item in extra:
        if isinstance(item, dict):
            chunks.append(" ".join(str(value) for value in item.values()))
        elif isinstance(item, list):
            chunks.append(" ".join(str(value) for value in item))
        else:
            chunks.append(str(item or ""))
    return "\n".join(chunks)


def is_game_story(story: Any, *extra: Any) -> bool:
    text = _story_text(story, *extra)
    return is_game_genre(text)


def _chapter_motif_candidates(story: Any, target_chapter: int, *, game_story: bool) -> list[dict[str, str]]:
    text = _story_text(story)
    motifs: list[dict[str, str]] = []
    if any(token in text for token in ("房租", "债", "账单", "余额", "现实压力")):
        motifs.append({"image": "一件现实压力物", "first_use": f"第{target_chapter}章", "echo_plan": "每次回响都压缩主角选择余地。"})
    if game_story:
        motifs.extend(
            [
                {"image": "装备或资源消耗提示", "first_use": f"第{target_chapter}章", "echo_plan": "收益出现前先让成本可见。"},
                {"image": "公共界面的滚动数字", "first_use": f"第{target_chapter}章", "echo_plan": "公共世界只显露弱线索，不替读者全知。"},
            ]
        )
    else:
        motifs.extend(
            [
                {"image": "一件可反复出现的小物", "first_use": f"第{target_chapter}章", "echo_plan": "每次出现都改变一次意义。"},
                {"image": "场景里固定的声音或气味", "first_use": f"第{target_chapter}章", "echo_plan": "作为读者返回本线的感官锚。"},
            ]
        )
    return motifs[:4]


def _setup_payoff_chain(target_chapter: int, *, game_story: bool) -> list[dict[str, Any]]:
    chain = [
        {
            "setup": "小额异常或细微违和只留下弱痕迹",
            "payoff_window": f"第{target_chapter + 3}到{target_chapter + 6}章",
            "payoff_condition": "重复、高频、公开或被多方汇总后，才升级为外部注意。",
        },
        {
            "setup": "一次选择先付出可见成本",
            "payoff_window": f"第{target_chapter + 1}到{target_chapter + 3}章",
            "payoff_condition": "用一次资源、关系或信息短缺逼主角改变路线。",
        },
    ]
    if game_story:
        chain.append(
            {
                "setup": "隐藏优势只表现为异常结果",
                "payoff_window": f"第{target_chapter + 5}章以后",
                "payoff_condition": "至少三次可见异常后再给读者部分解释。",
            }
        )
    else:
        chain.append(
            {
                "setup": "一句被轻轻带过的话",
                "payoff_window": f"第{target_chapter + 2}到{target_chapter + 5}章",
                "payoff_condition": "当角色利益位置改变后，让同一句话获得新含义。",
            }
        )
    return chain


def _show_tell_conversions(*, game_story: bool) -> list[dict[str, str]]:
    common = [
        {"tell": "他很谨慎", "show": "他先停住手，把可退路数了一遍，才碰下一步。"},
        {"tell": "她生气", "show": "她把杯子放得太轻，杯底没有响，话也跟着停了半拍。"},
        {"tell": "压力很大", "show": "他把那串数字又看了一遍，指腹在边角磨出一道白印。"},
    ]
    if game_story:
        common.extend(
            [
                {"tell": "成本很高", "show": "一个格子暗下去，耐久提示跳红，补给栏少了一瓶。"},
                {"tell": "有人开始注意", "show": "同一条记录被顶了三次，标题里的问号越来越少。"},
            ]
        )
    else:
        common.extend(
            [
                {"tell": "关系变冷", "show": "他把称呼换回全名，中间隔了一个完整停顿。"},
                {"tell": "秘密快藏不住", "show": "桌上的纸被压回原位，折角却露在灯下。"},
            ]
        )
    return common


def _abstract_to_object(*, game_story: bool) -> list[str]:
    common = ["压力->账单/余额/倒计时/未接电话", "犹豫->手指停在按钮或门把上", "风险->旁人视线/一处错位/一条未读消息"]
    if game_story:
        common.append("代价->耐久/背包格/补给数量/任务进度")
    else:
        common.append("代价->关系称呼/座位距离/被收回的承诺")
    return common


def _micro_hook_types(*, game_story: bool) -> list[str]:
    if game_story:
        return ["未结算数字", "NPC半句拒绝", "资源消耗提示", "背包或任务门槛", "旁人误读", "路线被迫改变"]
    return ["一句话少了后半截", "物件位置不对", "关系称呼变化", "时间被截断", "旁人误读", "下一步选择变窄"]


def _watch_phrases(story: Any, *, game_story: bool) -> list[str]:
    text = "\n".join(
        str(getattr(summary, "summary", "") or "") + "\n" + "\n".join(getattr(summary, "facts", []) or [])
        for summary in (getattr(story, "chapter_summaries", []) or [])[-8:]
    )
    phrases = []
    for part in re.split(r"[。！？!?；;\n]", text):
        cleaned = re.sub(r"\s+", "", part).strip(" “”，,：:、")
        if 8 <= len(cleaned) <= 28:
            phrases.append(cleaned)
    repeated = [phrase for phrase, count in Counter(phrases).most_common(8) if count > 1]
    generic = ["看了一眼", "沉默片刻"]
    if game_story:
        generic.append("打开面板")
    return repeated + [phrase for phrase in generic if phrase not in repeated]


def _transition_crutch_limits(*, game_story: bool) -> dict[str, Any]:
    limits = {
        "看了一眼": {"max_per_chapter": 2, "alternatives": ["手指停住", "数字刷新", "对方先移开视线"]},
        "沉默片刻": {"max_per_chapter": 1, "alternatives": ["把动作写出来", "让对话错开半拍", "用物件变化承接"]},
    }
    if game_story:
        limits["打开面板"] = {"max_per_chapter": 1, "alternatives": ["提示音弹出", "背包格变暗", "耐久提示跳出", "任务栏刷新"]}
    return limits


def build_craft_pack(
    story: Any,
    target_chapter: int,
    *,
    scene_cards: list[dict[str, Any]] | None = None,
    event_plan: dict[str, Any] | None = None,
    simulation_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build writer-facing craft guidance, separate from factual rules/spec."""

    scene_cards = scene_cards or []
    event_plan = _as_dict(event_plan)
    simulation_plan = _as_dict(simulation_plan)
    game_story = is_game_story(story, event_plan, simulation_plan, scene_cards)
    hook = str(
        event_plan.get("explicit_chapter_end_hook")
        or event_plan.get("next_focus")
        or event_plan.get("wow_beat")
        or simulation_plan.get("chapter_goal")
        or ""
    )
    scene_count = max(1, len(scene_cards))
    chapter_goal = str(simulation_plan.get("chapter_goal") or event_plan.get("chapter_goal") or "")
    return {
        "schema_version": "craft-pack/v1",
        "genre_mode": "game" if game_story else "general",
        "purpose": "把规则和事实转成可读场面；只约束写法，不新建世界事实。",
        "show_vs_tell": {
            "formula": "抽象判断 -> 可见动作/具体物件/停顿/错位反应/界面或环境反馈。",
            "conversions": _show_tell_conversions(game_story=game_story),
        },
        "concrete_discipline": {
            "rule": "每个抽象情绪或判断必须绑定一个具体物件、动作、数字或声音。",
            "avoid_softeners": SOFT_ABSTRACTION_WORDS,
            "abstract_to_object": _abstract_to_object(game_story=game_story),
        },
        "scene_beat_shape": {
            "shape": ["开: 本场目标落地", "涨: 阻力或成本加码", "断: 得到结果但被代价截断", "余: 留下一句话/一物/一条提示推向下一场"],
            "apply_to_each_scene": True,
            "scene_count": scene_count,
        },
        "dialogue_power_play": {
            "rule": "每段对话必须改变筹码、信息差、价格、信任或服务边界，不能只交换说明。",
            "moves": ["试探", "压价", "拒绝", "留口子", "转移话题", "用动作代替承认"],
        },
        "detail_budget": {
            "per_scene_new_world_details": 2,
            "per_chapter_new_terms": 1,
            "rule": "先重复旧细节并赋予新功能，再引入新设定。",
        },
        "setup_payoff_chain": _setup_payoff_chain(target_chapter, game_story=game_story),
        "motifs": _chapter_motif_candidates(story, target_chapter, game_story=game_story),
        "withholding_schedule": [
            {
                "secret": "隐藏优势机制" if game_story else "角色真正意图",
                "withhold_until": f"第{target_chapter + 5}章以后或三次可见证据之后",
                "allowed_now": "只写异常结果、成本和主角的验证动作。" if game_story else "只写动作、回避、矛盾话语和可见后果。",
            },
            {
                "secret": "外部势力判断" if game_story else "关系或组织背后的真实立场",
                "withhold_until": "出现重复、高频、公开或多源证据之后",
                "allowed_now": "只写弱反应和误读，不写全知结论。",
            },
        ],
        "micro_hooks": {
            "interval_chars": "500-800",
            "types": _micro_hook_types(game_story=game_story),
            "chapter_end_hook": hook,
        },
        "sentence_craft": {
            "sentence_start_variety": "连续3句不能同一种开头方式，轮换动作、物件、对话、界面、环境反馈。",
            "free_indirect_discourse": "把主角判断贴进叙述句，不写'他心想'；例如：还差两瓶药。现在回头，路费就白烧。",
            "cliche_blacklist": CLICHE_BLACKLIST,
        },
        "paragraph_rhythm": {
            "rule": "重要短句前后用较长动作段衬托；高潮处短句密，结算处留半拍。",
            "weights": {"setup": "breathing", "pressure": "staccato", "payoff": "dense", "aftermath": "breathing"},
        },
        "repetition_control": {
            "near_duplicate_check": "同一判断、同一金句、同一成本总结不得在相邻800字内换皮复读。",
            "watch_phrases": _watch_phrases(story, game_story=game_story),
        },
        "transition_crutch_limits": _transition_crutch_limits(game_story=game_story),
        "chapter_goal": compact_text(chapter_goal, 140),
    }


def enrich_scene_cards_with_craft(
    scene_cards: list[dict[str, Any]] | None,
    craft_pack: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Attach small scene-local craft handles without changing simulated facts."""

    craft_pack = _as_dict(craft_pack)
    beat_shape = _as_list(_as_dict(craft_pack.get("scene_beat_shape")).get("shape"), max_items=4, item_chars=50)
    show_conversions = _as_dict(craft_pack.get("show_vs_tell")).get("conversions", [])
    micro_types = _as_dict(craft_pack.get("micro_hooks")).get("types", [])
    detail_budget = _as_dict(craft_pack.get("detail_budget"))
    enriched: list[dict[str, Any]] = []
    for index, card in enumerate(scene_cards or [], start=1):
        new_card = deepcopy(card)
        if not new_card.get("beat_shape"):
            new_card["beat_shape"] = beat_shape
        if isinstance(show_conversions, list) and not new_card.get("show_tell_conversions"):
            new_card["show_tell_conversions"] = show_conversions[:2]
        if isinstance(micro_types, list) and micro_types and not new_card.get("micro_hook"):
            purpose = str(new_card.get("purpose") or new_card.get("conflict") or "")
            if any(token in purpose for token in ("收束", "结尾", "钩子", "下一步")):
                new_card["micro_hook"] = micro_types[-1]
            elif any(token in purpose for token in ("行动", "战斗", "选择", "验证", "交互")):
                new_card["micro_hook"] = micro_types[min(2, len(micro_types) - 1)]
            else:
                new_card["micro_hook"] = micro_types[(index - 1) % len(micro_types)]
        if detail_budget and not new_card.get("detail_budget"):
            new_card["detail_budget"] = detail_budget
        if not new_card.get("dialogue_power_shift") and any(
            token in str(new_card.get("purpose") or "") + str(new_card.get("conflict") or "")
            for token in ("对话", "NPC", "谈", "问", "交互", "服务")
        ):
            new_card["dialogue_power_shift"] = "若有对话，必须改变价格、边界、信息差、信任或下一步选择中的至少一项。"
        enriched.append(new_card)
    return enriched
