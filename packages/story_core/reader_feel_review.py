from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any


def _normalize(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "").lower()


def _paragraphs(text: str) -> list[str]:
    blocks = [part.strip() for part in re.split(r"\n\s*\n", str(text or "")) if part.strip()]
    if len(blocks) < 2:
        blocks = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return [block for block in blocks if len(_normalize(block)) >= 28]


def _bigrams(text: str) -> set[str]:
    return {text[index : index + 2] for index in range(max(0, len(text) - 1))}


def _similarity(left: str, right: str) -> float:
    left_norm = _normalize(left)
    right_norm = _normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    sequence_ratio = SequenceMatcher(None, left_norm, right_norm, autojunk=False).ratio()
    left_pairs = _bigrams(left_norm)
    right_pairs = _bigrams(right_norm)
    union = left_pairs | right_pairs
    pair_ratio = len(left_pairs & right_pairs) / len(union) if union else 0.0
    return max(sequence_ratio, pair_ratio)


def _near_duplicate_pairs(paragraphs: list[str]) -> list[dict[str, Any]]:
    sentence_units: list[tuple[int, str, str]] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        for sentence in re.split(r"[\u3002\uff01\uff1f\uff1b!?;]", paragraph):
            sentence = sentence.strip()
            if len(_normalize(sentence)) >= 18:
                sentence_units.append((paragraph_index, sentence, "sentence"))

    pairs: list[dict[str, Any]] = []
    candidates = [(index, paragraph, "paragraph") for index, paragraph in enumerate(paragraphs)]
    candidates.extend(sentence_units)
    seen: set[tuple[Any, ...]] = set()
    for left_position, (left_index, left, left_kind) in enumerate(candidates):
        for right_index, right, right_kind in candidates[left_position + 1 :]:
            if left_index == right_index and left_kind != right_kind:
                continue
            if left == right:
                similarity = 1.0
            else:
                similarity = _similarity(left, right)
            identity = tuple(sorted((_normalize(left), _normalize(right))))
            pair_key: tuple[Any, ...] = (
                ("paragraphs", min(left_index, right_index), max(left_index, right_index))
                if left_index != right_index
                else ("sentences", *identity)
            )
            if pair_key in seen:
                continue
            similarity = _similarity(left, right)
            if similarity < 0.72:
                continue
            seen.add(pair_key)
            pairs.append(
                {
                    "left_index": left_index,
                    "right_index": right_index,
                    "similarity": round(similarity, 3),
                    "left": left[:100],
                    "right": right[:100],
                }
            )
    return pairs


def review_reader_feel(text: str) -> dict[str, Any]:
    """Catch reader-visible patchwork that rule-oriented prose checks miss."""

    paragraphs = _paragraphs(text)
    duplicate_pairs = _near_duplicate_pairs(paragraphs)
    panel_count = len(re.findall(r"【[^】\n]{2,80}】", str(text or "")))
    panel_ratio = round(panel_count / max(1, len(paragraphs)), 3)

    issues: list[str] = []
    revision_plan: list[str] = []
    scores = {"patchwork": 8, "panel_balance": 8}

    if duplicate_pairs:
        scores["patchwork"] = 4 if len(duplicate_pairs) >= 2 else 5
        issues.append("段落重复或换词复述，正文有明显拼补感。")
        revision_plan.append("合并近似段落；同一个事实、判断或旁人误解只写一次，把省下的篇幅用于新的行动、对话或结果。")

    if panel_count >= 8 and panel_ratio >= 0.18:
        scores["panel_balance"] = 6
        issues.append("系统面板出现过密，场景被提示框切碎。")
        revision_plan.append("只保留马上影响选择的面板数字，其余改成角色动作或结算后的直接变化。")

    return {
        "reviewer": "reader_feel/v1",
        "pass": not issues,
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
        "metrics": {
            "paragraph_count": len(paragraphs),
            "near_duplicate_count": len(duplicate_pairs),
            "panel_count": panel_count,
            "panel_ratio": panel_ratio,
        },
        "duplicate_pairs": duplicate_pairs[:6],
    }
