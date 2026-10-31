from packages.story_core.orchestrator import _should_run_full_revision
from packages.story_core.simplified_review import build_simplified_review


def test_confirmed_legacy_review_keeps_full_review_advice_visible():
    result = build_simplified_review({
        "ok": True, "issues": [], "writing_review": {"pass": True},
        "complete_writing_review": {"pass": True, "issues": ["对话不自然。"],
                                   "prose_style_review": {"pass": False, "issues": ["对话不自然。"], "revision_plan": ["补清对话对象。"]}},
    })
    assert result["pass"] is True
    assert result["total_issues"] == 1
    assert result["issues"][0]["suggestion"] == "补清对话对象。"


def test_explicit_v2_review_does_not_resurrect_old_complete_review():
    from packages.story_core.review.contracts import ReviewResult
    result = build_simplified_review({
        "review_result": ReviewResult.from_findings([]).to_dict(),
        "complete_writing_review": {"issues": ["旧版本对话不自然。"]},
    })
    assert result["total_issues"] == 0


def test_attribute_allocation_mismatch_is_a_hard_error() -> None:
    report = build_simplified_review(
        {"writing_review": {"issues": ["attribute_allocation_mismatch: 正文同章重复加点。"]}}
    )

    assert report["has_hard_errors"] is True
    assert report["categories"]["hard"]["count"] == 1


def test_explicit_finding_metadata_wins_over_message_keywords():
    report = build_simplified_review(
        {
            "review_result": {
                "schema_version": "review-result/v2",
                "status": "warning",
                "pass": True,
                "has_hard_errors": False,
                "needs_revision": False,
                "issues": [
                    {
                        "code": "prose.timeline_metaphor",
                        "category": "prose",
                        "blocking": False,
                        "message": "这句用了时间线作为比喻。",
                        "suggestion": "换成具体动作。",
                        "source": "prose",
                    }
                ],
            }
        }
    )

    assert report["status"] == "warning"
    assert report["has_hard_errors"] is False
    assert report["issues"][0]["category"] == "prose"


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


def test_simplified_review_treats_excess_length_as_advisory():
    report = build_simplified_review({"issues": ["body_too_long"]})

    assert report["pass"] is True
    assert report["has_hard_errors"] is False
    assert report["categories"]["hard"]["count"] == 0
    assert report["categories"]["prose"]["count"] == 1


def test_simplified_review_preserves_modular_length_blocker_and_readable_message():
    result = build_simplified_review({
        "ok": False,
        "manual_quality_override": True,
        "writing_review": {
            "pass": False,
            "issues": ["chapter.length_too_long"],
            "blocking": [{"code": "chapter.length_too_long", "message": "正文约7050字，超过5700字。", "source": "deterministic"}],
        },
    })
    assert result["status"] == "blocked"
    assert result["has_hard_errors"] is True
    assert result["pass"] is False
    assert result["total_issues"] == 1
    assert result["issues"][0]["message"] == "正文约7050字，超过5700字。"


def test_simplified_review_keeps_structured_blocker_without_string_issue():
    result = build_simplified_review({"writing_review": {
        "issues": [],
        "blocking": [{"code": "new.deterministic_failure", "message": "本章确定性检查失败。", "source": "deterministic"}],
    }})
    assert result["status"] == "blocked"
    assert result["issues"][0]["severity"] == "blocking"


def test_style_blocker_keeps_ai_category_and_blocking_severity():
    result = build_simplified_review({"writing_review": {
        "issues": ["style.simile_stacking"],
        "blocking": [{"code": "style.simile_stacking", "message": "正文使用了11处显式比喻，密度过高。", "source": "deterministic"}],
    }})
    assert result["categories"]["ai_flavor"]["count"] == 1
    assert result["categories"]["hard"]["count"] == 0
    assert result["status"] == "blocked"
    assert result["pass"] is False
    assert result["issues"][0]["code"] == "style.simile_stacking"
    assert result["issues"][0]["blocking"] is True


def test_legacy_review_distinguishes_missing_ai_check_from_zero_findings():
    unchecked = build_simplified_review({"writing_review": {"pass": True}})
    checked = build_simplified_review({"ai_flavor_review": {"pass": True, "issues": []}, "prose_style_review": {"pass": True, "issues": []}})
    assert unchecked["diagnostics"]["ai_flavor_check_executed"] is False
    assert checked["diagnostics"]["ai_flavor_check_executed"] is True


def test_length_advice_uses_readable_text_and_retains_code_for_annotations():
    report = build_simplified_review({"writing_review": {"issues": ["chapter.length_above_target"]}})
    assert report["issues"][0]["code"] == "chapter.length_above_target"
    assert report["issues"][0]["message"] == "正文字数超过目标上限，建议适当压缩。"


def test_simplified_review_marks_elliptical_dialogue_for_targeted_revision():
    report = build_simplified_review(
        {"writing_review": {"issues": ["现代中文对话不自然：连续省略对象的状态台词。"]}}
    )

    assert report["has_hard_errors"] is False
    assert report["has_blocking_dialogue"] is True
    assert report["issues"][0]["severity"] == "blocking"
    assert _should_run_full_revision(report) is True


