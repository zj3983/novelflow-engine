from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.story_core.continuation_import import ContinuationChapter, scan_continuation_source
from packages.story_core.continuation_sessions import ContinuationSessionStore

from packages.story_core.continuation_analysis import (
    ChapterAnalysis,
    ClaimItem,
    ContinuationAnalysis,
    ContinuationStart,
    EvidenceRef,
    HookAnalysis,
    LLMContinuationAnalyzer,
    StyleProfile,
    TimelineEvent,
    run_continuation_analysis,
)


def _store_with_chapters(tmp_path: Path, count: int = 3):
    source = tmp_path / "novel"
    source.mkdir(parents=True)
    for number in range(1, count + 1):
        (source / f"{number}.txt").write_text(
            f"第{number}章 标题\n正文里人物在地点{number}行动。", encoding="utf-8"
        )
    store = ContinuationSessionStore(
        tmp_path / "sessions", session_id_factory=lambda: "ci-analysis-test"
    )
    session = store.create(scan_continuation_source(source))
    return store, session


def _claim(chapter: ContinuationChapter, text: str | None = None) -> ClaimItem:
    quote = chapter.body[:2]
    return ClaimItem(
        claim=text or f"事实-{chapter.number}",
        confidence="confirmed",
        evidence=[
            EvidenceRef(
                chapter_id=chapter.chapter_id,
                excerpt_start=0,
                excerpt_end=2,
                quote=quote,
            )
        ],
    )


def _chapter_result(chapter: ContinuationChapter, *, text: str | None = None) -> ChapterAnalysis:
    return ChapterAnalysis(
        chapter_id=chapter.chapter_id,
        summary=f"摘要-{chapter.number}",
        facts=[_claim(chapter, text)],
    )


def _replace_bodies(store, session, bodies: list[str]):
    chapters = [
        chapter.model_copy(
            update={
                "body": body,
                "fingerprint": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            }
        )
        for chapter, body in zip(session.chapters, bodies, strict=True)
    ]
    return store.replace_chapters(
        session.session_id, chapters, expected_revision=session.revision
    )


def _merged(results: list[ChapterAnalysis]) -> ContinuationAnalysis:
    return ContinuationAnalysis(
        story_overview="故事总览",
        timeline=[
            TimelineEvent(
                text=item.summary,
                confidence="confirmed",
                evidence=item.facts[0].evidence,
            )
            for item in results
        ],
        open_hooks=[HookAnalysis(text="等待继续", confidence="inferred")],
        style_profile=StyleProfile(narrative_voice="第三人称"),
        continuation_start=ContinuationStart(
            chapter_id=results[-1].chapter_id if results else "", guidance="承接末章"
        ),
    )


class FakeAnalyzer:
    def __init__(self, *, fail_call: int | None = None):
        self.batch_calls: list[list[ContinuationChapter]] = []
        self.merge_calls: list[tuple[list[ChapterAnalysis], list[ContinuationChapter]]] = []
        self.fail_call = fail_call

    def analyze_chapters(self, chapters: list[ContinuationChapter]) -> list[ChapterAnalysis]:
        self.batch_calls.append(chapters)
        if self.fail_call == len(self.batch_calls):
            raise RuntimeError("secret provider details")
        return [_chapter_result(chapter) for chapter in chapters]

    def merge(
        self,
        chapter_results: list[ChapterAnalysis],
        recent_chapters: list[ContinuationChapter],
    ) -> ContinuationAnalysis:
        self.merge_calls.append((chapter_results, recent_chapters))
        return _merged(chapter_results)


def test_evidence_ref_validates_offsets() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(chapter_id="c1", excerpt_start=-1, excerpt_end=1)
    with pytest.raises(ValidationError):
        EvidenceRef(chapter_id="c1", excerpt_start=1, excerpt_end=1)


def test_evidence_quote_is_optional_and_empty_quote_uses_range_only(
    tmp_path: Path,
) -> None:
    store, session = _store_with_chapters(tmp_path, count=1)

    class EmptyQuoteAnalyzer(FakeAnalyzer):
        def merge(self, results, recent):
            return ContinuationAnalysis(
                story_overview="总览",
                world=[
                    ClaimItem(
                        claim="范围已定位",
                        confidence="confirmed",
                        evidence=[
                            EvidenceRef(
                                chapter_id=session.chapters[0].chapter_id,
                                excerpt_start=0,
                                excerpt_end=2,
                            )
                        ],
                    )
                ],
            )

    result = run_continuation_analysis(store, session.session_id, EmptyQuoteAnalyzer())

    assert result.world[0].confidence == "confirmed"
    assert result.world[0].evidence[0].quote == ""


