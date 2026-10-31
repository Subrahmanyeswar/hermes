// gui/src/types.ts
// Authoritative TypeScript interfaces mapped strictly to Stage 2 Pydantic schemas

export interface HealthResponse {
  status: string;
  version: string;
  runtime_mode: string;
  python_version: string;
  workspace_locked: boolean;
  workspace_root: string;
  server_time: number;
  code_fingerprint?: string;
  code_match?: boolean;
  runtime_status?: string;
  python_executable?: string;
  model_stack: Record<string, string>;
}

export interface WorkspaceInfo {
  path: string;
  name?: string;
  is_locked: boolean;
  exists: boolean;
  is_active?: boolean;
  is_hermes_repo?: boolean;
  last_opened?: number | null;
  total_files: number | null;
  framework: string | null;
  language: string | null;
}

export interface WorkspacesResponse {
  workspaces: WorkspaceInfo[];
  current_workspace: string;
  is_hermes_repo?: boolean;
}

export interface PickFolderResponse {
  cancelled: boolean;
  path?: string | null;
  name?: string | null;
  is_hermes_repo?: boolean;
  error?: string | null;
}

export interface SessionSummary {
  session_id: string;
  mission_id: string;
  workspace_root: string;
  status: string;
  branch_name: string;
  created_at: number;
  updated_at: number;
  metadata: Record<string, any>;
}

export interface SessionsResponse {
  sessions: SessionSummary[];
  total_count: number;
}

export interface TaskSnapshot {
  task_id: string;
  title: string;
  description: string;
  status: string;
  is_verified: boolean;
  verification_evidence: string | null;
  files_created: string[];
  files_modified: string[];
}

export interface MissionSnapshot {
  mission_id: string;
  run_id?: string | null;
  attempt_number?: number;
  title: string;
  prompt: string;
  status: string;
  is_terminal: boolean;
  workspace_root: string;
  created_at: number;
  state_version: number;
  last_sequence: number;
  tasks: TaskSnapshot[];
  files_created: string[];
  files_modified: string[];
  checks?: VerificationCheckItem[];
  error: string | null;
  final_output?: string | null;
  completion_reason?: string | null;
  wait_reason?: string | null;
  recovery_required?: boolean;
  is_paused?: boolean;
  pause_pending?: boolean;
}

export interface FileDiffEntry {
  path: string;
  change_type: 'created' | 'modified' | 'deleted' | string;
  additions: number;
  deletions: number;
  diff_text: string;
  original_content?: string | null;
  new_content?: string | null;
  is_binary: boolean;
  size_bytes: number;
}

export interface MissionDiffsResponse {
  mission_id: string;
  files: FileDiffEntry[];
  total_additions: number;
  total_deletions: number;
}

export interface VerificationCheckItem {
  check_id: string;
  task_id?: string | null;
  title: string;
  status: 'passed' | 'failed' | 'blocked' | 'pending' | 'not_run' | string;
  command?: string | null;
  exit_code?: number | null;
  output_snippet?: string | null;
  evidence?: string | null;
  timestamp: number;
  duration_seconds?: number | null;
}

export interface MissionChecksResponse {
  mission_id: string;
  checks: VerificationCheckItem[];
  passed_count: number;
  failed_count: number;
  total_count: number;
}

export interface ApprovalDecisionRequest {
  approved: boolean;
  scope?: string;
  reason?: string;
}

export interface ApprovalDecisionResponse {
  request_id: string;
  resolved: boolean;
  approved: boolean;
  message: string;
}

export interface CreateMissionRequest {
  prompt: string;
  workspace_root?: string;
  plan_mode?: boolean;
}

export interface CreateMissionResponse {
  mission_id: string;
  status: string;
  workspace_root: string;
  message: string;
}

export interface StopMissionResponse {
  mission_id: string;
  cancelled: boolean;
  message: string;
}

export interface PauseMissionResponse {
  mission_id: string;
  paused: boolean;
  status?: string;
  message: string;
}

export interface ResumeMissionResponse {
  mission_id: string;
  run_id: string;
  status: string;
  attempt_number: number;
  target_task_id?: string | null;
  target_task_title?: string | null;
  workspace_root: string;
  message: string;
}

export interface DiscrepancyItem {
  discrepancy_type: string;
  path?: string | null;
  description: string;
  blocking: boolean;
  operation_id?: string | null;
  expected_hash?: string | null;
  actual_hash?: string | null;
}

export interface ResumePreviewResponse {
  mission_id: string;
  can_resume: boolean;
  checkpoint_id?: string | null;
  original_workspace: string;
  target_task_id?: string | null;
  target_task_title?: string | null;
  completed_tasks: string[];
  pending_tasks: string[];
  discrepancies: DiscrepancyItem[];
  reason: string;
  reconciliation_summary: Record<string, any>;
}


export interface PendingApprovalItem {
  request_id: string;
  mission_id?: string | null;
  tool_name: string;
  arguments: Record<string, any>;
  reason: string;
  created_at: number;
  expires_at: number | null;
}

export interface PendingApprovalsResponse {
  pending_approvals: PendingApprovalItem[];
}

export interface HermesEventPayload {
  [key: string]: any;
}

export interface HermesEvent {
  event_type: string;
  mission_id: string;
  run_id?: string | null;
  attempt_number?: number;
  task_id?: string | null;
  event_id: string;
  timestamp: number;
  sequence: number;
  payload: HermesEventPayload;
  severity: string;
  schema_version: number;
}

export interface NetworkStatusResponse {
  status: string;
  is_connected: boolean;
  last_checked: number;
  consecutive_failures: number;
  consecutive_successes: number;
  probe_targets: string[];
  last_error: string | null;
  waiting_missions_count: number;
}

export interface NetworkRecoverResponse {
  recovered_count: number;
  recovered_mission_ids: string[];
  message: string;
}
