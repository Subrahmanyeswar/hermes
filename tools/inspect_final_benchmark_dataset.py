"""
tools/inspect_final_benchmark_dataset.py
Read-only inspection utility for the frozen HERMES Final Benchmark Dataset.
"""
import json
import hashlib
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
DATASET_PATH = WORKSPACE / "artifacts" / "final_benchmark_dataset.json"
MANIFEST_PATH = WORKSPACE / "artifacts" / "final_benchmark_manifest.json"

def inspect():
    if not DATASET_PATH.exists():
        print("Dataset not found at:", DATASET_PATH)
        return
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    
    # Verify hash from exact file bytes
    raw_bytes = DATASET_PATH.read_bytes()
    actual_hash = hashlib.sha256(raw_bytes).hexdigest()
    hash_valid = (actual_hash == manifest["sha256"])
    
    print("==================================================")
    print("HERMES FINAL BENCHMARK DATASET INSPECTION")
    print("==================================================")
    print("Dataset Version:", manifest["dataset_version"])
    print("Total Tasks:", len(data))
    print("Expected Tasks:", manifest["task_count"])
    print("Dataset Hash (SHA-256):", actual_hash)
    print("Hash Validated Against Manifest:", "VALID" if hash_valid else "MISMATCH")
    print("Frozen:", manifest["frozen"])
    print("Benchmark Execution Allowed:", manifest["benchmark_execution_allowed"])
    print("--------------------------------------------------")
    print("Category Breakdown:")
    for cat, count in manifest["categories"].items():
        print(f"  - {cat}: {count}")
    print("--------------------------------------------------")
    print("Difficulty Breakdown:")
    for diff, count in manifest["difficulty_distribution"].items():
        print(f"  - {diff}: {count}")
    print("==================================================")

if __name__ == "__main__":
    inspect()
