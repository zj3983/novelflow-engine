from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from packages.story_core.title_strategy import normalize_title_text


def _write_json_atomic(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def scan_duplicate_chapter_titles(project_root: Path | str) -> dict[str, list[int]]:
    """Scan the project rolling and master outline for duplicate chapter titles."""
    root = Path(project_root)
    titles_by_norm: dict[str, list[tuple[int, str]]] = defaultdict(list)
    seen_numbers: set[int] = set()

    # 1. Read rolling outline
    rolling_path = root / ".story-system" / "outline-generation" / "rolling_outline.json"
    if rolling_path.is_file():
        try:
            rolling = json.loads(rolling_path.read_text(encoding="utf-8"))
            for chapter in rolling.get("chapters", []):
                if not isinstance(chapter, dict):
                    continue
                num = chapter.get("chapter_number")
                title = str(chapter.get("title") or chapter.get("chapter_title") or "").strip()
                if isinstance(num, int) and not isinstance(num, bool) and title and num not in seen_numbers:
                    seen_numbers.add(num)
                    norm = normalize_title_text(title)
                    titles_by_norm[norm].append((num, title))
        except Exception:
            pass

    # 2. Read webnovel outline
    webnovel_path = root / ".webnovel" / "outline.json"
    if webnovel_path.is_file():
        try:
            webnovel = json.loads(webnovel_path.read_text(encoding="utf-8"))
            for chapter in webnovel.get("chapters", []):
                if not isinstance(chapter, dict):
                    continue
                num = chapter.get("chapter_number")
                title = str(chapter.get("title") or chapter.get("chapter_title") or "").strip()
                if isinstance(num, int) and not isinstance(num, bool) and title and num not in seen_numbers:
                    seen_numbers.add(num)
                    norm = normalize_title_text(title)
                    titles_by_norm[norm].append((num, title))
        except Exception:
            pass

    duplicates: dict[str, list[int]] = {}
    for norm, items in titles_by_norm.items():
        if len(items) > 1:
            sorted_items = sorted(items, key=lambda x: x[0])
            first_title = sorted_items[0][1]
            duplicates[first_title] = [num for num, _ in sorted_items]

    return duplicates


def sync_renamed_chapter_titles(
    project_root: Path | str,
    renames: dict[int, str],
) -> dict[str, Any]:
    """Atomically rename chapter titles across all layers:

    1. .story-system/outline-generation/rolling_outline.json
    2. .story-system/volume-detail/*/*.json
    3. .webnovel/outline.json
    4. chapters/0XXX-*.md (renames file and updates markdown title)
    5. .story-system/chapters/0XXX.json
    6. .story-system/chapter-index.json
    7. .webnovel/state.json
    """
    root = Path(project_root)
    cleaned_renames: dict[int, str] = {
        int(k): str(v).strip()
        for k, v in renames.items()
        if str(v).strip()
    }
    if not cleaned_renames:
        return {"renamed_count": 0, "files_updated": []}

    files_updated: list[str] = []

    # 1. Update rolling_outline.json
    rolling_path = root / ".story-system" / "outline-generation" / "rolling_outline.json"
    if rolling_path.is_file():
        try:
            rolling = json.loads(rolling_path.read_text(encoding="utf-8"))
            changed = False
            for chapter in rolling.get("chapters", []):
                if not isinstance(chapter, dict):
                    continue
                num = chapter.get("chapter_number")
                if num in cleaned_renames:
                    chapter["title"] = cleaned_renames[num]
                    changed = True
            if changed:
                _write_json_atomic(rolling_path, rolling)
                files_updated.append(str(rolling_path.relative_to(root)))
        except Exception as exc:
            raise RuntimeError(f"Failed to update rolling_outline: {exc}") from exc

    # 2. Update volume-detail/*/*.json
    volume_detail_dir = root / ".story-system" / "volume-detail"
    if volume_detail_dir.is_dir():
        for vd_file in volume_detail_dir.rglob("*.json"):
            try:
                data = json.loads(vd_file.read_text(encoding="utf-8"))
                changed = False
                if isinstance(data, dict) and isinstance(data.get("chapters"), list):
                    for chapter in data["chapters"]:
                        if not isinstance(chapter, dict):
                            continue
                        num = chapter.get("chapter_number")
                        if num in cleaned_renames:
                            chapter["title"] = cleaned_renames[num]
                            changed = True
                if changed:
                    _write_json_atomic(vd_file, data)
                    files_updated.append(str(vd_file.relative_to(root)))
            except Exception as exc:
                raise RuntimeError(f"Failed to update {vd_file}: {exc}") from exc

    # 3. Update .webnovel/outline.json
    webnovel_outline_path = root / ".webnovel" / "outline.json"
    if webnovel_outline_path.is_file():
        try:
            outline = json.loads(webnovel_outline_path.read_text(encoding="utf-8"))
            changed = False
            for chapter in outline.get("chapters", []):
                if not isinstance(chapter, dict):
                    continue
                num = chapter.get("chapter_number")
                if num in cleaned_renames:
                    chapter["title"] = cleaned_renames[num]
                    if "chapter_title" in chapter:
                        chapter["chapter_title"] = cleaned_renames[num]
                    changed = True
            if changed:
                _write_json_atomic(webnovel_outline_path, outline)
                files_updated.append(str(webnovel_outline_path.relative_to(root)))
        except Exception as exc:
            raise RuntimeError(f"Failed to update .webnovel/outline: {exc}") from exc

    # 4. Update chapters/ Markdown files
    chapters_dir = root / "chapters"
    if chapters_dir.is_dir():
        for num, new_title in cleaned_renames.items():
            pattern_prefix = f"{num:04d}-"
            matches = [f for f in chapters_dir.glob("*.md") if f.name.startswith(pattern_prefix)]
            if not matches:
                matches = [f for f in chapters_dir.glob(f"*{num}*.md") if re.match(rf"^0*{num}[-_]", f.name)]
            for md_file in matches:
                try:
                    content = md_file.read_text(encoding="utf-8")
                    # Update internal markdown header if present (e.g. # 第X章 旧标题)
                    updated_content = re.sub(
                        rf"^(#\s*第\s*[一二三四五六七八九十百千万零两\d\s]+\s*章[：:\s]*).*$",
                        rf"\g<1>{new_title}",
                        content,
                        flags=re.MULTILINE,
                    )
                    new_filename = f"{num:04d}-第{num}章 {new_title}.md"
                    new_path = chapters_dir / new_filename
                    if updated_content != content:
                        md_file.write_text(updated_content, encoding="utf-8")
                    if md_file != new_path:
                        md_file.rename(new_path)
                    files_updated.append(f"chapters/{new_filename}")
                except Exception as exc:
                    raise RuntimeError(f"Failed to rename chapter markdown file {md_file}: {exc}") from exc

    # 5. Update .story-system/chapters/0XXX.json
    story_chapters_dir = root / ".story-system" / "chapters"
    if story_chapters_dir.is_dir():
        for num, new_title in cleaned_renames.items():
            sc_matches = list(story_chapters_dir.glob(f"{num:04d}.json")) + list(story_chapters_dir.glob(f"{num}.json"))
            for sc_file in set(sc_matches):
                try:
                    data = json.loads(sc_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        if "chapter_title" in data:
                            data["chapter_title"] = new_title
                        if "title" in data:
                            data["title"] = new_title
                        _write_json_atomic(sc_file, data)
                        files_updated.append(str(sc_file.relative_to(root)))
                except Exception as exc:
                    raise RuntimeError(f"Failed to update chapter JSON {sc_file}: {exc}") from exc

    # 6. Update .story-system/chapter-index.json
    chapter_index_path = root / ".story-system" / "chapter-index.json"
    if chapter_index_path.is_file():
        try:
            ci = json.loads(chapter_index_path.read_text(encoding="utf-8"))
            changed = False
            if isinstance(ci, dict) and isinstance(ci.get("chapters"), list):
                for chapter in ci["chapters"]:
                    if not isinstance(chapter, dict):
                        continue
                    num = chapter.get("chapter_number")
                    if num in cleaned_renames:
                        if "chapter_title" in chapter:
                            chapter["chapter_title"] = cleaned_renames[num]
                        if "title" in chapter:
                            chapter["title"] = cleaned_renames[num]
                        changed = True
            if changed:
                _write_json_atomic(chapter_index_path, ci)
                files_updated.append(str(chapter_index_path.relative_to(root)))
        except Exception as exc:
            raise RuntimeError(f"Failed to update chapter-index.json: {exc}") from exc

    # 7. Update .webnovel/state.json
    state_path = root / ".webnovel" / "state.json"
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            changed = False
            if isinstance(state, dict):
                summaries = state.get("chapter_summaries")
                if isinstance(summaries, list):
                    for summary in summaries:
                        if not isinstance(summary, dict):
                            continue
                        num = summary.get("chapter_number")
                        if num in cleaned_renames:
                            if "chapter_title" in summary:
                                summary["chapter_title"] = cleaned_renames[num]
                            if "title" in summary:
                                summary["title"] = cleaned_renames[num]
                            changed = True
            if changed:
                _write_json_atomic(state_path, state)
                files_updated.append(str(state_path.relative_to(root)))
        except Exception as exc:
            raise RuntimeError(f"Failed to update state.json: {exc}") from exc

    return {
        "renamed_count": len(cleaned_renames),
        "files_updated": files_updated,
    }
