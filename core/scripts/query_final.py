import sqlite3
import json
from core.persistence.database import get_canonical_database_path

conn = sqlite3.connect(get_canonical_database_path())
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT payload_json FROM mission_events WHERE sequence = 45907").fetchone()
if r:
    print(json.dumps(json.loads(r["payload_json"]), indent=2))
