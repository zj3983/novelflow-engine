from scripts.plot_review_trend import render_trend


def test_render_trend_outputs_recent_review_rows():
    records = [
        {
            "chapter": 1,
            "operation": "generate",
            "hard_count": 2,
            "soft_count": 1,
            "beats_completion": 0.75,
            "hook_type": "choice",
            "failed_scores": ["pov_boundary", "protagonist_speech"],
        },
        {
            "chapter": 2,
            "operation": "rewrite",
            "hard_count": 0,
            "soft_count": 1,
            "beats_completion": 1.0,
            "hook_type": "crisis",
            "failed_scores": [],
        },
    ]

    output = render_trend(records, limit=2)

    assert "Review Trend" in output
    assert "generate" in output
    assert "rewrite" in output
    assert "75%" in output
    assert "pov_boundary,protagonist_speech" in output
