"""Print an apply_patch plan for the confirmed chapter-64 template contamination.

Read-only: never writes project data. Restricts edits to the known project and
derived metadata. Logs, candidates, prose and audit commits remain unchanged.
"""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "data/exported-projects/p-1d6d3e51819b4b6d909a7a4929caef4e"
NAME = "药剂师洛婶"


def clean(value, key=""):
    if isinstance(value, dict):
        return {k: clean(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [
            clean(item)
            for item in value
            if not (
                key in {"characters", "character_profiles"}
                and (item == NAME or isinstance(item, dict) and item.get("name") == NAME)
            )
        ]
    return value


def main():
    project = json.loads((PROJECT / ".webnovel/project.json").read_text(encoding="utf-8"))
    assert project["title"] == "网游：全服只有我能给NPC发任务"
    paths = [PROJECT / ".webnovel" / f"{name}.json" for name in ("project", "state")]
    paths += [PROJECT / ".story-system" / folder / f"{n:04d}.json"
              for folder in ("chapters", "continuity/snapshots") for n in range(64, 72)]
    patch = ["*** Begin Patch\n"]
    changes = []
    for path in paths:
        raw = path.read_bytes()
        old = raw.decode("utf-8").replace("\r\n", "\n")
        original = json.loads(old)
        repaired = clean(original)
        if original == repaired:
            continue
        assert NAME not in json.dumps(repaired, ensure_ascii=False), path
        # Preserve the existing pretty-print convention.
        new = json.dumps(repaired, ensure_ascii=False, indent=2) + ("\n" if old.endswith("\n") else "")
        delta = list(difflib.unified_diff(old.splitlines(True), new.splitlines(True), n=3))[2:]
        patch.append(f"*** Update File: {path.as_posix()}\n")
        for line in delta:
            patch.append("@@\n" if line.startswith("@@") else line.rstrip("\n") + "\n")
        changes.append({"path": path.relative_to(PROJECT).as_posix(), "sha256_before": hashlib.sha256(raw).hexdigest()})
    patch.append("*** End Patch\n")
    prose = {p.relative_to(PROJECT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (PROJECT / "chapters").glob("*.md")}
    print(json.dumps({"patch": "".join(patch), "changes": changes, "prose_sha256": prose}, ensure_ascii=False))


if __name__ == "__main__":
    main()
