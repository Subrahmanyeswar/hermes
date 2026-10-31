// gui/src/api.ts
// Typed REST and SSE Client for HERMES Stage 2 backend

import {
  HealthResponse,
  WorkspacesResponse,
  SessionsResponse,
  MissionSnapshot,
  CreateMissionRequest,
  CreateMissionResponse,
  StopMissionResponse,
  PauseMissionResponse,
  ResumeMissionResponse,
  ResumePreviewResponse,
  PendingApprovalsResponse,
  ApprovalDecisionResponse,
  FileDiffEntry,
  MissionDiffsResponse,
  MissionChecksResponse,
  HermesEvent,
  PickFolderResponse,
  NetworkStatusResponse,
  NetworkRecoverResponse,
} from './types';

const API_BASE = '/api';

export class HermesApiClient {
  static async getHealth(): Promise<HealthResponse> {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error(`Health check failed: HTTP ${res.status}`);
    return res.json();
  }

  static async getWorkspaces(): Promise<WorkspacesResponse> {
    const res = await fetch(`${API_BASE}/workspaces`);
    if (!res.ok) throw new Error(`Fetch workspaces failed: HTTP ${res.status}`);
    return res.json();
  }

  static async selectWorkspace(folderPath: string): Promise<WorkspacesResponse> {
    const res = await fetch(`${API_BASE}/workspaces/select`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_path: folderPath }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to select workspace' }));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  static async pickFolder(): Promise<PickFolderResponse> {
    const res = await fetch(`${API_BASE}/workspaces/pick-folder`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to open folder picker' }));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  static async removeRecentWorkspace(folderPath: string): Promise<WorkspacesResponse> {
    const res = await fetch(`${API_BASE}/workspaces/recent`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_path: folderPath }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to remove recent workspace' }));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  static async getSessions(): Promise<SessionsResponse> {
    const res = await fetch(`${API_BASE}/sessions`);
    if (!res.ok) throw new Error(`Fetch sessions failed: HTTP ${res.status}`);
    return res.json();
  }

  static async createMission(req: CreateMissionRequest): Promise<CreateMissionResponse> {
    const res = await fetch(`${API_BASE}/missions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Unknown submission error' }));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  static async getMissionSnapshot(missionId: string): Promise<MissionSnapshot> {
    const res = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}`);
    if (!res.ok) throw new Error(`Mission snapshot failed: HTTP ${res.status}`);
    return res.json();
  }

  static async getMissionDiffs(missionId: string): Promise<MissionDiffsResponse> {
    const res = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/diffs`);
    if (!res.ok) throw new Error(`Fetch diffs failed: HTTP ${res.status}`);
    return res.json();
  }

  static async getFileDiff(missionId: string, filePath: string): Promise<FileDiffEntry> {
    const res = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/diffs/${encodeURIComponent(filePath)}`);
    if (!res.ok) throw new Error(`Fetch file diff failed: HTTP ${res.status}`);
    return res.json();
  }

  static async getMissionChecks(missionId: string): Promise<MissionChecksResponse> {
    const res = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/checks`);
    if (!res.ok) throw new Error(`Fetch checks failed: HTTP ${res.status}`);
    return res.json();
  }

  static async getMissionEventHistory(missionId: string, fromSeq: number = 0): Promise<{ mission_id: string; total: number; events: HermesEvent[] }> {
    const res = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/events/history?from_seq=${fromSeq}`);
    if (!res.ok) throw new Error(`Fetch event history failed: HTTP ${res.status}`);
    return res.json();
  }

  static async stopMission(missionId: string): Promise<StopMissionResponse> {
    const res = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/stop`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`Stop mission failed: HTTP ${res.status}`);
    return res.json();
  }

  static async pauseMission(missionId: string): Promise<PauseMissionResponse> {
    const res = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/pause`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to pause mission' }));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  static async resumeMission(missionId: string): Promise<ResumeMissionResponse> {
    const res = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/resume`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to resume mission' }));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  static async getResumePreview(missionId: string): Promise<ResumePreviewResponse> {
    const res = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/resume-preview`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to fetch resume preview' }));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  static async getPendingApprovals(): Promise<PendingApprovalsResponse> {
    const res = await fetch(`${API_BASE}/approvals`);
    if (!res.ok) throw new Error(`Fetch approvals failed: HTTP ${res.status}`);
    return res.json();
  }

  static async resolveApproval(requestId: string, approved: boolean, scope: string = 'ONCE'): Promise<ApprovalDecisionResponse> {
    const res = await fetch(`${API_BASE}/approvals/${encodeURIComponent(requestId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved, scope }),
    });
    if (!res.ok) throw new Error(`Resolve approval failed: HTTP ${res.status}`);
    return res.json();
  }

  static async getNetworkStatus(): Promise<NetworkStatusResponse> {
    const res = await fetch(`${API_BASE}/network/status`);
    if (!res.ok) throw new Error(`Fetch network status failed: HTTP ${res.status}`);
    return res.json();
  }

  static async triggerNetworkRecover(): Promise<NetworkRecoverResponse> {
    const res = await fetch(`${API_BASE}/network/recover`, { method: 'POST' });
    if (!res.ok) throw new Error(`Network recover failed: HTTP ${res.status}`);
    return res.json();
  }

  /**
   * Connect to SSE event stream with auto-reconnection and sequence cursor tracking.
   * Handles all event types (named and default) via streaming response.
   */
  static connectMissionEvents(
    missionId: string,
    initialCursor: number,
    onEvent: (event: HermesEvent) => void,
    onError: (err: any) => void,
    onGap?: (expected: number, received: number) => void
  ): () => void {
    let cursor = initialCursor;
    let active = true;
    let abortController: AbortController | null = null;
    let reconnectTimeout: any = null;

    const connect = async () => {
      if (!active) return;
      abortController = new AbortController();
      const url = `${API_BASE}/missions/${encodeURIComponent(missionId)}/events${cursor > 0 ? `?cursor=${cursor}` : ''}`;

      try {
        const response = await fetch(url, {
          signal: abortController.signal,
          headers: { Accept: 'text/event-stream' },
        });

        if (!response.ok) {
          throw new Error(`SSE stream failed: HTTP ${response.status}`);
        }

        if (!response.body) {
          throw new Error('ReadableStream not supported on response');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (active) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const blocks = buffer.split('\n\n');
          buffer = blocks.pop() || '';

          for (const block of blocks) {
            if (!block.trim()) continue;
            let dataStr = '';
            for (const line of block.split('\n')) {
              if (line.startsWith('data: ')) {
                dataStr = line.slice(6).trim();
              }
            }

            if (dataStr) {
              try {
                const parsed = JSON.parse(dataStr) as HermesEvent;
                if (parsed && typeof parsed.sequence === 'number') {
                  if (cursor > 0 && parsed.sequence > cursor + 1) {
                    if (onGap) {
                      onGap(cursor + 1, parsed.sequence);
                    }
                  }
                  if (parsed.sequence > cursor) {
                    cursor = parsed.sequence;
                  }
                }
                onEvent(parsed);
              } catch (parseErr) {
                console.warn('Failed to parse SSE event data', parseErr);
              }
            }
          }
        }
      } catch (err: any) {
        if (!active || (abortController && abortController.signal.aborted)) {
          return;
        }
        onError(err);
      } finally {
        if (active) {
          reconnectTimeout = setTimeout(connect, 3000);
        }
      }
    };

    connect();

    // Return cleanup closure
    return () => {
      active = false;
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
      }
      if (abortController) {
        abortController.abort();
        abortController = null;
      }
    };
  }
}
