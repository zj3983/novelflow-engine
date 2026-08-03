import json

import pytest

from packages.story_core.persistence.snapshot_store import SnapshotStore


def test_snapshot_store_atomic_json_and_transaction_keep_schema(tmp_path):
    store = SnapshotStore()
    first = tmp_path / 'a.json'
    second = tmp_path / 'nested' / 'b.json'

    store.write_json_atomic(first, {'name': '甲'})
    store.replace_json_transaction({first: {'name': '乙'}, second: {'value': 2}})

    assert json.loads(first.read_text(encoding='utf-8')) == {'name': '乙'}
    assert json.loads(second.read_text(encoding='utf-8')) == {'value': 2}


def test_snapshot_store_restores_files_and_removes_new_managed_files(tmp_path):
    store = SnapshotStore()
    directory = tmp_path / 'managed'
    original = directory / 'original.txt'
    original.parent.mkdir(parents=True)
    original.write_text('before', encoding='utf-8')
    snapshot = store.snapshot_managed_files([original], [directory])

    original.write_text('after', encoding='utf-8')
    added = directory / 'added.txt'
    added.write_text('new', encoding='utf-8')
    store.restore_managed_files(*snapshot)

    assert original.read_text(encoding='utf-8') == 'before'
    assert not added.exists()


def test_snapshot_store_rolls_back_transaction_on_replace_failure(tmp_path, monkeypatch):
    store = SnapshotStore()
    first = tmp_path / 'a.json'
    second = tmp_path / 'b.json'
    first.write_text('{"old": 1}', encoding='utf-8')
    calls = 0
    original_replace = store._replace_file

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('replace failed')
        return original_replace(source, target)

    monkeypatch.setattr(store, '_replace_file', fail_second)

    with pytest.raises(OSError, match='replace failed'):
        store.replace_json_transaction({first: {'new': 1}, second: {'new': 2}})

    assert first.read_text(encoding='utf-8') == '{"old": 1}'
    assert not second.exists()
