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
