"""Base classes for LLM-powered agents to eliminate code duplication.

- BaseOpenAIProvider: shared base for OpenAI-style providers (_runtime_settings,
  available, _post_json, and the standard LLM call loop).
- BaseLLMAgent: higher-level execute() wrapper with LLM-first + deterministic fallback.
"""

from __future__ import annotations

from typing import Protocol

import json
import urllib.error
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.runtime import record_agent_runtime
from packages.story_core.runtime_config import resolve_openai_runtime_settings

if TYPE_CHECKING:
    from packages.story_core.models import StoryState, CharacterProposal, DirectorDecision

T = TypeVar("T")

LONGFORM_FACT_PREFIXES = (
    "百万字",
    "长卷阶段",
    "长期成长阶段",
    "长期势力阶段",
    "长期经济阶段",
    "现实线阶段",
    "真相揭露阶段",
    "地图解锁阶段",
    "NPC演化阶段",
    "长期推演规则",
)


def find_protagonist(story: Any) -> Any | None:
    """Return the protagonist ``CharacterState`` from a story, or ``None``.

    Lookup order: explicit role tag (``"protagonist"`` / ``"主角"``) → first
    active non-frozen character → first character. Used by writers and
    reviewers that need the lead's name / game id / voice without coupling
    to a specific data layout.
    """
    characters = getattr(story, "characters", None) or []
    if not characters:
        return None
    for character in characters:
        if getattr(character, "frozen", False):
            continue
        role = str(getattr(character, "role", "") or "")
        if role in {"protagonist", "主角"}:
            return character
    for character in characters:
        if getattr(character, "frozen", False):
            continue
        lifecycle = str(getattr(character, "lifecycle_state", "") or "")
        if lifecycle in {"", "active", "proposed"}:
            return character
    return characters[0]


def compact_text(text: str, max_chars: int = 400) -> str:
    compact = " ".join(str(text or "").split()).strip()
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 1].rstrip()}…"


def compact_list(items: list[str] | str, max_items: int = 4, item_chars: int = 80) -> list[str]:
    if isinstance(items, str):
        items = [items]
    result: list[str] = []
    for item in items[:max_items]:
        cleaned = compact_text(str(item), item_chars)
        if cleaned:
            result.append(cleaned)
    return result


