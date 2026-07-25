from packages.story_core.world_consistency_review import review_world_event_consistency


def _systemic_scene_card() -> dict:
    return {
        "scene_id": "s3-small-verify",
        "state_delta": {
            "game_world_simulation": {
                "systemic_simulation": {
                    "ledger_delta": {
                        "cost_delta": {"hp": -54, "mp": -60, "durability": -6},
                        "hidden_system_delta": {"chaos_seed_anomaly_score": 7},
                    },
                    "visibility_layers": {
                        "guild": [
                            "Guilds can infer only from repeated public listings, route witnesses, rare items, or NPC anomalies."
                        ],
                        "npc": ["NPCs cannot know hidden talent or real identity."],
                    },
                }
            }
        },
    }


def test_world_consistency_review_flags_systemic_ledger_and_visibility_breaks():
    body = (
        "Night Ember finished the fight with full mana and an undamaged staff. "
        "The White Robe guild immediately locked his coordinates and identified his hidden talent."
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=[_systemic_scene_card()])

    assert not review["pass"]
    assert review["scores"]["systemic_consistency"] < 8
    assert any("systemic" in issue.lower() for issue in review["issues"])


def test_world_consistency_review_accepts_systemic_ledger_and_visibility_surface():
    body = (
        "Night Ember checked the panel: his mana had bottomed out, his health had dropped, "
        "and the staff durability was red. The guild could only see route noise and weak public traces."
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=[_systemic_scene_card()])

    assert review["scores"]["systemic_consistency"] == 8
    assert review["issues"] == []


def test_world_consistency_review_does_not_treat_hidden_identity_protection_as_exposure():
    body = (
        "平台提示买家不能查看卖方现实身份，匿名交易也不会公开隐藏天赋。"
        "担保交易完成后，夜烬的来源没有暴露。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=[_systemic_scene_card()])

    assert not any("visibility break" in issue.lower() for issue in review["issues"])
