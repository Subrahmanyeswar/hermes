import os
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# THREE-PROVIDER PRODUCTION ARCHITECTURE
# Tier 1: Z.ai / BigModel (glm-4.7-flash) [STATUS: WAITING_FOR_VALID_CREDENTIALS]
# Tier 2: NVIDIA NIM (nvidia/nemotron-3.5-lightning-30b-a3b) [STATUS: OPERATIONAL]
# Tier 3: OpenRouter (cohere/north-mini-code:free) [STATUS: OPERATIONAL]
# ==============================================================================

TIER1_PROVIDER = os.getenv("TIER1_PROVIDER", "zai")
TIER1_MODEL = os.getenv("TIER1_MODEL", "glm-4.7-flash")
TIER1_BASE_URL = os.getenv("TIER1_BASE_URL", "https://api.z.ai/api/paas/v4")
TIER1_PROVIDER_STATUS = os.getenv("TIER1_PROVIDER_STATUS", "WAITING_FOR_VALID_CREDENTIALS")
ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")

TIER2_PROVIDER = os.getenv("TIER2_PROVIDER", "nvidia_nim")
TIER2_MODEL = os.getenv("TIER2_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
TIER2_BASE_URL = os.getenv("TIER2_BASE_URL", "https://integrate.api.nvidia.com/v1")
TIER2_PROVIDER_STATUS = os.getenv("TIER2_PROVIDER_STATUS", "OPERATIONAL")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")

TIER3_PROVIDER = os.getenv("TIER3_PROVIDER", "openrouter")
TIER3_MODEL = os.getenv("TIER3_MODEL", "cohere/north-mini-code:free")
TIER3_BASE_URL = os.getenv("TIER3_BASE_URL", "https://openrouter.ai/api/v1")
TIER3_PROVIDER_STATUS = os.getenv("TIER3_PROVIDER_STATUS", "OPERATIONAL")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

def validate_timeout_config(
    env_var_name: str = "MODEL_TIMEOUT_SECONDS",
    default_val: int = 360,
) -> int:
    """
    Validate and return the configured timeout from environment.
    Enforces strict positive integer semantics and clear, actionable configuration errors.
    """
    raw_val = os.getenv(env_var_name)
    if raw_val is None or raw_val.strip() == "":
        return default_val
    stripped = raw_val.strip()
    try:
        val = int(stripped)
    except (TypeError, ValueError) as err:
        raise ValueError(
            f"Configuration error: {env_var_name}='{raw_val}' must be a valid positive integer."
        ) from err
    if val <= 0:
        raise ValueError(
            f"Configuration error: {env_var_name}={val} must be a positive integer greater than 0."
        )
    return val


MODEL_STREAMING = os.getenv("MODEL_STREAMING", "true").lower() == "true"
MODEL_TIMEOUT_SECONDS = validate_timeout_config("MODEL_TIMEOUT_SECONDS", 90)
PROVIDER_CONNECT_TIMEOUT = float(os.getenv("PROVIDER_CONNECT_TIMEOUT", "2.0"))
HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "8.0"))
MODEL_FIRST_TOKEN_TIMEOUT = float(os.getenv("MODEL_FIRST_TOKEN_TIMEOUT", "30.0"))
MODEL_TOTAL_TIMEOUT = int(os.getenv("MODEL_TOTAL_TIMEOUT", "360"))
VERIFICATION_TIMEOUT = int(os.getenv("VERIFICATION_TIMEOUT", "30"))
ARBITRATION_TIMEOUT = int(os.getenv("ARBITRATION_TIMEOUT", "30"))
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

# Keep-Alive Policies
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

# Phase 4D Adaptive Routing & Circuit Breaker Configurations
CIRCUIT_BREAKER_ENABLED = os.getenv("CIRCUIT_BREAKER_ENABLED", "true").lower() == "true"
T1_CIRCUIT_BREAKER_FAILURES = int(os.getenv("T1_CIRCUIT_BREAKER_FAILURES", "3"))
T1_CIRCUIT_BREAKER_WINDOW = float(os.getenv("T1_CIRCUIT_BREAKER_WINDOW", "120.0"))
T1_PROBE_INTERVAL = float(os.getenv("T1_PROBE_INTERVAL", "15.0"))
T2_MAX_CONCURRENCY = int(os.getenv("T2_MAX_CONCURRENCY", "1"))

# Mission Logical Turn Budgets
DEFAULT_MISSION_MAX_TURNS = int(os.getenv("MISSION_MAX_TURNS", "40"))
WEBSITE_MISSION_MAX_TURNS = int(os.getenv("WEBSITE_MISSION_MAX_TURNS", "80"))
