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

turns = {}
for seq, et, p_raw in rows:
    p = json.loads(p_raw) if isinstance(p_raw, str) else p_raw
    inner = p.get("payload", {})
    turn_id = p.get("turn_id")
    if turn_id:
        if turn_id not in turns:
            turns[turn_id] = []
        turns[turn_id].append((seq, et, inner))

print(f"Total turns: {len(turns)}")
for tid, evs in turns.items():
    tool_evs = [e for e in evs if e[1] in ("TOOL_STARTED", "TOOL_COMPLETED", "TOOL_FAILED")]
    decision_evs = [e for e in evs if e[1] == "AGENT_DECISION"]
    dec_tool = decision_evs[0][2].get("tool_name") if decision_evs else "none"
    t_names = [e[2].get("tool_name") for e in tool_evs]
    t_exits = [e[2].get("exit_code") for e in tool_evs]
    t_hl = [e[2].get("headline") for e in tool_evs]
    print(f"{tid}: dec={dec_tool} | tools={t_names} | exits={t_exits} | headlines={t_hl}")
