# -*- coding: utf-8 -*-
"""Markdown 大纲文件与工作台结构化大纲（.webnovel/outline.json）的双向同步。

设计要点（last-writer-wins）：
- 参与同步的 md 文件：``大纲/总纲.md``（overall + arcs）与
  ``大纲/第*卷-详细大纲.md``（chapters）。节拍表/时间线/爽点规划等纯人类
  规划文档不参与同步，绝不改动。
- json 的 ChapterPlan 只有 9 个字段，md 章块有 15 个字段。导出时做字段级
  合并：json 拥有的字段以 json 为准更新，md 独有的字段（代价/时间锚点/
  Strand/钩子等）原样保留；未被 touch 的章节块保持字节不变。
- round-trip 稳定性：export 渲染的格式可以被 import 原样解析回同样的
  json（deep-equal）。对「解析值与 json 值相等」的行保留原文，最大程度
  减小对人工维护 md 的 diff。
- mtime 平手策略防止抖动：import 写 json 后把 json 的 mtime 设为 md 最新
  mtime；export 写 md 后同样把 json mtime 抬到 md 最新 mtime。两侧相等即
  视为「已同步」，不会 import→export→import 乒乓。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from packages.story_core.elastic_outline import validate_outline_for_project
from packages.story_core.project_outline import normalize_project_outline

OUTLINE_DIR_NAME = "大纲"
OVERVIEW_FILENAME = "总纲.md"
DETAIL_GLOB = "第*卷-详细大纲.md"

# 章节块字段的规范顺序（json 拥有的 9 个字段 + md 独有字段）。
CHAPTER_FIELD_ORDER = [
    "目标",
    "阻力",
    "代价",
    "时间锚点",
    "章内时间跨度",
    "与上章时间差",
    "倒计时状态",
    "爽点",
    "Strand",
    "反派层级",
    "视角/主角",
    "关键实体",
    "本章变化",
    "章末未闭合问题",
    "钩子",
]

# json ChapterPlan 字段 → md 字段名（title/chapter_number 走标题行）。
CHAPTER_JSON_TO_MD = {
    "goal": "目标",
    "obstacle": "阻力",
    "action": "代价",
    "turn": "爽点",
    "cast": "视角/主角",
    "payoff": "本章变化",
    "ending_hook": "章末未闭合问题",
}
CHAPTER_MD_TO_JSON = {value: key for key, value in CHAPTER_JSON_TO_MD.items()}

# 分卷纲要 bullet → ArcOutline 字段。"卷末钩子" 等未列出的 bullet 为 md 独有，保留。
ARC_MD_TO_JSON = {
    "阶段目标": "goal",
    "核心冲突": "obstacle",
    "卷末高潮": "payoff",
    "现实线": "reality_line_payoff",
    "阶段反派": "stage_antagonist",
    "终态": "end_state",
    "游戏线兑现": "game_line_payoff",
    "长期反派痕迹": "long_term_antagonist_traces",
    "延续路线": "extension_gate.continue_route",
    "收束路线": "extension_gate.close_route",
}
# 导出时分卷纲要 bullet 的补充顺序（已存在的 bullet 保持原位置）。
ARC_BULLET_ORDER = [
    "阶段目标",
    "核心冲突",
    "阶段反派",
    "长期反派痕迹",
    "卷末高潮",
    "游戏线兑现",
    "现实线",
    "终态",
    "延续路线",
    "收束路线",
]

# 总纲中由同步模块自动维护的小节，存放 md 里没有自然归属的 overall 字段。
SYNC_META_HEADING = "## 同步元数据（自动维护）"

_CHAPTER_HEADING_RE = re.compile(r"^### 第\s*(\d+)\s*章[：:](.*)$")
# md 详细大纲字段行使用半角冒号：``- 目标: ...``；总纲的 ``- **xx**：`` 不会误匹配。
_CHAPTER_FIELD_RE = re.compile(r"^- ([^:\n*][^:\n]*):\s*(.*)$")
_ARC_HEADING_RE = re.compile(r"^### 第(\d+)卷[：:](.+?)（第\s*(\d+)\s*-\s*(\d+)\s*章(.*)）\s*$")
# 总纲 bullet 使用全角冒号：``- **阶段目标**：...``
_BULLET_RE = re.compile(r"^- \*\*([^*：:]+)\*\*[：:]\s*(.*)$")
_H2_RE = re.compile(r"^## (.+)$")
_DONE_MARK_RE = re.compile(r"【.*?】")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    """按字节读取并解码，避免平台换行转换掩盖混合换行符。"""
    return path.read_bytes().decode("utf-8")


def _write_text_atomic(path: Path, text: str) -> None:
    """原子写文本文件（与 FileProjectStore._write_json_atomic 同模式）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = None
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            if fd is not None:
                os.close(fd)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: Any) -> None:
    _write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _strip_done_marks(title: str) -> str:
    return _DONE_MARK_RE.sub("", title).strip()


