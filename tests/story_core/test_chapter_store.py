import json

from packages.story_core.persistence.chapter_store import ChapterStore


def test_chapter_store_preserves_existing_file_layout(tmp_path):
    store = ChapterStore(tmp_path)
    paths = store.paths(2, '门前/旧事')

    assert paths['json'] == tmp_path / '.story-system' / 'chapters' / '0002.json'
    assert paths['review'] == tmp_path / '.story-system' / 'reviews' / '0002.json'
    assert paths['markdown'] == tmp_path / 'chapters' / '0002-门前旧事.md'


def test_chapter_store_reads_records_and_ignores_invalid_files_when_requested(tmp_path):
    store = ChapterStore(tmp_path)
    store.chapters_directory.mkdir(parents=True)
    (store.chapters_directory / '0001.json').write_text(
        json.dumps({'chapter_number': 1, 'body': '第一章'}, ensure_ascii=False),
        encoding='utf-8',
    )
    (store.chapters_directory / '0002.json').write_text('{broken', encoding='utf-8')
    (store.chapters_directory / 'notes.json').write_text('{}', encoding='utf-8')

    assert store.chapter_numbers() == [1, 2]
    assert store.read_records(ignore_errors=True) == [
        (1, {'chapter_number': 1, 'body': '第一章'}),
        (2, {}),
    ]


def test_chapter_store_replaces_old_markdown_for_same_chapter(tmp_path):
    store = ChapterStore(tmp_path)
    store.markdown_directory.mkdir(parents=True)
    old = store.markdown_directory / '0003-旧标题.md'
    old.write_text('旧正文', encoding='utf-8')

    store.remove_markdowns(3)

    assert not old.exists()
