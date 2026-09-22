# HERMES — TIMEOUT & DEADLINE INVENTORY
## Gate 14 Comprehensive Production Timeout Inventory

**Generated**: September 3, 2026  
**Status**: **COMPLETE & VERIFIED**  

| Component | File | Constant / Config Key | Default Value | Scope | Parent Scope | Child Scope | Type | Expiry Action |
|---|---|---|---|---|---|---|---|---|
| **MissionRunner** | `core/mission_runner.py` | `DEFAULT_MISSION_TIMEOUT` | 1800 seconds | `MISSION` | `USER` | `KAIROS, TASK` | Hard | CancellationController.cancel_mission() |
| **ReasoningBudgetManager (L0_DIRECT)** | `core/reasoning_budget.py` | `T1_BUDGET_L0 / timeout` | 45 seconds | `MODEL_T1` | `TASK` | `NONE` | Hard | ErrorHandler.ollama_timeout -> tag [TIMEOUT] |
| **ReasoningBudgetManager (L1_SIMPLE)** | `core/reasoning_budget.py` | `T1_BUDGET_L1 / timeout` | 75 seconds | `MODEL_T1` | `TASK` | `NONE` | Hard | ErrorHandler.ollama_timeout |
| **ReasoningBudgetManager (L2_NORMAL)** | `core/reasoning_budget.py` | `T1_BUDGET_L2 / timeout` | 120 seconds | `MODEL_T1` | `TASK` | `NONE` | Hard | ErrorHandler.ollama_timeout |
| **ReasoningBudgetManager (L3_COMPLEX)** | `core/reasoning_budget.py` | `T1_BUDGET_L3 / timeout` | 180 seconds | `MODEL_T1` | `TASK` | `NONE` | Hard | ErrorHandler.ollama_timeout |
| **ReasoningBudgetManager (L4_VERY_COMPLEX)** | `core/reasoning_budget.py` | `T1_BUDGET_L4 / timeout` | 240 seconds | `MODEL_T1` | `TASK` | `NONE` | Hard | ErrorHandler.ollama_timeout |
| **OllamaClient (T1/T2 Default)** | `models/ollama_client.py` | `MODEL_TIMEOUT_SECONDS` | 180 seconds | `MODEL_PROVIDER` | `TASK` | `HTTPX` | Hard | Raise OllamaTimeoutError -> ErrorHandler |
| **OpenRouterClient (T3)** | `models/openrouter_client.py` | `MODEL_TIMEOUT_SECONDS` | 180 seconds | `MODEL_PROVIDER` | `TASK` | `HTTPX` | Hard | Raise OpenRouterTimeout -> Fallback/Tag |
| **BashExecTool** | `tools/shell_tools.py` | `inp.timeout_seconds` | 30 seconds | `TOOL` | `TASK` | `SUBPROCESS` | Hard | subprocess.TimeoutExpired -> terminate -> return ToolResult(exit_code=124) |
| **RunTestsTool** | `tools/shell_tools.py` | `inp.timeout_seconds` | 60 seconds | `TOOL` | `TASK` | `SUBPROCESS` | Hard | subprocess.TimeoutExpired -> terminate -> return ToolResult(exit_code=124) |
| **GitCommandTool** | `tools/shell_tools.py` | `inp.timeout_seconds` | 120 seconds | `TOOL` | `TASK` | `SUBPROCESS` | Hard | subprocess.TimeoutExpired -> terminate |
| **Subprocess Termination Watchdog** | `tools/shell_tools.py` | `terminate_active_subprocesses wait` | 1.5 seconds | `PROCESS_CLEANUP` | `CANCELLATION` | `OS_PROCESS` | Hard | proc.kill() |
| **ProgressiveVerificationEngine** | `core/progressive_verifier.py` | `VERIFICATION_TIMEOUT_SECONDS` | 30 seconds | `VERIFICATION` | `TASK` | `AST / TESTS` | Hard | VerificationResult(status='FAILED', failure_class='ENVIRONMENT_FAILURE') |
| **StructuredFeedbackGenerator** | `core/structured_feedback.py` | `timeout_seconds` | 15 seconds | `QUALITY_FEEDBACK` | `TASK` | `AST` | Hard | Return unverified feedback |
| **BackgroundMemoryManager** | `memory/background_worker.py` | `MEMORY_EXTRACTION_TIMEOUT_SECONDS` | 60 seconds | `BACKGROUND_WORKER` | `MISSION` | `ASYNC_TASK` | Hard | Drop unextracted memory job |
