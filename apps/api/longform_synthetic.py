"""Explicitly isolated offline author-workspace development server.

Run only with NOVELFLOW_LONGFORM_SYNTHETIC=1. No existing novel is loaded,
no chapter is prefilled, and each click uses the normal job/agent/confirmation
services. Model responses are deterministic fixtures, not writing-quality proof.
The repository's development dependencies (including pytest fixture imports)
are required. Importing fixture factories does not execute their test suites.

PowerShell, from the repository root:
    $env:NOVELFLOW_LONGFORM_SYNTHETIC='1'
    python -m uvicorn apps.api.longform_synthetic:app --host 127.0.0.1 --port 8531

Optionally set NOVELFLOW_LONGFORM_SYNTHETIC_ROOT to a new empty directory to
keep synthetic books across restarts; otherwise each process gets a new temp
directory, whose location is printed at startup. Do not use uvicorn workers or
reload: this entrypoint is intentionally one isolated development process.
NOVELFLOW_LONGFORM_SYNTHETIC_FAIL_ONCE='writer:17,consistency:18' injects a
persisted one-time model failure for explicit recovery exercises.

The fixtures support the 通用网文 genre, chapters 1-100, and two 50-chapter
volumes. They do not model arbitrary creative requirements or establish prose
quality. Settings, imports and unrelated machine APIs are deliberately closed.
No tests, startup or end-to-end runs are implied by this implementation.
"""
from __future__ import annotations

from copy import copy, deepcopy
import json
import ipaddress
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from threading import RLock
import types


if os.environ.get("NOVELFLOW_LONGFORM_SYNTHETIC") != "1":
    raise RuntimeError("Set NOVELFLOW_LONGFORM_SYNTHETIC=1 for this isolated offline entrypoint.")

ROOT_MARKER = "novelflow-longform-synthetic/v1"
configured_root = os.environ.get("NOVELFLOW_LONGFORM_SYNTHETIC_ROOT", "").strip()
if configured_root:
    ROOT = Path(configured_root).expanduser().resolve()
    marker = ROOT / ".longform-synthetic-root"
    if marker.is_symlink():
        raise RuntimeError("The synthetic marker must be a regular file.")
    if ROOT.exists() and any(ROOT.iterdir()) and (not marker.is_file() or marker.read_text(encoding="utf-8") != ROOT_MARKER):
        raise RuntimeError("The explicit synthetic root must be empty or already marked by this entrypoint.")
    ROOT.mkdir(parents=True, exist_ok=True)
else:
    ROOT = Path(tempfile.mkdtemp(prefix="novelflow-longform-synthetic-")).resolve()
(ROOT / ".longform-synthetic-root").write_text(ROOT_MARKER, encoding="utf-8")

# Set every mutable global store before importing the application's modules.
# Existing real export/runtime/database variables are intentionally overridden.
for key, relative in {
    "NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR": "projects",
    "NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH": "runtime.json",
    "NOVEL_AUTOGROWTH_CAPABILITY_CACHE_PATH": "capabilities.json",
    "NOVEL_AUTOGROWTH_DB_PATH": "stories.db",
    "STORY_DB_PATH": "stories.db",
    "NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH": "novel-types.json",
    "NOVEL_PROMPT_TEMPLATES_PATH": "prompt-templates.json",
}.items():
    os.environ[key] = str(ROOT / relative)
(ROOT / "projects").mkdir(exist_ok=True)
os.environ["NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS"] = str(ROOT / "projects")
os.environ["NOVEL_AUTOGROWTH_CORS_ORIGINS"] = ",".join(
    f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in (3000, 3530))
if any(path.is_symlink() or getattr(path, "is_junction", lambda: False)() for path in ROOT.rglob("*")):
    raise RuntimeError("Synthetic projects must not link to directories outside their isolated root.")


def _offline_only(*args, **kwargs):
    raise PermissionError("External connections and commands are disabled in the synthetic development server.")


# Windows asyncio uses loopback socket pairs for its own wakeups. Preserve
# those local connections while denying outbound addresses. Model transports
# are independently replaced below, and unrelated public routes are closed.
_socket_connect = socket.socket.connect
_socket_connect_ex = socket.socket.connect_ex


