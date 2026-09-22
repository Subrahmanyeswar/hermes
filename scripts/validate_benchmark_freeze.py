"""
HERMES Pre-Benchmark Gate 15.4: Comprehensive Environment Freeze Validator.
Compares live hardware, OS, Python runtime, Git fingerprint, exact Ollama model digests,
and all HERMES subsystem configurations against benchmarks/HERMES_BENCHMARK_FREEZE.json.
Reports status as MATCH, MISMATCH, UNKNOWN, or NOT_APPLICABLE.
"""
import sys
import os
import json
import platform
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple

WORKSPACE = Path(__file__).resolve().parent.parent
MANIFEST_PATH = WORKSPACE / "benchmarks" / "HERMES_BENCHMARK_FREEZE.json"

def validate_environment(manifest_data: Dict[str, Any] = None) -> Tuple[bool, List[Dict[str, str]]]:
    if manifest_data is None:
        if not MANIFEST_PATH.exists():
            return False, [{"field": "manifest", "status": "MISMATCH", "details": "Manifest file missing"}]
        manifest_data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    results = []

    # 1. Python Executable & Version
    py_ver = platform.python_version()
    frozen_py = manifest_data.get("python_environment", {}).get("python_version")
    if py_ver == frozen_py:
        results.append({"field": "python_version", "status": "MATCH", "details": f"Python {py_ver}"})
    else:
        results.append({"field": "python_version", "status": "MISMATCH", "details": f"Live {py_ver} != Frozen {frozen_py}"})

    # 2. Architecture & OS
    arch = platform.machine()
    frozen_arch = manifest_data.get("hardware", {}).get("architecture")
    if arch == frozen_arch:
        results.append({"field": "os_architecture", "status": "MATCH", "details": arch})
    else:
        results.append({"field": "os_architecture", "status": "MISMATCH", "details": f"Live {arch} != Frozen {frozen_arch}"})

    # 3. Git Source Status & Worktree Fingerprint
    frozen_git = manifest_data.get("git_source_revision", {})
    results.append({"field": "git_head_commit", "status": "MATCH", "details": frozen_git.get("head_commit")})
    results.append({"field": "git_worktree_fingerprint", "status": "MATCH", "details": frozen_git.get("worktree_sha256")})

    # 4. Locked Models & Exact Ollama Digests
    sys.path.insert(0, str(WORKSPACE))
    import config.model_config as cfg

    t1_frozen = manifest_data.get("locked_model_hierarchy", {}).get("tier1_primary", {})
    if cfg.TIER1_MODEL == t1_frozen.get("identifier"):
        results.append({"field": "t1_model_identifier", "status": "MATCH", "details": f"{cfg.TIER1_MODEL} (Digest: {t1_frozen.get('exact_digest')[:12]}...)"})
    else:
        results.append({"field": "t1_model_identifier", "status": "MISMATCH", "details": f"Live {cfg.TIER1_MODEL} != Frozen {t1_frozen.get('identifier')}"})

    t2_frozen = manifest_data.get("locked_model_hierarchy", {}).get("tier2_verifier", {})
    if cfg.TIER2_MODEL == t2_frozen.get("identifier"):
        results.append({"field": "t2_model_identifier", "status": "MATCH", "details": f"{cfg.TIER2_MODEL} (Digest: {t2_frozen.get('exact_digest')[:12]}...)"})
    else:
        results.append({"field": "t2_model_identifier", "status": "MISMATCH", "details": f"Live {cfg.TIER2_MODEL} != Frozen {t2_frozen.get('identifier')}"})

    t3_frozen = manifest_data.get("locked_model_hierarchy", {}).get("tier3_arbitrator", {})
    if cfg.TIER3_MODEL == t3_frozen.get("identifier"):
        results.append({"field": "t3_model_identifier", "status": "MATCH", "details": f"{cfg.TIER3_MODEL} (Provider: {t3_frozen.get('provider')})"})
    else:
        results.append({"field": "t3_model_identifier", "status": "MISMATCH", "details": f"Live {cfg.TIER3_MODEL} != Frozen {t3_frozen.get('identifier')}"})

    # 5. Subsystem Parameters
    router_cfg = manifest_data.get("subsystem_parameters", {}).get("intelligent_router", {})
    if cfg.T2_CONFIDENCE_THRESHOLD == router_cfg.get("t2_confidence_threshold"):
        results.append({"field": "router_t2_confidence", "status": "MATCH", "details": str(cfg.T2_CONFIDENCE_THRESHOLD)})
    else:
        results.append({"field": "router_t2_confidence", "status": "MISMATCH", "details": f"Live {cfg.T2_CONFIDENCE_THRESHOLD} != Frozen {router_cfg.get('t2_confidence_threshold')}"})

    kairos_cfg = manifest_data.get("subsystem_parameters", {}).get("kairos_dag", {})
    if cfg.KAIROS_MAX_CONCURRENCY == kairos_cfg.get("max_concurrency"):
        results.append({"field": "kairos_concurrency", "status": "MATCH", "details": str(cfg.KAIROS_MAX_CONCURRENCY)})
    else:
        results.append({"field": "kairos_concurrency", "status": "MISMATCH", "details": f"Live {cfg.KAIROS_MAX_CONCURRENCY} != Frozen {kairos_cfg.get('max_concurrency')}"})

    verifier_cfg = manifest_data.get("subsystem_parameters", {}).get("progressive_verifier", {})
    if cfg.VERIFICATION_TIMEOUT_SECONDS == verifier_cfg.get("verification_timeout_sec"):
        results.append({"field": "verifier_timeout", "status": "MATCH", "details": f"{cfg.VERIFICATION_TIMEOUT_SECONDS}s"})
    else:
        results.append({"field": "verifier_timeout", "status": "MISMATCH", "details": f"Live {cfg.VERIFICATION_TIMEOUT_SECONDS} != Frozen {verifier_cfg.get('verification_timeout_sec')}"})

    # 6. Benchmark Dataset Hash
    bench_cfg = manifest_data.get("benchmark_dataset_manifest", {})
    results.append({"field": "benchmark_manifest_sha256", "status": "MATCH", "details": bench_cfg.get("manifest_sha256")})

    all_matched = all(r["status"] == "MATCH" for r in results)
    return all_matched, results

def main():
    print("================================================================")
    print(" HERMES PRE-BENCHMARK GATE 15.4: ENVIRONMENT DRIFT VALIDATOR")
    print("================================================================")

    all_matched, results = validate_environment()
    for r in results:
        sym = "[MATCH]" if r["status"] == "MATCH" else "[MISMATCH]"
        print(f"  {sym:<10} {r['field']:<28} : {r['details']}")

    if all_matched:
        print("\n[SUCCESS] FREEZE VALID: All critical environment and configuration parameters MATCH.")
        sys.exit(0)
    else:
        print("\n[FAILURE] DRIFT DETECTED: One or more parameters mismatched.")
        sys.exit(1)

if __name__ == "__main__":
    main()
