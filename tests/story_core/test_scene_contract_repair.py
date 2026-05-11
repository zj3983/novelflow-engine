from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import StoryOrchestrator
from packages.story_core.scene_contract_repair import build_scene_contract_repair_plan
from packages.story_core.world_consistency_review import review_world_event_consistency


def _contract_scene_cards() -> list[dict]:
    return [
        {
            "scene_id": "s1-login",
            "template_id": "character_creation",
            "location": "login screen",
            "purpose": "Create the character.",
            "scene_contract": {
                "schema_version": "scene-contract/v1",
                "visible_consequences": [
                    {
                        "id": "panel_surface",
                        "description": "Show the character panel.",
                        "requires_any": ["panel", "Lv.1"],
                        "revision": "Keep the character panel visible.",
                    }
                ],
            },
        },
        {
            "scene_id": "s3-small-verify",
            "template_id": "small_verification",
            "location": "newbie field",
            "purpose": "Verify the drop advantage.",
            "scene_contract": {
                "schema_version": "scene-contract/v1",
                "visible_consequences": [
                    {
                        "id": "resource_cost_surface",
                        "description": "Show that the fight consumed mana.",
                        "requires_any": ["mana bottomed out", "low mana", "MP 0"],
                        "revision": "Add a panel/resource check that shows spent mana.",
                    },
                    {
                        "id": "inventory_delta_surface",
                        "description": "Show the loot entering inventory.",
                        "requires_any": ["backpack", "inventory", "loot"],
                        "revision": "Add backpack loot feedback with the new material count.",
                    },
                ],
            },
        },
    ]


def test_world_consistency_review_returns_structured_scene_contract_failures():
    review = review_world_event_consistency(
        "Night Ember created the character panel, then won and walked back.",
        world_events=[],
        scene_cards=_contract_scene_cards(),
    )

    failures = review["scene_contract_failures"]

    assert not review["pass"]
    assert [failure["scene_id"] for failure in failures] == ["s3-small-verify", "s3-small-verify"]
    assert {failure["consequence_id"] for failure in failures} == {
        "resource_cost_surface",
        "inventory_delta_surface",
    }
    assert failures[0]["rewrite_scope"] == "scene_only"
    assert "spent mana" in failures[0]["revision"]


def test_scene_contract_repair_plan_groups_failed_scenes_only():
    review = review_world_event_consistency(
        "Night Ember created the character panel, then won and walked back.",
        world_events=[],
        scene_cards=_contract_scene_cards(),
    )

    plan = build_scene_contract_repair_plan(review, _contract_scene_cards())

    assert plan["schema_version"] == "scene-contract-repair/v1"
    assert plan["rewrite_scope"] == "failed_scenes_only"
    assert plan["preserve_other_scenes"] is True
    assert [scene["scene_id"] for scene in plan["failed_scenes"]] == ["s3-small-verify"]
    failed_scene = plan["failed_scenes"][0]
    assert failed_scene["template_id"] == "small_verification"
    assert failed_scene["location"] == "newbie field"
    assert {item["id"] for item in failed_scene["missing_visible_consequences"]} == {
        "resource_cost_surface",
        "inventory_delta_surface",
    }


def test_revision_prompt_includes_targeted_scene_contract_repair_plan():
    story = StoryState(
        story_id="s-repair-prompt",
        outline="VRMMO hidden drop advantage.",
        genre="VRMMO",
        style="Tomato webnovel",
        characters=[CharacterState(name="Su Ye", role="protagonist", game_id="Night Ember")],
    )
    scene_cards = _contract_scene_cards()
    review = review_world_event_consistency(
        "Night Ember created the character panel, then won and walked back.",
        world_events=[],
        scene_cards=scene_cards,
    )
    plan = {
        "scene_cards": scene_cards,
        "event_plan": {"next_focus": "Find a service route."},
        "simulation_plan": {},
    }

    prompt = StoryOrchestrator()._revision_prompt(story, 1, "old body", plan, review)

    assert "scene_contract_repair_plan" in prompt
    assert "failed_scenes_only" in prompt
    assert "s3-small-verify" in prompt
    assert "只重写失败场景" in prompt
    assert "Add a panel/resource check that shows spent mana." in prompt
