from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.story_core.novel_type_ids import canonical_novel_type_id


SKILL_PACK_SCHEMA_VERSION = "skill-pack/v1"
DEFAULT_SKILL_PACKS_DIR = Path("data") / "skill-packs"
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_MANDATORY_HEADING_MARKERS = (
    "\u89c4\u5219",
    "\u6307\u4ee4",
    "\u8981\u6c42",
    "\u65b9\u6cd5",
    "\u539f\u5219",
    "\u5de5\u4f5c\u6d41",
    "\u5de5\u4f5c\u6d41\u7a0b",
    "\u6b65\u9aa4",
    "\u68c0\u67e5\u6e05\u5355",
)


@dataclass(frozen=True)
class SkillModule:
    module_id: str
    title: str
    description: str
    summary: str
    purposes: list[str]
    content: str
    relative_path: str


@dataclass(frozen=True)
class SkillPack:
    skill_id: str
    name: str
    version: str
    author: str
    description: str
    root_content: str
    modules: list[SkillModule]
    path: Path

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": SKILL_PACK_SCHEMA_VERSION,
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "module_count": len(self.modules),
            "modules": [
                {
                    "module_id": module.module_id,
                    "title": module.title,
                    "description": module.description,
                    "summary": module.summary,
                    "purposes": module.purposes,
                    "relative_path": module.relative_path,
                }
                for module in self.modules
            ],
        }


def skill_packs_root() -> Path:
    configured = os.getenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR")
    if configured:
        return Path(configured).resolve()
    return (Path.cwd() / DEFAULT_SKILL_PACKS_DIR).resolve()


def normalize_skill_id(value: str) -> str:
    normalized = _SAFE_ID_RE.sub("-", value.strip().lower()).strip("-._")
    return normalized or "skill-pack"


def resolve_enabled_skill_ids(
    project_payload: Mapping[str, Any] | None,
    state_payload: Mapping[str, Any] | None = None,
) -> list[str]:
    """Respect an explicit project selection, including an explicit empty list."""

    project = project_payload if isinstance(project_payload, Mapping) else {}
    state = state_payload if isinstance(state_payload, Mapping) else {}
    raw_ids = project.get("enabled_skill_ids")
    if not isinstance(raw_ids, list):
        raw_ids = state.get("enabled_skill_ids")
    if not isinstance(raw_ids, list):
        return []
    return [str(item).strip() for item in raw_ids if str(item).strip()]


def resolve_enabled_skill_module_ids(
    project_payload: Mapping[str, Any] | None,
    state_payload: Mapping[str, Any] | None = None,
) -> list[str] | None:
    """Return explicit module selections, or None for legacy pack-level projects."""

    project = project_payload if isinstance(project_payload, Mapping) else {}
    state = state_payload if isinstance(state_payload, Mapping) else {}
    raw_ids = project.get("enabled_skill_module_ids")
    if not isinstance(raw_ids, list):
        raw_ids = state.get("enabled_skill_module_ids")
    if not isinstance(raw_ids, list):
        return None
    return [str(item).strip() for item in raw_ids if str(item).strip()]


def skill_module_key(skill_id: str, module_id: str) -> str:
    return f"{normalize_skill_id(skill_id)}::{normalize_skill_id(module_id)}"


def _read_text(path: Path, limit: int = 20000) -> str:
    text = path.read_text(encoding="utf-8")
    return text[:limit]


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("'\"")
    return meta


def _plain_summary(text: str, *, limit: int = 180) -> str:
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]
    lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("|") or line.startswith("```"):
            continue
        line = re.sub(r"^\-\s+", "", line)
        line = line.replace("`", "").strip()
        if line:
            lines.append(line)
        if len(" ".join(lines)) >= limit:
            break
    summary = " ".join(lines).strip()
    return summary[:limit].rstrip()


def _markdown_heading_blocks(body: str) -> list[tuple[int, str, list[str]]]:
    blocks: list[tuple[int, str, list[str]]] = []
    level = 0
    heading = ""
    lines: list[str] = []
    for raw in body.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", raw)
        if match:
            if heading or lines:
                blocks.append((level, heading, lines))
            level = len(match.group(1))
            heading = match.group(2).strip()
            lines = []
            continue
        lines.append(raw)
    if heading or lines:
        blocks.append((level, heading, lines))
    return blocks


