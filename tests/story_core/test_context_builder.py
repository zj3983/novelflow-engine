from packages.story_core.context.context_builder import build_context_package


def test_context_builder_selects_requested_sections_and_records_exclusions():
    package = build_context_package(
        {
            "outline": "主线大纲",
            "adjacent_chapters": ["上一章"],
            "characters": [{"name": "夜烬"}],
            "relationships": [{"from": "夜烬", "to": "洛婶"}],
            "foreshadowings": [{"id": "seed-1", "status": "open"}],
            "world": {"rules": ["规则一"]},
            "genre": {"id": "web_game"},
            "long_term_memory": ["旧记忆"],
            "author_request": "节奏快一点",
        },
        requested_sections=("outline", "characters", "foreshadowings", "author_request"),
        chapter_number=3,
    )

    assert package.chapter_number == 3
    assert package.sections["outline"] == "主线大纲"
    assert package.sections["characters"] == [{"name": "夜烬"}]
    assert "world" in package.excluded_sections
    assert "long_term_memory" in package.excluded_sections
    assert package.sources["outline"] == "project.outline"
    assert package.snapshot_id


def test_context_builder_does_not_mutate_source_data():
    source = {"characters": [{"name": "夜烬"}], "outline": "主线"}

    package = build_context_package(source, requested_sections=("characters",))
    package.sections["characters"][0]["name"] = "被修改的副本"

    assert source["characters"][0]["name"] == "夜烬"
