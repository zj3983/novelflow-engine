import pytest

from packages.story_core.post_draft_memory import (
    build_post_draft_memory_prompt,
    fallback_post_draft_memory,
    normalize_post_draft_memory,
)


def test_post_draft_memory_keeps_only_body_grounded_updates():
    body = "林照把断香炉搬回偏殿。周执事让他明早去账房回话。"
    payload = {
        "summary": "林照搬回断香炉，并接到明早回话的要求。",
        "facts": [
            {"text": "断香炉已搬到偏殿", "evidence": "把断香炉搬回偏殿"},
            {"text": "林照得到三枚灵石", "evidence": "三枚灵石"},
        ],
        "unresolved_threads": [
            {"text": "账房为何找林照", "evidence": "明早去账房回话"},
        ],
        "next_focus": "明早去账房",
        "chapter_title": "断香炉",
        "character_updates": [
            {
                "name": "林照",
                "emotion": "警惕",
                "goal": "明早去账房",
                "location": "偏殿",
                    "evidence": "林照把断香炉搬回偏殿。周执事让他明早去账房回话",
            },
            {"name": "陌生人", "emotion": "愤怒", "evidence": "陌生人"},
        ],
        "ledger_updates": {
            "protagonist": {"location": "偏殿", "spirit_stones": 3}
        },
        "ledger_evidence": {
            "protagonist.location": "搬回偏殿",
            "protagonist.spirit_stones": "三枚灵石",
        },
    }

    result = normalize_post_draft_memory(
        payload,
        body=body,
        existing_character_names={"林照", "周执事"},
    )

    assert result["summary"] == ""
    assert result["next_focus"] == "明早去账房"
    assert result["chapter_title"] == "断香炉"
    assert result["facts"] == ["断香炉已搬到偏殿"]
    assert result["unresolved_threads"] == ["账房为何找林照"]
    assert [item["name"] for item in result["character_updates"]] == ["林照"]
    assert result["character_updates"][0] == {
        "name": "林照",
        "location": "偏殿",
        "evidence": "林照把断香炉搬回偏殿。周执事让他明早去账房回话",
    }
    assert result["ledger_updates"] == {"protagonist": {"location": "偏殿"}}
    assert any(
        item.get("name") == "陌生人" for item in result["rejected_updates"]
    )
    assert any(
        item.get("path") == "protagonist.spirit_stones"
        for item in result["rejected_updates"]
    )


def test_evidence_matching_ignores_whitespace_and_common_punctuation():
    body = "林照把断香炉，搬回\n偏殿。"
    payload = {
        "facts": [
            {"text": "断香炉已搬回偏殿", "evidence": "断香炉 搬回偏殿"}
        ],
        "unresolved_threads": [],
        "character_updates": [],
        "ledger_updates": {},
        "ledger_evidence": {},
    }

    result = normalize_post_draft_memory(
        payload,
        body=body,
        existing_character_names={"林照"},
    )

    assert result["facts"] == ["断香炉已搬回偏殿"]


def test_evidence_matching_rejects_semantic_paraphrases_without_substrings():
    body = "林照把断香炉搬回偏殿。"
    payload = {
        "facts": [{"text": "香炉已归位", "evidence": "香炉被安置在侧殿"}],
        "unresolved_threads": [],
        "character_updates": [],
        "ledger_updates": {},
        "ledger_evidence": {},
    }

    result = normalize_post_draft_memory(
        payload,
        body=body,
        existing_character_names={"林照"},
    )

    assert result["facts"] == []


def test_unrelated_body_quote_cannot_authorize_fictional_updates():
    result = normalize_post_draft_memory(
        {
            "facts": [{"text": "林照得到灵石", "evidence": "雨停了"}],
            "unresolved_threads": [],
            "character_updates": [
                {"name": "林照", "location": "山门", "evidence": "雨停了"}
            ],
            "ledger_updates": {"protagonist": {"spirit_stones": 1}},
            "ledger_evidence": {"protagonist.spirit_stones": "雨停了"},
        },
        body="林照关上窗，雨停了。",
        existing_character_names={"林照"},
    )

    assert result["facts"] == []
    assert result["character_updates"] == []
    assert result["ledger_updates"] == {}