def _split_cast(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[、/]", value) if part.strip()]


def _split_traces(value: str) -> list[str]:
    return [part.strip() for part in value.split("、") if part.strip()]


# ---------------------------------------------------------------------------
# 详细大纲（章节块）解析
# ---------------------------------------------------------------------------


def _parse_volume_blocks(text: str) -> tuple[list[str], list[dict[str, Any]]]:
    """把详细大纲 md 拆成行列表 + 章节块列表。

    每个块：{number, title_raw, heading_idx, end_idx, fields: {md_key: (line_idx, value)}}。
    end_idx 为该块最后一个字段行的下一行（不含尾部空行）。
    """
    lines = text.splitlines()
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for idx, line in enumerate(lines):
        heading = _CHAPTER_HEADING_RE.match(line)
        if heading:
            current = {
                "number": int(heading.group(1)),
                "title_raw": heading.group(2).strip(),
                "heading_idx": idx,
                "end_idx": idx + 1,
                "fields": {},
            }
            blocks.append(current)
            continue
        if current is None:
            continue
        field = _CHAPTER_FIELD_RE.match(line)
        if field:
            key = field.group(1).strip()
            value = field.group(2).strip()
            if key not in current["fields"]:
                current["fields"][key] = (idx, value)
                current["end_idx"] = idx + 1
    return lines, blocks


def _block_to_chapter(block: dict[str, Any]) -> dict[str, Any]:
    fields = block["fields"]
    chapter: dict[str, Any] = {
        "chapter_number": block["number"],
        "title": _strip_done_marks(block["title_raw"]),
    }
    for md_key, json_key in CHAPTER_MD_TO_JSON.items():
        entry = fields.get(md_key)
        value = entry[1] if entry else ""
        if json_key == "cast":
            chapter["cast"] = _split_cast(value)
        elif value:
            chapter[json_key] = value
    return chapter


def _parse_volume_chapters(path: Path) -> list[dict[str, Any]]:
    _, blocks = _parse_volume_blocks(_read_text(path))
    return [_block_to_chapter(block) for block in blocks]


# ---------------------------------------------------------------------------
# 总纲解析
# ---------------------------------------------------------------------------


def _h2_sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """返回 [(标题, 起始行, 结束行)]，起始行为 ``## `` 标题行。"""
    sections: list[tuple[str, int, int]] = []
    for idx, line in enumerate(lines):
        match = _H2_RE.match(line)
        if match:
            if sections:
                sections[-1] = (sections[-1][0], sections[-1][1], idx)
            sections.append((match.group(1).strip(), idx, len(lines)))
    return sections


def _parse_bullets(lines: list[str], start: int, end: int) -> dict[str, tuple[int, int, str]]:
    """解析区间内的 ``- **key**：value`` bullet，支持缩进续行。

    返回 {key: (起始行, 结束行的下一行, value)}；多行 value 以 \\n 连接。
    """
    bullets: dict[str, tuple[int, int, str]] = {}
    idx = start
    while idx < end:
        match = _BULLET_RE.match(lines[idx])
        if not match:
            idx += 1
            continue
        key = match.group(1).strip()
        parts = [match.group(2)]
        stop = idx + 1
        while stop < end:
            nxt = lines[stop]
            if nxt.startswith((" ", "\t")) and nxt.strip():
                parts.append(nxt.strip())
                stop += 1
            else:
                break
        if key not in bullets:
            bullets[key] = (idx, stop, "\n".join(parts).strip())
        idx = stop
    return bullets


def _section_body_text(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start:end]).strip()


