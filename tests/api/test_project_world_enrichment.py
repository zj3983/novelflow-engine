from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import stories as story_routes
from apps.api.storage import SQLiteStoryStore, _project_world_facts
from packages.story_core.models import NovelProject


def test_project_world_enrichment_updates_project(monkeypatch, tmp_path):
    monkeypatch.setattr(story_routes, "store", SQLiteStoryStore(str(tmp_path / "stories.db")))
    client = TestClient(app)
    project_id = "p-enrich-test"
    client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "Enrich Test",
            "world_summary": "A thin imported world.",
            "current_focus": "Prepare before chapter one.",
            "world_blueprint": {"premise": "A thin imported world."},
            "character_profiles": [{"name": "Lin Yue", "motivation": "Find the clue."}],
            "relationship_graph": [],
        },
    )

    def fake_enrich(project):
        project.world_blueprint = {
            "premise": "A deepened imported world.",
            "world_rules": ["The first clue must create pressure."],
            "power_system": ["Influence grows through secrets."],
            "progression_rules": ["Power must grow through paid clues."],
            "economy_rules": ["Clues have changing market prices."],
            "quest_rules": ["Each clue has a failure cost."],
            "faction_rules": ["Rivals react to visible progress."],
            "panel_rules": ["Status feedback stays short."],
            "chapter_formula": ["Every chapter closes a small gain loop."],
            "forbidden_breaks": ["Do not skip costs."],
            "locations": [{"name": "Ink Shop", "description": "The first scene anchor."}],
            "factions": [],
            "current_arc": "The lead prepares before chapter one.",
            "constraints": [],
            "relationship_graph": [{"source": "Lin Yue", "target": "Ink Shop", "bond": "investigates"}],
        }
        project.character_profiles = [
            {
                "name": "Lin Yue",
                "role": "protagonist",
                "motivation": "Find the clue before rivals erase it.",
                "current_state": "Ready for chapter one.",
            }
        ]
        project.relationship_graph = project.world_blueprint["relationship_graph"]
        project.world_summary = "A deepened imported world."
        return project

    monkeypatch.setattr(story_routes, "enrich_project_world", fake_enrich)

    response = client.post(f"/projects/{project_id}/enrich-world")

    assert response.status_code == 200
    payload = response.json()
    assert payload["world_blueprint"]["premise"] == "A deepened imported world."
    assert payload["pipeline_stage"] == "world_ready"
    assert payload["world_blueprint"]["progression_rules"] == ["Power must grow through paid clues."]
    assert payload["character_profiles"][0]["motivation"] == "Find the clue before rivals erase it."
    assert payload["relationship_graph"][0]["target"] == "Ink Shop"


def test_project_rulebook_enrichment_allowed_after_story_started(monkeypatch, tmp_path):
    monkeypatch.setattr(story_routes, "store", SQLiteStoryStore(str(tmp_path / "stories.db")))
    client = TestClient(app)
    project_id = "p-rulebook-test"
    story_id = "s-rulebook-test"
    client.post(
        "/stories",
        json={
            "story_id": story_id,
            "outline": "A game world with levels and guilds.",
            "genre": "网游",
            "style": "升级流",
            "characters": [{"name": "Su Ye", "role": "protagonist", "goals": ["hide the talent"], "frozen": False}],
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "Rulebook Test",
            "world_summary": "A game world.",
            "current_focus": "Keep the hidden talent secret.",
            "active_story_id": story_id,
        },
    )

    def fake_enrich(project):
        project.world_blueprint = {
            **project.world_blueprint,
            "premise": "A game world.",
            "progression_rules": ["Levels and EXP must stay consistent."],
            "economy_rules": ["Rare drops need anonymous selling risk."],
            "constraints": ["Every chapter needs gain and pressure."],
        }
        project.author_constraints = ["Every chapter needs gain and pressure."]
        return project

    monkeypatch.setattr(story_routes, "enrich_project_rulebook", fake_enrich)

    response = client.post(f"/projects/{project_id}/enrich-rulebook")

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipeline_stage"] == "simulating"
    assert payload["status"] == "simulating"
    assert payload["author_constraints"] == ["Every chapter needs gain and pressure."]
    assert payload["world_blueprint"]["economy_rules"] == ["Rare drops need anonymous selling risk."]


def test_project_world_facts_include_living_world_reactions():
    project = NovelProject(
        project_id="p-world-facts",
        title="Living World",
        world_summary="A market-driven starter town.",
        world_blueprint={
            "living_world": {
                "daily_routines": ["商人玩家每天盯交易行价差。"],
                "information_network": {"channels": ["交易行价格榜"]},
                "reaction_rules": ["大量低价材料会引起公会外围追踪。"],
            }
        },
    )

    facts = _project_world_facts(project)

    assert "世界摘要：A market-driven starter town." in facts
    assert "日常运转：商人玩家每天盯交易行价差。" in facts
    assert "消息渠道：交易行价格榜" in facts
    assert "世界反应：大量低价材料会引起公会外围追踪。" in facts
