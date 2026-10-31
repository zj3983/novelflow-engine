"""Compare Issue #46 pytest/JUnit fixture decisions without model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def summarize(path: Path) -> dict:
    rows = []
    for test in ET.parse(path).iter("testcase"):
        if not test.get("name", "").startswith("test_model_findings_require_established_evidence["):
            continue
        fields = {p.attrib["name"]: p.attrib.get("value", "") for p in test.findall("properties/property")}
        if not {"evidence_origin", "expected_blocking", "decision_blocking"} <= fields.keys():
            raise ValueError(f"Missing decision properties in {test.get('name')}")
        expected, actual = fields["expected_blocking"] == "True", fields["decision_blocking"] == "True"
        rows.append({"case": test.get("name"), **fields, "correct": expected == actual})
    if not rows:
        raise ValueError("No Issue #46 fixture decisions in JUnit report")
    untrusted = [r for r in rows if r["evidence_origin"] not in {"confirmed_snapshot", "author_requirement"}]
    return {
        "cases": len(rows),
        "correct_decisions": sum(r["correct"] for r in rows),
        "decision_accuracy": sum(r["correct"] for r in rows) / len(rows),
        "untrusted_evidence_cases": len(untrusted),
        "untrusted_evidence_blocked": sum(r["decision_blocking"] == "True" for r in untrusted),
        "future_evidence_blocked": sum(r["decision_blocking"] == "True" for r in rows if r["evidence_origin"] == "future_state"),
        "rows": rows,
    }


def compare(before: Path, after: Path) -> dict:
    previous, current = summarize(before), summarize(after)
    if {(r["case"], r["expected_blocking"]) for r in previous["rows"]} != {
        (r["case"], r["expected_blocking"]) for r in current["rows"]
    }:
        raise ValueError("Before and after reports must contain the same labeled fixtures")
    old_errors = previous["untrusted_evidence_blocked"]
    return {"scope": "deterministic synthetic boundary fixtures; not real-model quality",
            "before": previous, "after": current,
            "untrusted_blocking_reduction": (old_errors - current["untrusted_evidence_blocked"]) / old_errors if old_errors else None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = compare(args.before, args.after)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"before": {k: v for k, v in report["before"].items() if k != "rows"},
                      "after": {k: v for k, v in report["after"].items() if k != "rows"},
                      "untrusted_blocking_reduction": report["untrusted_blocking_reduction"]}, ensure_ascii=False))
