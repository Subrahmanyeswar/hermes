"""
benchmarks/statistics.py
HERMES Gate 19: Centralized Statistical & Percentile Calculation Module.

Provides deterministic, reproducible distribution statistics (Mean, P50, P75, P90, P95, P99, Min, Max).
Uses linear percentile interpolation with strict input validation against NaN/inf/negatives.
"""

import math
from typing import Dict, Any, List, Optional, Sequence


def calculate_percentiles(
    values: Sequence[float],
    metric_name: str = "latency",
    allow_zero: bool = True
) -> Dict[str, Any]:
    """
    Computes distribution percentiles and summary statistics for a sequence of numbers.

    Parameters:
        values: Sequence of numeric samples.
        metric_name: Name of the metric for reporting and error context.
        allow_zero: Whether zero values are considered valid.

    Returns:
        Dict containing count (N), mean, min, max, p50, p75, p90, p95, p99, and metadata.
    """
    if not values:
        raise ValueError(f"Cannot calculate percentiles on empty dataset for metric '{metric_name}'")

    valid_samples: List[float] = []
    discarded_samples: List[Dict[str, Any]] = []

    for v in values:
        if v is None:
            discarded_samples.append({"value": None, "reason": "NULL_SAMPLE"})
            continue
        try:
            val = float(v)
        except (ValueError, TypeError):
            discarded_samples.append({"value": v, "reason": "NON_NUMERIC"})
            continue

        if math.isnan(val):
            discarded_samples.append({"value": "NaN", "reason": "NAN_VALUE"})
            continue
        if math.isinf(val):
            discarded_samples.append({"value": "Infinity", "reason": "INFINITE_VALUE"})
            continue
        if val < 0.0:
            discarded_samples.append({"value": val, "reason": "NEGATIVE_DURATION"})
            continue
        if val == 0.0 and not allow_zero:
            discarded_samples.append({"value": 0.0, "reason": "ZERO_DISALLOWED"})
            continue

        valid_samples.append(val)

    n = len(valid_samples)
    if n == 0:
        raise ValueError(
            f"Zero valid samples remaining for metric '{metric_name}' after discarding {len(discarded_samples)} invalid entries."
        )

    # Sort in ascending order for linear percentile calculation
    sorted_samples = sorted(valid_samples)

    def _percentile(p: float) -> float:
        """Standard linear interpolation percentile calculation."""
        if n == 1:
            return sorted_samples[0]
        # Rank index: 0.0 to (n - 1)
        rank = (p / 100.0) * (n - 1)
        lower_idx = int(math.floor(rank))
        upper_idx = int(math.ceil(rank))
        if lower_idx == upper_idx:
            return sorted_samples[lower_idx]
        fraction = rank - lower_idx
        return sorted_samples[lower_idx] + fraction * (sorted_samples[upper_idx] - sorted_samples[lower_idx])

    mean_val = sum(sorted_samples) / n
    min_val = sorted_samples[0]
    max_val = sorted_samples[-1]
    p50_val = _percentile(50.0)
    p75_val = _percentile(75.0)
    p90_val = _percentile(90.0)
    p95_val = _percentile(95.0)
    p99_val = _percentile(99.0)

    tail_amplification = round(p95_val / p50_val, 2) if p50_val > 0 else None

    result = {
        "metric_name": metric_name,
        "n": n,
        "mean": round(mean_val, 4),
        "min": round(min_val, 4),
        "max": round(max_val, 4),
        "p50": round(p50_val, 4),
        "p75": round(p75_val, 4),
        "p90": round(p90_val, 4),
        "p95": round(p95_val, 4),
        "p99": round(p99_val, 4),
        "tail_amplification_p95_over_p50": tail_amplification,
        "percentile_method": "linear_interpolation",
        "sample_size_warning": "LOW_SAMPLE_WARNING (N < 20)" if n < 20 else None,
        "discarded_count": len(discarded_samples),
        "discarded_samples": discarded_samples if discarded_samples else []
    }

    return result
