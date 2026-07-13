import json
import importlib.util
from pathlib import Path


def _load_mcp_module():
    path = Path("plugins/novel-autogrowth/mcp/novel_autogrowth_mcp.py")
    spec = importlib.util.spec_from_file_location("novel_autogrowth_mcp_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _text_payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def test_mcp_lists_novel_autogrowth_tools():
    mcp = _load_mcp_module()

    response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response is not None
    assert response["result"]["tools"]
    assert {tool["name"] for tool in response["result"]["tools"]} >= {
        "get_context",
        "get_writing_packet",
        "review_chapter",
        "revise_chapter",
        "submit_manual_draft",
        "patch_world",
        "continue_generation",
    }


def test_mcp_review_chapter_calls_agent_review(monkeypatch):
    mcp = _load_mcp_module()

    calls: list[tuple[str, str, int, bool]] = []

    def fake_fetch_review(api_base, project_id, chapter_number, include_body):
        calls.append((api_base, project_id, chapter_number, include_body))
        return {
            "schema_version": "agent-review/v1",
            "project": {"project_id": project_id},
            "chapter": {"chapter_number": chapter_number},
        }

    monkeypatch.setattr(mcp.novel_agent, "fetch_review", fake_fetch_review)

    result = mcp.call_tool(
        "review_chapter",
        {
            "api_base": "http://api.test",
            "project_id": "p-1",
            "chapter_number": 2,
            "include_body": True,
        },
    )

    assert calls == [("http://api.test", "p-1", 2, True)]
    assert _text_payload(result)["schema_version"] == "agent-review/v1"


def test_mcp_get_writing_packet_calls_agent_packet(monkeypatch):
    mcp = _load_mcp_module()

    calls: list[tuple[str, str, int]] = []

    def fake_fetch_writing_packet(api_base, project_id, chapter_number):
        calls.append((api_base, project_id, chapter_number))
        return {
            "schema_version": "writing-packet/v1",
            "project": {"project_id": project_id},
            "target_chapter": chapter_number,
        }

    monkeypatch.setattr(mcp.novel_agent, "fetch_writing_packet", fake_fetch_writing_packet)

    result = mcp.call_tool(
        "get_writing_packet",
        {
            "api_base": "http://api.test",
            "project_id": "p-1",
            "chapter_number": 2,
        },
    )

    assert calls == [("http://api.test", "p-1", 2)]
    assert _text_payload(result)["schema_version"] == "writing-packet/v1"


def test_mcp_submit_manual_draft_calls_agent_manual_draft(monkeypatch):
    mcp = _load_mcp_module()

    calls: list[tuple[str, str, int, str, list[str], bool]] = []

    def fake_post_manual_draft(api_base, project_id, chapter_number, body, instructions, include_body):
        calls.append((api_base, project_id, chapter_number, body, instructions, include_body))
        return {"schema_version": "agent-revision/v1", "source": "manual_draft"}

    monkeypatch.setattr(mcp.novel_agent, "post_manual_draft", fake_post_manual_draft)

    result = mcp.call_tool(
        "submit_manual_draft",
        {
            "api_base": "http://api.test",
            "project_id": "p-1",
            "chapter_number": 1,
            "body": "manual chapter body",
            "instructions": ["keep panel consistent"],
            "include_body": True,
        },
    )

    assert calls == [("http://api.test", "p-1", 1, "manual chapter body", ["keep panel consistent"], True)]
    assert _text_payload(result)["source"] == "manual_draft"


def test_mcp_patch_world_accepts_single_author_constraint(monkeypatch):
    mcp = _load_mcp_module()

    calls: list[tuple[str, str, dict]] = []

    def fake_patch_project(api_base, project_id, payload):
        calls.append((api_base, project_id, payload))
        return {"project_id": project_id, **payload}

    monkeypatch.setattr(mcp.novel_agent, "patch_project", fake_patch_project)

    result = mcp.call_tool(
        "patch_world",
        {
            "api_base": "http://api.test",
            "project_id": "p-1",
            "author_constraint": "NPC 行为必须有信息来源和利益动机。",
        },
    )

    assert calls == [
        (
            "http://api.test",
            "p-1",
            {"author_constraints": ["NPC 行为必须有信息来源和利益动机。"]},
        )
    ]
    assert _text_payload(result)["author_constraints"] == ["NPC 行为必须有信息来源和利益动机。"]


def test_mcp_continue_generation_fetches_context_generates_and_reviews(monkeypatch):
    mcp = _load_mcp_module()

    calls: list[tuple[str, str]] = []

    def fake_fetch_context(api_base, project_id, recent_chapters, include_body):
        calls.append(("context", project_id))
        return {
            "project": {"project_id": project_id, "active_story_id": "s-1"},
            "active_story": {"story_id": "s-1"},
        }

    def fake_generate_story_chapter(api_base, story_id):
        calls.append(("generate", story_id))
        return {"status": "completed", "chapter_number": 3}

    def fake_fetch_review(api_base, project_id, chapter_number, include_body):
        calls.append(("review", project_id))
        return {"schema_version": "agent-review/v1", "chapter": {"chapter_number": 3}}

    monkeypatch.setattr(mcp.novel_agent, "fetch_context", fake_fetch_context)
    monkeypatch.setattr(mcp.novel_agent, "generate_story_chapter", fake_generate_story_chapter)
    monkeypatch.setattr(mcp.novel_agent, "fetch_review", fake_fetch_review)

    result = mcp.call_tool("continue_generation", {"api_base": "http://api.test", "project_id": "p-1"})
    payload = _text_payload(result)

    assert calls == [("context", "p-1"), ("generate", "s-1"), ("review", "p-1")]
    assert payload["schema_version"] == "novel-autogrowth-mcp-continue/v1"
    assert payload["review"]["schema_version"] == "agent-review/v1"
