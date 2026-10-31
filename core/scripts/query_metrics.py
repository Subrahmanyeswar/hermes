import sqlite3
import json
from collections import Counter
from core.persistence.database import get_canonical_database_path

conn = sqlite3.connect(get_canonical_database_path())
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT event_type, payload_json FROM mission_events WHERE mission_id = 'm_4084f1e3' ORDER BY sequence ASC").fetchall()

counts = Counter([r["event_type"] for r in rows])
print("Event type counts for m_4084f1e3:")
for k, v in sorted(counts.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")

# Model calls
model_calls = [r for r in rows if r["event_type"] == "MODEL_REQUESTED"]
model_completes = [r for r in rows if r["event_type"] == "MODEL_COMPLETED"]
print(f"\nModel calls: requested={len(model_calls)}, completed={len(model_completes)}")

# Latencies
latencies = []
for r in model_completes:
    pl = json.loads(r["payload_json"]) if r["payload_json"] else {}
    lat = pl.get("payload", {}).get("latency")
    if lat:
        latencies.append(lat)
if latencies:
    print(f"Latency: min={min(latencies):.2f}s, max={max(latencies):.2f}s, avg={sum(latencies)/len(latencies):.2f}s, total={sum(latencies):.2f}s")

# Tool calls
tool_calls = [r for r in rows if r["event_type"] == "TOOL_STARTED"]
tool_completed = [r for r in rows if r["event_type"] == "TOOL_COMPLETED"]
tool_failed = [r for r in rows if r["event_type"] == "TOOL_FAILED"]
print(f"\nTool calls: started={len(tool_calls)}, completed={len(tool_completed)}, failed={len(tool_failed)}")

# Unique tools used
tool_names = Counter()
for r in tool_completed + tool_failed:
    pl = json.loads(r["payload_json"]) if r["payload_json"] else {}
    tn = pl.get("payload", {}).get("tool_name")
    if tn:
        tool_names[tn] += 1
print("Tool breakdown:", dict(tool_names))
