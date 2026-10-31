# core/server/models.py
"""
Pydantic Request and Response Schemas for HERMES 2.x Local FastAPI Server.
Strict typing, schema validation, and safe data representations.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0-rc1"
    runtime_mode: str = "auto"
    python_version: str
    workspace_locked: bool
    workspace_root: str
    server_time: float = Field(default_factory=time.time)
    startup_time: Optional[float] = None
    pid: Optional[int] = None
    code_fingerprint: Optional[str] = None
    code_match: Optional[bool] = None
    runtime_status: Optional[str] = "SYNCED"
    python_executable: Optional[str] = None
    model_stack: Dict[str, str]


class WorkspaceInfo(BaseModel):
    path: str
    name: Optional[str] = None
    is_locked: bool
    exists: bool
    is_active: bool = False
    is_hermes_repo: bool = False
    last_opened: Optional[float] = None
    total_files: Optional[int] = None
    framework: Optional[str] = None
    language: Optional[str] = None


class WorkspacesResponse(BaseModel):
    workspaces: List[WorkspaceInfo]
    current_workspace: str
    is_hermes_repo: bool = False


class SelectWorkspaceRequest(BaseModel):
    folder_path: str = Field(..., min_length=1, description="Path to folder to select as active workspace")


class RemoveWorkspaceRequest(BaseModel):
    folder_path: str = Field(..., min_length=1, description="Path to folder to remove from recent list")


class PickFolderResponse(BaseModel):
    cancelled: bool
    path: Optional[str] = None
    name: Optional[str] = None
    is_hermes_repo: bool = False
    error: Optional[str] = None


class SessionSummary(BaseModel):
    session_id: str
    mission_id: str
    workspace_root: str
    status: str
    branch_name: str
    created_at: float
    updated_at: float
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionsResponse(BaseModel):
    sessions: List[SessionSummary]
    total_count: int


class TaskSnapshot(BaseModel):
    task_id: str
    title: str
    description: str
    status: str
    is_verified: bool
    verification_evidence: Optional[str] = None
    files_created: List[str] = Field(default_factory=list)
    files_modified: List[str] = Field(default_factory=list)


class VerificationCheckItem(BaseModel):
    check_id: str
    task_id: Optional[str] = None
    title: str
    status: str  # "passed", "failed", "blocked", "pending", "not_run", "warning"
    command: Optional[str] = None
    exit_code: Optional[int] = None
    output_snippet: Optional[str] = None
    evidence: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    duration_seconds: Optional[float] = None
    category: str = "acceptance_gate"  # "acceptance_gate", "task_gate", "tool_execution"
    severity: str = "error"  # "error", "warning", "info"
    is_blocking: bool = True


class MissionSnapshot(BaseModel):
    mission_id: str
    run_id: Optional[str] = None
    attempt_number: int = 1
    title: str
    prompt: str
    status: str
    is_terminal: bool
    workspace_root: str
    created_at: float
    state_version: int
    last_sequence: int
    tasks: List[TaskSnapshot] = Field(default_factory=list)
    files_created: List[str] = Field(default_factory=list)
    files_modified: List[str] = Field(default_factory=list)
    checks: List[VerificationCheckItem] = Field(default_factory=list)
    error: Optional[str] = None
    final_output: Optional[str] = None
    completion_reason: Optional[str] = None
    wait_reason: Optional[str] = None
    recovery_required: bool = False
    is_paused: bool = False
    pause_pending: bool = False


class CreateMissionRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="The goal or instruction for HERMES to execute")
    workspace_root: Optional[str] = Field(None, description="Optional workspace root directory to lock")
    plan_mode: bool = Field(False, description="Whether to run in plan mode without tool execution")


class CreateMissionResponse(BaseModel):
    mission_id: str
    status: str
    workspace_root: str
    message: str


class StopMissionResponse(BaseModel):
    mission_id: str
    cancelled: bool
    message: str


class PauseMissionResponse(BaseModel):
    mission_id: str
    paused: bool
    status: str = "PAUSED"
    message: str


class ResumeMissionResponse(BaseModel):
    mission_id: str
    run_id: str
    status: str
    attempt_number: int
    target_task_id: Optional[str] = None
    target_task_title: Optional[str] = None
    workspace_root: str
    message: str


class DiscrepancyItem(BaseModel):
    discrepancy_type: str
    path: Optional[str] = None
    description: str
    blocking: bool = True
    operation_id: Optional[str] = None
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None


class ResumePreviewResponse(BaseModel):
    mission_id: str
    can_resume: bool
    checkpoint_id: Optional[str] = None
    original_workspace: str
    target_task_id: Optional[str] = None
    target_task_title: Optional[str] = None
    completed_tasks: List[str] = Field(default_factory=list)
    pending_tasks: List[str] = Field(default_factory=list)
    discrepancies: List[DiscrepancyItem] = Field(default_factory=list)
    reason: str
    reconciliation_summary: Dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    approved: bool
    scope: str = Field("ONCE", description="Scope of approval: ONCE, SESSION, ALWAYS")
    reason: Optional[str] = None


class ApprovalDecisionResponse(BaseModel):
    request_id: str
    resolved: bool
    approved: bool
    message: str


class PendingApprovalItem(BaseModel):
    request_id: str
    mission_id: Optional[str] = None
    tool_name: str
    arguments: Dict[str, Any]
    reason: str
    created_at: float
    expires_at: Optional[float] = None


class PendingApprovalsResponse(BaseModel):
    pending_approvals: List[PendingApprovalItem]


class FileDiffEntry(BaseModel):
    path: str
    change_type: str  # "created", "modified", "deleted"
    additions: int = 0
    deletions: int = 0
    diff_text: str = ""
    original_content: Optional[str] = None
    new_content: Optional[str] = None
    is_binary: bool = False
    is_large: bool = False
    size_bytes: int = 0


class MissionDiffsResponse(BaseModel):
    mission_id: str
    files: List[FileDiffEntry] = Field(default_factory=list)
    total_additions: int = 0
    total_deletions: int = 0



class MissionChecksResponse(BaseModel):
    mission_id: str
    checks: List[VerificationCheckItem] = Field(default_factory=list)
    passed_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    warning_count: int = 0
    mandatory_failed_count: int = 0


class ErrorDetail(BaseModel):
    error: str
    detail: Optional[str] = None


class NetworkStatusResponse(BaseModel):
    status: str
    is_connected: bool
    last_checked: float
    consecutive_failures: int
    consecutive_successes: int
    probe_targets: List[str] = Field(default_factory=list)
    last_error: Optional[str] = None
    waiting_missions_count: int = 0


class NetworkRecoverResponse(BaseModel):
    recovered_count: int
    recovered_mission_ids: List[str] = Field(default_factory=list)
    message: str
