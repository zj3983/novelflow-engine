"""Writer agent.

The agent wraps a ``WriterRuntime`` and a prompt builder. It
owns the only "request in / result out" path the writer has,
so the rest of the codebase never has to know whether the
backing provider is Codex CLI, Gemini CLI, or HTTP API.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

from ..contracts import WriterRequest, WriterResult
from .prompt import build_writer_prompt
from .runtime import WriterRuntime


@dataclass
class _ModelRequest:
    """The minimal model-call payload the agent sends.

    The runtime is free to translate this into whatever the
    underlying transport expects; the agent itself only relies
    on ``prompt`` and ``metadata`` being preserved.
    """

    prompt: str
    stage: str
    metadata: dict[str, Any]


def _extract_text(response: Any) -> str:
    """Pull the body text out of whatever response the runtime returned."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    raw = getattr(response, "raw", None)
    if isinstance(raw, dict):
        for key in ("text", "body", "content"):
            value = raw.get(key)
            if isinstance(value, str):
                return value
    return ""


def _extract_proposed_facts(response: Any) -> list[dict[str, Any]]:
    """Pull the proposed facts the writer wants to attach to the chapter."""
    if response is None:
        return []
    raw = getattr(response, "raw", None)
    if isinstance(raw, dict):
        facts = raw.get("proposed_facts")
        if isinstance(facts, list):
            return [item for item in facts if isinstance(item, dict)]
    return []


def _length_distance(length: int, *, minimum: int, maximum: int) -> int:
    if length < minimum:
        return minimum - length
    if length > maximum:
        return length - maximum
    return 0


def _draft_score(body: str, *, minimum: int, maximum: int) -> tuple[int, int, int]:
    length = len("".join(body.split()))
    distance = _length_distance(length, minimum=minimum, maximum=maximum)
    similes = _simile_count(body)
    return (int(distance > 0) + int(similes >= 8), distance, similes)


