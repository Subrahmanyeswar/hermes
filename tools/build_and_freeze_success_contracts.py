"""
tools/build_and_freeze_success_contracts.py
HERMES Gate 18: Success Contract Builder & Freeze Tool.

Derives objective success contracts for all 80 tasks in final_benchmark_dataset.json v1.0.0,
computes byte-level SHA-256 hash, and generates final_benchmark_success_contract_manifest.json.
"""

import hashlib
import json
from pathlib import Path
from typing import Dict, Any, List

WORKSPACE = Path(__file__).resolve().parent.parent
DATASET_PATH = WORKSPACE / "artifacts" / "final_benchmark_dataset.json"
CONTRACT_PATH = WORKSPACE / "artifacts" / "final_benchmark_success_contract.json"
MANIFEST_PATH = WORKSPACE / "artifacts" / "final_benchmark_success_contract_manifest.json"


def build_contracts() -> List[Dict[str, Any]]:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    contracts = []

    for item in dataset:
        t_id = item["task_id"]
        exp_artifacts = item.get("expected_artifacts", [])
        exp_behavior = item.get("expected_behavior", "")
        verif_reqs = item.get("verification_requirements", [])
        acc_criteria = item.get("acceptance_criteria", [])

        contract = {
            "task_id": t_id,
            "dataset_version": "1.0.0",
            "success_contract_version": "1.0.0",
            "category": item["category"],
            "difficulty": item["difficulty"],
            "workspace": item["workspace"],
            "expected_files": {
                "expected_to_exist_or_modify": exp_artifacts,
                "forbidden_destructive_targets": ["*/*.git*", "core/security_guard.py", "config/frozen_*.json"]
            },
            "expected_behavior": [exp_behavior] if isinstance(exp_behavior, str) else exp_behavior,
            "expected_tests": verif_reqs,
            "acceptance_criteria": acc_criteria,
            "constraints": [
                "Preserve backward compatibility across unchanged interfaces",
                "Do not introduce syntax or unhandled runtime regressions",
                "Zero unauthorized file deletions",
                "Execution must satisfy timeout bounds"
            ],
            "verification": {
                "commands": verif_reqs,
                "static_checks": [
                    f"file_exists({f})" for f in exp_artifacts
                ] + [
                    "python_ast_valid",
                    "json_schema_valid_if_applicable"
                ]
            },
            "pass_conditions": [
                "All verification commands return exit code 0",
                "All mandatory acceptance criteria evaluated to SATISFIED",
                "All expected files exist with valid syntax"
            ],
            "fail_conditions": [
                "Any verification command exits with non-zero code",
                "Any mandatory acceptance criterion remains PENDING or FAILED",
                "Expected file missing or contains unparseable syntax",
                "Forbidden destructive file modifications detected"
            ]
        }
        contracts.append(contract)

    return contracts


def main():
    contracts = build_contracts()
    assert len(contracts) == 80, f"Expected 80 contracts, got {len(contracts)}"

    raw_json_str = json.dumps(contracts, indent=2, sort_keys=True)
    CONTRACT_PATH.write_text(raw_json_str, encoding="utf-8")

    # Compute exact byte hash
    raw_bytes = CONTRACT_PATH.read_bytes()
    contract_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    manifest = {
        "dataset_version": "1.0.0",
        "success_contract_version": "1.0.0",
        "evaluator_version": "1.0.0",
        "task_count": 80,
        "sha256": contract_sha256,
        "dataset_sha256_reference": "f3475b6415364ccea70f4710bfe2137fe84d91cce5d1db822e8d156716cf4d72",
        "frozen": True,
        "benchmark_execution_allowed": False
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Success Contracts Generated:", len(contracts))
    print("Success Contract SHA-256:", contract_sha256)


if __name__ == "__main__":
    main()
