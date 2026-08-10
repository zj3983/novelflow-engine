from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from scripts.smoke_production_pipeline import SmokeReport, _assert_acceptance


def test_smoke_script_can_run_directly() -> None:
    root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [sys.executable, "scripts/smoke_production_pipeline.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def _valid_report(**updates) -> SmokeReport:
    payload = {
        "project": Path("project"),
        "chapter_number": 1,
        "source_hash_before": "same",
        "source_hash_after": "same",
        "director_artifact": {
            "chapter_title": "第一章",
            "primary_conflict": "进入村子",
            "scene_chain": [
                {"location": "村口", "action": "进入", "change": "落脚"},
                {"location": "村内", "action": "观察", "change": "发现线索"},
            ],
        },
        "writer_prompt": "目标4200至5500字；低于3800字；超过5700字",
        "body_chars": 4800,
        "quality_report": {"ok": True},
    }
    payload.update(updates)
    return SmokeReport(**payload)


def test_smoke_rejects_malformed_inventory_keys() -> None:
    report = _valid_report(
        writer_context_cards=[
            {
                "name": "苏叶",
                "current": {
                    "game_state": {
                        "inventory": {
                            "里静静堆叠着【灰狼毒腺": 7,
                            "】与【粗糙狼皮": 7,
                        }
                    }
                },
            }
        ],
    )

    failures = _assert_acceptance(report)

    assert any(
        failure.startswith("writer_context_malformed_inventory")
        for failure in failures
    )


def test_smoke_rejects_failed_quality_and_out_of_range_body() -> None:
    report = _valid_report(
        body_chars=5800,
        quality_report={"ok": False},
        blocking_codes=["chapter.length_too_long"],
    )

    failures = _assert_acceptance(report)

    assert "quality_report_failed" in failures
    assert "body_chars_out_of_range:5800" in failures
    assert "blocking_findings:chapter.length_too_long" in failures
