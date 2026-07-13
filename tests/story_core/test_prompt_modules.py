from packages.story_core.prompt_modules import modules_for_stage, prompt_module_catalog, replaceable_slots


def test_prompt_modules_have_single_stage_and_owner_contract():
    catalog = prompt_module_catalog()
    assert catalog
    assert all(item["key"] and item["owner"] and item["stage"] for item in catalog)
    assert len({item["key"] for item in catalog}) == len(catalog)
    assert any(item["role"] == "fact_source" for item in catalog)
    assert any(item["replaceable"] for item in catalog)


def test_writing_stage_has_separate_plot_character_genre_and_skill_modules():
    keys = [item.key for item in modules_for_stage("writing")]
    assert keys.index("chapter_plan") < keys.index("character_context")
    assert keys.index("character_context") < keys.index("genre_context")
    assert "skill_context_dialogue" in keys
    assert "review_context" not in keys


def test_revision_stage_reads_review_and_source_body_but_not_full_character_library():
    keys = {item.key for item in modules_for_stage("revision")}
    assert {"review_context", "source_body", "character_context"} <= keys
    assert "character_library" not in keys


def test_replaceable_slots_are_limited_to_writing_method_defaults():
    slots = replaceable_slots()
    assert slots == {"genre": "genre_context", "style": "style_context"}
    assert "core_context" not in slots.values()
    assert "outline_context" not in slots.values()
    assert "chapter_plan" not in slots.values()
    assert "character_context" not in slots.values()
