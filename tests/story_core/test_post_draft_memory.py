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
                "evidence": "明早去账房回话",
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

    assert result["facts"] == ["断香炉已搬到偏殿"]
    assert result["unresolved_threads"] == ["账房为何找林照"]
    assert [item["name"] for item in result["character_updates"]] == ["林照"]
    assert result["character_updates"][0] == {
        "name": "林照",
        "goal": "明早去账房",
        "location": "偏殿",
        "evidence": "明早去账房回话",
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

    result = fallback_post_draft_memory(
        body,
        previous_next_focus="去账房回话",
    )

    assert result["summary"]
    assert result["summary"] in body
    assert result["next_focus"] == "去账房回话"
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