def test_three_chapters_batch_size_one_persists_each_batch(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path)
    analyzer = FakeAnalyzer()

    result = run_continuation_analysis(store, session.session_id, analyzer, batch_size=1)

    assert result.story_overview == "故事总览"
    loaded = store.get(session.session_id)
    assert loaded.status == "ready"
    assert loaded.revision == 6  # analyzing + 3 batches + ready
    assert loaded.analysis_progress["completed_chapter_ids"] == [
        chapter.chapter_id for chapter in loaded.chapters
    ]
    assert len(loaded.analysis_progress["chapter_results"]) == 3
    assert loaded.analysis_progress["chapter_fingerprints"] == {
        chapter.chapter_id: chapter.fingerprint for chapter in loaded.chapters
    }
    assert len(analyzer.batch_calls) == 3


def test_resume_skips_completed_chapter(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path)
    first = _chapter_result(session.chapters[0])
    store.update(
        session.session_id,
        lambda current: current.analysis_progress.update(
            completed_chapter_ids=[session.chapters[0].chapter_id],
            chapter_results=[first.model_dump(mode="json")],
            chapter_fingerprints={
                session.chapters[0].chapter_id: session.chapters[0].fingerprint
            },
        ),
    )
    analyzer = FakeAnalyzer()

    run_continuation_analysis(store, session.session_id, analyzer, batch_size=10)

    assert [[chapter.number for chapter in batch] for batch in analyzer.batch_calls] == [[2, 3]]


def test_same_id_changed_fingerprint_reanalyzes_only_stale_chapter(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path)
    results = [_chapter_result(chapter) for chapter in session.chapters]

    def seed_progress(current):
        current.status = "analyzing"
        current.analysis_progress = {
            "completed_chapter_ids": [chapter.chapter_id for chapter in current.chapters],
            "chapter_results": [result.model_dump(mode="json") for result in results],
            "chapter_fingerprints": {
                chapter.chapter_id: chapter.fingerprint for chapter in current.chapters
            },
        }

    store.update(session.session_id, seed_progress)

    def change_middle_chapter(current):
        changed = current.chapters[1]
        current.chapters[1] = changed.model_copy(
            update={"body": "修改后的第二章正文", "fingerprint": "changed-fingerprint"}
        )

    store.update(session.session_id, change_middle_chapter)
    analyzer = FakeAnalyzer()

    run_continuation_analysis(store, session.session_id, analyzer)

    assert [[chapter.number for chapter in batch] for batch in analyzer.batch_calls] == [[2]]
    loaded = store.get(session.session_id)
    assert loaded.analysis_progress["chapter_fingerprints"] == {
        chapter.chapter_id: chapter.fingerprint for chapter in loaded.chapters
    }


def test_legacy_progress_without_fingerprint_is_reanalyzed(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=2)
    first = _chapter_result(session.chapters[0])
    store.update(
        session.session_id,
        lambda current: current.analysis_progress.update(
            completed_chapter_ids=[session.chapters[0].chapter_id],
            chapter_results=[first.model_dump(mode="json")],
        ),
    )
    analyzer = FakeAnalyzer()

    run_continuation_analysis(store, session.session_id, analyzer)

    assert [[chapter.number for chapter in batch] for batch in analyzer.batch_calls] == [[1, 2]]


def test_failed_batch_keeps_checkpoint_and_resume_succeeds(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path)
    failing = FakeAnalyzer(fail_call=2)

    with pytest.raises(RuntimeError, match="secret provider details"):
        run_continuation_analysis(store, session.session_id, failing, batch_size=1)

    failed = store.get(session.session_id)
    assert failed.status == "failed"
    assert failed.error == "continuation_analysis_failed"
    assert failed.analysis == {}
    assert failed.analysis_progress["completed_chapter_ids"] == [session.chapters[0].chapter_id]

    retry = FakeAnalyzer()
    run_continuation_analysis(store, session.session_id, retry, batch_size=1)
    assert [batch[0].number for batch in retry.batch_calls] == [2, 3]


