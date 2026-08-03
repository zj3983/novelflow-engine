import sqlite3
import json

conn = sqlite3.connect('apps/api/data/stories.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# List tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r['name'] for r in cur.fetchall()]
print('Tables:', tables)

# Check chapters table
if 'chapters' in tables:
    cur.execute('SELECT COUNT(*) as cnt FROM chapters')
    print('Chapter count:', cur.fetchone()['cnt'])
    
    cur.execute("SELECT * FROM chapters ORDER BY created_at DESC LIMIT 5")
    rows = cur.fetchall()
    for r in rows:
        d = dict(r)
        body = d.get('body', '')
        if body:
            d['body'] = body[:200] + '...' if len(body) > 200 else body
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
        print('---')
else:
    print('No chapters table')

# Also check stories
if 'stories' in tables:
    cur.execute("SELECT * FROM stories ORDER BY updated_at DESC LIMIT 5")
    rows = cur.fetchall()
    for r in rows:
        d = dict(r)
        print('Story:', json.dumps(d, ensure_ascii=False, indent=2, default=str))

conn.close()
