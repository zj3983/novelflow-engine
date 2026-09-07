from __future__ import annotations

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


def patch_character_profiles() -> None:
    path = "packages/story_core/character_profiles.py"
    text = read(path)
    if "missing:story_drive.hidden_matters" in text:
        return
    text = replace_once(
        text,
        '        "placeholder",\n    }\n)',
        '        "placeholder",\n        "冷静聪明谨慎",\n        "冷静谨慎",\n        "观察后行动",\n        "不善言辞",\n    }\n)',
        "generic personality vocabulary",
    )
    text = replace_once(
        text,
        '("story_drive", "failure_stakes"),\n)',
        '("story_drive", "failure_stakes"),\n    ("story_drive", "main_conflict_reason"),\n)',
        "conflict reason quality field",
    )
    anchor = '\n    return issues\n\n\ndef character_profile_completeness'
    role_rules = '''

    if status != "stub":
        function_required: list[tuple[str, str]] = []
        if narrative_function == "protagonist":
            function_required = [
                ("identity_profile", "origin"),
                ("performance_profile", "speech_style"),
                ("performance_profile", "action_style"),
            ]
        elif narrative_function == "stage_antagonist":
            function_required = [
                ("current_life_profile", "authority_scope"),
                ("story_drive", "main_conflict_reason"),
                ("performance_profile", "action_style"),
            ]
        elif narrative_function == "long_term_antagonist":
            function_required = [
                ("current_life_profile", "authority_scope"),
                ("story_drive", "long_term_goal"),
                ("story_drive", "main_conflict_reason"),
            ]
        elif importance in {"supporting", "minor"}:
            function_required = [("identity_profile", "current_identity")]
        for section, field in function_required:
            if not _profile_field(card, section, field):
                issues.append(f"missing:{section}.{field}")

        if narrative_function in {"protagonist", "long_term_antagonist"}:
            drive = card.get("story_drive")
            hidden = drive.get("hidden_matters", []) if isinstance(drive, dict) else []
            if not any(str(item).strip() for item in hidden):
                issues.append("missing:story_drive.hidden_matters")

        if not any(
            isinstance(item, dict) and str(item.get("target") or "").strip()
            for item in card.get("relationship_notes", [])
        ):
            issues.append("missing:relationship_notes")
        if importance in {"core", "major"} and len(
            [item for item in card.get("dialogue_examples", []) if str(item).strip()]
        ) < 2:
            issues.append("missing:dialogue_examples")
'''
    text = replace_once(
        text,
        anchor,
        role_rules + '\n    return issues\n\n\ndef character_profile_completeness',
        "role-specific quality insertion",
    )
    generic_end = '    return compact in _GENERIC_CHARACTER_CONTENT\n\n\ndef character_profile_quality_issues'
    text = replace_once(
        text,
        generic_end,
        '    return compact in _GENERIC_CHARACTER_CONTENT\n\n\ndef is_generic_character_content(value: Any) -> bool:\n    """Public predicate used by seed-level quality gates."""\n\n    return _looks_generic_character_content(value)\n\n\ndef character_profile_quality_issues',
        "public generic helper",
    )
    write(path, text)