def test_removed_completed_id_is_cleaned_not_reused(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=2)
    stale = _chapter_result(session.chapters[0]).model_dump(mode="json")
    stale["chapter_id"] = "removed-id"
    store.update(
        session.session_id,
        lambda current: current.analysis_progress.update(
            completed_chapter_ids=["removed-id"], chapter_results=[stale]
        ),
    )
    analyzer = FakeAnalyzer()

    run_continuation_analysis(store, session.session_id, analyzer)

    assert [chapter.number for chapter in analyzer.batch_calls[0]] == [1, 2]


@pytest.mark.parametrize("mode", ["missing", "duplicate", "wrong_id"])
def test_invalid_batch_result_ids_fail_stably_and_keep_prior_progress(
    tmp_path: Path, mode: str
) -> None:
    store, session = _store_with_chapters(tmp_path, count=2)

    class InvalidAnalyzer(FakeAnalyzer):
        def analyze_chapters(self, chapters):
            self.batch_calls.append(chapters)
            if chapters[0].number == 1:
                return [_chapter_result(chapters[0])]
            valid = _chapter_result(chapters[0])
            if mode == "missing":
                return []
            if mode == "duplicate":
                return [valid, valid]
            return [valid.model_copy(update={"chapter_id": session.chapters[0].chapter_id})]

    with pytest.raises(ValueError, match="^invalid_chapter_analysis$"):
        run_continuation_analysis(store, session.session_id, InvalidAnalyzer(), batch_size=1)

    loaded = store.get(session.session_id)
    assert loaded.status == "failed"
    assert loaded.error == "invalid_chapter_analysis"
    assert loaded.analysis_progress["completed_chapter_ids"] == [session.chapters[0].chapter_id]


def test_reversed_batch_results_are_restored_to_chapter_order(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=2)

    class ReversedAnalyzer(FakeAnalyzer):
        def analyze_chapters(self, chapters):
            self.batch_calls.append(chapters)
            return [_chapter_result(chapter) for chapter in reversed(chapters)]

    analyzer = ReversedAnalyzer()
    run_continuation_analysis(store, session.session_id, analyzer, batch_size=2)

    assert [result.chapter_id for result in analyzer.merge_calls[0][0]] == [
        chapter.chapter_id for chapter in session.chapters
    ]


def test_extra_unique_batch_result_is_rejected(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=2)

    class ExtraResultAnalyzer(FakeAnalyzer):
        def analyze_chapters(self, chapters):
            results = [_chapter_result(chapter) for chapter in chapters]
            return [
                *results,
                results[0].model_copy(update={"chapter_id": "unexpected-extra"}),
            ]

    with pytest.raises(ValueError, match="^invalid_chapter_analysis$"):
        run_continuation_analysis(
            store, session.session_id, ExtraResultAnalyzer(), batch_size=2
        )

    loaded = store.get(session.session_id)
    assert loaded.status == "failed"
    assert loaded.analysis_progress["completed_chapter_ids"] == []


def test_batching_honors_count_and_body_character_budget(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=3)
    session = _replace_bodies(store, session, ["甲" * 4, "乙" * 4, "丙" * 4])
    analyzer = FakeAnalyzer()

    run_continuation_analysis(
        store,
        session.session_id,
        analyzer,
        batch_size=3,
        batch_body_char_budget=8,
        chapter_max_chars=10,
    )

    assert [[chapter.number for chapter in batch] for batch in analyzer.batch_calls] == [
        [1, 2],
        [3],
    ]


def test_oversized_chapter_fails_and_preserves_valid_progress(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=2)
    session = _replace_bodies(store, session, ["可" * 4, "超" * 11])
    first = _chapter_result(session.chapters[0])
    store.update(
        session.session_id,
        lambda current: current.analysis_progress.update(
            completed_chapter_ids=[session.chapters[0].chapter_id],
            chapter_results=[first.model_dump(mode="json")],
            chapter_fingerprints={
                session.chapters[0].chapter_id: session.chapters[0].fingerprint
            },
        ),
    )
    analyzer = FakeAnalyzer()

    with pytest.raises(ValueError, match="^continuation_chapter_too_large$"):
        run_continuation_analysis(
            store,
            session.session_id,
            analyzer,
            batch_body_char_budget=10,
            chapter_max_chars=10,
        )

    loaded = store.get(session.session_id)
    assert loaded.status == "failed"
    assert loaded.error == "continuation_chapter_too_large"
    assert loaded.analysis_progress["completed_chapter_ids"] == [
        session.chapters[0].chapter_id
    ]
    assert analyzer.batch_calls == []


