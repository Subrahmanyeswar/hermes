import sqlite3
import json
from core.persistence.database import get_canonical_database_path

conn = sqlite3.connect(get_canonical_database_path())
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT sequence, event_type, payload_json FROM mission_events WHERE sequence BETWEEN 45775 AND 45785 ORDER BY sequence ASC").fetchall()
for r in rows:
    print(r["sequence"], r["event_type"])
    if r["event_type"] in ("ACTION_REQUESTED", "ACTION_BLOCKED", "TOOL_STARTED", "TOOL_FAILED", "TOOL_COMPLETED", "AGENT_STALL_DETECTED"):
        print("  -->", r["payload_json"][:200])
