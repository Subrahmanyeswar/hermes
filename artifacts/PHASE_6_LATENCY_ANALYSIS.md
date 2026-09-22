# HERMES — PHASE 6 LATENCY & THROUGHPUT DISTRIBUTION
**Run ID**: `final_benchmark_20260905_140302`  

## 1. Percentile Distribution Table

| Measurement Scope | Sample Count (N) | Minimum | Maximum | Mean | P50 (Median) | P75 | P90 | P95 | P99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **End-to-End Task Duration** | 80 | 50.6132s | 8569.4322s | 337.8488s | **211.8828s** | 309.7876s | 372.3838s | **397.3817s** | **2176.5844s** |
| **Model Generation Duration** | 75 | 4.804s | 174.907s | 54.4585s | **50.445s** | 82.171s | 95.504s | **142.8022s** | **154.7413s** |

## 2. Distribution Properties
- **Monotonicity**: Direct wall-clock monotonic tracking verified across all 80 tasks.
- **Outlier Retention**: Zero artificial smoothing or outlier filtering.
