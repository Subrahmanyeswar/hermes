import sqlite3
import json
from core.persistence.database import get_canonical_database_path

conn = sqlite3.connect(get_canonical_database_path())
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT sequence, event_type, payload_json FROM mission_events WHERE mission_id = 'm_4084f1e3' ORDER BY sequence ASC"
).fetchall()

turns = []
current_turn = None
for r in rows:
    et = r["event_type"]
    pl = json.loads(r["payload_json"]) if r["payload_json"] else {}
    if et == "AGENT_TURN_STARTED":
        current_turn = {
            "turn_id": pl.get("turn_id"),
            "seq": r["sequence"],
            "decisions": [],
            "actions": [],
            "tools": [],
            "stalls": [],
        }
        turns.append(current_turn)
    elif et == "AGENT_DECISION" and current_turn:
        current_turn["decisions"].append(pl)
    elif et == "ACTION_REQUESTED" and current_turn:
        current_turn["actions"].append(pl)
    elif et in ("TOOL_STARTED", "TOOL_COMPLETED", "TOOL_FAILED") and current_turn:
        current_turn["tools"].append((et, pl))
    elif et == "AGENT_STALL_DETECTED" and current_turn:
        current_turn["stalls"].append(pl)

print(f"Total turns: {len(turns)}")
for i, t in enumerate(turns, 1):
    dec_info = []
    for d in t["decisions"]:
        dp = d.get("payload", {})
        dec_info.append(f"{dp.get('tool_name')}({dp.get('reasoning')[:40]}...)")
    
    act_info = []
    for a in t["actions"]:
        ap = a.get("payload", {})
        act_info.append(f"{ap.get('tool_name')}({ap.get('arguments')})")
        
    tool_evs = []
    for et, p in t["tools"]:
        pp = p.get("payload", {})
        tool_evs.append(f"{et}:{pp.get('tool_name')}")
        
    stalls = len(t["stalls"])
    print(f"Turn {i:02d}: Dec={dec_info} | Act={act_info} | Tools={tool_evs} | Stalls={stalls}")
