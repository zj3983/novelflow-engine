from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field


REQUIRED_FILES: tuple[str, ...] = ("current_focus.md", "volume_outline.md")
OPTIONAL_FILES: tuple[str, ...] = (
    "author_intent.md",
    "book_rules.md",
    "story_bible.md",
    "current_state.md",
    "pending_hooks.md",
    "subplot_board.md",
    "character_matrix.md",
)

KNOWN_FILES: tuple[str, ...] = REQUIRED_FILES + OPTIONAL_FILES
SUPPORTED_EXTRA_FILE_SUFFIXES: tuple[str, ...] = (".md", ".txt", ".json", ".yaml", ".yml")
IGNORED_EXTRA_DIRECTORIES: tuple[str, ...] = ("state", "runtime", "snapshots", ".git", ".idea", ".vscode")
CHARACTER_SECTION_ALIASES: tuple[str, ...] = ("角色档案", "角色列表", "人物档案", "角色信息")


class BookBootstrapCharacter(BaseModel):
    name: str
    goal: str = ""


class BookWorldEntry(BaseModel):
    name: str
    description: str = ""


class BookCharacterProfile(BaseModel):
    name: str
    role: str = ""
    motivation: str = ""
    current_state: str = ""
    personality: str = ""
    speech_style: str = ""
    goals: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    conflict_hooks: list[str] = Field(default_factory=list)


class BookRelationshipEdge(BaseModel):
    source: str
    target: str
    bond: str = ""
    tension: float = 0.0
    trust: float = 0.0


class BookWorldBlueprint(BaseModel):
    premise: str = ""
    world_rules: list[str] = Field(default_factory=list)
    power_system: list[str] = Field(default_factory=list)
    locations: list[BookWorldEntry] = Field(default_factory=list)
    factions: list[BookWorldEntry] = Field(default_factory=list)
    current_arc: str = ""
    constraints: list[str] = Field(default_factory=list)
    relationship_graph: list[BookRelationshipEdge] = Field(default_factory=list)


class BookFolderReport(BaseModel):
    source_path: str
    exists: bool = False
    missing_required_files: list[str] = Field(default_factory=list)
    missing_optional_files: list[str] = Field(default_factory=list)
    unusable_required_files: list[str] = Field(default_factory=list)
    empty_files: list[str] = Field(default_factory=list)
    present_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    documents: dict[str, str] = Field(default_factory=dict)
    can_bootstrap: bool = False


class BookBootstrapDraft(BaseModel):
    source_path: str
    title: str = ""
    outline: str = ""
    summary: str = ""
    world_summary: str = ""
    current_focus: str = ""
    author_constraints: list[str] = Field(default_factory=list)
    characters: list[BookBootstrapCharacter] = Field(default_factory=list)
    character_profiles: list[BookCharacterProfile] = Field(default_factory=list)
    world_blueprint: BookWorldBlueprint = Field(default_factory=BookWorldBlueprint)


class BookFolderParseResult(BaseModel):
    report: BookFolderReport
    bootstrap: BookBootstrapDraft


def normalize_book_source_path(source_path: Path | str) -> Path:
    raw = str(source_path).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        raw = raw[1:-1].strip()

    base = Path(raw).expanduser()
    try:
        base = base.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        base = Path(raw).expanduser()

    if base.exists() and base.is_file():
        return base.parent
    return base


def _safe_read_text(path: Path, warnings: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        warnings.append(f"Could not decode {path.name} as utf-8; read with replacement characters.")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"Could not read {path.name}: {exc!s}")
        return ""


def _one_line_excerpt(text: str, limit: int = 180) -> str:
    return " ".join(text.split())[:limit]