def test_ledger_number_must_match_a_complete_signed_number_token():
    for actual_text in (
        "获得10枚灵石",
        "获得1,000枚灵石",
        "获得-1枚灵石",
        "获得−1枚灵石",
        "获得负一枚灵石",
        "获得1e3枚灵石",
        "获得1/10枚灵石",
        "获得1%灵石",
        "获得1-10枚灵石",
        "获得1–10枚灵石",
        "获得1:10枚灵石",
        "获得1×10枚灵石",
        "获得1k枚灵石",
        "获得1万枚灵石",
        "经验增长百分之一",
    ):
        result = normalize_post_draft_memory(
            {
                "ledger_updates": {"protagonist": {"spirit_stones": 1}},
                "ledger_evidence": {"protagonist.spirit_stones": actual_text},
            },
            body=f"林照{actual_text}。",
            existing_character_names={"林照"},
        )

        assert result["ledger_updates"] == {}

    percentage = normalize_post_draft_memory(
        {
            "ledger_updates": {"protagonist": {"exp": 1}},
            "ledger_evidence": {"protagonist.exp": "经验增长百分之一"},
        },
        body="经验增长百分之一。",
        existing_character_names=set(),
    )
    assert percentage["ledger_updates"] == {}

    decimal = normalize_post_draft_memory(
        {
            "ledger_updates": {"protagonist": {"exp": 1}},
            "ledger_evidence": {"protagonist.exp": "经验增加一点五倍"},
        },
        body="经验增加一点五倍。",
        existing_character_names=set(),
    )
    assert decimal["ledger_updates"] == {}


def test_ledger_number_accepts_exact_arabic_and_chinese_values():
    for actual_text in ("获得3枚灵石", "获得三枚灵石"):
        result = normalize_post_draft_memory(
            {
                "ledger_updates": {"protagonist": {"spirit_stones": 3}},
                "ledger_evidence": {"protagonist.spirit_stones": actual_text},
            },
            body=f"林照{actual_text}。",
            existing_character_names={"林照"},
        )

        assert result["ledger_updates"] == {"protagonist": {"spirit_stones": 3}}


def test_attribute_allocation_requires_visible_choice_and_confirmed_remaining_points():
    body = "夜烬打开角色面板，把五点全部加到智力上。确认后，智力从五变成十，可用属性点归零。"
    payload = {
        "ledger_updates": {
            "protagonist": {
                "attribute_allocation": {
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            }
        },
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": "把五点全部加到智力上",
            "protagonist.attribute_allocation.remaining": "可用属性点归零",
        },
    }

    result = normalize_post_draft_memory(payload, body=body, existing_character_names={"夜烬"})

    assert result["ledger_updates"] == payload["ledger_updates"]


def test_attribute_allocation_accepts_completed_real_chapter_action():
    body = (
        "夜烬现在靠火球术刷怪，没必要把点数分散到别处，便把五点全加到了智力上。\n\n"
        "他点下确认，两行新的提示随即跳了出来：【智力：5→10。】【可用属性点：0。】"
    )
    payload = {
        "ledger_updates": {
            "protagonist": {
                "attribute_allocation": {
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            }
        },
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": "把五点全加到了智力上",
            "protagonist.attribute_allocation.remaining": "可用属性点：0",
        },
    }

    result = normalize_post_draft_memory(payload, body=body, existing_character_names={"夜烬"})

    assert result["ledger_updates"] == payload["ledger_updates"]


def test_attribute_allocation_accepts_evidence_backed_optional_reason():
    body = "夜烬打开角色面板，把五点加到智力上。为了法师路线，他确认加点，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {
                        "allocations": {"智力": 5},
                        "remaining": 0,
                        "reason": "法师路线",
                    }
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
                "protagonist.attribute_allocation.reason": "法师路线",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"]["protagonist"]["attribute_allocation"]["reason"] == "法师路线"


