import sqlite3, os, json

db_path = os.path.expandvars(r'%LOCALAPPDATA%\HERMES\hermes_runtime.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
rows = cur.execute('SELECT event_type, payload_json FROM mission_events WHERE mission_id = "m_b2361dc6"').fetchall()
for etype, pjson in rows:
    p = json.loads(pjson) if pjson else {}
    pl = p.get('payload', {})
    if 'content' in pl or 'tool_calls' in pl or 'reasoning' in pl or 'text' in pl:
        print(f"[{etype}]")
        for k in ('content', 'text', 'reasoning', 'tool_calls', 'headline'):
            if k in pl:
                val = str(pl[k])
                print(f"  {k}: {val[:300]}")


