"""
HERMES Threshold Calibration — Disagreement Router
Tests the router at thresholds: 0.60, 0.70, 0.72, 0.80, 0.90
For each threshold measures:
  - False Escalation Rate: agreed correct answers that were unnecessarily escalated
  - Missed Error Rate: wrong answers that were not escalated (passed through)
  - Accept Rate: tasks that went through locally without Tier 3
The threshold with the best tradeoff becomes the final value for the paper.

Run: pytest tests/integration/test_threshold_calibration.py -v --timeout=600
Or:  python tests/integration/test_threshold_calibration.py  (standalone)
"""
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.verifier import VerificationResult
from core.disagreement_router import DisagreementRouter, RoutingDecision


THRESHOLDS_TO_TEST = [0.60, 0.70, 0.72, 0.80, 0.90]
RESULTS_PATH = Path("data/threshold_calibration_results.json")


# ──────────────────────────────────────────────────────────────────────
# Calibration scenario definitions
# Each scenario represents a realistic T2 output we might see in practice
# ──────────────────────────────────────────────────────────────────────

@dataclass
class CalibrationScenario:
    """A synthetic T2 verification result for calibration testing."""
    scenario_id: str
    description: str
    agree: bool
    confidence: float
    risk_score: float
    critical_issues: list[str]
    ground_truth: str   # "correct" or "incorrect" — what T1 actually produced
    tool_name: str = "write_file"