def test_attribute_allocation_rejects_payload_number_that_conflicts_with_prose_evidence():
    body = "夜烬打开角色面板，把5点全部加到智力上。确认后，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {
                        "allocations": {"智力": 6},
                        "remaining": 0,
                    }
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把5点全部加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_rejects_final_panel_without_visible_choice_action():
    body = "夜烬的角色面板显示：智力：10，可用属性点：0。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {
                        "allocations": {"智力": 5},
                        "remaining": 0,
                    }
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "智力：10",
                "protagonist.attribute_allocation.remaining": "可用属性点：0",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_rejects_negated_choice_and_confirmation():
    body = "夜烬没有把五点加到智力上。他确认不分配，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {
                        "allocations": {"智力": 5},
                        "remaining": 0,
                    }
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_rejects_confirmation_of_not_allocating():
    body = "夜烬把五点加到智力上。他确认不分配，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {
                        "allocations": {"智力": 5},
                        "remaining": 0,
                    }
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_rejects_unrelated_later_confirmation():
    body = "夜烬把五点加到智力上。走到修理铺后，他确认了修理订单，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {
                        "allocations": {"智力": 5},
                        "remaining": 0,
                    }
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_rejects_system_description_without_character_choice():
    body = "《神域》系统说明：五点属性点加到智力上，确认后分配生效，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {
                        "allocations": {"智力": 5},
                        "remaining": 0,
                    }
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "五点属性点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names=set(),
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_accepts_pronoun_subject_without_known_game_id():
    body = "他把五点属性点加到智力上，确认加点后，可用属性点归零。"
    payload = {
        "ledger_updates": {
            "protagonist": {
                "attribute_allocation": {
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            }
        },
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": "把五点属性点加到智力上",
            "protagonist.attribute_allocation.remaining": "可用属性点归零",
        },
    }

    result = normalize_post_draft_memory(payload, body=body, existing_character_names=set())

    assert result["ledger_updates"] == payload["ledger_updates"]


def test_attribute_allocation_memory_accepts_modified_action_and_adjacent_paragraph_confirmation():
    body = "夜烬把刚拿到的五点全部加到智力上。\n\n他点下确认，可用属性点归零。"
    payload = {
        "ledger_updates": {
            "protagonist": {
                "attribute_allocation": {
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            }
        },
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": "把刚拿到的五点全部加到智力上",
            "protagonist.attribute_allocation.remaining": "可用属性点归零",
        },
    }

    result = normalize_post_draft_memory(payload, body=body, existing_character_names={"夜烬"})

    assert result["ledger_updates"] == payload["ledger_updates"]


