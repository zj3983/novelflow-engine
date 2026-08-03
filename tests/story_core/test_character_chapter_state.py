from copy import deepcopy

from packages.story_core.memory import apply_post_chapter_updates, build_character_cards
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.post_draft_memory import (
    build_post_draft_memory_prompt,
    normalize_post_draft_memory,
)


def test_character_cards_drop_legacy_profile_and_relationship_dumps_from_memory():
    story = StoryState(
        story_id="s-character-memory-cleanup",
        outline="测试",
        genre="玄幻",
        style="通俗",
        characters=[
            CharacterState(
                name="林修",
                role="protagonist",
                memory=[
                    "## 基本信息；- **姓名**：林修；- **年龄**：18岁",
                    "林修-沈墨璃: 朋友/战友",
                    "沈墨璃-林修：朋友/战友",
                    "第145章：林修确认残镜会牵引小乐。",
                    "第3-4章：连续值夜。",
                    "他判断这件事有**风险**。",
                    "他仍欠药铺一笔灵石。",
                ],
            ),
            CharacterState(name="沈墨璃", role="supporting"),
        ],
    )

    card = build_character_cards(story)[0]

    assert card["continuity_locks"]["memory"] == [
        "第145章：林修确认残镜会牵引小乐。",
        "第3-4章：连续值夜。",
        "他判断这件事有**风险**。",
        "他仍欠药铺一笔灵石。",
    ]


def _story(*characters: CharacterState, genre: str = "现实题材") -> StoryState:
    return StoryState(
        story_id="character-chapter-state",
        outline="林照继续追查旧案。",
        genre=genre,
        style="白描",
        characters=list(characters),
    )


def test_character_update_keeps_only_compatible_fields_and_state_line():
    evidence = "林照在偏殿，心中警惕，目标是查账。"
    result = normalize_post_draft_memory(
        {
            "character_updates": [
                {
                    "name": "林照",
                    "state_line": "reality",
                    "emotion": "警惕",
                    "goal": "查账",
                    "location": "偏殿",
                    "physical_condition": "旧伤复发",
                    "knowledge": ["铜印属于内库"],
                    "possessions": ["铜印"],
                    "possessions_removed": ["旧钥匙"],
                    "age": 99,
                    "background": "伪造背景",
                    "evidence": evidence,
                }
            ]
        },
        body=evidence,
        existing_character_names={"林照"},
    )

    assert result["character_updates"] == [
        {
            "name": "林照",
            "state_line": "reality",
            "emotion": "警惕",
            "goal": "查账",
            "location": "偏殿",
            "evidence": evidence,
        }
    ]


def test_game_evidence_updates_only_game_trace_and_preserves_legacy_flat_state():
    character = CharacterState(
        name="林峰",
        role="主角",
        game_id="青锋",
        current_emotion="现实平静",
        location="出租屋",
        goals=["现实缴租"],
        game_state={"balance": "27.60", "recent_changes": []},
    )
    story = _story(character, genre="网游")
    evidence = "青锋在石门，心中振奋，目标是开门。"

    apply_post_chapter_updates(
        story,
        evidence,
        13,
        post_draft_memory={
            "character_updates": [
                {
                    "name": "林峰",
                    "state_line": "game",
                    "emotion": "振奋",
                    "goal": "开门",
                    "location": "石门",
                    "physical_condition": "满血",
                    "possessions": ["赤晶"],
                    "evidence": evidence,
                }
            ]
        },
    )

    assert character.current_emotion == "现实平静"
    assert character.location == "出租屋"
    assert character.goals == ["现实缴租"]
    assert character.game_state["balance"] == "27.60"
    assert character.game_state["current"] == {
        "balance": "27.60",
        "last_appearance_chapter": 13,
    }
    assert character.game_state["recent_changes"] == [
        {"chapter": 13, "fact": evidence}
    ]


def test_reality_evidence_updates_compatible_fields_and_preserves_stable_profiles():
    character = CharacterState(
        name="林照",
        role="主角",
        identity_profile={"age": 19, "current_identity": "账房学徒"},
        background_profile={"upbringing": "在河港长大"},
        story_drive={"long_term_goal": "洗清父亲冤案"},
        personality_portrait={"voice": {"sentence_habit": "少用反问"}},
        current_emotion="平静",
        location="账房",
        goals=["核对旧账"],
    )
    story = _story(character)
    stable_before = deepcopy(
        {
            field: getattr(character, field).model_dump()
            for field in (
                "identity_profile",
                "background_profile",
                "story_drive",
                "personality_portrait",
            )
        }
    )
    evidence = "林照在偏殿，心中警惕，目标是查账。"

    apply_post_chapter_updates(
        story,
        evidence,
        7,
        post_draft_memory={
            "character_updates": [
                {
                    "name": "林照",
                    "state_line": "reality",
                    "emotion": "警惕",
                    "goal": "查账",
                    "location": "偏殿",
                    "knowledge": ["伪造知识"],
                    "age": 99,
                    "background": "伪造背景",
                    "evidence": evidence,
                }
            ]
        },
    )

    assert character.current_emotion == "警惕"
    assert character.location == "偏殿"
    assert character.goals[0] == "查账"
    assert character.real_state["current"] == {"last_appearance_chapter": 7}
    assert character.real_state["recent_changes"] == [
        {"chapter": 7, "fact": evidence}
    ]
    assert {
        field: getattr(character, field).model_dump()
        for field in stable_before
    } == stable_before


