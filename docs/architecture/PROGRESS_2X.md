# Truthful Progress Engine 2.x

## Overview

In legacy agent systems, "progress" is often a synthetic counter (e.g. "Task 1/7") or an illusion inferred from recent tool calls. HERMES 2.x replaces this with a **Truthful Progress Model**:
- Progress is a **descriptive projection** derived from the state of requirements, acceptance checks, and verified evidence.
- Progress is never an independent authority that can override ground truth evidence.
- The UI observes progress; it does not dictate it.

## Semantic Progress Tracking

Rather than reporting raw tool execution counters, [`ProgressState`](file:///c:/Users/SUBBU/Downloads/hermes/core/runtime_state/models.py) reports semantic milestones:

```python
@dataclass
class ProgressState:
    last_meaningful_change: str = "Mission initialized"
    current_focus: Optional[str] = None
    next_action: str = "Review project requirements and select starting focus."
    known_failures: List[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    overall_status: str = "PENDING"
    verified_requirements_count: int = 0
    total_requirements_count: int = 0
    passing_checks_count: int = 0
    total_checks_count: int = 0
    overall_fraction: float = 0.0
    progress_fingerprint: str = ""
```

## Noise Filtering

Repetitive identical tool calls (e.g. repeated `fs.read` or `search.glob` without state change) are filtered out:
- Events without delta changes do not trigger `PROGRESS_UPDATED`.
- High-level progress projections only update when requirement states, check statuses, or file artifacts change.

## Deterministic Focus Selection & Oscillation Protection

The [`ProgressController`](file:///c:/Users/SUBBU/Downloads/hermes/core/planning/progress.py) deterministically computes the next requirement focus:
1. **Sticky Focus**: If the current focus is `IN_PROGRESS` and unblocked, stick with it to maintain cognitive continuity.
2. **Priority Ordering**: Ranks unblocked `READY` requirements by priority (`CRITICAL` > `HIGH` > `MEDIUM` > `LOW`).
3. **Dependency Gating**: Only considers requirements whose dependencies are satisfied.
4. **Oscillation Protection**: Tracks focus history; candidates visited multiple times without progressing accumulate an oscillation penalty, preventing rapid flip-flopping between unresolved requirements.

## Progress Fingerprinting & Turn-Based Stall Detection

The engine hashes the state of all requirements, checks, and failures into a compact SHA-256 fingerprint:
$$\text{fingerprint} = \text{SHA256}(\text{req\_statuses} \parallel \text{focus} \parallel \text{failures} \parallel \text{check\_counts})$$

- If the progress fingerprint remains unchanged for $\ge N$ consecutive turns (default threshold: 3 to 5 turns), `detect_stall()` triggers an `AGENT_STALL_DETECTED` event.
- Grounded recovery advice is delivered to the agent (e.g., "Active failure on requirement 'req.persistence'. Inspect error output and attempt alternative fix"), breaking infinite loops without requiring user intervention.
