from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.review.contracts import ReviewFinding, ReviewResult
from packages.story_core.review.prose_checks import with_prose_annotation_evidence


def test_style_annotations_include_every_match_not_only_message_examples():
    lines = [f"“铜牌{index}，背包满，先停手。”" for index in range(9)]
    body = "此刻查看数据、异常和基准。\n\n" + "\n\n".join(lines)
    review = review_prose_style(body)
    assert {item["message"] for item in review["annotations"]} == set(review["issues"])
    quotes = {quote for item in review["annotations"] for quote in item["quotes"]}
    assert {"此刻", "基准"} <= quotes
    assert all(any(f"铜牌{index}" in quote for quote in quotes) for index in range(9))
    assert all(quote in body for quote in quotes)


def test_ai_annotations_only_describe_raised_issues_and_preserve_full_formula_quotes():
    body = "不是胆怯，而是谨慎。他推开门。不是退让，而是等待。他握住刀。"
    review = review_ai_flavor(body)
    assert {item["message"] for item in review["annotations"]} == set(review["issues"])
    assert set(review["hits"]["formula"]) <= {quote for item in review["annotations"] for quote in item["quotes"]}
    assert review_ai_flavor("他记下基准，关上门。")["annotations"] == []


def test_full_findings_survive_summary_issue_limit():
    result = ReviewResult.from_findings([
        ReviewFinding(code=f"prose.{index}", category="prose", blocking=False,
                      message=f"问题{index}", suggestion="复核", source="style", evidence=f"原句{index}")
        for index in range(8)
    ]).to_dict()
    assert len(result["issues"]) == 3
    assert len(result["findings"]) == 8


def test_historical_annotation_backfill_is_read_only_and_does_not_add_new_issues():
    quality = {"ok": True, "prose_style_review": {"issues": ["AI高频套话进入正文：此刻。"]}}
    enriched = with_prose_annotation_evidence("此刻他记下基准。", quality)
    assert "annotations" not in quality["prose_style_review"]
    assert enriched["ok"] is True
    assert enriched["prose_style_review"]["issues"] == []
    assert enriched["prose_style_review"]["rule_signals"][0]["message"] == quality["prose_style_review"]["issues"][0]
