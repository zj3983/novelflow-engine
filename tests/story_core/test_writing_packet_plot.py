from packages.story_core.engine import ChapterBundle
from packages.story_core.models import StoryState
from packages.story_core.writing_packet import build_codex_writing_packet


def test_packet_exposes_plot_simulation_for_prose_renderer():
    story = StoryState(story_id="s-packet-plot", outline="网游开服。", genre="网游", style="白描升级流")
    plot = {
        "mode": "plot-first",
        "reader_hook": "读者要看到夜烬暗中滚出领先。",
        "chapter_desire": "夜烬想补齐清道夫委托。",
        "obstacle_chain": ["法力不足", "法杖快裂", "旁人会误判"],
        "choice_point": "先兑现奖励还是继续隐藏来源。",
        "payoff": "完成委托，换到补给。",
        "cost": "花光三十铜。",
        "emotional_turn": "从紧绷变成更谨慎。",
        "outsider_misread": "别人只当他运气好。",
        "ending_hook": "后坡入口亮起。",
    }
    bundle = ChapterBundle(
        chapter_number=2,
        body="",
        next_outline="去后坡入口。",
        updated_story=story,
        simulation_plan={"plot_simulation": plot},
    )

    packet = build_codex_writing_packet(story, bundle)

    assert packet["plot_simulation"] == plot
    assert "plot_simulation" in packet["prose_renderer"]["input_boundary"]["allowed"]