def _local_connect(original, sock, address):
    if sock.family == getattr(socket, "AF_UNIX", None):
        return original(sock, address)
    if isinstance(address, tuple):
        try:
            if ipaddress.ip_address(address[0]).is_loopback:
                return original(sock, address)
        except ValueError:
            pass
    return _offline_only()


socket.socket.connect = lambda sock, address: _local_connect(_socket_connect, sock, address)
socket.socket.connect_ex = lambda sock, address: _local_connect(_socket_connect_ex, sock, address)
socket.create_connection = _offline_only
subprocess.Popen = _offline_only

REPOSITORY = Path(__file__).resolve().parents[2]
package = types.ModuleType("tests")
package.__path__ = [str(REPOSITORY / "tests")]
package.__package__ = "tests"
sys.modules["tests"] = package

from tests.story_core.test_opening_build import opening_payloads  # noqa: E402
from packages.story_core import runtime_config  # noqa: E402
from packages.story_core.model_gateway import RuntimeModelGateway  # noqa: E402
from packages.story_core.model_gateway.capabilities import ModelCapabilityResolver, ModelCapabilityStore  # noqa: E402


SETTINGS = runtime_config.StageRuntimeSettings(
    provider_id="custom_openai", protocol="openai_compatible", model="offline-longform-fixture",
    api_key="synthetic-not-a-credential", base_url="http://synthetic.invalid/v1", temperature=0.0,
    user_declared_capabilities={"capabilities": {"json_mode": "supported", "temperature": "supported"},
                               "limits": {"context_window": 2000000, "input_token_limit": 1900000, "max_output_tokens": 100000}},
)
runtime_config.resolve_stage_runtime = lambda stage: SETTINGS.model_copy(deep=True)

PAYLOADS = opening_payloads()
# Plans contain two real volume ranges;正文 remains empty until the author
# explicitly generates and confirms each chapter through the application.
PAYLOADS["book_outline"]["overall"].update(core_ending_chapter=100, extension_ceiling_chapter=100,
    planned_length=100, planned_arc_count=2)
first_arc = deepcopy(PAYLOADS["volume_plan"]["arcs"][0])
arcs = []
for index, start in enumerate((1, 51), 1):
    arc = deepcopy(first_arc)
    arc.update(id=f"synthetic-volume-{index}", title=f"第{index}卷·旧档查证", start_chapter=start,
               end_chapter=start + 49, is_final_arc=index == 2)
    node = deepcopy(first_arc["story_nodes"][0])
    arc["story_nodes"] = [{**node, "start_chapter": n, "end_chapter": min(n + 14, start + 49)}
                          for n in range(start, start + 50, 15)]
    arcs.append(arc)
PAYLOADS["volume_plan"] = {"arcs": arcs}
PAYLOADS["event_chains"] = {"event_chains": [{"arc_id": arc["id"], "nodes": deepcopy(arc["story_nodes"])} for arc in arcs]}

_audit_lock = RLock()


