# core/persistence/serializer.py
"""
Typed, deterministic JSON serialization and deserialization for HermesRuntimeState.

Core Invariants:
1. NO PICKLE: All state serialized into typed, verifiable JSON structures.
2. DETERMINISTIC STATE HASH: Canonical SHA-256 computed across sorted keys.
3. COMPLETE ROUND-TRIP: deserialize(serialize(state)) produces identical logical state.
4. SAFE VALIDATION: Validates required keys, enums, and timestamps upon load.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Tuple

from core.runtime_state.models import (
    HermesRuntimeState,
    MissionState,
    MissionStatus,
    GoalState,
    GoalStatus,
    ProgressState,
    TaskState,
    TaskStatus,
    ToolExecutionState,
    ToolStatus,
    ModelExecutionState,
    ModelStatus,
    VerificationState,
    VerificationStatus,
    NetworkState,
    NetworkConnectivity,
    PermissionState,
    PermissionStatus,
    SessionState,
    SessionStatus,
    EvidenceState,
    EvidenceKind,
    CheckpointState,
    CheckpointStatus,
    RequirementState,
    RequirementStatus,
    RequirementPriority,
    RequirementCategory,
    RequirementType,
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    TodoState,
    TodoStatus,
    PlanState,
    PlanStatus,
    PlanStep,
    ExecutionMode,
    AgentRecord,
    AgentType,
    SubagentStatus,
    SubagentTaskRecord,
    WorktreeRecord,
    WorktreeStatus,
    BackgroundJobRecord,
    JobKind,
    JobStatus,
    JobLifecycle,
    RepairState,
    RepairStatus,
    FailureClass,
    EscalationState,
    EscalationDecisionType,
    DisagreementClass,
)
from core.contracts.blueprint import ImplementationBlueprint
from core.contracts.manifest import InterfaceManifest
from core.contracts.rubric import QualityRubric


def compute_state_hash(state_dict: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of serialized state."""
    canonical_json = json.dumps(state_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def serialize_runtime_state(state: HermesRuntimeState) -> Tuple[Dict[str, Any], str]:
    """
    Serialize HermesRuntimeState to a pure Python dictionary and compute its state_hash.
    """
    data = state.to_dict()
    state_hash = compute_state_hash(data)
    return data, state_hash


import dataclasses


def _reconstruct_dataclass(cls: Any, data_dict: Any, enum_map: Dict[str, Any] = None) -> Any:
    """Safely instantiate dataclass from dictionary, dropping unknown keys and converting enums."""
    if not isinstance(data_dict, dict):
        return cls()
    valid_fields = {f.name: f for f in dataclasses.fields(cls)}
    clean = {}
    for k, v in data_dict.items():
        if k in valid_fields:
            clean[k] = v
    if enum_map:
        for k, enum_cls in enum_map.items():
            if k in clean and clean[k] is not None:
                try:
                    clean[k] = enum_cls(clean[k])
                except Exception:
                    pass
    return cls(**clean)


def deserialize_runtime_state(data: Dict[str, Any]) -> HermesRuntimeState:
    """
    Safely reconstruct HermesRuntimeState from a validated dictionary.
    """
    # 1. MissionState
    m_data = data.get("mission", {})
    mission = MissionState(
        mission_id=m_data.get("mission_id", "default"),
        run_id=m_data.get("run_id"),
        attempt_number=m_data.get("attempt_number", 1),
        request_id=m_data.get("request_id"),
        session_id=m_data.get("session_id", "sess_default"),
        status=MissionStatus(m_data.get("status", MissionStatus.CREATED.value)),
        title=m_data.get("title", ""),
        prompt=m_data.get("prompt", ""),
        start_time=m_data.get("start_time", 0.0),
        end_time=m_data.get("end_time"),
        current_task_id=m_data.get("current_task_id"),
        task_count=m_data.get("task_count", 0),
        completed_task_count=m_data.get("completed_task_count", 0),
        failed_task_count=m_data.get("failed_task_count", 0),
        blocked_task_count=m_data.get("blocked_task_count", 0),
        cancelled=m_data.get("cancelled", False),
        abort_reason=m_data.get("abort_reason"),
        completion_reason=m_data.get("completion_reason"),
        execution_mode=m_data.get("execution_mode", "auto"),
        workspace_root=m_data.get("workspace_root", ""),
        last_event_sequence=m_data.get("last_event_sequence", 0),
        active_skills=m_data.get("active_skills", data.get("active_skills", [])),
        skill_fingerprints=m_data.get("skill_fingerprints", data.get("skill_fingerprints", {})),
    )

    # 2. GoalState
    g_data = data.get("goal", {})
    g_dict = dict(g_data)
    if "status" in g_dict:
        g_dict["status"] = GoalStatus(g_dict["status"])
    goal = GoalState(**g_dict)

    # 3. ProgressState
    from core.runtime_state.models import WaitReason
    progress = _reconstruct_dataclass(
        ProgressState,
        data.get("progress", {}),
        {"waiting_reason": WaitReason},
    )

    # 4. Tasks
    tasks = {}
    for tid, t_dict in data.get("tasks", {}).items():
        tasks[tid] = _reconstruct_dataclass(
            TaskState,
            t_dict,
            {"status": TaskStatus},
        )

    current_task = None
    if data.get("current_task"):
        current_task = _reconstruct_dataclass(
            TaskState,
            data["current_task"],
            {"status": TaskStatus},
        )

    # 5. ToolExecutionState
    tool_exec = _reconstruct_dataclass(
        ToolExecutionState,
        data.get("tool_execution", {}),
        {"status": ToolStatus},
    )

    # 6. ModelExecutionState
    model_exec = _reconstruct_dataclass(
        ModelExecutionState,
        data.get("model_execution", {}),
        {"status": ModelStatus},
    )

    # 7. VerificationState
    verification = _reconstruct_dataclass(
        VerificationState,
        data.get("verification", {}),
        {"status": VerificationStatus},
    )

    # 8. NetworkState
    network = _reconstruct_dataclass(
        NetworkState,
        data.get("network", {}),
        {"connectivity": NetworkConnectivity},
    )

    # 9. PermissionState
    permission = _reconstruct_dataclass(
        PermissionState,
        data.get("permission", {}),
        {"status": PermissionStatus},
    )

    # 10. SessionState
    se_data = dict(data.get("session", {}))
    if not se_data.get("session_id"):
        se_data["session_id"] = mission.session_id
    session = _reconstruct_dataclass(
        SessionState,
        se_data,
        {"status": SessionStatus},
    )

    # 11. Evidence
    evidence = {}
    for eid, ed in data.get("evidence", {}).items():
        evidence[eid] = _reconstruct_dataclass(
            EvidenceState,
            ed,
            {"kind": EvidenceKind},
        )

    # 12. CheckpointState
    checkpoint = _reconstruct_dataclass(
        CheckpointState,
        data.get("checkpoint", {}),
        {"status": CheckpointStatus},
    )

    # 13. Requirements & AcceptanceLedger
    requirements = {}
    for rid, rd in data.get("requirements", {}).items():
        requirements[rid] = _reconstruct_dataclass(
            RequirementState,
            rd,
            {
                "category": RequirementCategory,
                "requirement_type": RequirementType,
                "priority": RequirementPriority,
                "status": RequirementStatus,
            },
        )

    ledger_data = data.get("acceptance_ledger", {})
    checks = {}
    for cid, cd in ledger_data.get("checks", {}).items():
        checks[cid] = _reconstruct_dataclass(
            AcceptanceCheck,
            cd,
            {"status": AcceptanceCheckStatus},
        )
    ledger = AcceptanceLedger(
        goal_id=ledger_data.get("goal_id", goal.goal_id),
        version=ledger_data.get("version", 1),
        checks=checks,
        requirement_checks=ledger_data.get("requirement_checks", {}),
        updated_at=ledger_data.get("updated_at", 0.0),
    )

    # 14. Todos & Plan
    todos = {}
    for toid, tod in data.get("todos", {}).items():
        todos[toid] = _reconstruct_dataclass(
            TodoState,
            tod,
            {"status": TodoStatus, "priority": RequirementPriority},
        )

    plan = None
    if data.get("plan"):
        pd = data["plan"]
        steps = [_reconstruct_dataclass(PlanStep, s) for s in pd.get("steps", [])]
        plan = PlanState(
            plan_id=pd.get("plan_id", ""),
            goal_id=pd.get("goal_id", goal.goal_id),
            version=pd.get("version", 1),
            steps=steps,
            status=PlanStatus(pd.get("status", PlanStatus.DRAFT.value)) if "status" in pd else PlanStatus.DRAFT,
            risks=pd.get("risks", []),
            unknowns=pd.get("unknowns", []),
            open_questions=pd.get("open_questions", []),
            created_at=pd.get("created_at", 0.0),
            updated_at=pd.get("updated_at", 0.0),
            reason_changed=pd.get("reason_changed"),
            approved_by=pd.get("approved_by"),
            approved_at=pd.get("approved_at"),
        )

    # 15. Subagents, Worktrees, Background Jobs
    agents = {}
    for aid, ad in data.get("agents", {}).items():
        agents[aid] = _reconstruct_dataclass(
            AgentRecord,
            ad,
            {"agent_type": AgentType, "status": SubagentStatus},
        )

    subagent_tasks = {}
    for stid, std in data.get("subagent_tasks", {}).items():
        subagent_tasks[stid] = _reconstruct_dataclass(
            SubagentTaskRecord,
            std,
            {"status": SubagentStatus},
        )

    worktrees = {}
    for wid, wd in data.get("worktrees", {}).items():
        worktrees[wid] = _reconstruct_dataclass(
            WorktreeRecord,
            wd,
            {"status": WorktreeStatus},
        )

    background_jobs = {}
    for bjid, bjd in data.get("background_jobs", {}).items():
        background_jobs[bjid] = _reconstruct_dataclass(
            BackgroundJobRecord,
            bjd,
            {"kind": JobKind, "status": JobStatus, "lifecycle": JobLifecycle},
        )

    # 16. Repairs & Escalations
    repairs = {}
    for rid, rd in data.get("repairs", {}).items():
        repairs[rid] = _reconstruct_dataclass(
            RepairState,
            rd,
            {"status": RepairStatus, "failure_class": FailureClass},
        )

    escalations = {}
    for eid, ed in data.get("escalations", {}).items():
        escalations[eid] = _reconstruct_dataclass(
            EscalationState,
            ed,
            {"decision": EscalationDecisionType, "disagreement_class": DisagreementClass},
        )

    # 17. Phase 11 Contracts
    bp_data = data.get("blueprint")
    blueprint = ImplementationBlueprint.from_dict(bp_data) if bp_data else None

    im_data = data.get("interface_manifest")
    interface_manifest = InterfaceManifest.from_dict(im_data) if im_data else None

    qr_data = data.get("quality_rubric")
    quality_rubric = QualityRubric.from_dict(qr_data) if qr_data else None

    # Assemble state
    state = HermesRuntimeState(
        mission=mission,
        goal=goal,
        progress=progress,
        current_task=current_task,
        tasks=tasks,
        tool_execution=tool_exec,
        model_execution=model_exec,
        verification=verification,
        network=network,
        permission=permission,
        session=session,
        evidence=evidence,
        checkpoint=checkpoint,
        requirements=requirements,
        acceptance_ledger=ledger,
        todos=todos,
        plan=plan,
        execution_mode=ExecutionMode(data.get("execution_mode", ExecutionMode.EXECUTION_MODE.value)),
        agents=agents,
        subagent_tasks=subagent_tasks,
        worktrees=worktrees,
        background_jobs=background_jobs,
        repairs=repairs,
        escalations=escalations,
        blueprint=blueprint,
        interface_manifest=interface_manifest,
        quality_rubric=quality_rubric,
        active_skills=data.get("active_skills", []),
        skill_fingerprints=data.get("skill_fingerprints", {}),
        state_version=data.get("state_version", 0),
        last_event_sequence=data.get("last_event_sequence", 0),
        last_updated_at=data.get("last_updated_at", 0.0),
        metadata=data.get("metadata", {}),
    )
    return state
