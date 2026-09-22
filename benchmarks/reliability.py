"""
benchmarks/reliability.py
HERMES Gate 19: Reliability Metrics & Protocol Aggregator.

Calculates:
1. Overall mission success rate (using Gate 18 objective evaluator).
2. First-attempt success rate vs repaired success rate.
3. Repair recovery and repair failure rates.
4. False completion & false negative rates.
5. Routing escalation frequencies (T1 -> T2 -> T3) and transition matrix.
6. Latency distributions (P50, P75, P90, P95, P99) with sample size tracking.
7. Category-level reliability breakdown (Categories A through H).
8. Repeated-attempt reliability protocol (20-task subset x 3 independent attempts).
"""

from typing import Dict, Any, List, Optional
from benchmarks.statistics import calculate_percentiles

# Deterministic 20-task subset for repeated-attempt reliability study
RELIABILITY_SUBSET_TASK_IDS = [
    "A01", "A05", "A09",
    "B01", "B05", "B09",
    "C01", "C05",
    "D01", "D05",
    "E01", "E05", "E09",
    "F01", "F05",
    "G01", "G05",
    "H01", "H05", "H09"
]


def aggregate_reliability_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregates comprehensive reliability, recovery, routing, and latency metrics from run records.
    """
    total_evaluated = len(records)
    if total_evaluated == 0:
        raise ValueError("Cannot aggregate reliability metrics on empty record list.")

    # 1. Mission Outcomes
    success_count = sum(1 for r in records if r.get("objective_status") == "PASS")
    failure_count = sum(1 for r in records if r.get("objective_status") == "FAIL")
    error_count = sum(1 for r in records if r.get("objective_status") == "ERROR")
    inconclusive_count = sum(1 for r in records if r.get("objective_status") == "INCONCLUSIVE")
    success_rate = round(success_count / total_evaluated, 4)

    # 2. First-Attempt vs Repaired Outcomes
    first_attempt_success_count = sum(
        1 for r in records
        if r.get("objective_status") == "PASS" and r.get("repair_count", 0) == 0
    )
    first_attempt_success_rate = round(first_attempt_success_count / total_evaluated, 4)

    repair_required_count = sum(1 for r in records if r.get("repair_count", 0) > 0)
    repair_required_rate = round(repair_required_count / total_evaluated, 4)

    repaired_and_passed_count = sum(
        1 for r in records
        if r.get("objective_status") == "PASS" and r.get("repair_count", 0) > 0
    )
    repaired_and_failed_count = sum(
        1 for r in records
        if r.get("objective_status") != "PASS" and r.get("repair_count", 0) > 0
    )

    repair_success_rate = (
        round(repaired_and_passed_count / repair_required_count, 4)
        if repair_required_count > 0 else 0.0
    )
    repair_failure_rate = (
        round(repaired_and_failed_count / repair_required_count, 4)
        if repair_required_count > 0 else 0.0
    )

    # 3. False Completion & False Negative
    self_reported_completed_count = sum(
        1 for r in records if str(r.get("hermes_reported_status", "")).upper() in ["COMPLETED", "SUCCESS"]
    )
    false_completion_count = sum(1 for r in records if r.get("false_completion", False))
    false_completion_rate_all = round(false_completion_count / total_evaluated, 4)
    false_completion_rate_given_self_reported = (
        round(false_completion_count / self_reported_completed_count, 4)
        if self_reported_completed_count > 0 else 0.0
    )

    false_negative_count = sum(1 for r in records if r.get("false_negative", False))
    false_negative_rate = round(false_negative_count / total_evaluated, 4)

    # 4. Routing & Escalations
    t1_count = sum(1 for r in records if r.get("tier_used") == "T1" or "T1" in r.get("tiers_invoked", []))
    t2_escalation_count = sum(1 for r in records if "T2" in r.get("tiers_invoked", []) or r.get("tier_used") == "T2")
    t3_escalation_count = sum(1 for r in records if "T3" in r.get("tiers_invoked", []) or r.get("tier_used") == "T3")
    t3_unavailable_count = sum(1 for r in records if r.get("t3_status") == "NOT_AVAILABLE")

    t2_escalation_rate = round(t2_escalation_count / total_evaluated, 4)
    t3_escalation_rate = round(t3_escalation_count / total_evaluated, 4)

    # 5. Latency Distributions
    e2e_durations = [r["e2e_latency_s"] for r in records if "e2e_latency_s" in r and r["e2e_latency_s"] is not None]
    model_durations = [r["model_latency_s"] for r in records if "model_latency_s" in r and r["model_latency_s"] is not None]
    ttft_durations = [r["ttft_s"] for r in records if "ttft_s" in r and r["ttft_s"] is not None]
    verif_durations = [r["verification_latency_s"] for r in records if "verification_latency_s" in r and r["verification_latency_s"] is not None]
    repair_durations = [r["repair_latency_s"] for r in records if "repair_latency_s" in r and r["repair_latency_s"] is not None]

    latency_summary = {}
    if e2e_durations:
        latency_summary["e2e_mission"] = calculate_percentiles(e2e_durations, metric_name="e2e_mission_latency")
    if model_durations:
        latency_summary["model_call"] = calculate_percentiles(model_durations, metric_name="model_call_latency")
    if ttft_durations:
        latency_summary["ttft"] = calculate_percentiles(ttft_durations, metric_name="time_to_first_token")
    if verif_durations:
        latency_summary["verification"] = calculate_percentiles(verif_durations, metric_name="verification_latency")
    if repair_durations:
        latency_summary["repair"] = calculate_percentiles(repair_durations, metric_name="repair_latency")

    # 6. Category Breakdown
    categories = sorted(list(set(r.get("category", "unknown") for r in records)))
    category_breakdown = {}
    for cat in categories:
        cat_records = [r for r in records if r.get("category") == cat]
        cat_n = len(cat_records)
        cat_succ = sum(1 for r in cat_records if r.get("objective_status") == "PASS")
        cat_first = sum(1 for r in cat_records if r.get("objective_status") == "PASS" and r.get("repair_count", 0) == 0)
        cat_rep = sum(1 for r in cat_records if r.get("repair_count", 0) > 0)
        cat_false_comp = sum(1 for r in cat_records if r.get("false_completion", False))
        cat_e2e = [r["e2e_latency_s"] for r in cat_records if "e2e_latency_s" in r and r["e2e_latency_s"] is not None]

        category_breakdown[cat] = {
            "n": cat_n,
            "success_rate": round(cat_succ / cat_n, 4) if cat_n > 0 else 0.0,
            "first_attempt_success_rate": round(cat_first / cat_n, 4) if cat_n > 0 else 0.0,
            "repair_required_rate": round(cat_rep / cat_n, 4) if cat_n > 0 else 0.0,
            "false_completion_rate": round(cat_false_comp / cat_n, 4) if cat_n > 0 else 0.0,
            "latency": calculate_percentiles(cat_e2e, metric_name=f"category_{cat}_e2e") if cat_e2e else None
        }

    return {
        "tasks_evaluated": total_evaluated,
        "mission": {
            "success_count": success_count,
            "failure_count": failure_count,
            "error_count": error_count,
            "inconclusive_count": inconclusive_count,
            "success_rate": success_rate
        },
        "first_attempt": {
            "success_count": first_attempt_success_count,
            "success_rate": first_attempt_success_rate
        },
        "repair": {
            "required_count": repair_required_count,
            "required_rate": repair_required_rate,
            "success_count": repaired_and_passed_count,
            "failure_count": repaired_and_failed_count,
            "success_rate": repair_success_rate,
            "failure_rate": repair_failure_rate
        },
        "false_completion": {
            "count": false_completion_count,
            "rate_all_tasks": false_completion_rate_all,
            "rate_given_self_reported": false_completion_rate_given_self_reported
        },
        "false_negative": {
            "count": false_negative_count,
            "rate": false_negative_rate
        },
        "routing": {
            "t1_count": t1_count,
            "t2_escalation_count": t2_escalation_count,
            "t2_escalation_rate": t2_escalation_rate,
            "t3_escalation_count": t3_escalation_count,
            "t3_escalation_rate": t3_escalation_rate,
            "t3_unavailable_count": t3_unavailable_count
        },
        "latency_distributions": latency_summary,
        "category_breakdown": category_breakdown
    }


def evaluate_repeated_attempt_study(repeated_records: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Evaluates the repeated-attempt reliability study (e.g. 20 tasks x 3 independent attempts).
    """
    total_tasks = len(repeated_records)
    task_evaluations = {}
    consistent_tasks_count = 0

    for task_id, attempts in repeated_records.items():
        n_attempts = len(attempts)
        pass_count = sum(1 for a in attempts if a.get("objective_status") == "PASS")
        fail_count = sum(1 for a in attempts if a.get("objective_status") != "PASS")
        statuses = [a.get("objective_status") for a in attempts]
        
        is_consistent = len(set(statuses)) == 1
        if is_consistent:
            consistent_tasks_count += 1

        task_evaluations[task_id] = {
            "attempts_count": n_attempts,
            "passes_count": pass_count,
            "failures_count": fail_count,
            "pass_rate": round(pass_count / n_attempts, 4) if n_attempts > 0 else 0.0,
            "outcomes_sequence": statuses,
            "is_consistent": is_consistent
        }

    task_consistency_rate = round(consistent_tasks_count / total_tasks, 4) if total_tasks > 0 else 0.0

    return {
        "repeated_tasks_count": total_tasks,
        "task_consistency_rate": task_consistency_rate,
        "consistent_tasks_count": consistent_tasks_count,
        "per_task_results": task_evaluations
    }