def _parse_overview(path: Path) -> dict[str, Any]:
    lines = _read_text(path).splitlines()
    sections = _h2_sections(lines)
    by_title = {title: (start, end) for title, start, end in sections}

    overall: dict[str, Any] = {}
    story_span = by_title.get("故事一句话")
    if story_span:
        overall["story"] = _section_body_text(lines, story_span[0] + 1, story_span[1])

    main_line = by_title.get("核心主线")
    if main_line:
        bullets = _parse_bullets(lines, main_line[0] + 1, main_line[1])
        if "主线目标" in bullets:
            overall["protagonist_goal"] = bullets["主线目标"][2]
        if "主要阻力" in bullets:
            overall["main_conflict"] = bullets["主要阻力"][2]

    growth = by_title.get("主角成长线")
    if growth:
        bullets = _parse_bullets(lines, growth[0] + 1, growth[1])
        if "关键跃迁节点" in bullets:
            overall["growth_path"] = bullets["关键跃迁节点"][2]
        if "终局定位" in bullets:
            overall["ending_direction"] = bullets["终局定位"][2]

    meta = next(
        (span for title, span in by_title.items() if title.startswith("同步元数据")),
        None,
    )
    if meta:
        bullets = _parse_bullets(lines, meta[0] + 1, meta[1])
        try:
            if "核心终局章" in bullets:
                overall["core_ending_chapter"] = int(bullets["核心终局章"][2])
            if "扩展上限章" in bullets:
                overall["extension_ceiling_chapter"] = int(bullets["扩展上限章"][2])
        except ValueError:
            pass
        if "当前策略" in bullets and bullets["当前策略"][2] in ("observe", "expand", "close"):
            overall["current_strategy"] = bullets["当前策略"][2]
        if "终局契约" in bullets:
            overall["ending_contract"] = bullets["终局契约"][2]

    arcs: list[dict[str, Any]] = []
    arcs_span = by_title.get("分卷纲要")
    if arcs_span:
        for idx in range(arcs_span[0] + 1, arcs_span[1]):
            heading = _ARC_HEADING_RE.match(lines[idx])
            if not heading:
                continue
            sec_end = arcs_span[1]
            for j in range(idx + 1, arcs_span[1]):
                if lines[j].startswith("### "):
                    sec_end = j
                    break
            bullets = _parse_bullets(lines, idx + 1, sec_end)
            arc: dict[str, Any] = {
                "id": f"vol-{int(heading.group(1))}",
                "title": heading.group(2).strip(),
                "start_chapter": int(heading.group(3)),
                "end_chapter": int(heading.group(4)),
                "extension_gate": {},
            }
            provided: set[str] = set()
            for md_key, json_key in ARC_MD_TO_JSON.items():
                entry = bullets.get(md_key)
                if entry is None:
                    continue
                value = entry[2]
                provided.add(json_key)
                if json_key == "long_term_antagonist_traces":
                    arc["long_term_antagonist_traces"] = _split_traces(value)
                elif json_key.startswith("extension_gate."):
                    arc["extension_gate"][json_key.split(".", 1)[1]] = value
                else:
                    arc[json_key] = value
            arc["_provided"] = provided
            arcs.append(arc)

    return {"overall": overall, "arcs": arcs, "has_meta": meta is not None}