def test_simplified_review_keeps_telegraphic_dialogue_as_visible_advice():
    report = build_simplified_review(
        {
            "writing_review": {
                "issues": [
                    "现代中文对话不自然：清单式短句“你守住校验，残镜若再拉你，立刻拒绝”、"
                    "电报码式台词“你守住校验，残镜若再拉你，立刻拒绝”。"
                ]
            }
        }
    )

    assert report["has_hard_errors"] is False
    assert report["has_blocking_dialogue"] is False
    assert report["issues"][0]["severity"] == "advisory"
    assert _should_run_full_revision(report) is False


def test_simplified_review_does_not_revise_for_ordinary_prose_advice():
    report = build_simplified_review(
        {"writing_review": {"pass": False, "issues": ["章末动作还可以更具体。"]}}
    )

    assert report["pass"] is True
    assert report["needs_revision"] is False
    assert report["categories"]["prose"]["count"] == 1


def test_simplified_review_keeps_scheduled_trope_miss_as_advice():
    report = build_simplified_review(
        {
            "writing_review": {
                "pass": False,
                "issues": ["套路节点未兑现：本章未写出当前节点「雨夜接下挑战」的正文动作或反馈。"],
                "revision_plan": ["按套路节点改：本章必须兑现「雨夜接下挑战」，并落到回报「赢得信任」。"],
            }
        }
    )

    assert report["pass"] is True
    assert report["has_hard_errors"] is False
    assert report["needs_revision"] is False
    assert report["categories"]["hard"]["count"] == 0
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
    assert report["revision_plan"] == [item["suggestion"] for item in report["issues"]]


def test_simplified_review_preserves_issue_action_pairs_when_categories_reorder():
    report = build_simplified_review(
        {
            "writing_review": {
                "issues": ["对话不够自然。", "设定冲突：规划实体写错。"],
                "revision_plan": ["修对白。", "修规划词。"],
            }
        }
    )

    assert [
        (item["message"], item["suggestion"])
        for item in report["issues"]
    ] == [
        ("设定冲突：规划实体写错。", "修规划词。"),
        ("对话不够自然。", "修对白。"),
    ]
    assert report["revision_plan"] == ["修规划词。", "修对白。"]


def test_simplified_review_prefers_suggestion_embedded_in_issue():
    report = build_simplified_review(
        {
            "issues": [
                {
                    "message": "人物状态与上一章冲突。",
                    "suggestion": "恢复上一章已经确认的人物状态。",
                }
            ],
            "revision_plan": ["不应覆盖 issue 自带建议。"],
        }
    )

    assert report["issues"][0]["suggestion"] == "恢复上一章已经确认的人物状态。"
    assert report["revision_plan"] == ["恢复上一章已经确认的人物状态。"]


def test_simplified_review_replaces_aggregate_plan_with_later_embedded_suggestion():
    message = "设定冲突：规划实体写错。"
    report = build_simplified_review(
        {
            "writing_review": {
                "issues": [message],
                "revision_plan": ["aggregate-wrong"],
                "reviewer_agent_review": {
                    "issues": [
                        {
                            "message": message,
                            "suggestion": "embedded-correct",
                        }
                    ]
                },
            }
        }
    )

    assert report["issues"][0]["suggestion"] == "embedded-correct"
    assert report["revision_plan"] == ["embedded-correct"]


def test_simplified_review_prefers_nested_paired_plan_over_aggregate_paired_plan():
    message = "设定冲突：规划实体写错。"
    report = build_simplified_review(
        {
            "writing_review": {
                "issues": [message],
                "revision_plan": ["aggregate-wrong"],
                "reviewer_agent_review": {
                    "issues": [message],
                    "revision_plan": ["nested-paired-correct"],
                },
            }
        }
    )

    assert report["issues"][0]["suggestion"] == "nested-paired-correct"
    assert report["revision_plan"] == ["nested-paired-correct"]


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


def test_simplified_review_blocks_missing_required_game_surfaces_but_not_repetition():
    report = build_simplified_review(
        {
            "writing_review": {
                "issues": [
                    "第一章缺少带身份栏的角色面板。",
                    "首次正式交战前缺少简洁怪物面板。",
                    "场景卡必写内容缺失：s6 缺少真实到账、现实急账处理。",
                    "段首主语连续重复：获得连续作为段首出现3次。",
                ]
            }
        }
    )

    assert report["has_hard_errors"] is True
    assert report["categories"]["hard"]["count"] == 3
    assert report["categories"]["ai_flavor"]["count"] == 1


def test_simplified_review_blocks_required_progression_and_project_anchors():
    report = build_simplified_review(
        {
            "writing_review": {
                "issues": [
                    "章节写死了游戏币与现实货币的汇率，但世界档案没有明确官方兑换行情。",
                    "attribute_allocation_missing: 当前章节计划加点，但正文缺少确认结果。",
                    "第一章缺少“混沌之种：未解析”钩子。",
                    "第一章缺少“底层协议校验通过”触发锚点。",
                ]
            }
        }
    )

    assert report["has_hard_errors"] is True
    assert report["categories"]["hard"]["count"] == 4