def _clean_instruction_line(line: str) -> str:
    line = re.sub(r"^[-*]\s+", "", line)
    line = re.sub(r"^\d+[.)]\s+", "", line)
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    line = line.replace("`", "").strip()

    # These slogans are useful as editing notes but too easy to turn
    # into clipped, unnatural dialogue when copied literally.
    for old, new in (
        ("\u8d8a\u77ed\u8d8a\u72e0", "\u77ed\u53e5\u53ea\u7528\u4e8e\u5f3a\u8c03\u6216\u6253\u65ad"),
        ("\u6253\u788e\u957f\u53e5", "\u62c6\u5206\u8fc7\u957f\u53e5\uff0c\u4f46\u4fdd\u7559\u5fc5\u8981\u7684\u5bf9\u8c61\u3001\u539f\u56e0\u548c\u7ed3\u679c"),
        ("\u7559\u767d > \u8bf4\u5c3d", "\u53ef\u4ee5\u7559\u767d\u60c5\u7eea\uff0c\u4f46\u4e0d\u7701\u7565\u5bf9\u8bdd\u5bf9\u8c61\u548c\u884c\u52a8\u51b3\u5b9a"),
    ):
        line = line.replace(old, new)
    return line


def extract_skill_instructions(
    text: str,
    *,
    limit: int = 1000,
    include_examples: bool = False,
    genre_id: str = "",
) -> str:
    """Extract complete, purpose-aware heading blocks from a Skill document."""

    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]

    meta = _frontmatter(text)
    is_genre_examples = normalize_skill_id(meta.get("name", "")) == "genre-examples"
    if is_genre_examples and not include_examples:
        return ""

    candidates: list[tuple[int, str]] = []
    skipped_scope_level: int | None = None
    example_scope_level: int | None = None
    mandatory_scope_level: int | None = None
    genre_scope: tuple[int, str] | None = None
    selected_genre = canonical_novel_type_id(genre_id)
    allowed_genres = {"\u901a\u7528"}
    if selected_genre:
        allowed_genres.add(selected_genre)

    for level, heading, raw_lines in _markdown_heading_blocks(body):
        if level:
            if skipped_scope_level is not None and level <= skipped_scope_level:
                skipped_scope_level = None
            if example_scope_level is not None and level <= example_scope_level:
                example_scope_level = None
            if mandatory_scope_level is not None and level <= mandatory_scope_level:
                mandatory_scope_level = None
            if genre_scope is not None and level <= genre_scope[0]:
                genre_scope = None

            if any(marker in heading for marker in ("\u4f55\u65f6\u7528", "\u4f55\u65f6\u4f7f\u7528", "\u4e0b\u4e00\u6b65")):
                skipped_scope_level = level
            if any(marker in heading for marker in ("\u6b63\u4f8b", "\u53cd\u4f8b", "\u7ed3\u6784\u793a\u4f8b", "\u793a\u4f8b")):
                example_scope_level = level
            if any(marker in heading for marker in _MANDATORY_HEADING_MARKERS):
                mandatory_scope_level = level
            if is_genre_examples:
                tag_match = re.search(r"\[([^\]]+)\]", heading)
                if tag_match:
                    tag = tag_match.group(1).strip()
                    canonical_tag = "\u901a\u7528" if tag == "\u901a\u7528" else canonical_novel_type_id(tag)
                    genre_scope = (level, canonical_tag)

        if skipped_scope_level is not None:
            continue
        if example_scope_level is not None and not include_examples:
            continue
        if genre_scope is not None and genre_scope[1] not in allowed_genres:
            continue

        block_lines = [heading] if heading else []
        for raw in raw_lines:
            line = raw.strip()
            if not line or line.startswith("|") or line.startswith("```"):
                continue
            cleaned = _clean_instruction_line(line)
            if cleaned:
                block_lines.append(cleaned)
        block = " ".join(block_lines).strip()
        if not block:
            continue
        if example_scope_level is not None:
            priority = 2
        elif mandatory_scope_level is not None:
            priority = 0
        else:
            priority = 1
        candidates.append((priority, block))

    selected: list[str] = []
    total = 0
    for priority in range(3):
        for block_priority, block in candidates:
            if block_priority != priority:
                continue
            added_chars = len(block) + (1 if selected else 0)
            if total + added_chars > limit:
                continue
            selected.append(block)
            total += added_chars

    return " ".join(selected).strip()


