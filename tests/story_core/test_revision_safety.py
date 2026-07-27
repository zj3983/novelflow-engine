from packages.story_core.revision_safety import choose_best_revision, choose_best_segment_revision, score_quality_report
from packages.story_core.orchestrator import StoryOrchestrator
from packages.story_core.segmented_writing import SegmentSpec
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import CharacterState, StoryState


def _quality(passed: bool, scores: dict[str, int], issues: list[str] | None = None) -> dict:
    return {
        "ok": passed,
        "issues": issues or [],
        "writing_review": {
            "pass": passed,
            "scores": scores,
            "issues": issues or [],
            "adversarial_cut_review": {"pass": passed, "cut_pressure": 0 if passed else 2, "cuts": []},
            "world_state_review": {"pass": passed, "issues": [] if passed else [{"type": "bad"}]},
        },
    }


def test_score_quality_report_rewards_passes_and_penalizes_issues():
    clean = _quality(True, {"genre_rules": 8, "prose_style_meta_language": 8})
    dirty = _quality(False, {"genre_rules": 5, "prose_style_meta_language": 4}, ["AI腔", "设定冲突"])

    assert score_quality_report(clean) > score_quality_report(dirty)


def test_choose_best_revision_rejects_candidate_that_scores_worse():
    original = _quality(True, {"genre_rules": 8, "prose_style_meta_language": 8})
    candidate = _quality(False, {"genre_rules": 5, "prose_style_meta_language": 4}, ["写入审稿词"])

    result = choose_best_revision(
        original_body="原稿正文",
        original_quality=original,
        candidate_body="更差的改稿",
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["selected"] == "original"
    assert result["body"] == "原稿正文"
    assert result["quality"] is original
    assert result["report"]["reason"] == "candidate_worse_than_original"


def test_choose_best_revision_accepts_candidate_that_improves_review():
    original = _quality(False, {"genre_rules": 5, "prose_style_meta_language": 5}, ["缺少职业面板"])
    candidate = _quality(True, {"genre_rules": 8, "prose_style_meta_language": 8})

    result = choose_best_revision(
        original_body="原稿正文",
        original_quality=original,
        candidate_body="更好的改稿",
        candidate_quality=candidate,
    )

    assert result["accepted"] is True
    assert result["selected"] == "candidate"
    assert result["body"] == "更好的改稿"
    assert result["quality"] is candidate
    assert result["report"]["reason"] == "candidate_not_worse"


class _BadRevisionOrchestrator(StoryOrchestrator):
    def _chat(self, story, prompt: str, *, max_tokens: int, json_mode: bool, agent: str = "director"):
        return "爽点已经兑现。读者期待已经满足。", ""


def test_revise_chapter_body_keeps_original_when_llm_revision_scores_worse():
    story = StoryState(
        story_id="s-revision-safety",
        outline="网游开服。",
        genre="网游",
        style="升级流",
        current_chapter=1,
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )
    original_body = (
        "苏叶登录游戏，角色夜烬站在灰烬村门口。\n"
        "【角色：夜烬】【等级：Lv.1】【职业：元素法师学徒】【经验：0/100】\n"
        "灰鼠从草根下钻出来，夜烬用火苗术完成第一次验证。"
    ) * 30
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="第1章 灰烬村的登录",
        body=original_body,
        next_outline="继续确认任务奖励。",
        event_plan={"next_focus": "继续确认任务奖励。", "world_reactions": ["洛婶只看到任务材料。"], "stakes": "现实账单逼近。"},
        updated_story=story,
    )
    review = {
        "pass": False,
        "scores": {"genre_rules": 7, "prose_style_meta_language": 8},
        "issues": ["需要补一点NPC服务。"],
        "revision_plan": ["只补NPC服务，不改事实。"],
    }

    body, quality, error = _BadRevisionOrchestrator().revise_chapter_body(story, bundle, review)

    assert error == ""
    assert body == original_body
    assert quality["revision_safety"]["accepted"] is False
    assert quality["revision_safety"]["selected"] == "original"


