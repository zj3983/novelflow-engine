"""Source prompt templates and strict placeholder rendering."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from collections.abc import Mapping
import re


_VARIABLE_PATTERN = re.compile(r"{{([a-z][a-z0-9_]*)}}")


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
        title="导演剧情计划（通用）",
        stage="planning",
        content="\n".join(
            [
                "请为中文长篇项目生成本章推演计划，只返回 JSON。",
                "目标章节：第{{chapter_number}}章",
                "章节阶段：{{chapter_phase}}",
                "项目快照：{{project_snapshot}}",
                "本章连续性材料：{{chapter_seed}}",
                "相关角色卡：{{character_cards}}",
                "输出JSON：character_moves；chapter_intent；event_plan；memory_constraints；chapter_summary。",
                "event_plan包含ordered_actions、chapter_satisfaction、chapter_end_hook、world_reactions、stakes、next_focus；chapter_satisfaction包含core_event、obstacle、visible_payoff、cost、outsider_misread、state_change、next_hook。",
                "chapter_end_hook 使用结构：{type, strength, content}；type 只能是危机钩、悬念钩、渴望钩、反转钩、余韵钩；strength 只能是 strong、medium、weak。",
                "要求：动作具体，焦点明确，事件链短但有效，不要写正文。",
            ]
        ),
        required_variables=("chapter_number", "chapter_phase", "project_snapshot", "chapter_seed", "character_cards"),
    ),
    "director": PromptTemplate(
        key="director",
        title="导演剧情计划（网游）",
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
                "memory_constraints: {must_keep_facts, unresolved_threads, author_constraints, current_focus, ledger_updates}；chapter_summary: {summary, facts, unresolved_threads, next_focus, chapter_title}。",
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
        content="下面这章正文超过目标篇幅，请在不改变剧情事实、人物选择、游戏账本、结尾钩子的前提下压缩。\n目标篇幅：{{target_chars}}。\n{{compression_method}}\n只输出压缩后的小说正文，不要解释，不要列大纲。\n原正文：\n{{source_body}}",
        required_variables=("target_chars", "compression_method", "source_body"),
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
    unknown = set(template_variables(template.content)) - set(template.required_variables)
    if unknown:
        raise ValueError(f"unknown_template_variable:{sorted(unknown)[0]}")


def render_prompt_template(template: PromptTemplate, values: Mapping[str, str]) -> str:
    validate_prompt_template(template)
    variables = set(template_variables(template.content))
    missing = variables - values.keys()
    if missing:
        raise ValueError(f"missing_template_variable:{sorted(missing)[0]}")
    return _VARIABLE_PATTERN.sub(lambda match: str(values[match.group(1)]), template.content)