def test_oversized_chapter_fails_after_checkpointing_earlier_pending_batch(
    tmp_path: Path,
) -> None:
    store, session = _store_with_chapters(tmp_path, count=2)
    session = _replace_bodies(store, session, ["可" * 4, "超" * 11])
    analyzer = FakeAnalyzer()

    with pytest.raises(ValueError, match="^continuation_chapter_too_large$"):
        run_continuation_analysis(
            store,
            session.session_id,
            analyzer,
            batch_size=1,
            batch_body_char_budget=10,
            chapter_max_chars=10,
        )

    assert [[chapter.number for chapter in batch] for batch in analyzer.batch_calls] == [
        [1]
    ]
    loaded = store.get(session.session_id)
    assert loaded.analysis_progress["completed_chapter_ids"] == [
        session.chapters[0].chapter_id
    ]


def test_merge_once_and_receives_at_most_last_ten_chapters(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=12)
    analyzer = FakeAnalyzer()

    run_continuation_analysis(store, session.session_id, analyzer, batch_size=4)

    assert len(analyzer.merge_calls) == 1
    recent = analyzer.merge_calls[0][1]
    assert [chapter.number for chapter in recent] == list(range(3, 13))


def test_confirmed_claim_with_valid_evidence_is_indexed(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=1)
    result = run_continuation_analysis(store, session.session_id, FakeAnalyzer())

    assert result.timeline[0].confidence == "confirmed"
    assert result.evidence_index["timeline.0"][0].chapter_id == session.chapters[0].chapter_id
    assert result.needs_confirmation == []


def test_evidence_offsets_count_non_bmp_text_as_python_code_points(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=1)
    session = _replace_bodies(store, session, ["甲😀乙"])

    class EmojiEvidenceAnalyzer(FakeAnalyzer):
        def merge(self, results, recent):
            return ContinuationAnalysis(
                story_overview="总览",
                world=[
                    ClaimItem(
                        claim="出现表情",
                        confidence="confirmed",
                        evidence=[
                            EvidenceRef(
                                chapter_id=session.chapters[0].chapter_id,
                                excerpt_start=1,
                                excerpt_end=2,
                                quote="😀",
                            )
                        ],
                    )
                ],
            )

    result = run_continuation_analysis(store, session.session_id, EmojiEvidenceAnalyzer())

    assert len(session.chapters[0].body) == 3
    assert result.world[0].confidence == "confirmed"
    assert result.world[0].evidence[0].quote == "😀"


def test_chapter_claim_without_evidence_survives_checkpoint_as_confirmation(
    tmp_path: Path,
) -> None:
    store, session = _store_with_chapters(tmp_path, count=1)

    class UnsupportedChapterAnalyzer(FakeAnalyzer):
        def analyze_chapters(self, chapters):
            return [
                ChapterAnalysis(
                    chapter_id=chapters[0].chapter_id,
                    facts=[ClaimItem(claim="模型猜测", confidence="confirmed")],
                )
            ]

        def merge(self, results, recent):
            return ContinuationAnalysis(story_overview="总览")

    result = run_continuation_analysis(
        store, session.session_id, UnsupportedChapterAnalyzer()
    )

    assert result.needs_confirmation[0].claim == "模型猜测"
    assert result.needs_confirmation[0].source.startswith("chapter.")
    progress = store.get(session.session_id).analysis_progress["chapter_results"][0]
    assert progress["needs_confirmation"][0]["claim"] == "模型猜测"


@pytest.mark.parametrize("bad_ref", ["missing", "range", "quote"])
def test_invalid_or_missing_confirmed_evidence_is_downgraded(
    tmp_path: Path, bad_ref: str
) -> None:
    store, session = _store_with_chapters(tmp_path, count=1)

    class EvidenceAnalyzer(FakeAnalyzer):
        def merge(self, results, recent):
            evidence = []
            if bad_ref == "missing":
                evidence = [EvidenceRef(chapter_id="not-a-chapter", excerpt_start=0, excerpt_end=1)]
            elif bad_ref == "range":
                evidence = [
                    EvidenceRef(
                        chapter_id=session.chapters[0].chapter_id,
                        excerpt_start=0,
                        excerpt_end=len(session.chapters[0].body) + 1,
                    )
                ]
            else:
                evidence = [
                    EvidenceRef(
                        chapter_id=session.chapters[0].chapter_id,
                        excerpt_start=0,
                        excerpt_end=2,
                        quote="不匹配",
                    )
                ]
            return ContinuationAnalysis(
                story_overview="总览",
                world=[ClaimItem(claim="待核事实", confidence="confirmed", evidence=evidence)],
            )

    result = run_continuation_analysis(store, session.session_id, EvidenceAnalyzer())

    assert result.world[0].confidence == "inferred"
    assert result.world[0].evidence == []
    assert result.needs_confirmation[0].claim == "待核事实"
    assert result.needs_confirmation[0].source == "world.0"


