"""Test-only FastAPI entrypoint with deterministic model and chapter generation."""

from __future__ import annotations

import json
import os
import sys
import threading
import types
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any


if os.getenv("NOVELFLOW_E2E_SYNTHETIC") != "1":
    raise RuntimeError(
        "Synthetic model injection is available only from the dedicated integration config."
    )


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _use_repository_test_namespace() -> None:
    """Resolve repository fixtures instead of an unrelated site-packages `tests`."""

    package = types.ModuleType("tests")
    package.__path__ = [str(REPOSITORY_ROOT / "tests")]
    package.__package__ = "tests"
    sys.modules["tests"] = package


_use_repository_test_namespace()

from packages.story_core.engine import ChapterBundle  # noqa: E402
from packages.story_core.model_gateway import ModelResponse  # noqa: E402
from packages.story_core.novel_type_catalog import (  # noqa: E402
    novel_type_prompt_context,
    runtime_novel_type,
)
from tests.story_core.test_opening_build import opening_payloads  # noqa: E402

from apps.api.routes import file_projects as file_project_routes  # noqa: E402


_event_lock = threading.Lock()
_payloads = opening_payloads()
_synthetic_runtime = SimpleNamespace(
    provider_id="synthetic-e2e",
    protocol="openai_compatible",
    model="synthetic-e2e-model",
    api_key="",
    base_url="http://127.0.0.1/synthetic-only",
    temperature=0.0,
    user_declared_capabilities={},
)


def _append_json_line(path_value: str | None, item: dict[str, Any]) -> None:
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    with _event_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(serialized + "\n")


def _record_synthetic_event(**event: Any) -> None:
    _append_json_line(os.getenv("NOVELFLOW_E2E_SYNTHETIC_AUDIT_LOG"), event)


class SyntheticOpeningDirectionGenerator:
    def generate(self, brief: Any, *, guidance: str = "") -> dict[str, Any]:
        genre = runtime_novel_type(brief.novel_type_id)
        context = novel_type_prompt_context(genre) if genre is not None else {}
        trope_candidates = context.get("genre_trope_templates", [])
        trope_id = next(
            (
                str(item.get("id"))
                for item in trope_candidates
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ),
            None,
        )
        _record_synthetic_event(
            kind="opening_directions",
            novel_type_id=str(brief.novel_type_id),
            guidance_length=len(guidance),
        )
        directions = []
        for index, title in enumerate(("雨夜遗嘱", "被改写的账本", "失联证人的签名"), start=1):
            directions.append(
                {
                    "id": f"synthetic-direction-{index}",
                    "title": title,
                    "hook": "一份写着次日日期的遗嘱在雨夜送到律师门前。",
                    "logline": "失业律师必须核清一笔被改写的旧账，才能证明遗嘱不是伪造。",
                    "protagonist_profile": "一名擅长核对档案、却不再信任同行的失业律师。",
                    "inciting_incident": "陌生人的遗嘱要求他在天亮前找到旧账原件。",
                    "protagonist_goal": "查清旧账的真正债主。",
                    "main_conflict": "前同事封锁档案，并把律师指成伪造者。",
                    "failure_stakes": "证据会被销毁，律师也会背上伪造遗嘱的罪名。",
                    "growth_path": "从自保转向公开承担查明真相的代价。",
                    "excitement_point": "每个对不上日期的签名都指向一名新的证人。",
                    "target_audience": "喜欢都市悬疑和职业查案的读者。",
                    "reader_promise": "每笔旧账都会带来一个可核实的结果和新的压力。",
                    "ending_direction": "主角公开完整证据，并重建自己的事务所。",
                    "opening_promise": "一份遗嘱将牵出被改写的人生记录。",
                    "primary_trope_id": trope_id,
                    "core_advantage": {
                        "name": "档案检索",
                        "type": "信息优势",
                        "ability": "提前发现账目日期和签名之间的矛盾。",
                        "growth_rule": "每次核验都增加一条可追溯的证据链。",
                        "limits": "一次只能核清一份原始记录。",
                        "early_payoff": "识破第一处被涂改的日期。",
                    },
                    "central_mystery": {
                        "surface_anomaly": "遗嘱日期比档案中的签署日期早一天。",
                        "hidden_truth": "有人重写债务记录以替换真正的债主。",
                        "reality_impact": "证人被误认为债务人，原债主因此失踪。",
                        "reveal_path": ["核对遗嘱底稿", "找到旧账原件"],
                    },
                    "initial_drive": {
                        "immediate_need": "洗清伪造遗嘱的嫌疑。",
                        "trigger": "遗嘱要求他在天亮前找到旧账原件。",
                        "short_term_goal": "找到并验证旧账原件。",
                        "failure_stakes": "他会失去执业资格，证人也会失联。",
                        "long_term_transition": "从替陌生人查案转向公开整条利益链。",
                    },
                }
            )
        return {
            "schema_version": "opening-directions/v1",
            "directions": directions,
            "selected_id": "",
        }


