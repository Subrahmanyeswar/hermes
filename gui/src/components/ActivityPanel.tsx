// gui/src/components/ActivityPanel.tsx
import React, { useState } from 'react';
import { Activity, ChevronDown, ChevronUp } from 'lucide-react';
import { HermesEvent } from '../types';

interface ActivityPanelProps {
  events: HermesEvent[];
}

export const ActivityPanel: React.FC<ActivityPanelProps> = ({ events }) => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      style={{
        borderTop: '1px solid var(--border-subtle)',
        backgroundColor: 'var(--bg-chrome)',
        fontSize: '11px',
      }}
    >
      {/* Collapsible Bar */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '6px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          color: 'var(--text-secondary)',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
          <Activity size={12} />
          <span>Activity & Stream Events ({events.length})</span>
        </div>
        <div>{expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}</div>
      </div>

      {/* Expanded Events Drawer */}
      {expanded && (
        <div
          style={{
            maxHeight: '220px',
            overflowY: 'auto',
            padding: '8px 20px',
            backgroundColor: 'var(--bg-surface)',
            borderTop: '1px solid var(--border-subtle)',
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {events.length === 0 ? (
            <div style={{ color: 'var(--text-secondary)', fontStyle: 'italic', padding: '6px 0' }}>
              Waiting for backend execution events...
            </div>
          ) : (
            events.map((e, idx) => {
              const isFailure =
                e.event_type.includes('FAIL') ||
                e.event_type.includes('ERROR') ||
                e.event_type.includes('CANCEL');
              const isSuccess =
                e.event_type.includes('COMPLETED') ||
                e.event_type.includes('PASSED') ||
                e.event_type.includes('ALLOWED');

              let statusColor = 'var(--text-main)';
              if (isFailure) statusColor = 'var(--text-failure)';
              else if (isSuccess) statusColor = 'var(--color-forest)';

              // Format clean descriptive detail
              const p = e.payload || {};
              const detail =
                p.summary ||
                p.reason ||
                p.description ||
                p.error ||
                (p.tool_name ? `Tool: ${p.tool_name}` : '') ||
                (p.target_path ? `Path: ${p.target_path}` : '') ||
                JSON.stringify(p);

              return (
                <div
                  key={`${e.sequence}-${e.event_id || idx}`}
                  style={{
                    display: 'flex',
                    alignItems: 'baseline',
                    gap: '10px',
                    fontSize: '11px',
                    lineHeight: '1.4',
                  }}
                >
                  <span style={{ color: 'var(--text-secondary)', minWidth: '40px' }}>
                    #{e.sequence}
                  </span>
                  <span style={{ fontWeight: 600, color: statusColor, minWidth: '160px' }}>
                    {e.event_type}
                  </span>
                  <span
                    style={{
                      color: 'var(--text-secondary)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      flex: 1,
                    }}
                    title={typeof detail === 'string' ? detail : JSON.stringify(detail)}
                  >
                    {typeof detail === 'string' ? detail : JSON.stringify(detail)}
                  </span>
                  {e.timestamp ? (
                    <span style={{ color: 'var(--text-secondary)', fontSize: '10px' }}>
                      {new Date(e.timestamp * 1000).toLocaleTimeString()}
                    </span>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
};
