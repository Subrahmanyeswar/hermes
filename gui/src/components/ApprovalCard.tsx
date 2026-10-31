// gui/src/components/ApprovalCard.tsx
import React, { useState } from 'react';
import { ShieldAlert, Check, X, ShieldCheck } from 'lucide-react';
import { PendingApprovalItem } from '../types';

interface ApprovalCardProps {
  approvals: PendingApprovalItem[];
  onResolve: (requestId: string, approved: boolean, scope: string) => Promise<void>;
}

export const ApprovalCard: React.FC<ApprovalCardProps> = ({ approvals, onResolve }) => {
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  if (!approvals || approvals.length === 0) {
    return null;
  }

  const handleAction = async (requestId: string, approved: boolean, scope: string) => {
    setResolvingId(requestId);
    try {
      await onResolve(requestId, approved, scope);
    } catch (err) {
      console.error('Error resolving approval:', err);
    } finally {
      setResolvingId(null);
    }
  };

  return (
    <div
      style={{
        margin: '16px 0',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
      }}
    >
      {approvals.map((req) => (
        <div
          key={req.request_id}
          style={{
            padding: '16px 18px',
            borderRadius: '8px',
            backgroundColor: 'rgba(222, 186, 214, 0.15)', // Soft Orchid Lilac background
            border: '2px solid var(--color-forest)',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)',
          }}
        >
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ShieldAlert size={18} color="var(--color-forest)" />
              <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-forest)', textTransform: 'uppercase' }}>
                Protected Action Requires Approval
              </span>
            </div>
            <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
              {req.mission_id && (
                <span
                  style={{
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    backgroundColor: 'rgba(0, 84, 55, 0.1)',
                    color: 'var(--color-forest)',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    fontWeight: 600,
                  }}
                >
                  {req.mission_id}
                </span>
              )}
              <span
                style={{
                  fontSize: '11px',
                  fontFamily: 'var(--font-mono)',
                  backgroundColor: 'var(--bg-surface)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                {req.request_id}
              </span>
            </div>
          </div>

          {/* Tool & Arguments */}
          <div style={{ fontSize: '13px', color: 'var(--text-main)', marginBottom: '6px' }}>
            <strong>Tool:</strong> <code style={{ backgroundColor: 'rgba(0,0,0,0.05)', padding: '2px 6px', borderRadius: '4px' }}>{req.tool_name}</code>
          </div>

          <div
            style={{
              padding: '8px 12px',
              borderRadius: '6px',
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              maxHeight: '120px',
              overflowY: 'auto',
              marginBottom: '10px',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}
          >
            {JSON.stringify(req.arguments, null, 2)}
          </div>

          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '14px' }}>
            <strong>Risk Rationale:</strong> {req.reason}
          </div>

          {/* Action Buttons */}
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <button
              onClick={() => handleAction(req.request_id, true, 'ONCE')}
              disabled={resolvingId === req.request_id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                borderRadius: '6px',
                border: 'none',
                backgroundColor: 'var(--color-forest)',
                color: '#FFF',
                fontWeight: 600,
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              <Check size={14} />
              Approve Once
            </button>

            <button
              onClick={() => handleAction(req.request_id, true, 'SESSION')}
              disabled={resolvingId === req.request_id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                borderRadius: '6px',
                border: '1px solid var(--color-forest)',
                backgroundColor: 'transparent',
                color: 'var(--color-forest)',
                fontWeight: 600,
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              <ShieldCheck size={14} />
              Approve Session
            </button>

            <button
              onClick={() => handleAction(req.request_id, false, 'ONCE')}
              disabled={resolvingId === req.request_id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                borderRadius: '6px',
                border: '1px solid var(--border-failure)',
                backgroundColor: 'var(--bg-failure)',
                color: 'var(--text-failure)',
                fontWeight: 600,
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              <X size={14} />
              Deny
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};
