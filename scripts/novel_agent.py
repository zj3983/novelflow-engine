from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import urllib.parse
import urllib.request
import urllib.error


DEFAULT_API_BASE = "http://127.0.0.1:8000"


def _ensure_utf8_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def _context_url(api_base: str, project_id: str, recent_chapters: int, include_body: bool) -> str:
    base = api_base.rstrip("/")
    encoded_project_id = urllib.parse.quote(project_id, safe="")
    query = urllib.parse.urlencode(
        {
            "recent_chapters": recent_chapters,
            "include_body": "true" if include_body else "false",
        }
    )
    return f"{base}/projects/{encoded_project_id}/agent-context?{query}"


def _review_url(api_base: str, project_id: str, chapter_number: int | None, include_body: bool) -> str:
    base = api_base.rstrip("/")
    encoded_project_id = urllib.parse.quote(project_id, safe="")
    query_params: dict[str, int | str] = {}
    if chapter_number is not None:
        query_params["chapter_number"] = chapter_number
    query_params["include_body"] = "true" if include_body else "false"
    query = urllib.parse.urlencode(query_params)
    return f"{base}/projects/{encoded_project_id}/agent-review?{query}"


def _revise_url(api_base: str, project_id: str) -> str:
    base = api_base.rstrip("/")
    encoded_project_id = urllib.parse.quote(project_id, safe="")
    return f"{base}/projects/{encoded_project_id}/agent-revise"


def _project_url(api_base: str, project_id: str) -> str:
    base = api_base.rstrip("/")
    encoded_project_id = urllib.parse.quote(project_id, safe="")
    return f"{base}/projects/{encoded_project_id}"


def _writing_packet_url(api_base: str, project_id: str, chapter_number: int | None) -> str:
    base = api_base.rstrip("/")
    encoded_project_id = urllib.parse.quote(project_id, safe="")
    query_params: dict[str, int] = {}
    if chapter_number is not None:
        query_params["chapter_number"] = chapter_number
    query = urllib.parse.urlencode(query_params)
    suffix = f"?{query}" if query else ""
    if project_id.startswith("file:"):
        return f"{base}/file-projects/{encoded_project_id}/writing-packet{suffix}"
    return f"{base}/projects/{encoded_project_id}/writing-packet{suffix}"


def _story_generate_url(api_base: str, story_id: str) -> str:
    base = api_base.rstrip("/")
    encoded_story_id = urllib.parse.quote(story_id, safe="")
    return f"{base}/stories/{encoded_story_id}/generate"


def _story_generation_job_url(api_base: str, story_id: str, job_id: str | None = None) -> str:
    base = api_base.rstrip("/")
    encoded_story_id = urllib.parse.quote(story_id, safe="")
    if job_id is None:
        return f"{base}/stories/{encoded_story_id}/generation-jobs"
    encoded_job_id = urllib.parse.quote(job_id, safe="")
    return f"{base}/stories/{encoded_story_id}/generation-jobs/{encoded_job_id}"


def _read_json_response(request: urllib.request.Request, timeout: int) -> dict:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _json_request(url: str, *, method: str = "GET", payload: dict | None = None, timeout: int = 30) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if payload is not None:
        request.headers["Content-Type"] = "application/json"
    return _read_json_response(request, timeout)


def fetch_context(api_base: str, project_id: str, recent_chapters: int, include_body: bool) -> dict:
    url = _context_url(api_base, project_id, recent_chapters, include_body)
    request = urllib.request.Request(url, method="GET")
    return _read_json_response(request, 30)


def fetch_review(api_base: str, project_id: str, chapter_number: int | None, include_body: bool) -> dict:
    url = _review_url(api_base, project_id, chapter_number, include_body)
    request = urllib.request.Request(url, method="GET")
    return _read_json_response(request, 30)


