// gui/src/App.tsx
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { TopBar } from './components/TopBar';
import { LeftPane } from './components/LeftPane';
import { TaskCard } from './components/TaskCard';
import { ExecutionTimeline } from './components/ExecutionTimeline';
import { RightPane } from './components/RightPane';
import { Composer } from './components/Composer';
import { ActivityPanel } from './components/ActivityPanel';
import { ApprovalCard } from './components/ApprovalCard';
import { HermesRootModal } from './components/HermesRootModal';
import { Folder, MessageSquare, Sliders } from 'lucide-react';
import { HermesApiClient } from './api';
import {
  HealthResponse,
  WorkspaceInfo,
  SessionSummary,
  MissionSnapshot,
  PendingApprovalItem,
  HermesEvent,
} from './types';
import {
  ClientSyncState,
  createInitialSyncState,
  processIncomingSnapshot,
  processIncomingEvent,
} from './sync';

export const App: React.FC = () => {
  // ── Runtime & Workspace State ─────────────────────────────────────────────
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [backendConnected, setBackendConnected] = useState<boolean>(false);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [currentWorkspace, setCurrentWorkspace] = useState<string>('');
  const [isCurrentHermesRepo, setIsCurrentHermesRepo] = useState<boolean>(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [copiedPath, setCopiedPath] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState<PendingApprovalItem[]>([]);

  // ── HERMES Root Guard Modal State ─────────────────────────────────────────
  const [showHermesModal, setShowHermesModal] = useState<boolean>(false);
  const [pendingPromptForModal, setPendingPromptForModal] = useState<string>('');

  // ── Mission & Event Stream State ──────────────────────────────────────────
  const [currentMissionId, setCurrentMissionId] = useState<string | null>(null);
  const [currentPrompt, setCurrentPrompt] = useState<string>('');
  const [snapshot, setSnapshot] = useState<MissionSnapshot | null>(null);
  const [streamEvents, setStreamEvents] = useState<HermesEvent[]>([]);
  const [isStopping, setIsStopping] = useState(false);
  const [isPickingFolder, setIsPickingFolder] = useState(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);

  // ── Right Pane Tab State ──────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<'changes' | 'checks' | 'outcome'>('outcome');

  // ── Mobile View State ──────────────────────────────────────────────────────
  const [mobileView, setMobileView] = useState<'hub' | 'mission' | 'details'>('mission');

  const sseCleanupRef = useRef<(() => void) | null>(null);
  const initialLoadedRef = useRef<boolean>(false);
  const snapshotRef = useRef<MissionSnapshot | null>(null);
  const syncStateRef = useRef<ClientSyncState>(createInitialSyncState());

  useEffect(() => {
    snapshotRef.current = snapshot;
  }, [snapshot]);

  // ── 1. Initial Data Fetch & Health Poll ────────────────────────────────────
  const fetchInitialData = useCallback(async () => {
    try {
      const h = await HermesApiClient.getHealth();
      setHealth(h);
      setBackendConnected(true);

      const ws = await HermesApiClient.getWorkspaces();
      setWorkspaces(ws.workspaces);
      setCurrentWorkspace(ws.current_workspace);
      setIsCurrentHermesRepo(!!ws.is_hermes_repo);

      const sess = await HermesApiClient.getSessions();
      setSessions(sess.sessions);
      if (!initialLoadedRef.current) {
        initialLoadedRef.current = true;
        if (sess.sessions.length > 0) {
          setCurrentMissionId((prev) => {
            if (!prev) {
              refreshSnapshot(sess.sessions[0].mission_id);
              return sess.sessions[0].mission_id;
            }
            return prev;
          });
        }
      }

      const appr = await HermesApiClient.getPendingApprovals();
      setPendingApprovals(appr.pending_approvals);
    } catch (err) {
      setBackendConnected(false);
    }
  }, []);

  useEffect(() => {
    fetchInitialData();
    const interval = setInterval(fetchInitialData, 5000);
    return () => clearInterval(interval);
  }, [fetchInitialData]);

  // Handle URL query parameter ?mission_id=...
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const mId = params.get('mission_id');
    if (mId) {
      setCurrentMissionId(mId);
      refreshSnapshot(mId);
    }
  }, []);

  // ── Approval Decision Handler ─────────────────────────────────────────────
  const handleResolveApproval = async (requestId: string, approved: boolean, scope: string = 'ONCE') => {
    try {
      await HermesApiClient.resolveApproval(requestId, approved, scope);
      const appr = await HermesApiClient.getPendingApprovals();
      setPendingApprovals(appr.pending_approvals);
      if (currentMissionId) {
        refreshSnapshot(currentMissionId);
      }
    } catch (err) {
      console.error('Failed to resolve approval:', err);
    }
  };

  // ── 2. Poll / Refresh Snapshot for Active Mission ─────────────────────────
  const refreshSnapshot = useCallback(async (missionId: string) => {
    try {
      const snap = await HermesApiClient.getMissionSnapshot(missionId);
      // Mission switching guard: if user switched away, ignore snapshot of other mission
      if (currentMissionId && snap.mission_id !== currentMissionId) {
        return;
      }

      const res = processIncomingSnapshot(syncStateRef.current, snap);
      if (res.accepted) {
        syncStateRef.current = res.nextState;
        setSnapshot(res.nextState.snapshot);
        if (snap.prompt) {
          setCurrentPrompt(snap.prompt);
        }
        if (snap.workspace_root) {
          setCurrentWorkspace(snap.workspace_root);
        }

        // On failure, automatically switch tab to Outcome
        if (snap.status === 'FAILED') {
          setActiveTab('outcome');
        }

        // Reconcile and recover durable event history from backend
        try {
          const hist = await HermesApiClient.getMissionEventHistory(missionId);
          if (hist && Array.isArray(hist.events) && hist.events.length > 0) {
            setStreamEvents((prev) => {
              const existingKeys = new Set(
                prev.map((e) => `${e.sequence}:${e.event_id || e.event_type}`)
              );
              const toAdd = hist.events.filter(
                (e) => !existingKeys.has(`${e.sequence}:${e.event_id || e.event_type}`)
              );
              if (toAdd.length === 0) return prev;
              const merged = [...prev, ...toAdd].sort((a, b) => (a.sequence || 0) - (b.sequence || 0));
              return merged.length > 1000 ? merged.slice(merged.length - 1000) : merged;
            });
          }
        } catch (histErr) {
          console.debug('Event history fetch note:', histErr);
        }
      } else {
        console.warn('Snapshot rejected by race guard:', res.reason);
      }
    } catch (err) {
      console.warn('Failed to fetch snapshot', err);
    }
  }, [currentMissionId]);

  // ── 3. Connect to SSE Stream for Current Mission ──────────────────────────
  useEffect(() => {
    if (!currentMissionId) {
      if (sseCleanupRef.current) {
        sseCleanupRef.current();
        sseCleanupRef.current = null;
      }
      return;
    }

    if (sseCleanupRef.current) {
      sseCleanupRef.current();
    }

    const cleanup = HermesApiClient.connectMissionEvents(
      currentMissionId,
      0,
      (event: HermesEvent) => {
        const res = processIncomingEvent(syncStateRef.current, event);
        if (res.accepted) {
          syncStateRef.current = res.nextState;
          setStreamEvents((prev) => {
            const isDup = prev.some(
              (e) =>
                (e.sequence > 0 && e.sequence === event.sequence) ||
                (e.event_id && event.event_id && e.event_id === event.event_id)
            );
            if (isDup) return prev;
            const next = [...prev, event];
            return next.length > 1000 ? next.slice(next.length - 1000) : next;
          });
        } else {
          console.debug('Event rejected by race guard:', res.reason);
        }

        if (
          event.event_type.includes('COMPLETED') ||
          event.event_type.includes('FAILED') ||
          event.event_type.includes('CANCELLED') ||
          event.event_type.includes('STOPPED') ||
          event.event_type.includes('TASK_') ||
          event.event_type.includes('WAITING') ||
          event.event_type.includes('NETWORK_') ||
          event.event_type.includes('PAUSED') ||
          event.event_type.includes('RESUMED')
        ) {
          refreshSnapshot(currentMissionId);
        }
      },
      (err: any) => {
        console.warn('SSE connection alert', err);
      },
      (expected: number, received: number) => {
        console.warn(
          `Event sequence gap detected: expected ${expected}, got ${received}. Resynchronizing snapshot.`
        );
        refreshSnapshot(currentMissionId);
      }
    );

    sseCleanupRef.current = cleanup;

    const pollInterval = setInterval(() => {
      if (currentMissionId) {
        refreshSnapshot(currentMissionId);
      }
    }, 2000);

    return () => {
      clearInterval(pollInterval);
      if (sseCleanupRef.current) {
        sseCleanupRef.current();
        sseCleanupRef.current = null;
      }
    };
  }, [currentMissionId, refreshSnapshot]);

  // ── 4. Project Switching & Native Folder Picker ───────────────────────────
  const handleOpenFolderDialog = async () => {
    if (isPickingFolder) return;
    if (showHermesModal) {
      setShowHermesModal(false);
      setPendingPromptForModal('');
    }
    setIsPickingFolder(true);
    try {
      const res = await HermesApiClient.pickFolder();
      if (!res.cancelled && res.path) {
        setSubmissionError(null);
        // Refresh workspaces list & current workspace
        const ws = await HermesApiClient.getWorkspaces();
        setWorkspaces(ws.workspaces);
        setCurrentWorkspace(ws.current_workspace);
        setIsCurrentHermesRepo(!!ws.is_hermes_repo);
        // Clear current active task composer/view so new project is ready
        handleNewTask();
      } else if (res.error) {
        setSubmissionError(res.error);
      }
    } catch (err: any) {
      setSubmissionError(err.message || 'Error opening folder picker');
    } finally {
      setIsPickingFolder(false);
    }
  };

  const handleSelectWorkspace = async (path: string) => {
    try {
      const ws = await HermesApiClient.selectWorkspace(path);
      setWorkspaces(ws.workspaces);
      setCurrentWorkspace(ws.current_workspace);
      setIsCurrentHermesRepo(!!ws.is_hermes_repo);
      handleNewTask();
    } catch (err: any) {
      setSubmissionError(err.message || 'Failed to switch workspace');
    }
  };

  const handleRemoveRecentWorkspace = async (path: string) => {
    try {
      const ws = await HermesApiClient.removeRecentWorkspace(path);
      setWorkspaces(ws.workspaces);
      setCurrentWorkspace(ws.current_workspace);
      setIsCurrentHermesRepo(!!ws.is_hermes_repo);
    } catch (err: any) {
      console.error('Failed to remove recent workspace', err);
    }
  };

  // ── 5. Task Submission with HERMES Root Guard ─────────────────────────────
  const executeMissionSubmission = async (promptText: string) => {
    setSubmissionError(null);
    setCurrentPrompt(promptText);
    setStreamEvents([]);
    syncStateRef.current = createInitialSyncState(null);
    setIsStopping(false);

    try {
      const resp = await HermesApiClient.createMission({
        prompt: promptText,
        workspace_root: currentWorkspace || health?.workspace_root,
        plan_mode: false, // Mandatory AUTO mode execution
      });
      setCurrentMissionId(resp.mission_id);
      setActiveTab('outcome');
      await refreshSnapshot(resp.mission_id);
      // Refresh sessions list
      const sess = await HermesApiClient.getSessions();
      setSessions(sess.sessions);
    } catch (err: any) {
      setSubmissionError(err.message || 'Failed to submit mission.');
    }
  };

  const handleSendPrompt = async (promptText: string) => {
    // Check if targeting HERMES repo root without confirmation
    if (isCurrentHermesRepo) {
      setPendingPromptForModal(promptText);
      setShowHermesModal(true);
      return;
    }
    await executeMissionSubmission(promptText);
  };

  const handleConfirmHermesRoot = async () => {
    setShowHermesModal(false);
    if (pendingPromptForModal) {
      await executeMissionSubmission(pendingPromptForModal);
      setPendingPromptForModal('');
    }
  };

  const handleCancelHermesRoot = () => {
    setShowHermesModal(false);
    setPendingPromptForModal('');
  };

  // ── 6. Mission Cancellation, Pause & Resumption ─────────────────────────
  const handleStopMission = async () => {
    if (!currentMissionId) return;
    setIsStopping(true);
    try {
      await HermesApiClient.stopMission(currentMissionId);
      await refreshSnapshot(currentMissionId);
    } catch (err: any) {
      console.error('Stop request failed', err);
      setSubmissionError(err.message || 'Failed to stop mission');
    } finally {
      setIsStopping(false);
    }
  };

  // ── 7. UI Helpers ─────────────────────────────────────────────────────────
  const handleCopyPath = () => {
    const p = currentWorkspace || health?.workspace_root;
    if (p) {
      navigator.clipboard.writeText(p);
      setCopiedPath(true);
      setTimeout(() => setCopiedPath(false), 2000);
    }
  };

  const handleNewTask = () => {
    syncStateRef.current = createInitialSyncState(null);
    setCurrentMissionId(null);
    setCurrentPrompt('');
    setSnapshot(null);
    setStreamEvents([]);
    setSubmissionError(null);
  };

  const isTerminal = snapshot?.is_terminal || ['COMPLETED', 'FAILED', 'CANCELLED', 'STOPPED', 'ABORTED'].includes(snapshot?.status || '');
  const isRunning = !isTerminal && (snapshot?.status === 'RUNNING' || snapshot?.status === 'VERIFYING' || (!!currentMissionId && !snapshot?.status));
  const isFailed = snapshot?.status === 'FAILED';
  const isCompleted = snapshot?.status === 'COMPLETED';

  const activePath = snapshot?.workspace_root || currentWorkspace || health?.workspace_root || '';
  const displayWorkspaceName = activePath
    ? activePath.split(/[/\\]/).pop() || activePath
    : 'Workspace';

  const displayWorkspacePath = activePath || 'Not connected';

  return (
    <div className="app-container" style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw' }}>
      {/* Top Bar with Project Switcher & Guard */}
      <TopBar
        workspaceName={displayWorkspaceName}
        workspacePath={displayWorkspacePath}
        isHermesRepo={isCurrentHermesRepo}
        backendConnected={backendConnected}
        missionStatus={snapshot?.status || 'IDLE'}
        waitReason={snapshot?.wait_reason}
        isPaused={snapshot?.is_paused}
        pausePending={snapshot?.pause_pending}
        onOpenFolderDialog={handleOpenFolderDialog}
        isOpeningFolder={isPickingFolder}
        onCopyPath={handleCopyPath}
        copied={copiedPath}
        codeMatch={health?.code_match}
      />

      {/* Mobile Navigation Switcher (visible <= 900px) */}
      <nav className="mobile-nav-bar" aria-label="Mobile Navigation">
        <button
          className={`mobile-nav-item ${mobileView === 'hub' ? 'active' : ''}`}
          onClick={() => setMobileView('hub')}
          title="Project Hub"
        >
          <Folder size={16} />
          <span>Hub</span>
        </button>
        <button
          className={`mobile-nav-item ${mobileView === 'mission' ? 'active' : ''}`}
          onClick={() => setMobileView('mission')}
          title="Mission Workspace"
        >
          <MessageSquare size={16} />
          <span>Mission</span>
        </button>
        <button
          className={`mobile-nav-item ${mobileView === 'details' ? 'active' : ''}`}
          onClick={() => setMobileView('details')}
          title="Details & Outcomes"
        >
          <Sliders size={16} />
          <span>Details</span>
        </button>
      </nav>

      {/* Main Three-Pane Shell */}
      <div className="main-shell" style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left Pane: Antigravity-Inspired Project Hub */}
        <LeftPane
          className={mobileView === 'hub' ? 'mobile-active' : ''}
          workspaces={workspaces}
          currentWorkspace={currentWorkspace}
          sessions={sessions}
          activeSessionId={activeSessionId}
          onOpenFolderDialog={handleOpenFolderDialog}
          isOpeningFolder={isPickingFolder}
          onSelectWorkspace={handleSelectWorkspace}
          onRemoveRecentWorkspace={handleRemoveRecentWorkspace}
          onNewTask={handleNewTask}
          onSelectSession={(sid) => {
            setActiveSessionId(sid);
            const s = sessions.find((item) => item.session_id === sid);
            if (s?.mission_id) {
              syncStateRef.current = createInitialSyncState(null);
              setStreamEvents([]);
              setCurrentMissionId(s.mission_id);
              refreshSnapshot(s.mission_id);
            }
          }}
        />

        {/* Center Pane: Task Progression & Conversation */}
        <main
          className={`center-pane-container ${mobileView === 'mission' ? 'mobile-active' : ''}`}
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            backgroundColor: 'var(--bg-main)',
            overflow: 'hidden',
          }}
        >
          {/* Scrollable Conversation Content */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '24px 32px' }}>
            {/* Backend Offline Warning Banner */}
            {!backendConnected && (
              <div
                style={{
                  padding: '12px 16px',
                  borderRadius: '6px',
                  backgroundColor: 'var(--bg-failure)',
                  border: '1px solid var(--border-failure)',
                  color: 'var(--text-failure)',
                  fontSize: '13px',
                  fontWeight: 600,
                  marginBottom: '16px',
                }}
              >
                Local HERMES backend offline at http://127.0.0.1:8765. Launch server using:
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', marginTop: '4px' }}>
                  .\venv\Scripts\python.exe main.py serve
                </div>
              </div>
            )}

            {/* Submission Error Banner */}
            {submissionError && (
              <div
                style={{
                  padding: '12px 16px',
                  borderRadius: '6px',
                  backgroundColor: 'var(--bg-failure)',
                  border: '1px solid var(--border-failure)',
                  color: 'var(--text-failure)',
                  fontSize: '13px',
                  marginBottom: '16px',
                }}
              >
                <strong>Submission Rejected:</strong> {submissionError}
              </div>
            )}

            {/* Inline Security Approvals Card */}
            <ApprovalCard
              approvals={pendingApprovals}
              onResolve={handleResolveApproval}
            />

            {/* Empty State / Prompt Introduction */}
            {!currentPrompt && !currentMissionId ? (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: '70%',
                  textAlign: 'center',
                }}
              >
                <div
                  style={{
                    width: '48px',
                    height: '48px',
                    borderRadius: '10px',
                    backgroundColor: 'var(--color-forest)',
                    color: '#FFF',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 700,
                    fontSize: '22px',
                    marginBottom: '16px',
                  }}
                >
                  H
                </div>
                <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--color-forest)', marginBottom: '8px' }}>
                  HERMES Autonomous Harness
                </h2>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '460px', lineHeight: '1.5' }}>
                  Active Project: <strong style={{ color: 'var(--text-main)' }}>{displayWorkspaceName}</strong>
                  <br />
                  <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                    {displayWorkspacePath}
                  </span>
                </p>
                <div style={{ marginTop: '12px', display: 'flex', gap: '10px' }}>
                  <button
                    onClick={handleOpenFolderDialog}
                    style={{
                      padding: '6px 14px',
                      borderRadius: '6px',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-subtle)',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--color-forest)',
                      cursor: 'pointer',
                    }}
                  >
                    Open Another Project
                  </button>
                </div>
              </div>
            ) : (
              <div>
                {/* User Prompt Bubble */}
                <div
                  style={{
                    backgroundColor: 'var(--bg-surface)',
                    borderRadius: '8px',
                    padding: '14px 18px',
                    border: '1px solid var(--border-subtle)',
                    marginBottom: '16px',
                  }}
                >
                  <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--color-forest)', textTransform: 'uppercase', marginBottom: '4px' }}>
                    User Request ({snapshot?.workspace_root ? (snapshot.workspace_root.split(/[/\\]/).pop() || snapshot.workspace_root) : displayWorkspaceName})
                  </div>
                  <div style={{ fontSize: '14px', color: 'var(--text-main)', lineHeight: '1.4' }}>
                    {currentPrompt}
                  </div>
                </div>

                {/* Task Execution Card */}
                {(() => {
                  const lastTierEvent = [...streamEvents].reverse().find(
                    (e) => e.event_type === 'TIER_SELECTED' || e.event_type === 'TIER_FAILOVER_STARTED'
                  );
                  const activeTier = Number(lastTierEvent?.payload?.tier || lastTierEvent?.payload?.to_tier || 1);
                  return (
                    <TaskCard
                      tasks={snapshot?.tasks || []}
                      isFailed={isFailed}
                      isCompleted={isCompleted}
                      failureError={snapshot?.error}
                      activeTier={activeTier}
                      modelStack={health?.model_stack}
                    />
                  );
                })()}

                {/* Antigravity-Style Chronological Micro-Step Cards */}
                <ExecutionTimeline events={streamEvents} isRunning={isRunning} />
              </div>
            )}
          </div>

          {/* Collapsed Activity Stream */}
          <ActivityPanel events={streamEvents} />

          {/* Bottom Pinned Composer */}
          <Composer
            onSend={handleSendPrompt}
            onStop={handleStopMission}
            isRunning={isRunning}
            isStopping={isStopping}
            isPaused={snapshot?.is_paused}
            waitReason={snapshot?.wait_reason}
            disabled={!backendConnected}
          />
        </main>

        {/* Right Pane: Changes, Checks, Outcome */}
        <RightPane
          className={mobileView === 'details' ? 'mobile-active' : ''}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          snapshot={snapshot}
          onStopMission={handleStopMission}
          isStopping={isStopping}
        />
      </div>

      {/* HERMES Repo Root Protection Confirmation Modal */}
      <HermesRootModal
        isOpen={showHermesModal}
        workspacePath={currentWorkspace || health?.workspace_root || ''}
        pendingPrompt={pendingPromptForModal}
        onConfirm={handleConfirmHermesRoot}
        onCancel={handleCancelHermesRoot}
        onOpenFolderDialog={handleOpenFolderDialog}
      />
    </div>
  );
};
