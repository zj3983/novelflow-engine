from types import SimpleNamespace
import json

from packages.story_core.contextual_prose_review import review_contextual_prose, build_contextual_prose_prompt, apply_contextual_review, run_chapter_context_review
from packages.story_core.review.prose_checks import run_prose_checks
from packages.story_core.review.prose_checks import with_prose_annotation_evidence


class Gateway:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def complete_stage(self, stage, request):
        self.requests.append(request)
        return SimpleNamespace(ok=True, text=json.dumps(self.payload, ensure_ascii=False))


def test_contextual_prompt_protects_technical_terms_and_recorded_readings():
    prompt = build_contextual_prose_prompt("他核对基准和数据。", {"character_cards": [{"name": "维修师", "speech_style": "简洁报数"}]})
    assert "严禁按禁词表判错" in prompt
    assert "表格记录" in prompt
    assert "简洁报数" in prompt


def test_contextual_review_requires_literal_sentence_and_context_reason():
    body = "他没有按下开关，只把工具箱推回了墙边。"
    gateway = Gateway({"summary": "一处重复解说", "issues": [{"category": "prose", "title": "重复解释动作",
        "quote": body, "context_reason": "前文已经用动作说明他停止抢修，这里再次重复同一判断，延缓了后续的回应。", "suggestion": "删除重复判断，直接接门人的反应。"}]})
    report = review_contextual_prose(body, {"chapter_number": 3}, model_gateway=gateway)
    assert report["status"] == "completed"
    assert report["issues"][0]["evidence"] == body
    assert report["annotations"][0]["quotes"] == [body]
    assert report["issues"][0]["blocking"] is False


def test_isolated_word_or_invented_quote_is_not_a_successful_review():
    gateway = Gateway({"issues": [{"category": "ai_flavor", "quote": "基准", "context_reason": "这个词听起来非常像人工智能的术语。", "suggestion": "删掉"}]})
    report = review_contextual_prose("他记下当前压力作为检修基准。", {}, model_gateway=gateway)
    assert report["status"] == "partial"
    assert report["pass"] is False
    assert report["issues"] == []


def test_word_rules_are_only_signals_and_model_context_decides_findings():
    checks = run_prose_checks("此刻他核对数据并记录基准。")
    assert checks["prose_style_review"]["issues"] == []
    assert checks["prose_style_review"]["rule_signals"]
    report = apply_contextual_review({**checks, "writing_review": {"pass": True}}, {"executed": True, "status": "completed", "issues": [], "annotations": []})
    assert report["simplified_review"]["total_issues"] == 0
    assert report["simplified_review"]["diagnostics"]["contextual_prose_review_executed"] is True


def test_manual_context_review_only_saves_review_metadata(tmp_path):
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    path = chapter_dir / "0001.json"
    body = "他核对数据，确认当前压力就是检修基准。"
    path.write_text(json.dumps({"body": body, "quality_report": {}, "other": "保留"}), encoding="utf-8")
    def read_json(target):
        return json.loads(target.read_text(encoding="utf-8"))
    def replace(payloads):
        for target, payload in payloads.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload), encoding="utf-8")
    store = SimpleNamespace(root=tmp_path, story_system_dir=tmp_path, candidate_store=None,
                            chapter=lambda number: read_json(path), project=lambda: {"title": "维修故事"},
                            prompt_call_log=lambda: None, _read_json=read_json, _replace_json_transaction=replace)
    result = run_chapter_context_review(store, 1, model_gateway=Gateway({"summary": "专业术语符合维修场景", "issues": []}))
    assert result["contextual_review"]["status"] == "completed"
    assert read_json(path)["body"] == body
    assert read_json(path)["other"] == "保留"
    assert read_json(path)["quality_report"]["contextual_prose_review"]["issues"] == []


def test_context_review_for_an_old_body_is_not_displayed_as_current():
    quality = {"contextual_prose_review": {"executed": True, "status": "completed", "body_sha256": "old", "issues": []}}
    projected = with_prose_annotation_evidence("已经修改过的新正文。", quality)
    assert "contextual_prose_review" not in projected
    assert "contextual_prose_review" in quality
