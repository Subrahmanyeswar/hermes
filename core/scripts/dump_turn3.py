import sqlite3, os, json

db_path = os.path.expandvars(r'%LOCALAPPDATA%\HERMES\hermes_runtime.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
rows = cur.execute('SELECT payload_json FROM mission_events WHERE mission_id = "m_b2361dc6" AND event_type = "AGENT_DECISION"').fetchall()
with open('turn3_reasoning.txt', 'w', encoding='utf-8') as f:
    f.write(json.loads(rows[2][0])['payload']['reasoning'])
print('Wrote turn3_reasoning.txt, size:', os.path.getsize('turn3_reasoning.txt'))
