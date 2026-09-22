import json
from pathlib import Path

# Load Prompt 1 State
p1_state_path = Path("artifacts/performance/PROMPT_1_STATE.json")
p1_state = {}
if p1_state_path.exists():
    with open(p1_state_path, "r", encoding="utf-8") as f:
        p1_state = json.load(f)

# Load Golden Analysis from Prompt 2
p2_analysis_path = Path("artifacts/performance/golden/golden_analysis.json")
p2_analysis = {}
if p2_analysis_path.exists():
    with open(p2_analysis_path, "r", encoding="utf-8") as f:
        p2_analysis = json.load(f)

# Load Reasoning Experiments from Prompt 2
reasoning_path = Path("artifacts/performance/reasoning_budget_experiments.json")
reasoning_exp = {}
if reasoning_path.exists():
    with open(reasoning_path, "r", encoding="utf-8") as f:
        reasoning_exp = json.load(f)

# Load Switch & Residency Data from Prompt 2
switch_path = Path("artifacts/performance/switch_and_residency_data.json")
switch_data = {}
if switch_path.exists():
    with open(switch_path, "r", encoding="utf-8") as f:
        switch_data = json.load(f)

# Load Golden Run 01 from Prompt 2
golden_run_path = Path("artifacts/performance/golden/golden_run_01.json")
golden_run = {}
if golden_run_path.exists():
    with open(golden_run_path, "r", encoding="utf-8") as f:
        golden_run = json.load(f)

prechange_state = {
    "program": "HERMES Performance Optimization Program",
    "prompt_phase": "PROMPT 3 OF 8",
    "status": "PRECHANGE_ESTABLISHED",
    "prompt_1_baseline": {
        "mission_id": "golden_performance_probe_01",
        "total_wall_latency_seconds": 62.73,
        "t1_generation_seconds": 51.82,
        "t1_generation_share_percent": 82.61,
        "t1_load_seconds": 8.71,
        "prompt_eval_seconds": 1.24,
        "orchestration_overhead_seconds": 0.17,
        "tool_execution_seconds": 0.0,
        "verification_seconds": 0.0,
        "output_tokens": 1536,
        "tokens_per_second": 29.64,
        "thinking_characters": 6532,
        "direct_response_characters": 0
    },
    "prompt_2_golden_mission": {
        "mission_name": "EduPath Mini Career Guidance Webpage",
        "planning_latency_seconds": 133.97,
        "rule_enforced": "Rule 9: Minimum 8 tasks. Maximum 25 tasks",
        "tasks_planned": 13,
        "tasks_completed": 0,
        "task_1_complexity_assigned": "L4_VERY_COMPLEX (score=0.90)",
        "task_1_budget_assigned": {
            "num_predict": 8192,
            "timeout_seconds": 240
        },
        "task_1_attempt_1_outcome": "OllamaTimeoutError (240s exhausted in continuous reasoning)",
        "task_1_attempt_2_outcome": "Aborted due to deterministic runaway reasoning",
        "total_measured_run_seconds": 411.25,
        "primary_failure_mechanism": "Unconstrained DeepSeek-R1 reasoning runaway leading to 240s timeout and retry churn"
    },
    "controlled_reasoning_probe_results": {
        "think_true_config_a_1536": {
            "wall_seconds": 53.36,
            "eval_tokens": 1536,
            "tokens_per_second": 29.73,
            "thinking_closed": False,
            "direct_parse_success": False
        },
        "think_true_config_b_512": {
            "wall_seconds": 17.30,
            "eval_tokens": 512,
            "tokens_per_second": 30.14,
            "thinking_closed": False,
            "direct_parse_success": False
        },
        "think_true_config_c_1024": {
            "wall_seconds": 34.64,
            "eval_tokens": 1024,
            "tokens_per_second": 29.92,
            "thinking_closed": False,
            "direct_parse_success": False
        },
        "think_false_diagnostic": {
            "wall_seconds": 4.50,
            "eval_tokens": 129,
            "tokens_per_second": 30.44,
            "thinking_closed": True,
            "direct_parse_success": True,
            "extracted_tool": "write_file",
            "latency_reduction_percent": 91.57,
            "token_reduction_percent": 91.60
        }
    },
    "model_switching_and_residency": {
        "hardware": "NVIDIA GeForce RTX 3050 Laptop GPU (6144 MiB VRAM)",
        "unloaded_vram_mb": 0.0,
        "t1_resident_vram_mb": 5495.0,
        "t2_resident_vram_mb": 5495.0,
        "dual_residency_possible": False,
        "cold_t1_load_seconds": 8.63,
        "warm_t1_load_seconds": 0.18,
        "t1_to_t2_switch_load_seconds": 8.64,
        "warm_t2_load_seconds": 0.16,
        "t2_to_t1_switch_load_seconds": 8.53,
        "round_trip_switch_penalty_seconds": 17.17
    },
    "runtime_configuration": {
        "t1_model": "deepseek-r1:8b",
        "t2_model": "qwen3:8b",
        "t3_model": "stealth/ox-alpha",
        "keep_alive": "300s",
        "num_ctx": 4096,
        "default_budget_level": "L1_SIMPLE (num_predict=1536)",
        "max_budget_level": "L4_VERY_COMPLEX (num_predict=8192)"
    }
}

out1 = Path("artifacts/performance/PROMPT_3_PRECHANGE_STATE.json")
with open(out1, "w", encoding="utf-8") as f:
    json.dump(prechange_state, f, indent=2)

p3_dir = Path("artifacts/performance/prompt3")
p3_dir.mkdir(parents=True, exist_ok=True)
out2 = p3_dir / "prechange_state.json"
with open(out2, "w", encoding="utf-8") as f:
    json.dump(prechange_state, f, indent=2)

print(f"Created {out1} and {out2}")