def patch_outline_planning() -> None:
    path = "packages/story_core/outline_planning.py"
    text = read(path)
    if "def _migrate_legacy_taxonomy(cls, value):" in text:
        return
    text = replace_once(
        text,
        "from pydantic import BaseModel, ConfigDict, Field\n",
        "from pydantic import BaseModel, ConfigDict, Field, model_validator\n",
        "outline planning pydantic import",
    )
    old_import = '''from packages.story_core.character_profiles import (
    BackgroundProfile,
    CurrentLifeProfile,
    IdentityProfile,
    RelationshipNote,
    StoryDriveProfile,
    is_placeholder_character_name,
)
'''
    new_import = '''from packages.story_core.character_profiles import (
    BackgroundProfile,
    CharacterImportance,
    CharacterNarrativeFunction,
    CharacterProfileStatus,
    CurrentLifeProfile,
    IdentityProfile,
    RelationshipNote,
    StoryDriveProfile,
    character_profile_completeness,
    infer_character_profile_status,
    infer_character_taxonomy,
    is_placeholder_character_name,
)
'''
    text = replace_once(text, old_import, new_import, "outline planning character imports")
    old_class = '''class PlanningCharacterCard(_PlanningModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    character_tier: CharacterTier
    first_appearance: int = Field(default=0, ge=0)
    identity_profile: IdentityProfile
    background_profile: BackgroundProfile
    current_life_profile: CurrentLifeProfile
    story_drive: StoryDriveProfile
    performance_profile: CharacterPerformanceProfile = Field(default_factory=CharacterPerformanceProfile)
    dialogue_examples: list[str] = Field(min_length=2, max_length=3)
    relationship_notes: list[RelationshipNote] = Field(default_factory=list)
'''
    new_class = '''class PlanningCharacterCard(_PlanningModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    character_tier: CharacterTier
    importance: CharacterImportance
    narrative_function: CharacterNarrativeFunction
    profile_status: CharacterProfileStatus
    profile_completeness: int = Field(ge=0, le=100)
    first_appearance: int = Field(default=0, ge=0)
    identity_profile: IdentityProfile
    background_profile: BackgroundProfile
    current_life_profile: CurrentLifeProfile
    story_drive: StoryDriveProfile
    performance_profile: CharacterPerformanceProfile = Field(default_factory=CharacterPerformanceProfile)
    dialogue_examples: list[str] = Field(default_factory=list, max_length=3)
    relationship_notes: list[RelationshipNote] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_taxonomy(cls, value):
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        importance, narrative_function = infer_character_taxonomy(migrated)
        migrated.setdefault("importance", importance)
        migrated.setdefault("narrative_function", narrative_function)
        migrated.setdefault("profile_status", infer_character_profile_status(migrated))
        migrated.setdefault("profile_completeness", character_profile_completeness(migrated))
        return migrated
'''
    text = replace_once(text, old_class, new_class, "PlanningCharacterCard model")
    write(path, text)


def patch_models() -> None:
    path = "packages/story_core/models.py"
    text = read(path)
    if "def _migrate_character_taxonomy(cls, value):" in text:
        return
    old_import = '''from packages.story_core.character_profiles import (
    BackgroundProfile,
    CurrentLifeProfile,
    IdentityProfile,
    RelationshipNote,
    StoryDriveProfile,
)
'''
    new_import = '''from packages.story_core.character_profiles import (
    BackgroundProfile,
    CharacterImportance,
    CharacterNarrativeFunction,
    CharacterProfileStatus,
    CurrentLifeProfile,
    IdentityProfile,
    RelationshipNote,
    StoryDriveProfile,
    character_profile_completeness,
    infer_character_profile_status,
    infer_character_taxonomy,
)
'''
    text = replace_once(text, old_import, new_import, "CharacterState imports")
    text = replace_once(
        text,
        '    character_tier: str = ""\n    first_appearance: int = Field(default=0, ge=0)\n',
        '    character_tier: str = ""\n    importance: CharacterImportance\n    narrative_function: CharacterNarrativeFunction\n    profile_status: CharacterProfileStatus\n    profile_completeness: int = Field(ge=0, le=100)\n    first_appearance: int = Field(default=0, ge=0)\n',
        "CharacterState taxonomy fields",
    )
    migration = '''    @model_validator(mode="before")
    @classmethod
    def _migrate_character_taxonomy(cls, value):
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        importance, narrative_function = infer_character_taxonomy(migrated)
        migrated.setdefault("importance", importance)
        migrated.setdefault("narrative_function", narrative_function)
        migrated.setdefault("profile_status", infer_character_profile_status(migrated))
        migrated.setdefault("profile_completeness", character_profile_completeness(migrated))
        return migrated

'''
    text = replace_once(
        text,
        '    @field_validator("current_state", mode="before")\n',
        migration + '    @field_validator("current_state", mode="before")\n',
        "CharacterState migration validator",
    )
    write(path, text)


