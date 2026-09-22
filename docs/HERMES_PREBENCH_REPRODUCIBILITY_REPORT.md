# HERMES Pre-Benchmark Gate 15.4: Reproducibility Report
=======================================================

**Date:** September 2, 2026  
**Freeze Status:** **LOCKED & VERIFIED**  

---

## 1. Deterministic Hashes & Fingerprints

- **Source Worktree SHA-256:** `67659e5d336f79398000f8f0f958597268a439673be2263d299419398e1b9a21`
- **Benchmark Manifest SHA-256:** `4e78f99ad5c60205b380f2dcf35a9681329c2cf9b2223bb3511ebf6ec9a6c434`
- **Tier 1 (DeepSeek-R1:8b) Ollama Digest:** `6995872bfe4c521a67b32da386cd21d5c6e819b6e0d62f79f64ec83be99f5763`
- **Tier 2 (Qwen3:8b) Ollama Digest:** `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`

---

## 2. Instructions to Reproduce & Validate Freeze

1. **Verify Environment:**  
   `python scripts/validate_benchmark_freeze.py`
2. **Execute Full Test Suite:**  
   `pytest tests/ -v`
3. **Execute Benchmark Dry-Run:**  
   `python benchmarks/gate15_4_dry_run.py`
