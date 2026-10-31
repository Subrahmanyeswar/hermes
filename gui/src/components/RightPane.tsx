// gui/src/components/RightPane.tsx
import React, { useState, useEffect } from 'react';
import {
  FileText,
  CheckSquare,
  Flag,
  AlertTriangle,
  CheckCircle,
  Clock,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Terminal,
  StopCircle,
} from 'lucide-react';
import {
  MissionSnapshot,
  MissionDiffsResponse,
  FileDiffEntry,
  VerificationCheckItem,
} from '../types';
import { HermesApiClient } from '../api';

interface RightPaneProps {
  activeTab: 'changes' | 'checks' | 'outcome';
  onTabChange: (tab: 'changes' | 'checks' | 'outcome') => void;
  snapshot: MissionSnapshot | null;
  onStopMission?: () => void;
  isStopping?: boolean;
  className?: string;
}

export const RightPane: React.FC<RightPaneProps> = ({
  activeTab,
  onTabChange,
  snapshot,
  onStopMission,
  isStopping,
  className,
}) => {
  // ── Changes Tab State ───────────────────────────────────────────────────────
  const [diffsData, setDiffsData] = useState<MissionDiffsResponse | null>(null);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [loadingDiffs, setLoadingDiffs] = useState(false);
  const [copiedDiff, setCopiedDiff] = useState(false);

  // ── Checks Tab State ────────────────────────────────────────────────────────
  const [checks, setChecks] = useState<VerificationCheckItem[]>([]);
  const [checkFilter, setCheckFilter] = useState<'all' | 'passed' | 'failed'>('all');
  const [expandedCheckIds, setExpandedCheckIds] = useState<Set<string>>(new Set());
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);

  // ── Outcome Tab State ───────────────────────────────────────────────────────
  const [showTraceback, setShowTraceback] = useState(false);
  const [copiedTraceback, setCopiedTraceback] = useState(false);
  const [copiedWsPath, setCopiedWsPath] = useState(false);

  const handleCopyCommand = (cmd: string) => {
    navigator.clipboard.writeText(cmd);
    setCopiedCommand(cmd);
    setTimeout(() => setCopiedCommand(null), 2000);
  };

  // Fetch diffs whenever mission changes or last sequence advances
  useEffect(() => {
    if (!snapshot?.mission_id) {
      setDiffsData(null);
      setSelectedFilePath(null);
      return;
    }

    let isMounted = true;
    setLoadingDiffs(true);
    HermesApiClient.getMissionDiffs(snapshot.mission_id)
      .then((data) => {
        if (!isMounted) return;
        setDiffsData(data);
        if (data.files.length > 0 && !selectedFilePath) {
          setSelectedFilePath(data.files[0].path);
        }
      })
      .catch((err) => {
        console.debug('Could not fetch mission diffs', err);
      })
      .finally(() => {
        if (isMounted) setLoadingDiffs(false);
      });

    return () => {
      isMounted = false;
    };
  }, [snapshot?.mission_id, snapshot?.last_sequence]);

  // Fetch or sync checks
  useEffect(() => {
    if (!snapshot?.mission_id) {
      setChecks([]);
      return;
    }

    if (snapshot.checks && snapshot.checks.length > 0) {
      setChecks(snapshot.checks);
    } else {
      HermesApiClient.getMissionChecks(snapshot.mission_id)
        .then((resp) => {
          setChecks(resp.checks);
        })
        .catch(() => {});
    }
  }, [snapshot?.mission_id, snapshot?.checks, snapshot?.last_sequence]);

  // Determine active file diff
  const activeFileDiff: FileDiffEntry | undefined = diffsData?.files.find(
    (f) => f.path === selectedFilePath
  ) || diffsData?.files[0];

  const handleCopyDiff = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedDiff(true);
    setTimeout(() => setCopiedDiff(false), 2000);
  };

  const handleCopyTraceback = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedTraceback(true);
    setTimeout(() => setCopiedTraceback(false), 2000);
  };

  const handleCopyWorkspace = () => {
    if (snapshot?.workspace_root) {
      navigator.clipboard.writeText(snapshot.workspace_root);
      setCopiedWsPath(true);
      setTimeout(() => setCopiedWsPath(false), 2000);
    }
  };

  const toggleCheckExpand = (checkId: string) => {
    setExpandedCheckIds((prev) => {
      const next = new Set(prev);
      if (next.has(checkId)) next.delete(checkId);
      else next.add(checkId);
      return next;
    });
  };

  const filteredChecks = checks.filter((c) => {
    if (checkFilter === 'passed') return c.status === 'passed';
    if (checkFilter === 'failed') return c.status === 'failed';
    return true;
  });

  const passedChecksCount = checks.filter((c) => c.status === 'passed').length;
  const failedChecksCount = checks.filter((c) => c.status === 'failed').length;

  const totalAdditions = diffsData?.total_additions || 0;
  const totalDeletions = diffsData?.total_deletions || 0;
  const totalFilesChanged = diffsData?.files.length || (snapshot?.files_created.length || 0) + (snapshot?.files_modified.length || 0);

  const tabs = [
    { id: 'changes', label: 'Changes', icon: FileText, count: totalFilesChanged },
    { id: 'checks', label: 'Checks', icon: CheckSquare, count: passedChecksCount },
    { id: 'outcome', label: 'Outcome', icon: Flag },
  ] as const;

  return (
    <aside
      className={`right-pane-container ${className || ''}`}
      style={{
        backgroundColor: 'var(--bg-chrome)',
        borderLeft: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        userSelect: 'none',
      }}
    >
      {/* Tab Switcher Header */}
      <div
        style={{
          display: 'flex',
          borderBottom: '1px solid var(--border-subtle)',
          backgroundColor: 'var(--bg-chrome)',
        }}
      >
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              style={{
                flex: 1,
                padding: '12px 6px',
                border: 'none',
                background: isActive ? 'var(--bg-main)' : 'transparent',
                color: isActive ? 'var(--color-forest)' : 'var(--text-secondary)',
                fontWeight: isActive ? 700 : 500,
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '5px',
                cursor: 'pointer',
                borderBottom: isActive ? '2px solid var(--color-forest)' : '2px solid transparent',
              }}
              className="transition-fast"
            >
              <Icon size={14} />
              <span>{tab.label}</span>
              {'count' in tab && tab.count > 0 && (
                <span
                  style={{
                    backgroundColor: 'rgba(0, 84, 55, 0.1)',
                    borderRadius: '10px',
                    padding: '1px 6px',
                    fontSize: '10px',
                    fontWeight: 700,
                  }}
                >
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab Content Panes */}
      <div style={{ flex: 1, padding: '16px', overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
        {/* ──────────────────────────────────────────────────────────────────── */}
        {/* TAB 1: CHANGES (Genuine Diffs)                                       */}
        {/* ──────────────────────────────────────────────────────────────────── */}
        {activeTab === 'changes' && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Summary Pill Bar */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '12px',
              }}
            >
              <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
                Files ({totalFilesChanged})
              </span>
              <div style={{ display: 'flex', gap: '8px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
                {totalAdditions > 0 && (
                  <span style={{ color: 'var(--color-forest)', fontWeight: 700 }}>+{totalAdditions}</span>
                )}
                {totalDeletions > 0 && (
                  <span style={{ color: 'var(--text-failure)', fontWeight: 700 }}>-{totalDeletions}</span>
                )}
              </div>
            </div>

            {/* If no files */}
            {(!diffsData || diffsData.files.length === 0) && (!snapshot || (snapshot.files_created.length === 0 && snapshot.files_modified.length === 0)) ? (
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', fontStyle: 'italic', padding: '12px 0' }}>
                {loadingDiffs ? 'Scanning file modifications...' : 'No file changes recorded by runtime.'}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: '12px' }}>
                {/* File List Selector */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '140px', overflowY: 'auto' }}>
                  {diffsData?.files.map((file) => {
                    const isSelected = (selectedFilePath || diffsData.files[0]?.path) === file.path;
                    const isCreated = file.change_type === 'created';
                    const isDeleted = file.change_type === 'deleted';

                    return (
                      <div
                        key={file.path}
                        onClick={() => setSelectedFilePath(file.path)}
                        style={{
                          padding: '6px 10px',
                          borderRadius: '4px',
                          backgroundColor: isSelected ? 'rgba(0, 84, 55, 0.08)' : 'var(--bg-surface)',
                          border: `1px solid ${isSelected ? 'var(--color-forest)' : 'var(--border-subtle)'}`,
                          fontSize: '11px',
                          fontFamily: 'var(--font-mono)',
                          color: 'var(--text-main)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          cursor: 'pointer',
                        }}
                      >
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '240px' }}>
                          {file.path}
                        </span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span
                            style={{
                              fontSize: '9px',
                              fontWeight: 700,
                              padding: '1px 4px',
                              borderRadius: '3px',
                              backgroundColor: isCreated
                                ? 'rgba(0, 84, 55, 0.15)'
                                : isDeleted
                                ? 'rgba(156, 48, 48, 0.15)'
                                : 'rgba(222, 186, 214, 0.4)',
                              color: isCreated
                                ? 'var(--color-forest)'
                                : isDeleted
                                ? 'var(--text-failure)'
                                : 'var(--text-main)',
                            }}
                          >
                            {file.change_type.toUpperCase()}
                          </span>
                          {(file.additions > 0 || file.deletions > 0) && (
                            <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                              +{file.additions}/-{file.deletions}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Diff Viewer */}
                {activeFileDiff && (
                  <div
                    style={{
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      borderRadius: '6px',
                      border: '1px solid var(--border-subtle)',
                      backgroundColor: 'var(--bg-main)',
                      overflow: 'hidden',
                    }}
                  >
                    {/* Diff Header */}
                    <div
                      style={{
                        padding: '6px 10px',
                        backgroundColor: 'var(--bg-surface)',
                        borderBottom: '1px solid var(--border-subtle)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                        {activeFileDiff.path}
                      </span>
                      <button
                        onClick={() => handleCopyDiff(activeFileDiff.diff_text)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px',
                          border: 'none',
                          background: 'transparent',
                          color: 'var(--text-secondary)',
                          fontSize: '11px',
                          cursor: 'pointer',
                        }}
                      >
                        {copiedDiff ? <Check size={12} color="var(--color-forest)" /> : <Copy size={12} />}
                        {copiedDiff ? 'Copied' : 'Copy'}
                      </button>
                    </div>

                    {/* Diff Body */}
                    <div
                      style={{
                        flex: 1,
                        padding: '8px',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '11px',
                        lineHeight: '1.45',
                        overflowY: 'auto',
                        whiteSpace: 'pre',
                      }}
                    >
                      {activeFileDiff.is_binary ? (
                        <div style={{ color: 'var(--text-secondary)', fontStyle: 'italic', padding: '12px' }}>
                          [Binary file ({activeFileDiff.size_bytes} bytes) not displayed]
                        </div>
                      ) : activeFileDiff.diff_text ? (
                        activeFileDiff.diff_text.split('\n').map((line, idx) => {
                          const isAdd = line.startsWith('+') && !line.startsWith('+++');
                          const isDel = line.startsWith('-') && !line.startsWith('---');
                          const isHdr = line.startsWith('@@');

                          let bg = 'transparent';
                          let fg = 'var(--text-main)';

                          if (isAdd) {
                            bg = 'rgba(0, 84, 55, 0.12)';
                            fg = 'var(--color-forest)';
                          } else if (isDel) {
                            bg = 'rgba(156, 48, 48, 0.12)';
                            fg = 'var(--text-failure)';
                          } else if (isHdr) {
                            bg = 'rgba(0, 0, 0, 0.04)';
                            fg = 'var(--text-secondary)';
                          }

                          return (
                            <div
                              key={idx}
                              style={{
                                backgroundColor: bg,
                                color: fg,
                                padding: '1px 4px',
                                borderRadius: '2px',
                              }}
                            >
                              {line}
                            </div>
                          );
                        })
                      ) : (
                        <div style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                          No text differences recorded.
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ──────────────────────────────────────────────────────────────────── */}
        {/* TAB 2: CHECKS (Evidence-Driven Verification Results)                 */}
        {/* ──────────────────────────────────────────────────────────────────── */}
        {activeTab === 'checks' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {/* Header & Filter Controls */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
                Verification Gates ({checks.length})
              </div>
              <div style={{ display: 'flex', gap: '4px' }}>
                <button
                  onClick={() => setCheckFilter('all')}
                  style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    border: 'none',
                    backgroundColor: checkFilter === 'all' ? 'var(--color-forest)' : 'transparent',
                    color: checkFilter === 'all' ? '#FFF' : 'var(--text-secondary)',
                    cursor: 'pointer',
                  }}
                >
                  All ({checks.length})
                </button>
                <button
                  onClick={() => setCheckFilter('passed')}
                  style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    border: 'none',
                    backgroundColor: checkFilter === 'passed' ? 'var(--color-forest)' : 'transparent',
                    color: checkFilter === 'passed' ? '#FFF' : 'var(--text-secondary)',
                    cursor: 'pointer',
                  }}
                >
                  Passed ({passedChecksCount})
                </button>
                <button
                  onClick={() => setCheckFilter('failed')}
                  style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    border: 'none',
                    backgroundColor: checkFilter === 'failed' ? 'var(--color-forest)' : 'transparent',
                    color: checkFilter === 'failed' ? '#FFF' : 'var(--text-secondary)',
                    cursor: 'pointer',
                  }}
                >
                  Failed ({failedChecksCount})
                </button>
              </div>
            </div>

            {/* Checks List */}
            {filteredChecks.length === 0 ? (
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', fontStyle: 'italic', padding: '12px 0' }}>
                No verification checks match the current filter.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {filteredChecks.map((check) => {
                  const isExpanded = expandedCheckIds.has(check.check_id);
                  const isPassed = check.status === 'passed';
                  const isFailed = check.status === 'failed';

                  return (
                    <div
                      key={check.check_id}
                      style={{
                        borderRadius: '6px',
                        backgroundColor: isPassed
                          ? 'var(--bg-verified)'
                          : isFailed
                          ? 'var(--bg-failure)'
                          : 'var(--bg-surface)',
                        border: `1px solid ${
                          isFailed ? 'var(--border-failure)' : 'var(--border-subtle)'
                        }`,
                        overflow: 'hidden',
                      }}
                    >
                      {/* Check Item Header */}
                      <div
                        onClick={() => toggleCheckExpand(check.check_id)}
                        style={{
                          padding: '10px 12px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          cursor: 'pointer',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          {isPassed ? (
                            <CheckCircle size={15} color="var(--color-forest)" />
                          ) : isFailed ? (
                            <AlertTriangle size={15} color="var(--text-failure)" />
                          ) : (
                            <Clock size={15} color="var(--text-secondary)" />
                          )}
                          <div style={{ display: 'flex', flexDirection: 'column' }}>
                            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-main)' }}>
                              {check.title}
                            </span>
                            <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                              {check.evidence || (isPassed ? 'Verified' : 'Pending')}
                            </span>
                          </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          {check.exit_code !== undefined && check.exit_code !== null && (
                            <span
                              style={{
                                fontSize: '10px',
                                fontFamily: 'var(--font-mono)',
                                padding: '1px 5px',
                                borderRadius: '3px',
                                backgroundColor: isPassed ? 'rgba(0, 84, 55, 0.15)' : 'rgba(156, 48, 48, 0.15)',
                                color: isPassed ? 'var(--color-forest)' : 'var(--text-failure)',
                                fontWeight: 600,
                              }}
                            >
                              exit {check.exit_code}
                            </span>
                          )}
                          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </div>
                      </div>

                      {/* Expandable Details Accordion */}
                      {isExpanded && (
                        <div
                          style={{
                            padding: '8px 12px 12px',
                            borderTop: '1px solid var(--border-subtle)',
                            backgroundColor: 'rgba(255, 255, 255, 0.6)',
                            fontSize: '11px',
                          }}
                        >
                          {check.command && (
                            <div style={{ marginBottom: '6px' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                                <strong style={{ color: 'var(--text-secondary)' }}>Command:</strong>
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleCopyCommand(check.command!);
                                  }}
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    padding: '2px 6px',
                                    fontSize: '10px',
                                    borderRadius: '4px',
                                    border: '1px solid var(--border-subtle)',
                                    background: 'var(--bg-main)',
                                    color: 'var(--text-main)',
                                    cursor: 'pointer',
                                  }}
                                  title="Copy command to clipboard"
                                >
                                  {copiedCommand === check.command ? (
                                    <>
                                      <Check size={10} color="var(--color-forest)" />
                                      <span style={{ color: 'var(--color-forest)' }}>Copied</span>
                                    </>
                                  ) : (
                                    <>
                                      <Copy size={10} />
                                      <span>Copy</span>
                                    </>
                                  )}
                                </button>
                              </div>
                              <div
                                style={{
                                  marginTop: '2px',
                                  padding: '4px 8px',
                                  borderRadius: '4px',
                                  backgroundColor: 'var(--bg-main)',
                                  fontFamily: 'var(--font-mono)',
                                  border: '1px solid var(--border-subtle)',
                                }}
                              >
                                {check.command}
                              </div>
                            </div>
                          )}

                          {check.output_snippet && (
                            <div style={{ marginBottom: '6px' }}>
                              <strong style={{ color: 'var(--text-secondary)' }}>Output:</strong>
                              <pre
                                style={{
                                  marginTop: '2px',
                                  padding: '6px 8px',
                                  borderRadius: '4px',
                                  backgroundColor: 'var(--bg-main)',
                                  fontFamily: 'var(--font-mono)',
                                  maxHeight: '100px',
                                  overflowY: 'auto',
                                  whiteSpace: 'pre-wrap',
                                  border: '1px solid var(--border-subtle)',
                                  color: isFailed ? 'var(--text-failure)' : 'var(--text-main)',
                                }}
                              >
                                {check.output_snippet}
                              </pre>
                            </div>
                          )}

                          <div style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                            Check ID: <span className="mono">{check.check_id}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* ──────────────────────────────────────────────────────────────────── */}
        {/* TAB 3: OUTCOME (Authoritative Result & Recovery Diagnostics)         */}
        {/* ──────────────────────────────────────────────────────────────────── */}
        {activeTab === 'outcome' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
              Authoritative Mission Result
            </div>

            {!snapshot ? (
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                No active mission outcome recorded.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {/* Authoritative Outcome Hero Box */}
                <div
                  style={{
                    padding: '16px',
                    borderRadius: '8px',
                    backgroundColor:
                      snapshot.status === 'COMPLETED'
                        ? 'var(--bg-verified)'
                        : snapshot.status === 'FAILED'
                        ? 'var(--bg-failure)'
                        : (snapshot.status === 'CANCELLED' || snapshot.status === 'STOPPED')
                        ? 'rgba(217, 119, 6, 0.08)'
                        : 'var(--bg-surface)',
                    border: `1.5px solid ${
                      snapshot.status === 'FAILED'
                        ? 'var(--border-failure)'
                        : snapshot.status === 'COMPLETED'
                        ? 'var(--color-forest)'
                        : (snapshot.status === 'CANCELLED' || snapshot.status === 'STOPPED')
                        ? '#D97706'
                        : 'var(--border-subtle)'
                    }`,
                  }}
                >
                  <div
                    style={{
                      fontSize: '14px',
                      fontWeight: 700,
                      color:
                        snapshot.status === 'FAILED'
                          ? 'var(--text-failure)'
                          : (snapshot.status === 'CANCELLED' || snapshot.status === 'STOPPED')
                          ? '#D97706'
                          : 'var(--color-forest)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    {snapshot.status === 'COMPLETED' && <CheckCircle size={16} />}
                    {snapshot.status === 'FAILED' && <AlertTriangle size={16} />}
                    {(snapshot.status === 'CANCELLED' || snapshot.status === 'STOPPED') && <StopCircle size={16} />}
                    {snapshot.status}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-main)', marginTop: '6px', lineHeight: '1.4' }}>
                    {snapshot.status === 'COMPLETED'
                      ? 'Mission completed and verified against all required acceptance criteria.'
                      : snapshot.status === 'FAILED'
                      ? 'Mission execution failed. Required target criteria or tools did not succeed.'
                      : snapshot.status === 'CANCELLED'
                      ? 'Mission cancelled by operator.'
                      : 'Mission actively running in autonomous runtime harness.'}
                  </div>
                </div>

                {/* Delivered Agent Response Card */}
                {snapshot.final_output && (
                  <div
                    style={{
                      padding: '14px',
                      borderRadius: '8px',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-subtle)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginBottom: '8px',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          color: 'var(--color-forest)',
                          fontWeight: 700,
                          fontSize: '12px',
                        }}
                      >
                        <FileText size={14} />
                        Delivered Agent Response
                      </div>
                      {snapshot.completion_reason && (
                        <span
                          style={{
                            fontSize: '10px',
                            color: 'var(--text-secondary)',
                            backgroundColor: 'rgba(0, 84, 55, 0.08)',
                            padding: '2px 6px',
                            borderRadius: '4px',
                          }}
                        >
                          {snapshot.completion_reason}
                        </span>
                      )}
                    </div>
                    <div
                      style={{
                        fontSize: '12px',
                        color: 'var(--text-main)',
                        whiteSpace: 'pre-wrap',
                        lineHeight: '1.5',
                        backgroundColor: 'var(--bg-main)',
                        padding: '10px',
                        borderRadius: '6px',
                        border: '1px solid var(--border-subtle)',
                        maxHeight: '260px',
                        overflowY: 'auto',
                      }}
                    >
                      {snapshot.final_output}
                    </div>
                  </div>
                )}

                {/* Failure Diagnostic Card */}
                {snapshot.error && (
                  <div
                    style={{
                      padding: '14px',
                      borderRadius: '8px',
                      backgroundColor: 'rgba(156, 48, 48, 0.08)',
                      border: '1px solid var(--border-failure)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginBottom: '6px',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          color: 'var(--text-failure)',
                          fontWeight: 700,
                          fontSize: '12px',
                        }}
                      >
                        <AlertTriangle size={14} />
                        Failure Diagnosis
                      </div>
                      <button
                        onClick={() => handleCopyTraceback(snapshot.error || '')}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px',
                          border: 'none',
                          background: 'transparent',
                          color: 'var(--text-failure)',
                          fontSize: '10px',
                          cursor: 'pointer',
                        }}
                      >
                        {copiedTraceback ? <Check size={12} /> : <Copy size={12} />}
                        {copiedTraceback ? 'Copied' : 'Copy'}
                      </button>
                    </div>

                    <div
                      style={{
                        fontSize: '11px',
                        fontFamily: 'var(--font-mono)',
                        color: 'var(--text-failure)',
                        wordBreak: 'break-all',
                        lineHeight: '1.4',
                      }}
                    >
                      {snapshot.error}
                    </div>

                    {/* Traceback Inspector Toggle */}
                    <div style={{ marginTop: '10px' }}>
                      <button
                        onClick={() => setShowTraceback(!showTraceback)}
                        style={{
                          padding: '4px 8px',
                          borderRadius: '4px',
                          border: '1px solid var(--border-failure)',
                          backgroundColor: 'transparent',
                          color: 'var(--text-failure)',
                          fontSize: '11px',
                          fontWeight: 600,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px',
                        }}
                      >
                        <Terminal size={12} />
                        {showTraceback ? 'Hide Traceback' : 'View Full Traceback'}
                      </button>

                      {showTraceback && (
                        <pre
                          style={{
                            marginTop: '8px',
                            padding: '10px',
                            borderRadius: '4px',
                            backgroundColor: 'var(--bg-main)',
                            border: '1px solid var(--border-failure)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '10px',
                            maxHeight: '180px',
                            overflowY: 'auto',
                            whiteSpace: 'pre-wrap',
                            color: 'var(--text-failure)',
                          }}
                        >
                          {snapshot.error}
                        </pre>
                      )}
                    </div>
                  </div>
                )}

                {/* Waiting / Recovery Status Card */}
                {(snapshot.wait_reason || snapshot.recovery_required) && (
                  <div
                    style={{
                      padding: '12px 14px',
                      borderRadius: '8px',
                      backgroundColor: 'rgba(217, 119, 6, 0.08)',
                      border: '1px solid rgba(217, 119, 6, 0.3)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        color: '#D97706',
                        fontWeight: 700,
                        fontSize: '12px',
                        marginBottom: '4px',
                      }}
                    >
                      <Clock size={14} />
                      Execution Waiting / Recovery
                    </div>
                    {snapshot.wait_reason && (
                      <div style={{ fontSize: '11px', color: 'var(--text-main)', marginTop: '2px' }}>
                        <strong>Reason:</strong> {snapshot.wait_reason}
                      </div>
                    )}
                    {snapshot.recovery_required && (
                      <div style={{ fontSize: '11px', color: '#D97706', marginTop: '2px', fontWeight: 600 }}>
                        Automatic or manual recovery required before continuation.
                      </div>
                    )}
                  </div>
                )}

                {/* Workspace & Execution Controls */}
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '6px' }}>
                  <button
                    onClick={handleCopyWorkspace}
                    style={{
                      flex: 1,
                      padding: '8px 10px',
                      borderRadius: '6px',
                      border: '1px solid var(--border-subtle)',
                      backgroundColor: 'var(--bg-surface)',
                      color: 'var(--text-main)',
                      fontSize: '11px',
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px',
                      cursor: 'pointer',
                    }}
                  >
                    {copiedWsPath ? <Check size={13} color="var(--color-forest)" /> : <Copy size={13} />}
                    {copiedWsPath ? 'Workspace Path Copied' : 'Copy Workspace Path'}
                  </button>

                  {onStopMission && (
                    snapshot.status === 'RUNNING' ||
                    snapshot.status === 'VERIFYING' ||
                    snapshot.is_paused ||
                    snapshot.status === 'WAITING'
                  ) && (
                    <button
                      onClick={onStopMission}
                      disabled={isStopping}
                      style={{
                        padding: '8px 10px',
                        borderRadius: '6px',
                        border: '1px solid var(--border-failure)',
                        backgroundColor: 'var(--bg-failure)',
                        color: 'var(--text-failure)',
                        fontSize: '11px',
                        fontWeight: 600,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        cursor: isStopping ? 'not-allowed' : 'pointer',
                        opacity: isStopping ? 0.7 : 1,
                      }}
                    >
                      <StopCircle size={13} />
                      {isStopping ? 'Stopping…' : 'Stop Mission'}
                    </button>
                  )}
                </div>

                {/* Diagnostic Metadata */}
                <div
                  style={{
                    fontSize: '11px',
                    color: 'var(--text-secondary)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px',
                    paddingTop: '8px',
                    borderTop: '1px solid var(--border-subtle)',
                  }}
                >
                  <div>
                    Mission ID: <span className="mono">{snapshot.mission_id}</span>
                  </div>
                  <div>
                    State Version: <span className="mono">{snapshot.state_version}</span>
                  </div>
                  <div>
                    Last Event Seq: <span className="mono">{snapshot.last_sequence}</span>
                  </div>
                  <div>
                    Workspace: <span className="mono">{snapshot.workspace_root}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
};
