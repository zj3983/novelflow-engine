"""Prompt module catalog and stage dependencies.

This file describes what each context block is responsible for. It does not
build prose prompts; the orchestrator remains responsible for rendering the
selected data for the target agent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PromptModuleSpec:
    key: str
    title: str
    owner: str
    stage: str
    purpose: str
    description: str
    depends_on: tuple[str, ...] = ()
    role: str = "instruction"
    replaceable: bool = False

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["depends_on"] = list(self.depends_on)
        return payload


MODULES: tuple[PromptModuleSpec, ...] = (
    PromptModuleSpec("core_context", "核心事实", "context", "all", "continuity", "当前主线、世界事实、时间、账本和最近记忆。", role="fact_source"),
    PromptModuleSpec("outline_context", "大纲约束", "outline", "planning", "plot", "总大纲、当前卷方向和本章允许推进的范围。", role="fact_source"),
    PromptModuleSpec("chapter_plan", "本章剧情包", "director", "writing", "plot", "本章目标、冲突、行动顺序、场景卡和章末钩子。", ("core_context", "outline_context")),
    PromptModuleSpec("character_context", "场景人物", "character", "writing", "character", "只提取本章出场人物及当前场景需要的行为和语言侧写。", ("chapter_plan",)),
    PromptModuleSpec("dialogue_context", "对话情绪", "dialogue", "writing", "dialogue", "本场对话的情绪目标、关系限制和台词后的变化。", ("character_context", "chapter_plan")),
    PromptModuleSpec("genre_context", "题材规则", "genre", "writing", "genre", "按小说类型加载的写法和世界表面规则。", role="default_provider", replaceable=True),
    PromptModuleSpec("writing_taskbook", "写作任务书", "writer", "writing", "craft", "把剧情包翻译成正文可执行的场景任务。", ("chapter_plan",)),
    PromptModuleSpec("style_context", "表达方法", "writer", "writing", "style", "白描、口语、节奏和反 AI 表达方法。", role="default_provider", replaceable=True),
    PromptModuleSpec("skill_context_writer", "正文 Skill", "skill", "writing", "writer", "用户启用的正文写作技能。", role="skill", replaceable=True),
    PromptModuleSpec("skill_context_dialogue", "对话 Skill", "skill", "writing", "dialogue", "用户启用的对话技能。", role="skill", replaceable=True),
    PromptModuleSpec("skill_context_style", "风格 Skill", "skill", "writing", "style", "用户启用的风格技能。", role="skill", replaceable=True),
    PromptModuleSpec("skill_context_genre", "题材 Skill", "skill", "writing", "genre", "用户启用的题材技能。", role="skill", replaceable=True),
    PromptModuleSpec("skill_context_continuity", "连续性 Skill", "skill", "validation", "continuity", "用户启用的连续性技能。", role="skill", replaceable=False),
    PromptModuleSpec("skill_context_reviewer", "审稿 Skill", "skill", "review", "reviewer", "用户启用的审稿技能。", role="skill", replaceable=True),
    PromptModuleSpec("review_context", "审稿报告", "reviewer", "revision", "review", "上一版正文的问题和修改清单。"),
    PromptModuleSpec("source_body", "原正文", "writer", "revision", "revision", "需要改写的原正文，只在改稿阶段注入。"),
)

_BY_KEY = {module.key: module for module in MODULES}

STAGE_MODULES: dict[str, tuple[str, ...]] = {
    "planning": ("core_context", "outline_context"),
    "writing": (
        "core_context",
        "outline_context",
        "chapter_plan",
        "character_context",
        "dialogue_context",
        "genre_context",
        "writing_taskbook",
        "style_context",
        "skill_context_writer",
        "skill_context_dialogue",
        "skill_context_style",
        "skill_context_genre",
    ),
    "revision": (
        "core_context",
        "chapter_plan",
        "character_context",
        "dialogue_context",
        "genre_context",
        "writing_taskbook",
        "style_context",
        "review_context",
        "source_body",
        "skill_context_writer",
        "skill_context_dialogue",
        "skill_context_style",
        "skill_context_genre",
        "skill_context_reviewer",
    ),
    "validation": ("core_context", "chapter_plan", "skill_context_continuity"),
}


def get_prompt_module(key: str) -> PromptModuleSpec:
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise KeyError(f"unknown_prompt_module:{key}") from exc


def modules_for_stage(stage: str, *, available: set[str] | None = None) -> list[PromptModuleSpec]:
    keys = STAGE_MODULES.get(stage, ())
    return [get_prompt_module(key) for key in keys if available is None or key in available]


def prompt_module_catalog() -> list[dict[str, object]]:
    return [module.as_dict() for module in MODULES]


def replaceable_slots() -> dict[str, str]:
    """Return the defaults that a selected skill is allowed to replace."""
    return {
        module.purpose: module.key
        for module in MODULES
        if module.role == "default_provider" and module.replaceable
    }