def _merge_with_existing_json(
    project_root: Path,
    overall: dict[str, Any],
    arcs: list[dict[str, Any]],
    *,
    has_meta: bool,
) -> None:
    """md 没有覆盖到的 arc/overall 字段，从现有 outline.json 取长补短。

    真实项目的 outline.json 可能带有 md 分卷纲要里没有的 arc 元数据
    （阶段反派/终态/延期闸门等）；import 时不应把这些字段抹成空值。
    md 明确提供的字段仍以 md 为准。读取失败时静默跳过。
    """
    json_path = Path(project_root) / ".webnovel" / "outline.json"
    try:
        existing = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(existing, dict):
        return
    existing_overall = existing.get("overall")
    if not has_meta and isinstance(existing_overall, dict):
        for key in (
            "core_ending_chapter",
            "extension_ceiling_chapter",
            "current_strategy",
            "ending_contract",
        ):
            if key not in overall and existing_overall.get(key) not in (None, ""):
                overall[key] = existing_overall[key]
    existing_arcs = existing.get("arcs")
    if not isinstance(existing_arcs, list):
        return
    by_id = {
        str(item.get("id")): item
        for item in existing_arcs
        if isinstance(item, dict) and item.get("id")
    }
    for arc in arcs:
        provided = arc.get("_provided") or set()
        old = by_id.get(arc["id"])
        if not old:
            continue
        for key in (
            "goal",
            "obstacle",
            "payoff",
            "end_state",
            "stage_antagonist",
            "game_line_payoff",
            "reality_line_payoff",
        ):
            if key not in provided and old.get(key):
                arc[key] = old[key]
        if "long_term_antagonist_traces" not in provided and old.get("long_term_antagonist_traces"):
            arc["long_term_antagonist_traces"] = old["long_term_antagonist_traces"]
        old_gate = old.get("extension_gate")
        if isinstance(old_gate, dict):
            gate = arc.setdefault("extension_gate", {})
            for route in ("continue_route", "close_route"):
                if f"extension_gate.{route}" not in provided and old_gate.get(route):
                    gate[route] = old_gate[route]


# ---------------------------------------------------------------------------
# import：md → json
# ---------------------------------------------------------------------------


def import_markdown_outline(project_root: Path) -> dict[str, Any] | None:
    """把 大纲/*.md 解析为 project-outline/v1 dict。

    解析失败或关键内容（总纲/故事一句话/分卷纲要）缺失时返回 None，
    绝不产生半残数据。
    """
    try:
        outline_dir = Path(project_root) / OUTLINE_DIR_NAME
        overview_path = outline_dir / OVERVIEW_FILENAME
        if not overview_path.exists():
            return None
        parsed = _parse_overview(overview_path)
        overall = parsed["overall"]
        arcs = parsed["arcs"]
        if not str(overall.get("story") or "").strip() or not arcs:
            return None
        _merge_with_existing_json(
            Path(project_root), overall, arcs, has_meta=parsed["has_meta"]
        )
        for arc in arcs:
            arc.pop("_provided", None)
        chapters: list[dict[str, Any]] = []
        for volume_path in sorted(outline_dir.glob(DETAIL_GLOB)):
            chapters.extend(_parse_volume_chapters(volume_path))
        outline = {
            "schema_version": "project-outline/v1",
            "overall": overall,
            "arcs": arcs,
            "chapters": chapters,
        }
        return normalize_project_outline(outline)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# export：json → md（字段级合并渲染）
# ---------------------------------------------------------------------------


def _render_bullet(key: str, value: str) -> list[str]:
    """渲染总纲 bullet，多行值用缩进续行表示（可被 _parse_bullets 还原）。"""
    parts = str(value).split("\n")
    lines = [f"- **{key}**：{parts[0]}".rstrip()]
    lines.extend(f"  {part}".rstrip() for part in parts[1:])
    return lines


def _render_chapter_lines(
    number: int,
    title: str,
    values: dict[str, str],
    include_keys: set[str],
) -> list[str]:
    """渲染章节块。只渲染「值非空」或「在 include_keys 里」的字段行，
    避免给原本没有该字段的块追加一堆空行噪音。"""
    heading = f"### 第 {number} 章：{title}".rstrip()
    lines = [heading]
    for key in CHAPTER_FIELD_ORDER:
        value = values.get(key, "")
        if value or key in include_keys:
            lines.append(f"- {key}: {value}".rstrip())
    return lines


def _chapter_field_values(chapter: dict[str, Any], existing: dict[str, tuple[int, str]] | None) -> dict[str, str]:
    """合并单章字段值：json 拥有的 9 个字段用 json，md 独有字段保留原值。"""
    values: dict[str, str] = {}
    existing = existing or {}
    for key in CHAPTER_FIELD_ORDER:
        values[key] = existing[key][1] if key in existing else ""
    for json_key, md_key in CHAPTER_JSON_TO_MD.items():
        raw = chapter.get(json_key)
        if json_key == "cast":
            values[md_key] = "、".join(str(item) for item in (raw or []))
        else:
            values[md_key] = str(raw or "")
    return values