def test_manual_revision_instructions_are_not_short_circuited_by_local_patch(monkeypatch):
    story = StoryState(
        story_id="s-manual-revision-priority",
        outline="林照看守断香炉。",
        genre="xianxia",
        style="白描",
        current_chapter=1,
        characters=[CharacterState(name="林照", role="protagonist")],
    )
    original_body = "昨晚那句话是真的，今晚这句也是真的。" * 300
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="断香炉开口",
        body=original_body,
        next_outline="赵管事带人清点祖祠。",
        event_plan={"next_focus": "赵管事带人清点祖祠。"},
        updated_story=story,
    )

    monkeypatch.setattr(
        "packages.story_core.orchestrator.apply_expression_patches_from_review",
        lambda body, review: (body.replace("昨晚", "前夜", 1), {"applied": True}),
    )
    monkeypatch.setattr(
        "packages.story_core.orchestrator._review_chapter_body",
        lambda *args, **kwargs: {"pass": True, "issues": [], "scores": {}, "adversarial_cut_review": {"pass": True}},
    )

    class TrackingOrchestrator(StoryOrchestrator):
        chat_called = False

        def _chat(self, story, prompt: str, *, max_tokens: int, json_mode: bool, agent: str = "director"):
            self.chat_called = True
            return original_body.replace("昨晚那句话是真的，今晚这句也是真的。", "门外传来脚步声。"), ""

    orchestrator = TrackingOrchestrator()
    orchestrator.revise_chapter_body(story, bundle, {"revision_plan": []}, ["章末加入赵管事清点祖祠。"])

    assert orchestrator.chat_called is True


def test_refresh_revised_metadata_replaces_generic_xianxia_title():
    story = StoryState(
        story_id="s-revised-title",
        outline="林照看守断香炉。",
        genre="xianxia",
        style="白描",
        characters=[CharacterState(name="林照", role="protagonist")],
    )
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="真相道韵",
        body="林照接下祖祠守炉差事，夜里听见残香开口提醒。" * 100,
        next_outline="有人来试门。",
        event_plan={"next_focus": "残香给出第一个反馈，有人夜里来试门。"},
        chapter_summary={"chapter_number": 1, "chapter_title": "真相道韵", "summary": "林照守炉。"},
        updated_story=story,
    )

    refreshed = StoryOrchestrator().refresh_revised_bundle_metadata(story, bundle)

    assert refreshed.chapter_title == "断香炉开口"
    assert refreshed.chapter_summary["chapter_title"] == "断香炉开口"


def test_refresh_revised_metadata_uses_final_body_after_long_outline_for_title():
    story = StoryState(
        story_id="s-revised-title-long-outline",
        outline="林照留在祖祠查旧账。" * 80,
        genre="xianxia",
        style="白描",
        characters=[CharacterState(name="林照", role="protagonist")],
    )
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="真相道韵",
        body=("林照守到后半夜，始终没有动静。" * 30) + "最后一缕残香忽然开口提醒他。",
        next_outline="有人来试门。",
        chapter_summary={"chapter_number": 1, "chapter_title": "真相道韵", "summary": "林照守炉。"},
        updated_story=story,
    )

    refreshed = StoryOrchestrator().refresh_revised_bundle_metadata(story, bundle)

    assert refreshed.chapter_title == "断香炉开口"


