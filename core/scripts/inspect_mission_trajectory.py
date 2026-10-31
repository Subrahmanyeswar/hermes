import sqlite3, os, json

db_path = os.path.expandvars(r'%LOCALAPPDATA%\HERMES\hermes_runtime.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
rows = cur.execute(
    "SELECT event_type, payload_json FROM mission_events WHERE mission_id = 'm_b2361dc6' "
    "AND event_type IN ('AGENT_DECISION', 'ACTION_REQUESTED', 'ACTION_DENIED', 'TOOL_COMPLETED', 'MISSION_FAILED') "
    "ORDER BY sequence"
).fetchall()

for etype, pjson in rows:
    p = json.loads(pjson) if pjson else {}
    pl = p.get('payload', {})
    print(f"[{etype}]")
    for k, v in pl.items():
        v_str = str(v)
        if len(v_str) > 120:
            v_str = v_str[:120] + "..."
        print(f"  {k}: {v_str}")