def _chapter_block_unchanged(block: dict[str, Any], chapter: dict[str, Any]) -> bool:
    if _strip_done_marks(block["title_raw"]) != str(chapter.get("title") or "").strip():
        return False
    fields = block["fields"]
    for json_key, md_key in CHAPTER_JSON_TO_MD.items():
        existing = fields.get(md_key)
        existing_value = existing[1] if existing else ""
        raw = chapter.get(json_key)
        if json_key == "cast":
            if _split_cast(existing_value) != [str(item) for item in (raw or [])]:
                return False
        elif existing_value != str(raw or "").strip():
            return False
    return True


def _merge_volume_text(text: str, chapters: list[dict[str, Any]]) -> tuple[str, set[int]]:
    """把 json 章节合并进一个详细大纲文件，返回 (新文本, 已处理的章节号)。"""
    lines, blocks = _parse_volume_blocks(text)
    by_number = {block["number"]: block for block in blocks}
    handled: set[int] = set()
    # 自底向上替换，避免行号位移。
    replacements: list[tuple[int, int, list[str]]] = []
    for chapter in chapters:
        number = int(chapter["chapter_number"])
        block = by_number.get(number)
        if block is None:
            continue
        handled.add(number)
        if _chapter_block_unchanged(block, chapter):
            continue
        values = _chapter_field_values(chapter, block["fields"])
        include_keys = set(block["fields"]) | set(CHAPTER_JSON_TO_MD.values())
        rendered = _render_chapter_lines(
            number, str(chapter.get("title") or "").strip(), values, include_keys
        )
        replacements.append((block["heading_idx"], block["end_idx"], rendered))
    for start, stop, rendered in sorted(replacements, reverse=True):
        lines[start:stop] = rendered
    if not replacements:
        # 没有任何字段变化：原文原样返回（保留原始换行符/字节），不重写文件。
        return text, handled
    new_text = "\n".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, handled


def _volume_range(text: str, blocks: list[dict[str, Any]]) -> tuple[int, int]:
    header = re.search(r"^> 章节范围[：:]\s*第\s*(\d+)\s*-\s*(\d+)\s*章", text, re.M)
    if header:
        return int(header.group(1)), int(header.group(2))
    numbers = [block["number"] for block in blocks]
    return (min(numbers), max(numbers)) if numbers else (1, 0)


def _export_chapters(outline_dir: Path, chapters: list[dict[str, Any]]) -> list[Path]:
    """把章节合并到各卷详细大纲文件，返回被写入的文件列表。"""
    volume_paths = sorted(outline_dir.glob(DETAIL_GLOB))
    if not chapters:
        return []
    written: list[Path] = []
    remaining = {int(ch["chapter_number"]): ch for ch in chapters}
    file_texts: dict[Path, str] = {}
    file_blocks: dict[Path, list[dict[str, Any]]] = {}
    for path in volume_paths:
        file_texts[path] = _read_text(path)
        _, file_blocks[path] = _parse_volume_blocks(file_texts[path])

    # 第一遍：已有章节按所在文件合并。
    for path in volume_paths:
        numbers = {block["number"] for block in file_blocks[path]}
        targets = [remaining[num] for num in sorted(numbers & remaining.keys())]
        if not targets:
            continue
        new_text, handled = _merge_volume_text(file_texts[path], targets)
        for num in handled:
            remaining.pop(num, None)
        if new_text != file_texts[path]:
            _write_text_atomic(path, new_text)
            file_texts[path] = new_text
            written.append(path)

    # 第二遍：json 新增章节，追加到章节范围匹配的卷文件（否则最后一个卷文件）。
    for number in sorted(remaining):
        target_path: Path | None = None
        for path in volume_paths:
            start, end = _volume_range(file_texts[path], file_blocks[path])
            if start <= number <= end:
                target_path = path
                break
        if target_path is None:
            target_path = volume_paths[-1] if volume_paths else None
        if target_path is None:
            # 项目还没有任何详细大纲文件：新建第1卷。
            target_path = outline_dir / "第1卷-详细大纲.md"
            file_texts[target_path] = f"# 第 1 卷\n"
            volume_paths.append(target_path)
        values = _chapter_field_values(remaining[number], None)
        block_lines = _render_chapter_lines(
            number,
            str(remaining[number].get("title") or "").strip(),
            values,
            set(CHAPTER_JSON_TO_MD.values()),
        )
        base = file_texts[target_path].rstrip("\n")
        new_text = base + "\n\n" + "\n".join(block_lines) + "\n"
        _write_text_atomic(target_path, new_text)
        file_texts[target_path] = new_text
        _, file_blocks[target_path] = _parse_volume_blocks(new_text)
        if target_path not in written:
            written.append(target_path)
    return written


