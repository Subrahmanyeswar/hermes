# HERMES 2.x — Subagent Handoff & Observation Architecture (AGENT_HANDOFF.md)

## 1. Architectural Purpose
When a child subagent completes its task, returning its entire raw conversation transcript or full tool output to the primary agent would cause massive context bloat and token degradation.

HERMES 2.x introduces the **Bounded Handoff Protocol**, ensuring the parent receives concise, high-signal observations and evidence links while full artifacts are stored externally.

---

## 2. Fundamental Invariant
> **Subagent SUCCESS $\neq$ Requirement VERIFIED $\neq$ Goal COMPLETE**  
> 
> A subagent is an untrusted worker that provides evidence. Even if a subagent reports `SUCCEEDED`, the primary agent and the authoritative State Store must independently evaluate the returned evidence against the Goal's Acceptance Ledger before any requirement can be marked `VERIFIED`.

---

## 3. SubagentResult Schema
The child produces a typed `SubagentResult`:
```python
@dataclass
class SubagentResult:
    status: SubagentStatus              # SUCCEEDED, FAILED, TIMED_OUT, etc.
    task_id: str
    agent_id: str
    summary: str                        # Concise 1-2 sentence overview
    findings: List[str]                 # High-signal bullet points
    files: List[str]                    # List of touched/read files
    changes: List[Dict[str, Any]]       # Patches or change summaries
    evidence_refs: List[str]            # IDs of verified evidence items
    artifact_refs: List[str]            # File paths to externalized artifacts
    tests: Dict[str, Any]               # Test execution results
    errors: List[str]                   # Any non-fatal or fatal errors
    next_recommendation: Optional[str]  # Recommended next step for primary agent
    duration: float                     # Execution runtime in seconds
    resource_usage: Dict[str, Any]      # Turns, tool calls, and tokens used
```

---

## 4. Observation Formatting & Boundedness
The `HandoffManager` formats the `SubagentResult` into the canonical `Observation` structure consumed by `AgentLoop`:

1. **Structured Markdown**:
   - `### SUBAGENT EXECUTION REPORT: [SUCCEEDED]`
   - Summary, Key Findings, Modified Files, Test Results, Evidence References, Recommendations.
2. **Context Boundedness**:
   - Max output limit: 50,000 bytes (configurable).
   - If payload exceeds the limit, the full result is serialized to `.hermes/artifacts/subagent_{agent_id}_result.json`.
   - The returned observation content includes a preview and a clickable reference link to the externalized artifact.

---

## 5. Flow Diagram
```
CHILD SUBAGENT FINISHES
       │
       ▼
SubagentResult (summary, findings, files, tests, errors)
       │
       ▼
HandoffManager.format_observation()
 ├── Under 50KB? ──> Bounded Markdown Observation
 └── Over 50KB?  ──> Dump to .hermes/artifacts/*.json + Bounded Preview
       │
       ▼
Parent AgentLoop Observation Turn
       │
       ▼
Primary Agent reviews evidence and decides next action
```
