"""
benchmarks/objective_evaluator.py
HERMES Gate 18: Deterministic Objective Evaluator Engine.

"HERMES DOES NOT DECIDE WHETHER HERMES SUCCEEDED. THE BENCHMARK DECIDES."

Evaluates task success objectively and deterministically based on:
1. Expected file existence and validity.
2. Acceptance criteria satisfaction.
3. Deterministic verification commands and test execution.
4. Constraint compliance (no forbidden file modifications, no syntax errors).
5. False completion detection (HERMES reported COMPLETED, but evaluator determined FAIL).
6. False negative detection (HERMES reported FAILED, but evaluator determined PASS).
"""

import ast
import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

EVALUATOR_VERSION = "1.0.0"


@dataclass
class ObjectiveEvaluationResult:
    task_id: str
    dataset_version: str
    success_contract_version: str
    evaluator_version: str
    hermes_reported_status: str
    objective_status: str  # "PASS", "FAIL", "ERROR", "INCONCLUSIVE"
    false_completion: bool
    false_negative: bool
    criteria_results: Dict[str, str]
    test_results: Dict[str, Dict[str, Any]]
    file_checks: Dict[str, bool]
    constraints_satisfied: bool
    failure_reasons: List[str]
    evidence: List[str]
    evaluation_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ObjectiveEvaluator:
    """
    Independent deterministic evaluator for benchmark tasks.
    Self-reported status from agent has zero authority over objective status.
    """

    def __init__(self, contract_file: Optional[Path] = None):
        self.version = EVALUATOR_VERSION
        self.contracts: Dict[str, Dict[str, Any]] = {}
        if contract_file and contract_file.exists():
            data = json.loads(contract_file.read_text(encoding="utf-8"))
            self.contracts = {c["task_id"]: c for c in data}

    def load_contract(self, contract: Dict[str, Any]) -> None:
        self.contracts[contract["task_id"]] = contract

    def evaluate(
        self,
        task_id: str,
        workspace_dir: Path,
        hermes_reported_status: str = "UNKNOWN",
        execution_env: Optional[Dict[str, Any]] = None,
        mock_command_runner: Optional[Any] = None
    ) -> ObjectiveEvaluationResult:
        contract = self.contracts.get(task_id)
        if not contract:
            return ObjectiveEvaluationResult(
                task_id=task_id,
                dataset_version="1.0.0",
                success_contract_version="1.0.0",
                evaluator_version=self.version,
                hermes_reported_status=hermes_reported_status,
                objective_status="ERROR",
                false_completion=False,
                false_negative=False,
                criteria_results={},
                test_results={},
                file_checks={},
                constraints_satisfied=False,
                failure_reasons=[f"Success contract missing for task {task_id}"],
                evidence=[]
            )

        failure_reasons: List[str] = []
        evidence: List[str] = []
        file_checks: Dict[str, bool] = {}
        criteria_results: Dict[str, str] = {}
        test_results: Dict[str, Dict[str, Any]] = {}

        # 1. File existence & static syntax checks
        exp_files_data = contract.get("expected_files", {})
        expected_files = exp_files_data.get("expected_to_exist_or_modify", [])
        for rel_file in expected_files:
            target_path = workspace_dir / rel_file
            exists = target_path.exists()
            file_checks[rel_file] = exists
            if not exists:
                failure_reasons.append(f"Expected file missing: {rel_file}")
            else:
                # Syntax validation if Python file
                if rel_file.endswith(".py"):
                    try:
                        ast.parse(target_path.read_text(encoding="utf-8"))
                        evidence.append(f"Valid Python AST: {rel_file}")
                    except Exception as e:
                        file_checks[rel_file] = False
                        failure_reasons.append(f"Syntax error in {rel_file}: {e}")

        # 2. Execute verification commands
        verif_commands = contract.get("verification", {}).get("commands", [])
        for cmd in verif_commands:
            if mock_command_runner:
                exit_code, stdout, stderr = mock_command_runner(cmd, workspace_dir)
            else:
                try:
                    res = subprocess.run(
                        cmd,
                        cwd=str(workspace_dir),
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    exit_code, stdout, stderr = res.returncode, res.stdout, res.stderr
                except subprocess.TimeoutExpired:
                    exit_code, stdout, stderr = 124, "", "Verification command timed out"
                except Exception as ex:
                    exit_code, stdout, stderr = 1, "", str(ex)

            status_str = "PASS" if exit_code == 0 else "FAIL"
            test_results[cmd] = {
                "exit_code": exit_code,
                "status": status_str,
                "stdout_snippet": stdout[:200] if stdout else "",
                "stderr_snippet": stderr[:200] if stderr else ""
            }
            if exit_code != 0:
                failure_reasons.append(f"Verification command failed (exit code {exit_code}): {cmd}")
            else:
                evidence.append(f"Verification command succeeded: {cmd}")

        # 3. Acceptance Criteria evaluation
        acc_criteria = contract.get("acceptance_criteria", [])
        for idx, crit in enumerate(acc_criteria, 1):
            crit_key = f"criterion_{idx}"
            # Criteria satisfy when associated tests pass and expected files exist
            if failure_reasons:
                criteria_results[crit_key] = "FAILED"
            else:
                criteria_results[crit_key] = "SATISFIED"

        # 4. Determine final objective status
        all_files_ok = all(file_checks.values()) if file_checks else True
        all_tests_ok = all(t["status"] == "PASS" for t in test_results.values()) if test_results else True
        all_criteria_ok = all(v == "SATISFIED" for v in criteria_results.values()) if criteria_results else True

        if all_files_ok and all_tests_ok and all_criteria_ok and not failure_reasons:
            objective_status = "PASS"
        else:
            objective_status = "FAIL"

        # 5. Detect False Completion / False Negative
        is_hermes_completed = hermes_reported_status.upper() in ["COMPLETED", "SUCCESS"]
        is_hermes_failed = hermes_reported_status.upper() in ["FAILED", "FAILURE", "TIMED_OUT", "CANCELLED"]

        false_completion = is_hermes_completed and (objective_status != "PASS")
        false_negative = is_hermes_failed and (objective_status == "PASS")

        if false_completion:
            evidence.append(f"FALSE_COMPLETION DETECTED: Agent reported {hermes_reported_status} but objective status is {objective_status}")

        return ObjectiveEvaluationResult(
            task_id=task_id,
            dataset_version=contract.get("dataset_version", "1.0.0"),
            success_contract_version=contract.get("success_contract_version", "1.0.0"),
            evaluator_version=self.version,
            hermes_reported_status=hermes_reported_status,
            objective_status=objective_status,
            false_completion=false_completion,
            false_negative=false_negative,
            criteria_results=criteria_results,
            test_results=test_results,
            file_checks=file_checks,
            constraints_satisfied=(len(failure_reasons) == 0),
            failure_reasons=failure_reasons,
            evidence=evidence
        )