def test_inferred_claim_with_only_invalid_evidence_is_flagged(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=1)

    class InferredEvidenceAnalyzer(FakeAnalyzer):
        def merge(self, results, recent):
            return ContinuationAnalysis(
                story_overview="总览",
                power_system=[
                    ClaimItem(
                        claim="疑似规则",
                        confidence="inferred",
                        evidence=[
                            EvidenceRef(
                                chapter_id="missing", excerpt_start=0, excerpt_end=1
                            )
                        ],
                    )
                ],
            )

    result = run_continuation_analysis(
        store, session.session_id, InferredEvidenceAnalyzer()
    )

    assert result.power_system[0].evidence == []
    assert result.needs_confirmation[0].source == "power_system.0"


def test_ready_is_idempotent_and_cancelled_is_rejected(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path)
    first_analyzer = FakeAnalyzer()
    expected = run_continuation_analysis(store, session.session_id, first_analyzer)
    revision = store.get(session.session_id).revision

    ready_analyzer = FakeAnalyzer()
    second = run_continuation_analysis(store, session.session_id, ready_analyzer)

    assert second == expected
    assert store.get(session.session_id).revision == revision
    assert ready_analyzer.batch_calls == []
    assert ready_analyzer.merge_calls == []

    store2, session2 = _store_with_chapters(tmp_path / "cancelled")
    store2.update(session2.session_id, lambda current: setattr(current, "status", "cancelled"))
    with pytest.raises(ValueError, match="^continuation_analysis_cancelled$"):
        run_continuation_analysis(store2, session2.session_id, FakeAnalyzer())


def test_ready_with_changed_fingerprint_reanalyzes_only_changed_chapter(
    tmp_path: Path,
) -> None:
    store, session = _store_with_chapters(tmp_path, count=3)
    run_continuation_analysis(store, session.session_id, FakeAnalyzer())
    ready = store.get(session.session_id)
    changed_body = "第二章已经修改"
    changed_chapters = list(ready.chapters)
    changed_chapters[1] = changed_chapters[1].model_copy(
        update={
            "body": changed_body,
            "fingerprint": hashlib.sha256(changed_body.encode("utf-8")).hexdigest(),
        }
    )
    store.replace_chapters(
        ready.session_id, changed_chapters, expected_revision=ready.revision
    )

    class UpdatedMergeAnalyzer(FakeAnalyzer):
        def merge(self, chapter_results, recent_chapters):
            self.merge_calls.append((chapter_results, recent_chapters))
            return ContinuationAnalysis(story_overview=recent_chapters[1].body)

    analyzer = UpdatedMergeAnalyzer()
    result = run_continuation_analysis(store, session.session_id, analyzer)

    assert [[chapter.number for chapter in batch] for batch in analyzer.batch_calls] == [[2]]
    assert len(analyzer.merge_calls) == 1
    assert result.story_overview == changed_body
    loaded = store.get(session.session_id)
    assert loaded.status == "ready"
    assert loaded.analysis_progress["chapter_fingerprints"] == {
        chapter.chapter_id: chapter.fingerprint for chapter in loaded.chapters
    }


@pytest.mark.parametrize("batch_size", [0, -1])
def test_invalid_batch_size_is_rejected(tmp_path: Path, batch_size: int) -> None:
    store, session = _store_with_chapters(tmp_path)
    with pytest.raises(ValueError, match="^invalid_batch_size$"):
        run_continuation_analysis(store, session.session_id, FakeAnalyzer(), batch_size=batch_size)


def test_revision_conflict_does_not_overwrite_concurrent_change(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=1)

    class ConcurrentAnalyzer(FakeAnalyzer):
        def analyze_chapters(self, chapters):
            result = super().analyze_chapters(chapters)
            store.update(
                session.session_id,
                lambda current: current.analysis_progress.update(concurrent="kept"),
            )
            return result

    with pytest.raises(ValueError, match="^session_revision_conflict$"):
        run_continuation_analysis(store, session.session_id, ConcurrentAnalyzer())

    assert store.get(session.session_id).analysis_progress["concurrent"] == "kept"