def test_attribute_allocation_memory_rejects_named_bystander_when_protagonist_aliases_are_known():
    body = "短发玩家把五点加到智力上，确认后可用属性点归零。夜烬只是看着，没有加点。"
    payload = {
        "ledger_updates": {
            "protagonist": {
                "attribute_allocation": {
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            }
        },
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
            "protagonist.attribute_allocation.remaining": "可用属性点归零",
        },
    }

    result = normalize_post_draft_memory(
        payload,
        body=body,
        existing_character_names={"苏叶", "夜烬", "短发玩家"},
        protagonist_aliases={"苏叶", "夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_memory_rejects_bystander_action_after_protagonist_mention():
    body = "夜烬看着短发玩家把五点加到智力上，确认后可用属性点归零。他自己没有加点。"
    payload = {
        "ledger_updates": {
            "protagonist": {
                "attribute_allocation": {
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            }
        },
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
            "protagonist.attribute_allocation.remaining": "可用属性点归零",
        },
    }

    result = normalize_post_draft_memory(
        payload,
        body=body,
        existing_character_names={"苏叶", "夜烬", "短发玩家"},
        protagonist_aliases={"苏叶", "夜烬"},
    )

    assert result["ledger_updates"] == {}


@pytest.mark.parametrize("action", ("夜烬直接把五点加到智力上", "他果断把五点加到智力上", "夜烬又把五点加到智力上"))
def test_attribute_allocation_memory_accepts_protagonist_actions_with_modifiers(action: str):
    body = f"{action}，确认后可用属性点归零。"
    payload = {
        "ledger_updates": {
            "protagonist": {
                "attribute_allocation": {
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            }
        },
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": action,
            "protagonist.attribute_allocation.remaining": "可用属性点归零",
        },
    }

    result = normalize_post_draft_memory(
        payload,
        body=body,
        existing_character_names={"苏叶", "夜烬"},
        protagonist_aliases={"苏叶", "夜烬"},
    )

    assert result["ledger_updates"] == payload["ledger_updates"]


def test_attribute_allocation_rejects_zero_remaining_from_unrelated_durability_text():
    body = "夜烬把五点加到智力上，确认加点。可用属性点还是5点，法杖耐久归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {
                        "allocations": {"智力": 5},
                        "remaining": 0,
                    }
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "法杖耐久归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_memory_rejects_bystander_remaining_after_protagonist_confirmation():
    body = "夜烬把五点加到智力上。随后他确认加点。短发玩家的可用属性点还剩四点。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {"protagonist": {"attribute_allocation": {"allocations": {"智力": 5}, "remaining": 4}}},
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点还剩四点",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_memory_rejects_a_known_named_bystander_panel_chain():
    body = "林峰站在一旁，显得得意。夜烬把五点加到智力上。青锋看了夜烬一眼，他确认加点，提示消失后，他的面板上的可用属性点还剩四点。"
    result = normalize_post_draft_memory(
        {
            "character_updates": [
                {"name": "青锋", "emotion": "得意", "evidence": "青锋看了夜烬一眼"},
                {"name": "林峰", "emotion": "得意", "evidence": "林峰站在一旁，显得得意"},
            ],
            "ledger_updates": {"protagonist": {"attribute_allocation": {"allocations": {"智力": 5}, "remaining": 4}}},
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点还剩四点",
            },
        },
        body=body,
        existing_character_names={"夜烬", "林峰"},
        evidence_character_names={"夜烬", "林峰", "青锋"},
        protagonist_aliases={"夜烬"},
    )

    assert result["ledger_updates"] == {}
    assert result["character_updates"] == [
        {"name": "林峰", "emotion": "得意", "evidence": "林峰站在一旁，显得得意"}
    ]
    assert any(
        item.get("kind") == "character_update"
        and item.get("name") == "青锋"
        and item.get("reason") == "unknown_character"
        for item in result["rejected_updates"]
    )


