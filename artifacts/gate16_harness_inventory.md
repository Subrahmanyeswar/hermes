# HERMES — BENCHMARK HARNESS & METRIC INVENTORY
## Gate 16 Measurement Boundary & Clock Inventory

**Generated**: September 3, 2026  
**Status**: **COMPLETE & VERIFIED**  

| Metric Name | Producer | Start Boundary | End Boundary | Clock Used | Unit | Scope | Double-Counting Risk |
|---|---|---|---|---|---|---|---|
| **E2E Wall Clock Mission Latency** | `time.perf_counter()` | `User request arrival / Mission execution start` | `Mission terminal state committed in ExecutionStateStore` | `time.perf_counter() (Monotonic)` | `seconds` | `END_TO_END` | None (Measured directly across global mission lifecycle) |
| **Model Time to First Token (TTFT)** | `Streaming token generator timestamp` | `HTTP request sent to provider` | `First token chunk yielded by stream` | `time.monotonic()` | `seconds` | `MODEL_LEVEL` | None (Explicitly distinguished from generation duration) |
| **Model Generation Latency** | `Streaming token loop` | `First token yielded` | `Final token chunk received` | `time.monotonic()` | `seconds` | `MODEL_LEVEL` | None |
| **Generation Throughput (tok/s)** | `completion_tokens / generation_duration_s` | `First token yielded` | `Final token yielded` | `time.monotonic()` | `tokens/second` | `MODEL_LEVEL` | None (Divided strictly by generation latency, not E2E) |
| **Component Latencies (Workspace, Context, Tools, Verifier, Repair)** | `time.perf_counter() around component entry/exit` | `Component method start` | `Component method return` | `time.perf_counter()` | `seconds` | `COMPONENT_LEVEL` | None (Recorded independently, not summed into E2E) |
| **VRAM Consumption** | `Process memory sampling` | `Pre-generation baseline` | `Post-generation residency` | `Wall Clock / Polling` | `Megabytes (MB)` | `SYSTEM_RESOURCE` | None |
| **Cloud Cost Accounting** | `Provider reported usage JSON` | `Request initiation` | `Response completion` | `Provider Clock` | `USD ($)` | `CLOUD_COST` | None (Explicitly labeled NOT_AVAILABLE if auth-blocked) |