def audit(kind, number, task=""):
    with _audit_lock:
        with (ROOT / "model-calls.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps({"kind": kind, "chapter": number, "task": task, "synthetic": True}, ensure_ascii=False) + "\n")


def _fail_once(operation, chapter):
    requested = {part.strip() for part in os.environ.get("NOVELFLOW_LONGFORM_SYNTHETIC_FAIL_ONCE", "").split(",") if part.strip()}
    key = f"{operation}:{chapter}"
    if key not in requested:
        return
    with _audit_lock:
        path = ROOT / "injected-failures.json"
        used = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if key in used:
            return
        used.append(key)
        path.write_text(json.dumps(used), encoding="utf-8")
    raise RuntimeError("synthetic_injected_failure")


def _chapter_payload(number):
    if not 1 <= number <= 100:
        raise RuntimeError("Synthetic planning supports chapters 1 through 100 only.")
    chapter = deepcopy(PAYLOADS["chapter_outline_3"]["chapter"])
    chapter.update(chapter_number=number, title=f"第{number}次核验", cast=["林照", "周满"])
    # Keep the full schema; align the fixture's older example name with its cast.
    return json.loads(json.dumps({"chapter": chapter}, ensure_ascii=False).replace("林修", "林照"))


def _model_content(request):
    metadata = dict(request.metadata or {})
    operation = str(metadata.get("agent") or request.operation or "")
    chapter = int(metadata.get("chapter_number") or 1)
    task = str(metadata.get("world_build_task") or "")
    if not task:
        match = re.search(r"chapter_outline_\d+", str(request.operation))
        task = match.group(0) if match else next((key for key in PAYLOADS if str(request.operation).endswith("_" + key)), "")
    audit(operation, chapter, task)
    _fail_once(operation, chapter)
    if task:
        if task.startswith("chapter_outline_"):
            return json.dumps(_chapter_payload(int(task.rsplit("_", 1)[1])), ensure_ascii=False)
        if task not in PAYLOADS:
            raise RuntimeError("No synthetic response is defined for this planning task.")
        return json.dumps(deepcopy(PAYLOADS[task]), ensure_ascii=False)
    if operation == "character":
        return json.dumps({"proposals": [{"name": name, "goal": "保留可核对的证据", "emotion": "谨慎",
            "action": "核对账册并留下记录", "priority": 3, "target": "旧账原件", "trigger": "收到清点任务",
            "speech_strategy": "先说明记录的来源", "blocked_reaction": "保留副本再核验"}
            for name in ("林照", "赵衡", "周满") if name in request.prompt]}, ensure_ascii=False)
    if operation == "director":
        locked = re.search(r"本章细纲标题已经锁定，原样复制，不得重命名：([^\n]+)", request.prompt)
        return json.dumps({"chapter_number": chapter, "chapter_title": locked.group(1).strip() if locked else f"第{chapter}次核验",
            "chapter_goal": "查清旧档中的一项差异", "opening_state": "林照正在核对已有记录",
            "scene_beats": [{"order": 1, "location": "祖祠", "action": "林照核对旧账的日期", "result": "保留一份可复查的记录"},
                            {"order": 2, "location": "祖祠", "action": "周满协助逐项抄录", "result": "两人约定继续核查原件"}],
            "ending_state": "原有证据保留，下一项记录仍需核查", "hook": "有人提前找过青砖", "entity_requirements": []}, ensure_ascii=False)
    if operation in {"consistency", "canon_review"}:
        # This is an injected reviewer response. Deterministic hard gates still run.
        return json.dumps({"issues": []})
    if operation == "writer":
        phrase = f"林照翻到第{chapter}章要核对的那页旧档，把已知日期重新抄在纸上。周满等他写完，才将原件递过去。两人只记录能核实的内容，不能确定的地方另留一行，等下次找到依据再补。他把纸页压平，没有改动已经留下的记录。"
        if "请按作者要求修改下面的候选" in request.prompt:
            phrase = "林照先把记录的出处写清，又将原件和抄件分开放好。" + phrase
        length = re.search(r"正文目标(\d+)至(\d+)字", request.prompt)
        target = (int(length.group(1)) + int(length.group(2))) // 2 if length else 4300
        body = "\n\n".join([phrase] * max(1, (target - 80) // (len(phrase) + 2)))
        hook = re.search(r"计划章末钩子[：:]([^\n]+)", request.prompt)
        return body + "\n\n" + (hook.group(1).strip() if hook else "有人提前找过青砖。")
    raise RuntimeError("No synthetic response is defined for this model operation.")


_real_init = RuntimeModelGateway.__init__
_real_complete = RuntimeModelGateway.complete_resolved


def _synthetic_init(self, stage=None, **kwargs):
    # Every instance in this dedicated process receives the same isolated
    # local capability store. No user provider settings are consulted.
    kwargs.update(runtime_resolver=lambda stage: SETTINGS.model_copy(deep=True),
        capability_resolver=ModelCapabilityResolver(store=ModelCapabilityStore(ROOT / "capabilities.json")))
    _real_init(self, stage, **kwargs)


def _synthetic_complete(self, settings, request):
    local = copy(self)
    def transport(**kwargs):
        content = _model_content(request)
        return {"model": SETTINGS.model, "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    local.transport = transport
    # Preserve the real profile resolution, preflight, native HTTP adapter and
    # response parsing. Only the transport returns an in-memory response.
    return _real_complete(local, SETTINGS.model_copy(deep=True), request)


RuntimeModelGateway.__init__ = _synthetic_init
RuntimeModelGateway.complete_resolved = _synthetic_complete


class OpeningDirections:
    def generate(self, brief, *, guidance=""):
        from packages.story_core.novel_type_catalog import novel_type_prompt_context, runtime_novel_type
        audit("opening_directions", 0)
        _fail_once("opening_directions", 0)
        overall = PAYLOADS["book_outline"]["overall"]
        genre = runtime_novel_type(brief.novel_type_id)
        context = novel_type_prompt_context(genre) if genre else {}
        trope = next((item["id"] for item in context.get("genre_trope_templates", []) if isinstance(item, dict) and item.get("id")), None)
        directions = []
        for index, title in enumerate(("祖祠旧档", "青砖上的记录", "被封存的名字"), 1):
            directions.append({"id": f"offline-direction-{index}", "title": title,
                "hook": "一份旧名册出现了可以核对的差异。", "logline": overall["story"],
                "protagonist_profile": "林照，负责记录和核验的外门弟子。", "inciting_incident": "祖祠清点时发现旧记录不一致。",
                "protagonist_goal": overall["protagonist_goal"], "main_conflict": overall["main_conflict"],
                "failure_stakes": "旧档会被封存，已有证据难以公开。", "growth_path": overall["growth_path"],
                "excitement_point": "每次核对都有可追溯的结果。", "target_audience": "喜欢查证过程的读者。",
                "reader_promise": "每项线索有依据，每次选择保留后果。", "ending_direction": overall["ending_direction"],
                "opening_promise": "从一页旧档追查宗门旧案。", "primary_trope_id": trope,
                "core_advantage": {"name": "核验记录", "type": "信息", "ability": "比较已有记录", "growth_rule": "积累证据", "limits": "不能推断缺失内容", "early_payoff": "保住一份副本"},
                "central_mystery": {"surface_anomaly": "名册不一致", "hidden_truth": "旧档曾被替换", "reality_impact": "相关人的身份受到影响", "reveal_path": ["核对日期", "查找副本"]},
                "initial_drive": {"immediate_need": "保住旧档", "trigger": "收到封档通知", "short_term_goal": "核对第一页", "failure_stakes": "原件失去查阅机会", "long_term_transition": "公开旧案"}})
        return {"schema_version": "opening-directions/v1", "directions": directions, "selected_id": ""}


from apps.api.routes import file_projects  # noqa: E402

file_projects.opening_direction_generator = OpeningDirections()
file_projects.resolve_stage_runtime = lambda stage: SETTINGS.model_copy(deep=True)

from apps.api.main import app  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402


@app.middleware("http")
async def synthetic_boundary(request, call_next):
    # The full application's internal route callbacks remain available to the
    # product adapter. Public unrelated/import/probe APIs are not exposed here.
    if request.url.path not in {"/health", "/author-workspace", "/author-workspace/commands"}:
        return JSONResponse(status_code=403, content={"detail": "离线开发入口仅开放四页创作工作区。"})
    response = await call_next(request)
    if request.method == "GET" and request.url.path == "/author-workspace" and response.status_code == 200:
        raw = b"".join([part async for part in response.body_iterator])
        payload = json.loads(raw)
        payload["storageWarning"] = "离线开发数据：模型回答由固定样例提供，不代表真实写作质量。"
        # The supplied plan fixtures are genre-neutral. Other genre validators
        # are intentionally not represented as covered by this development app.
        payload["genres"] = [item for item in payload.get("genres", []) if item["value"] == "generic_webnovel"]
        response = JSONResponse(payload, headers={key: value for key, value in response.headers.items() if key.lower() not in {"content-length", "content-type"}})
    response.headers["x-novelflow-synthetic"] = "longform-offline"
    return response


print(f"Offline synthetic workspace: {ROOT}")