def test_chinese_analysis_round_trips_through_store(tmp_path: Path) -> None:
    store, session = _store_with_chapters(tmp_path, count=1)
    run_continuation_analysis(store, session.session_id, FakeAnalyzer())
    raw = json.loads(
        (tmp_path / "sessions" / session.session_id / "session.json").read_text(encoding="utf-8")
    )
    assert raw["analysis"]["story_overview"] == "故事总览"


def _runtime():
    return type(
        "Runtime",
        (),
        {
            "provider": "openai",
            "model": "test-model",
            "api_key": "key",
            "base_url": "https://example.invalid",
            "codex_command": "",
            "temperature": 0.2,
        },
    )()


def test_llm_analyzer_rejects_invalid_json_stably() -> None:
    analyzer = LLMContinuationAnalyzer(
        post_json=lambda *args, **kwargs: {"choices": [{"message": {"content": "not json"}}]},
        runtime_resolver=lambda stage: _runtime(),
    )
    chapter = ContinuationChapter(
        chapter_id="c2",
        number=2,
        title="第二章",
        body="只有本章正文",
        source_name="2.txt",
        fingerprint="x",
    )

    with pytest.raises(ValueError, match="^continuation_analysis_invalid_response$"):
        analyzer.analyze_chapters([chapter])


def test_llm_batch_prompt_contains_only_requested_chapters() -> None:
    payloads = []

    def post_json(*args, **kwargs):
        payloads.append(args[2])
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "chapters": [
                                    {
                                        "chapter_id": "c2",
                                        "summary": "中文摘要",
                                        "characters": [],
                                        "facts": [],
                                        "locations": [],
                                        "timeline_events": [],
                                        "power_changes": [],
                                        "hooks": [],
                                        "evidence": [],
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    analyzer = LLMContinuationAnalyzer(post_json=post_json, runtime_resolver=lambda stage: _runtime())
    chapter = ContinuationChapter(
        chapter_id="c2",
        number=2,
        title="第二章",
        body="仅第二章正文",
        source_name="2.txt",
        fingerprint="x",
    )

    analyzer.analyze_chapters([chapter])

    prompt = payloads[0]["messages"][1]["content"]
    assert "仅第二章正文" in prompt
    assert "无关旧章正文" not in prompt
    assert "JSON" in payloads[0]["messages"][0]["content"]
    context = json.loads(prompt)
    assert context["body_char_count"] == len(chapter.body)
    assert context["body_char_budget"] >= context["body_char_count"]
    assert "Unicode code point" in " ".join(context["rules"])


def test_llm_merge_prompt_is_bounded_omits_old_body_and_keeps_latest_tail() -> None:
    payloads = []

    def post_json(*args, **kwargs):
        payloads.append(args[2])
        content = ContinuationAnalysis(story_overview="合并完成").model_dump(mode="json")
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    analyzer = LLMContinuationAnalyzer(
        post_json=post_json,
        runtime_resolver=lambda stage: _runtime(),
        merge_char_budget=3000,
        recent_body_char_budget=400,
    )
    chapters = [
        ContinuationChapter(
            chapter_id=f"c{number}",
            number=number,
            title=f"第{number}章",
            body=(
                "UNRELATED_OLD_BODY"
                if number == 1
                else ("最新章节前文" * 100 + "LATEST_END" if number == 12 else f"正文-{number}")
            ),
            source_name=f"{number}.txt",
            fingerprint=f"fp-{number}",
        )
        for number in range(1, 13)
    ]
    results = [
        ChapterAnalysis(
            chapter_id=chapter.chapter_id,
            summary=f"摘要-{chapter.number}-" + "详" * 1000,
        )
        for chapter in chapters
    ]

    merged = analyzer.merge(results, chapters)

    assert merged.story_overview == "合并完成"
    messages = payloads[0]["messages"]
    assert sum(len(message["content"]) for message in messages) <= 3000
    prompt = messages[1]["content"]
    assert "UNRELATED_OLD_BODY" not in prompt
    assert "LATEST_END" in prompt
    assert "[TRUNCATED_TO_RECENT_TAIL]" in prompt
    context = json.loads(prompt)
    assert sum(len(item["body_excerpt"]) for item in context["recent_chapters"]) <= 400
