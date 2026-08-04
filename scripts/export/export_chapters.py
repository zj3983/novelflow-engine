import sqlite3
import json
import os

conn = sqlite3.connect('apps/api/data/stories.db')
cur = conn.cursor()

# Get the story with 2 chapters (latest)
cur.execute("SELECT story_id, story_state FROM stories WHERE story_state LIKE '%chapter_summaries%' ORDER BY updated_at DESC LIMIT 1")
row = cur.fetchone()
if not row:
    print("No story found")
    exit()

story_id = row[0]
state = json.loads(row[1])

# Extract memory index with full chapter bodies
memory_index = state.get('memory_index', [])

output_dir = os.path.join('chapter_exports', story_id)
os.makedirs(output_dir, exist_ok=True)

for m in memory_index:
    chap_num = m['chapter_number']
    chap_title = m.get('chapter_title', f'chapter_{chap_num}')
    body = m.get('summary', '')

    filename = f'chapter_{chap_num:02d}.md'
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(body)

    print(f"Exported: {filepath} ({len(body)} chars)")

print(f"\nAll chapters exported to: {output_dir}")
conn.close()
