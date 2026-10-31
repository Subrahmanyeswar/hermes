// gui/src/components/Composer.tsx
import React, { useState, useRef, useEffect, KeyboardEvent } from 'react';
import { Send, Square } from 'lucide-react';

interface ComposerProps {
  onSend: (prompt: string) => void;
  onStop: () => void;
  isRunning: boolean;
  isStopping: boolean;
  isPaused?: boolean;
  waitReason?: string | null;
  disabled: boolean;
}

export const Composer: React.FC<ComposerProps> = ({
  onSend,
  onStop,
  isRunning,
  isStopping,
  isPaused,
  waitReason,
  disabled,
}) => {
  const [prompt, setPrompt] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-expand textarea up to approximately 220px, then allow vertical scrolling
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const nextHeight = Math.min(el.scrollHeight, 220);
    el.style.height = `${Math.max(nextHeight, 40)}px`;
    el.style.overflowY = el.scrollHeight > 220 ? 'auto' : 'hidden';
  }, [prompt]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = () => {
    const trimmed = prompt.trim();
    if (!trimmed || disabled || isRunning || isPaused) return;
    onSend(trimmed);
    setPrompt('');
  };

  const isInputDisabled = disabled || isRunning || !!isPaused;

  let placeholderText = 'Enter a task or instruction for HERMES... (Press Enter to send, Shift+Enter for new line)';
  if (isPaused) {
    placeholderText = 'Mission is paused. Click Stop to cancel.';
  } else if (waitReason) {
    placeholderText = `Mission waiting (${waitReason}). Click Stop to cancel.`;
  } else if (isRunning) {
    placeholderText = 'Mission is running... Click Stop to cancel execution.';
  }

  return (
    <div
      style={{
        padding: '12px 20px',
        backgroundColor: 'var(--bg-chrome)',
        borderTop: '1px solid var(--border-subtle)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: '10px',
          backgroundColor: 'var(--bg-surface)',
          borderRadius: '8px',
          border: '1px solid var(--border-subtle)',
          padding: '8px 12px',
        }}
      >
        <textarea
          ref={textareaRef}
          rows={2}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isInputDisabled}
          placeholder={placeholderText}
          style={{
            flex: 1,
            border: 'none',
            background: 'transparent',
            outline: 'none',
            resize: 'none',
            fontFamily: 'var(--font-family)',
            fontSize: '13px',
            color: 'var(--text-main)',
            lineHeight: '1.4',
            maxHeight: '220px',
            minHeight: '40px',
            boxSizing: 'border-box',
          }}
        />

        {/* Action Controls: Running, Paused, Waiting/Recovery, or Idle/Send */}
        {isPaused || (waitReason && !isRunning) ? (
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              onClick={onStop}
              disabled={isStopping}
              title="Request mission cancellation"
              style={{
                height: '34px',
                padding: '0 14px',
                backgroundColor: 'var(--text-failure)',
                color: '#FFFFFF',
                border: 'none',
                borderRadius: '6px',
                fontWeight: 600,
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                cursor: isStopping ? 'not-allowed' : 'pointer',
                opacity: isStopping ? 0.7 : 1,
              }}
              className="transition-fast"
            >
              <Square size={13} fill="#FFFFFF" />
              {isStopping ? 'Stopping…' : 'Stop'}
            </button>
          </div>
        ) : isRunning ? (
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              onClick={onStop}
              disabled={isStopping}
              title="Request mission cancellation"
              style={{
                height: '34px',
                padding: '0 14px',
                backgroundColor: 'var(--text-failure)',
                color: '#FFFFFF',
                border: 'none',
                borderRadius: '6px',
                fontWeight: 600,
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                cursor: isStopping ? 'not-allowed' : 'pointer',
                opacity: isStopping ? 0.7 : 1,
              }}
              className="transition-fast"
            >
              <Square size={13} fill="#FFFFFF" />
              {isStopping ? 'Stopping…' : 'Stop'}
            </button>
          </div>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!prompt.trim() || disabled}
            title="Submit task"
            style={{
              height: '34px',
              padding: '0 16px',
              backgroundColor: 'var(--color-forest)',
              color: '#FFFFFF',
              border: 'none',
              borderRadius: '6px',
              fontWeight: 600,
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: !prompt.trim() || disabled ? 'not-allowed' : 'pointer',
              opacity: !prompt.trim() || disabled ? 0.5 : 1,
            }}
            className="transition-fast"
          >
            <Send size={13} />
            Send
          </button>
        )}
      </div>
    </div>
  );
};
