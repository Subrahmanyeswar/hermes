import sqlite3
import json
from core.persistence.database import get_canonical_database_path

db_path = get_canonical_database_path()
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT sequence, event_type, payload_json FROM mission_events WHERE mission_id = 'm_4084f1e3' ORDER BY sequence ASC").fetchall()

for r in rows:
    et = r["event_type"]
    pl = json.loads(r["payload_json"]) if r["payload_json"] else {}
    seq = r["sequence"]
    if et == "ACTION_REQUESTED":
        p = pl.get("payload", {})
        print(f"[{seq}] REQ: {p.get('tool_name')} args={p.get('arguments')}")
    elif et == "TOOL_COMPLETED":
        p = pl.get("payload", {})
        print(f"[{seq}] COMPLETED: {p.get('tool_name')} succ={p.get('success')} headline={p.get('headline')} out={str(p.get('output_preview'))[:60]}")
    elif et == "TOOL_FAILED":
        p = pl.get("payload", {})
        print(f"[{seq}] FAILED: {p.get('tool_name')} err={p.get('error')}")
