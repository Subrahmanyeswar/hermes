import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.persistence.database import SQLiteDatabase, get_canonical_database_path

db = SQLiteDatabase(get_canonical_database_path())
with db._get_connection() as conn:
    rows = conn.execute(
        "SELECT sequence, event_type, payload_json FROM mission_events WHERE mission_id = 'm_b312d1c3' ORDER BY sequence ASC"
    ).fetchall()

print(f"Total events for m_b312d1c3: {len(rows)}")

tool_events = []
for seq, et, p_raw in rows:
    p = json.loads(p_raw) if isinstance(p_raw, str) else p_raw
    if et in ("TOOL_STARTED", "TOOL_COMPLETED", "TOOL_FAILED", "ACTION_REQUESTED", "ACTION_DENIED", "AGENT_STALL_DETECTED", "MODEL_FAILED"):
        tool_events.append((seq, et, p))

print(f"Total tool/action events: {len(tool_events)}")

# Print all failed tools
failed = [x for x in tool_events if x[1] == "TOOL_FAILED"]
print(f"\n--- FAILED TOOLS ({len(failed)}) ---")
for seq, et, p in failed:
    print(f"Seq {seq}: keys={list(p.keys()) if isinstance(p, dict) else type(p)}")
    print(f"   content: {p}")

# Print observations
print("\n--- SAMPLE OBSERVATIONS (first 10) ---")
obs = [x for x in rows if json.loads(x[2]).get("event_type") == "OBSERVATION_CREATED"]
for seq, et, p_raw in obs[:15]:
    p = json.loads(p_raw)
    inner = p.get("payload", {})
    tool = inner.get("tool_name")
    summary = inner.get("summary", "")[:120]
    print(f"Seq {seq}: tool={tool} | {summary}")

