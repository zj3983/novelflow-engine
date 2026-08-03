import sqlite3
import json

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
print(f"Story: {story_id}")
print(f"Current chapter: {state.get('current_chapter')}")
print(f"Title: {state.get('title', 'N/A')}")

# Extract chapter summaries
summaries = state.get('chapter_summaries', [])
print(f"\nChapter summaries count: {len(summaries)}")

for s in summaries:
    print(f"\n{'='*60}")
    print(f"Chapter {s['chapter_number']}: {s['chapter_title']}")
    print(f"Cadence: {s.get('cadence', 'N/A')}")
    print(f"Summary: {s.get('summary', 'N/A')[:200]}")
    print(f"Facts: {s.get('facts', [])}")
    print(f"Next focus: {s.get('next_focus', 'N/A')}")
    print(f"{'='*60}")

# Extract memory index (contains full chapter body)
memory_index = state.get('memory_index', [])
for m in memory_index:
    print(f"\n\n{'#'*60}")
    print(f"FULL CHAPTER {m['chapter_number']}: {m.get('chapter_title', 'N/A')}")
    print(f"{'#'*60}")
    print(m.get('summary', 'N/A')[:3000])
    print(f"\n... (truncated, full text available)")
    print(f"{'#'*60}")

conn.close()
