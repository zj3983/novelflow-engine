from packages.story_core.review.quality_gate import ReviewDependencies, review_chapter_body


def _pass_review(*_args, **_kwargs):
    return {"pass": True, "scores": {}, "issues": [], "revision_plan": []}


def test_quality_gate_merges_selected_genre_review_into_compatible_report():
    class Profile:
        def review_chapter(self, *, context):
            assert context["chapter_number"] == 3
            return {
                "pass": True,
                "scores": {"genre_specific": 8},
                "issues": [],
                "revision_plan": [],
                "active_genre_reviews": {
                    "xuanhuan_review": {"pass": True, "scores": {}, "issues": []},
                },
            }

    dependencies = ReviewDependencies(
        profile_for=lambda _context: Profile(),
        review_continuity=lambda *_args, **_kwargs: {"issues": [], "revision_plan": []},
        review_fragments=lambda _body: [],
        review_consistency=_pass_review,
        review_style=_pass_review,
        review_prose_quality=_pass_review,
        review_adversarial_cuts=_pass_review,
        review_ai_flavor=_pass_review,
        review_reader_feel=_pass_review,
        review_cold_reader=_pass_review,
        review_plot_spine=_pass_review,
        review_critical_rules=_pass_review,
        build_scene_repair=lambda *_args, **_kwargs: [],
        report_progress=lambda _message: None,
    )

    report = review_chapter_body(
        chapter_number=3,
        body="林照推开门，确认院内无人。",
        event_plan={"next_focus": "检查院内"},
        genre_context={"genre": "xuanhuan"},
        dependencies=dependencies,
        min_chapter_chars=1,
        target_chapter_chars="1到10字",
        chapter_char_tolerance=0,
    )

    assert report["pass"] is True
    assert report["scores"]["genre_specific"] == 8
    assert report["xuanhuan_review"]["pass"] is True
    assert report["reader_agent_review"]["mode"] == "consolidated"
    assert report["editor_agent_review"]["mode"] == "consolidated"
    assert report["reviewer_agent_review"]["mode"] == "consolidated"