def parse_json_message_content(response: dict) -> dict | None:
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return None

    content = message.get("content", "")
    if isinstance(content, list):
        fragments: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if text:
                    fragments.append(str(text))
            elif isinstance(block, str):
                fragments.append(block)
        content = "\n".join(fragments)
    elif isinstance(content, dict):
        content = str(content.get("text", "")).strip()
    else:
        content = str(content).strip()

    content = content.strip()
    if content.startswith("```"):
        lines = [line for line in content.splitlines() if not line.strip().startswith("```")]
        content = "\n".join(lines).strip()

    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(content[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


class BaseOpenAIProvider:
    """Shared base for OpenAI-style LLM providers.
    
    Eliminates duplicated _runtime_settings(), available(), and _post_json()
    across OpenAIWriterTextProvider, OpenAIDirectorDecisionProvider,
    OpenAICharacterProposalProvider, and OpenAIMemorySummaryProvider.
    
    Subclass must set:
    - runtime_key: str  (e.g. "writer", "director", "character", "memory")
    """
    runtime_key: str = ""
    
    def _runtime_settings(self) -> Any:
        return resolve_openai_runtime_settings(self.runtime_key)
    
    def available(self) -> bool:
        return bool(self._runtime_settings().api_key)

    def _set_last_error(self, reason: str) -> None:
        self._last_error = compact_text(reason, 160)

    def _clear_last_error(self) -> None:
        self._last_error = ""

    def last_error_reason(self) -> str:
        return getattr(self, "_last_error", "")
    
    def _post_json(self, path: str, payload: dict, settings: Any | None = None) -> dict:
        settings = settings or self._runtime_settings()
        return post_json_with_retry(
            settings.base_url, path, payload, settings.api_key,
        )


class StoryAgentProvider(Protocol):
    def propose(self, story: StoryState) -> list[CharacterProposal]: ...
    def decide(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> DirectorDecision: ...
    def write(
        self,
        story: StoryState,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str: ...
    def remember(
        self,
        story: StoryState,
        body: str,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> StoryState: ...


class BaseLLMAgent(Generic[T]):
    """Base class for agents that call LLM APIs.
    
    Subclasses must implement:
    - _build_prompt(): construct the user prompt
    - _parse_response(): parse the LLM JSON response into the expected type
    
    Optionally override:
    - _system_message(): custom system prompt
    - _response_format(): custom response_format dict
    """
    
    agent_name: str = ""  # e.g. "CharacterAgent", "WriterAgent"
    runtime_key: str = ""  # e.g. "character", "writer", "director", "memory"
    
    def _runtime_settings(self, story: StoryState):
        """Resolve runtime settings for this agent's role."""
        return resolve_openai_runtime_settings(self.runtime_key)
    
    def _system_message(self, story: StoryState) -> str:
        """Default system message. Override for custom prompts."""
        return f"You are the {self.agent_name} for a novel engine. Return JSON only."
    
    def _response_format(self) -> dict:
        """Response format for the API call."""
        return {"type": "json_object"}
    
    def _build_prompt(self, story: StoryState, **kwargs: Any) -> str:
        """Construct the user prompt. Must be overridden."""
        raise NotImplementedError
    
    def _parse_response(self, story: StoryState, parsed: dict, **kwargs: Any) -> T | None:
        """Parse the JSON response into the expected type. Must be overridden."""
        raise NotImplementedError
    
    def call_llm(self, story: StoryState, **kwargs: Any) -> T | None:
        """Call the LLM and return the parsed result, or None on failure."""
        settings = self._runtime_settings(story)
        if not settings.api_key:
            return None
        
        model = self._resolve_model(story)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": self._system_message(story)},
                {"role": "user", "content": self._build_prompt(story, **kwargs)},
            ],
            "response_format": self._response_format(),
            "temperature": float(story.agent_settings.temperature),
        }
        
        try:
            response = post_json_with_retry(
                settings.base_url, "/chat/completions", payload, settings.api_key,
            )
            content = response["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError, Exception):
            return None
        
        if not isinstance(parsed, dict):
            return None
        
        return self._parse_response(story, parsed, **kwargs)
    
    def _resolve_model(self, story: StoryState) -> str:
        """Resolve the model name to use. Override if needed."""
        raise NotImplementedError
    
    def execute(
        self,
        story: StoryState,
        *,
        rule_fallback: Any,
        rule_args: dict | None = None,
        llm_kwargs: dict | None = None,
        fallback_reason: str = "LLM 没有返回可用结果",
        no_apikey_reason: str = "未配置 API 密钥",
        **kwargs: Any,
    ) -> T:
        """Execute with LLM-first, deterministic-fallback pattern.
        
        Args:
            story: Current story state
            rule_fallback: Callable that returns the fallback result
            rule_args: Arguments to pass to rule_fallback
            llm_kwargs: Extra kwargs for LLM call
            fallback_reason: Default fallback reason
            no_apikey_reason: Default no-apikey reason
            **kwargs: Passed to both LLM and rule fallback
        """
        if story.agent_settings.mode == "LLM-assisted":
            llm_kwargs = llm_kwargs or {}
            result = self.call_llm(story, **{**kwargs, **llm_kwargs})
            if result is not None:
                record_agent_runtime(
                    story,
                    self.agent_name,
                    story.agent_settings.mode,
                    "llm",
                    story.current_chapter,
                )
                return result
            
            reason = fallback_reason
            if not self._runtime_settings(story).api_key:
                reason = no_apikey_reason
            record_agent_runtime(
                story,
                self.agent_name,
                story.agent_settings.mode,
                "fallback",
                story.current_chapter,
                reason,
            )
        rule_args = rule_args or {}
        return rule_fallback(**{**kwargs, **rule_args})
