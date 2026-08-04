import sqlite3, json

conn = sqlite3.connect('apps/api/data/stories.db')
cur = conn.cursor()

# Check s-retry-035100
cur.execute("SELECT story_id, story_state, updated_at FROM stories WHERE story_id='s-retry-035100'")
row = cur.fetchone()
if row:
    state = json.loads(row[1])
    print("Found s-retry-035100")
    print("  Updated:", row[2])
    print("  Chapter:", state.get('current_chapter'))
    print("  Summaries:", len(state.get('chapter_summaries', [])))
    print("  Status:", state.get('status', 'N/A'))
    print("  Pipeline:", state.get('pipeline_stage', 'N/A'))
    print("  Title:", state.get('title', 'N/A'))
    print("  Recent events:", state.get('agent_runtime', {}).get('recent_events', [])[-3:])
else:
    print("s-retry-035100 not found in DB")

# Check all recent stories
print("\n--- All stories (last 5) ---")
cur.execute("SELECT story_id, story_state, updated_at FROM stories ORDER BY updated_at DESC LIMIT 5")
rows = cur.fetchall()
for r in rows:
    state = json.loads(r[1])
    ps = state.get('pipeline_stage', '')
    st = state.get('status', '')
    ch = state.get('current_chapter', 0)
    print(f"  {r[0]} | status={st} | pipeline={ps} | chapter={ch} | updated={r[2]}")

conn.close()
