import os
import sys
import hashlib
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

WS_DIR = Path(r"C:\Users\SUBBU\Downloads\testing 1").resolve()
BACKUPS_DIR = WS_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
target_backup_dir = BACKUPS_DIR / f"preflight_backup_{timestamp}"
target_backup_dir.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("CAMPUSFLOW PRE-FLIGHT AUDIT & FORENSIC BACKUP")
print("=" * 70)
print(f"Workspace: {WS_DIR}")
print(f"Backup Target: {target_backup_dir}")

# 1. Record hashes and sizes of root files and tests
files_to_record = [
    "main.py",
    "index.html",
    "style.css",
    "app.js",
    "package.json",
    "campusflow.db",
    "tests/test_campusflow.py"
]

manifest = {}
print("\n--- Source Files Inventory & SHA-256 Digests ---")
for rel_path in files_to_record:
    fpath = WS_DIR / rel_path
    if fpath.exists():
        content = fpath.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        size = len(content)
        manifest[rel_path] = {
            "size": size,
            "sha256": sha256
        }
        print(f"  {rel_path:25s} | Size: {size:6d} B | SHA256: {sha256[:16]}...")
    else:
        print(f"  {rel_path:25s} | NOT FOUND")

# 2. Backup files
print("\n--- Copying Files to Backup Directory ---")
for rel_path in files_to_record:
    if rel_path == "campusflow.db":
        continue # Handled via SQLite backup API
    src = WS_DIR / rel_path
    if src.exists():
        dst = target_backup_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  Copied {rel_path} -> {dst.relative_to(WS_DIR)}")

# 3. Consistent SQLite backup using SQLite backup API
db_src = WS_DIR / "campusflow.db"
if db_src.exists():
    db_dst = target_backup_dir / "campusflow.db"
    print(f"\n--- Performing SQLite Atomic Backup ---")
    print(f"  Source: {db_src}")
    print(f"  Target: {db_dst}")
    src_conn = sqlite3.connect(str(db_src))
    dst_conn = sqlite3.connect(str(db_dst))
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    print("  SQLite atomic backup completed successfully.")

# Save manifest to backup folder
import json
manifest_file = target_backup_dir / "FORENSIC_BASELINE_MANIFEST.json"
manifest_file.write_text(json.dumps({
    "timestamp": timestamp,
    "workspace": str(WS_DIR),
    "files": manifest
}, indent=2), encoding="utf-8")
print(f"\nManifest recorded at: {manifest_file}")
print("=" * 70)
