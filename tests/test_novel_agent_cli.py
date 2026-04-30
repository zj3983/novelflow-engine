import json
from types import SimpleNamespace


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _FakeStdout:
    def __init__(self):
        self.reconfigure_calls: list[dict] = []
        self.output: list[str] = []

    def reconfigure(self, **kwargs):
        self.reconfigure_calls.append(kwargs)

    def write(self, text: str) -> int:
        self.output.append(text)
        return len(text)

    def flush(self) -> None:
        pass


def test_novel_agent_context_cli_fetches_context_pack(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requested: list[str] = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        assert timeout == 30
        return _FakeResponse(
            {
                "schema_version": "agent-context/v1",
                "project": {"project_id": "p-1"},
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(
        [
            "context",
            "p-1",
            "--api-base",
            "http://api.test",
            "--recent-chapters",
            "2",
            "--include-body",
        ]
    )

    assert exit_code == 0
    assert requested == ["http://api.test/projects/p-1/agent-context?recent_chapters=2&include_body=true"]
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "agent-context/v1"
    assert output["project"]["project_id"] == "p-1"


def test_novel_agent_review_cli_fetches_chapter_review(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requested: list[str] = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        assert timeout == 30
        return _FakeResponse(
            {
                "schema_version": "agent-review/v1",
                "project": {"project_id": "p-1"},
                "chapter": {"chapter_number": 2},
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(
        [
            "review",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "2",
            "--include-body",
        ]
    )

    assert exit_code == 0
    assert requested == ["http://api.test/projects/p-1/agent-review?chapter_number=2&include_body=true"]
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "agent-review/v1"
    assert output["chapter"]["chapter_number"] == 2


def test_novel_agent_revise_cli_posts_revision_request(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requests: list[tuple[str, dict]] = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, json.loads(request.data.decode("utf-8"))))
        assert request.get_method() == "POST"
        assert request.get_header("Content-Type") == "application/json"
        assert timeout == 300
        return _FakeResponse(
            {
                "schema_version": "agent-revision/v1",
                "project": {"project_id": "p-1"},
                "chapter": {"chapter_number": 2},
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(
        [
            "revise",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "2",
            "--instruction",
            "补足交易行规则",
            "--instruction",
            "统一千倍爆率写法",
            "--include-body",
        ]
    )

    assert exit_code == 0
    assert requests == [
        (
            "http://api.test/projects/p-1/agent-revise",
            {
                "chapter_number": 2,
                "instructions": ["补足交易行规则", "统一千倍爆率写法"],
                "include_body": True,
            },
        )
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "agent-revision/v1"
    assert output["chapter"]["chapter_number"] == 2


def test_novel_agent_writing_packet_cli_fetches_packet(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requested: list[str] = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        assert request.get_method() == "GET"
        assert timeout == 30
        return _FakeResponse(
            {
                "schema_version": "writing-packet/v1",
                "project": {"project_id": "p-1"},
                "target_chapter": 2,
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(
        [
            "writing-packet",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "2",
        ]
    )

    assert exit_code == 0
    assert requested == ["http://api.test/projects/p-1/writing-packet?chapter_number=2"]
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "writing-packet/v1"
    assert output["target_chapter"] == 2


def test_novel_agent_manual_draft_cli_posts_body(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requests: list[tuple[str, dict]] = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, json.loads(request.data.decode("utf-8"))))
        assert request.get_method() == "POST"
        assert request.get_header("Content-Type") == "application/json"
        assert timeout == 300
        return _FakeResponse(
            {
                "schema_version": "agent-revision/v1",
                "source": "manual_draft",
                "chapter": {"chapter_number": 1},
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(
        [
            "manual-draft",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "1",
            "--body",
            "manual chapter body",
            "--instruction",
            "keep character panel consistent",
            "--include-body",
        ]
    )

    assert exit_code == 0
    assert requests == [
        (
            "http://api.test/projects/p-1/manual-draft",
            {
                "chapter_number": 1,
                "body": "manual chapter body",
                "instructions": ["keep character panel consistent"],
                "include_body": True,
            },
        )
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["source"] == "manual_draft"


def test_novel_agent_manual_segment_draft_cli_posts_segment(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requests: list[tuple[str, dict]] = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, json.loads(request.data.decode("utf-8"))))
        assert request.get_method() == "POST"
        assert request.get_header("Content-Type") == "application/json"
        assert timeout == 300
        return _FakeResponse(
            {
                "schema_version": "agent-revision/v1",
                "source": "manual_segment_draft",
                "chapter": {"chapter_number": 1},
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(
        [
            "manual-segment-draft",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "1",
            "--segment-index",
            "3",
            "--body",
            "rewritten paragraph",
            "--instruction",
            "remove AI-sounding short lines",
        ]
    )

    assert exit_code == 0
    assert requests == [
        (
            "http://api.test/projects/p-1/manual-segment-draft",
            {
                "chapter_number": 1,
                "segment_index": 3,
                "body": "rewritten paragraph",
                "instructions": ["remove AI-sounding short lines"],
                "include_body": False,
            },
        )
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["source"] == "manual_segment_draft"


def test_novel_agent_world_get_fetches_project_state(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requested: list[str] = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        assert request.get_method() == "GET"
        assert timeout == 30
        return _FakeResponse(
            {
                "project_id": "p-1",
                "title": "World Project",
                "world_summary": "world seed",
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(["world", "get", "p-1", "--api-base", "http://api.test"])

    assert exit_code == 0
    assert requested == ["http://api.test/projects/p-1"]
    output = json.loads(capsys.readouterr().out)
    assert output["project_id"] == "p-1"
    assert output["world_summary"] == "world seed"


def test_novel_agent_world_patch_updates_project_world_fields(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requests: list[tuple[str, dict]] = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, json.loads(request.data.decode("utf-8"))))
        assert request.get_method() == "PATCH"
        assert request.get_header("Content-Type") == "application/json"
        assert timeout == 30
        return _FakeResponse(
            {
                "project_id": "p-1",
                "world_summary": "richer world",
                "current_focus": "focus line",
                "author_constraints": ["keep economy consistent"],
                "world_blueprint": {"economy": {"gold": "stable"}},
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(
        [
            "world",
            "patch",
            "p-1",
            "--api-base",
            "http://api.test",
            "--world-summary",
            "richer world",
            "--current-focus",
            "focus line",
            "--author-constraint",
            "keep economy consistent",
            "--world-blueprint-json",
            '{"economy":{"gold":"stable"}}',
        ]
    )

    assert exit_code == 0
    assert requests == [
        (
            "http://api.test/projects/p-1",
            {
                "world_summary": "richer world",
                "current_focus": "focus line",
                "author_constraints": ["keep economy consistent"],
                "world_blueprint": {"economy": {"gold": "stable"}},
            },
        )
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["world_blueprint"]["economy"]["gold"] == "stable"


def test_novel_agent_review_package_exports_openclaw_contract(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requested: list[str] = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        if "agent-context" in request.full_url:
            return _FakeResponse(
                {
                    "schema_version": "agent-context/v1",
                    "project": {"project_id": "p-1"},
                    "world": {"gaps": [{"area": "npc_system"}]},
                }
            )
        return _FakeResponse(
            {
                "schema_version": "agent-review/v1",
                "project": {"project_id": "p-1"},
                "chapter": {"chapter_number": 1},
                "recommendation": {"action": "revise", "must_fix": ["add NPC logic"]},
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(
        [
            "review-package",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "1",
            "--include-body",
        ]
    )

    assert exit_code == 0
    assert requested == [
        "http://api.test/projects/p-1/agent-context?recent_chapters=3&include_body=true",
        "http://api.test/projects/p-1/agent-review?chapter_number=1&include_body=true",
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "openclaw-review-request/v1"
    assert output["provider_target"] == "openclaw"
    assert output["context"]["schema_version"] == "agent-context/v1"
    assert output["review"]["schema_version"] == "agent-review/v1"
    assert "openclaw-review-result/v1" == output["expected_response_schema"]


def test_novel_agent_auto_generates_reviews_and_revises_when_needed(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    calls: list[tuple[str, str, dict | None]] = []

    def fake_urlopen(request, timeout):
        method = request.get_method()
        data = json.loads(request.data.decode("utf-8")) if getattr(request, "data", None) else None
        calls.append((method, request.full_url, data))
        if request.full_url.endswith("/agent-context?recent_chapters=3&include_body=true"):
            return _FakeResponse(
                {
                    "schema_version": "agent-context/v1",
                    "project": {"project_id": "p-1"},
                    "active_story": {"story_id": "s-1", "current_chapter": 0},
                    "recent_chapters": [],
                }
            )
        if request.full_url.endswith("/stories/s-1/generation-jobs") and method == "POST":
            assert timeout == 30
            return _FakeResponse({"job_id": "gj-1", "story_id": "s-1", "status": "queued"})
        if request.full_url.endswith("/stories/s-1/generation-jobs/gj-1") and method == "GET":
            assert timeout == 30
            return _FakeResponse({"job_id": "gj-1", "story_id": "s-1", "status": "completed", "chapter_number": 1})
        if "agent-review" in request.full_url:
            return _FakeResponse(
                {
                    "schema_version": "agent-review/v1",
                    "chapter": {"chapter_number": 1},
                    "recommendation": {
                        "action": "revise",
                        "must_fix": ["expand game background"],
                        "revision_plan": ["add protagonist job"],
                    },
                }
            )
        if request.full_url.endswith("/agent-revise"):
            assert timeout == 300
            return _FakeResponse(
                {
                    "schema_version": "agent-revision/v1",
                    "chapter": {"chapter_number": 1, "body_chars": 4200},
                    "revision": {"changed": True},
                }
            )
        raise AssertionError(request.full_url)

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    exit_code = novel_agent.main(
        [
            "auto",
            "p-1",
            "--api-base",
            "http://api.test",
            "--intent",
            "补足现实背景和网游规则",
            "--max-revisions",
            "1",
            "--review-provider",
            "local",
            "--include-body",
        ]
    )

    assert exit_code == 0
    assert calls == [
        ("GET", "http://api.test/projects/p-1/agent-context?recent_chapters=3&include_body=true", None),
        ("POST", "http://api.test/stories/s-1/generation-jobs", None),
        ("GET", "http://api.test/stories/s-1/generation-jobs/gj-1", None),
        ("GET", "http://api.test/projects/p-1/agent-review?include_body=true", None),
        (
            "POST",
            "http://api.test/projects/p-1/agent-revise",
            {
                "chapter_number": None,
                "instructions": [
                    "用户意图：补足现实背景和网游规则",
                    "审稿问题：expand game background",
                    "改稿计划：add protagonist job",
                ],
                "include_body": True,
            },
        ),
        ("GET", "http://api.test/projects/p-1/agent-review?include_body=true", None),
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "novel-auto-run/v1"
    assert output["generated"] is True
    assert output["revision_attempts"] == 1
    assert output["final_review"]["schema_version"] == "agent-review/v1"


def test_novel_agent_generation_poll_survives_transient_status_timeout(monkeypatch):
    import scripts.novel_agent as novel_agent

    calls = 0

    def fake_json_request(url, *, method="GET", payload=None, timeout=30):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("status request timed out")
        assert url == "http://api.test/stories/s-1/generation-jobs/gj-1"
        return {"job_id": "gj-1", "status": "completed", "chapter_number": 1}

    monkeypatch.setattr(novel_agent, "_json_request", fake_json_request)
    monkeypatch.setattr(novel_agent.time, "sleep", lambda seconds: None)

    result = novel_agent.poll_generation_job("http://api.test", "s-1", "gj-1", timeout_seconds=5)

    assert result["status"] == "completed"
    assert calls == 2


def test_novel_agent_apply_review_result_revises_from_openclaw_output(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requests: list[tuple[str, dict]] = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, json.loads(request.data.decode("utf-8"))))
        assert request.get_method() == "POST"
        assert timeout == 300
        return _FakeResponse(
            {
                "schema_version": "agent-revision/v1",
                "chapter": {"chapter_number": 2, "body_chars": 4300},
                "revision": {"changed": True},
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    result_json = json.dumps(
        {
            "schema_version": "openclaw-review-result/v1",
            "action": "revise",
            "must_fix": ["economy mismatch"],
            "revision_instructions": ["add NPC quest giver"],
        }
    )

    exit_code = novel_agent.main(
        [
            "apply-review-result",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "2",
            "--result-json",
            result_json,
            "--include-body",
        ]
    )

    assert exit_code == 0
    assert requests == [
        (
            "http://api.test/projects/p-1/agent-revise",
            {
                "chapter_number": 2,
                "instructions": [
                    "OpenClaw must fix: economy mismatch",
                    "OpenClaw revision instruction: add NPC quest giver",
                ],
                "include_body": True,
            },
        )
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "openclaw-review-apply/v1"
    assert output["action"] == "revise"
    assert output["revision"]["schema_version"] == "agent-revision/v1"


def test_novel_agent_apply_review_result_approves_without_mutation(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    def fake_urlopen(request, timeout):
        raise AssertionError("approve should not call backend mutation")

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)

    result_json = json.dumps(
        {
            "schema_version": "openclaw-review-result/v1",
            "action": "approve",
            "summary": "ready",
        }
    )

    exit_code = novel_agent.main(
        [
            "apply-review-result",
            "p-1",
            "--api-base",
            "http://api.test",
            "--result-json",
            result_json,
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "openclaw-review-apply/v1"
    assert output["action"] == "approve"
    assert output["revision"] is None


def test_novel_agent_openclaw_review_runs_agent_and_outputs_result(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    requested: list[str] = []
    commands: list[list[str]] = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        if "agent-context" in request.full_url:
            return _FakeResponse(
                {
                    "schema_version": "agent-context/v1",
                    "project": {"project_id": "p-1"},
                    "active_story": {"story_id": "s-1"},
                }
            )
        return _FakeResponse(
            {
                "schema_version": "agent-review/v1",
                "chapter": {"chapter_number": 1, "body_chars": 3200},
            }
        )

    def fake_run(command, capture_output, text, encoding, timeout, check):
        commands.append(command)
        assert capture_output is True
        assert text is True
        assert encoding == "utf-8"
        assert timeout == 120
        assert check is False
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "payloads": [
                        {
                            "text": json.dumps(
                                {
                                    "schema_version": "openclaw-review-result/v1",
                                    "action": "approve",
                                    "summary": "ready",
                                    "must_fix": [],
                                    "revision_instructions": [],
                                    "risk_flags": [],
                                }
                            )
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(novel_agent.subprocess, "run", fake_run)
    monkeypatch.setattr(novel_agent.shutil, "which", lambda command: command)

    exit_code = novel_agent.main(
        [
            "openclaw-review",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "1",
            "--include-body",
            "--openclaw-agent",
            "main",
            "--timeout",
            "120",
        ]
    )

    assert exit_code == 0
    assert requested == [
        "http://api.test/projects/p-1/agent-context?recent_chapters=3&include_body=true",
        "http://api.test/projects/p-1/agent-review?chapter_number=1&include_body=true",
    ]
    assert commands
    assert commands[0][:5] == ["openclaw", "agent", "--agent", "main", "--local"]
    assert "--json" in commands[0]
    assert "--message" in commands[0]
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "openclaw-review-run/v1"
    assert output["result"]["schema_version"] == "openclaw-review-result/v1"
    assert output["result"]["action"] == "approve"
    assert output["applied"] is None


def test_novel_agent_openclaw_cmd_wrapper_is_bypassed(monkeypatch):
    import scripts.novel_agent as novel_agent

    monkeypatch.setattr(novel_agent.shutil, "which", lambda command: r"D:\clawx\resources\cli\openclaw.cmd")
    monkeypatch.setattr(novel_agent.os.path, "exists", lambda path: True)

    command = novel_agent._resolve_openclaw_command("openclaw")

    assert command == [
        r"D:\clawx\resources\bin\node.exe",
        r"D:\clawx\resources\openclaw\openclaw.mjs",
    ]


def test_novel_agent_openclaw_review_can_apply_revision(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    post_payloads: list[dict] = []

    def fake_urlopen(request, timeout):
        if "agent-context" in request.full_url:
            return _FakeResponse({"schema_version": "agent-context/v1", "project": {"project_id": "p-1"}})
        if "agent-review" in request.full_url:
            return _FakeResponse({"schema_version": "agent-review/v1", "chapter": {"chapter_number": 1}})
        if request.full_url.endswith("/agent-revise"):
            post_payloads.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse({"schema_version": "agent-revision/v1", "revision": {"changed": True}})
        raise AssertionError(request.full_url)

    def fake_run(command, capture_output, text, encoding, timeout, check):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "payloads": [
                        {
                            "text": json.dumps(
                                {
                                    "schema_version": "openclaw-review-result/v1",
                                    "action": "revise",
                                    "summary": "needs work",
                                    "must_fix": ["world too thin"],
                                    "revision_instructions": ["add NPC services"],
                                    "risk_flags": [],
                                }
                            )
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(novel_agent.subprocess, "run", fake_run)
    monkeypatch.setattr(novel_agent.shutil, "which", lambda command: command)

    exit_code = novel_agent.main(
        [
            "openclaw-review",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "1",
            "--apply",
        ]
    )

    assert exit_code == 0
    assert post_payloads == [
        {
            "chapter_number": 1,
            "instructions": [
                "OpenClaw must fix: world too thin",
                "OpenClaw revision instruction: add NPC services",
            ],
            "include_body": False,
        }
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["applied"]["schema_version"] == "openclaw-review-apply/v1"
    assert output["applied"]["revision"]["schema_version"] == "agent-revision/v1"


def test_novel_agent_openclaw_review_reads_result_from_stderr(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    post_payloads: list[dict] = []

    def fake_urlopen(request, timeout):
        if "agent-context" in request.full_url:
            return _FakeResponse({"schema_version": "agent-context/v1", "project": {"project_id": "p-1"}})
        if "agent-review" in request.full_url:
            return _FakeResponse({"schema_version": "agent-review/v1", "chapter": {"chapter_number": 1}})
        if request.full_url.endswith("/agent-revise"):
            post_payloads.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse({"schema_version": "agent-revision/v1", "revision": {"changed": True}})
        raise AssertionError(request.full_url)

    def fake_run(command, capture_output, text, encoding, timeout, check):
        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr=json.dumps(
                {
                    "meta": {
                        "finalAssistantRawText": json.dumps(
                            {
                                "schema_version": "openclaw-review-result/v1",
                                "action": "revise",
                                "summary": "stderr result",
                                "must_fix": ["parse stderr"],
                                "revision_instructions": ["apply stderr review"],
                                "risk_flags": [],
                            }
                        )
                    }
                }
            ),
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(novel_agent.subprocess, "run", fake_run)
    monkeypatch.setattr(novel_agent.shutil, "which", lambda command: command)

    exit_code = novel_agent.main(
        [
            "openclaw-review",
            "p-1",
            "--api-base",
            "http://api.test",
            "--chapter-number",
            "1",
            "--apply",
        ]
    )

    assert exit_code == 0
    assert post_payloads == [
        {
            "chapter_number": 1,
            "instructions": [
                "OpenClaw must fix: parse stderr",
                "OpenClaw revision instruction: apply stderr review",
            ],
            "include_body": False,
        }
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["result"]["action"] == "revise"
    assert output["applied"]["revision"]["schema_version"] == "agent-revision/v1"


def test_novel_agent_openclaw_review_pauses_on_non_json_output(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    def fake_urlopen(request, timeout):
        if "agent-context" in request.full_url:
            return _FakeResponse({"schema_version": "agent-context/v1", "project": {"project_id": "p-1"}})
        return _FakeResponse({"schema_version": "agent-review/v1", "chapter": {"chapter_number": 1}})

    def fake_run(command, capture_output, text, encoding, timeout, check):
        return SimpleNamespace(returncode=0, stdout="I read it, but here is prose instead.", stderr="")

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(novel_agent.subprocess, "run", fake_run)
    monkeypatch.setattr(novel_agent.shutil, "which", lambda command: command)

    exit_code = novel_agent.main(["openclaw-review", "p-1", "--api-base", "http://api.test"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["result"]["schema_version"] == "openclaw-review-result/v1"
    assert output["result"]["action"] == "pause"
    assert "non_json_output" in output["result"]["risk_flags"]


def test_novel_agent_openclaw_parser_reads_final_assistant_raw_text():
    import scripts.novel_agent as novel_agent

    stdout = (
        'noise before "finalAssistantRawText": '
        + json.dumps(
            json.dumps(
                {
                    "schema_version": "openclaw-review-result/v1",
                    "action": "revise",
                    "summary": "needs revision",
                    "must_fix": ["expand"],
                    "revision_instructions": ["add scene"],
                    "risk_flags": [],
                }
            )
        )
        + ', "stopReason": "stop" noise after'
    )

    result = novel_agent.parse_openclaw_agent_output(stdout)

    assert result["schema_version"] == "openclaw-review-result/v1"
    assert result["action"] == "revise"
    assert result["revision_instructions"] == ["add scene"]


def test_novel_agent_openclaw_parser_reads_escaped_final_assistant_raw_text():
    import scripts.novel_agent as novel_agent

    review_json = json.dumps(
        {
            "schema_version": "openclaw-review-result/v1",
            "action": "revise",
            "summary": "escaped",
            "must_fix": ["fix"],
            "revision_instructions": ["revise"],
            "risk_flags": [],
        }
    )
    escaped_fragment = json.dumps(f'"finalAssistantRawText": {json.dumps(review_json)}')

    result = novel_agent.parse_openclaw_agent_output(escaped_fragment)

    assert result["schema_version"] == "openclaw-review-result/v1"
    assert result["action"] == "revise"
    assert result["must_fix"] == ["fix"]


def test_novel_agent_auto_uses_openclaw_provider_for_review_loop(monkeypatch, capsys):
    import scripts.novel_agent as novel_agent

    openclaw_actions = ["revise", "approve"]
    post_payloads: list[dict] = []

    def fake_urlopen(request, timeout):
        if "agent-context" in request.full_url:
            return _FakeResponse(
                {
                    "schema_version": "agent-context/v1",
                    "project": {"project_id": "p-1"},
                    "active_story": {"story_id": "s-1", "current_chapter": 0},
                    "recent_chapters": [],
                }
            )
        if request.full_url.endswith("/stories/s-1/generation-jobs"):
            return _FakeResponse({"job_id": "gj-openclaw", "story_id": "s-1", "status": "queued"})
        if request.full_url.endswith("/stories/s-1/generation-jobs/gj-openclaw"):
            return _FakeResponse({"job_id": "gj-openclaw", "story_id": "s-1", "status": "completed", "chapter_number": 1})
        if "agent-review" in request.full_url:
            return _FakeResponse(
                {
                    "schema_version": "agent-review/v1",
                    "chapter": {"chapter_number": 1, "body_chars": 3300},
                }
            )
        if request.full_url.endswith("/agent-revise"):
            post_payloads.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse({"schema_version": "agent-revision/v1", "revision": {"changed": True}})
        raise AssertionError(request.full_url)

    def fake_run(command, capture_output, text, encoding, timeout, check):
        action = openclaw_actions.pop(0)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "payloads": [
                        {
                            "text": json.dumps(
                                {
                                    "schema_version": "openclaw-review-result/v1",
                                    "action": action,
                                    "summary": action,
                                    "must_fix": ["needs stronger world"] if action == "revise" else [],
                                    "revision_instructions": ["add NPC loop"] if action == "revise" else [],
                                    "risk_flags": [],
                                }
                            )
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(novel_agent.subprocess, "run", fake_run)
    monkeypatch.setattr(novel_agent.shutil, "which", lambda command: command)

    exit_code = novel_agent.main(
        [
            "auto",
            "p-1",
            "--api-base",
            "http://api.test",
            "--intent",
            "自动写并审核第一章",
            "--review-provider",
            "openclaw",
            "--max-revisions",
            "1",
            "--openclaw-agent",
            "main",
            "--timeout",
            "120",
            "--include-body",
        ]
    )

    assert exit_code == 0
    assert openclaw_actions == []
    assert post_payloads == [
        {
            "chapter_number": None,
            "instructions": [
                "OpenClaw must fix: needs stronger world",
                "OpenClaw revision instruction: add NPC loop",
            ],
            "include_body": True,
        }
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "novel-auto-run/v1"
    assert output["generated"] is True
    assert output["revision_attempts"] == 1
    assert output["final_openclaw_result"]["action"] == "approve"


def test_novel_agent_cli_outputs_utf8_for_agent_pipes(monkeypatch):
    import scripts.novel_agent as novel_agent

    fake_stdout = _FakeStdout()

    def fake_urlopen(request, timeout):
        return _FakeResponse(
            {
                "schema_version": "agent-review/v1",
                "project": {"title": "苟在网游里成神"},
                "chapter": {"chapter_number": 2},
            }
        )

    monkeypatch.setattr(novel_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(novel_agent.sys, "stdout", fake_stdout)

    exit_code = novel_agent.main(["review", "p-1", "--api-base", "http://api.test"])

    assert exit_code == 0
    assert fake_stdout.reconfigure_calls[0]["encoding"] == "utf-8"
    assert "苟在网游里成神" in "".join(fake_stdout.output)
