import sqlite3, json

conn = sqlite3.connect('apps/api/data/stories.db')
cur = conn.cursor()

cur.execute("SELECT story_id, story_state FROM stories WHERE story_id='s-retry-035100'")
row = cur.fetchone()
state = json.loads(row[1])

# Get chapter 1 from memory_index
memory_index = state.get('memory_index', [])
for m in memory_index:
    if m['chapter_number'] == 1:
        body = m.get('summary', '')
        print(f"Chapter 1: {m.get('chapter_title', 'N/A')}")
        print(f"Chars: {len(body)}")
        print(f"---BODY_START---")
        print(body)
        print(f"---BODY_END---")

# Get quality info from chapter_summaries
for s in state.get('chapter_summaries', []):
    if s['chapter_number'] == 1:
        print(f"\nQuality info:")
        print(json.dumps(s.get('quality', {}), ensure_ascii=False, indent=2))

conn.close()