def _find_section(lines: list[str], title_prefix: str) -> tuple[int, int] | None:
    for title, start, end in _h2_sections(lines):
        if title.startswith(title_prefix):
            return start, end
    return None


def _merge_overview_bullets(
    lines: list[str], span: tuple[int, int], updates: dict[str, str]
) -> None:
    """在某个 ## 小节内做 bullet 级合并（相等保留原文，不同替换，缺失追加）。"""
    start, end = span
    bullets = _parse_bullets(lines, start + 1, end)
    replacements: list[tuple[int, int, list[str]]] = []
    missing: dict[str, str] = {}
    for key, value in updates.items():
        entry = bullets.get(key)
        if entry is None:
            # 空值的新 bullet 不追加，避免给人工维护的小节塞空行噪音；
            # round-trip 不受影响（缺失的 bullet 解析回来同样是空值）。
            if str(value).strip():
                missing[key] = value
        elif entry[2] != str(value).strip():
            replacements.append((entry[0], entry[1], _render_bullet(key, str(value).strip())))
    for r_start, r_stop, rendered in sorted(replacements, reverse=True):
        lines[r_start:r_stop] = rendered
    if missing:
        # 追加到小节最后一个非空内容行之后。
        # 注意：上面的替换可能已改变行数，这里从 start 重新扫描小节边界，
        # 遇到任何标题行（## 或 ###）即停止，不能依赖调用方传入的旧 end。
        insert_at = start + 1
        for idx in range(start + 1, len(lines)):
            if lines[idx].startswith("#"):
                break
            if lines[idx].strip():
                insert_at = idx + 1
        rendered: list[str] = []
        for key, value in missing.items():
            rendered.extend(_render_bullet(key, str(value).strip()))
        lines[insert_at:insert_at] = rendered


def _arc_numbers(arc: dict[str, Any]) -> int | None:
    match = re.fullmatch(r"vol-(\d+)", str(arc.get("id") or ""))
    return int(match.group(1)) if match else None


