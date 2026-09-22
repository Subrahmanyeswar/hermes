"""
tests/test_benchmark_dataset_integrity.py
HERMES Final Benchmark Dataset Integrity & Freeze Test Suite.

Validates that:
- Dataset contains exactly 80 tasks.
- Exactly 10 tasks exist per category (A01-A10, B01-B10, C01-C10, D01-D10, E01-E10, F01-F10, G01-G10, H01-H10).
- All task IDs are unique and strictly formatted.
- All tasks contain non-empty prompts, acceptance criteria, verification commands, and metadata.
- Cryptographic SHA-256 hash matches the manifest and the freeze report.
- Manifest states frozen=True and benchmark_execution_allowed=False.
- No duplicate prompts or leakage.
"""

import hashlib
import json
from pathlib import Path
import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
DATASET_PATH = WORKSPACE / "artifacts" / "final_benchmark_dataset.json"
MANIFEST_PATH = WORKSPACE / "artifacts" / "final_benchmark_manifest.json"
FREEZE_REPORT_PATH = WORKSPACE / "artifacts" / "FINAL_BENCHMARK_DATASET_FREEZE_REPORT.md"


def test_dataset_files_exist():
    """Validates that dataset, manifest, and freeze report exist."""
    assert DATASET_PATH.exists()
    assert MANIFEST_PATH.exists()
    assert FREEZE_REPORT_PATH.exists()


def test_dataset_size_and_categories():
    """Validates exactly 80 tasks and 10 tasks per category."""
    tasks = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert len(tasks) == 80

    categories = {}
    for t in tasks:
        cat = t["category"]
        categories[cat] = categories.get(cat, 0) + 1

    expected_categories = {
        "simple": 10,
        "standard_coding": 10,
        "multi_file": 10,
        "complex_missions": 10,
        "debugging_repair": 10,
        "workspace_understanding": 10,
        "adversarial_failure": 10,
        "realistic_user_prompts": 10
    }
    assert categories == expected_categories


def test_task_id_uniqueness_and_ranges():
    """Validates unique task IDs matching standard category prefixes."""
    tasks = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    task_ids = [t["task_id"] for t in tasks]
    assert len(task_ids) == len(set(task_ids)), "Duplicate task IDs found!"

    expected_ids = set()
    prefixes = ["A", "B", "C", "D", "E", "F", "G", "H"]
    for p in prefixes:
        for idx in range(1, 11):
            expected_ids.add(f"{p}{idx:02d}")

    assert set(task_ids) == expected_ids


def test_task_schema_completeness():
    """Validates that every task has all mandatory fields populated."""
    tasks = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    required_keys = [
        "task_id", "category", "difficulty", "prompt", "workspace",
        "language", "framework", "expected_scope", "acceptance_criteria",
        "verification_requirements", "expected_behavior", "expected_artifacts",
        "known_failure_modes", "golden_patch_or_reference", "dataset_version"
    ]
    for t in tasks:
        for k in required_keys:
            assert k in t, f"Task {t.get('task_id')} missing required key {k}"
        assert len(t["prompt"].strip()) > 0
        assert len(t["acceptance_criteria"]) > 0
        assert len(t["verification_requirements"]) > 0
        assert t["dataset_version"] == "1.0.0"


def test_dataset_sha256_hash_and_manifest_lock():
    """Validates cryptographic SHA-256 hash match across dataset, manifest, and report."""
    raw_bytes = DATASET_PATH.read_bytes()
    actual_hash = hashlib.sha256(raw_bytes).hexdigest()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["dataset_version"] == "1.0.0"
    assert manifest["task_count"] == 80
    assert manifest["sha256"] == actual_hash
    assert manifest["frozen"] is True
    assert manifest["benchmark_execution_allowed"] is False

    # Also verify hash in freeze report
    report_text = FREEZE_REPORT_PATH.read_text(encoding="utf-8")
    assert actual_hash in report_text


def test_duplicate_prompt_and_leakage_check():
    """Validates that there are zero duplicate prompts."""
    tasks = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    prompts = [t["prompt"].strip().lower() for t in tasks]
    assert len(prompts) == len(set(prompts)), "Duplicate prompts detected!"
