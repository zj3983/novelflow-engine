"""Base classes for LLM-powered agents to eliminate code duplication.

- BaseOpenAIProvider: shared base for OpenAI-style providers (_runtime_settings,
  available, _post_json, and the standard LLM call loop).
- BaseLLMAgent: higher-level execute() wrapper with LLM-first + rule-fallback.
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
        """Execute with LLM-first, rule-based-fallback pattern.
        
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
        else:
            record_agent_runtime(
                story,
                self.agent_name,
                story.agent_settings.mode,
                "rule-based",
                story.current_chapter,
            )
        
        rule_args = rule_args or {}
        return rule_fallback(**{**kwargs, **rule_args})