def test_character_update_uses_only_its_own_game_id_as_body_evidence():
    accepted = normalize_post_draft_memory(
        {
            "character_updates": [
                {"name": "林峰", "emotion": "凝重", "evidence": "青锋脸色凝重"},
                {"name": "青锋", "emotion": "凝重", "evidence": "青锋脸色凝重"},
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        body="青锋脸色凝重。",
        existing_character_names={"林峰", "周远"},
        character_aliases_by_name={"林峰": {"青锋"}, "周远": {"赤霄"}},
    )

    assert accepted["character_updates"] == [
        {"name": "林峰", "emotion": "凝重", "evidence": "青锋脸色凝重"}
    ]
    assert any(
        item.get("name") == "青锋" and item.get("reason") == "unknown_character"
        for item in accepted["rejected_updates"]
    )

    wrong_alias = normalize_post_draft_memory(
        {
            "character_updates": [
                {"name": "林峰", "emotion": "凝重", "evidence": "赤霄脸色凝重"}
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        body="青锋站在门口，赤霄脸色凝重。",
        existing_character_names={"林峰", "周远"},
        character_aliases_by_name={"林峰": {"青锋"}, "周远": {"赤霄"}},
    )

    assert wrong_alias["character_updates"] == []
    assert any(
        item.get("name") == "林峰" and item.get("reason") == "evidence_character_mismatch"
        for item in wrong_alias["rejected_updates"]
    )


def test_character_update_fields_must_be_supported_by_the_same_evidence():
    body = "青锋站在门口。青锋脸色凝重。"
    doorway_evidence = normalize_post_draft_memory(
        {
            "character_updates": [
                {
                    "name": "林峰",
                    "emotion": "凝重",
                    "location": "门口",
                    "evidence": "青锋站在门口",
                }
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        body=body,
        existing_character_names={"林峰"},
        character_aliases_by_name={"林峰": {"青锋"}},
    )

    assert doorway_evidence["character_updates"] == [
        {"name": "林峰", "location": "门口", "evidence": "青锋站在门口"}
    ]

    emotion_evidence = normalize_post_draft_memory(
        {
            "character_updates": [
                {"name": "林峰", "emotion": "凝重", "evidence": "青锋脸色凝重"}
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        body=body,
        existing_character_names={"林峰"},
        character_aliases_by_name={"林峰": {"青锋"}},
    )

    assert emotion_evidence["character_updates"] == [
        {"name": "林峰", "emotion": "凝重", "evidence": "青锋脸色凝重"}
    ]


def test_character_update_field_and_alias_must_share_one_evidence_clause():
    split_evidence = normalize_post_draft_memory(
        {
            "character_updates": [
                {"name": "林峰", "emotion": "凝重", "evidence": "青锋站门口。赤霄脸色凝重。"}
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        body="青锋站门口。赤霄脸色凝重。",
        existing_character_names={"林峰", "周远"},
        character_aliases_by_name={"林峰": {"青锋"}, "周远": {"赤霄"}},
    )

    assert split_evidence["character_updates"] == []

    same_clause = normalize_post_draft_memory(
        {
            "character_updates": [
                {"name": "林峰", "emotion": "凝重", "evidence": "青锋站门口，脸色凝重。"}
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        body="青锋站门口，脸色凝重。",
        existing_character_names={"林峰"},
        character_aliases_by_name={"林峰": {"青锋"}},
    )

    assert same_clause["character_updates"] == [
        {"name": "林峰", "emotion": "凝重", "evidence": "青锋站门口，脸色凝重。"}
    ]


@pytest.mark.parametrize(
    "evidence",
    [
        "青锋站门口，赤霄脸色凝重。",
        "青锋站门口.赤霄脸色凝重.",
    ],
)
def test_character_update_evidence_stops_at_the_next_known_character(evidence: str):
    result = normalize_post_draft_memory(
        {
            "character_updates": [
                {"name": "林峰", "emotion": "凝重", "evidence": evidence}
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        body=evidence,
        existing_character_names={"林峰", "周远"},
        character_aliases_by_name={"林峰": {"青锋"}, "周远": {"赤霄"}},
    )

    assert result["character_updates"] == []


def test_character_update_ignores_target_alias_used_as_an_object():
    evidence = "赤霄看着青锋，脸色凝重。"

    result = normalize_post_draft_memory(
        {
            "character_updates": [
                {"name": "林峰", "emotion": "凝重", "evidence": evidence}
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        body=evidence,
        existing_character_names={"林峰", "周远"},
        character_aliases_by_name={"林峰": {"青锋"}, "周远": {"赤霄"}},
    )

    assert result["character_updates"] == []


def test_character_update_switches_subject_only_when_alias_starts_a_subclause():
    evidence = "赤霄看着青锋，青锋脸色凝重。"

    result = normalize_post_draft_memory(
        {
            "character_updates": [
                {"name": "林峰", "emotion": "凝重", "evidence": evidence}
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        body=evidence,
        existing_character_names={"林峰", "周远"},
        character_aliases_by_name={"林峰": {"青锋"}, "周远": {"赤霄"}},
    )

    assert result["character_updates"] == [
        {"name": "林峰", "emotion": "凝重", "evidence": evidence}
    ]


def test_memory_prompt_lists_game_id_but_requires_real_character_name_for_updates():
    prompt = build_post_draft_memory_prompt(
        "青锋脸色凝重。",
        existing_character_names={"林峰"},
        character_aliases_by_name={"林峰": {"青锋"}},
    )

    assert "林峰（游戏ID：青锋）" in prompt
    assert "character_updates.name必须返回真实人物名" in prompt


def test_attribute_allocation_requires_local_remaining_evidence_even_when_body_has_zero_points():
    body = "夜烬把五点加到智力上，确认加点后，可用属性点归零。法杖耐久也归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {
                        "allocations": {"智力": 5},
                        "remaining": 0,
                    }
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "法杖耐久也归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_accepts_character_action_through_system_panel():
    body = "夜烬打开系统面板，把五点加到智力上。确认加点后，可用属性点归零。"
    payload = {
        "ledger_updates": {
            "protagonist": {
                "attribute_allocation": {
                    "allocations": {"智力": 5},
                    "remaining": 0,
                }
            }
        },
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
            "protagonist.attribute_allocation.remaining": "可用属性点归零",
        },
    }

    result = normalize_post_draft_memory(payload, body=body, existing_character_names={"夜烬"})

    assert result["ledger_updates"] == payload["ledger_updates"]


def test_attribute_allocation_memory_rejects_quoted_conditional_hypothesis():
    body = "短发玩家说：‘如果夜烬把五点加到智力上，确认后智力就会从五变成十，可用属性点归零。’"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {"allocations": {"智力": 5}, "remaining": 0}
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
        protagonist_aliases={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_memory_accepts_actual_turn_after_same_sentence_condition():
    body = "“如果保留五点会更灵活”，夜烬还是把五点加到智力上。随后他点下确认，可用属性点归零。"
    payload = {
        "ledger_updates": {
            "protagonist": {
                "attribute_allocation": {"allocations": {"智力": 5}, "remaining": 0}
            }
        },
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
            "protagonist.attribute_allocation.remaining": "可用属性点归零",
        },
    }

    result = normalize_post_draft_memory(
        payload,
        body=body,
        existing_character_names={"夜烬"},
        protagonist_aliases={"夜烬"},
    )

    assert result["ledger_updates"] == payload["ledger_updates"]


def test_attribute_allocation_memory_rejects_conditional_action_without_explicit_turn():
    body = "如果拿到五点，夜烬把五点加到智力上。确认后，智力会从五变成十，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {"allocations": {"智力": 5}, "remaining": 0}
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
        protagonist_aliases={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_memory_rejects_ruo_condition_without_a_fixed_expression_exception():
    body = "若有机会，夜烬把五点加到智力上。确认后，智力会从五变成十，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {"protagonist": {"attribute_allocation": {"allocations": {"智力": 5}, "remaining": 0}}},
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_memory_rejects_conditional_action_with_actuality_word():
    body = "如果拿到五点，夜烬还是把五点加到智力上。确认后，智力会从五变成十，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attribute_allocation": {"allocations": {"智力": 5}, "remaining": 0}
                }
            },
            "ledger_evidence": {
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
        protagonist_aliases={"夜烬"},
    )

    assert result["ledger_updates"] == {}


def test_attribute_allocation_memory_prefers_directive_over_final_attribute_mirrors():
    body = "夜烬打开面板，把五点加到智力上。确认后，智力从五变成十，可用属性点归零。夜烬站在灰狼坡。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attributes": {"智力": 10},
                    "unallocated_attribute_points": 0,
                    "attribute_allocation": {"allocations": {"智力": 5}, "remaining": 0},
                    "location": "灰狼坡",
                }
            },
            "ledger_evidence": {
                "protagonist.attributes.智力": "智力从五变成十",
                "protagonist.unallocated_attribute_points": "可用属性点归零",
                "protagonist.attribute_allocation.allocations.智力": "把五点加到智力上",
                "protagonist.attribute_allocation.remaining": "可用属性点归零",
                "protagonist.location": "灰狼坡",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
        protagonist_aliases={"夜烬"},
    )

    assert result["ledger_updates"] == {
        "protagonist": {
            "attribute_allocation": {"allocations": {"智力": 5}, "remaining": 0},
            "location": "灰狼坡",
        }
    }


def test_non_protagonist_attributes_do_not_require_protagonist_allocation_action():
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "monster": {
                    "attributes": {"力量": 12},
                    "remaining": 0,
                    "reason": "受伤",
                }
            },
            "ledger_evidence": {
                "monster.attributes.力量": "灰狼力量增加到12",
                "monster.remaining": "剩余0点",
                "monster.reason": "受伤",
            },
        },
        body="灰狼力量增加到12，剩余0点的原因是受伤。",
        existing_character_names=set(),
    )

    assert result["ledger_updates"] == {"monster": {"attributes": {"力量": 12}}}


def test_attribute_state_aliases_accept_visible_post_allocation_values():
    body = "夜烬把五点加到智力上，确认后智力从五变成十，可用属性点归零。"
    result = normalize_post_draft_memory(
        {
            "ledger_updates": {
                "protagonist": {
                    "attributes": {"智力": 10},
                    "unallocated_attribute_points": 0,
                }
            },
            "ledger_evidence": {
                "protagonist.attributes.智力": "智力从五变成十",
                "protagonist.unallocated_attribute_points": "可用属性点归零",
            },
        },
        body=body,
        existing_character_names={"夜烬"},
    )

    assert result["ledger_updates"] == {
        "protagonist": {"attributes": {"智力": 10}, "unallocated_attribute_points": 0}
    }


def test_invalid_payload_and_fields_return_normalized_empty_result():
    for payload in (None, [], "bad payload", {"facts": "not-a-list"}):
        result = normalize_post_draft_memory(
            payload,
            body="正文。",
            existing_character_names=set(),
        )

        assert result["summary"] == ""
        assert result["facts"] == []
        assert result["unresolved_threads"] == []
        assert result["character_updates"] == []
        assert result["ledger_updates"] == {}


def test_missing_evidence_is_rejected_without_raising():
    result = normalize_post_draft_memory(
        {
            "facts": [{"text": "无证据事实"}],
            "unresolved_threads": [{"text": "无证据悬念"}],
            "character_updates": [{"name": "林照", "location": "偏殿"}],
            "ledger_updates": {"protagonist": {"location": "偏殿"}},
            "ledger_evidence": {},
        },
        body="林照回到偏殿。",
        existing_character_names={"林照"},
    )

    assert result["facts"] == []
    assert result["unresolved_threads"] == []
    assert result["character_updates"] == []
    assert result["ledger_updates"] == {}


def test_fallback_uses_only_final_body_and_keeps_no_state_updates():
    body = "林照把断香炉搬回偏殿。周执事让他明早去账房回话。"

    result = fallback_post_draft_memory(body)

    assert result["summary"]
    assert result["summary"] in body
    assert result["next_focus"] == ""
    assert result["character_updates"] == []
    assert result["ledger_updates"] == {}


def test_prompt_declares_final_body_as_the_only_factual_source():
    prompt = build_post_draft_memory_prompt(
        "林照把断香炉搬回偏殿。",
        previous_summary="上一章摘要",
        existing_character_names={"林照"},
        genre="仙侠",
        fact_locks={"planned_fact": "林照得到三枚灵石"},
    )

    assert "最终正文是唯一事实来源" in prompt
    assert "计划、大纲、模拟只是上下文，不能直接当事实" in prompt
    assert "JSON only" in prompt
    assert "林照把断香炉搬回偏殿。" in prompt


def test_prompt_documents_attribute_allocation_evidence_leaf_paths():
    prompt = build_post_draft_memory_prompt(
        "夜烬把五点加到智力上。",
        existing_character_names={"夜烬"},
        genre="网游",
    )

    assert "attribute_allocation" in prompt
    assert "allocations.智力" in prompt
    assert "remaining" in prompt
