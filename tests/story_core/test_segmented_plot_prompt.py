from packages.story_core.segmented_writing import build_segment_prompt, build_segment_specs


def test_segment_prompt_carries_plot_spine_without_backend_key():
    plan = {
        "simulation_plan": {
            "chapter_goal": "完成清道夫委托",
            "plot_simulation": {
                "reader_hook": "读者要看到夜烬暗中领先。",
                "chapter_desire": "夜烬想补齐两份毒腺。",
                "choice_point": "他要决定先交任务，还是先藏来源。",
                "payoff": "委托进度必须变化。",
                "cost": "付出蓝量或耐久。",
                "ending_hook": "后坡巡查前置任务露出。",
            },
        }
    }
    spec = build_segment_specs(2, plan)[0]

    prompt = build_segment_prompt(chapter_number=2, spec=spec, plan=plan)

    assert "剧情主线" in prompt
    assert "夜烬想补齐两份毒腺" in prompt
    assert "后坡巡查前置任务露出" in prompt
    assert "plot_simulation" not in prompt
