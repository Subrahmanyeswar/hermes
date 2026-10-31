// gui/src/components/TopBar.tsx
import React from 'react';
import { Shield, Wifi, WifiOff, Folder, AlertTriangle, ArrowRightLeft } from 'lucide-react';

interface TopBarProps {
  workspaceName: string;
  workspacePath: string;
  isHermesRepo: boolean;
  backendConnected: boolean;
  missionStatus: string;
  waitReason?: string | null;
  isPaused?: boolean;
  pausePending?: boolean;
  onOpenFolderDialog: () => void;
  isOpeningFolder?: boolean;
  onCopyPath: () => void;
  copied: boolean;
  codeMatch?: boolean;
}

export const TopBar: React.FC<TopBarProps> = ({
  workspaceName,
  workspacePath,
  isHermesRepo,
  backendConnected,
  missionStatus,
  waitReason,
  isPaused,
  pausePending,
  onOpenFolderDialog,
  isOpeningFolder = false,
  onCopyPath,
  copied,
  codeMatch,
}) => {
  return (
    <header
      className="topbar-container"
      style={{
        height: '52px',
        backgroundColor: 'var(--bg-chrome)',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        userSelect: 'none',
      }}
    >
      {/* Brand Identity & Active Project Info */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div
            style={{
              width: '28px',
              height: '28px',
              borderRadius: '6px',
              backgroundColor: 'var(--color-forest)',
              color: '#FFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              fontSize: '14px',
              letterSpacing: '0.5px',
            }}
          >
            H
          </div>
          <span
            style={{
              fontWeight: 700,
              fontSize: '15px',
              letterSpacing: '0.8px',
              color: 'var(--color-forest)',
            }}
          >
            HERMES
          </span>
        </div>

        <div style={{ width: '1px', height: '20px', backgroundColor: 'var(--border-subtle)' }} />

        {/* Project Selector Badge & Path Display */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '6px',
              padding: '3px 8px',
            }}
          >
            <Folder size={13} color="var(--color-forest)" />
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)' }}>
              {workspaceName || 'No Project'}
            </span>
            {isHermesRepo && (
              <span
                title="HERMES Runtime Repository — tasks here require confirmation guard"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '3px',
                  backgroundColor: '#FEF3C7',
                  color: '#92400E',
                  borderRadius: '4px',
                  padding: '1px 5px',
                  fontSize: '10px',
                  fontWeight: 700,
                }}
              >
                <AlertTriangle size={10} color="#D97706" />
                HERMES ROOT
              </span>
            )}
            <button
              onClick={onOpenFolderDialog}
              disabled={isOpeningFolder}
              title={isOpeningFolder ? "Windows folder picker is open..." : "Switch project folder"}
              style={{
                marginLeft: '4px',
                background: 'transparent',
                border: 'none',
                color: isOpeningFolder ? 'var(--text-disabled)' : 'var(--text-secondary)',
                cursor: isOpeningFolder ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                padding: '2px',
              }}
            >
              <ArrowRightLeft size={12} />
            </button>
          </div>

          <button
            className="topbar-path-btn"
            onClick={onCopyPath}
            title="Click to copy absolute project path"
            style={{
              background: 'rgba(0, 84, 55, 0.06)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '4px',
              padding: '3px 8px',
              fontSize: '11px',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontFamily: 'var(--font-mono)',
              maxWidth: '360px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {copied ? '✓ Copied!' : workspacePath || '...'}
          </button>
        </div>
      </div>

      {/* Right Controls: Fixed AUTO Indicator, Status, Connectivity */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        {/* Mandatory Fixed Non-interactive AUTO Indicator */}
        <div
          title="Autonomous execution mode (governed by internal safety invariants)"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '3px 9px',
            borderRadius: '4px',
            backgroundColor: 'var(--color-forest)',
            color: '#FFFFFF',
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.6px',
          }}
        >
          <Shield size={12} strokeWidth={2.5} />
          AUTO
        </div>

        {/* Real Mission Status Indicator */}
        {(() => {
          const displayStatus = isPaused
            ? 'PAUSED'
            : pausePending
            ? 'PAUSE PENDING'
            : waitReason
            ? `WAITING (${waitReason})`
            : missionStatus;

          if (!displayStatus || displayStatus === 'IDLE') return null;

          const isWarning =
            displayStatus.includes('PAUSED') ||
            displayStatus.includes('WAITING') ||
            displayStatus === 'CANCELLED' ||
            displayStatus === 'STOPPED';

          return (
            <div
              style={{
                padding: '3px 8px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.4px',
                backgroundColor:
                  displayStatus === 'COMPLETED'
                    ? 'var(--bg-verified)'
                    : displayStatus === 'FAILED'
                    ? 'var(--bg-failure)'
                    : isWarning
                    ? 'rgba(217, 119, 6, 0.12)'
                    : 'var(--bg-selected)',
                color:
                  displayStatus === 'COMPLETED'
                    ? 'var(--text-verified)'
                    : displayStatus === 'FAILED'
                    ? 'var(--text-failure)'
                    : isWarning
                    ? '#D97706'
                    : 'var(--color-forest)',
              }}
            >
              {displayStatus}
            </div>
          );
        })()}

        {/* Runtime Sync State */}
        {codeMatch === false && (
          <div
            title="Running server memory does not match disk code. Restart server."
            style={{
              padding: '2px 6px',
              borderRadius: '4px',
              fontSize: '10px',
              fontWeight: 700,
              backgroundColor: 'rgba(217, 119, 6, 0.15)',
              color: '#D97706',
              border: '1px solid #D97706',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <AlertTriangle size={11} />
            STALE RUNTIME
          </div>
        )}
        {codeMatch === true && (
          <div
            title="Running server code matches on-disk code."
            style={{
              padding: '2px 6px',
              borderRadius: '4px',
              fontSize: '10px',
              fontWeight: 600,
              backgroundColor: 'rgba(0, 84, 55, 0.08)',
              color: 'var(--color-forest)',
            }}
          >
            ✓ SYNCED
          </div>
        )}

        {/* Backend Connection State */}
        <div
          title={backendConnected ? 'Connected to local runtime' : 'Backend unavailable'}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            fontSize: '11px',
            color: backendConnected ? 'var(--color-forest)' : 'var(--text-failure)',
          }}
        >
          {backendConnected ? <Wifi size={14} /> : <WifiOff size={14} />}
          <span className="topbar-desktop-only">{backendConnected ? '127.0.0.1:8765' : 'Offline'}</span>
        </div>
      </div>
    </header>
  );
};