def _clean_markdown_links(text: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


def _looks_like_path_inventory(line: str) -> bool:
    normalized = line.replace("\\", "/")
    if "snapshots/" in normalized or "/state/" in normalized or normalized.startswith("state/"):
        return True
    return bool(re.search(r"\b[\w./-]+\.(json|yaml|yml|md|txt)\b", normalized)) and len(normalized) > 80


def _strip_noise(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = _clean_markdown_links(raw_line).strip()
        if not line:
            cleaned_lines.append("")
            continue
        if line.startswith("```"):
            continue
        if _looks_like_path_inventory(line):
            continue
        lowered = line.lower()
        if lowered.startswith(("version:", "genrelock:", "behavioralconstraints:", "personalitylock:", "schemaVersion:".lower())):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _compact_text(text: str) -> str:
    stripped = _strip_noise(text)
    lines = [line.strip() for line in stripped.splitlines()]
    compact: list[str] = []
    allow_blank = False
    for line in lines:
        if not line:
            if compact:
                allow_blank = True
            continue
        if allow_blank and compact:
            compact.append("")
        compact.append(line)
        allow_blank = False
    return "\n".join(compact).strip()


def _parse_character_matrix(text: str) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^:?-{3,}:?$", line):
            continue

        candidate = ""
        if line.startswith("|") and "|" in line[1:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells:
                first = cells[0]
                if first.lower() not in {"name", "角色", "姓名"} and not re.match(r"^:?-{3,}:?$", first):
                    candidate = first
        elif line.startswith(("-", "*")):
            candidate = line.lstrip("-* ").strip()

        if candidate and candidate not in seen:
            seen.add(candidate)
            names.append(candidate)
    return names


def _parse_character_profiles(text: str) -> list[BookBootstrapCharacter]:
    characters: list[BookBootstrapCharacter] = []
    current_name = ""
    current_fields: dict[str, str] = {}

    def flush_current() -> None:
        nonlocal current_name, current_fields
        name = current_name.strip().strip("*# ")
        if not name:
            return
        characters.append(BookBootstrapCharacter(name=name, goal=_profile_goal(current_fields)))
        current_name = ""
        current_fields = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^##\s+(.+)$", line)
        if heading:
            flush_current()
            current_name = heading.group(1).strip()
            continue
        if not current_name:
            continue
        field = re.match(r"^[-*]\s*\*\*([^*]+)\*\*\s*[:：]\s*(.+)$", line)
        if field:
            current_fields[field.group(1).strip()] = field.group(2).strip()

    flush_current()
    return characters


def _profile_goal(fields: dict[str, str]) -> str:
    for key in ("Current", "Goal", "Motivation", "Role", "当前", "当前目标", "动机", "核心动机", "定位"):
        value = fields.get(key)
        if value:
            return _one_line_excerpt(value, limit=100)
    return ""


def _parse_structured_character_profiles(text: str) -> list[BookCharacterProfile]:
    profiles: list[BookCharacterProfile] = []
    current_name = ""
    current_fields: dict[str, str] = {}

    def field_value(*keys: str) -> str:
        for key in keys:
            if current_fields.get(key):
                return _one_line_excerpt(current_fields[key], limit=180)
        return ""

    def list_value(*keys: str) -> list[str]:
        raw = field_value(*keys)
        if not raw:
            return []
        return [part.strip() for part in re.split(r"[;；、,，/]", raw) if part.strip()]

    def flush_current() -> None:
        nonlocal current_name, current_fields
        name = current_name.strip().strip("*# ")
        if not name:
            return
        profiles.append(
            BookCharacterProfile(
                name=name,
                role=field_value("Role", "定位", "角色", "身份"),
                motivation=field_value("Motivation", "动机", "核心动机"),
                current_state=field_value("Current", "当前", "当前状态"),
                personality=field_value("Personality", "性格", "人格"),
                speech_style=field_value("Speech", "Speech Style", "说话风格", "语气"),
                goals=list_value("Goal", "Goals", "目标", "当前目标"),
                secrets=list_value("Secret", "Secrets", "秘密"),
                conflict_hooks=list_value("Hook", "Hooks", "Conflict", "冲突钩子", "矛盾"),
            )
        )
        current_name = ""
        current_fields = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^##\s+(.+)$", line)
        if heading:
            flush_current()
            current_name = heading.group(1).strip()
            continue
        if not current_name:
            continue
        field = re.match(r"^[-*]\s*\*\*([^*]+)\*\*\s*[:：]\s*(.+)$", line)
        if field:
            current_fields[field.group(1).strip()] = field.group(2).strip()

    flush_current()
    return profiles


def _best_goal_from_cells(cells: list[str]) -> str:
    for index in (8, 7, 6, 1):
        if index < len(cells):
            candidate = _one_line_excerpt(_compact_text(cells[index]), limit=80).strip()
            if candidate:
                return candidate
    return ""


def _parse_character_matrix_strict(text: str) -> list[BookBootstrapCharacter]:
    seen: set[str] = set()
    characters: list[BookBootstrapCharacter] = []
    collecting_characters = False
    section_aliases = CHARACTER_SECTION_ALIASES + ("角色档案", "角色列表", "人物档案", "角色信息")
    has_character_section = any(section_name in text for section_name in section_aliases)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        section_match = re.match(r"^###\s+(.*)$", line)
        if section_match:
            collecting_characters = section_match.group(1).strip() in section_aliases
            continue

        if re.match(r"^:?-{3,}:?$", line):
            continue

        if not collecting_characters and has_character_section:
            continue

        if line.startswith("|") and "|" in line[1:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not cells:
                continue
            first = cells[0]
            if first.lower() in {"name", "角色", "姓名"}:
                continue
            if re.match(r"^角色[a-zA-Z]$", first):
                continue
            if re.match(r"^:?-{3,}:?$", first):
                continue
            if first and first not in seen:
                seen.add(first)
                characters.append(BookBootstrapCharacter(name=first, goal=_best_goal_from_cells(cells)))
            continue

        if line.startswith(("-", "*")) and not has_character_section:
            candidate = line.lstrip("-* ").strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                characters.append(BookBootstrapCharacter(name=candidate, goal=""))

    return characters


def _extract_focus_bullets(text: str, limit: int = 6) -> list[str]:
    bullets: list[str] = []
    for raw_line in _compact_text(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("-", "*")):
            bullets.append(line.lstrip("-* ").strip())
        elif re.match(r"^\d+[.)、\s]*", line):
            bullets.append(re.sub(r"^\d+[.)、\s]*", "", line))
        if len(bullets) >= limit:
            break
    if bullets:
        return bullets
    for raw_line in _compact_text(text).splitlines():
        line = raw_line.strip().lstrip("# ").strip()
        if not line or len(line) < 8:
            continue
        if ":" in line:
            line = line.split(":", 1)[1].strip() or line
        bullets.append(line)
        if len(bullets) >= limit:
            break
    return bullets


def _extract_short_paragraph(text: str, limit: int = 160) -> str:
    for raw_line in _compact_text(text).splitlines():
        line = raw_line.strip().lstrip("-*# ").strip()
        if not line or len(line) < 8:
            continue
        return _one_line_excerpt(line, limit)
    return ""


def _extract_world_summary(text: str, limit: int = 520) -> str:
    """Build a useful project-level worldview instead of returning the document title."""
    compact = _compact_text(text)
    if not compact:
        return ""

    picked: list[str] = []
    current_heading = ""
    for raw_line in compact.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading = re.match(r"^#{1,3}\s*(.+)$", line)
        if heading:
            title = heading.group(1).strip()
            current_heading = title
            # Skip pure document titles such as "《xxx》故事圣经".
            if "故事圣经" in title or "story bible" in title.lower():
                continue
            if len(title) >= 4 and len(picked) < 4 and not re.match(r"^\d+[_-]", title):
                picked.append(title)
            continue

        cleaned = line.lstrip("-* ").strip().replace("**", "")
        if len(cleaned) < 10:
            continue
        if "故事圣经" in cleaned and len(cleaned) < 40:
            continue
        if current_heading and not cleaned.startswith(current_heading):
            display_heading = re.sub(r"^\d+[_-]", "", current_heading)
            cleaned = f"{display_heading}：{cleaned}"
        picked.append(_one_line_excerpt(cleaned, limit=180))
        if len(picked) >= 5:
            break

    summary = "\n".join(dict.fromkeys(picked)).strip()
    return summary[:limit]


def _strip_label(line: str) -> tuple[str, str]:
    cleaned = line.strip().lstrip("-* ").strip().replace("**", "")
    match = re.match(r"^([^:：]{2,24})[:：]\s*(.+)$", cleaned)
    if not match:
        return "", cleaned
    return match.group(1).strip().lower(), match.group(2).strip()


def _entry_from_sentence(sentence: str) -> BookWorldEntry:
    name = sentence
    description = sentence
    match = re.match(r"^(?:the\s+)?(.+?)\s+(?:is|are|hunts|controls|guards|owns|seeks)\b(.+)$", sentence, re.IGNORECASE)
    if match:
        name = match.group(1).strip(" .")
    elif "，" in sentence:
        name = sentence.split("，", 1)[0].strip()
    elif "," in sentence:
        name = sentence.split(",", 1)[0].strip()
    return BookWorldEntry(name=name[:48], description=description)


def _has_substantive_text(value: str) -> bool:
    if value.rstrip().endswith((":","：")):
        return False
    cleaned = value.strip().strip("-:：.。")
    return len(cleaned) >= 4


def _looks_like_price_or_item(value: str) -> bool:
    return any(token in value for token in ("铜币", "银币", "金币", "元", "药水", "武器", "装备", "材料", "消耗品"))


def _build_world_blueprint(
    report: BookFolderReport,
    characters: list[BookBootstrapCharacter],
    character_profiles: list[BookCharacterProfile],
) -> BookWorldBlueprint:
    story_bible = _compact_text(report.documents.get("story_bible.md", ""))
    focus = "\n".join(_extract_focus_bullets(report.documents.get("current_focus.md", ""), limit=4))
    outline = _extract_outline_summary(report.documents.get("volume_outline.md", ""), report.documents.get("current_focus.md", ""))
    constraints = _extract_author_constraints(
        report.documents.get("book_rules.md", ""),
        report.documents.get("author_intent.md", ""),
    )

    premise = ""
    world_rules: list[str] = []
    power_system: list[str] = []
    locations: list[BookWorldEntry] = []
    factions: list[BookWorldEntry] = []
    current_arc = ""
    current_heading = ""

    for raw_line in story_bible.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = re.match(r"^#{1,3}\s*(.+)$", line)
        if heading:
            current_heading = heading.group(1).strip()
            if not premise:
                premise = current_heading
            continue

        label, value = _strip_label(line)
        if not _has_substantive_text(value):
            continue

        source_text = f"{current_heading} {label} {value}"
        lowered = source_text.lower()
        if not premise and label in {"premise", "world", "game", "bible", "overview"}:
            premise = value
        if (
            label in {"rule", "rules", "mechanic", "mechanics"}
            or any(token in lowered for token in (" rule", "currency", "exchange", "limitation", "must ", "cannot "))
            or any(token in source_text for token in ("核心设定", "经济体系", "汇率", "市场规则", "交易行", "限制", "货币", "兑换"))
        ):
            world_rules.append(value)
        elif (
            label in {"power", "system", "level", "levels", "cultivation"}
            or any(token in lowered for token in ("level", "skill", "equipment", "profession", "quest", "ability", "magic", "cultivation"))
            or any(token in source_text for token in ("职业体系", "基础职业", "进阶规则", "技能", "等级", "属性", "数值体系", "金手指"))
        ):
            power_system.append(value)
        elif (
            label in {"location", "place", "city", "region", "map"}
            or any(token in lowered for token in ("village", "city", "realm", "zone", "location"))
            or any(token in current_heading for token in ("地理", "环境"))
            or any(token in label for token in ("地点", "地理", "环境", "地图"))
        ):
            if not _looks_like_price_or_item(value):
                locations.append(_entry_from_sentence(value))
        elif (
            label in {"faction", "guild", "sect", "organization"}
            or any(token in lowered for token in ("guild", "sect", "faction", "organization", "clan"))
            or any(token in current_heading for token in ("势力", "阵营"))
            or any(token in label for token in ("势力", "公会", "组织", "联盟", "阵营"))
        ):
            factions.append(_entry_from_sentence(value))
        elif label in {"arc", "current arc", "mainline", "plot"} or any(token in source_text for token in ("主线", "当前阶段", "剧情阶段")):
            current_arc = value

    if not premise:
        premise = _extract_short_paragraph(story_bible, limit=180) or _derive_project_title(Path(report.source_path), outline)
    if not current_arc:
        current_arc = _extract_short_paragraph(focus or outline, limit=220)

    relationship_graph = _build_relationship_graph(report.documents.get("character_matrix.md", ""), characters, character_profiles)

    return BookWorldBlueprint(
        premise=premise,
        world_rules=list(dict.fromkeys(world_rules))[:8],
        power_system=list(dict.fromkeys(power_system))[:8],
        locations=locations[:8],
        factions=factions[:8],
        current_arc=current_arc,
        constraints=constraints,
        relationship_graph=relationship_graph,
    )


def _build_relationship_graph(
    text: str,
    characters: list[BookBootstrapCharacter],
    profiles: list[BookCharacterProfile],
) -> list[BookRelationshipEdge]:
    edges: list[BookRelationshipEdge] = []
    seen: set[tuple[str, str, str]] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-* ").strip()
        if not line:
            continue
        arrow = re.match(r"^(.+?)\s*(?:->|=>|-->|→)\s*(.+?)(?:[:：]\s*(.+))?$", line)
        if arrow:
            source = arrow.group(1).strip()
            target = arrow.group(2).strip()
            bond = (arrow.group(3) or "").strip()
            key = (source, target, bond)
            if source and target and key not in seen:
                seen.add(key)
                edges.append(BookRelationshipEdge(source=source, target=target, bond=bond))

    if edges or len(characters) < 2:
        return edges[:12]

    lead = characters[0].name
    for character in characters[1:5]:
        bond = character.goal or "story relationship pending confirmation"
        edges.append(BookRelationshipEdge(source=lead, target=character.name, bond=bond))
    return edges


def _extract_outline_summary(volume_outline: str, current_focus: str) -> str:
    outline_text = _compact_text(volume_outline)
    focus_lines = _extract_focus_bullets(current_focus, limit=5)

    summary_parts: list[str] = []
    for line in outline_text.splitlines():
        if not line:
            continue
        if line.startswith("## ") or line.startswith("### "):
            summary_parts.append(line.lstrip("# ").strip())
        elif line.startswith(("-", "*")):
            summary_parts.append(line.lstrip("-* ").strip())
        elif len(line) >= 8 and ":" in line:
            summary_parts.append(line)
        if len(summary_parts) >= 6:
            break

    if focus_lines:
        summary_parts.append("当前聚焦：")
        summary_parts.extend(focus_lines)

    return "\n".join(summary_parts).strip()


def _extract_author_constraints(book_rules: str, author_intent: str) -> list[str]:
    constraints: list[str] = []
    seen: set[str] = set()
    combined = "\n".join(part for part in (book_rules, author_intent) if part.strip())

    for raw_line in _compact_text(combined).splitlines():
        line = raw_line.strip().lstrip("-*#> ").strip().strip('"')
        if not line:
            continue
        if len(line) < 4 or len(line) > 64:
            continue
        lowered = line.lower()
        if any(token in lowered for token in ("version", "primary", "forbidden", "protagonist", "personalitylock", "behavioralconstraints")):
            continue
        if ":" in line and not any(keyword in line for keyword in ("不要", "禁止", "必须", "避免", "不可")):
            continue
        if any(keyword in line for keyword in ("不要", "禁止", "必须", "避免", "不可")):
            if line not in seen:
                seen.add(line)
                constraints.append(line)
        if len(constraints) >= 8:
            break
    return constraints


def _build_director_summary(report: BookFolderReport) -> str:
    sections: list[str] = []

    author_intent = _extract_short_paragraph(report.documents.get("author_intent.md", ""), limit=140)
    if author_intent:
        sections.append(f"创作方向：{author_intent}")

    story_bible = _extract_short_paragraph(report.documents.get("story_bible.md", ""), limit=140)
    if story_bible:
        sections.append(f"世界背景：{story_bible}")

    focus_bullets = _extract_focus_bullets(report.documents.get("current_focus.md", ""), limit=3)
    if focus_bullets:
        sections.append("近期聚焦：")
        sections.extend(f"- {item}" for item in focus_bullets)

    constraints = _extract_author_constraints(
        report.documents.get("book_rules.md", ""),
        report.documents.get("author_intent.md", ""),
    )
    if constraints:
        sections.append("硬约束：")
        sections.extend(f"- {item}" for item in constraints[:3])

    return "\n".join(sections).strip()


def _derive_project_title(base: Path, outline: str) -> str:
    candidate = base.name.strip()
    if candidate.lower() == "story" and base.parent.name:
        candidate = base.parent.name.strip()
    if candidate:
        return candidate

    first_line = next((line.strip() for line in outline.splitlines() if line.strip()), "")
    if first_line:
        return re.sub(r"^#+\s*", "", first_line)[:24]
    return "未命名小说项目"


def scan_book_folder(source_path: Path | str) -> BookFolderParseResult:
    base = normalize_book_source_path(source_path)

    report = BookFolderReport(source_path=str(base))
    if not base.exists() or not base.is_dir():
        report.exists = False
        report.missing_required_files = sorted(REQUIRED_FILES)
        report.missing_optional_files = sorted(OPTIONAL_FILES)
        report.can_bootstrap = False
        bootstrap = BookBootstrapDraft(source_path=str(base))
        return BookFolderParseResult(report=report, bootstrap=bootstrap)

    report.exists = True
    existing_files: set[str] = set()

    for filename in KNOWN_FILES:
        file_path = base / filename
        if not file_path.exists():
            continue
        existing_files.add(filename)
        if not file_path.is_file():
            report.warnings.append(f"{filename} exists but is not a regular file.")
            if filename in REQUIRED_FILES:
                report.unusable_required_files.append(filename)
            continue

        report.present_files.append(filename)
        content = _safe_read_text(file_path, report.warnings)
        report.documents[filename] = content
        if not content.strip():
            report.empty_files.append(filename)
            if filename in REQUIRED_FILES:
                report.unusable_required_files.append(filename)

    for file_path in sorted(base.rglob("*") if base.exists() and base.is_dir() else []):
        if not file_path.is_file():
            continue
        relative_path = file_path.relative_to(base)
        if relative_path.parts and relative_path.parts[0] in IGNORED_EXTRA_DIRECTORIES:
            continue
        if file_path.name in KNOWN_FILES:
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTRA_FILE_SUFFIXES:
            continue

        key = relative_path.as_posix()
        report.present_files.append(key)
        content = _safe_read_text(file_path, report.warnings)
        report.documents[key] = content
        if not content.strip():
            report.empty_files.append(key)

    report.present_files = sorted(report.present_files)
    report.missing_required_files = sorted([name for name in REQUIRED_FILES if name not in existing_files])
    report.missing_optional_files = sorted([name for name in OPTIONAL_FILES if name not in existing_files])
    report.unusable_required_files = sorted(set(report.unusable_required_files))
    report.empty_files = sorted(set(report.empty_files))
    report.can_bootstrap = report.exists and not report.missing_required_files and not report.unusable_required_files

    volume_outline = report.documents.get("volume_outline.md", "")
    current_focus = report.documents.get("current_focus.md", "")
    outline = _extract_outline_summary(volume_outline, current_focus)
    if not outline:
        outline = _compact_text(volume_outline or current_focus)

    summary = _build_director_summary(report)
    if not summary:
        summary = _extract_short_paragraph(report.documents.get("story_bible.md", ""), limit=180)

    characters_text = report.documents.get("character_matrix.md", "")
    characters = _parse_character_profiles(characters_text) if characters_text else []
    explicit_character_section = any(
        section_name in characters_text
        for section_name in CHARACTER_SECTION_ALIASES + ("角色档案", "角色列表", "人物档案", "角色信息")
    )
    if not characters and characters_text:
        characters = _parse_character_matrix_strict(characters_text)
    if not characters and characters_text and not explicit_character_section:
        characters = [BookBootstrapCharacter(name=name, goal="") for name in _parse_character_matrix(characters_text)]

    character_profiles = _parse_structured_character_profiles(characters_text) if characters_text else []
    if not character_profiles:
        character_profiles = [
            BookCharacterProfile(name=character.name, motivation=character.goal)
            for character in characters
        ]
    world_blueprint = _build_world_blueprint(report, characters, character_profiles)

    bootstrap = BookBootstrapDraft(
        source_path=str(base),
        title=_derive_project_title(base, outline),
        outline=outline,
        summary=summary,
        world_summary=_extract_world_summary(report.documents.get("story_bible.md", "")),
        current_focus="\n".join(_extract_focus_bullets(current_focus, limit=5)),
        author_constraints=_extract_author_constraints(
            report.documents.get("book_rules.md", ""),
            report.documents.get("author_intent.md", ""),
        ),
        characters=characters,
        character_profiles=character_profiles,
        world_blueprint=world_blueprint,
    )
    return BookFolderParseResult(report=report, bootstrap=bootstrap)
