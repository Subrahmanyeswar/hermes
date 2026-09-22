import json
from pathlib import Path

p = Path("artifacts/final_benchmark")
for d in sorted(p.glob("final_benchmark_2026*")):
    sf = d / "final_benchmark_summary.json"
    mf = d / "manifest.json"
    if sf.exists():
        try:
            d_json = json.loads(sf.read_text(encoding="utf-8"))
            passes = d_json.get("after", {}).get("mission_success", {}).get("completed", "N/A")
            dur = d_json.get("total_benchmark_duration_seconds", "N/A")
            print(f"{d.name}: duration={dur}s, passes={passes}/80")
        except Exception as e:
            print(f"{d.name}: error reading summary: {e}")
    elif mf.exists():
        try:
            m_json = json.loads(mf.read_text(encoding="utf-8"))
            p_cnt = m_json.get("objective_passes", "N/A")
            print(f"{d.name}: manifest passes={p_cnt}/80")
        except Exception as e:
            print(f"{d.name}: error reading manifest: {e}")
    else:
        print(f"{d.name}: directory exists")