def infer_skill_purposes(*values: str) -> list[str]:
    text = " ".join(value.lower() for value in values if value)
    mapping = [
        ("writer", ("writer", "write", "creator", "正文", "写章", "写作", "续写", "生成草稿")),
        ("reviewer", ("review", "reviewer", "审查", "审稿", "润色", "修订", "post-validation")),
        ("dialogue", ("dialogue", "对话", "口语", "口头禅")),
        ("style", ("style", "风格", "白描", "节奏", "语言", "humanization", "craft")),
        ("genre", ("genre", "题材", "网游", "修仙", "玄幻", "都市")),
        ("continuity", ("truth", "continuity", "manager", "world", "伏笔", "真相", "一致性", "世界观", "角色", "大纲")),
        ("workflow", ("workflow", "goethe", "dante", "agent", "流程", "调度", "planning")),
        ("text", ("text", "chunk", "compress", "切割", "压缩", "长文本")),
    ]
    purposes = [purpose for purpose, needles in mapping if any(needle in text for needle in needles)]
    return purposes or ["general"]


def _declared_purposes(meta: Mapping[str, str], *fallback_values: str) -> list[str]:
    raw = str(meta.get("purposes") or "")
    declared = [item.strip() for item in raw.split(",") if item.strip()]
    return list(dict.fromkeys(declared)) or infer_skill_purposes(*fallback_values)


def _load_manifest(root: Path, root_skill_text: str) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    meta = _frontmatter(root_skill_text)
    return {
        "skill_id": meta.get("name") or root.name,
        "name": meta.get("name") or root.name,
        "version": meta.get("version") or "0.1.0",
        "author": meta.get("author") or "",
        "description": meta.get("description") or "",
    }


def load_skill_pack(path: str | Path) -> SkillPack:
    root = Path(path).resolve()
    root_skill = root / "SKILL.md"
    if not root.is_dir() or not root_skill.exists():
        raise ValueError("skill_pack_requires_root_skill_md")

    root_content = _read_text(root_skill)
    manifest = _load_manifest(root, root_content)
    skill_id = normalize_skill_id(str(manifest.get("skill_id") or manifest.get("name") or root.name))
    modules: list[SkillModule] = []
    skills_dir = root / "skills"
    if skills_dir.exists():
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            module_root = skill_md.parent
            content = _read_text(skill_md)
            meta = _frontmatter(content)
            module_id = normalize_skill_id(str(meta.get("name") or module_root.name))
            modules.append(
                SkillModule(
                    module_id=module_id,
                    title=str(meta.get("name") or module_root.name),
                    description=str(meta.get("description") or ""),
                    summary=_plain_summary(content),
                    purposes=_declared_purposes(
                        meta,
                        module_id,
                        str(meta.get("name") or ""),
                        str(meta.get("description") or ""),
                    ),
                    content=content,
                    relative_path=str(skill_md.relative_to(root)).replace("\\", "/"),
                )
            )

    return SkillPack(
        skill_id=skill_id,
        name=str(manifest.get("name") or skill_id),
        version=str(manifest.get("version") or "0.1.0"),
        author=str(manifest.get("author") or ""),
        description=str(manifest.get("description") or ""),
        root_content=root_content,
        modules=modules,
        path=root,
    )


def list_skill_packs(root: Path | None = None) -> list[SkillPack]:
    base = root or skill_packs_root()
    if not base.exists():
        return []
    packs: list[SkillPack] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        try:
            packs.append(load_skill_pack(child))
        except ValueError:
            continue
    return packs


def get_skill_pack(skill_id: str, root: Path | None = None) -> SkillPack | None:
    wanted = normalize_skill_id(skill_id)
    for pack in list_skill_packs(root):
        if pack.skill_id == wanted:
            return pack
    return None


