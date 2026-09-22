# Table 1: HERMES Subsystem & Architecture Validation Summary

| Subsystem / Capability | Evaluation Protocol & Evidence | Sample Size (N) | Success Rate (%) | Status | Source Artifact |
|---|---|---:|---:|:---:|---|
| **Full Software Regression** | Comprehensive pytest execution across all subsystems | 945 tests | **100.0%** | `VERIFIED` | `gate22_regression_results.json` |
| **Core Unit Regression** | Surgical root-cause bugfix test suite | 96 tests | **100.0%** | `VERIFIED` | `FINAL_REPAIR_RESULTS.json` |
| **Tool Reliability & Parsing** | Adversarial malformed output stress testing | 90 tests | **100.0%** | `VERIFIED` | `gate_15_9_tool_reliability_results.json` |
| **Cancellation & Process Safety** | Termination lifecycle boundaries and leak tests | 58 tests | **100.0%** | `VERIFIED` | `gate13_cancellation_results.json` |
| **Sustained Load Execution** | Continuous end-to-end mission execution | 30 missions | **100.0%** | `VERIFIED` | `thermal_test_summary.json` |
| **Security Boundary Defense** | Path traversal, symlink escape & injection probes | 24 attacks | **100.0%** | `VERIFIED` | `gate_15_7_security_results.json` |
| **Adaptive Model Routing** | Multi-tier escalation policy calibration | 24 decisions | **100.0%** | `VERIFIED` | `gate12_routing_calibration_results.json` |
| **Workspace Indexing & State** | Repository mapping and incremental consistency | 15 benchmarks | **100.0%** | `VERIFIED` | `gate10_workspace_correctness_results.json` |
| **Live Multi-Tier E2E Missions** | Local LLM inference, physical disk mutation & tests | 4 missions | **100.0%** | `VERIFIED` | `REAL_E2E_REPAIR_REPORT.md` |

**Key takeaway**: HERMES demonstrates 100.0% deterministic verification across 1,286 aggregate test and mission evaluations spanning full regression, adversarial tool handling, process safety, workspace caching, and security boundaries.