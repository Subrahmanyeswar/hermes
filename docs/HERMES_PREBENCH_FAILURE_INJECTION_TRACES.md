# HERMES Pre-Benchmark Gate 15.2: Failure Injection Traces
=========================================================

**Date:** September 2, 2026  
**Status:** COMPLETE  

---

## Trace 1: T1 Failure -> Intelligent Routing Escalation to T2

```text
MISSION (Complex Subsystem Refactor)
│
├─ [01] TASK_STARTED (t1)
├─ [02] T1_INFERENCE_FAILED (Low confidence / provider timeout)
├─ [03] ROUTING_DECISION -> ESCALATE_T2
│   └─ reason: "Elevated risk or low confidence (<0.70); escalating to T2"
├─ [04] T2_INFERENCE_STARTED (Qwen3:8b)
├─ [05] T2_INFERENCE_COMPLETED
├─ [06] VERIFICATION_STARTED
├─ [07] VERIFICATION_COMPLETED (PASSED)
└─ [08] MISSION_COMPLETED
```

---

## Trace 2: Repeated Verification Failure -> Repair Budget Exhaustion

```text
MISSION (Defect Repair)
│
├─ [01] VERIFICATION_FAILED (AssertionError: calculate(2, 3) != 5)
├─ [02] REPAIR_STARTED (Attempt 1/3)
├─ [03] VERIFICATION_FAILED (AssertionError)
├─ [04] REPAIR_STARTED (Attempt 2/3)
├─ [05] VERIFICATION_FAILED (AssertionError)
├─ [06] REPAIR_STARTED (Attempt 3/3)
├─ [07] VERIFICATION_FAILED (AssertionError)
├─ [08] REPAIR_BLOCKED (Exceeded max_repairs=3)
└─ [09] MISSION_FAILED (Acceptance criteria unsatisfied)
```

---

## Trace 3: Crashing TUI Subscriber -> Backend Protected Execution

```text
MISSION (Active Task Execution)
│
├─ [01] TASK_STARTED (t1)
├─ [02] EVENT_PUBLISH (TASK_STARTED)
│   ├─ Subscriber 1 (TUI Formatter): Throws ZeroDivisionError
│   ├─ EventBus Log: [WARNING] Subscriber threw exception: division by zero
│   └─ Subscriber 2 (State Store): Applied event successfully
├─ [03] TOOL_COMPLETED (write_file)
├─ [04] VERIFICATION_COMPLETED (PASSED)
└─ [05] MISSION_COMPLETED (Backend unharmed by UI crash)
```
