import hashlib
from pathlib import Path

targets = {
    "dataset": ("artifacts/final_benchmark_dataset.json", "f3475b6415364ccea70f4710bfe2137fe84d91cce5d1db822e8d156716cf4d72"),
    "contract": ("artifacts/final_benchmark_success_contract.json", "4cf78a7dce0cfedfeb81e5e6929241fb7fd69d5eba0ba2b91888f6744834fff3"),
    "protocol": ("artifacts/FINAL_BENCHMARK_EXECUTION_PROTOCOL.md", "8740e0a6face5b1b4ce1b23839a97605cffb63045e289bda7b297fb83d8bfe15")
}

all_match = True
for name, (path, expected) in targets.items():
    p = Path(path)
    if not p.exists():
        print(f"FAIL: {name} file not found at {path}")
        all_match = False
        continue
    content = p.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected:
        print(f"FAIL: {name} hash mismatch! got {digest}, expected {expected}")
        all_match = False
    else:
        print(f"PASS: {name} hash verified ({digest[:16]}...)")

if not all_match:
    print("\nBENCHMARK INTEGRITY VERIFICATION: FAILED")
    exit(1)
else:
    print("\nBENCHMARK INTEGRITY VERIFICATION: ALL MATCH (FROZEN)")
