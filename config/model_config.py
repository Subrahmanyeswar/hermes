import os
from dotenv import load_dotenv

load_dotenv()

TIER1_PROVIDER = os.getenv("TIER1_PROVIDER", "ollama")
TIER1_MODEL = os.getenv("TIER1_MODEL", "deepseek-r1:8b")

TIER2_PROVIDER = os.getenv("TIER2_PROVIDER", "ollama")
TIER2_MODEL = os.getenv("TIER2_MODEL", "qwen3:8b")

TIER3_PROVIDER = os.getenv("TIER3_PROVIDER", "openrouter")
TIER3_MODEL = os.getenv("TIER3_MODEL", "stealth/ox-alpha")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

MODEL_STREAMING = os.getenv("MODEL_STREAMING", "true").lower() == "true"
MODEL_TIMEOUT_SECONDS = int(os.getenv("MODEL_TIMEOUT_SECONDS", "180"))
MODEL_KEEP_ALIVE = os.getenv("MODEL_KEEP_ALIVE", "300s")
MEMORY_EXTRACTION_TIMEOUT_SECONDS = int(os.getenv("MEMORY_EXTRACTION_TIMEOUT_SECONDS", "60"))
MEMORY_QUEUE_MAX_SIZE = int(os.getenv("MEMORY_QUEUE_MAX_SIZE", "50"))
PROGRESSIVE_VERIFICATION_ENABLED = os.getenv("PROGRESSIVE_VERIFICATION_ENABLED", "true").lower() == "true"
ADAPTIVE_T1_BUDGET_ENABLED = os.getenv("ADAPTIVE_T1_BUDGET_ENABLED", "true").lower() == "true"
OPTIMIZED_MODEL_RESIDENCY_ENABLED = os.getenv("OPTIMIZED_MODEL_RESIDENCY_ENABLED", "true").lower() == "true"
ROBUST_TOOL_VALIDATION_ENABLED = os.getenv("ROBUST_TOOL_VALIDATION_ENABLED", "true").lower() == "true"
WORKSPACE_INTELLIGENCE_ENABLED = os.getenv("WORKSPACE_INTELLIGENCE_ENABLED", "true").lower() == "true"
CONTEXT_ENGINE_ENABLED = os.getenv("CONTEXT_ENGINE_ENABLED", "true").lower() == "true"
ADAPTIVE_EXECUTION_ENABLED = os.getenv("ADAPTIVE_EXECUTION_ENABLED", "true").lower() == "true"
KAIROS_DAG_ENABLED = os.getenv("KAIROS_DAG_ENABLED", "true").lower() == "true"
KAIROS_MAX_CONCURRENCY = int(os.getenv("KAIROS_MAX_CONCURRENCY", "4"))
INTELLIGENT_ROUTING_ENABLED = os.getenv("INTELLIGENT_ROUTING_ENABLED", "true").lower() == "true"
T2_CONFIDENCE_THRESHOLD = float(os.getenv("T2_CONFIDENCE_THRESHOLD", "0.70"))
HIGH_RISK_THRESHOLD = float(os.getenv("HIGH_RISK_THRESHOLD", "0.60"))
MISSION_COMPLETION_ENGINE_ENABLED = os.getenv("MISSION_COMPLETION_ENGINE_ENABLED", "true").lower() == "true"
MAX_MISSION_REPAIR_ATTEMPTS = int(os.getenv("MAX_MISSION_REPAIR_ATTEMPTS", "3"))
MAX_DYNAMIC_TASKS = int(os.getenv("MAX_DYNAMIC_TASKS", "5"))
PROGRESSIVE_VERIFIER_ENABLED = os.getenv("PROGRESSIVE_VERIFIER_ENABLED", "true").lower() == "true"
VERIFICATION_TIMEOUT_SECONDS = int(os.getenv("VERIFICATION_TIMEOUT_SECONDS", "30"))
EVENT_BUS_ENABLED = os.getenv("EVENT_BUS_ENABLED", "true").lower() == "true"
EVENT_BUS_BUFFER_SIZE = int(os.getenv("EVENT_BUS_BUFFER_SIZE", "1000"))

# Model Keep-Alive Policies (RTX 3050 6GB single-model residency)
T1_KEEP_ALIVE = os.getenv("T1_KEEP_ALIVE", "300s")
T2_KEEP_ALIVE = os.getenv("T2_KEEP_ALIVE", "60s")

# Tier 1 Task-Aware Reasoning & Generation Budgets (Tokens)
T1_BUDGET_L0 = int(os.getenv("T1_BUDGET_L0", "768"))
T1_BUDGET_L1 = int(os.getenv("T1_BUDGET_L1", "1536"))
T1_BUDGET_L2 = int(os.getenv("T1_BUDGET_L2", "2560"))
T1_BUDGET_L3 = int(os.getenv("T1_BUDGET_L3", "4096"))
T1_BUDGET_L4 = int(os.getenv("T1_BUDGET_L4", "8192"))

TIER1_PARAMS = {"temperature": 0.0, "top_p": 1.0, "max_tokens": 8192}
TIER2_PARAMS = {"temperature": 0.0, "top_p": 1.0, "max_tokens": 4096}
TIER3_PARAMS = {"temperature": 0.0, "top_p": 1.0, "max_tokens": 4096}

