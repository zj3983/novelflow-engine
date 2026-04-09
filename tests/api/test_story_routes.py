from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def test_story_can_be_created_and_rolled_back():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-001",
            "outline": "A detective prince uncovers palace crimes.",
            "genre": "fantasy",
            "style": "noir",
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["current_chapter"] == 0
    assert create_resp.json()["history"] == []

    gen_resp = client.post("/stories/s-001/generate")
    assert gen_resp.status_code == 200
    assert gen_resp.json()["chapter_number"] == 1

    rollback_resp = client.post("/stories/s-001/rollback")
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["current_chapter"] == 0


def test_story_can_store_characters_and_freeze_them():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-characters",
            "outline": "A palace clerk learns the truth about the treasury.",
            "genre": "fantasy",
            "style": "court intrigue",
            "characters": [
                {
                    "name": "Pei An",
                    "role": "clerk",
                    "goals": ["protect the evidence"],
                    "frozen": False,
                }
            ],
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["characters"][0]["name"] == "Pei An"

    freeze_resp = client.post("/stories/s-characters/characters/Pei%20An/freeze")
    assert freeze_resp.status_code == 200
    assert freeze_resp.json()["characters"][0]["frozen"] is True


def test_rollback_restores_previous_story_state():
    client.post(
        "/stories",
        json={
            "story_id": "s-rollback-state",
            "outline": "A magistrate hunts the source of forged decrees.",
            "genre": "mystery",
            "style": "tense",
            "characters": [
                {
                    "name": "Lin Yue",
                    "role": "investigator",
                    "goals": ["find the forger"],
                    "frozen": False,
                    "relationships": {
                        "Su Wan": {
                            "target": "Su Wan",
                            "trust": 0.4,
                            "tension": 0.9,
                            "bond": "uneasy alliance",
                        }
                    },
                }
            ],
        },
    )

    client.post("/stories/s-rollback-state/generate")
    client.post("/stories/s-rollback-state/generate")

    rollback_resp = client.post("/stories/s-rollback-state/rollback")
    assert rollback_resp.status_code == 200

    story = rollback_resp.json()
    assert story["current_chapter"] == 1
    assert len(story["history"]) == 1
    assert story["history"][0]["chapter_number"] == 1
    relation = story["characters"][0]["relationships"]["Su Wan"]
    assert relation["trust"] == 0.3
    assert relation["tension"] == 1.0


def test_story_can_branch_from_a_previous_chapter():
    client.post(
        "/stories",
        json={
            "story_id": "s-branch-root",
            "outline": "Two rivals hunt a ledger buried under the imperial archives.",
            "genre": "fantasy",
            "style": "court intrigue",
            "characters": [
                {
                    "name": "Lin Yue",
                    "role": "investigator",
                    "goals": ["find the ledger"],
                    "frozen": False,
                }
            ],
        },
    )
    client.post("/stories/s-branch-root/generate")
    client.post("/stories/s-branch-root/generate")

    branch_resp = client.post(
        "/stories/s-branch-root/branch",
        json={"new_story_id": "s-branch-alt", "from_chapter": 1},
    )
    assert branch_resp.status_code == 200

    branch_story = branch_resp.json()
    assert branch_story["story_id"] == "s-branch-alt"
    assert branch_story["current_chapter"] == 1
    assert len(branch_story["history"]) == 1
    assert branch_story["history"][0]["chapter_number"] == 1

    original_story = client.get("/stories/s-branch-root")
    assert original_story.status_code == 200
    assert original_story.json()["current_chapter"] == 2