def post_revision(
    api_base: str,
    project_id: str,
    chapter_number: int | None,
    instructions: list[str],
    include_body: bool,
) -> dict:
    url = _revise_url(api_base, project_id)
    payload = {
        "chapter_number": chapter_number,
        "instructions": instructions,
        "include_body": include_body,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    request.headers["Content-Type"] = "application/json"
    return _read_json_response(request, 300)


def fetch_project(api_base: str, project_id: str) -> dict:
    return _json_request(_project_url(api_base, project_id), timeout=30)


def patch_project(api_base: str, project_id: str, payload: dict) -> dict:
    return _json_request(_project_url(api_base, project_id), method="PATCH", payload=payload, timeout=30)


def fetch_writing_packet(api_base: str, project_id: str, chapter_number: int | None) -> dict:
    return _json_request(_writing_packet_url(api_base, project_id, chapter_number), timeout=30)


def generate_story_chapter(api_base: str, story_id: str) -> dict:
    job = _json_request(_story_generation_job_url(api_base, story_id), method="POST", timeout=30)
    job_id = str(job.get("job_id", ""))
    if not job_id:
        # Compatibility fallback for older backends without generation jobs.
        return _json_request(_story_generate_url(api_base, story_id), method="POST", timeout=900)
    return poll_generation_job(api_base, story_id, job_id, timeout_seconds=900)


def poll_generation_job(
    api_base: str,
    story_id: str,
    job_id: str,
    *,
    timeout_seconds: int,
    poll_interval: float = 2.0,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_job: dict = {}
    while time.monotonic() <= deadline:
        try:
            last_job = _json_request(_story_generation_job_url(api_base, story_id, job_id), timeout=30)
        except (TimeoutError, urllib.error.URLError):
            # Some dev servers become slow to answer status checks while the
            # generation worker is busy. Treat a single poll timeout as
            # "still running" as long as the overall deadline has not expired.
            time.sleep(poll_interval)
            continue
        status = str(last_job.get("status", ""))
        if status == "completed":
            return last_job
        if status == "failed":
            error = str(last_job.get("error", "")).strip() or "generation_failed"
            raise RuntimeError(error)
        time.sleep(poll_interval)
    raise TimeoutError(f"generation job timed out after {timeout_seconds}s: {last_job}")


def build_review_package(
    api_base: str,
    project_id: str,
    chapter_number: int | None,
    recent_chapters: int,
    include_body: bool,
) -> dict:
    context = fetch_context(api_base, project_id, recent_chapters, include_body)
    review = fetch_review(api_base, project_id, chapter_number, include_body)
    return {
        "schema_version": "openclaw-review-request/v1",
        "provider_target": "openclaw",
        "project_id": project_id,
        "expected_response_schema": "openclaw-review-result/v1",
        "context": context,
        "review": review,
        "instructions": {
            "role": "independent_webnovel_editor",
            "allowed_actions": ["approve", "revise", "pause"],
            "return_json_only": True,
        },
    }


def _load_json_object(raw: str, field_name: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def build_world_patch_payload(args: argparse.Namespace) -> dict:
    payload: dict[str, object] = {}
    if args.world_summary is not None:
        payload["world_summary"] = args.world_summary
    if args.current_focus is not None:
        payload["current_focus"] = args.current_focus
    if args.author_constraint:
        payload["author_constraints"] = args.author_constraint
    if args.world_blueprint_json is not None:
        payload["world_blueprint"] = _load_json_object(args.world_blueprint_json, "world_blueprint")
    if args.character_profile_json:
        payload["character_profiles"] = [
            _load_json_object(raw, "character_profile")
            for raw in args.character_profile_json
        ]
    if args.relationship_json:
        payload["relationship_graph"] = [
            _load_json_object(raw, "relationship")
            for raw in args.relationship_json
        ]
    if args.status is not None:
        payload["status"] = args.status
    if args.pipeline_stage is not None:
        payload["pipeline_stage"] = args.pipeline_stage
    return payload


def _active_story_id(context: dict) -> str:
    active_story = context.get("active_story")
    if isinstance(active_story, dict) and active_story.get("story_id"):
        return str(active_story["story_id"])
    project = context.get("project")
    if isinstance(project, dict) and project.get("active_story_id"):
        return str(project["active_story_id"])
    return ""


def _needs_initial_generation(context: dict) -> bool:
    active_story = context.get("active_story")
    recent_chapters = context.get("recent_chapters")
    if isinstance(active_story, dict) and int(active_story.get("current_chapter") or 0) <= 0:
        return True
    return isinstance(recent_chapters, list) and not recent_chapters


def _revision_instructions(intent: str, review: dict) -> list[str]:
    recommendation = review.get("recommendation", {}) if isinstance(review, dict) else {}
    if not isinstance(recommendation, dict):
        recommendation = {}
    instructions: list[str] = []
    if intent.strip():
        instructions.append(f"用户意图：{intent.strip()}")
    for issue in recommendation.get("must_fix", []) if isinstance(recommendation.get("must_fix", []), list) else []:
        instructions.append(f"审稿问题：{issue}")
    for item in recommendation.get("revision_plan", []) if isinstance(recommendation.get("revision_plan", []), list) else []:
        instructions.append(f"改稿计划：{item}")
    return instructions or ["按审核结果改稿，保持主线、人物动机和世界规则稳定。"]


def run_auto_workflow(
    api_base: str,
    project_id: str,
    *,
    intent: str,
    chapter_number: int | None,
    recent_chapters: int,
    include_body: bool,
    max_revisions: int,
    review_provider: str,
    openclaw_command: str = "openclaw",
    openclaw_agent: str = "main",
    openclaw_timeout: int = 600,
    openclaw_local: bool = True,
) -> dict:
    context = fetch_context(api_base, project_id, recent_chapters, include_body)
    generated = False
    generated_chapter: dict | None = None
    if chapter_number is None and _needs_initial_generation(context):
        story_id = _active_story_id(context)
        if not story_id:
            raise RuntimeError("active_story_not_found")
        generated_chapter = generate_story_chapter(api_base, story_id)
        generated = True

    if review_provider == "openclaw":
        revision_attempts = 0
        last_revision: dict | None = None
        final_package: dict | None = None
        final_openclaw_result: dict | None = None
        while True:
            final_package = build_review_package(api_base, project_id, chapter_number, recent_chapters, include_body)
            final_openclaw_result = call_openclaw_review(
                final_package,
                openclaw_command=openclaw_command,
                openclaw_agent=openclaw_agent,
                timeout_seconds=openclaw_timeout,
                local=openclaw_local,
            )
            if final_openclaw_result.get("action") != "revise" or revision_attempts >= max(0, max_revisions):
                break
            applied = apply_review_result(
                api_base,
                project_id,
                chapter_number=chapter_number,
                result=final_openclaw_result,
                include_body=include_body,
            )
            last_revision = applied.get("revision") if isinstance(applied, dict) else None
            revision_attempts += 1

        return {
            "schema_version": "novel-auto-run/v1",
            "project_id": project_id,
            "review_provider": review_provider,
            "intent": intent,
            "generated": generated,
            "generated_chapter": generated_chapter,
            "revision_attempts": revision_attempts,
            "last_revision": last_revision,
            "final_review": final_package.get("review") if isinstance(final_package, dict) else None,
            "final_openclaw_result": final_openclaw_result,
            "openclaw_review_package": final_package,
        }

    review = fetch_review(api_base, project_id, chapter_number, include_body)
    last_revision: dict | None = None
    revision_attempts = 0
    for _ in range(max(0, max_revisions)):
        recommendation = review.get("recommendation", {}) if isinstance(review, dict) else {}
        if not isinstance(recommendation, dict) or recommendation.get("action") != "revise":
            break
        last_revision = post_revision(
            api_base,
            project_id,
            chapter_number,
            _revision_instructions(intent, review),
            include_body,
        )
        revision_attempts += 1
        review = fetch_review(api_base, project_id, chapter_number, include_body)

    return {
        "schema_version": "novel-auto-run/v1",
        "project_id": project_id,
        "review_provider": review_provider,
        "intent": intent,
        "generated": generated,
        "generated_chapter": generated_chapter,
        "revision_attempts": revision_attempts,
        "last_revision": last_revision,
        "final_review": review,
        "openclaw_review_package": {
            "schema_version": "openclaw-review-request/v1",
            "provider_target": "openclaw",
            "project_id": project_id,
            "context": context,
            "review": review,
            "expected_response_schema": "openclaw-review-result/v1",
        },
    }


def load_review_result(result_json: str | None, result_file: str | None) -> dict:
    if result_json:
        result = json.loads(result_json)
    elif result_file:
        with open(result_file, "r", encoding="utf-8") as handle:
            result = json.load(handle)
    else:
        result = json.load(sys.stdin)
    if not isinstance(result, dict):
        raise ValueError("review result must be a JSON object")
    if result.get("schema_version") != "openclaw-review-result/v1":
        raise ValueError("unsupported review result schema")
    return result


def _openclaw_revision_instructions(result: dict) -> list[str]:
    instructions: list[str] = []
    must_fix = result.get("must_fix", [])
    if isinstance(must_fix, list):
        for item in must_fix:
            instructions.append(f"OpenClaw must fix: {item}")
    revision_instructions = result.get("revision_instructions", [])
    if isinstance(revision_instructions, list):
        for item in revision_instructions:
            instructions.append(f"OpenClaw revision instruction: {item}")
    return instructions or ["OpenClaw requested revision; apply the review result while preserving continuity."]


def apply_review_result(
    api_base: str,
    project_id: str,
    *,
    chapter_number: int | None,
    result: dict,
    include_body: bool,
) -> dict:
    action = str(result.get("action", "pause"))
    revision = None
    if action == "revise":
        revision = post_revision(
            api_base,
            project_id,
            chapter_number,
            _openclaw_revision_instructions(result),
            include_body,
        )
    return {
        "schema_version": "openclaw-review-apply/v1",
        "project_id": project_id,
        "action": action,
        "summary": result.get("summary", ""),
        "revision": revision,
        "source_review": result,
    }


def _extract_json_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise ValueError("openclaw output did not contain a JSON object")
    return match.group(0)


def _extract_final_assistant_raw_text(text: str) -> str:
    match = re.search(r'"finalAssistantRawText"\s*:\s*("(?:(?:\\.)|[^"\\])*")', text)
    if not match:
        return ""
    decoded = json.loads(match.group(1))
    return decoded if isinstance(decoded, str) else ""


def _coerce_openclaw_review_result(value) -> dict:
    if isinstance(value, str):
        value = json.loads(_extract_json_text(value))
    if not isinstance(value, dict):
        raise ValueError("openclaw review result must be a JSON object")
    if value.get("schema_version") != "openclaw-review-result/v1":
        raise ValueError("openclaw review result schema mismatch")
    return value


def parse_openclaw_agent_output(stdout: str) -> dict:
    final_text = _extract_final_assistant_raw_text(stdout)
    if final_text:
        return _coerce_openclaw_review_result(final_text)

    try:
        decoded_stdout = json.loads(stdout)
    except Exception:
        decoded_stdout = None
    if isinstance(decoded_stdout, str) and decoded_stdout != stdout:
        final_text = _extract_final_assistant_raw_text(decoded_stdout)
        if final_text:
            return _coerce_openclaw_review_result(final_text)
        if "openclaw-review-result/v1" in decoded_stdout:
            return _coerce_openclaw_review_result(decoded_stdout)

    outer = json.loads(_extract_json_text(stdout))
    if isinstance(outer, dict) and isinstance(outer.get("payloads"), list) and outer["payloads"]:
        first_payload = outer["payloads"][0]
        if isinstance(first_payload, dict) and isinstance(first_payload.get("text"), str):
            result = _coerce_openclaw_review_result(first_payload["text"])
        else:
            result = first_payload
    elif isinstance(outer, dict) and isinstance(outer.get("meta"), dict) and isinstance(outer["meta"].get("finalAssistantRawText"), str):
        result = _coerce_openclaw_review_result(outer["meta"]["finalAssistantRawText"])
    else:
        result = outer
    return _coerce_openclaw_review_result(result)


def write_openclaw_review_package_file(review_package: dict) -> str:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        suffix=".openclaw-review-request.json",
        delete=False,
    ) as handle:
        json.dump(review_package, handle, ensure_ascii=False, indent=2)
        return handle.name


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[TRUNCATED: original_chars={len(text)}]"


def compact_openclaw_review_package(review_package: dict, *, body_char_limit: int = 3000) -> dict:
    context = review_package.get("context", {}) if isinstance(review_package, dict) else {}
    review = review_package.get("review", {}) if isinstance(review_package, dict) else {}
    project = context.get("project", {}) if isinstance(context, dict) else {}
    world = context.get("world", {}) if isinstance(context, dict) else {}
    source_chapter = review.get("chapter", {}) if isinstance(review.get("chapter"), dict) else {}
    original_body = source_chapter.get("body", "") if isinstance(source_chapter.get("body"), str) else ""
    quality_report = source_chapter.get("quality_report", {}) if isinstance(source_chapter.get("quality_report"), dict) else {}
    writing_review = quality_report.get("writing_review", {}) if isinstance(quality_report.get("writing_review"), dict) else {}
    chapter = {
        "chapter_number": source_chapter.get("chapter_number"),
        "chapter_title": source_chapter.get("chapter_title", ""),
        "body_chars": source_chapter.get("body_chars", len(original_body)),
        "body_excerpt": _truncate_text(original_body, body_char_limit),
        "body_was_truncated_for_transport": len(original_body) > body_char_limit,
        "summary": source_chapter.get("summary", ""),
        "facts": source_chapter.get("facts", []),
        "next_focus": source_chapter.get("next_focus", ""),
        "quality": {
            "ok": quality_report.get("ok"),
            "issues": quality_report.get("issues", [])[:8] if isinstance(quality_report.get("issues", []), list) else [],
            "writing_scores": writing_review.get("scores", {}),
            "writing_issues": writing_review.get("issues", [])[:8] if isinstance(writing_review.get("issues", []), list) else [],
            "revision_plan": writing_review.get("revision_plan", [])[:8] if isinstance(writing_review.get("revision_plan", []), list) else [],
        },
    }
    world_gaps = []
    for gap in world.get("gaps", [])[:8] if isinstance(world, dict) and isinstance(world.get("gaps", []), list) else []:
        if isinstance(gap, dict):
            world_gaps.append(
                {
                    "area": gap.get("area", ""),
                    "severity": gap.get("severity", ""),
                    "message": gap.get("message", ""),
                }
            )
    return {
        "schema_version": "openclaw-review-compact/v1",
        "project": project,
        "world_gaps": world_gaps,
        "chapter": chapter,
        "recommendation": review.get("recommendation", {}) if isinstance(review, dict) else {},
    }


def build_openclaw_review_prompt(review_package: dict) -> str:
    compact_package = compact_openclaw_review_package(review_package)
    parts = [
        "你是独立网文审稿 Agent。请只返回 JSON，不要 Markdown。",
        "返回 schema 必须是 openclaw-review-result/v1。",
        "字段必须包括 schema_version, action, summary, must_fix, revision_instructions, risk_flags。",
        "action 只能是 approve、revise 或 pause。",
        "你必须基于提供的章节正文、世界缺口和已有质量报告给出判断。",
        "如果需要改稿，action=revise，并把可执行改稿要求写入 revision_instructions。",
        "审核材料 JSON:",
        json.dumps(compact_package, ensure_ascii=False),
    ]
    return " ".join(parts)


def _resolve_openclaw_command(openclaw_command: str) -> list[str]:
    resolved_command = shutil.which(openclaw_command)
    if resolved_command is None and not openclaw_command.lower().endswith((".cmd", ".exe")):
        resolved_command = shutil.which(f"{openclaw_command}.cmd")
    command_path = resolved_command or openclaw_command
    if command_path.lower().endswith("openclaw.cmd"):
        cli_dir = os.path.dirname(command_path)
        if cli_dir:
            node_exe = os.path.normpath(os.path.join(cli_dir, "..", "bin", "node.exe"))
            entrypoint = os.path.normpath(os.path.join(cli_dir, "..", "openclaw", "openclaw.mjs"))
            if os.path.exists(node_exe) and os.path.exists(entrypoint):
                return [node_exe, entrypoint]
    return [command_path]


def call_openclaw_review(
    review_package: dict,
    *,
    openclaw_command: str,
    openclaw_agent: str,
    timeout_seconds: int,
    local: bool,
) -> dict:
    write_openclaw_review_package_file(review_package)
    command = [*_resolve_openclaw_command(openclaw_command), "agent", "--agent", openclaw_agent]
    if local:
        command.append("--local")
    command.extend(
        [
            "--json",
            "--timeout",
            str(timeout_seconds),
            "--message",
            build_openclaw_review_prompt(review_package),
        ]
    )
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "openclaw review failed")
    output_candidates = [
        completed.stdout,
        completed.stderr,
        "\n".join(part for part in [completed.stdout, completed.stderr] if part),
    ]
    last_error: ValueError | None = None
    for candidate in output_candidates:
        if not candidate or not candidate.strip():
            continue
        try:
            return parse_openclaw_agent_output(candidate)
        except ValueError as exc:
            last_error = exc
            continue
    try:
        return parse_openclaw_agent_output(completed.stdout)
    except ValueError as exc:
        raw_output = (completed.stdout or completed.stderr or "").strip()
        parse_error = last_error or exc
        return {
            "schema_version": "openclaw-review-result/v1",
            "action": "pause",
            "summary": f"OpenClaw did not return contract JSON: {parse_error}",
            "must_fix": [],
            "revision_instructions": [],
            "risk_flags": ["non_json_output"],
            "raw_output": raw_output[-4000:],
        }


def run_openclaw_review(
    api_base: str,
    project_id: str,
    *,
    chapter_number: int | None,
    recent_chapters: int,
    include_body: bool,
    openclaw_command: str,
    openclaw_agent: str,
    timeout_seconds: int,
    local: bool,
    apply: bool,
) -> dict:
    review_package = build_review_package(api_base, project_id, chapter_number, recent_chapters, include_body)
    result = call_openclaw_review(
        review_package,
        openclaw_command=openclaw_command,
        openclaw_agent=openclaw_agent,
        timeout_seconds=timeout_seconds,
        local=local,
    )
    applied = None
    if apply:
        applied = apply_review_result(
            api_base,
            project_id,
            chapter_number=chapter_number,
            result=result,
            include_body=include_body,
        )
    return {
        "schema_version": "openclaw-review-run/v1",
        "project_id": project_id,
        "openclaw_agent": openclaw_agent,
        "result": result,
        "applied": applied,
        "review_package_schema": review_package["schema_version"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novel-agent",
        description="Agent-facing CLI for Novel Autogrowth Engine.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    context = subparsers.add_parser("context", help="Fetch a project context pack.")
    context.add_argument("project_id", help="Project id, for example p-c771ad03.")
    context.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")
    context.add_argument("--recent-chapters", type=int, default=3, help="Number of recent chapters to include, clamped by the API.")
    context.add_argument("--include-body", action="store_true", help="Include recent chapter prose bodies.")

    review = subparsers.add_parser("review", help="Fetch a structured chapter review.")
    review.add_argument("project_id", help="Project id, for example p-c771ad03.")
    review.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")
    review.add_argument("--chapter-number", type=int, default=None, help="Chapter number to review. Defaults to the latest chapter.")
    review.add_argument("--include-body", action="store_true", help="Include the reviewed chapter prose body.")

    revise = subparsers.add_parser("revise", help="Revise the latest chapter through the agent API.")
    revise.add_argument("project_id", help="Project id, for example p-c771ad03.")
    revise.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")
    revise.add_argument("--chapter-number", type=int, default=None, help="Chapter number to revise. Defaults to the latest chapter.")
    revise.add_argument("--instruction", action="append", default=[], help="Revision instruction. Can be passed multiple times.")
    revise.add_argument("--include-body", action="store_true", help="Include the revised chapter prose body.")

    writing_packet = subparsers.add_parser("writing-packet", help="Fetch the Codex writing packet for one chapter.")
    writing_packet.add_argument("project_id", help="Project id, for example p-c771ad03.")
    writing_packet.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")
    writing_packet.add_argument("--chapter-number", type=int, default=None, help="Chapter number to write. Defaults to the next target chapter.")

    world = subparsers.add_parser("world", help="Read or patch project world state.")
    world_subparsers = world.add_subparsers(dest="world_command", required=True)

    world_get = world_subparsers.add_parser("get", help="Fetch project world state.")
    world_get.add_argument("project_id", help="Project id, for example p-c771ad03.")
    world_get.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")

    world_patch = world_subparsers.add_parser("patch", help="Patch project world state.")
    world_patch.add_argument("project_id", help="Project id, for example p-c771ad03.")
    world_patch.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")
    world_patch.add_argument("--world-summary", default=None, help="Replacement world summary.")
    world_patch.add_argument("--current-focus", default=None, help="Replacement current focus.")
    world_patch.add_argument("--author-constraint", action="append", default=[], help="Replacement author constraint list item. Can be passed multiple times.")
    world_patch.add_argument("--world-blueprint-json", default=None, help="Replacement world_blueprint JSON object.")
    world_patch.add_argument("--character-profile-json", action="append", default=[], help="Replacement character profile JSON object. Can be passed multiple times.")
    world_patch.add_argument("--relationship-json", action="append", default=[], help="Replacement relationship JSON object. Can be passed multiple times.")
    world_patch.add_argument("--status", default=None, help="Replacement project status.")
    world_patch.add_argument("--pipeline-stage", default=None, help="Replacement project pipeline stage.")

    review_package = subparsers.add_parser("review-package", help="Export an OpenClaw-compatible review request package.")
    review_package.add_argument("project_id", help="Project id, for example p-c771ad03.")
    review_package.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")
    review_package.add_argument("--chapter-number", type=int, default=None, help="Chapter number to review. Defaults to latest chapter.")
    review_package.add_argument("--recent-chapters", type=int, default=3, help="Number of recent chapters to include.")
    review_package.add_argument("--include-body", action="store_true", help="Include prose bodies in context and review.")

    auto = subparsers.add_parser("auto", help="Run a minimal generate-review-revise automation loop.")
    auto.add_argument("project_id", help="Project id, for example p-c771ad03.")
    auto.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")
    auto.add_argument("--intent", default="", help="Natural-language author intent for this run.")
    auto.add_argument("--chapter-number", type=int, default=None, help="Chapter number to review/revise. Defaults to latest chapter.")
    auto.add_argument("--recent-chapters", type=int, default=3, help="Number of recent chapters to include in context.")
    auto.add_argument("--include-body", action="store_true", help="Include prose bodies in automation calls.")
    auto.add_argument("--max-revisions", type=int, default=1, help="Maximum automatic revision attempts.")
    auto.add_argument("--review-provider", default="local", choices=["local", "openclaw"], help="Review provider label for automation reports. Default uses the built-in Codex/self reviewer.")
    auto.add_argument("--openclaw-command", default="openclaw", help="OpenClaw command path or executable name.")
    auto.add_argument("--openclaw-agent", default="main", help="OpenClaw agent id used when --review-provider openclaw.")
    auto.add_argument("--timeout", type=int, default=600, help="OpenClaw command timeout in seconds.")
    auto.add_argument("--no-local", action="store_true", help="Use the gateway instead of embedded local OpenClaw.")

    apply_review = subparsers.add_parser("apply-review-result", help="Apply an OpenClaw review result to the project.")
    apply_review.add_argument("project_id", help="Project id, for example p-c771ad03.")
    apply_review.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")
    apply_review.add_argument("--chapter-number", type=int, default=None, help="Chapter number to revise. Defaults to latest chapter.")
    apply_review.add_argument("--result-json", default=None, help="OpenClaw review result JSON string.")
    apply_review.add_argument("--result-file", default=None, help="Path to an OpenClaw review result JSON file. Reads stdin when omitted.")
    apply_review.add_argument("--include-body", action="store_true", help="Include the revised chapter prose body.")

    openclaw_review = subparsers.add_parser("openclaw-review", help="Run OpenClaw as the independent reviewer.")
    openclaw_review.add_argument("project_id", help="Project id, for example p-c771ad03.")
    openclaw_review.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"API base URL. Default: {DEFAULT_API_BASE}")
    openclaw_review.add_argument("--chapter-number", type=int, default=None, help="Chapter number to review. Defaults to latest chapter.")
    openclaw_review.add_argument("--recent-chapters", type=int, default=3, help="Number of recent chapters to include.")
    openclaw_review.add_argument("--include-body", action="store_true", help="Include prose bodies in the review package.")
    openclaw_review.add_argument("--openclaw-command", default="openclaw", help="OpenClaw command path or executable name.")
    openclaw_review.add_argument("--openclaw-agent", default="main", help="OpenClaw agent id.")
    openclaw_review.add_argument("--timeout", type=int, default=600, help="OpenClaw command timeout in seconds.")
    openclaw_review.add_argument("--no-local", action="store_true", help="Use the gateway instead of embedded local OpenClaw.")
    openclaw_review.add_argument("--apply", action="store_true", help="Apply a revise result through agent-revise.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "context":
        _ensure_utf8_stdout()
        payload = fetch_context(args.api_base, args.project_id, args.recent_chapters, args.include_body)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "review":
        _ensure_utf8_stdout()
        payload = fetch_review(args.api_base, args.project_id, args.chapter_number, args.include_body)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "revise":
        _ensure_utf8_stdout()
        payload = post_revision(
            args.api_base,
            args.project_id,
            args.chapter_number,
            args.instruction,
            args.include_body,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "writing-packet":
        _ensure_utf8_stdout()
        payload = fetch_writing_packet(args.api_base, args.project_id, args.chapter_number)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "world":
        _ensure_utf8_stdout()
        if args.world_command == "get":
            payload = fetch_project(args.api_base, args.project_id)
        else:
            payload = patch_project(args.api_base, args.project_id, build_world_patch_payload(args))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "review-package":
        _ensure_utf8_stdout()
        payload = build_review_package(
            args.api_base,
            args.project_id,
            args.chapter_number,
            args.recent_chapters,
            args.include_body,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "auto":
        _ensure_utf8_stdout()
        payload = run_auto_workflow(
            args.api_base,
            args.project_id,
            intent=args.intent,
            chapter_number=args.chapter_number,
            recent_chapters=args.recent_chapters,
            include_body=args.include_body,
            max_revisions=args.max_revisions,
            review_provider=args.review_provider,
            openclaw_command=args.openclaw_command,
            openclaw_agent=args.openclaw_agent,
            openclaw_timeout=args.timeout,
            openclaw_local=not args.no_local,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "apply-review-result":
        _ensure_utf8_stdout()
        payload = apply_review_result(
            args.api_base,
            args.project_id,
            chapter_number=args.chapter_number,
            result=load_review_result(args.result_json, args.result_file),
            include_body=args.include_body,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "openclaw-review":
        _ensure_utf8_stdout()
        payload = run_openclaw_review(
            args.api_base,
            args.project_id,
            chapter_number=args.chapter_number,
            recent_chapters=args.recent_chapters,
            include_body=args.include_body,
            openclaw_command=args.openclaw_command,
            openclaw_agent=args.openclaw_agent,
            timeout_seconds=args.timeout,
            local=not args.no_local,
            apply=args.apply,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
