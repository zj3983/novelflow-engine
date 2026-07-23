from packages.story_core.simplified_review import build_simplified_review


def test_simplified_review_only_blocks_hard_errors():
    report = build_simplified_review(
        {
            "issues": ["body_too_short"],
            "writing_review": {"issues": ["对话不够自然。", "AI味偏重：报告腔明显。"]},
        }
    )

    assert report["pass"] is False
    assert report["has_hard_errors"] is True
    assert report["categories"]["hard"]["count"] == 1
    assert report["categories"]["dialogue"]["count"] == 1
    assert report["categories"]["ai_flavor"]["count"] == 1
    assert report["needs_revision"] is True


def test_simplified_review_keeps_advisory_issues_non_blocking():
    report = build_simplified_review(
        {"writing_review": {"pass": False, "issues": ["对话不够自然。", "章末动作不够具体。"]}}
    )

    assert report["pass"] is True
    assert report["has_hard_errors"] is False
    assert report["needs_revision"] is True
    assert report["categories"]["dialogue"]["count"] == 1
    assert all(item["severity"] == "advisory" for item in report["issues"])


def test_simplified_review_does_not_revise_for_ordinary_prose_advice():
    report = build_simplified_review(
        {"writing_review": {"pass": False, "issues": ["章末动作还可以更具体。"]}}
    )

    assert report["pass"] is True
    assert report["needs_revision"] is False
    assert report["categories"]["prose"]["count"] == 1


def test_simplified_review_revises_ai_flavor_once():
    report = build_simplified_review(
        {"writing_review": {"pass": False, "issues": ["AI味偏重：报告腔明显。"]}}
    )

    assert report["needs_revision"] is True
    assert report["categories"]["ai_flavor"]["count"] == 1


def test_simplified_review_deduplicates_and_limits_main_issues():
    report = build_simplified_review(
        {
            "writing_review": {
                "issues": [
                    "对话不够自然。",
                    "对话不够自然。",
                    "剧情推进偏慢。",
                    "章末动作不够具体。",
                    "段首主语重复。",
                    "AI味偏重：报告腔明显。",
                    "抽象总结过多。",
                ]
            },
            "ai_flavor_review": {"issues": ["AI味偏重：报告腔明显。"]},
        }
    )

    assert len(report["issues"]) == 3
    assert [item["message"] for item in report["issues"]].count("对话不够自然。") == 1
    assert len(report["revision_plan"]) <= 3
    assert report["revision_plan"][0].startswith("对话不够自然")


def test_simplified_review_exposes_one_consolidated_status():
    report = build_simplified_review(
        {
            "writing_review": {
                "issues": ["对话不够自然。", "AI味偏重：报告腔明显。"],
                "reader_agent_review": {"issues": ["对话不够自然。"]},
                "editor_agent_review": {"issues": ["AI味偏重：报告腔明显。"]},
            }
        }
    )

    assert report["status"] == "needs_revision"
    assert report["agent_label"] == "综合审稿"
    assert len(report["issues"]) == 2


def test_simplified_review_reads_nested_agent_issues_for_legacy_chapters():
    report = build_simplified_review(
        {
            "writing_review": {
                "reader_agent_review": {"issues": ["开头进入剧情太慢。"]},
                "editor_agent_review": {"issues": ["同一信息重复解释。"]},
                "reviewer_agent_review": {"issues": ["人物状态与上一章冲突。"]},
            }
        }
    )

    assert report["has_hard_errors"] is True
    assert report["categories"]["hard"]["count"] == 1
    assert report["categories"]["prose"]["count"] == 2


def test_simplified_review_hides_internal_validation_field_names():
    report = build_simplified_review(
        {"issues": ["primary_conflict", "secondary_conflict", "event_beat", "writing_review", "对话不够自然。"]}
    )

    assert [item["message"] for item in report["issues"]] == ["对话不够自然。"]


def test_simplified_review_blocks_locked_outline_amount_mismatches():
    report = build_simplified_review(
        {
            "writing_review": {
                "issues": [
                    "开篇余额不一致：正文开篇必须保留27.60元。",
                    "大纲金额不一致：正文必须保留明确到账金额1764.00元。",
                    "章末余额不一致：现实余额必须是312.60元。",
                ]
            }
        }
    )

    assert report["has_hard_errors"] is True
    assert report["categories"]["hard"]["count"] == 3
