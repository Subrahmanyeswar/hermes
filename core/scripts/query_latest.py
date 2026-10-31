import sqlite3
import json
from core.persistence.database import get_canonical_database_path

conn = sqlite3.connect(get_canonical_database_path())
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT sequence, event_type, payload_json FROM mission_events WHERE sequence >= 45778 ORDER BY sequence ASC").fetchall()
for r in rows:
    pl = json.loads(r["payload_json"]) if r["payload_json"] else {}
    print(r["sequence"], r["event_type"], json.dumps(pl, indent=2)[:300])
