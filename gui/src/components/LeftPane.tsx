// gui/src/components/LeftPane.tsx
import React, { useState } from 'react';
import { formatFileCount } from '../utils/format';
import { Plus, FolderPlus, Folder, History, Search, Trash2, CheckCircle2, AlertTriangle } from 'lucide-react';
import { WorkspaceInfo, SessionSummary } from '../types';

interface LeftPaneProps {
  workspaces: WorkspaceInfo[];
  currentWorkspace: string;
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onOpenFolderDialog: () => void;
  isOpeningFolder?: boolean;
  onSelectWorkspace: (path: string) => void;
  onRemoveRecentWorkspace: (path: string) => void;
  onNewTask: () => void;
  onSelectSession: (sessionId: string) => void;
  className?: string;
}

export const LeftPane: React.FC<LeftPaneProps> = ({
  workspaces,
  currentWorkspace,
  sessions,
  activeSessionId,
  onOpenFolderDialog,
  isOpeningFolder = false,
  onSelectWorkspace,
  onRemoveRecentWorkspace,
  onNewTask,
  onSelectSession,
  className,
}) => {
  const [sessionFilter, setSessionFilter] = useState('');
  const [projectFilter, setProjectFilter] = useState('');

  const filteredWorkspaces = workspaces.filter(
    (w) =>
      (w.name || w.path).toLowerCase().includes(projectFilter.toLowerCase()) ||
      w.path.toLowerCase().includes(projectFilter.toLowerCase())
  );

  const filteredSessions = sessions.filter(
    (s) =>
      s.session_id.toLowerCase().includes(sessionFilter.toLowerCase()) ||
      s.mission_id.toLowerCase().includes(sessionFilter.toLowerCase())
  );

  return (
    <aside
      className={`left-pane-container ${className || ''}`}
      style={{
        backgroundColor: 'var(--bg-chrome)',
        borderRight: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        userSelect: 'none',
      }}
    >
      {/* ── 1. Action Controls: New Task & Open Project ── */}
      <div style={{ padding: '12px 14px 8px 14px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <button
          onClick={onNewTask}
          title="Start a new task in active project"
          style={{
            width: '100%',
            height: '36px',
            backgroundColor: 'var(--color-forest)',
            color: '#FFFFFF',
            border: 'none',
            borderRadius: '6px',
            fontWeight: 600,
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            cursor: 'pointer',
          }}
          className="transition-fast"
        >
          <Plus size={16} strokeWidth={2.5} />
          New Task
        </button>

        <button
          onClick={onOpenFolderDialog}
          disabled={isOpeningFolder}
          title={isOpeningFolder ? "Windows folder picker is open..." : "Browse Windows folder picker to open a project"}
          style={{
            width: '100%',
            height: '34px',
            backgroundColor: 'var(--bg-surface)',
            color: 'var(--text-main)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '6px',
            fontWeight: 600,
            fontSize: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            cursor: isOpeningFolder ? 'wait' : 'pointer',
            opacity: isOpeningFolder ? 0.7 : 1,
          }}
          className="transition-fast"
        >
          <FolderPlus size={15} color={isOpeningFolder ? "var(--text-secondary)" : "var(--color-forest)"} />
          {isOpeningFolder ? 'Opening Picker…' : 'Open Project'}
        </button>
      </div>

      {/* ── 2. Antigravity-Inspired Projects Hub Section ── */}
      <div style={{ padding: '8px 14px 4px 14px', maxHeight: '42%', display: 'flex', flexDirection: 'column' }}>
        <div
          style={{
            fontSize: '11px',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.6px',
            color: 'var(--text-secondary)',
            marginBottom: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Folder size={12} />
            Projects ({workspaces.length})
          </div>
        </div>

        {/* Project search filter if > 4 workspaces */}
        {workspaces.length > 4 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'var(--bg-surface)',
              borderRadius: '4px',
              padding: '3px 6px',
              marginBottom: '6px',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <Search size={11} color="var(--text-secondary)" style={{ marginRight: '4px' }} />
            <input
              type="text"
              placeholder="Search projects..."
              value={projectFilter}
              onChange={(e) => setProjectFilter(e.target.value)}
              style={{
                border: 'none',
                background: 'transparent',
                outline: 'none',
                fontSize: '11px',
                color: 'var(--text-main)',
                width: '100%',
              }}
            />
          </div>
        )}

        {/* Project List */}
        <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px', paddingRight: '2px' }}>
          {filteredWorkspaces.length === 0 ? (
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', padding: '6px 0' }}>
              No projects added yet
            </div>
          ) : (
            filteredWorkspaces.map((w) => {
              const isActive = w.is_active || w.path.toLowerCase() === currentWorkspace.toLowerCase();
              return (
                <div
                  key={w.path}
                  onClick={() => onSelectWorkspace(w.path)}
                  title={`${w.path}\n${w.is_hermes_repo ? '⚠️ Protected HERMES Repository Root' : ''}`}
                  style={{
                    padding: '6px 8px',
                    borderRadius: '5px',
                    backgroundColor: isActive ? 'var(--bg-selected)' : 'transparent',
                    border: '1px solid',
                    borderColor: isActive ? 'var(--border-focus)' : 'transparent',
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '2px',
                    position: 'relative',
                  }}
                  className="transition-fast"
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden' }}>
                      {isActive && <CheckCircle2 size={12} color="var(--color-forest)" style={{ flexShrink: 0 }} />}
                      {w.is_hermes_repo && (
                        <span title="Protected HERMES Root" style={{ display: 'flex' }}>
                          <AlertTriangle size={12} color="#D97706" style={{ flexShrink: 0 }} />
                        </span>
                      )}
                      <span
                        style={{
                          fontSize: '12px',
                          fontWeight: isActive ? 700 : 500,
                          color: isActive ? 'var(--color-forest)' : 'var(--text-main)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {w.name || w.path.split(/[/\\]/).pop() || w.path}
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      {w.total_files !== null && (
                        <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                          {formatFileCount(w.total_files)}
                        </span>
                      )}
                      {!isActive && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onRemoveRecentWorkspace(w.path);
                          }}
                          title="Remove from recent list"
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--text-secondary)',
                            cursor: 'pointer',
                            padding: '2px',
                            display: 'flex',
                            alignItems: 'center',
                          }}
                        >
                          <Trash2 size={11} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Canonical path snippet */}
                  <div
                    style={{
                      fontSize: '10px',
                      color: 'var(--text-secondary)',
                      fontFamily: 'var(--font-mono)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {w.path}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      <div style={{ height: '1px', backgroundColor: 'var(--border-subtle)', margin: '8px 14px' }} />

      {/* ── 3. Sessions History Section (Scoped to Project/Mission) ── */}
      <div style={{ padding: '4px 14px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div
          style={{
            fontSize: '11px',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.6px',
            color: 'var(--text-secondary)',
            marginBottom: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <History size={12} />
            Missions ({sessions.length})
          </div>
        </div>

        {/* Filter input */}
        {sessions.length > 3 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'var(--bg-surface)',
              borderRadius: '4px',
              padding: '4px 8px',
              marginBottom: '6px',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <Search size={12} color="var(--text-secondary)" style={{ marginRight: '6px' }} />
            <input
              type="text"
              placeholder="Filter missions..."
              value={sessionFilter}
              onChange={(e) => setSessionFilter(e.target.value)}
              style={{
                border: 'none',
                background: 'transparent',
                outline: 'none',
                fontSize: '11px',
                color: 'var(--text-main)',
                width: '100%',
              }}
            />
          </div>
        )}

        {/* Sessions list */}
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {filteredSessions.length === 0 ? (
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', padding: '10px 0' }}>
              No historical missions
            </div>
          ) : (
            filteredSessions.map((s) => {
              const isSelected = activeSessionId === s.session_id;
              return (
                <div
                  key={s.session_id}
                  onClick={() => onSelectSession(s.session_id)}
                  style={{
                    padding: '8px',
                    borderRadius: '5px',
                    backgroundColor: isSelected ? 'var(--bg-selected)' : 'transparent',
                    border: '1px solid',
                    borderColor: isSelected ? 'var(--border-focus)' : 'transparent',
                    cursor: 'pointer',
                  }}
                  className="transition-fast"
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-main)' }}>
                      {s.mission_id || s.session_id.slice(0, 10)}
                    </span>
                    <span
                      style={{
                        fontSize: '10px',
                        fontWeight: 600,
                        padding: '1px 5px',
                        borderRadius: '3px',
                        backgroundColor: s.status === 'COMPLETED' ? 'var(--bg-verified)' : 'var(--bg-surface)',
                        color: s.status === 'COMPLETED' ? 'var(--text-verified)' : 'var(--text-secondary)',
                      }}
                    >
                      {s.status}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                    {new Date(s.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </aside>
  );
};