def test_unknown_frozen_and_missing_evidence_do_not_update_character_trace():
    active = CharacterState(name="林照", role="主角", location="账房")
    frozen = CharacterState(name="周执事", role="配角", location="外院", frozen=True)
    story = _story(active, frozen)

    apply_post_chapter_updates(
        story,
        "林照仍在账房。周执事仍在外院。",
        3,
        post_draft_memory={
            "character_updates": [
                {"name": "林照", "location": "偏殿"},
                {
                    "name": "周执事",
                    "location": "外院",
                    "evidence": "周执事仍在外院",
                },
                {
                    "name": "陌生人",
                    "location": "账房",
                    "evidence": "林照仍在账房",
                },
            ]
        },
    )

    assert active.location == "账房"
    assert active.real_state == {}
    assert frozen.location == "外院"
    assert frozen.real_state == {}


def test_missing_state_line_records_evidence_without_guessing_reality_or_game():
    evidence = "林照走进灰烬村，准备查看任务牌。"
    character = CharacterState(
        name="林照",
        role="protagonist",
        current_emotion="平静",
        location="出租屋",
    )
    story = _story(character, genre="网游")

    apply_post_chapter_updates(
        story,
        evidence,
        8,
        post_draft_memory={
            "character_updates": [
                {
                    "name": "林照",
                    "emotion": "警惕",
                    "goal": "查看任务牌",
                    "location": "灰烬村",
                    "evidence": evidence,
                }
            ]
        },
    )

    assert character.current_emotion == "平静"
    assert character.location == "出租屋"
    assert character.real_state == {}
    assert character.game_state == {}
    assert all(evidence not in item for item in character.memory)


def test_character_trace_deduplicates_same_chapter_evidence_and_caps_at_24():
    evidence = "林照在偏殿。"
    character = CharacterState(
        name="林照",
        role="主角",
        real_state={
            "recent_changes": [
                {"chapter": chapter, "fact": f"第{chapter}章证据"}
                for chapter in range(1, 25)
            ]
        },
    )
    story = _story(character)
    update = {
        "name": "林照",
        "state_line": "reality",
        "location": "偏殿",
        "evidence": evidence,
    }

    for _ in range(2):
        apply_post_chapter_updates(
            story,
            evidence,
            25,
            post_draft_memory={"character_updates": [update]},
        )

    changes = character.real_state["recent_changes"]
    assert len(changes) == 24
    assert changes[-1] == {"chapter": 25, "fact": evidence}
    assert changes.count({"chapter": 25, "fact": evidence}) == 1
    assert character.real_state["current"]["last_appearance_chapter"] == 25


def test_character_memory_prompt_limits_updates_to_compatible_fields():
    prompt = build_post_draft_memory_prompt(
        "林照在偏殿。",
        existing_character_names={"林照"},
    )

    assert "角色更新限emotion、goal、location" in prompt
    assert "其他结构化状态由明确状态事件负责" in prompt
    assert "稳定档案禁改" in prompt
    assert "physical_condition" not in prompt
    assert "possessions_removed" not in prompt


def test_post_chapter_updates_merge_equipment_cards_into_story_state():
    story = StoryState(
        story_id="s-equipment-memory",
        outline="equipment continuity",
        genre="game_webnovel",
        genre_plugin_ids=["game_webnovel"],
        style="commercial",
        equipment_cards=[
            {
                "name": "Dusk Verdict",
                "equipment_type": "weapon",
                "durability": "31/40",
                "current_owner": "Night Ember",
            }
        ],
    )
    body = "Night Ember placed Dusk Verdict in the guild vault."

    apply_post_chapter_updates(
        story,
        body,
        8,
        post_draft_memory={
            "equipment_updates": [
                {
                    "name": "Dusk Verdict",
                    "equipment_type": "weapon",
                    "current_owner": "Guild Vault",
                    "current_location": "Ashen Hall",
                    "evidence": [
                        {
                            "chapter": 8,
                            "quote": body,
                            "confidence": "confirmed",
                        }
                    ],
                }
            ]
        },
    )

    assert len(story.equipment_cards) == 1
    assert story.equipment_cards[0]["current_owner"] == "Guild Vault"
    assert story.equipment_cards[0]["durability"] == "31/40"
    assert story.equipment_cards[0]["last_update_chapter"] == 8


def test_evidence_only_character_update_records_appearance_without_guessing_state():
    character = CharacterState(name="林照", role="主角", location="祖祠")
    story = _story(character)
    evidence = "林照把旧铜钥匙收进袖口，继续守在祖祠里。"

    apply_post_chapter_updates(
        story,
        evidence,
        3,
        post_draft_memory={
            "character_updates": [
                {"name": "林照", "state_line": "reality", "evidence": evidence}
            ]
        },
    )

    assert character.location == "祖祠"
    assert character.real_state["current"]["last_appearance_chapter"] == 3
    assert character.real_state["recent_changes"] == [{"chapter": 3, "fact": evidence}]
