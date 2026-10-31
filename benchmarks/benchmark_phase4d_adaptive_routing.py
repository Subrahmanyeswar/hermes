# benchmarks/benchmark_phase4d_adaptive_routing.py
"""
HERMES Phase 4D Benchmark:
Adaptive Routing Decision Overhead, Circuit Breaker Latency, and Avoided Timeout Accounting.
"""

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.runtime_identity import get_canonical_python_executable
canonical_py = get_canonical_python_executable()
assert sys.executable.lower() == canonical_py.lower(), f"Must run under canonical runtime: {canonical_py}"

from core.adaptive_routing import (
    AdaptiveRouter,
    ProviderHealthState,
    get_adaptive_router,
)


def run_benchmark():
    print("=" * 80)
    print("HERMES PHASE 4D — ADAPTIVE ROUTING & ZERO-WAIT FAILOVER BENCHMARK")
    print("=" * 80)

    router = get_adaptive_router()
    router.reset()
    results = {}

    # 1. Healthy T1 Decision Latency (500 samples)
    t_start = time.perf_counter()
    healthy_latencies = []
    for _ in range(500):
        t0 = time.perf_counter()
        dec = router.route_primary()
        healthy_latencies.append((time.perf_counter() - t0) * 1000.0)

    healthy_med = sorted(healthy_latencies)[len(healthy_latencies) // 2]
    healthy_p95 = sorted(healthy_latencies)[int(len(healthy_latencies) * 0.95)]
    print(f"1. Healthy T1 Routing Latency (500 runs): median={healthy_med:.4f}ms | p95={healthy_p95:.4f}ms (target <= 5.0ms)")
    results["healthy_routing_median_ms"] = healthy_med
    results["healthy_routing_p95_ms"] = healthy_p95
    assert healthy_p95 < 5.0, f"Healthy routing p95 exceeded 5.0ms: {healthy_p95}ms"

    # 2. Trip Circuit & Measure Open-Circuit Zero-Wait Failover Latency (500 samples)
    router.record_failure(tier=1, error=TimeoutError("upstream timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    bypass_latencies = []
    for _ in range(500):
        t0 = time.perf_counter()
        dec = router.route_primary()
        bypass_latencies.append((time.perf_counter() - t0) * 1000.0)
        assert dec.tier == 2
        assert dec.bypassed is True

    bypass_med = sorted(bypass_latencies)[len(bypass_latencies) // 2]
    bypass_p95 = sorted(bypass_latencies)[int(len(bypass_latencies) * 0.95)]
    print(f"2. Open-Circuit Zero-Wait Routing Latency (500 runs): median={bypass_med:.4f}ms | p95={bypass_p95:.4f}ms (target <= 10.0ms)")
    results["bypass_routing_median_ms"] = bypass_med
    results["bypass_routing_p95_ms"] = bypass_p95
    assert bypass_p95 < 10.0, f"Bypass routing p95 exceeded 10.0ms: {bypass_p95}ms"

    # 3. Avoided Timeout Accounting
    telem = router.telemetry
    print(f"3. Avoided Timeout Metrics: count={telem.avoided_timeout_count} | avoided_wait={telem.avoided_timeout_ms/1000.0:.1f}s")
    results["avoided_timeout_count"] = telem.avoided_timeout_count
    results["avoided_timeout_seconds"] = telem.avoided_timeout_ms / 1000.0

    # 4. Recovery Transition Latency
    t_rec0 = time.perf_counter()
    router.record_success(tier=1, latency=2.1)
    rec_lat = (time.perf_counter() - t_rec0) * 1000.0
    assert router.get_health(1).state == ProviderHealthState.HEALTHY
    print(f"4. T1 Recovery State Transition Latency: {rec_lat:.4f}ms")
    results["recovery_transition_ms"] = rec_lat

    print("-" * 80)
    print("BENCHMARK SUMMARY:")
    for k, v in results.items():
        print(f"  - {k}: {v:.4f}")
    print("=" * 80)
    return results


if __name__ == "__main__":
    run_benchmark()