class SyntheticModelGateway:
    """Return repository-valid task fixtures without contacting any provider."""

    def complete_stage(self, _stage: str, request: Any) -> Any:
        task_id = str((getattr(request, "metadata", {}) or {}).get("world_build_task") or "")
        if not task_id:
            task_id = str(getattr(request, "operation", "")).rsplit("_", 1)[-1]
        if task_id.startswith("chapter_outline_"):
            number = int(task_id.rsplit("_", 1)[1])
            payload = deepcopy(_payloads["chapter_outline_3"])
            payload["chapter"].update(
                chapter_number=number,
                title=f"律师核账的第{number}步",
            )
        elif task_id in _payloads:
            payload = deepcopy(_payloads[task_id])
        else:
            raise RuntimeError(f"No synthetic output fixture for {task_id!r}.")
        if task_id == "book_outline":
            payload["overall"].update(
                core_ending_chapter=3,
                extension_ceiling_chapter=3,
                planned_length=3,
                planned_arc_count=1,
            )
        elif task_id == "volume_plan":
            first = payload["arcs"][0]
            first.update(end_chapter=3, is_final_arc=True)
            node = deepcopy(first["story_nodes"][0])
            first["story_nodes"] = [{**node, "start_chapter": 1, "end_chapter": 3}]
        elif task_id == "event_chains":
            volume_plan = deepcopy(_payloads["volume_plan"]["arcs"][0])
            volume_plan.update(end_chapter=3, is_final_arc=True)
            node = deepcopy(volume_plan["story_nodes"][0])
            volume_plan["story_nodes"] = [{**node, "start_chapter": 1, "end_chapter": 3}]
            payload["event_chains"] = [
                {"arc_id": arc["id"], "nodes": deepcopy(arc["story_nodes"])}
                for arc in (volume_plan,)
            ]
        _record_synthetic_event(kind="model", task_id=task_id)
        return replace(
            ModelResponse.success(
                request,
            text=json.dumps(payload, ensure_ascii=False),
            raw={"synthetic_fixture": True},
            ),
            provider="synthetic-e2e",
            model="synthetic-e2e-model",
            resolved_model="synthetic-e2e-model",
        )


class SyntheticCandidateGenerator:
    """Small fake generator injected at StoryEngine construction in this process."""

    def __init__(self, *args: Any, project_root: str | Path | None = None, **kwargs: Any) -> None:
        del args, kwargs
        if project_root is None:
            isolated_projects = os.getenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR")
            if not isolated_projects:
                raise RuntimeError("The integration generator requires the isolated project root.")
            # apps.api.routes.stories creates a process-level engine while the
            # FastAPI app imports. File-project generation passes its real
            # isolated project root explicitly; this inert fallback remains
            # inside the dedicated run root if another route constructs it.
            project_root = Path(isolated_projects) / "synthetic-global-engine-unused"
        self.project_root = Path(project_root).resolve()

    def generate_next_chapter(self, story: Any, **kwargs: Any) -> ChapterBundle:
        del kwargs
        chapter_number = int(story.current_chapter or 0) + 1
        state_path = self.project_root / ".story-system" / "integration-generator-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {"calls_by_chapter": {}}
        calls = state.setdefault("calls_by_chapter", {})
        chapter_calls = int(calls.get(str(chapter_number), 0)) + 1
        calls[str(chapter_number)] = chapter_calls
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

        hard_blocked = chapter_number == 1 and chapter_calls == 1
        paragraph = f"律师核对第{chapter_number}章的旧账编号与签名，记录来源已逐项确认。"
        body = "\n\n".join([paragraph] * 165)
        if not 3800 <= len(body) <= 5500:
            raise AssertionError(f"Synthetic chapter body length is outside the accepted fixture range: {len(body)}")

        quality_report = {
            "ok": not hard_blocked,
            "issues": ["canon.hard_blocker"] if hard_blocked else [],
            "writing_review": {
                "pass": not hard_blocked,
                "blocking": (
                    [
                        {
                            "code": "canon.hard_blocker",
                            "message": "合成 Canon blocker：遗嘱日期与已确认时间线冲突。",
                            "source": "canon",
                            "evidence": "synthetic-confirmed-timeline",
                        }
                    ]
                    if hard_blocked
                    else []
                ),
                "warnings": [],
            },
            "modular_pipeline": {
                "canon_review_snapshot": {
                    "as_of_chapter": int(story.current_chapter or 0),
                    "state_source": "synthetic-confirmed-state",
                    "bounded_state_available": True,
                },
                "canon_preflight": {
                    "requested": ["遗嘱日期"],
                    "prepared": ["遗嘱日期"],
                    "missing": [],
                },
            },
        }
        _record_synthetic_event(
            kind="candidate",
            project_root=self.project_root.name,
            chapter_number=chapter_number,
            call=chapter_calls,
            hard_blocked=hard_blocked,
        )
        return ChapterBundle(
            chapter_number=chapter_number,
            chapter_title=f"合成第{chapter_number}章",
            body=body,
            next_outline=f"继续核对第{chapter_number + 1}章的账目。",
            updated_story=story.model_copy(deep=True),
            chapter_summary={
                "chapter_number": chapter_number,
                "summary": f"律师逐项核对第{chapter_number}章涉及的旧账记录。",
                "facts": [],
                "unresolved_threads": [],
            },
            quality_report=quality_report,
            context_snapshot_id=f"synthetic-e2e-context-{chapter_number}",
        )


file_project_routes.opening_direction_generator = SyntheticOpeningDirectionGenerator()
file_project_routes.shuangwen_model_gateway = SyntheticModelGateway()
file_project_routes.resolve_stage_runtime = lambda _stage: _synthetic_runtime

import packages.story_core.engine as story_engine_module  # noqa: E402

story_engine_module.StoryEngine = SyntheticCandidateGenerator

from apps.api.main import app  # noqa: E402


@app.middleware("http")
async def mark_and_audit_integration_api_requests(request: Any, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["x-novelflow-integration-server"] = "synthetic"
    if request.url.path != "/health":
        _append_json_line(
            os.getenv("NOVELFLOW_E2E_API_REQUESTS_LOG"),
            {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "user_agent": request.headers.get("user-agent", ""),
            },
        )
    return response