def patch_generation() -> None:
    path = "packages/story_core/outline_planning_generation.py"
    text = read(path)
    if "def _failed_character_names_from_quality_error(error: str)" in text:
        return
    text = replace_once(
        text,
        "from pydantic import BaseModel, ConfigDict, Field, ValidationError\n",
        "from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator\n",
        "generation pydantic import",
    )
    old_import = '''from packages.story_core.character_profiles import (
    character_profile_quality_issues,
    find_character_homogeneity_issues,
    normalize_speech_style_for_writing,
)
'''
    new_import = '''from packages.story_core.character_profiles import (
    CharacterImportance,
    CharacterNarrativeFunction,
    CharacterProfileStatus,
    character_profile_quality_issues,
    find_character_homogeneity_issues,
    infer_character_taxonomy,
    is_generic_character_content,
    normalize_speech_style_for_writing,
)
'''
    text = replace_once(text, old_import, new_import, "generation character imports")
    text = replace_once(
        text,
        'class GeneratedCharacterRoster(_PlanningInput):\n    characters: list["PlanningCharacterSeed"]\n',
        'class GeneratedCharacterRoster(_PlanningInput):\n    characters: list["PlanningCharacterSeed"]\n\n\nclass GeneratedCharacterCardRepair(_PlanningInput):\n    characters: list[PlanningCharacterCard]\n',
        "direct repair schema",
    )
    seed_start = text.index("class PlanningCharacterSeed(_PlanningInput):")
    seed_end = text.index("\n\n_CHINESE_DIGITS", seed_start)
    new_seed = '''class PlanningCharacterSeed(_PlanningInput):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    character_tier: CharacterTier
    importance: CharacterImportance
    narrative_function: CharacterNarrativeFunction
    profile_status: CharacterProfileStatus
    first_appearance: int = Field(default=0, ge=0)
    age: int | None = Field(default=None, ge=0)
    origin: str = Field(default="", max_length=300)
    current_identity: str = Field(min_length=1, max_length=200)
    occupation: str = Field(default="", max_length=120)
    authority_scope: str = Field(default="", max_length=300)
    immediate_problem: str = Field(default="", max_length=300)
    immediate_goal: str = Field(default="", max_length=300)
    motivation: str = Field(default="", max_length=300)
    long_term_goal: str = Field(default="", max_length=300)
    failure_stakes: str = Field(default="", max_length=300)
    main_conflict_reason: str = Field(default="", max_length=300)
    personality: str = Field(default="", max_length=300)
    speech_style: str = Field(default="", max_length=200)
    action_style: str = Field(default="", max_length=200)
    emotional_trigger: str = Field(default="", max_length=200)
    decision_rule: str = Field(default="", max_length=200)
    hidden_matter: str = Field(default="", max_length=300)
    dialogue_examples: list[str] = Field(default_factory=list, max_length=2)
    relationship_notes: list[PlanningRelationshipSeed] = Field(default_factory=list, max_length=6)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_seed(cls, value):
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        importance, narrative_function = infer_character_taxonomy(migrated)
        migrated.setdefault("importance", importance)
        migrated.setdefault("narrative_function", narrative_function)
        effective_function = str(migrated.get("narrative_function") or narrative_function)
        expected_tier = {
            "protagonist": "protagonist",
            "stage_antagonist": "stage_antagonist",
            "long_term_antagonist": "long_term_antagonist",
        }.get(effective_function, "supporting")
        if "narrative_function" in value or "importance" in value:
            migrated["character_tier"] = expected_tier
        else:
            migrated.setdefault("character_tier", expected_tier)
        if not str(migrated.get("profile_status") or "").strip():
            detail_fields = (
                "current_identity",
                "immediate_problem",
                "immediate_goal",
                "motivation",
                "failure_stakes",
                "speech_style",
                "action_style",
            )
            enough_detail = all(str(migrated.get(field) or "").strip() for field in detail_fields)
            migrated["profile_status"] = (
                "ready" if enough_detail and migrated.get("relationship_notes") else "stub"
            )
        return migrated
'''
    text = text[:seed_start] + new_seed + text[seed_end:]
    text = replace_once(
        text,
        '        seed.long_term_goal,\n        seed.hidden_matter,\n',
        '        seed.long_term_goal,\n        seed.main_conflict_reason,\n        seed.hidden_matter,\n',
        "seed chronology conflict reason",
    )
    text = replace_once(
        text,
        '            "character_tier": seed.character_tier,\n            "first_appearance": seed.first_appearance,\n',
        '            "character_tier": seed.character_tier,\n            "importance": seed.importance,\n            "narrative_function": seed.narrative_function,\n            "profile_status": seed.profile_status,\n            "first_appearance": seed.first_appearance,\n',
        "expanded seed taxonomy",
    )
    text = replace_once(
        text,
        '                "failure_stakes": seed.failure_stakes,\n                "hidden_matters": [seed.hidden_matter] if seed.hidden_matter else [],\n',
        '                "failure_stakes": seed.failure_stakes,\n                "main_conflict_reason": seed.main_conflict_reason,\n                "hidden_matters": [seed.hidden_matter] if seed.hidden_matter else [],\n',
        "expanded conflict reason",
    )
    old_validate = '''def _validate_character_card_roster_quality(
    cards: list[Any],
    *,
    existing_names: set[str] | None = None,
) -> None:
    issues = _character_card_roster_quality_issues(
        cards,
        existing_names=existing_names,
    )
    if not issues:
        return
    detail = ";".join(
        f"{name}[{','.join(values)}]" for name, values in sorted(issues.items())
    )
    raise ValueError(f"character_profile_quality_failed:{detail}")


def _validate_character_seed_roster_quality(
    seeds: list[PlanningCharacterSeed],
    *,
    existing_names: set[str] | None = None,
) -> None:
    _validate_character_card_roster_quality(
        [_expand_character_seed(seed) for seed in seeds],
        existing_names=existing_names,
    )
'''
    new_validate = '''def _raise_character_quality_issues(issues: dict[str, list[str]]) -> None:
    if not issues:
        return
    detail = ";".join(
        f"{name}[{','.join(dict.fromkeys(values))}]"
        for name, values in sorted(issues.items())
    )
    raise ValueError(f"character_profile_quality_failed:{detail}")


def _validate_character_card_roster_quality(
    cards: list[Any],
    *,
    existing_names: set[str] | None = None,
) -> None:
    _raise_character_quality_issues(
        _character_card_roster_quality_issues(cards, existing_names=existing_names)
    )


def _validate_character_seed_roster_quality(
    seeds: list[PlanningCharacterSeed],
    *,
    existing_names: set[str] | None = None,
) -> None:
    cards = [_expand_character_seed(seed) for seed in seeds]
    issues = _character_card_roster_quality_issues(cards, existing_names=existing_names)
    for seed in seeds:
        if seed.importance == "core" and seed.profile_status != "ready":
            issues.setdefault(seed.name, []).append("core_requires_ready")
        if (
            seed.importance == "major"
            and 0 < seed.first_appearance <= INITIAL_OUTLINE_CHAPTER_COUNT
            and seed.profile_status != "ready"
        ):
            issues.setdefault(seed.name, []).append("opening_major_requires_ready")
        if seed.profile_status == "ready" and is_generic_character_content(seed.personality):
            issues.setdefault(seed.name, []).append("generic:personality")
    _raise_character_quality_issues(issues)
'''
    text = replace_once(text, old_validate, new_validate, "quality validation wrappers")
    helper_anchor = '\n\ndef _validate_game_dual_line_payoffs(plan: GeneratedOutlinePlan) -> None:'
    repair_helpers = '''

_CHARACTER_QUALITY_ERROR_PREFIX = "character_profile_quality_failed:"


def _failed_character_names_from_quality_error(error: str) -> list[str]:
    if not str(error or "").startswith(_CHARACTER_QUALITY_ERROR_PREFIX):
        return []
    detail = str(error)[len(_CHARACTER_QUALITY_ERROR_PREFIX):]
    names: list[str] = []
    for item in detail.split(";"):
        name = item.split("[", 1)[0].strip()
        if name and name not in names:
            names.append(name)
    return names


def _merge_repaired_character_rows(
    original: dict[str, Any],
    repaired: dict[str, Any],
    failed_names: list[str],
) -> dict[str, Any]:
    original_rows = original.get("characters")
    repaired_rows = repaired.get("characters")
    if not isinstance(original_rows, list) or not isinstance(repaired_rows, list):
        raise ValueError("invalid_character_repair_payload")
    expected = set(failed_names)
    replacements = {
        str(row.get("name") or "").strip(): row
        for row in repaired_rows
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }
    if set(replacements) != expected:
        raise ValueError("character_repair_name_mismatch")
    merged = deepcopy(original)
    merged["characters"] = [
        deepcopy(replacements.get(str(row.get("name") or "").strip(), row))
        if isinstance(row, dict)
        else row
        for row in original_rows
    ]
    return merged
'''
    text = replace_once(text, helper_anchor, repair_helpers + helper_anchor, "repair helpers")
    retry_old = '''                        if result is None:
                            invalid_response = (
                                json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                                if isinstance(data, dict)
                                else "{}"
                            )
                            retry_payload = {
                                **request_payload,
                                "messages": [
                                    *request_payload.get("messages", []),
                                    {
                                        "role": "assistant",
                                        "content": invalid_response,
                                    },
                                    {
                                        "role": "system",
                                        "content": (
                                            "The JSON immediately above failed schema validation. Edit that object "
                                            "to correct only the reported structural or missing-field problems, then return the complete JSON object "
                                            "again without markdown or commentary. Validation error: "
                                            f"{validation_error}"
                                        ),
                                    },
                                ],
                            }
                            response = _complete_payload(
                                self._model_gateway,
                                retry_payload,
                                operation=f"outline_planning_{phase}_retry",
                            )
                            data = parse_json_message_content(response)
                            if data is None:
                                raise ValueError(invalid_json_error)
                            if not attribute_allocation_enabled:
                                _drop_disabled_attribute_allocations(data)
                            _fill_equivalent_arc_handoffs(data)
                            result = schema.model_validate(data)
                            if result_validator:
                                result_validator(result)
'''
    retry_new = '''                        if result is None:
                            invalid_response = (
                                json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                                if isinstance(data, dict)
                                else "{}"
                            )
                            failed_character_names = (
                                _failed_character_names_from_quality_error(validation_error)
                                if phase == "character_roster"
                                else []
                            )
                            if failed_character_names and isinstance(data, dict):
                                original_rows = data.get("characters") or []
                                failed_set = set(failed_character_names)
                                failed_rows = [row for row in original_rows if isinstance(row, dict) and str(row.get("name") or "").strip() in failed_set]
                                locked_rows = [row for row in original_rows if isinstance(row, dict) and str(row.get("name") or "").strip() not in failed_set]
                                retry_payload = {
                                    **request_payload,
                                    "messages": [
                                        *request_payload.get("messages", []),
                                        {
                                            "role": "system",
                                            "content": (
                                                "Repair only the failed character cards. Return root field characters with exactly the failed names and no locked valid character. Do not rename anyone. "
                                                f"Failed rows: {json.dumps(failed_rows, ensure_ascii=False)}. "
                                                f"Locked context: {json.dumps(locked_rows, ensure_ascii=False)}. "
                                                f"Validation error: {validation_error}"
                                            ),
                                        },
                                    ],
                                }
                                response = _complete_payload(self._model_gateway, retry_payload, operation=f"outline_planning_{phase}_retry_failed_characters")
                                repaired = parse_json_message_content(response)
                                if repaired is None:
                                    raise ValueError(invalid_json_error)
                                data = _merge_repaired_character_rows(data, repaired, failed_character_names)
                            else:
                                retry_payload = {
                                    **request_payload,
                                    "messages": [
                                        *request_payload.get("messages", []),
                                        {"role": "assistant", "content": invalid_response},
                                        {
                                            "role": "system",
                                            "content": (
                                                "The JSON immediately above failed schema validation. Edit that object to correct only the reported structural or missing-field problems, then return the complete JSON object again without markdown or commentary. Validation error: "
                                                f"{validation_error}"
                                            ),
                                        },
                                    ],
                                }
                                response = _complete_payload(self._model_gateway, retry_payload, operation=f"outline_planning_{phase}_retry")
                                data = parse_json_message_content(response)
                                if data is None:
                                    raise ValueError(invalid_json_error)
                            if not attribute_allocation_enabled:
                                _drop_disabled_attribute_allocations(data)
                            _fill_equivalent_arc_handoffs(data)
                            result = schema.model_validate(data)
                            if result_validator:
                                result_validator(result)
'''
    text = replace_once(text, retry_old, retry_new, "split targeted retry")
    text = replace_once(
        text,
        '                        "Do not reuse the same motivation, long-term goal, speech style, or action style across multiple characters.",\n                    ],\n',
        '                        "Do not reuse the same motivation, long-term goal, speech style, or action style across multiple characters.",\n                        "Set importance, narrative_function, and profile_status explicitly. Core characters and major characters active in the opening use ready; ordinary or later supporting/minor characters may remain stub.",\n                        "Aim for roughly 4 to 7 ready core/major cards in the opening roster; do not force all 10 to 15 members into full detail.",\n                    ],\n',
        "split roster depth rules",
    )
    text = replace_once(
        text,
        '                                "Do not give multiple characters identical motivation, long-term goal, speech style, or action style. "\n                                "Follow prompt_context.output_schema exactly."\n',
        '                                "Do not give multiple characters identical motivation, long-term goal, speech style, or action style. "\n                                "Set importance, narrative_function, and profile_status explicitly. Fully detail only active core/major characters; ordinary or later supporting/minor characters may remain lightweight stubs. "\n                                "Follow prompt_context.output_schema exactly."\n',
        "split roster depth prompt",
    )
    direct_old = '''                try:
                    response = _complete_payload(
                        self._model_gateway,
                        payload,
                        operation="outline_planning",
                    )
                    parsed = parse_direct_outline(response)
                except Exception as exc:
                    validation_error = re.sub(r"\\s+", " ", str(exc)).strip()[:1000]
                    retry_payload = {
                        **payload,
                        "messages": [
                            *payload.get("messages", []),
                            {
                                "role": "system",
                                "content": (
                                    "The previous JSON failed schema or chapter-title validation. "
                                    "Correct only the reported problems, then return the complete JSON object "
                                    "again without markdown or commentary. Validation error: "
                                    f"{validation_error}"
                                ),
                            },
                        ],
                    }
                    response = _complete_payload(
                        self._model_gateway,
                        retry_payload,
                        operation="outline_planning_retry",
                    )
                    parsed = parse_direct_outline(response)
'''
    direct_new = '''                response: dict[str, Any] | None = None
                try:
                    response = _complete_payload(
                        self._model_gateway,
                        payload,
                        operation="outline_planning",
                    )
                    parsed = parse_direct_outline(response)
                except Exception as exc:
                    validation_error = re.sub(r"\\s+", " ", str(exc)).strip()[:1000]
                    failed_character_names = _failed_character_names_from_quality_error(validation_error)
                    original_candidate = parse_json_message_content(response) if response is not None else None
                    if failed_character_names and isinstance(original_candidate, dict):
                        original_rows = original_candidate.get("characters") or []
                        failed_set = set(failed_character_names)
                        failed_rows = [row for row in original_rows if isinstance(row, dict) and str(row.get("name") or "").strip() in failed_set]
                        locked_rows = [row for row in original_rows if isinstance(row, dict) and str(row.get("name") or "").strip() not in failed_set]
                        repair_payload = {
                            **payload,
                            "reasoning_effort": "low",
                            "messages": [
                                {"role": "system", "content": "Repair only the failed full character cards. Return JSON with root field characters and exactly the failed names. Keep names unchanged and do not return locked cards."},
                                {"role": "user", "content": json.dumps({"failed_characters": failed_rows, "locked_characters": locked_rows, "validation_error": validation_error, "output_schema": GeneratedCharacterCardRepair.model_json_schema()}, ensure_ascii=False)},
                            ],
                        }
                        repair_response = _complete_payload(self._model_gateway, repair_payload, operation="outline_planning_retry_failed_characters")
                        repaired = parse_json_message_content(repair_response)
                        if repaired is None:
                            raise ValueError("invalid_character_repair_json")
                        GeneratedCharacterCardRepair.model_validate(repaired)
                        merged_candidate = _merge_repaired_character_rows(original_candidate, repaired, failed_character_names)
                        candidate_plan = GeneratedOutlinePlan.model_validate(merged_candidate)
                        _validate_character_card_roster_quality(list(candidate_plan.characters), existing_names=(set(existing_character_names) if mode == "extend" else set()))
                        validate_chapter_title_window(
                            [chapter.model_dump(mode="python") for chapter in candidate_plan.outline.chapters],
                            genre_id=effective_novel_type_id,
                            previous_chapters=previous_chapters,
                            known_chapters=existing_outline_chapters,
                            generated_chapter_numbers=target_chapter_numbers,
                        )
                        parsed = merged_candidate
                    else:
                        retry_payload = {
                            **payload,
                            "messages": [
                                *payload.get("messages", []),
                                {"role": "system", "content": ("The previous JSON failed schema or chapter-title validation. Correct only the reported problems, then return the complete JSON object again without markdown or commentary. Validation error: " f"{validation_error}")},
                            ],
                        }
                        response = _complete_payload(self._model_gateway, retry_payload, operation="outline_planning_retry")
                        parsed = parse_direct_outline(response)
'''
    text = replace_once(text, direct_old, direct_new, "direct targeted retry")
    write(path, text)


patch_character_profiles()
patch_outline_planning()
patch_models()
patch_generation()
