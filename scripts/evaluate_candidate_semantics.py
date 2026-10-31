"""Run a bounded synthetic semantic check with the existing Antigravity CLI."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace

from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.antigravity_cli_provider import post_json_via_antigravity_cli
from packages.story_core.candidate_semantics import review_candidate_semantics
from packages.story_core.continuity.delta import ContinuityDelta
from packages.story_core.http_retry import RetryConfig


def prepare(cases):
    changes = defaultdict(list)
    expected, entities = {}, []
    for row in cases:
        field = row["kind"]
        change = {"chapter_number": 1, "source_sentence": row["body"], **row["change"]}
        if field in {"inventory_changes", "location_movements", "entity_updates"}:
            change["entity_id"] = f"char-{row['id']}"
            actor = re.search(r"甲[一二三四五六七八九十]+", row["body"])
            entities.append({"entity_id": change["entity_id"], "kind": "character", "name": actor.group()})
        change_id = f"{field}:{len(changes[field])}"
        expected[change_id] = row
        changes[field].append(change)
    return "\n".join(f"【独立片段{row['id']}】{row['body']}" for row in cases), ContinuityDelta(chapter_number=1, **changes), expected, entities


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[1] / "tests/fixtures/issue48-semantic-cases.json")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--run", action="store_true", help="One real CLI call; otherwise only validate the fixture dataset")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    body, delta, expected, entities = prepare(cases)
    args.out.mkdir(parents=True, exist_ok=True)
    if not args.run:
        print(json.dumps({"cases": len(cases), "proposals": len(expected), "model_calls": 0}))
        return
    config = json.loads(args.config.read_text(encoding="utf-8"))
    binding = config["stages"]["writer"]
    if binding["provider_id"] != "antigravity":
        raise ValueError("This audit retains the existing Antigravity CLI; no API/provider switching")
    command = config["accounts"]["antigravity"]["codex_command"]
    model = binding["model"]

    class Runtime:
        calls = 0

        def complete(self, request):
            self.calls += 1
            if self.calls > 1:
                raise ValueError("Synthetic audit is limited to one model request")
            (args.out / "synthetic-request.txt").write_text(request.prompt, encoding="utf-8")
            response = post_json_via_antigravity_cli({"model": model, "messages": [{"role": "user", "content": request.prompt}],
                "response_format": {"type": "json_object"}}, command=command, config=RetryConfig(timeout=180, max_retries=1))
            text = response["choices"][0]["message"]["content"]
            (args.out / "synthetic-response.txt").write_text(text, encoding="utf-8")
            return SimpleNamespace(ok=True, text=text)

    runtime = Runtime()
    previous = os.environ.get("NOVEL_ANTIGRAVITY_RUNTIME_DIR")
    os.environ["NOVEL_ANTIGRAVITY_RUNTIME_DIR"] = str(args.out / "cli-runtime")
    try:
        _, report = review_candidate_semantics(body=body, chapter_number=1, delta=delta,
            director=DirectorArtifact(chapter_number=1, chapter_title="语义边界合成评测",
                chapter_goal="编号片段彼此独立，时间与人物状态互不关联；只核对每项自己的引文，不跨片段借用事实。",
                opening_state="独立合成片段，不是正式小说", ending_state="只核验实际变化", scene_beats=[]),
            snapshot={"schema_version": "canon-review-snapshot/v1", "as_of_chapter": 0,
                "bounded_state_available": True, "entities": entities, "facts": []}, runtime=runtime)
    finally:
        if previous is None:
            os.environ.pop("NOVEL_ANTIGRAVITY_RUNTIME_DIR", None)
        else:
            os.environ["NOVEL_ANTIGRAVITY_RUNTIME_DIR"] = previous
    results = []
    for decision in report["decisions"]:
        case = expected[decision["change_id"]]
        correct = decision["verdict"] == ("supported" if case["supported"] else "unsupported")
        results.append({"case_id": case["id"], "category": case["category"], "expected_supported": case["supported"],
                        **decision, "correct": correct})
    summary = {"scope": "synthetic agent-labeled cases; not independent human or production evaluation",
        "provider": "antigravity", "model": model, "model_calls": runtime.calls, "cases": len(cases),
        "correct": sum(r["correct"] for r in results),
        "accuracy": sum(r["correct"] for r in results) / len(results),
        "false_state_acceptances": sum(not r["expected_supported"] and r["verdict"] == "supported" for r in results),
        "uncertain": sum(r["verdict"] == "uncertain" for r in results), "results": results}
    (args.out / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
