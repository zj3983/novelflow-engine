from __future__ import annotations

from typing import Any

from packages.story_core.story_core_card import (
    StoryCoreCard,
    merge_story_core_into_overall,
    outline_seed_from_story_core,
    story_core_from_direction,
    story_core_from_legacy,
    story_core_projection,
)


def _complete_payload() -> dict[str, Any]:
    return {
        "schema_version": "story-core/v1",
        "title": "明日来信",
        "logline": "一个害怕承担责任的快递员收到明天的失踪报告后，必须在当天找到失踪者，否则妹妹会成为下一名失踪者。",
        "protagonist_profile": "二十四岁的夜班快递员，观察细，但遇事习惯躲开。",
        "inciting_incident": "他收到一份日期为明天、收件人却是自己的失踪报告。",
        "protagonist_goal": "在午夜前找到报告中的失踪者并查明寄件人。",
        "main_conflict": "寄件人不断修改当天事件，警方也把他列为嫌疑人。",
        "failure_stakes": "失踪者会死亡，他的妹妹会成为下一名目标。",
        "growth_path": "从只求自保变成愿意承担选择后果的人。",
        "excitement_point": "用一张张未来单据追查正在发生的案件。",
        "target_audience": "喜欢都市悬疑、连续反转和人物成长的网文读者。",
        "reader_promise": "每个阶段解决一份未来单据，同时逼近寄件人的真实目的。",
        "ending_direction": "主角主动寄出第一份改变过去的单据，并承担新规则的代价。",
        "core_advantage": {
            "name": "Tomorrow's receipt",
            "type": "information advantage",
            "ability": "Shows one transaction before it happens.",
            "growth_rule": "Each verified receipt reveals one more causal link.",
            "limits": "Only one active receipt can exist at a time.",
            "early_payoff": "The protagonist prevents the first disappearance.",
        },
        "central_mystery": {
            "surface_anomaly": "Receipts arrive with tomorrow's date.",
            "hidden_truth": "The sender is changing failed timelines.",
            "reality_impact": "Every intervention rewrites one relationship.",
            "reveal_path": ["verify the first receipt", "identify the sender", "choose a timeline"],
        },
        "initial_drive": {
            "immediate_need": "Keep the courier job.",
            "trigger": "His sister appears on the next report.",
            "short_term_goal": "Find the missing customer before midnight.",
            "failure_stakes": "His sister becomes the next target.",
            "long_term_transition": "He changes from self-preservation to investigating the sender.",
        },
        "source_direction_id": "direction-1",
    }


def test_story_core_card_trims_text_and_keeps_version() -> None:
    payload = _complete_payload()
    payload["title"] = "  明日来信  "

    card = StoryCoreCard.model_validate(payload)

    assert card.schema_version == "story-core/v1"
    assert card.title == "明日来信"


def test_story_core_from_direction_maps_complete_candidate() -> None:
    candidate = {key: value for key, value in _complete_payload().items() if key != "schema_version"}
    candidate["id"] = candidate.pop("source_direction_id")
    candidate["hook"] = candidate["logline"]
    candidate["opening_promise"] = candidate["reader_promise"]

    card = story_core_from_direction(candidate)

    assert card.source_direction_id == "direction-1"
    assert card.logline == candidate["logline"]
    assert card.reader_promise == candidate["reader_promise"]


def test_story_core_from_legacy_does_not_invent_missing_fields() -> None:
    card = story_core_from_legacy(
        selected_direction={
            "id": "legacy-1",
            "title": "旧方向",
            "hook": "主角在旧城发现一封不该存在的信。",
            "protagonist_goal": "找出寄信人。",
            "main_conflict": "寄信人正在销毁证据。",
            "growth_path": "从逃避变成承担。",
            "opening_promise": "沿着信件追查真相。",
        },
        outline={"overall": {"ending_direction": "主角公开真相。"}},
        title="旧书名",
    )

    assert card.logline == "主角在旧城发现一封不该存在的信。"
    assert card.failure_stakes == ""
    assert card.excitement_point == ""
    assert card.core_advantage.name == ""
    assert card.central_mystery.hidden_truth == ""
    assert card.initial_drive.immediate_need == ""
    assert card.ending_direction == "主角公开真相。"


def test_story_core_projections_keep_stage_boundaries() -> None:
    card = StoryCoreCard.model_validate(_complete_payload())

    assert set(story_core_projection(card, "character")) == {
        "protagonist_profile",
        "protagonist_goal",
        "failure_stakes",
        "growth_path",
        "main_conflict",
        "core_advantage",
        "initial_drive",
    }
    assert set(story_core_projection(card, "world")) == {
        "inciting_incident",
        "main_conflict",
        "excitement_point",
        "core_advantage",
        "central_mystery",
    }
    assert story_core_projection(card, "writing") == {
        "logline": card.logline,
        "reader_promise": card.reader_promise,
        "core_advantage": card.core_advantage.model_dump(mode="json"),
        "initial_drive": card.initial_drive.model_dump(mode="json"),
    }
    planning = story_core_projection(card, "planning")
    assert planning["central_mystery"] == {
        "surface_anomaly": card.central_mystery.surface_anomaly,
        "reality_impact": card.central_mystery.reality_impact,
    }
    assert "hidden_truth" not in planning["central_mystery"]
    assert set(story_core_projection(card, "outline")) == {
        key for key in _complete_payload() if key != "schema_version"
    }


def test_outline_seed_uses_core_fields_without_copying_audience() -> None:
    card = StoryCoreCard.model_validate(_complete_payload())

    seed = outline_seed_from_story_core(card, primary_trope_id="mystery-letter")

    assert seed["overall"]["story"] == card.logline
    assert seed["overall"]["book_objective"] == card.protagonist_goal
    assert seed["overall"]["ending_direction"] == card.ending_direction
    assert seed["overall"]["primary_trope_id"] == "mystery-letter"
    assert "target_audience" not in seed["overall"]


def test_overwriting_story_core_refreshes_denormalized_overall_fields() -> None:
    card = StoryCoreCard.model_validate(_complete_payload())

    merged = merge_story_core_into_overall(
        {
            "book_objective": "stale objective",
            "core_selling_point": "stale selling point",
            "ending_image": "stale ending image",
            "ending_contract": "stale ending contract",
        },
        card,
        overwrite=True,
    )

    assert merged["book_objective"] == card.protagonist_goal
    assert merged["core_selling_point"] == card.excitement_point
    assert merged["ending_image"] == card.ending_direction
    assert merged["ending_contract"] == card.ending_direction
