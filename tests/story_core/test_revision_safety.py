from packages.story_core.revision_safety import choose_best_revision, choose_best_segment_revision, score_quality_report
from packages.story_core.orchestrator import StoryOrchestrator
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
        return (
            "夜烬把任务栏重新拉开，上一章留下的材料还在背包里。他先看等级，再看经验，最后看法力值。"
            "村口的木牌被风吹得轻轻晃动，清道夫委托挂在最下面一行，奖励和要求写得很清楚。"
            "他没有急着接，只把新手法杖转到掌心，确认耐久没有继续掉。"
        ) * 20, ""


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
