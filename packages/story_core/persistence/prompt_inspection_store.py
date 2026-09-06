from __future__ import annotations

import json
from typing import Any

from packages.story_core.models import StoryState
from packages.story_core.prompt_templates import prompt_template_scope
from packages.story_core.skill_packs import (
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
    skill_pack_prompt_context,
)
from packages.story_core.web_game_economy import normalize_legacy_economy_prompt_value
from packages.story_core.writing_taskbook import format_taskbook_brief_section


class PromptInspectionStoreMixin:
    """Rebuild prompt previews and expose the context modules used by a chapter."""

    def _prompt_plan_from_chapter(self, chapter: dict[str, Any]) -> dict[str, Any]:
        plan: dict[str, Any] = {}
        for key in (
            "character_moves",
            "chapter_intent",
            "event_plan",
            "memory_constraints",
            "chapter_seed",
            "simulation_plan",
            "world_events",
            "scene_cards",
            "style_guidance",
            "governance",
            "writing_taskbook",
        ):
            value = chapter.get(key)
            if value not in (None, "", [], {}):
                plan[key] = value
        return plan

    @staticmethod
    def _prompt_entry(
        *,
        key: str,
        title: str,
        agent: str,
        stage: str,
        content: str,
        source: str,
        description: str = "",
        module_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        text = str(content or "")
        return {
            "key": key,
            "title": title,
            "agent": agent,
            "stage": stage,
            "source": source,
            "description": description,
            "content": text,
            "chars": len(text),
            "module_keys": list(module_keys or []),
        }

    @staticmethod
    def _prompt_review_payload(review: Any) -> dict[str, Any]:
        if not isinstance(review, dict):
            return {}
        nested = review.get("writing_review") if isinstance(review.get("writing_review"), dict) else None
        if nested:
            merged = dict(nested)
            for key in ("ok", "pass", "issues", "revision_plan", "scores"):
                if key in review and key not in merged:
                    merged[key] = review[key]
            return merged
        return review

    def _slim_prompt_preview_value(self, value: Any, *, depth: int = 0) -> Any:
        if depth > 4:
            return self._compact_text(value, 160)
        if isinstance(value, str):
            return self._compact_text(value, 180)
        if isinstance(value, list):
            return [self._slim_prompt_preview_value(item, depth=depth + 1) for item in value[:8]]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if item in (None, "", [], {}):
                    continue
                result[str(key)] = self._slim_prompt_preview_value(item, depth=depth + 1)
            return result
        return value

    def _compact_prompt_preview_packet(self, packet: Any) -> dict[str, Any]:
        if not isinstance(packet, dict):
            return {}

        state = packet.get("state") if isinstance(packet.get("state"), dict) else {}
        outline_context = packet.get("outline_context") if isinstance(packet.get("outline_context"), dict) else {}
        chapter_outline = outline_context.get("chapter") if isinstance(outline_context.get("chapter"), dict) else {}
        characters = packet.get("character_cards") if isinstance(packet.get("character_cards"), list) else []
        if not characters:
            characters = state.get("characters") if isinstance(state.get("characters"), list) else []

        loaded_skill_modules: dict[tuple[str, str], dict[str, Any]] = {}
        skill_context = packet.get("skill_context") if isinstance(packet.get("skill_context"), dict) else {}
        for purpose, packs in skill_context.items():
            if not isinstance(packs, list):
                continue
            for pack in packs:
                if not isinstance(pack, dict):
                    continue
                skill_id = str(pack.get("skill_id") or pack.get("name") or "").strip()
                modules = pack.get("modules") if isinstance(pack.get("modules"), list) else []
                if not modules and pack.get("root_skill"):
                    modules = [{"module_id": "root", "title": "根模块"}]
                for module in modules:
                    if not isinstance(module, dict):
                        continue
                    module_id = str(module.get("module_id") or "root").strip()
                    key = (skill_id, module_id)
                    item = loaded_skill_modules.setdefault(
                        key,
                        {
                            "skill_id": skill_id,
                            "module_id": module_id,
                            "title": str(module.get("title") or module_id).strip(),
                            "purposes": [],
                        },
                    )
                    if purpose not in item["purposes"]:
                        item["purposes"].append(purpose)

        preview = {
            "schema_version": packet.get("schema_version"),
            "target_chapter": packet.get("target_chapter"),
            "target_chars": self._slim_prompt_preview_value(packet.get("target_chars")),
            "acceptance_chars": self._slim_prompt_preview_value(packet.get("acceptance_chars")),
            "scene_kind": packet.get("scene_kind"),
            "instruction": self._compact_text(packet.get("instruction"), 260),
            "hard_locks": [self._compact_text(item, 160) for item in packet.get("hard_locks", [])[:10]],
            "scene_cards": self._slim_prompt_preview_value(packet.get("scene_cards", [])[:6]),
            "chapter_outline": self._slim_prompt_preview_value(chapter_outline),
            "characters": [
                {
                    "name": item.get("name"),
                    "role": item.get("role"),
                    "location": self._compact_text(item.get("location"), 80),
                    "goal": self._compact_text(item.get("goal"), 140),
                }
                for item in characters[:6]
                if isinstance(item, dict)
            ],
            "title_contract": self._slim_prompt_preview_value(packet.get("title_contract")),
            "style_rules": [self._compact_text(item, 180) for item in packet.get("style_rules", [])[:6]],
            "loaded_skill_modules": list(loaded_skill_modules.values()),
            "note": "这里只显示本章执行约束；完整上下文由其他模块展示，完整写作包仍由 writing_packet 接口返回。",
        }
        return {key: value for key, value in preview.items() if value not in (None, "", [], {})}

    def prompt_preview(self, chapter_number: int | None = None) -> dict[str, Any]:
        with prompt_template_scope(self.prompt_template_object, self.prompt_template_source):
            return self._prompt_preview(chapter_number)

    def _prompt_preview(self, chapter_number: int | None = None) -> dict[str, Any]:
        from packages.story_core.orchestrator import (
            StoryOrchestrator,
            _chapter_char_count,
            _genre_context_for_prompt,
            _render_compression_length_prompt,
            _render_expansion_length_prompt,
            _render_polish_length_prompt,
            _review_context_facts,
            _story_snapshot,
        )
        from packages.story_core.prompt_modules import modules_for_stage, prompt_module_catalog
        from packages.story_core.genre_stages.registry import genre_stage_profile_for

        numbers = self.chapter_numbers()
        latest_number = numbers[-1] if numbers else 0
        state = self.state()
        project = self.project()
        game_context = self._is_game_story_payload(project, state)
        target = int(chapter_number or state.get("current_chapter") or latest_number or 1)
        chapter: dict[str, Any] = {}
        try:
            chapter = self.chapter(target)
        except FileNotFoundError:
            chapter = {}

        state_before_chapter = self._generation_state_for_target(dict(state), target)
        direction_payload = self._story_state_payload_for_direction(
            state_before_chapter,
            project,
            target,
        )
        story = StoryState.model_validate(direction_payload)
        profile = genre_stage_profile_for(story)
        orchestrator = StoryOrchestrator()
        writing_packet, _, _ = self._build_writing_packet(target)
        plan = self._prompt_plan_from_chapter(chapter)
        plan["scene_cards"] = writing_packet.get("scene_cards", [])
        if isinstance(writing_packet.get("power_system"), dict):
            plan["power_system"] = writing_packet["power_system"]
        body = str(chapter.get("body") or "")
        review = chapter.get("quality_report") if isinstance(chapter.get("quality_report"), dict) else {}
        if not review and chapter:
            try:
                review = self.review(target)
            except FileNotFoundError:
                review = {}
        review = self._prompt_review_payload(review)
        core_context = _story_snapshot(story)
        writer_context = orchestrator._build_writer_context(story, target, plan)
        character_context = profile.prepare_writer_context(context=writer_context).character_context
        genre_context = _genre_context_for_prompt(story, target, plan)
        modules: list[dict[str, Any]] = [
            self._prompt_entry(
                key="core_context",
                title="核心上下文模块",
                agent="context",
                stage="核心上下文",
                content=json.dumps(core_context, ensure_ascii=False, indent=2),
                source="orchestrator._story_snapshot",
                description="主线、世界事实、账本、最近记忆和活世界信号；不包含完整人物角色卡。",
            ),
            self._prompt_entry(
                key="character_context",
                title="本章人物模块",
                agent="context",
                stage="人物角色卡",
                content=json.dumps(character_context, ensure_ascii=False, indent=2),
                source="orchestrator._character_context_for_prompt",
                description="按本章计划提取出场人物的角色卡；不是全量人物库。",
            ),
            self._prompt_entry(
                key="genre_context",
                title="题材写法模块",
                agent="context",
                stage="题材写法",
                content=json.dumps(genre_context, ensure_ascii=False, indent=2),
                source="orchestrator._genre_context_for_prompt",
                description="按项目题材单独选择写法。当前网游项目加载网游模块，其他题材加载对应模块。",
            ),
        ]
        enabled_skill_ids = resolve_enabled_skill_ids(project, state)
        enabled_skill_module_ids = resolve_enabled_skill_module_ids(project, state)
        for purpose, title in (
            ("writer", "正文写作 Skill"),
            ("dialogue", "对话 Skill"),
            ("style", "风格 Skill"),
            ("genre", "题材 Skill"),
            ("continuity", "连续性 Skill"),
            ("reviewer", "审稿 Skill"),
        ):
            skill_context = skill_pack_prompt_context(
                enabled_skill_ids,
                enabled_module_ids=enabled_skill_module_ids,
                purpose=purpose,
                max_chars_per_pack=2600,
            )
            if not skill_context:
                continue
            modules.append(
                self._prompt_entry(
                    key=f"skill_context_{purpose}",
                    title=title,
                    agent="context",
                    stage="Skill",
                    content=json.dumps(skill_context, ensure_ascii=False, indent=2),
                    source=f"skill_packs.enabled_skill_ids.{purpose}",
                    description="按用途裁剪后的本地 skill 包内容；只在相关阶段读取。",
                )
            )
        if isinstance(review, dict) and review:
            modules.append(
                self._prompt_entry(
                    key="review_context",
                    title="审稿报告模块",
                    agent="review",
                    stage="审稿报告",
                    content=json.dumps(review, ensure_ascii=False, indent=2),
                    source="chapter.quality_report",
                    description="改稿阶段才读取的审稿问题和修复清单。",
                )
            )
        packet_preview = self._compact_prompt_preview_packet(writing_packet)
        if isinstance(writing_packet.get("power_system"), dict):
            packet_preview["power_system"] = self._slim_prompt_preview_value(
                writing_packet["power_system"]
            )
        modules.append(
            self._prompt_entry(
                key="packet_context",
                title="写作包预览模块",
                agent="codex",
                stage="写作包",
                content=json.dumps(packet_preview, ensure_ascii=False, indent=2),
                source="file_project_store.writing_packet_compact_preview",
                description="给人工/Codex查看的压缩写作包；完整写作包仍由写作包接口返回。",
            )
        )

        prompts: list[dict[str, Any]] = [
            self._prompt_entry(
                key="director_plan",
                title="章节规划补全 Prompt",
                agent="director",
                stage="剧情计划生成",
                content=orchestrator._render_plan_prompt(story, target),
                source="rebuilt_from_state_before_chapter",
                description="生成 event_plan、chapter_intent、scene_cards 等结构化剧情计划。",
                module_keys=["core_context", "outline_context"],
            ),
            self._prompt_entry(
                key="writer_body",
                title="整章正文 Prompt",
                agent="writer",
                stage="整章正文生成",
                content=orchestrator._render_body_prompt(story, target, plan),
                source="rebuilt_from_chapter_plan",
                description="整章正文实际提示词，按输出要求、本章方向、本章事实、出场人物和正文写法五块装配。",
                module_keys=[
                    "core_context",
                    "outline_context",
                    "chapter_plan",
                    "character_context",
                    "genre_context",
                    "style_context",
                    "skill_context_writer",
                    "skill_context_dialogue",
                    "skill_context_style",
                    "skill_context_genre",
                    "writing_taskbook",
                ],
            ),
        ]

        taskbook = plan.get("writing_taskbook")
        if isinstance(taskbook, dict):
            taskbook_module = self._prompt_entry(
                key="writing_taskbook",
                title="本章方向模块",
                agent="context",
                stage="本章方向",
                content=format_taskbook_brief_section(taskbook),
                source="chapter.writing_taskbook",
                description="只保留本章目标、场面推进和收束，不重复通用风格规则。",
            )
            modules.append(taskbook_module)
            prompts.append(
                self._prompt_entry(
                    key="writing_taskbook",
                    title="写作任务书 Prompt 片段",
                    agent="writer",
                    stage="写作任务书",
                    content=taskbook_module["content"],
                    source="chapter.writing_taskbook",
                    description="整章正文读取的场景任务、风格合同和场面写法模板。",
                    module_keys=["writing_taskbook"],
                )
            )

        if body.strip():
            source_body_placeholder = f"[原正文由 source_body 注入；面板不展示正文全文；当前正文 {len(body)} 字。]"
            chapter_seed = plan.get("chapter_seed") if isinstance(plan.get("chapter_seed"), dict) else {}
            expansion_prompt = _render_expansion_length_prompt(
                story,
                source_body=source_body_placeholder,
                chapter_number=target,
                event_plan=plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {},
                world_facts=_review_context_facts(story),
                source_chars_override=_chapter_char_count(body),
            )
            compression_prompt = _render_compression_length_prompt(
                story,
                source_body=source_body_placeholder,
                chapter_number=target,
                event_plan=plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {},
                world_facts=_review_context_facts(story),
                outline_anchor=chapter_seed.get("outline_anchor"),
            )
            polish_prompt = _render_polish_length_prompt(
                story,
                source_body=source_body_placeholder,
                chapter_number=target,
                event_plan=plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {},
                world_facts=_review_context_facts(story),
            )
            prompts.extend(
                [
                    self._prompt_entry(
                        key="revision",
                        title="审稿改稿 Prompt",
                        agent="writer",
                        stage="审稿改稿",
                        content=orchestrator._render_revision_prompt(
                            story,
                            target,
                            source_body_placeholder,
                            plan,
                            review if isinstance(review, dict) else {},
                        ),
                        source="rebuilt_from_chapter_body_and_review",
                        description="章节未通过写作审稿时，用于自动改稿的完整提示词。",
                        module_keys=["core_context", "character_context", "genre_context", "writing_taskbook", "review_context"],
                    ),
                    self._prompt_entry(
                        key="expansion",
                        title="章节扩写 Prompt",
                        agent="writer",
                        stage="章节扩写",
                        content=expansion_prompt,
                        source="rebuilt_conditional_prompt",
                        description="正文低于目标篇幅时触发。",
                        module_keys=["source_body"],
                    ),
                    self._prompt_entry(
                        key="compression",
                        title="章节压缩 Prompt",
                        agent="writer",
                        stage="章节压缩",
                        content=compression_prompt,
                        source="rebuilt_conditional_prompt",
                        description="正文超过目标篇幅时触发。",
                        module_keys=["source_body"],
                    ),
                    self._prompt_entry(
                        key="polish",
                        title="章节润色 Prompt",
                        agent="writer",
                        stage="章节润色",
                        content=polish_prompt,
                        source="rebuilt_conditional_prompt",
                        description="正文篇幅合适时改善表达，不改变剧情事实。",
                        module_keys=["source_body"],
                    ),
                ]
            )

        prompts.append(
            self._prompt_entry(
                key="review_agents",
                title="读者/编辑/审稿 Agent 说明",
                agent="review",
                stage="质量审稿",
                content="\n".join(
                    [
                        "读者 agent、编辑 agent、审稿 agent 当前主要读取章节正文和质量报告执行本地规则/函数检查。",
                        "它们不是独立调用 LLM 的隐藏提示词；如果后续接入 LLM 审稿，应把对应 prompt 也写入本接口。",
                    ]
                ),
                source="local_rule_based_review",
                description="说明为什么这里没有额外隐藏 prompt。",
                module_keys=["review_context"],
            )
        )

        artifact_stages = {
            "director_plan": "director",
            "writer_body": "writer",
            "writing_taskbook": "writer",
            "revision": "revision",
            "expansion": "length",
            "compression": "length",
            "polish": "length",
            "review_agents": "review",
        }
        prompt_entry_ids = {id(entry) for entry in prompts}
        for entry in [*modules, *prompts]:
            content = normalize_legacy_economy_prompt_value(
                str(entry.get("content") or ""),
                game_context=game_context,
                chapter_number=target,
            )
            entry["content"] = content
            entry["chars"] = len(content)
            entry["genre_stage_profile"] = profile.profile_id
            genre_stage = (
                artifact_stages.get(str(entry.get("key") or ""), "")
                if id(entry) in prompt_entry_ids
                else ""
            )
            entry["genre_stage"] = genre_stage
            entry["genre_stage_modules"] = list(profile.modules_for(genre_stage))

        return {
            "schema_version": "file-project-prompt-preview/v1",
            "project_id": self.project().get("project_id") or self.root.name,
            "chapter_number": target,
            "chapter_title": chapter.get("chapter_title") or "",
            "source": "rebuilt_from_current_project_files",
            "reconstructed": True,
            "has_chapter": bool(chapter),
            "genre_stage_profile": profile.profile_id,
            "module_catalog": prompt_module_catalog(),
            "stage_modules": {
                stage: [module.key for module in modules_for_stage(stage)]
                for stage in ("planning", "writing", "revision", "validation")
            },
            "modules": modules,
            "prompts": prompts,
        }

    def prompt_context(self, chapter_number: int | None = None) -> dict[str, Any]:
        from packages.story_core.prompt_modules import prompt_module_catalog

        preview = self.prompt_preview(chapter_number)
        available_modules = []
        available_keys: set[str] = set()
        for module in preview.get("modules", []):
            item = dict(module)
            item["available"] = True
            available_modules.append(item)
            available_keys.add(str(item.get("key") or ""))
        for spec in prompt_module_catalog():
            key = str(spec.get("key") or "")
            if not key or key in available_keys or key == "source_body":
                continue
            available_modules.append(
                {
                    "key": key,
                    "title": spec.get("title") or key,
                    "agent": spec.get("owner") or "context",
                    "stage": spec.get("stage") or "context",
                    "source": spec.get("owner") or "context",
                    "description": spec.get("description") or "",
                    "content": "",
                    "chars": 0,
                    "module_keys": list(spec.get("depends_on") or []),
                    "available": False,
                    "reason": "not_provided_for_chapter",
                }
            )
        return {
            "schema_version": "file-project-prompt-context/v1",
            "project_id": preview.get("project_id"),
            "chapter_number": preview.get("chapter_number"),
            "chapter_title": preview.get("chapter_title"),
            "source": "current_project_context",
            "module_catalog": preview.get("module_catalog", []),
            "stage_modules": preview.get("stage_modules", {}),
            "modules": available_modules,
        }
