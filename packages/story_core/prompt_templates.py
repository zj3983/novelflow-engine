"""Source prompt templates and strict placeholder rendering."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from collections.abc import Mapping
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import tempfile


_VARIABLE_PATTERN = re.compile(r"{{([a-z][a-z0-9_]*)}}")
_current_template_resolver: ContextVar[Callable[[str], "PromptTemplate"] | None] = ContextVar(
    "current_prompt_template_resolver",
    default=None,
)
_current_template_source_resolver: ContextVar[Callable[[str], str] | None] = ContextVar(
    "current_prompt_template_source_resolver",
    default=None,
)


@dataclass(frozen=True)
class PromptTemplate:
    key: str
    title: str
    stage: str
    content: str
    required_variables: tuple[str, ...]

    @property
    def version(self) -> str:
        digest = sha256(self.content.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["required_variables"] = list(self.required_variables)
        payload["version"] = self.version
        return payload


_DEFAULT_TEMPLATES: dict[str, PromptTemplate] = {
    "director_generic": PromptTemplate(
        key="director_generic",
        title="章节规划补全（通用）",
        stage="planning",
        content="\n".join(
            [
                "请为中文长篇项目生成本章推演计划，只返回 JSON。",
                "目标章节：第{{chapter_number}}章",
                "章节阶段：{{chapter_phase}}",
                "项目快照：{{project_snapshot}}",
                "本章连续性材料：{{chapter_seed}}",
                "相关角色卡：{{character_cards}}",
                "输出JSON：character_moves；chapter_intent；event_plan。",
                "event_plan包含ordered_actions、chapter_satisfaction、chapter_end_hook、world_reactions、stakes、next_focus；chapter_satisfaction包含core_event、obstacle、visible_payoff、cost、outsider_misread、state_change、next_hook。",
                "chapter_end_hook 使用结构：{type, strength, content}；type 只能是危机钩、悬念钩、渴望钩、反转钩、余韵钩；strength 只能是 strong、medium、weak。",
                "要求：动作具体，焦点明确，事件链短但有效，不要写正文。",
            ]
        ),
        required_variables=("chapter_number", "chapter_phase", "project_snapshot", "chapter_seed", "character_cards"),
    ),
    "director": PromptTemplate(
        key="director",
        title="章节规划补全（网游）",
        stage="planning",
        content="\n".join(
            [
                "网游计划写法：先排出一条玩家行动链；不要只列设定，要让目标、卡点、尝试、消耗、反馈、小进度和下一步都能写成场景。",
                "请为中文网文项目生成本章推演计划，只返回 JSON。",
                "目标章节：第{{chapter_number}}章",
                "章节阶段：{{chapter_phase}}",
                "项目快照：{{project_snapshot}}",
                "本章连续性材料：{{chapter_seed}}",
                "相关角色卡：{{character_cards}}",
                "输出JSON字段：",
                "character_moves: [{name, goal, emotion, action, priority}]；chapter_intent: {chapter_title, cadence, next_focus, primary_conflict, secondary_conflict}。",
                "event_plan: {chapter_title, ordered_actions, chapter_satisfaction, chapter_end_hook, world_reactions, stakes, next_focus}；chapter_satisfaction: {core_event, obstacle, visible_payoff, cost, outsider_misread, state_change, next_hook}。",
                "chapter_end_hook: {type, strength, content}；type为危机钩|悬念钩|渴望钩|反转钩|余韵钩，strength为strong|medium|weak。",
                "只补齐本章行动链，不生成章节摘要、既成事实或账本更新；这些内容必须在正文完成后提取。",
                "活跃角色：{{active_characters}}",
                "计划优先级：先遵守本章连续性材料，再用项目快照补连续性；不要把检查规则复述进计划。",
                "网游连续性：现实姓名、游戏ID、身份、等级、经验、货币、背包、装备耐久、任务进度必须能在 ledger_updates 里对上。",
                "计划必须落成目标、阻碍、行动、代价、可见收益、外人误判和章末下一步；世界反应只能依据玩家/NPC可见痕迹。动作具体，不写正文。",
            ]
        ),
        required_variables=(
            "chapter_number",
            "chapter_phase",
            "project_snapshot",
            "chapter_seed",
            "character_cards",
            "active_characters",
        ),
    ),
    "writer": PromptTemplate(
        key="writer",
        title="整章正文写作",
        stage="writing",
        content="\n\n".join(
            [
                "{{output_section}}",
                "{{chapter_direction}}",
                "{{chapter_facts}}",
                "{{character_context}}",
                "{{prose_method}}",
            ]
        ),
        required_variables=("output_section", "chapter_direction", "chapter_facts", "character_context", "prose_method"),
    ),
    "revision": PromptTemplate(
        key="revision",
        title="审稿改稿",
        stage="revision",
        content="{{body_prompt}}\n\n{{revision_instructions}}\n\n## 原正文\n以下内容只作改稿输入，不复述提示词，不输出修改说明。\n{{source_body}}",
        required_variables=("body_prompt", "revision_instructions", "source_body"),
    ),
    "expansion": PromptTemplate(
        key="expansion",
        title="章节扩写",
        stage="revision",
        content="下面这章正文太短，请在不改变剧情事实和结尾钩子的前提下扩写成完整网文章节。\n目标篇幅：{{target_chars}}。\n{{expansion_focus}}\n只输出扩写后的小说正文，不要解释，不要列大纲。\n原正文：\n{{source_body}}",
        required_variables=("target_chars", "expansion_focus", "source_body"),
    ),
    "compression": PromptTemplate(
        key="compression",
        title="章节压缩",
        stage="revision",
        content="{{opening_line}}\n目标篇幅：{{target_chars}}。\n{{compression_method}}\n{{chapter_scope}}\n只输出压缩后的小说正文，不要解释，不要列大纲。\n原正文：\n{{source_body}}",
        required_variables=("opening_line", "target_chars", "compression_method", "chapter_scope", "source_body"),
    ),
}


def list_default_prompt_templates() -> list[PromptTemplate]:
    return list(_DEFAULT_TEMPLATES.values())


def get_default_prompt_template(key: str) -> PromptTemplate:
    try:
        return _DEFAULT_TEMPLATES[key]
    except KeyError as exc:
        raise KeyError(f"unknown_prompt_template:{key}") from exc


def template_variables(content: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_VARIABLE_PATTERN.findall(content)))


def validate_prompt_template(template: PromptTemplate) -> None:
    variables = set(template_variables(template.content))
    required = set(template.required_variables)
    unknown = variables - required
    if unknown:
        raise ValueError(f"unknown_template_variable:{sorted(unknown)[0]}")
    missing = required - variables
    if missing:
        raise ValueError(f"missing_required_template_variable:{sorted(missing)[0]}")


def render_prompt_template(template: PromptTemplate, values: Mapping[str, str]) -> str:
    validate_prompt_template(template)
    variables = set(template_variables(template.content))
    missing = variables - values.keys()
    if missing:
        raise ValueError(f"missing_template_variable:{sorted(missing)[0]}")
    return _VARIABLE_PATTERN.sub(lambda match: str(values[match.group(1)]), template.content)


def _global_storage_path(storage_path: str | Path | None = None) -> Path:
    if storage_path is not None:
        return Path(storage_path)
    configured = os.getenv("NOVEL_PROMPT_TEMPLATES_PATH", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "prompt-templates" / "templates.json"


def _template_with_content(key: str, content: str) -> PromptTemplate:
    base = get_default_prompt_template(key)
    candidate = PromptTemplate(
        key=base.key,
        title=base.title,
        stage=base.stage,
        content=str(content),
        required_variables=base.required_variables,
    )
    validate_prompt_template(candidate)
    return candidate


def _read_global_overrides(storage_path: str | Path | None = None) -> dict[str, dict[str, str]]:
    path = _global_storage_path(storage_path)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    templates = payload.get("templates", {}) if isinstance(payload, dict) else {}
    return templates if isinstance(templates, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def load_global_prompt_templates(*, storage_path: str | Path | None = None) -> list[PromptTemplate]:
    overrides = _read_global_overrides(storage_path)
    templates: list[PromptTemplate] = []
    for base in list_default_prompt_templates():
        override = overrides.get(base.key, {})
        content = override.get("content") if isinstance(override, dict) else None
        templates.append(_template_with_content(base.key, content) if isinstance(content, str) else base)
    return templates


def get_global_prompt_template(key: str, *, storage_path: str | Path | None = None) -> PromptTemplate:
    try:
        return next(item for item in load_global_prompt_templates(storage_path=storage_path) if item.key == key)
    except StopIteration as exc:
        raise KeyError(f"unknown_prompt_template:{key}") from exc


def get_effective_prompt_template(key: str) -> PromptTemplate:
    resolver = _current_template_resolver.get()
    return resolver(key) if resolver is not None else get_global_prompt_template(key)


def get_effective_prompt_template_source(key: str) -> str:
    resolver = _current_template_source_resolver.get()
    if resolver is not None:
        return str(resolver(key))
    template = get_global_prompt_template(key)
    return "global_default" if template.content == get_default_prompt_template(key).content else "global_override"


@contextmanager
def prompt_template_scope(
    resolver: Callable[[str], PromptTemplate],
    source_resolver: Callable[[str], str] | None = None,
) -> Iterator[None]:
    token = _current_template_resolver.set(resolver)
    source_token = _current_template_source_resolver.set(source_resolver)
    try:
        yield
    finally:
        _current_template_source_resolver.reset(source_token)
        _current_template_resolver.reset(token)


def save_global_prompt_template(
    key: str,
    content: str,
    *,
    storage_path: str | Path | None = None,
) -> PromptTemplate:
    candidate = _template_with_content(key, content)
    path = _global_storage_path(storage_path)
    overrides = _read_global_overrides(path)
    overrides[key] = {
        "content": candidate.content,
        "version": candidate.version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json_atomic(path, {"schema_version": "prompt-templates/v1", "templates": overrides})
    return candidate


def delete_global_prompt_template(key: str, *, storage_path: str | Path | None = None) -> PromptTemplate:
    base = get_default_prompt_template(key)
    path = _global_storage_path(storage_path)
    overrides = _read_global_overrides(path)
    overrides.pop(key, None)
    _write_json_atomic(path, {"schema_version": "prompt-templates/v1", "templates": overrides})
    return base