def _export_overview(path: Path, outline: dict[str, Any]) -> bool:
    """把 overall/arcs 合并渲染回 总纲.md，返回是否有写入。"""
    original = _read_text(path)
    lines = original.splitlines()
    overall = outline["overall"]
    arcs = outline["arcs"]

    # 1. 故事一句话（整节替换 body，内容相等则不动）。
    story = str(overall.get("story") or "").strip()
    story_span = _find_section(lines, "故事一句话")
    if story_span and story:
        body = _section_body_text(lines, story_span[0] + 1, story_span[1])
        if body != story:
            lines[story_span[0] + 1 : story_span[1]] = [story, ""]

    # 2. 核心主线 / 主角成长线 bullet 合并。
    main_span = _find_section(lines, "核心主线")
    if main_span:
        _merge_overview_bullets(
            lines,
            main_span,
            {
                "主线目标": str(overall.get("protagonist_goal") or ""),
                "主要阻力": str(overall.get("main_conflict") or ""),
            },
        )
    growth_span = _find_section(lines, "主角成长线")
    if growth_span:
        _merge_overview_bullets(
            lines,
            growth_span,
            {
                "关键跃迁节点": str(overall.get("growth_path") or ""),
                "终局定位": str(overall.get("ending_direction") or ""),
            },
        )

    # 3. 分卷纲要：按卷号（或章节范围）匹配合并，新卷追加小节。
    # 每次合并都可能改变行数，因此每个 arc 都重新扫描小节位置。
    def _arc_subsections() -> tuple[tuple[int, int] | None, list[tuple[int, re.Match[str], int]]]:
        span = _find_section(lines, "分卷纲要")
        if span is None:
            return None, []
        subs: list[tuple[int, re.Match[str], int]] = []
        idx = span[0] + 1
        while idx < span[1]:
            match = _ARC_HEADING_RE.match(lines[idx])
            if match:
                sec_end = span[1]
                for j in range(idx + 1, span[1]):
                    if lines[j].startswith("### "):
                        sec_end = j
                        break
                subs.append((idx, match, sec_end))
                idx = sec_end
            else:
                idx += 1
        return span, subs

    def _arc_bullet_values(arc: dict[str, Any]) -> dict[str, str]:
        values: dict[str, str] = {}
        for md_key, json_key in ARC_MD_TO_JSON.items():
            if json_key == "long_term_antagonist_traces":
                values[md_key] = "、".join(arc.get("long_term_antagonist_traces") or [])
            elif json_key.startswith("extension_gate."):
                values[md_key] = str(
                    (arc.get("extension_gate") or {}).get(json_key.split(".", 1)[1], "")
                )
            else:
                values[md_key] = str(arc.get(json_key) or "")
        return values

    def _render_arc_section(number: int, arc: dict[str, Any]) -> list[str]:
        section_lines = [
            f"### 第{number}卷：{arc.get('title') or ''}"
            f"（第{arc['start_chapter']}-{arc['end_chapter']}章）"
        ]
        bullet_values = _arc_bullet_values(arc)
        for key in ARC_BULLET_ORDER:
            section_lines.extend(_render_bullet(key, bullet_values.get(key, "")))
        return section_lines

    arcs_span, _ = _arc_subsections()
    if arcs_span:
        new_arc_sections: list[str] = []
        for arc in arcs:
            vol_no = _arc_numbers(arc)
            _, subs = _arc_subsections()  # 重新扫描，行号可能已位移
            target: tuple[int, re.Match[str], int] | None = None
            for head_idx, match, sec_end in subs:
                if vol_no is not None and int(match.group(1)) == vol_no:
                    target = (head_idx, match, sec_end)
                    break
                if (
                    int(match.group(3)) == arc["start_chapter"]
                    and int(match.group(4)) == arc["end_chapter"]
                ):
                    target = (head_idx, match, sec_end)
                    break
            if target is None:
                # 新卷：在分卷纲要末尾追加完整小节。
                n = vol_no if vol_no is not None else len(subs) + len(new_arc_sections) + 1
                new_arc_sections.extend(["", *_render_arc_section(n, arc)])
                continue
            head_idx, match, sec_end = target
            # 标题行：title/章节范围一致则保留原文（含 Lv 后缀），否则重渲染。
            if (
                match.group(2).strip() != str(arc.get("title") or "").strip()
                or int(match.group(3)) != arc["start_chapter"]
                or int(match.group(4)) != arc["end_chapter"]
            ):
                suffix = match.group(5) or ""
                n = vol_no if vol_no is not None else int(match.group(1))
                lines[head_idx] = (
                    f"### 第{n}卷：{arc.get('title') or ''}"
                    f"（第{arc['start_chapter']}-{arc['end_chapter']}章{suffix}）"
                )
            _merge_overview_bullets(lines, (head_idx, sec_end), _arc_bullet_values(arc))
        if new_arc_sections:
            span, _ = _arc_subsections()
            insert_at = span[1] if span else len(lines)
            lines[insert_at:insert_at] = new_arc_sections
    else:
        # 没有分卷纲要小节：整体追加。
        appended: list[str] = ["", "## 分卷纲要"]
        for position, arc in enumerate(arcs, start=1):
            n = _arc_numbers(arc) or position
            appended.extend(["", *_render_arc_section(n, arc)])
        lines.extend(appended)

    # 4. 同步元数据小节（overall 里没有自然归属的字段），保证 round-trip。
    meta_values = {
        "核心终局章": str(overall.get("core_ending_chapter") or ""),
        "扩展上限章": str(overall.get("extension_ceiling_chapter") or ""),
        "当前策略": str(overall.get("current_strategy") or "observe"),
        "终局契约": str(overall.get("ending_contract") or ""),
    }
    meta_span = _find_section(lines, "同步元数据")
    if meta_span:
        _merge_overview_bullets(lines, meta_span, meta_values)
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(SYNC_META_HEADING)
        for key, value in meta_values.items():
            lines.extend(_render_bullet(key, value))

    new_text = "\n".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    if new_text == original:
        return False
    _write_text_atomic(path, new_text)
    return True


