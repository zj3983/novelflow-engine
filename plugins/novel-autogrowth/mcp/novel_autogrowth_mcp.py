from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import novel_agent  # noqa: E402


DEFAULT_API_BASE = os.environ.get("NOVEL_AUTOGROWTH_API_BASE", novel_agent.DEFAULT_API_BASE)


def _json_text(payload: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ]
    }


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    api_base = str(args.get("api_base") or DEFAULT_API_BASE)

    if name == "get_context":
        return _json_text(
            novel_agent.fetch_context(
                api_base,
                str(args["project_id"]),
                int(args.get("recent_chapters", 3)),
                bool(args.get("include_body", False)),
            )
        )

    if name == "get_world":
        return _json_text(novel_agent.fetch_project(api_base, str(args["project_id"])))

    if name == "review_chapter":
        chapter_number = args.get("chapter_number")
        return _json_text(
            novel_agent.fetch_review(
                api_base,
                str(args["project_id"]),
                int(chapter_number) if chapter_number is not None else None,
                bool(args.get("include_body", True)),
            )
        )

    if name == "get_writing_packet":
        chapter_number = args.get("chapter_number")
        return _json_text(
            novel_agent.fetch_writing_packet(
                api_base,
                str(args["project_id"]),
                int(chapter_number) if chapter_number is not None else None,
            )
        )

    if name == "submit_manual_draft":
        return _json_text(
            novel_agent.post_manual_draft(
                api_base,
                str(args["project_id"]),
                int(args["chapter_number"]),
                str(args["body"]),
                _str_list(args.get("instructions")),
                bool(args.get("include_body", True)),
            )
        )

    if name == "submit_segment_draft":
        return _json_text(
            novel_agent.post_manual_segment_draft(
                api_base,
                str(args["project_id"]),
                int(args["chapter_number"]),
                int(args["segment_index"]),
                str(args["body"]),
                _str_list(args.get("instructions")),
                bool(args.get("include_body", True)),
            )
        )

    if name == "revise_chapter":
        chapter_number = args.get("chapter_number")
        return _json_text(
            novel_agent.post_revision(
                api_base,
                str(args["project_id"]),
                int(chapter_number) if chapter_number is not None else None,
                _str_list(args.get("instructions")),
                bool(args.get("include_body", True)),
            )
        )

    if name == "patch_world":
        payload: dict[str, Any] = {}
        for key in [
            "world_summary",
            "current_focus",
            "author_constraints",
            "world_blueprint",
            "character_profiles",
            "relationship_graph",
            "status",
            "pipeline_stage",
        ]:
            if key in args:
                payload[key] = args[key]
        if "author_constraint" in args:
            payload["author_constraints"] = _str_list(args.get("author_constraint"))
        return _json_text(novel_agent.patch_project(api_base, str(args["project_id"]), payload))

    if name == "continue_generation":
        project_id = str(args["project_id"])
        context = novel_agent.fetch_context(
            api_base,
            project_id,
            int(args.get("recent_chapters", 3)),
            bool(args.get("include_body", False)),
        )
        story_id = (
            context.get("project", {}).get("active_story_id")
            or context.get("active_story", {}).get("story_id")
            or args.get("story_id")
        )
        if not story_id:
            raise ValueError("active_story_id_required")
        generated = novel_agent.generate_story_chapter(api_base, str(story_id))
        review = novel_agent.fetch_review(api_base, project_id, None, bool(args.get("include_body", True)))
        return _json_text(
            {
                "schema_version": "novel-autogrowth-mcp-continue/v1",
                "project_id": project_id,
                "story_id": story_id,
                "generated": generated,
                "review": review,
            }
        )

    if name == "dashboard":
        return _json_text(
            {
                "schema_version": "novel-autogrowth-dashboard/v1",
                "url": str(args.get("url") or "http://localhost:3000"),
            }
        )

    raise ValueError(f"unknown_tool:{name}")


TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_context",
        "description": "Fetch the current project context, recent chapters, world gaps, and suggested next actions.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
                "recent_chapters": {"type": "integer", "default": 3},
                "include_body": {"type": "boolean", "default": False},
                "api_base": {"type": "string"},
            },
        },
    },
    {
        "name": "get_world",
        "description": "Fetch the project world bible, rules, character profiles, and active story metadata.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
                "api_base": {"type": "string"},
            },
        },
    },
    {
        "name": "review_chapter",
        "description": "Review one chapter through the local/self webnovel review agent.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
                "chapter_number": {"type": "integer"},
                "include_body": {"type": "boolean", "default": True},
                "api_base": {"type": "string"},
            },
        },
    },
    {
        "name": "get_writing_packet",
        "description": "Fetch the Codex writing packet for a target chapter before manual prose writing.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
                "chapter_number": {"type": "integer"},
                "api_base": {"type": "string"},
            },
        },
    },
    {
        "name": "submit_manual_draft",
        "description": "Submit a Codex/manual full-chapter draft, then receive the updated review package.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "chapter_number", "body"],
            "properties": {
                "project_id": {"type": "string"},
                "chapter_number": {"type": "integer"},
                "body": {"type": "string"},
                "instructions": {"type": "array", "items": {"type": "string"}},
                "include_body": {"type": "boolean", "default": True},
                "api_base": {"type": "string"},
            },
        },
    },
    {
        "name": "submit_segment_draft",
        "description": "Submit a Codex/manual replacement for one zero-based chapter segment.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "chapter_number", "segment_index", "body"],
            "properties": {
                "project_id": {"type": "string"},
                "chapter_number": {"type": "integer"},
                "segment_index": {"type": "integer"},
                "body": {"type": "string"},
                "instructions": {"type": "array", "items": {"type": "string"}},
                "include_body": {"type": "boolean", "default": True},
                "api_base": {"type": "string"},
            },
        },
    },
    {
        "name": "revise_chapter",
        "description": "Revise a chapter with explicit editorial instructions.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "instructions"],
            "properties": {
                "project_id": {"type": "string"},
                "chapter_number": {"type": "integer"},
                "instructions": {"type": "array", "items": {"type": "string"}},
                "include_body": {"type": "boolean", "default": True},
                "api_base": {"type": "string"},
            },
        },
    },
    {
        "name": "patch_world",
        "description": "Patch project worldbuilding, current focus, constraints, profiles, or rulebook fields.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
                "world_summary": {"type": "string"},
                "current_focus": {"type": "string"},
                "author_constraint": {"type": "string"},
                "author_constraints": {"type": "array", "items": {"type": "string"}},
                "world_blueprint": {"type": "object"},
                "character_profiles": {"type": "array"},
                "relationship_graph": {"type": "array"},
                "status": {"type": "string"},
                "pipeline_stage": {"type": "string"},
                "api_base": {"type": "string"},
            },
        },
    },
    {
        "name": "continue_generation",
        "description": "Generate the next chapter and immediately fetch the local/self review report.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
                "story_id": {"type": "string"},
                "recent_chapters": {"type": "integer", "default": 3},
                "include_body": {"type": "boolean", "default": True},
                "api_base": {"type": "string"},
            },
        },
    },
    {
        "name": "dashboard",
        "description": "Return the local web dashboard URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "default": "http://localhost:3000"},
            },
        },
    },
]


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def _write_message(message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _success(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        return _success(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "novel-autogrowth", "version": "0.1.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _success(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            return _success(request_id, call_tool(str(params.get("name")), params.get("arguments") or {}))
        except Exception as exc:  # MCP clients expect tool errors as JSON-RPC errors.
            return _error(request_id, -32000, str(exc))
    return _error(request_id, -32601, f"method_not_found:{method}")


def main() -> int:
    while True:
        message = _read_message()
        if message is None:
            return 0
        response = handle_request(message)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
