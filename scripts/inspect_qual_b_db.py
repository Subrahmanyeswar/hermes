# scripts/inspect_qual_b_db.py
import sqlite3
import json

db_path = r'generated_projects/live_qual_b_python/.hermes/hermes_state.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('Tables:', tables)
for t in tables:
    count = cursor.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    print(f"{t}: {count} rows")

if 'runtime_state' in tables:
    for row in cursor.execute("SELECT * FROM runtime_state").fetchall():
        print("runtime_state:", row[0], row[1])
        try:
            d = json.loads(row[2])
            print("Status:", d.get("status"), "Turns:", d.get("turns_completed"), "Tasks:", len(d.get("tasks", [])))
        except Exception:
            pass
