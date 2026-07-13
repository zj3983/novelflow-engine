from packages.story_core.models import StoryState
from packages.story_core.world_simulation_gate import needs_world_simulation, world_simulation_decision


def test_game_opening_always_needs_world_simulation():
    story = StoryState(story_id="s", outline="网游开服", genre="网游", style="白描")
    assert needs_world_simulation(story, 1, event_plan={}, chapter_seed={}) is True


def test_plain_dialogue_chapter_skips_world_simulation():
    story = StoryState(story_id="s", outline="都市人物关系", genre="都市", style="白描")
    assert needs_world_simulation(story, 4, event_plan={"turn": "两人把误会说开"}, chapter_seed={}) is False


def test_task_or_resource_change_runs_world_simulation():
    story = StoryState(story_id="s", outline="网游升级", genre="网游", style="白描")
    assert needs_world_simulation(story, 4, event_plan={"quest_beats": ["交任务"]}, chapter_seed={}) is True


def test_npc_or_quest_mention_alone_does_not_trigger_simulation():
    story = StoryState(story_id="s", outline="都市人物关系", genre="都市", style="白描")
    assert needs_world_simulation(story, 4, event_plan={"npc_beats": ["两人聊起任务"]}, chapter_seed={}) is False


def test_external_effect_flag_allows_npc_reaction_to_trigger_simulation():
    story = StoryState(story_id="s", outline="都市人物关系", genre="都市", style="白描")
    assert needs_world_simulation(story, 4, event_plan={"npc_beats": ["柜台改变办理条件"], "external_effect": True}, chapter_seed={}) is True


def test_long_term_seed_rules_do_not_trigger_simulation_for_a_dialogue_chapter():
    story = StoryState(story_id="s", outline="都市人物关系", genre="都市", style="白描")
    seed = {"required_beats": ["任务、装备和货币要保持连续"], "forbidden_moves": ["不要改变任务状态"]}
    assert needs_world_simulation(story, 4, event_plan={"turn": "两人把误会说开"}, chapter_seed=seed) is False


def test_simulation_decision_exposes_debug_reason_and_triggers():
    story = StoryState(story_id="s", outline="网游升级", genre="网游", style="白描")
    decision = world_simulation_decision(story, 4, event_plan={"quest_beats": ["交任务"]}, chapter_seed={})
    assert decision["run"] is True
    assert decision["reason"] == "chapter_external_effect"
    assert "quest_beats" in decision["triggers"]
