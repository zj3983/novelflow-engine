# -*- coding: utf-8 -*-
"""薄 CLI：把 大纲/*.md 同步为工作台读取的 .webnovel/outline.json（project-outline/v1）。

解析/渲染逻辑都在 packages/story_core/outline_markdown_sync.py，
本脚本只负责参数处理与调用。工作台运行期间读写 outline.json 时会自动做
双向同步（见 FileProjectStore.project_outline / update_project_outline），
一般不再需要手动跑本脚本。

用法：
    python sync_outline_to_workbench.py [--project 项目目录]   # md → json
    python sync_outline_to_workbench.py --export               # json → md
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from packages.story_core.elastic_outline import validate_outline_for_project  # noqa: E402
from packages.story_core.outline_markdown_sync import (  # noqa: E402
    _write_json_atomic,
    export_outline_to_markdown,
    import_markdown_outline,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="大纲 md 与工作台 outline.json 双向同步")
    parser.add_argument(
        "--project",
        default=str(ROOT / "data" / "exported-projects" / "p-gou-webgame-restored"),
        help="项目目录（默认：工作台项目 p-gou-webgame-restored）",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="反向：把 outline.json 字段级合并渲染回 大纲/*.md",
    )
    args = parser.parse_args()
    project = Path(args.project)
    json_path = project / ".webnovel" / "outline.json"

    if args.export:
        if not json_path.exists():
            sys.exit(f"outline.json 不存在: {json_path}")
        outline = json.loads(json_path.read_text(encoding="utf-8"))
        result = export_outline_to_markdown(project, outline)
        print(f"已导出 outline.json → 大纲/*.md（{result}）")
        return

    outline = import_markdown_outline(project)
    if outline is None:
        sys.exit("Markdown 大纲解析失败或关键内容缺失，未改动 outline.json")

    state = json.loads((project / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    current_chapter = int(state.get("current_chapter") or 0)
    normalized = validate_outline_for_project(outline, current_chapter=current_chapter)

    if json_path.exists():
        backup = project / ".webnovel" / "backups" / "outline.backup_before_sync.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_path, backup)
        print(f"已备份旧文件到 {backup}")
    _write_json_atomic(json_path, normalized)
    print(f"已写入 {json_path}")
    chapters = normalized["chapters"]
    if chapters:
        print(
            f"章节大纲条数: {len(chapters)}"
            f"（{chapters[0]['chapter_number']}-{chapters[-1]['chapter_number']}）"
        )
    print(f"阶段大纲条数: {len(normalized['arcs'])}")
    print("校验通过: validate_outline_for_project OK")


if __name__ == "__main__":
    main()