def test_choose_best_revision_rejects_severely_shorter_candidate_even_if_scores_tie():
    original = _quality(False, {"genre_rules": 6, "prose_style_meta_language": 6}, ["需要补写"])
    candidate = _quality(False, {"genre_rules": 6, "prose_style_meta_language": 6}, ["需要补写"])

    result = choose_best_revision(
        original_body="原稿正文" * 600,
        original_quality=original,
        candidate_body="短稿",
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["report"]["candidate_chars"] < result["report"]["original_chars"]


def test_choose_best_revision_rejects_chapter_rewrite_that_falls_below_minimum():
    original = _quality(False, {"genre_rules": 6, "prose_style_meta_language": 6}, ["需要补写"])
    candidate = _quality(True, {"genre_rules": 8, "prose_style_meta_language": 8})

    result = choose_best_revision(
        original_body="原稿正文" * 1200,
        original_quality=original,
        candidate_body="短稿正文" * 800,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["selected"] == "original"


def test_choose_best_revision_accepts_smoother_chapter_after_removing_repetition():
    original = _quality(False, {"reader_feel_patchwork": 5, "genre_rules": 8}, ["段落重复，正文有明显拼补感。"])
    candidate = _quality(True, {"reader_feel_patchwork": 8, "genre_rules": 8})

    result = choose_best_revision(
        original_body="原稿正文" * 1250,
        original_quality=original,
        candidate_body="顺畅正文" * 1050,
        candidate_quality=candidate,
    )

    assert result["accepted"] is True
    assert result["selected"] == "candidate"


def test_choose_best_revision_keeps_in_range_draft_when_failed_candidate_grows_out_of_range():
    original = _quality(False, {"genre_rules": 7, "prose_style_meta_language": 7}, ["缺少怪物面板"])
    candidate = _quality(False, {"genre_rules": 8, "prose_style_meta_language": 8}, ["对话仍不自然"])

    result = choose_best_revision(
        original_body="原" * 5211,
        original_quality=original,
        candidate_body="改" * 6197,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["selected"] == "original"
    assert result["report"]["reason"] == "candidate_above_chapter_maximum"


def test_choose_best_revision_rejects_failed_candidate_without_fewer_issues():
    original = _quality(False, {"genre_rules": 6, "prose_style_meta_language": 6}, ["问题一", "问题二"])
    candidate = _quality(False, {"genre_rules": 8, "prose_style_meta_language": 8}, ["新问题一", "新问题二"])

    result = choose_best_revision(
        original_body="原" * 5730,
        original_quality=original,
        candidate_body="改" * 5200,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["report"]["reason"] == "failed_candidate_did_not_reduce_issues"


def test_choose_best_revision_prefers_in_range_candidate_that_repairs_structural_length_error():
    original_issues = [f"原问题{i}" for i in range(6)]
    candidate_issues = [f"候选软问题{i}" for i in range(9)]
    original = _quality(False, {"genre_rules": 6}, original_issues)
    original["issues"] = ["body_too_short", *original_issues]
    original["has_hard_errors"] = True
    candidate = _quality(False, {"genre_rules": 6}, candidate_issues)
    candidate["has_hard_errors"] = False

    result = choose_best_revision(
        original_body="原" * 46,
        original_quality=original,
        candidate_body="改" * 4309,
        candidate_quality=candidate,
    )

    assert result["accepted"] is True
    assert result["selected"] == "candidate"
    assert result["report"]["reason"] == "structural_length_error_resolved"
    assert result["report"]["original_issue_count"] == 6
    assert result["report"]["candidate_issue_count"] == 9


def test_choose_best_revision_structural_length_preference_handles_overlong_original():
    original = _quality(False, {"genre_rules": 6}, ["原问题"])
    original["issues"] = ["body_too_long", "原问题"]
    original["has_hard_errors"] = True
    candidate = _quality(False, {"genre_rules": 6}, ["软问题一", "软问题二", "软问题三", "软问题四"])
    candidate["has_hard_errors"] = False

    result = choose_best_revision(
        original_body="原" * 6000,
        original_quality=original,
        candidate_body="改" * 5200,
        candidate_quality=candidate,
    )

    assert result["accepted"] is True
    assert result["report"]["reason"] == "structural_length_error_resolved"


def test_choose_best_revision_rejects_structural_repair_candidate_with_hard_errors():
    original = _quality(False, {"genre_rules": 6}, ["原问题"])
    original["issues"] = ["body_too_short", "原问题"]
    original["has_hard_errors"] = True
    candidate = _quality(False, {"genre_rules": 8}, ["设定冲突"])
    candidate["has_hard_errors"] = True

    result = choose_best_revision(
        original_body="原" * 46,
        original_quality=original,
        candidate_body="改" * 4309,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["report"]["reason"] != "structural_length_error_resolved"


def test_choose_best_revision_rejects_structural_repair_candidate_outside_preferred_range():
    original = _quality(False, {"genre_rules": 6}, ["原问题"])
    original["issues"] = ["body_too_short", "原问题"]
    original["has_hard_errors"] = True
    candidate = _quality(False, {"genre_rules": 8}, [])
    candidate["has_hard_errors"] = False

    below = choose_best_revision(
        original_body="原" * 46,
        original_quality=original,
        candidate_body="改" * 4199,
        candidate_quality=candidate,
    )
    above = choose_best_revision(
        original_body="原" * 5600,
        original_quality=original,
        candidate_body="改" * 5501,
        candidate_quality=candidate,
    )

    assert below["accepted"] is False
    assert above["accepted"] is False


def test_choose_best_revision_rejects_structural_repair_when_soft_issues_increase_by_four():
    original_issues = [f"原问题{i}" for i in range(6)]
    candidate_issues = [f"候选软问题{i}" for i in range(10)]
    original = _quality(False, {"genre_rules": 6}, original_issues)
    original["issues"] = ["body_too_short", *original_issues]
    original["has_hard_errors"] = True
    candidate = _quality(False, {"genre_rules": 8}, candidate_issues)
    candidate["has_hard_errors"] = False

    result = choose_best_revision(
        original_body="原" * 46,
        original_quality=original,
        candidate_body="改" * 4309,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["report"]["reason"] == "failed_candidate_did_not_reduce_issues"


def test_choose_best_revision_does_not_apply_structural_preference_to_in_range_original():
    original = _quality(False, {"genre_rules": 8}, ["原问题"])
    original["has_hard_errors"] = False
    candidate = _quality(False, {"genre_rules": 2}, ["软问题一", "软问题二", "软问题三", "软问题四"])
    candidate["has_hard_errors"] = False

    result = choose_best_revision(
        original_body="原" * 5000,
        original_quality=original,
        candidate_body="改" * 5000,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["report"]["reason"] != "structural_length_error_resolved"


def test_choose_best_revision_rejects_severe_quality_regression_even_when_hard_errors_resolve():
    original = _quality(False, {"genre_rules": 10}, ["设定冲突"])
    original["has_hard_errors"] = True
    candidate = _quality(False, {"genre_rules": -10}, [f"软问题{i}" for i in range(20)])
    candidate["has_hard_errors"] = False

    result = choose_best_revision(
        original_body="原" * 5000,
        original_quality=original,
        candidate_body="改" * 5000,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["selected"] == "original"
    assert result["report"]["candidate_issue_count"] == 20
    assert result["report"]["candidate_score"] < result["report"]["original_score"] - 15


def test_choose_best_revision_accepts_bounded_soft_regression_when_hard_errors_resolve():
    original = _quality(False, {"genre_rules": 6}, ["设定冲突"])
    original["has_hard_errors"] = True
    candidate = _quality(False, {"genre_rules": 7}, ["对话问题", "AI味", "节奏问题"])
    candidate["has_hard_errors"] = False

    result = choose_best_revision(
        original_body="原" * 5000,
        original_quality=original,
        candidate_body="改" * 5000,
        candidate_quality=candidate,
    )

    assert result["accepted"] is True
    assert result["selected"] == "candidate"
    assert result["report"]["reason"] == "hard_errors_resolved"
    assert result["report"]["candidate_issue_count"] == result["report"]["original_issue_count"] + 2
    assert result["report"]["candidate_score"] >= result["report"]["original_score"] - 15


def test_choose_best_revision_rejects_candidate_above_absolute_maximum():
    original = _quality(False, {"genre_rules": 6}, ["设定冲突"])
    original["has_hard_errors"] = True
    candidate = _quality(True, {"genre_rules": 10})
    candidate["has_hard_errors"] = False

    result = choose_best_revision(
        original_body="原" * 6000,
        original_quality=original,
        candidate_body="改" * 10000,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["selected"] == "original"
    assert result["report"]["reason"] == "candidate_above_chapter_maximum"


def test_choose_best_revision_rejects_too_short_candidate_even_when_hard_errors_resolve():
    original = _quality(False, {"genre_rules": 6}, ["设定冲突"])
    original["has_hard_errors"] = True
    candidate = _quality(True, {"genre_rules": 8})
    candidate["has_hard_errors"] = False

    result = choose_best_revision(
        original_body="原" * 5000,
        original_quality=original,
        candidate_body="改" * 3800,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["selected"] == "original"
    assert result["report"]["reason"] == "candidate_below_chapter_minimum"


def test_choose_best_revision_does_not_prioritize_candidate_with_hard_errors_remaining():
    original = _quality(False, {"genre_rules": 8}, ["设定冲突"])
    original["has_hard_errors"] = True
    candidate = _quality(False, {"genre_rules": 5}, ["另一处设定冲突"])
    candidate["has_hard_errors"] = True

    result = choose_best_revision(
        original_body="原" * 5000,
        original_quality=original,
        candidate_body="改" * 5000,
        candidate_quality=candidate,
    )

    assert result["accepted"] is False
    assert result["report"]["reason"] != "hard_errors_resolved"


def test_choose_best_segment_revision_rejects_worse_local_rewrite():
    original_review = {"pass": False, "issues": ["偏短"], "scores": {"segment_scope": 8, "segment_surface": 5, "segment_style": 8}}
    candidate_review = {
        "pass": False,
        "issues": ["偏短", "提前写交易行"],
        "scores": {"segment_scope": 5, "segment_surface": 5, "segment_style": 5},
    }

    result = choose_best_segment_revision(
        original_text="原段正文" * 120,
        original_review=original_review,
        candidate_text="更差的段落",
        candidate_review=candidate_review,
    )

    assert result["accepted"] is False
    assert result["selected"] == "original"
    assert result["text"] == "原段正文" * 120
    assert result["review"] is original_review
    assert result["report"]["reason"] == "candidate_worse_than_original"


def test_choose_best_segment_revision_accepts_better_local_rewrite():
    original_review = {"pass": False, "issues": ["偏短"], "scores": {"segment_scope": 8, "segment_surface": 5, "segment_style": 8}}
    candidate_review = {"pass": True, "issues": [], "scores": {"segment_scope": 8, "segment_surface": 8, "segment_style": 8}}

    result = choose_best_segment_revision(
        original_text="原段正文",
        original_review=original_review,
        candidate_text="更好的段落",
        candidate_review=candidate_review,
    )

    assert result["accepted"] is True
    assert result["selected"] == "candidate"
    assert result["text"] == "更好的段落"
    assert result["review"] is candidate_review


class _BadSegmentRevisionOrchestrator(StoryOrchestrator):
    def __init__(self):
        self.calls = 0

    def _chat(self, story, prompt: str, *, max_tokens: int, json_mode: bool, agent: str = "director"):
        self.calls += 1
        if self.calls == 1:
            return "夜烬站在村口，反复检查背包和任务栏。他没有急着往前走，只把上一章留下的问题重新过了一遍。" * 80, ""
        return "爽点已经兑现。", ""


def test_segment_pipeline_keeps_original_segment_when_local_revision_is_worse():
    story = StoryState(story_id="s-segment-safety", outline="网游开服。", genre="网游", style="升级流")
    orchestrator = _BadSegmentRevisionOrchestrator()

    body, error, reviews = orchestrator._write_chapter_in_segments(
        story,
        2,
        {"governance": {"chapter_intent": {"must_avoid": []}, "rule_stack": {"hard_facts": [], "diagnostic_only": []}}},
    )

    assert error == ""
    assert body.split("\n\n")[0].startswith("夜烬站在村口")
    assert reviews[0]["segment_revision_safety"]["accepted"] is False
    assert reviews[0]["segment_revision_safety"]["selected"] == "original"


class _GoodSegmentRevisionOrchestrator(StoryOrchestrator):
    def __init__(self):
        self.calls = 0

    def _chat(self, story, prompt: str, *, max_tokens: int, json_mode: bool, agent: str = "director"):
        self.calls += 1
        if self.calls == 1:
            return "短段", ""
        return "".join(
            [
                "夜烬把任务栏重新拉开，上一章留下的材料还在背包里。他先看等级，再看经验，最后看法力值。",
                "村口的木牌旁挤着十几个玩家，清道夫委托挂在最下面，奖励和要求写得很清楚。",
                "他没有急着接，只把新手法杖转到掌心，确认耐久足够支撑下一轮战斗。",
                "排在前面的剑士交齐材料，柜台后的登记员盖了章，又把一张后坡路线图递过去。",
                "夜烬这才明白，委托给的经验只是明面奖励，真正有用的是后面的前置任务。",
                "短发玩家回头问他是不是也差毒腺，他说自己还要核对背包，免得交错任务材料。",
                "对方提醒他后坡的狼更密，法师一个人过去容易被两只怪同时贴住。",
                "夜烬顺着他指的方向看了一眼，把坡口的石头、木栅栏和退路记了下来。",
                "轮到他时，登记员先核对等级，又问他是否完成村口的清理记录。",
                "他把材料递过去，没有多说来源，只问完成以后能不能登记后坡探路。",
                "登记员收走规定数量，把剩下的退回去，告诉他路线图要等任务结算后才能领取。",
                "铜币和经验到账，夜烬升了一级，法力上限也跟着增加，但背包里的多余材料还在。",
                "他让开柜台，先去修理铺补好新手法杖，又买了一瓶最便宜的回蓝药。",
                "修理匠收钱时随口说后坡今天死了不少新人，让他别仗着刚升级就往里面冲。",
                "夜烬答应了一声，把药水放到顺手的位置，随后沿村墙走向后坡入口。",
            ]
        ), ""


def test_segment_pipeline_accepts_better_local_revision():
    story = StoryState(story_id="s-segment-safety-good", outline="网游开服。", genre="网游", style="升级流")
    orchestrator = _GoodSegmentRevisionOrchestrator()

    body, error, reviews = orchestrator._write_chapter_in_segments(
        story,
        2,
        {"governance": {"chapter_intent": {"must_avoid": []}, "rule_stack": {"hard_facts": [], "diagnostic_only": []}}},
    )

    assert error == ""
    assert body.split("\n\n")[0].startswith("夜烬把任务栏重新拉开")
    assert reviews[0]["segment_revision_safety"]["accepted"] is True
    assert reviews[0]["segment_revision_safety"]["selected"] == "candidate"


def test_segment_pipeline_does_not_model_revise_soft_only_issues(monkeypatch):
    monkeypatch.setattr(
        "packages.story_core.orchestrator.build_segment_specs",
        lambda chapter_number, plan: [
            SegmentSpec(
                key="soft",
                title="软问题片段",
                goal="完成当前动作",
                required_surface="夜烬",
                target_chars=120,
            )
        ],
    )
    monkeypatch.setattr(
        "packages.story_core.orchestrator.review_segment_output",
        lambda spec, text, *, chapter_number: {
            "pass": False,
            "issues": ["AI味偏重：同章多次使用解释句。"],
            "revision_plan": ["后续整章统一处理语气。"],
            "scores": {"segment_scope": 8, "segment_surface": 8, "segment_style": 5},
            "critical_review": {"hard_issues": [], "soft_issues": ["AI味偏重"], "severity_summary": {"has_hard_violation": False}},
            "segment_key": spec.key,
            "segment_title": spec.title,
        },
    )

    class SoftOnlyOrchestrator(StoryOrchestrator):
        def __init__(self):
            self.calls = 0

        def _chat(self, story, prompt: str, *, max_tokens: int, json_mode: bool, agent: str = "director"):
            self.calls += 1
            return "夜烬站在柜台前，先把背包打开，又把任务牌看了一遍。", ""

    story = StoryState(story_id="s-soft-only", outline="网游开服。", genre="网游", style="升级流")
    orchestrator = SoftOnlyOrchestrator()

    body, error, reviews = orchestrator._write_chapter_in_segments(story, 1, {})

    assert error == ""
    assert body.startswith("夜烬站在柜台前")
    assert orchestrator.calls == 1
    assert "segment_revision_safety" not in reviews[0]