def _file_projects_root() -> Path:
    configured = os.getenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR")
    if configured:
        return Path(configured).resolve()
    return (Path.cwd() / "data" / "exported-projects").resolve()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.skill-uninstall.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _scrub_project_skill_reference(project_root: Path, skill_id: str) -> bool:
    changed = False
    for filename in ("project.json", "state.json"):
        path = project_root / ".webnovel" / filename
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("enabled_skill_ids"), list):
            continue
        enabled = [str(item).strip() for item in payload["enabled_skill_ids"] if str(item).strip()]
        next_enabled = [item for item in enabled if item != skill_id]
        if next_enabled == enabled:
            continue
        payload["enabled_skill_ids"] = next_enabled
        _write_json_atomic(path, payload)
        changed = True
    return changed


def _scrub_project_skill_module_reference(project_root: Path, skill_id: str, module_id: str) -> bool:
    module_key = skill_module_key(skill_id, module_id)
    pack_prefix = f"{normalize_skill_id(skill_id)}::"
    changed = False
    for filename in ("project.json", "state.json"):
        path = project_root / ".webnovel" / filename
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("enabled_skill_module_ids"), list):
            # Projects without this field use the legacy whole-pack mode. Keep
            # their pack selection intact; the removed module simply vanishes.
            continue
        enabled_modules = [str(item).strip() for item in payload["enabled_skill_module_ids"] if str(item).strip()]
        next_modules = [item for item in enabled_modules if item != module_key]
        if next_modules == enabled_modules:
            continue
        payload["enabled_skill_module_ids"] = next_modules
        enabled_packs = payload.get("enabled_skill_ids")
        if isinstance(enabled_packs, list) and not any(item.startswith(pack_prefix) for item in next_modules):
            payload["enabled_skill_ids"] = [
                str(item).strip() for item in enabled_packs if str(item).strip() != normalize_skill_id(skill_id)
            ]
        _write_json_atomic(path, payload)
        changed = True
    return changed


def uninstall_skill_pack(
    skill_id: str,
    *,
    root: Path | None = None,
    projects_root: Path | None = None,
) -> dict[str, Any]:
    normalized = normalize_skill_id(skill_id)
    registry = (root or skill_packs_root()).resolve()
    target = (registry / normalized).resolve()
    if target.parent != registry:
        raise ValueError("invalid_skill_pack_path")
    pack = get_skill_pack(normalized, registry)
    if pack is None or not target.is_dir():
        raise KeyError("skill_pack_not_found")

    shutil.rmtree(target)
    affected_project_ids: list[str] = []
    project_base = (projects_root or _file_projects_root()).resolve()
    if project_base.is_dir():
        for project_root in sorted(project_base.iterdir()):
            if not project_root.is_dir():
                continue
            if _scrub_project_skill_reference(project_root, normalized):
                affected_project_ids.append(project_root.name)
    return {
        "skill_id": normalized,
        "pack": pack.summary(),
        "affected_project_count": len(affected_project_ids),
        "affected_project_ids": affected_project_ids,
    }


def uninstall_skill_module(
    skill_id: str,
    module_id: str,
    *,
    root: Path | None = None,
    projects_root: Path | None = None,
) -> dict[str, Any]:
    normalized_skill_id = normalize_skill_id(skill_id)
    normalized_module_id = normalize_skill_id(module_id)
    if normalized_module_id == "root":
        raise ValueError("skill_pack_root_module_cannot_uninstall")

    registry = (root or skill_packs_root()).resolve()
    pack = get_skill_pack(normalized_skill_id, registry)
    if pack is None:
        raise KeyError("skill_pack_not_found")
    module = next((item for item in pack.modules if item.module_id == normalized_module_id), None)
    if module is None:
        raise KeyError("skill_module_not_found")

    skills_root = (pack.path / "skills").resolve()
    module_file = (pack.path / module.relative_path).resolve()
    module_root = module_file.parent
    if (
        module_file.name != "SKILL.md"
        or module_root.parent != skills_root
        or not module_file.is_file()
    ):
        raise ValueError("invalid_skill_module_path")

    shutil.rmtree(module_root)
    affected_project_ids: list[str] = []
    project_base = (projects_root or _file_projects_root()).resolve()
    if project_base.is_dir():
        for project_root in sorted(project_base.iterdir()):
            if not project_root.is_dir():
                continue
            if _scrub_project_skill_module_reference(project_root, normalized_skill_id, normalized_module_id):
                affected_project_ids.append(project_root.name)

    updated_pack = get_skill_pack(normalized_skill_id, registry)
    if updated_pack is None:
        raise RuntimeError("skill_pack_missing_after_module_uninstall")
    return {
        "skill_id": normalized_skill_id,
        "module_id": normalized_module_id,
        "pack": updated_pack.summary(),
        "affected_project_count": len(affected_project_ids),
        "affected_project_ids": affected_project_ids,
    }


