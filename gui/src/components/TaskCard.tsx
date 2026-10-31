// gui/src/components/TaskCard.tsx
import React from 'react';
import { CheckCircle2, XCircle, AlertCircle, Clock, ChevronDown, ChevronRight, Cpu, Activity } from 'lucide-react';
import { TaskSnapshot } from '../types';

interface TaskCardProps {
  tasks: TaskSnapshot[];
  isFailed: boolean;
  isCompleted: boolean;
  failureError?: string | null;
  activeTier?: number;
  modelStack?: Record<string, string>;
}

const cleanModelLabel = (raw?: string, fallback: string = ''): string => {
  if (!raw) return fallback;
  const parts = raw.split('/');
  const modelName = parts[parts.length - 1].trim();
  const provider = raw.toLowerCase().includes('zai') ? 'Z.ai' : (raw.toLowerCase().includes('nvidia') ? 'NVIDIA NIM' : (raw.toLowerCase().includes('openrouter') ? 'OpenRouter' : ''));
  return provider ? `${provider} / ${modelName}` : modelName;
};

export const TaskCard: React.FC<TaskCardProps> = ({
  tasks,
  isFailed,
  isCompleted,
  failureError,
  activeTier = 1,
  modelStack,
}) => {
  const [showTrace, setShowTrace] = React.useState(false);

  return (
    <div
      style={{
        backgroundColor: 'var(--bg-surface)',
        borderRadius: '8px',
        border: `1px solid ${isFailed ? 'var(--border-failure)' : 'var(--border-subtle)'}`,
        padding: '16px',
        margin: '16px 0',
      }}
    >
      {/* 3-Tier Model Routing Architecture Ribbon */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '8px',
          padding: '8px 12px',
          borderRadius: '6px',
          backgroundColor: 'rgba(0, 0, 0, 0.04)',
          border: '1px solid var(--border-subtle)',
          marginBottom: '14px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Cpu size={14} color="var(--color-forest)" />
          <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.5px', color: 'var(--text-main)' }}>
            THREE-TIER ROUTING
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' }}>
          <span
            style={{
              padding: '2px 6px',
              borderRadius: '4px',
              backgroundColor: activeTier === 1 ? 'rgba(0, 84, 55, 0.12)' : 'transparent',
              color: activeTier === 1 ? 'var(--color-forest)' : 'var(--text-secondary)',
              fontWeight: activeTier === 1 ? 700 : 500,
              border: activeTier === 1 ? '1px solid var(--color-forest)' : '1px solid transparent',
            }}
          >
            T1: {cleanModelLabel(modelStack?.tier1, 'Z.ai GLM-4.7-Flash')}
          </span>
          <span style={{ color: 'var(--text-secondary)' }}>&rarr;</span>
          <span
            style={{
              padding: '2px 6px',
              borderRadius: '4px',
              backgroundColor: activeTier === 2 ? 'rgba(217, 119, 6, 0.12)' : 'transparent',
              color: activeTier === 2 ? '#D97706' : 'var(--text-secondary)',
              fontWeight: activeTier === 2 ? 700 : 500,
              border: activeTier === 2 ? '1px solid #D97706' : '1px solid transparent',
            }}
          >
            T2: {cleanModelLabel(modelStack?.tier2, 'NVIDIA NIM MiniMax M3.1 Flash')}
          </span>
          <span style={{ color: 'var(--text-secondary)' }}>&rarr;</span>
          <span
            style={{
              padding: '2px 6px',
              borderRadius: '4px',
              backgroundColor: activeTier === 3 ? 'rgba(220, 38, 38, 0.12)' : 'transparent',
              color: activeTier === 3 ? '#DC2626' : 'var(--text-secondary)',
              fontWeight: activeTier === 3 ? 700 : 500,
              border: activeTier === 3 ? '1px solid #DC2626' : '1px solid transparent',
            }}
          >
            T3: {cleanModelLabel(modelStack?.tier3, 'OpenRouter Kimi K2.6 Free')}
          </span>
        </div>
      </div>

      {/* Header Distinction: PLAN · ATTEMPTED vs CHECKS · EVIDENCE */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--border-subtle)',
          paddingBottom: '10px',
          marginBottom: '12px',
        }}
      >
        <div style={{ display: 'flex', gap: '16px' }}>
          <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.6px', color: 'var(--color-forest)' }}>
            PLAN · ATTEMPTED ({tasks.length})
          </span>
          <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.6px', color: 'var(--text-secondary)' }}>
            CHECKS · EVIDENCE
          </span>
        </div>

        <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>
          {isCompleted ? 'All Steps Verified' : isFailed ? 'Execution Blocked' : 'Progressing...'}
        </div>
      </div>

      {/* Task List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {tasks.length === 0 ? (
          <div style={{ fontSize: '13px', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
            Preparing initial plan decomposition...
          </div>
        ) : (
          tasks.map((t, idx) => {
            const isTaskDone = t.status === 'COMPLETED';
            const isTaskFailed = t.status === 'FAILED';
            const isTaskRunning = t.status === 'RUNNING';
            return (
              <div
                key={t.task_id || idx}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '10px',
                  padding: '8px 10px',
                  borderRadius: '5px',
                  backgroundColor: isTaskFailed
                    ? 'var(--bg-failure)'
                    : isTaskDone && t.is_verified
                    ? 'var(--bg-verified)'
                    : isTaskRunning
                    ? 'rgba(0, 84, 55, 0.08)'
                    : 'rgba(255, 255, 255, 0.4)',
                  border: isTaskRunning ? '1px solid var(--color-forest)' : '1px solid transparent',
                }}
              >
                <div style={{ marginTop: '2px' }}>
                  {isTaskDone && t.is_verified ? (
                    <CheckCircle2 size={16} color="var(--color-forest)" />
                  ) : isTaskFailed ? (
                    <XCircle size={16} color="var(--text-failure)" />
                  ) : isTaskRunning ? (
                    <Activity size={16} color="var(--color-forest)" className="spin-slow" />
                  ) : (
                    <Clock size={16} color="var(--text-secondary)" />
                  )}
                </div>

                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: isTaskFailed ? 'var(--text-failure)' : 'var(--text-main)' }}>
                      {t.title}
                    </div>
                    {isTaskRunning && (
                      <span
                        style={{
                          fontSize: '10px',
                          fontWeight: 700,
                          padding: '1px 6px',
                          borderRadius: '4px',
                          backgroundColor: 'var(--color-forest)',
                          color: '#FFFFFF',
                          letterSpacing: '0.4px',
                        }}
                      >
                        RUNNING
                      </span>
                    )}
                  </div>
                  {t.description && (
                    <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      {t.description}
                    </div>
                  )}
                  {t.verification_evidence && (
                    <div
                      style={{
                        fontSize: '11px',
                        color: 'var(--color-forest)',
                        marginTop: '4px',
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      ✓ {t.verification_evidence}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Campus Lab Manager Acceptance Reference: The Essential Failure Frame */}
      {isFailed && failureError && (
        <div
          style={{
            marginTop: '14px',
            padding: '12px 14px',
            backgroundColor: 'var(--bg-failure)',
            borderRadius: '6px',
            border: '1px solid var(--border-failure)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-failure)', fontWeight: 700, fontSize: '12px' }}>
            <AlertCircle size={16} />
            <span>Mission Execution Terminated</span>
          </div>

          <div
            style={{
              fontSize: '13px',
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              color: 'var(--text-failure)',
              margin: '8px 0 4px 0',
            }}
          >
            {failureError}
          </div>

          <div style={{ fontSize: '11px', color: 'var(--text-failure)', marginBottom: '8px' }}>
            This blocks mission completion. Review execution details and terminal reason below.
          </div>

          <button
            onClick={() => setShowTrace(!showTrace)}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-failure)',
              fontSize: '11px',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              padding: 0,
            }}
          >
            {showTrace ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {showTrace ? 'Hide Traceback' : 'View Traceback'}
          </button>

          {showTrace && (
            <pre
              style={{
                marginTop: '8px',
                padding: '8px',
                backgroundColor: 'rgba(0, 0, 0, 0.05)',
                borderRadius: '4px',
                fontSize: '11px',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-failure)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {failureError}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};
