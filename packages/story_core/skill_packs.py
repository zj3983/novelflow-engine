from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKILL_PACK_SCHEMA_VERSION = "skill-pack/v1"
DEFAULT_SKILL_PACKS_DIR = Path("data") / "skill-packs"
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


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
                    purposes=infer_skill_purposes(module_id, str(meta.get("name") or ""), str(meta.get("description") or "")),
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


def import_skill_pack_from_zip(zip_bytes: bytes, root: Path | None = None) -> SkillPack:
    base = root or skill_packs_root()
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "skill.zip"
        zip_path.write_bytes(zip_bytes)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(tmp_path / "unzipped")
        candidates = [path for path in (tmp_path / "unzipped").iterdir() if path.is_dir()]
        source = candidates[0] if len(candidates) == 1 and (candidates[0] / "SKILL.md").exists() else tmp_path / "unzipped"
        return import_skill_pack_from_path(source, root=base)


def skill_pack_prompt_context(
    skill_ids: list[str],
    *,
    purpose: str | None = None,
    max_chars_per_pack: int = 5000,
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for skill_id in skill_ids:
        pack = get_skill_pack(skill_id)
        if pack is None:
            continue
        module_summaries = []
        root_skill = pack.root_content[:1800]
        used_chars = len(root_skill)
        for module in pack.modules:
            if purpose and purpose not in module.purposes and "general" not in module.purposes:
                continue
            if used_chars >= max_chars_per_pack:
                break
            remaining = max_chars_per_pack - used_chars
            content = module.content[: max(0, min(remaining, 1800))]
            used_chars += len(content)
            module_summaries.append(
                {
                    "module_id": module.module_id,
                    "title": module.title,
                    "description": module.description,
                    "summary": module.summary,
                    "purposes": module.purposes,
                    "content": content,
                    "relative_path": module.relative_path,
                }
            )
        if purpose and not module_summaries:
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
