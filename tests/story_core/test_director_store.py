"""Tests for the director artifact store.

The director store owns the on-disk shape of the
``DirectorArtifact``: a JSON file under
``.story-system/director/NNNN.json`` written atomically, with
the agent's input trace, output, provider, model, and status
inside the same envelope so the workbench and the migration
script can later prove exactly what produced the chapter plan.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from packages.story_core.persistence.director_store import DirectorStore


def test_director_store_writes_atomic_json_under_story_system(tmp_path: Path) -> None:
    project = tmp_path / "story"
    project.mkdir()
    (project / ".story-system").mkdir()

    store = DirectorStore(project)
    path = store.save(
        chapter_number=7,
        payload={
            "status": "ok",
            "provider": "openai",
            "model": "gpt-5",
            "input_trace": {"reads": []},
            "output": {"schema_version": "director-artifact/v1", "chapter_number": 7},
        },
    )

    assert path == project / ".story-system" / "director" / "0007.json"
    assert path.exists()
    # No leftover temp file.
    siblings = list(path.parent.iterdir())
    assert all(not name.startswith(".0007") for name in [s.name for s in siblings])
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["status"] == "ok"
    assert loaded["output"]["chapter_number"] == 7


def test_director_store_round_trips_payload(tmp_path: Path) -> None:
    project = tmp_path / "story"
    project.mkdir()
    (project / ".story-system").mkdir()
    store = DirectorStore(project)

    payload = {
        "status": "ok",
        "provider": "openai",
        "model": "gpt-5",
        "input_trace": {"reads": [{"path": "outline.json", "sha256": "abc"}]},
        "output": {
            "schema_version": "director-artifact/v1",
            "chapter_number": 12,
            "chapter_goal": "拿到进入矿区的许可",
        },
    }
    store.save(chapter_number=12, payload=payload)
    loaded = store.load(chapter_number=12)

    assert loaded == payload
    assert loaded["output"]["chapter_number"] == 12


def test_director_store_path_uses_four_digit_chapter_padding(tmp_path: Path) -> None:
    project = tmp_path / "story"
    project.mkdir()
    (project / ".story-system").mkdir()
    store = DirectorStore(project)

    assert store.path_for(3) == project / ".story-system" / "director" / "0003.json"
    assert store.path_for(123) == project / ".story-system" / "director" / "0123.json"


def test_director_store_load_returns_none_when_missing(tmp_path: Path) -> None:
    project = tmp_path / "story"
    project.mkdir()
    (project / ".story-system").mkdir()
    store = DirectorStore(project)

    assert store.load(chapter_number=99) is None


def test_director_store_rejects_chapter_numbers_below_one(tmp_path: Path) -> None:
    project = tmp_path / "story"
    project.mkdir()
    (project / ".story-system").mkdir()
    store = DirectorStore(project)

    with pytest.raises(ValueError, match=re.compile("invalid_chapter_number", re.I)):
        store.save(chapter_number=0, payload={})
    with pytest.raises(ValueError, match=re.compile("invalid_chapter_number", re.I)):
        store.save(chapter_number=-1, payload={})


def test_director_store_persists_provider_and_model_metadata(tmp_path: Path) -> None:
    """The workbench shows which provider and model produced the
    artifact, so the persisted payload must keep the
    ``provider`` and ``model`` fields intact.
    """
    project = tmp_path / "story"
    project.mkdir()
    (project / ".story-system").mkdir()
    store = DirectorStore(project)

    store.save(
        chapter_number=4,
        payload={
            "status": "fallback",
            "provider": "codex-cli",
            "model": "gpt-5-codex",
            "input_trace": {"reads": []},
            "output": {"schema_version": "director-artifact/v1", "chapter_number": 4},
        },
    )

    loaded = store.load(chapter_number=4)
    assert loaded["provider"] == "codex-cli"
    assert loaded["model"] == "gpt-5-codex"
    assert loaded["status"] == "fallback"
