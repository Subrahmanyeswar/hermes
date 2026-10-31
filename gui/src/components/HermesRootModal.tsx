// gui/src/components/HermesRootModal.tsx
import React from 'react';
import { AlertTriangle, X, ShieldAlert } from 'lucide-react';

interface HermesRootModalProps {
  isOpen: boolean;
  workspacePath: string;
  pendingPrompt: string;
  onConfirm: () => void;
  onCancel: () => void;
  onOpenFolderDialog?: () => void;
}

export const HermesRootModal: React.FC<HermesRootModalProps> = ({
  isOpen,
  workspacePath,
  pendingPrompt,
  onConfirm,
  onCancel,
  onOpenFolderDialog,
}) => {
  if (!isOpen) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.55)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        style={{
          width: '520px',
          maxWidth: '90vw',
          backgroundColor: 'var(--bg-chrome)',
          borderRadius: '10px',
          border: '1px solid #F59E0B',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.1)',
          overflow: 'hidden',
          animation: 'fadeIn 0.15s ease-out',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            backgroundColor: '#FEF3C7',
            borderBottom: '1px solid #FDE68A',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <AlertTriangle size={20} color="#D97706" />
            <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: '#92400E' }}>
              Protected HERMES Repository Warning
            </h3>
          </div>
          <button
            onClick={onCancel}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: '#92400E',
              display: 'flex',
              padding: '2px',
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ fontSize: '13px', color: 'var(--text-main)', lineHeight: '1.5' }}>
            The current active project is <strong>HERMES itself</strong> (the agent harness repository):
          </div>

          <div
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '6px',
              padding: '8px 12px',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-main)',
              wordBreak: 'break-all',
            }}
          >
            {workspacePath}
          </div>

          <div
            style={{
              display: 'flex',
              gap: '10px',
              backgroundColor: '#FFFBEB',
              border: '1px solid #FDE68A',
              borderRadius: '6px',
              padding: '10px 12px',
              fontSize: '12px',
              color: '#92400E',
              lineHeight: '1.4',
            }}
          >
            <ShieldAlert size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
            <div>
              Executing coding tasks directly against the HERMES runtime codebase may alter agent core files, test suites, or runtime state.
              To develop an external project, click <strong>Cancel</strong> and choose <strong>Open Project</strong> to pick your target repository.
            </div>
          </div>

          {pendingPrompt && (
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              <strong>Task Prompt:</strong> &quot;{pendingPrompt.slice(0, 100)}{pendingPrompt.length > 100 ? '…' : ''}&quot;
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '14px 20px',
            backgroundColor: 'var(--bg-surface)',
            borderTop: '1px solid var(--border-subtle)',
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '10px',
          }}
        >
          {onOpenFolderDialog && (
            <button
              onClick={() => {
                onCancel();
                onOpenFolderDialog();
              }}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'var(--bg-chrome)',
                fontSize: '13px',
                fontWeight: 600,
                color: 'var(--color-forest)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              Open Other Project
            </button>
          )}

          <button
            onClick={onCancel}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: '1px solid var(--border-subtle)',
              backgroundColor: 'transparent',
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--text-main)',
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>

          <button
            onClick={onConfirm}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: '#D97706',
              fontSize: '13px',
              fontWeight: 600,
              color: '#FFFFFF',
              cursor: 'pointer',
            }}
          >
            Proceed Against HERMES Root
          </button>
        </div>
      </div>
    </div>
  );
};