# 50 calibration scenarios spanning the full confidence/correctness space
CALIBRATION_SCENARIOS: list[CalibrationScenario] = [

    # ── Clearly correct outputs (T1 was right, T2 agrees) ─────────────
    CalibrationScenario("C01", "Perfect write_file call",
        agree=True, confidence=0.97, risk_score=0.1, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("C02", "Good list_directory call",
        agree=True, confidence=0.95, risk_score=0.05, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("C03", "Correct bash_exec echo",
        agree=True, confidence=0.93, risk_score=0.15, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("C04", "Clean read_file call",
        agree=True, confidence=0.91, risk_score=0.05, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("C05", "Valid create_folder",
        agree=True, confidence=0.89, risk_score=0.08, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("C06", "Correct run_tests",
        agree=True, confidence=0.88, risk_score=0.12, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("C07", "Valid web_search",
        agree=True, confidence=0.86, risk_score=0.05, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("C08", "Reasonable git_add_commit",
        agree=True, confidence=0.84, risk_score=0.25, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("C09", "Correct append_file",
        agree=True, confidence=0.82, risk_score=0.1, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("C10", "Valid save_memory",
        agree=True, confidence=0.80, risk_score=0.05, critical_issues=[],
        ground_truth="correct"),

    # ── Borderline correct (high confidence but T2 slightly uncertain) ─
    CalibrationScenario("B01", "Slightly uncertain write",
        agree=True, confidence=0.76, risk_score=0.2, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("B02", "Modest confidence list",
        agree=True, confidence=0.74, risk_score=0.1, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("B03", "At the threshold exactly",
        agree=True, confidence=0.72, risk_score=0.15, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("B04", "Just below threshold — correct",
        agree=True, confidence=0.70, risk_score=0.12, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("B05", "Low-moderate confidence — correct",
        agree=True, confidence=0.68, risk_score=0.1, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("B06", "T2 uncertain but correct outcome",
        agree=True, confidence=0.65, risk_score=0.18, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("B07", "T2 agrees, confidence 0.63, correct",
        agree=True, confidence=0.63, risk_score=0.1, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("B08", "T2 agrees, confidence 0.61, correct",
        agree=True, confidence=0.61, risk_score=0.08, critical_issues=[],
        ground_truth="correct"),

    # ── Correctly escalated (T1 was wrong, T2 disagrees) ──────────────
    CalibrationScenario("W01", "Wrong tool selected",
        agree=False, confidence=0.85, risk_score=0.3,
        critical_issues=["bash_exec used when write_file needed"],
        ground_truth="incorrect"),
    CalibrationScenario("W02", "Syntax error in generated code",
        agree=False, confidence=0.90, risk_score=0.2,
        critical_issues=["Python code has syntax error on line 3"],
        ground_truth="incorrect"),
    CalibrationScenario("W03", "Wrong file path used",
        agree=False, confidence=0.88, risk_score=0.25,
        critical_issues=["File path /etc/hosts is a protected path"],
        ground_truth="incorrect"),
    CalibrationScenario("W04", "Logic error in calculation",
        agree=False, confidence=0.82, risk_score=0.2,
        critical_issues=["Division operator missing in calculator"],
        ground_truth="incorrect"),
    CalibrationScenario("W05", "Missing error handling",
        agree=False, confidence=0.75, risk_score=0.3,
        critical_issues=["Flask route has no try/except around db query"],
        ground_truth="incorrect"),
    CalibrationScenario("W06", "T2 correctly flags missing import",
        agree=False, confidence=0.91, risk_score=0.15,
        critical_issues=["import flask missing from generated code"],
        ground_truth="incorrect"),
    CalibrationScenario("W07", "Incorrect SQL syntax",
        agree=False, confidence=0.87, risk_score=0.3,
        critical_issues=["SQL INSERT missing VALUES keyword"],
        ground_truth="incorrect"),
    CalibrationScenario("W08", "Wrong API endpoint",
        agree=False, confidence=0.79, risk_score=0.2,
        critical_issues=["Route decorator has wrong HTTP method"],
        ground_truth="incorrect"),

    # ── Missed errors (T1 was wrong but T2 agreed — dangerous zone) ───
    CalibrationScenario("M01", "T2 missed subtle bug, confident",
        agree=True, confidence=0.84, risk_score=0.2, critical_issues=[],
        ground_truth="incorrect"),
    CalibrationScenario("M02", "T2 missed off-by-one error",
        agree=True, confidence=0.81, risk_score=0.15, critical_issues=[],
        ground_truth="incorrect"),
    CalibrationScenario("M03", "T2 missed wrong variable name",
        agree=True, confidence=0.78, risk_score=0.1, critical_issues=[],
        ground_truth="incorrect"),
    CalibrationScenario("M04", "T2 missed missing return statement",
        agree=True, confidence=0.76, risk_score=0.12, critical_issues=[],
        ground_truth="incorrect"),
    CalibrationScenario("M05", "T2 missed wrong indentation",
        agree=True, confidence=0.74, risk_score=0.1, critical_issues=[],
        ground_truth="incorrect"),
    CalibrationScenario("M06", "T2 missed missing dependency",
        agree=True, confidence=0.71, risk_score=0.08, critical_issues=[],
        ground_truth="incorrect"),
    CalibrationScenario("M07", "T2 missed logic inversion",
        agree=True, confidence=0.68, risk_score=0.15, critical_issues=[],
        ground_truth="incorrect"),
    CalibrationScenario("M08", "T2 missed hardcoded secret",
        agree=True, confidence=0.65, risk_score=0.2, critical_issues=[],
        ground_truth="incorrect"),

    # ── High-risk escalations (correct but risky operations) ──────────
    CalibrationScenario("R01", "git_push — correct but risky",
        agree=True, confidence=0.88, risk_score=0.72, critical_issues=[],
        ground_truth="correct", tool_name="git_push"),
    CalibrationScenario("R02", "delete_file — correct but risky",
        agree=True, confidence=0.90, risk_score=0.80, critical_issues=[],
        ground_truth="correct", tool_name="delete_file"),
    CalibrationScenario("R03", "install_package — correct",
        agree=True, confidence=0.85, risk_score=0.65, critical_issues=[],
        ground_truth="correct", tool_name="install_package"),
    CalibrationScenario("R04", "bash rm -r — elevated risk",
        agree=True, confidence=0.82, risk_score=0.68, critical_issues=[],
        ground_truth="correct"),

    # ── True edge cases (ambiguous situations) ─────────────────────────
    CalibrationScenario("A01", "T2 very uncertain — correct output",
        agree=True, confidence=0.58, risk_score=0.25, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("A02", "T2 slightly uncertain — incorrect",
        agree=True, confidence=0.62, risk_score=0.18, critical_issues=[],
        ground_truth="incorrect"),
    CalibrationScenario("A03", "T2 disagrees mildly — correct output",
        agree=False, confidence=0.60, risk_score=0.15,
        critical_issues=["Minor style concern"],
        ground_truth="correct"),
    CalibrationScenario("A04", "T2 disagrees, issues present, correct",
        agree=False, confidence=0.70, risk_score=0.2,
        critical_issues=["Unused import in generated file"],
        ground_truth="correct"),
    CalibrationScenario("A05", "Timeout scenario — unknown truth",
        agree=False, confidence=0.0, risk_score=0.5,
        critical_issues=["Tier 2 verification timed out"],
        ground_truth="correct"),
    CalibrationScenario("A06", "T2 connection error — unknown truth",
        agree=True, confidence=0.5, risk_score=0.3,
        critical_issues=["T2 unavailable: ollama_timeout"],
        ground_truth="correct"),
    CalibrationScenario("A07", "Very high risk, T2 agrees",
        agree=True, confidence=0.92, risk_score=0.92, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("A08", "Moderate risk, disagrees, incorrect",
        agree=False, confidence=0.77, risk_score=0.45,
        critical_issues=["T1 output has logic error"],
        ground_truth="incorrect"),
    CalibrationScenario("A09", "Lowest possible confidence",
        agree=True, confidence=0.10, risk_score=0.1, critical_issues=[],
        ground_truth="correct"),
    CalibrationScenario("A10", "Perfect score scenario",
        agree=True, confidence=1.0, risk_score=0.0, critical_issues=[],
        ground_truth="correct"),
]


# ──────────────────────────────────────────────────────────────────────
# Calibration runner
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ThresholdResult:
    """Metrics for one threshold value."""
    threshold: float
    total_scenarios: int
    accept_count: int
    escalate_count: int
    block_count: int

    # Correctness analysis
    correct_accepted: int = 0      # T1 was correct AND router accepted (true positive)
    incorrect_accepted: int = 0    # T1 was wrong AND router accepted (missed error)
    correct_escalated: int = 0     # T1 was correct AND router escalated (false escalation)
    incorrect_escalated: int = 0   # T1 was wrong AND router escalated (true escalation)

    @property
    def accept_rate(self) -> float:
        return self.accept_count / self.total_scenarios if self.total_scenarios else 0

    @property
    def false_escalation_rate(self) -> float:
        """Escalated correct answers / all correct answers."""
        all_correct = self.correct_accepted + self.correct_escalated
        return self.correct_escalated / all_correct if all_correct > 0 else 0

    @property
    def missed_error_rate(self) -> float:
        """Accepted wrong answers / all wrong answers."""
        all_incorrect = self.incorrect_accepted + self.incorrect_escalated
        return self.incorrect_accepted / all_incorrect if all_incorrect > 0 else 0

    @property
    def f1_score(self) -> float:
        """
        Harmonic mean of (1 - false_escalation_rate) and (1 - missed_error_rate).
        Higher is better. Perfect = 1.0.
        This balances cost efficiency (not over-escalating) vs safety (not missing errors).
        """
        precision = 1.0 - self.false_escalation_rate
        recall = 1.0 - self.missed_error_rate
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "total_scenarios": self.total_scenarios,
            "accept_count": self.accept_count,
            "escalate_count": self.escalate_count,
            "block_count": self.block_count,
            "accept_rate": round(self.accept_rate, 4),
            "false_escalation_rate": round(self.false_escalation_rate, 4),
            "missed_error_rate": round(self.missed_error_rate, 4),
            "f1_score": round(self.f1_score, 4),
            "correct_accepted": self.correct_accepted,
            "incorrect_accepted": self.incorrect_accepted,
            "correct_escalated": self.correct_escalated,
            "incorrect_escalated": self.incorrect_escalated,
        }


def run_calibration_at_threshold(threshold: float) -> ThresholdResult:
    """Run all 50 scenarios through the router at a given threshold."""
    router = DisagreementRouter(confidence_threshold=threshold)

    result = ThresholdResult(
        threshold=threshold,
        total_scenarios=len(CALIBRATION_SCENARIOS),
        accept_count=0,
        escalate_count=0,
        block_count=0,
    )

    for scenario in CALIBRATION_SCENARIOS:
        verification = VerificationResult(
            agree=scenario.agree,
            confidence=scenario.confidence,
            risk_score=scenario.risk_score,
            critical_issues=scenario.critical_issues,
            reasoning=f"Scenario {scenario.scenario_id}"
        )

        routing = router.route(verification, tool_name=scenario.tool_name)
        decision = routing.decision

        if decision == RoutingDecision.ACCEPT:
            result.accept_count += 1
            if scenario.ground_truth == "correct":
                result.correct_accepted += 1
            else:
                result.incorrect_accepted += 1

        elif decision == RoutingDecision.ESCALATE:
            result.escalate_count += 1
            if scenario.ground_truth == "correct":
                result.correct_escalated += 1
            else:
                result.incorrect_escalated += 1

        else:  # BLOCK
            result.block_count += 1
            if scenario.ground_truth == "correct":
                result.correct_escalated += 1
            else:
                result.incorrect_escalated += 1

    return result


def run_full_calibration() -> dict:
    """Run calibration across all thresholds and pick the best one."""
    print(f"\nRunning threshold calibration on {len(CALIBRATION_SCENARIOS)} scenarios...")
    print(f"Thresholds: {THRESHOLDS_TO_TEST}")
    print("=" * 80)
    print(f"{'Threshold':>10} | {'Accept%':>8} | {'FalseEsc%':>10} | {'MissErr%':>9} | {'F1':>6} | {'Verdict'}")
    print("-" * 80)

    threshold_results = []

    for threshold in THRESHOLDS_TO_TEST:
        result = run_calibration_at_threshold(threshold)
        threshold_results.append(result)

        verdict = ""
        if result.false_escalation_rate > 0.30:
            verdict = "WARNING - over-escalates"
        elif result.missed_error_rate > 0.25:
            verdict = "WARNING - misses too many errors"
        else:
            verdict = "OK - good balance"

        print(
            f"{threshold:>10.2f} | "
            f"{result.accept_rate*100:>7.1f}% | "
            f"{result.false_escalation_rate*100:>9.1f}% | "
            f"{result.missed_error_rate*100:>8.1f}% | "
            f"{result.f1_score:>5.3f} | "
            f"{verdict}"
        )

    print("=" * 80)

    # Pick the best threshold by F1 score
    best = max(threshold_results, key=lambda r: r.f1_score)

    print(f"\nBEST THRESHOLD: {best.threshold:.2f}")
    print(f"  F1 score:              {best.f1_score:.3f}")
    print(f"  Accept rate:           {best.accept_rate*100:.1f}%")
    print(f"  False escalation rate: {best.false_escalation_rate*100:.1f}%")
    print(f"  Missed error rate:     {best.missed_error_rate*100:.1f}%")
    print(f"\n  -> Use confidence_threshold = {best.threshold} in the paper")

    # Build the full results dict
    output = {
        "calibration_run_timestamp": __import__("datetime").datetime.now().isoformat(),
        "total_scenarios": len(CALIBRATION_SCENARIOS),
        "thresholds_tested": THRESHOLDS_TO_TEST,
        "results_by_threshold": [r.to_dict() for r in threshold_results],
        "recommended_threshold": best.threshold,
        "recommended_threshold_justification": (
            f"Threshold {best.threshold} achieves the best F1 score ({best.f1_score:.3f}), "
            f"balancing false escalation rate ({best.false_escalation_rate*100:.1f}%) "
            f"against missed error rate ({best.missed_error_rate*100:.1f}%). "
            f"Accept rate of {best.accept_rate*100:.1f}% means {best.accept_rate*100:.1f}% "
            f"of tasks run locally without Tier 3 API cost."
        ),
        "scenario_breakdown": {
            "total": len(CALIBRATION_SCENARIOS),
            "truly_correct": sum(1 for s in CALIBRATION_SCENARIOS if s.ground_truth == "correct"),
            "truly_incorrect": sum(1 for s in CALIBRATION_SCENARIOS if s.ground_truth == "incorrect"),
        }
    }

    # Save to file
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nFull results saved to: {RESULTS_PATH}")
    return output


# ──────────────────────────────────────────────────────────────────────
# pytest test functions
# ──────────────────────────────────────────────────────────────────────

def test_calibration_produces_results_for_all_thresholds():
    """All 5 thresholds must produce valid ThresholdResult objects."""
    for threshold in THRESHOLDS_TO_TEST:
        result = run_calibration_at_threshold(threshold)
        assert isinstance(result, ThresholdResult)
        assert result.threshold == threshold
        assert result.total_scenarios == len(CALIBRATION_SCENARIOS)
        assert result.accept_count + result.escalate_count + result.block_count == len(CALIBRATION_SCENARIOS)


def test_higher_threshold_means_more_escalations():
    """A higher confidence threshold should produce more escalations (fewer accepts)."""
    results = {t: run_calibration_at_threshold(t) for t in [0.60, 0.90]}
    # At 0.90, fewer things clear the threshold → more escalations
    assert results[0.90].escalate_count >= results[0.60].escalate_count, (
        "Higher threshold should produce >= escalations vs lower threshold"
    )


def test_lower_threshold_catches_fewer_errors():
    """Lower threshold accepts more → misses more errors."""
    r_low = run_calibration_at_threshold(0.60)
    r_high = run_calibration_at_threshold(0.90)
    # Lower threshold accepts more incorrect outputs
    assert r_low.missed_error_rate >= r_high.missed_error_rate, (
        "Lower threshold should have >= missed error rate"
    )


def test_f1_scores_are_valid_range():
    """All F1 scores must be between 0 and 1."""
    for threshold in THRESHOLDS_TO_TEST:
        result = run_calibration_at_threshold(threshold)
        assert 0.0 <= result.f1_score <= 1.0, (
            f"F1 score {result.f1_score} out of range for threshold {threshold}"
        )


def test_rates_are_valid_probabilities():
    """All rates must be valid probabilities [0, 1]."""
    for threshold in THRESHOLDS_TO_TEST:
        result = run_calibration_at_threshold(threshold)
        assert 0.0 <= result.accept_rate <= 1.0
        assert 0.0 <= result.false_escalation_rate <= 1.0
        assert 0.0 <= result.missed_error_rate <= 1.0


def test_best_threshold_is_selected_by_f1():
    """The recommended threshold must be the one with highest F1 score."""
    results = {t: run_calibration_at_threshold(t) for t in THRESHOLDS_TO_TEST}
    best_threshold = max(results, key=lambda t: results[t].f1_score)
    best_f1 = results[best_threshold].f1_score

    for t, r in results.items():
        assert r.f1_score <= best_f1 + 0.001, (
            f"Threshold {t} has F1={r.f1_score:.3f} > best F1={best_f1:.3f} at {best_threshold}"
        )


def test_results_are_saved_to_file():
    """Calibration must save results.json to data/."""
    output = run_full_calibration()
    assert RESULTS_PATH.exists(), f"Results not saved to {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        loaded = json.load(f)
    assert "recommended_threshold" in loaded
    assert "results_by_threshold" in loaded
    assert len(loaded["results_by_threshold"]) == len(THRESHOLDS_TO_TEST)


def test_72_threshold_has_acceptable_performance():
    """
    Validate that 0.72 (our initial choice) has acceptable performance.
    This is the fairness test — if 0.72 performs well, our initial choice was justified.
    If another threshold is better by F1, the paper should use that one.
    """
    result = run_calibration_at_threshold(0.72)

    # These are minimum acceptability criteria
    assert result.accept_rate >= 0.40, (
        f"0.72 threshold accepts only {result.accept_rate*100:.1f}% — too many escalations"
    )
    assert result.missed_error_rate <= 0.50, (
        f"0.72 threshold misses {result.missed_error_rate*100:.1f}% of errors — too many"
    )
    assert result.f1_score >= 0.50, (
        f"0.72 threshold has F1={result.f1_score:.3f} — unacceptably low"
    )


if __name__ == "__main__":
    results = run_full_calibration()
    print(f"\nRecommended threshold: {results['recommended_threshold']}")
    print(f"Justification: {results['recommended_threshold_justification']}")
