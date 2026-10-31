import sqlite3
import json
from core.persistence.database import get_canonical_database_path

conn = sqlite3.connect(get_canonical_database_path())
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT payload_json FROM mission_events WHERE event_type = 'MODEL_COMPLETED' AND sequence < 45814 ORDER BY sequence DESC LIMIT 1").fetchone()
if r:
    pl = json.loads(r["payload_json"])
    print(repr(pl))
