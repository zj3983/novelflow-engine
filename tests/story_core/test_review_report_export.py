"""Tests for the env-gated automatic review-report exporter."""
import os
from pathlib import Path
from unittest.mock import patch

from packages.story_core.orchestrator import (
    _persist_review_report,
    _review_reports_enabled,
    _review_report_output_dir,
)


def _writing_review_fixture():
    return {
        "pass": False,
        "issues": ["主角全章没有可识别的开口对话"],
        "revision_plan": ["补一次主角主动开口"],
        "scores": {"webnovel_hook": 8},
        "genre_profile_id": "game_webnovel",
        "critical_review": {
            "pass": False,
            "hard_issues": ["主角全章没有可识别的开口对话"],
            "soft_issues": [],
            "issues": ["主角全章没有可识别的开口对话"],
            "revision_plan": [],
            "requires_revision": True,
            "severity_summary": {
                "has_hard_violation": True,
                "soft_violation_count": 0,
                "soft_threshold": 3,
            },
        },
        "hook_review": {"scores": {}, "issues": [], "hook_meta": None},
        "pacing_review": {"scores": {}, "issues": [], "diagnostics": {}},
        "beats_review": {"scores": {}, "issues": [], "diagnostics": {}},
    }


# ---------------------------------------------------------------------------
# Env flag plumbing
# ---------------------------------------------------------------------------


def test_reports_disabled_by_default():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVEL_AUTOGROWTH_REVIEW_REPORTS", None)
        assert _review_reports_enabled() is False


def test_reports_enabled_via_truthy_env():
    for value in ("1", "true", "TRUE", "Yes", "on"):
        with patch.dict(os.environ, {"NOVEL_AUTOGROWTH_REVIEW_REPORTS": value}, clear=False):
            assert _review_reports_enabled() is True, f"failed for value={value!r}"


def test_reports_disabled_for_falsy_env():
    for value in ("0", "false", "no", "off", ""):
        with patch.dict(os.environ, {"NOVEL_AUTOGROWTH_REVIEW_REPORTS": value}, clear=False):
            assert _review_reports_enabled() is False, f"failed for value={value!r}"


def test_output_dir_uses_override_when_set(tmp_path):
    with patch.dict(os.environ, {"NOVEL_AUTOGROWTH_REVIEW_REPORTS_DIR": str(tmp_path)}, clear=False):
        assert _review_report_output_dir() == tmp_path


def test_output_dir_defaults_to_chapter_exports():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVEL_AUTOGROWTH_REVIEW_REPORTS_DIR", None)
        assert _review_report_output_dir() == Path("chapter_exports")


# ---------------------------------------------------------------------------
# _persist_review_report
# ---------------------------------------------------------------------------


def test_persist_returns_none_when_disabled():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NOVEL_AUTOGROWTH_REVIEW_REPORTS", None)
        result = _persist_review_report(1, "正文。", _writing_review_fixture())
    assert result is None


def test_persist_writes_markdown_when_enabled(tmp_path):
    body = "他走进村口。" * 30
    review = _writing_review_fixture()
    env = {
        "NOVEL_AUTOGROWTH_REVIEW_REPORTS": "1",
        "NOVEL_AUTOGROWTH_REVIEW_REPORTS_DIR": str(tmp_path),
    }
    with patch.dict(os.environ, env, clear=False):
        out_path = _persist_review_report(7, body, review)

    assert out_path is not None
    assert out_path.exists()
    assert out_path.name == "review_ch0007.md"
    content = out_path.read_text(encoding="utf-8")
    # Header must reflect the chapter number we passed in
    assert "# 第 7 章 审稿报告" in content
    # HARD violation surfaces in the markdown
    assert "主角全章没有可识别的开口对话" in content


def test_persist_creates_output_dir(tmp_path):
    nested = tmp_path / "nested" / "reviews"
    env = {
        "NOVEL_AUTOGROWTH_REVIEW_REPORTS": "1",
        "NOVEL_AUTOGROWTH_REVIEW_REPORTS_DIR": str(nested),
    }
    with patch.dict(os.environ, env, clear=False):
        out_path = _persist_review_report(1, "短文。", _writing_review_fixture())
    assert out_path is not None
    assert nested.exists()
    assert (nested / "review_ch0001.md").exists()


def test_persist_swallows_exceptions(tmp_path):
    """A formatter explosion must NOT crash chapter finalization."""
    env = {
        "NOVEL_AUTOGROWTH_REVIEW_REPORTS": "1",
        "NOVEL_AUTOGROWTH_REVIEW_REPORTS_DIR": str(tmp_path),
    }
    with patch.dict(os.environ, env, clear=False), patch(
        "packages.story_core.orchestrator.format_review_report",
        side_effect=RuntimeError("boom"),
    ):
        result = _persist_review_report(1, "正文。", _writing_review_fixture())
    assert result is None
    # And no file leaked out
    assert not list(tmp_path.glob("review_ch*.md"))


def test_persist_chapter_number_padded_to_four_digits(tmp_path):
    env = {
        "NOVEL_AUTOGROWTH_REVIEW_REPORTS": "1",
        "NOVEL_AUTOGROWTH_REVIEW_REPORTS_DIR": str(tmp_path),
    }
    with patch.dict(os.environ, env, clear=False):
        out_path = _persist_review_report(123, "正文。", _writing_review_fixture())
    assert out_path is not None
    assert out_path.name == "review_ch0123.md"
