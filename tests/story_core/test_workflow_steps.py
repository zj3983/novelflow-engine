from packages.story_core.workflow_steps import build_workflow_step_event, merge_workflow_step, normalize_workflow_step


def test_build_workflow_step_event_creates_one_structured_progress_event():
    result = build_workflow_step_event(
        "outline",
        "读取大纲",
        status="done",
        source="context_loader",
        used_modules=["outline_store"],
        reads=["总纲"],
        outputs={"chapter_goal": "推进主线"},
    )

    assert result["stage"] == "outline"
    assert result["artifact"]["workflow_step"]["reads"] == ["总纲"]
    assert result["artifact"]["used_modules"] == ["outline_store"]
    assert result["artifact"]["outputs"]["chapter_goal"] == "推进主线"


def test_normalize_workflow_step_keeps_display_and_trace_fields():
    result = normalize_workflow_step(
        {"message": "读取大纲完成", "status": "done", "stage": "context_loader", "source": "context_loader", "artifact": {"workflow_step": {"id": "outline", "label": "读取大纲", "reads": ["总纲"]}}}
    )

    assert result["message"] == "读取大纲完成"
    assert result["status"] == "done"
    assert result["stage"] == "context_loader"
    assert result["artifact"]["workflow_step"]["id"] == "outline"


def test_merge_workflow_step_replaces_same_message_without_losing_new_artifact():
    steps = [{"message": "章节规划进行中", "status": "running", "stage": "director"}]

    merge_workflow_step(
        steps,
        {"message": "章节规划进行中", "status": "done", "stage": "director", "artifact": {"outputs": {"goal": "推进主线"}}},
    )

    assert len(steps) == 1
    assert steps[0]["status"] == "done"
    assert steps[0]["artifact"]["outputs"]["goal"] == "推进主线"