def import_skill_pack_from_path(source_path: str | Path, root: Path | None = None) -> SkillPack:
    source = Path(source_path).resolve()
    pack = load_skill_pack(source)
    base = root or skill_packs_root()
    base.mkdir(parents=True, exist_ok=True)
    target = base / pack.skill_id
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    return load_skill_pack(target)


MAX_SKILL_ZIP_BYTES = 20 * 1024 * 1024
MAX_SKILL_ZIP_MEMBERS = 2000
MAX_SKILL_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


def import_skill_pack_from_zip(zip_bytes: bytes, root: Path | None = None) -> SkillPack:
    if len(zip_bytes) > MAX_SKILL_ZIP_BYTES:
        raise ValueError("skill_pack_zip_too_large")
    base = root or skill_packs_root()
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "skill.zip"
        zip_path.write_bytes(zip_bytes)
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_SKILL_ZIP_MEMBERS:
                raise ValueError("skill_pack_zip_too_many_members")
            if sum(info.file_size for info in infos) > MAX_SKILL_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError("skill_pack_zip_uncompressed_too_large")
            archive.extractall(tmp_path / "unzipped")
        candidates = [path for path in (tmp_path / "unzipped").iterdir() if path.is_dir()]
        source = candidates[0] if len(candidates) == 1 and (candidates[0] / "SKILL.md").exists() else tmp_path / "unzipped"
        return import_skill_pack_from_path(source, root=base)


def skill_pack_prompt_context(
    skill_ids: list[str],
    *,
    enabled_module_ids: list[str] | None = None,
    purpose: str | None = None,
    include_examples: bool = False,
    genre_id: str = "",
    max_chars_per_pack: int = 5000,
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    selected_module_keys = None if enabled_module_ids is None else {str(item).strip() for item in enabled_module_ids}
    for skill_id in skill_ids:
        pack = get_skill_pack(skill_id)
        if pack is None:
            continue
        module_summaries = []
        root_selected = selected_module_keys is None or skill_module_key(pack.skill_id, "root") in selected_module_keys
        root_skill = (
            extract_skill_instructions(
                pack.root_content,
                limit=max(0, min(1000, max_chars_per_pack)),
                include_examples=include_examples,
                genre_id=genre_id,
            )
            if root_selected
            else ""
        )
        used_chars = len(root_skill)
        for module in pack.modules:
            if selected_module_keys is not None and skill_module_key(pack.skill_id, module.module_id) not in selected_module_keys:
                continue
            if purpose and purpose not in module.purposes and "general" not in module.purposes:
                continue
            if used_chars >= max_chars_per_pack:
                break
            remaining = max_chars_per_pack - used_chars
            instructions = extract_skill_instructions(
                module.content,
                limit=max(0, min(1000, remaining)),
                include_examples=include_examples,
                genre_id=genre_id,
            )
            content = instructions
            used_chars += len(content)
            module_summaries.append(
                {
                    "module_id": module.module_id,
                    "title": module.title,
                    "description": module.description,
                    "summary": _plain_summary(instructions),
                    "purposes": module.purposes,
                    "instructions": instructions,
                    "content": content,
                    "relative_path": module.relative_path,
                }
            )
        if purpose and not module_summaries and not root_skill:
            continue
        contexts.append(
            {
                "skill_id": pack.skill_id,
                "name": pack.name,
                "version": pack.version,
                "description": pack.description,
                "purpose": purpose or "all",
                "root_skill": root_skill,
                "modules": module_summaries,
            }
        )
    return contexts