def export_outline_to_markdown(project_root: Path, outline: dict[str, Any]) -> str:
    """把 project-outline/v1 dict 字段级合并渲染回 大纲/*.md。

    只更新参与同步的文件；节拍表/时间线/爽点规划等绝不触碰。
    渲染输出统一用 \\n 换行。没有 大纲/总纲.md 的项目直接跳过。
    结束后把 outline.json 的 mtime 抬到不低于 md 最新 mtime（平手策略，
    避免 export→import→export 抖动）。
    """
    root = Path(project_root)
    outline_dir = root / OUTLINE_DIR_NAME
    overview_path = outline_dir / OVERVIEW_FILENAME
    if not overview_path.exists():
        return "skipped:no-markdown-outline"

    normalized = normalize_project_outline(outline)
    _export_overview(overview_path, normalized)
    _export_chapters(outline_dir, normalized["chapters"])

    # mtime 平手策略：export 之后把 json mtime 对齐到 md 最新 mtime。
    # 两种情况都覆盖：export 写了 md（md 比 json 新）→ 抬 json；
    # export 无内容可写（json 仍比 md 新）→ 把 json 回落到 md mtime，
    # 否则每次读接口都会空跑一次 export。
    json_path = root / ".webnovel" / "outline.json"
    if json_path.exists():
        md_mtime = _latest_markdown_mtime(root)
        if md_mtime is not None and json_path.stat().st_mtime != md_mtime:
            os.utime(json_path, (md_mtime, md_mtime))
    return "ok"


# ---------------------------------------------------------------------------
# 自动方向判断同步
# ---------------------------------------------------------------------------


def _markdown_files(project_root: Path) -> list[Path]:
    outline_dir = Path(project_root) / OUTLINE_DIR_NAME
    if not outline_dir.is_dir():
        return []
    files: list[Path] = []
    overview = outline_dir / OVERVIEW_FILENAME
    if overview.exists():
        files.append(overview)
    files.extend(sorted(outline_dir.glob(DETAIL_GLOB)))
    return files


def _latest_markdown_mtime(project_root: Path) -> float | None:
    mtimes = [path.stat().st_mtime for path in _markdown_files(project_root)]
    return max(mtimes) if mtimes else None


def _current_chapter(project_root: Path) -> int:
    state_path = Path(project_root) / ".webnovel" / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return int(state.get("current_chapter") or 0)
    except Exception:
        return 0


def sync_outline_if_stale(project_root: Path) -> str:
    """比较 大纲/*.md 与 .webnovel/outline.json 的 mtime，自动选择同步方向。

    - md 新 → import 写 json（写前 validate_outline_for_project 校验，
      失败则不动 json 并返回错误说明）；
    - json 新 → export 合并渲染回 md；
    - 无 md 或无 json → 跳过；
    - 平手（刚刚同步过）→ no-op。

    返回实际执行的动作描述字符串。
    """
    root = Path(project_root)
    json_path = root / ".webnovel" / "outline.json"
    md_mtime = _latest_markdown_mtime(root)
    if md_mtime is None:
        return "skipped:no-markdown-outline"
    if not json_path.exists():
        return "skipped:no-outline-json"

    json_mtime = json_path.stat().st_mtime
    if md_mtime > json_mtime:
        outline = import_markdown_outline(root)
        if outline is None:
            return "error:markdown-parse-failed, outline.json untouched"
        try:
            validated = validate_outline_for_project(
                outline, current_chapter=_current_chapter(root)
            )
        except Exception as exc:
            return f"error:validation-failed:{exc}, outline.json untouched"
        _write_json_atomic(json_path, validated)
        # mtime 平手策略：刚写入的 json 与 md 视为同一版本，避免紧跟着 export 回写 md。
        os.utime(json_path, (md_mtime, md_mtime))
        return (
            f"imported:markdown→outline.json "
            f"({len(validated['chapters'])} chapters, {len(validated['arcs'])} arcs)"
        )
    if json_mtime > md_mtime:
        try:
            outline = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return f"error:outline-json-unreadable:{exc}"
        result = export_outline_to_markdown(root, outline)
        return f"exported:outline.json→markdown ({result})"
    return "no-op:already-in-sync"
