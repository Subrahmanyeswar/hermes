# HERMES Research Evidence Directory

This directory contains the canonical, verified, and defensible research evidence compiled for the academic publication of the HERMES agent architecture.

## Directory Structure

```text
artifacts/research_evidence/
├── README.md                              # Guide to evidence provenance and usage
├── evidence_inventory.json                # Complete audit and classification of all project datasets
├── excluded_results.md                    # Explicit scientific rationale for excluding invalid runs
├── final_research_metrics.json            # Machine-readable key-value database of paper-safe metrics
├── figure_sources.json                    # Exact raw values and data sources for generated figures
├── PAPER_DATA_SUMMARY.md                  # Executive data summary formatted for paper writing
├── table_1_system_validation.csv          # Table 1: Subsystem validation matrix (CSV)
├── table_1_system_validation.md           # Table 1: Subsystem validation matrix (Markdown)
├── table_2_runtime_metrics.csv            # Table 2: Measured runtime & hardware metrics (CSV)
├── table_2_runtime_metrics.md             # Table 2: Measured runtime & hardware metrics (Markdown)
└── figures/
    ├── figure_1_system_validation.png     # Figure 1: Subsystem validation rates (300 DPI)
    └── figure_2_runtime_performance.png   # Figure 2: Latency percentiles & thermals (300 DPI)
```

## Evidence Principles

1. **Strict Provenance**: Every plotted bar, table row, and quoted statistic maps to a specific JSON or Markdown artifact generated during verified system certification.
2. **Zero Fabrication**: No estimates or synthetic placeholders are used. Where metrics were not captured under valid protocols, they are designated `NOT_AVAILABLE`.
3. **Exclusion of Contaminated Baselines**: Historical runs affected by known model ingestion defects (such as the 1/80 = 1.25% run) are explicitly quarantined to the problem statement / engineering section and excluded from system capability metrics.
