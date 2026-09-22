"""
tests/test_benchmark_statistics.py
HERMES Gate 19: Statistical & Percentile Calculation Test Suite.

Validates that:
- Linear percentile interpolation is mathematically exact.
- Mean, P50, P75, P90, P95, P99, Min, and Max are correctly computed.
- Sample sizes ($N$) are strictly tracked.
- Low sample warnings ($N < 20$) are emitted.
- Outliers are retained (tail amplification).
- Invalid samples (NaN, inf, negative numbers) are rejected/discarded.
"""

import math
import pytest
from benchmarks.statistics import calculate_percentiles


def test_percentiles_synthetic_standard_array():
    """Validates percentiles on known array [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]."""
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    res = calculate_percentiles(data, metric_name="test_seq")

    assert res["n"] == 10
    assert res["mean"] == 5.5
    assert res["min"] == 1.0
    assert res["max"] == 10.0
    assert res["p50"] == 5.5
    assert res["p75"] == 7.75
    assert res["p90"] == 9.1
    assert res["p95"] == 9.55
    assert res["p99"] == 9.91
    assert res["percentile_method"] == "linear_interpolation"
    assert "LOW_SAMPLE_WARNING" in res["sample_size_warning"]


def test_percentiles_single_sample():
    """Validates single element array (N=1)."""
    res = calculate_percentiles([42.0])
    assert res["n"] == 1
    assert res["mean"] == 42.0
    assert res["p50"] == 42.0
    assert res["p90"] == 42.0
    assert res["p99"] == 42.0
    assert res["sample_size_warning"] is not None


def test_percentiles_two_samples():
    """Validates two element array (N=2)."""
    res = calculate_percentiles([10.0, 20.0])
    assert res["n"] == 2
    assert res["mean"] == 15.0
    assert res["p50"] == 15.0
    assert res["min"] == 10.0
    assert res["max"] == 20.0


def test_percentiles_identical_values():
    """Validates array with repeated identical values."""
    res = calculate_percentiles([5.0] * 50)
    assert res["n"] == 50
    assert res["mean"] == 5.0
    assert res["p50"] == 5.0
    assert res["p95"] == 5.0
    assert res["p99"] == 5.0
    assert res["sample_size_warning"] is None


def test_percentiles_tail_outlier_retained():
    """Validates that large outliers are preserved and tail amplification is computed."""
    data = [10.0] * 95 + [100.0] * 5
    res = calculate_percentiles(data)
    assert res["n"] == 100
    assert res["p50"] == 10.0
    assert res["p95"] == 14.5
    assert res["p99"] == 100.0
    assert res["tail_amplification_p95_over_p50"] == 1.45
    assert res["max"] == 100.0


def test_percentiles_invalid_sample_rejection():
    """Validates handling of NaN, inf, and negative numbers."""
    data = [10.0, 20.0, float("nan"), float("inf"), -5.0, 30.0]
    res = calculate_percentiles(data)
    assert res["n"] == 3  # 10, 20, 30
    assert res["discarded_count"] == 3
    assert res["p50"] == 20.0


def test_percentiles_empty_dataset_raises():
    """Validates that empty list raises ValueError."""
    with pytest.raises(ValueError, match="Cannot calculate percentiles on empty dataset"):
        calculate_percentiles([])
