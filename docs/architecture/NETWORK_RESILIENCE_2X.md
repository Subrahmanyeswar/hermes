# NETWORK RESILIENCE 2.x — ZERO-SILENT-HANG HARDENING

## 1. Overview & Core Philosophy
In HERMES 2.x, the network is never treated as a transparent or reliable transport. Provider calls to local daemons (Ollama) or external APIs (NVIDIA NIM) can stall, drop packets, rate-limit, fail authentication, or freeze indefinitely without throwing explicit socket errors.

The Prompt 12 reliability architecture guarantees:
1. **Zero Silent Hangs**: Every network operation is strictly bounded by hierarchical monotonic deadlines. `timeout=None` is forbidden.
2. **Connection $\neq$ Generation**: An HTTP 200 response or established TCP socket does not constitute progress. Generation progress requires verified streaming deltas.
3. **Bounded Recovery**: Retries are deterministic, rate-limited with exponential backoff and jitter, and budget-contained.
4. **Tool Replay Safety**: Tool execution is idempotent and protected against replay when model generation streams retry or fail.
5. **No Provider Misattribution**: Failures from NVIDIA NIM are never attributed to Ollama, and vice-versa.

---

## 2. Canonical Request Lifecycle
```
REQUEST CREATED
     │
     ▼
 CONNECTING ──► HTTP_CONNECTED (TCP socket open, headers read)
     │                │
     ▼                ▼
 STREAMING  ◄── STREAM_ACTIVE (StreamWatchdog initialized)
     │
     ├─► REQUEST_FIRST_DELTA (TTFT recorded via monotonic clock)
     ├─► REQUEST_PROGRESS (Incremental tokens received)
     │
     ├─► STALLING (TTFT timeout or inter-delta idle timeout exceeded)
     │        │
     │        ▼
     │   DISCONNECTED ──► RECONNECTING ──► RECOVERED ──► STREAMING
     │        │                                │
     │        ▼                                ▼
     │   FALLBACK (Non-streaming)        FAILED (Budget exhausted)
     │        │
     ▼        ▼
 COMPLETED (Authoritative model response verified)
```

---

## 3. Hierarchical Deadlines
Deadlines follow strict monotonic containment:
$$\text{Mission Deadline} \ge \text{Turn Deadline} \ge \text{Logical Request Deadline} \ge \text{Attempt Timeout}$$

1. **Mission Deadline**: Upper bound on entire user goal execution.
2. **Turn Deadline**: Upper bound on a single turn of the agent loop.
3. **Logical Request Deadline**: Total budget allocated for a model decision across all retry and fallback attempts (default: 90s).
4. **Attempt Timeout**: Maximum duration permitted for an individual HTTP attempt (default: 45s).
5. **First-Delta Timeout**: Time allowed between connection established and first token delivery (default: 15s).
6. **Idle Stream Timeout**: Maximum gap permitted between consecutive streaming deltas (default: 15s).

If `remaining_budget < delay + min_attempt_budget`, retries abort immediately with `DEADLINE_EXCEEDED` rather than wasting system time.

---

## 4. Key Subsystems
- **StreamWatchdog (`core.network.watchdog`)**: Independent monotonic watchdog checking TTFT and inter-delta stall. Aborts frozen streams cleanly.
- **NetworkSupervisor (`core.network.supervisor`)**: Central coordinator orchestrating logical requests, physical attempts, health updates, event emissions, and replay safety.
- **ProviderHealthState (`core.network.health`)**: Circuit breaker maintaining per-provider states (`CLOSED`, `OPEN`, `HALF_OPEN`) with hysteresis and cooldown.
- **RetryPolicy (`core.network.retry`)**: Determines retryability, computes exponential backoff with jitter, and verifies remaining budget before retry.
- **Provider Adapters (`core.network.adapters`)**: Protocol translators for NVIDIA NIM, Ollama, and test mocks with exception normalization.