def _trim_small_final_overflow(
    body: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    """Remove complete non-dialogue sentences when a draft barely misses the cap."""
    compact_length = len("".join(body.split()))
    overflow = compact_length - maximum
    small_overflow_limit = max(400, int(maximum * 0.08))
    if overflow <= 0 or overflow > small_overflow_limit:
        return body

    paragraphs = re.split(r"\n\s*\n", body.strip())
    if len(paragraphs) < 3:
        return body

    sentence_rows: list[list[str]] = []
    candidates: list[tuple[int, int, int, int]] = []
    redundant_markers = (
        "仿佛",
        "如同",
        "犹如",
        "宛如",
        "就像",
        "像是",
        "这意味着",
        "也就是说",
        "事实上",
        "显然",
    )
    protected_from = len(paragraphs) - (2 if len(paragraphs) >= 5 else 1)
    for paragraph_index, paragraph in enumerate(paragraphs):
        sentences = [
            item
            for item in re.findall(r".+?(?:[。！？!?]+|$)", paragraph, flags=re.S)
            if item.strip()
        ]
        sentence_rows.append(sentences)
        if paragraph_index == 0 or paragraph_index >= protected_from:
            continue
        for sentence_index, sentence in enumerate(sentences):
            if any(mark in sentence for mark in ('“', '”', '"')):
                continue
            sentence_length = len("".join(sentence.split()))
            if sentence_length < 8:
                continue
            redundancy = sum(sentence.count(marker) for marker in redundant_markers)
            candidates.append(
                (redundancy, sentence_length, paragraph_index, sentence_index)
            )

    removed: set[tuple[int, int]] = set()
    remaining_overflow = overflow
    while remaining_overflow > 0 and candidates:
        fitting = [item for item in candidates if item[1] >= remaining_overflow]
        if fitting:
            chosen = min(fitting, key=lambda item: (-item[0], item[1]))
        else:
            chosen = max(candidates, key=lambda item: (item[0], item[1]))
        candidates.remove(chosen)
        _, sentence_length, paragraph_index, sentence_index = chosen
        removed.add((paragraph_index, sentence_index))
        remaining_overflow -= sentence_length

    if remaining_overflow > 0:
        return body

    rebuilt_paragraphs = []
    for paragraph_index, sentences in enumerate(sentence_rows):
        kept = [
            sentence
            for sentence_index, sentence in enumerate(sentences)
            if (paragraph_index, sentence_index) not in removed
        ]
        if kept:
            rebuilt_paragraphs.append("".join(kept).strip())
    rebuilt = "\n\n".join(rebuilt_paragraphs)
    rebuilt_length = len("".join(rebuilt.split()))
    if minimum <= rebuilt_length <= maximum:
        return rebuilt
    return body


def _compact_overlong_prompt(
    original_prompt: str,
    body: str,
    *,
    current_length: int,
    target_min: int,
    target_max: int,
    hard_max: int,
) -> str:
    remove_min = max(0, current_length - target_max)
    remove_max = max(remove_min, current_length - target_min)
    return (
        f"{original_prompt}\n\n"
        "## 超长重写\n"
        f"上一稿约{current_length}字，超过{hard_max}字。只需删减约{remove_min}至{remove_max}字，"
        f"把正文收紧到{target_min}至{target_max}字，"
        f"最终绝不能超过{hard_max}字。保留导演规定的场景结果和章末钩子，删除重复解释、"
        "无关环境铺陈、过长文书原文和过度血腥细节。不要从头另写，只在上一稿上删除或合并段落，"
        "不可压成摘要，也不能删掉完整的行动过程和对话。仍然只能输出连续小说正文。\n\n"
        f"## 上一稿\n{body}"
    )


def _expand_undersized_prompt(
    original_prompt: str,
    body: str,
    *,
    current_length: int,
    acceptance_min: int,
    target_min: int,
    target_max: int,
    hard_max: int,
) -> str:
    add_min = max(0, target_min - current_length)
    add_max = max(add_min, target_max - current_length)
    return (
        f"{original_prompt}\n\n"
        "## 字数不足重写\n"
        f"上一稿约{current_length}字，不足{acceptance_min}字。只需增加约{add_min}至{add_max}字，"
        f"把正文补到{target_min}至{target_max}字，"
        f"最终绝不能超过{hard_max}字。通过补足必要的行动、反应和因果过程扩写，"
        "不要添加无关人物、重复解释、空泛环境描写或新的支线。不要从头另写，保留原有事件顺序，"
        "在原有段落之间补入会改变判断或加强冲突的行动、交流与后果。仍然只能输出连续小说正文。\n\n"
        f"## 上一稿\n{body}"
    )


_SIMILE_MARKERS = ("仿佛", "如同", "犹如", "宛如", "就像", "像是")


def _simile_count(body: str) -> int:
    return sum(body.count(marker) for marker in _SIMILE_MARKERS)


def _rewrite_simile_stacking_prompt(
    _original_prompt: str,
    body: str,
    *,
    target_min: int,
    target_max: int,
    hard_max: int,
) -> str:
    return (
        "你是小说句子编辑。只处理下面原稿中的比喻堆叠，不重新构思或扩写章节。\n\n"
        "## 比喻堆叠修复\n"
        f"上一稿出现了{_simile_count(body)}处显式比喻。请保持事件顺序、人物行为和对话不变，"
        "只改写这些过密的比喻，把它们改成直接的动作、状态和结果，全章最多保留两处真正必要的比喻。"
        f"正文保持{target_min}至{target_max}字，绝不能超过{hard_max}字。"
        "不要添加新事件，不要输出说明，只输出完整小说正文。\n\n"
        f"## 上一稿\n{body}"
    )


_GRAPHIC_DETAIL_TERMS = (
    "器官",
    "内脏",
    "脑组织",
    "骨茬",
    "断肢",
    "离断",
    "胸骨碎裂",
    "贯穿胸腔",
    "尸体细节",
    "白森森",
)


def _explicit_guidance_violations(guidance: str, body: str) -> list[str]:
    normalized = guidance.strip()
    if not normalized or not any(
        marker in normalized
        for marker in ("不描写", "不要描写", "不细写", "避免描写")
    ):
        return []
    return [term for term in _GRAPHIC_DETAIL_TERMS if term in body]


def _rewrite_guidance_compliance_prompt(
    original_prompt: str,
    body: str,
    *,
    violations: list[str],
    target_min: int,
    target_max: int,
    hard_max: int,
) -> str:
    return (
        f"{original_prompt}\n\n"
        "## 指导违例重写\n"
        f"上一稿出现了本次指导明确禁止的细节：{'、'.join(violations)}。"
        "请完整重写正文，用人物反应、现场秩序和事件后果代替这些伤情细节，"
        "不得在文书引用、人物观察或旁白中换一种说法重复。"
        f"正文保持{target_min}至{target_max}字，绝不能超过{hard_max}字。"
        "只能输出连续小说正文。\n\n"
        f"## 上一稿\n{body}"
    )


def _document_transcription_labels(body: str) -> list[str]:
    """Return label-like lines when prose starts copying a form verbatim."""
    labels = re.findall(
        r"(?:^|\n)([\u4e00-\u9fffA-Za-z0-9·（）()]{2,24})[：:]",
        body,
    )
    return list(dict.fromkeys(label.strip() for label in labels if label.strip()))


def _rewrite_document_transcription_prompt(
    original_prompt: str,
    body: str,
    *,
    labels: list[str],
    target_min: int,
    target_max: int,
    hard_max: int,
) -> str:
    return (
        f"{original_prompt}\n\n"
        "## 文书照抄修复\n"
        f"上一稿连续照抄了表格或记录字段：{'、'.join(labels[:6])}。"
        "请完整重写正文，文书、面板或记录总共最多保留三行，"
        "只留下会改变人物下一步选择的内容，其余信息改由人物动作和现场后果呈现。"
        f"正文保持{target_min}至{target_max}字，绝不能超过{hard_max}字。"
        "只能输出连续小说正文。\n\n"
        f"## 上一稿\n{body}"
    )


class WriterAgent:
    """The single writer boundary.

    The agent takes one ``WriterRequest`` and produces one
    ``WriterResult`` per call. No provider-specific branching
    lives here; the runtime decides which transport to use. Automatic
    repair is opt-in so production preserves the first draft for
    human review.
    """

    def __init__(
        self,
        runtime: WriterRuntime,
        *,
        allow_automatic_repair: bool = False,
    ) -> None:
        self._runtime = runtime
        self._allow_automatic_repair = allow_automatic_repair

    def run(self, request: WriterRequest) -> WriterResult:
        prompt = build_writer_prompt(request)
        model_request = _ModelRequest(
            prompt=prompt,
            stage="writer",
            metadata={
                "chapter_number": request.chapter_number,
                "agent": "writer",
                "schema_version": request.director_artifact.schema_version,
            },
        )
        response = self._runtime.complete(model_request)
        body = _extract_text(response).strip()
        if not body:
            raise RuntimeError("writer_empty_body")
        acceptance_min = int(request.acceptance_chars.get("min", 3800))
        hard_max = int(request.acceptance_chars.get("max", 5700))
        target_min = int(request.target_chars.get("min", 4200))
        target_max = int(request.target_chars.get("max", 5500))
        best_body = body
        best_response = response
        best_score = _draft_score(
            body,
            minimum=acceptance_min,
            maximum=hard_max,
        )
        # At most four repair calls. Real providers can oscillate from a long
        # draft to a short compaction and back again; the final slot lets a
        # near-limit draft converge without turning this into an unbounded loop.
        allow_repair = self._allow_automatic_repair and (
            request.repair_length or bool(request.rewrite_guidance.strip())
        )
        for retry_index in range(4 if allow_repair else 0):
            compact_length = len("".join(body.split()))
            guidance_violations = _explicit_guidance_violations(
                request.rewrite_guidance, body
            )
            document_labels = _document_transcription_labels(body)
            document_violation = len(document_labels) >= 4
            simile_violation = _simile_count(body) >= 8
            length_ok = acceptance_min <= compact_length <= hard_max
            if (
                (length_ok or not request.repair_length)
                and not guidance_violations
                and (not document_violation or not request.repair_length)
                and (not simile_violation or not request.repair_length)
            ):
                break
            if guidance_violations:
                retry_prompt = _rewrite_guidance_compliance_prompt(
                    prompt,
                    body,
                    violations=guidance_violations,
                    target_min=target_min,
                    target_max=target_max,
                    hard_max=hard_max,
                )
                reason = "rewrite_guidance_violation"
            elif compact_length > hard_max:
                target_margin = max(1, (target_max - target_min) // 4)
                retry_target_min = max(
                    target_min,
                    min(target_max - target_margin, int(compact_length * 0.80)),
                )
                retry_target_max = min(
                    target_max,
                    max(retry_target_min + target_margin, int(compact_length * 0.88)),
                )
                retry_prompt = _compact_overlong_prompt(
                    prompt,
                    body,
                    current_length=compact_length,
                    target_min=retry_target_min,
                    target_max=retry_target_max,
                    hard_max=hard_max,
                )
                reason = "over_hard_max"
            elif compact_length < acceptance_min:
                missing = acceptance_min - compact_length
                add_min = max(missing + 1, int(compact_length * 0.15))
                add_max = max(add_min + 1, int(compact_length * 0.30))
                retry_target_min = max(
                    acceptance_min,
                    min(target_min, compact_length + add_min),
                )
                retry_target_max = min(
                    target_max,
                    max(retry_target_min + 1, compact_length + add_max),
                )
                retry_prompt = _expand_undersized_prompt(
                    prompt,
                    body,
                    current_length=compact_length,
                    acceptance_min=acceptance_min,
                    target_min=retry_target_min,
                    target_max=retry_target_max,
                    hard_max=hard_max,
                )
                reason = "under_acceptance_min"
            elif document_violation:
                retry_prompt = _rewrite_document_transcription_prompt(
                    prompt,
                    body,
                    labels=document_labels,
                    target_min=target_min,
                    target_max=target_max,
                    hard_max=hard_max,
                )
                reason = "document_transcription"
            else:
                retry_prompt = _rewrite_simile_stacking_prompt(
                    prompt,
                    body,
                    target_min=target_min,
                    target_max=target_max,
                    hard_max=hard_max,
                )
                reason = "simile_stacking"
            retry_request = _ModelRequest(
                prompt=retry_prompt,
                stage="writer",
                metadata={
                    "chapter_number": request.chapter_number,
                    "agent": "writer",
                    "schema_version": request.director_artifact.schema_version,
                    "attempt": retry_index + 2,
                    "reason": reason,
                },
            )
            retry_response = self._runtime.complete(retry_request)
            retry_body = _extract_text(retry_response).strip()
            if retry_body:
                response = retry_response
                body = retry_body
                if reason in {
                    "over_hard_max",
                    "under_acceptance_min",
                    "document_transcription",
                    "simile_stacking",
                }:
                    retry_score = _draft_score(
                        retry_body,
                        minimum=acceptance_min,
                        maximum=hard_max,
                    )
                    if retry_score <= best_score:
                        best_body = retry_body
                        best_response = retry_response
                        best_score = retry_score
                else:
                    best_body = retry_body
                    best_response = retry_response
                    best_score = _draft_score(
                        retry_body,
                        minimum=acceptance_min,
                        maximum=hard_max,
                    )
            else:
                break
        body = best_body
        response = best_response
        trimmed_body = (
            _trim_small_final_overflow(
                body,
                minimum=acceptance_min,
                maximum=hard_max,
            )
            if self._allow_automatic_repair
            else body
        )
        length_trimmed = trimmed_body != body
        body = trimmed_body
        remaining_violations = _explicit_guidance_violations(
            request.rewrite_guidance, body
        )
        remaining_document_labels = _document_transcription_labels(body)
        notes = (
            "rewrite_guidance_violation:" + ",".join(remaining_violations)
            if remaining_violations
            else (
                "document_transcription:" + ",".join(remaining_document_labels[:6])
                if len(remaining_document_labels) >= 4
                else ""
            )
        )
        if length_trimmed:
            notes = ";".join(
                item for item in (notes, "deterministic_length_trim") if item
            )
        return WriterResult(
            body=body,
            proposed_facts=_extract_proposed_facts(response),
            word_count=len("".join(body.split())),
            notes=notes,
        )


__all__ = ["WriterAgent"]
