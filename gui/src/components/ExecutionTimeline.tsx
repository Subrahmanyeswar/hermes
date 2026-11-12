// gui/src/components/ExecutionTimeline.tsx
import React, { useState } from 'react';
import {
  ChevronRight,
  ChevronDown,
  Terminal,
  FileText,
  FilePlus,
  FileEdit,
  Search,
  Globe,
  Cpu,
  AlertTriangle,
  CheckCircle2,
  Copy,
  Check,
  Flag,
  Image as ImageIcon,
  Download,
  Compass,
  Layers,
  ExternalLink,
} from 'lucide-react';
import { HermesEvent } from '../types';

export interface ExecutionTimelineProps {
  events: HermesEvent[];
  isRunning?: boolean;
}

interface TimelineStep {
  id: string;
  type:
    | 'thought'
    | 'command'
    | 'file_read'
    | 'file_write'
    | 'file_edit'
    | 'search'
    | 'browser'
    | 'failover'
    | 'verification'
    | 'mission_complete'
    | 'web_search'
    | 'web_fetch'
    | 'web_crawl'
    | 'image_search'
    | 'image_download'
    | 'research_bundle'
    | 'other';
  headline: string;
  status: 'running' | 'completed' | 'failed';
  timestamp?: number;
  durationMs?: number;
  model?: string;
  provider?: string;
  tier?: number;
  diffStat?: { added: number; deleted: number; is_new?: boolean };
  exitCode?: number;
  targetPath?: string;
  command?: string;
  details?: any;
  outputPreview?: string;
  rawError?: string;
  metadata?: any;
}

const getFallbackHeadline = (
  toolName: string,
  targetPath?: string,
  argsSummary?: string,
  isCompleted = true,
  success = true
): string => {
  const tn = (toolName || '').toLowerCase();
  const file = targetPath ? targetPath.split(/[/\\]/).pop() : '';
  if (tn.includes('shell') || tn.includes('bash') || tn.includes('command')) {
    const cmd = argsSummary ? argsSummary.replace(/^['"{]|['"}]$/g, '').slice(0, 50) : '';
    return cmd ? `Ran ${cmd}` : 'Ran shell command';
  }
  if (tn.includes('read') || tn.includes('view') || tn.includes('cat')) {
    return file ? `Analyzed ${file}` : 'Analyzed file';
  }
  if (tn.includes('write') || tn.includes('create')) {
    return file ? `Created ${file}` : 'Created file';
  }
  if (tn.includes('edit') || tn.includes('replace') || tn.includes('patch')) {
    return file ? `Modified ${file}` : 'Modified file';
  }
  if (tn.includes('glob') || tn.includes('search') || tn.includes('grep')) {
    return file ? `Searched in ${file}` : 'Searched files';
  }
  if (tn.includes('browser') || tn.includes('preview')) {
    return 'Browser evaluation';
  }
  return isCompleted ? (success ? `Executed ${toolName}` : `Failed ${toolName}`) : `Running ${toolName}...`;
};

export const ExecutionTimeline: React.FC<ExecutionTimelineProps> = ({ events, isRunning }) => {
  const [expandedSteps, setExpandedSteps] = useState<Record<string, boolean>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const toggleExpand = (id: string) => {
    setExpandedSteps((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1800);
  };

  // ── Process chronological stream into discrete Antigravity micro-steps ─────
  const steps: TimelineStep[] = [];
  const openToolMap = new Map<string, TimelineStep>();

  for (const ev of events) {
    const et = ev.event_type;
    const p = ev.payload || {};

    if (et === 'MODEL_REQUESTED') {
      const stepId = `thought_${ev.sequence || ev.event_id || steps.length}`;
      const step: TimelineStep = {
        id: stepId,
        type: 'thought',
        headline: 'Thinking...',
        status: 'running',
        timestamp: ev.timestamp,
        model: p.model || 'nvidia/nemotron-3.5-super-vl-120b-a12b',
        tier: p.tier || 1,
      };
      steps.push(step);
    } else if (et === 'MODEL_COMPLETED') {
      let lastThought = [...steps].reverse().find((s) => s.type === 'thought' && s.status === 'running');
      if (!lastThought) {
        const recentThought = [...steps].reverse().find((s) => s.type === 'thought');
        const durSec = p.latency ? p.latency.toFixed(1) : ((p.duration_ms || 0) / 1000).toFixed(1);
        const headlineCandidate = p.headline || `Thought for ${durSec}s`;
        if (
          recentThought &&
          (recentThought.headline === headlineCandidate ||
            Math.abs(new Date(ev.timestamp || Date.now()).getTime() - new Date(recentThought.timestamp || Date.now()).getTime()) < 3000)
        ) {
          lastThought = recentThought;
        } else {
          lastThought = {
            id: `thought_${ev.sequence || ev.event_id || steps.length}`,
            type: 'thought',
            headline: '',
            status: 'completed',
            timestamp: ev.timestamp,
          };
          steps.push(lastThought);
        }
      }
      const durSec = p.latency ? p.latency.toFixed(1) : ((p.duration_ms || 0) / 1000).toFixed(1);
      lastThought.status = 'completed';
      lastThought.headline = p.headline || `Thought for ${durSec}s`;
      lastThought.durationMs = p.duration_ms || Math.round((p.latency || 0) * 1000);
      lastThought.model = p.model || lastThought.model || 'nvidia/nemotron-3.5-super-vl-120b-a12b';
      lastThought.tier = p.tier || lastThought.tier || 1;
    } else if (et === 'TIER_FAILOVER_STARTED') {
      const stepId = `failover_${ev.sequence || ev.event_id || steps.length}`;
      steps.push({
        id: stepId,
        type: 'failover',
        headline: p.headline || `Failover: Tier ${p.from_tier || 1} -> Tier ${p.to_tier || 2}`,
        status: 'failed',
        timestamp: ev.timestamp,
        rawError: p.error || 'Model timeout or provider outage',
      });
    } else if (et === 'TOOL_STARTED') {
      const opKey = p.operation_id || p.tool_call_id || (ev as any).tool_call_id || p.action_id || `tool_${ev.sequence}`;
      const toolName = (p.tool_name || '').toLowerCase();
      let stepType: TimelineStep['type'] = 'other';
      if (toolName.includes('shell') || toolName.includes('bash') || toolName.includes('command')) {
        stepType = 'command';
      } else if (toolName.includes('image_search') || toolName.includes('search_image')) {
        stepType = 'image_search';
      } else if (toolName.includes('download_image') || toolName.includes('fetch_image') || toolName.includes('save_image')) {
        stepType = 'image_download';
      } else if (toolName.includes('web_search') || toolName.includes('search_web')) {
        stepType = 'web_search';
      } else if (toolName.includes('web_fetch') || toolName.includes('fetch_web')) {
        stepType = 'web_fetch';
      } else if (toolName.includes('web_crawl') || toolName.includes('crawl_web')) {
        stepType = 'web_crawl';
      } else if (toolName.includes('deep_web_research') || toolName.includes('deep_research') || toolName.includes('web_research')) {
        stepType = 'research_bundle';
      } else if (toolName.includes('read') || toolName.includes('view') || toolName.includes('cat')) {
        stepType = 'file_read';
      } else if (toolName.includes('write') || toolName.includes('create')) {
        stepType = 'file_write';
      } else if (toolName.includes('edit') || toolName.includes('replace') || toolName.includes('patch')) {
        stepType = 'file_edit';
      } else if (toolName.includes('search') || toolName.includes('glob') || toolName.includes('grep')) {
        stepType = 'search';
      } else if (toolName.includes('browser') || toolName.includes('preview')) {
        stepType = 'browser';
      }

      const initialHeadline = p.headline || getFallbackHeadline(p.tool_name, p.target_path, p.arguments_summary, false);
      const step: TimelineStep = {
        id: `op_${opKey}`,
        type: stepType,
        headline: initialHeadline,
        status: 'running',
        timestamp: ev.timestamp,
        targetPath: p.target_path,
        command: (p.arguments && p.arguments.command) || (p.arguments_summary || ''),
        diffStat: p.diff_stat,
        metadata: p.metadata,
      };
      openToolMap.set(opKey, step);
      steps.push(step);
    } else if (et === 'TOOL_COMPLETED' || et === 'TOOL_FAILED') {
      const opKey = p.operation_id || p.tool_call_id || (ev as any).tool_call_id || p.action_id || `tool_${ev.sequence}`;
      let step = openToolMap.get(opKey);
      if (!step) {
        step = [...steps].reverse().find((s) => s.status === 'running' && s.type !== 'thought');
      }
      if (!step) {
        step = {
          id: `op_${opKey}`,
          type: 'other',
          headline: '',
          status: et === 'TOOL_COMPLETED' ? 'completed' : 'failed',
          timestamp: ev.timestamp,
        };
        steps.push(step);
      }

      const isSuccess = et === 'TOOL_COMPLETED' && p.success !== false;
      step.status = isSuccess ? 'completed' : 'failed';
      const tn = (p.tool_name || step.type || '').toLowerCase();
      if (tn.includes('image_search') || tn.includes('search_image')) step.type = 'image_search';
      else if (tn.includes('download_image') || tn.includes('fetch_image')) step.type = 'image_download';
      else if (tn.includes('web_search') || tn.includes('search_web')) step.type = 'web_search';
      else if (tn.includes('web_fetch') || tn.includes('fetch_web')) step.type = 'web_fetch';
      else if (tn.includes('web_crawl') || tn.includes('crawl_web')) step.type = 'web_crawl';
      else if (tn.includes('deep_web_research') || tn.includes('deep_research')) step.type = 'research_bundle';

      const targetP = p.target_path || step.targetPath;
      const argsSum = p.arguments_summary || step.command;
      const fallback = getFallbackHeadline(tn, targetP, argsSum, true, isSuccess);
      step.headline = p.headline || fallback;
      step.durationMs = p.duration_ms || Math.round((p.duration || 0) * 1000);
      step.exitCode = p.exit_code;
      step.diffStat = p.diff_stat || step.diffStat;
      step.targetPath = targetP;
      step.metadata = p.metadata || step.metadata;
      step.outputPreview = p.output_preview || p.summary || (typeof p.details === 'string' ? p.details : '');
      if (p.error) step.rawError = p.error;
      openToolMap.delete(opKey);
    } else if (
      et === 'IMAGE_SEARCH_COMPLETED' ||
      et === 'WEB_SEARCH_COMPLETED' ||
      et === 'IMAGE_DOWNLOAD_COMPLETED' ||
      et === 'RESEARCH_BUNDLE_COMPLETED' ||
      et === 'WEB_FETCH_COMPLETED' ||
      et === 'WEB_CRAWL_COMPLETED'
    ) {
      const opKey = p.operation_id || `ev_${ev.sequence || ev.event_id || steps.length}`;
      let step = openToolMap.get(opKey) || [...steps].reverse().find((s) => s.id === `op_${opKey}`);
      if (step) {
        step.metadata = p.metadata || step.metadata;
        if (p.headline) step.headline = p.headline;
        if (et === 'IMAGE_SEARCH_COMPLETED') step.type = 'image_search';
        else if (et === 'IMAGE_DOWNLOAD_COMPLETED') step.type = 'image_download';
        else if (et === 'WEB_SEARCH_COMPLETED') step.type = 'web_search';
        else if (et === 'WEB_FETCH_COMPLETED') step.type = 'web_fetch';
        else if (et === 'WEB_CRAWL_COMPLETED') step.type = 'web_crawl';
        else if (et === 'RESEARCH_BUNDLE_COMPLETED') step.type = 'research_bundle';
      }
    } else if (et === 'VERIFICATION_COMPLETED') {
      const stepId = `verif_${ev.sequence || ev.event_id || steps.length}`;
      steps.push({
        id: stepId,
        type: 'verification',
        headline: p.headline || (p.reason ? `Verified: ${p.reason}` : 'Verified acceptance criteria'),
        status: p.verdict === 'FAILED' ? 'failed' : 'completed',
        timestamp: ev.timestamp,
        outputPreview: p.reason || p.verdict || 'All criteria verified.',
      });
    } else if (et === 'MISSION_COMPLETED') {
      const stepId = `mission_done_${ev.sequence || ev.event_id || steps.length}`;
      steps.push({
        id: stepId,
        type: 'mission_complete',
        headline: p.headline || 'Mission completed successfully',
        status: 'completed',
        timestamp: ev.timestamp,
        outputPreview: p.reason || p.final_output || 'All tasks completed.',
      });
    }
  }

  if (steps.length === 0 && !isRunning) {
    return null;
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        marginTop: '12px',
        marginBottom: '16px',
      }}
    >
      {steps.map((step) => {
        const isExpanded = !!expandedSteps[step.id];

        // Pick matching icon and style
        let icon = <Cpu size={13} style={{ color: 'var(--color-forest)' }} />;
        let iconBg = 'rgba(0, 84, 55, 0.08)';

        if (step.type === 'command') {
          icon = <Terminal size={13} style={{ color: '#0284c7' }} />;
          iconBg = 'rgba(2, 132, 199, 0.1)';
        } else if (step.type === 'file_read') {
          icon = <FileText size={13} style={{ color: 'var(--color-forest)' }} />;
          iconBg = 'rgba(0, 84, 55, 0.08)';
        } else if (step.type === 'file_write') {
          icon = <FilePlus size={13} style={{ color: '#16a34a' }} />;
          iconBg = 'rgba(22, 163, 74, 0.1)';
        } else if (step.type === 'web_search') {
          icon = <Globe size={13} style={{ color: '#0284c7' }} />;
          iconBg = 'rgba(2, 132, 199, 0.12)';
        } else if (step.type === 'web_fetch' || step.type === 'web_crawl') {
          icon = <Compass size={13} style={{ color: '#0d9488' }} />;
          iconBg = 'rgba(13, 148, 136, 0.12)';
        } else if (step.type === 'image_search') {
          icon = <ImageIcon size={13} style={{ color: '#8b5cf6' }} />;
          iconBg = 'rgba(139, 92, 246, 0.12)';
        } else if (step.type === 'image_download') {
          icon = <Download size={13} style={{ color: '#16a34a' }} />;
          iconBg = 'rgba(22, 163, 74, 0.14)';
        } else if (step.type === 'research_bundle') {
          icon = <Layers size={13} style={{ color: '#2563eb' }} />;
          iconBg = 'rgba(37, 99, 235, 0.12)';
        } else if (step.type === 'file_edit') {
          icon = <FileEdit size={13} style={{ color: '#ca8a04' }} />;
          iconBg = 'rgba(202, 138, 4, 0.1)';
        } else if (step.type === 'search') {
          icon = <Search size={13} style={{ color: '#7c3aed' }} />;
          iconBg = 'rgba(124, 58, 237, 0.1)';
        } else if (step.type === 'browser') {
          icon = <Globe size={13} style={{ color: '#2563eb' }} />;
          iconBg = 'rgba(37, 99, 235, 0.1)';
        } else if (step.type === 'verification') {
          icon = <CheckCircle2 size={13} style={{ color: 'var(--color-forest)' }} />;
          iconBg = 'rgba(0, 84, 55, 0.12)';
        } else if (step.type === 'mission_complete') {
          icon = <Flag size={13} style={{ color: '#16a34a' }} />;
          iconBg = 'rgba(22, 163, 74, 0.15)';
        } else if (step.type === 'failover' || step.status === 'failed') {
          icon = <AlertTriangle size={13} style={{ color: 'var(--text-failure)' }} />;
          iconBg = 'var(--bg-failure)';
        }

        return (
          <div
            key={step.id}
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderRadius: '6px',
              border: `1px solid ${step.status === 'failed' ? 'var(--border-failure)' : 'var(--border-subtle)'}`,
              overflow: 'hidden',
              fontSize: '12px',
              transition: 'border-color 150ms ease',
            }}
          >
            {/* Header / Clickable Summary Row */}
            <div
              onClick={() => toggleExpand(step.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '6px 12px',
                cursor: 'pointer',
                gap: '8px',
                userSelect: 'none',
              }}
            >
              {/* Disclosure triangle */}
              <div style={{ color: 'var(--text-secondary)', display: 'flex', alignItems: 'center' }}>
                {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </div>

              {/* Icon badge */}
              <div
                style={{
                  width: '20px',
                  height: '20px',
                  borderRadius: '4px',
                  backgroundColor: iconBg,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                {icon}
              </div>

              {/* Headline */}
              <div
                style={{
                  flex: 1,
                  fontWeight: 500,
                  color: step.status === 'failed' ? 'var(--text-failure)' : 'var(--text-main)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  fontFamily: step.type === 'command' ? 'var(--font-mono)' : 'inherit',
                  fontSize: step.type === 'command' ? '11px' : '12px',
                }}
              >
                {step.headline || (step.status === 'running' ? 'Executing...' : 'Completed')}
              </div>

              {/* Diff chips */}
              {step.diffStat && (
                <div style={{ display: 'flex', gap: '4px', alignItems: 'center', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
                  {step.diffStat.added > 0 && (
                    <span
                      style={{
                        padding: '1px 5px',
                        borderRadius: '3px',
                        backgroundColor: 'rgba(22, 163, 74, 0.15)',
                        color: '#16a34a',
                        fontWeight: 600,
                      }}
                    >
                      +{step.diffStat.added}
                    </span>
                  )}
                  {step.diffStat.deleted > 0 && (
                    <span
                      style={{
                        padding: '1px 5px',
                        borderRadius: '3px',
                        backgroundColor: 'rgba(220, 38, 38, 0.15)',
                        color: '#dc2626',
                        fontWeight: 600,
                      }}
                    >
                      -{step.diffStat.deleted}
                    </span>
                  )}
                </div>
              )}

              {/* Exit code chip */}
              {step.exitCode !== undefined && (
                <span
                  style={{
                    padding: '1px 5px',
                    borderRadius: '3px',
                    backgroundColor: step.exitCode === 0 ? 'rgba(0, 84, 55, 0.1)' : 'var(--bg-failure)',
                    color: step.exitCode === 0 ? 'var(--color-forest)' : 'var(--text-failure)',
                    fontSize: '10px',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                  }}
                >
                  exit {step.exitCode}
                </span>
              )}

              {/* Duration chip */}
              {step.durationMs !== undefined && step.durationMs > 0 && (
                <span
                  style={{
                    color: 'var(--text-secondary)',
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    flexShrink: 0,
                  }}
                >
                  {step.durationMs < 1000 ? `${step.durationMs}ms` : `${(step.durationMs / 1000).toFixed(1)}s`}
                </span>
              )}

              {/* Running indicator */}
              {step.status === 'running' && (
                <span
                  style={{
                    display: 'inline-block',
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    backgroundColor: '#16a34a',
                    boxShadow: '0 0 6px rgba(22, 163, 74, 0.8)',
                    animation: 'pulse 1.2s infinite',
                  }}
                />
              )}
            </div>

            {/* Collapsible Details Drawer */}
            {isExpanded && (
              <div
                style={{
                  padding: '8px 12px 10px 36px',
                  borderTop: '1px solid var(--border-subtle)',
                  backgroundColor: 'rgba(0, 61, 40, 0.02)',
                  fontSize: '11px',
                }}
              >
                {/* Thought Details (NEVER shows raw <think> tags) */}
                {step.type === 'thought' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <div style={{ color: 'var(--text-secondary)' }}>
                      <strong>Active Component / Model:</strong>{' '}
                      <span style={{ fontFamily: 'var(--font-mono)' }}>
                        {step.provider === 'runtime' || step.model === 'turn_deadline_enforcer'
                          ? 'Internal Runtime Supervisor (turn_deadline_enforcer)'
                          : (step.model || 'Unknown Model')}
                      </span>
                    </div>
                    <div style={{ color: 'var(--text-secondary)' }}>
                      <strong>Routing Tier:</strong>{' '}
                      <span>
                        {step.provider === 'runtime' || step.model === 'turn_deadline_enforcer'
                          ? 'Internal Runtime Control'
                          : `Tier ${step.tier || 1} ${step.tier === 1 ? '(Primary)' : (step.tier === 2 ? '(Tier 2 Fallback)' : '(Tier 3 Fallback)')}`}
                      </span>
                    </div>
                    {step.durationMs && (
                      <div style={{ color: 'var(--text-secondary)' }}>
                        <strong>Reasoning Latency:</strong> {(step.durationMs / 1000).toFixed(2)} seconds
                      </div>
                    )}
                  </div>
                )}

                {/* Command Details */}
                {step.type === 'command' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {step.command && (
                      <div
                        style={{
                          backgroundColor: '#1e1e1e',
                          color: '#d4d4d4',
                          padding: '6px 10px',
                          borderRadius: '4px',
                          fontFamily: 'var(--font-mono)',
                          fontSize: '11px',
                          position: 'relative',
                          overflowX: 'auto',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                          <span style={{ color: '#858585', fontSize: '10px' }}>COMMAND</span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleCopy(step.id, step.command || '');
                            }}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: '#858585',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '3px',
                              fontSize: '10px',
                            }}
                          >
                            {copiedId === step.id ? <Check size={11} color="#4ade80" /> : <Copy size={11} />}
                          </button>
                        </div>
                        <code>{step.command}</code>
                      </div>
                    )}
                    {step.outputPreview && (
                      <div
                        style={{
                          backgroundColor: 'rgba(0, 0, 0, 0.04)',
                          padding: '6px 10px',
                          borderRadius: '4px',
                          fontFamily: 'var(--font-mono)',
                          fontSize: '11px',
                          color: 'var(--text-main)',
                          maxHeight: '160px',
                          overflowY: 'auto',
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {step.outputPreview}
                      </div>
                    )}
                  </div>
                )}

                {/* File Read/Write/Edit Details */}
                {(step.type === 'file_read' || step.type === 'file_write' || step.type === 'file_edit') && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {step.targetPath && (
                      <div style={{ color: 'var(--text-secondary)' }}>
                        <strong>File:</strong>{' '}
                        <span style={{ fontFamily: 'var(--font-mono)' }}>{step.targetPath}</span>
                      </div>
                    )}
                    {step.outputPreview && (
                      <div
                        style={{
                          marginTop: '4px',
                          backgroundColor: 'rgba(0, 0, 0, 0.04)',
                          padding: '6px 10px',
                          borderRadius: '4px',
                          fontFamily: 'var(--font-mono)',
                          fontSize: '11px',
                          color: 'var(--text-main)',
                          maxHeight: '140px',
                          overflowY: 'auto',
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {step.outputPreview}
                      </div>
                    )}
                  </div>
                )}

                {/* Web Search Details */}
                {step.type === 'web_search' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                      <span><strong>Provider:</strong> {step.metadata?.provider || 'Google Serper'}</span>
                      {step.metadata?.results?.length && (
                        <span>{step.metadata.results.length} ranked results</span>
                      )}
                    </div>
                    {step.metadata?.results && Array.isArray(step.metadata.results) ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {step.metadata.results.map((res: any, idx: number) => (
                          <div
                            key={idx}
                            style={{
                              backgroundColor: 'rgba(0, 0, 0, 0.03)',
                              borderRadius: '4px',
                              padding: '6px 8px',
                              border: '1px solid var(--border-subtle)',
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px' }}>
                              <a
                                href={res.url}
                                target="_blank"
                                rel="noreferrer"
                                style={{
                                  fontWeight: 600,
                                  color: '#0284c7',
                                  textDecoration: 'none',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  fontSize: '11px',
                                }}
                              >
                                {res.title || 'Untitled'}
                                <ExternalLink size={10} />
                              </a>
                              {res.date && <span style={{ color: 'var(--text-secondary)', fontSize: '10px' }}>{res.date}</span>}
                            </div>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '10px', marginTop: '2px' }}>
                              {res.snippet}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      step.outputPreview && (
                        <div
                          style={{
                            backgroundColor: 'rgba(0, 0, 0, 0.04)',
                            padding: '6px 10px',
                            borderRadius: '4px',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '11px',
                            color: 'var(--text-main)',
                            maxHeight: '160px',
                            overflowY: 'auto',
                            whiteSpace: 'pre-wrap',
                          }}
                        >
                          {step.outputPreview}
                        </div>
                      )
                    )}
                  </div>
                )}

                {/* Image Search Details (Thumbnails Grid) */}
                {step.type === 'image_search' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                      <span><strong>Visual Asset Repository:</strong> {step.metadata?.provider || 'Pixabay API'}</span>
                      {step.metadata?.count !== undefined && (
                        <span>{step.metadata.count} candidates found</span>
                      )}
                    </div>
                    {step.metadata?.images && Array.isArray(step.metadata.images) && step.metadata.images.length > 0 ? (
                      <div
                        style={{
                          display: 'grid',
                          gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))',
                          gap: '8px',
                          marginTop: '4px',
                        }}
                      >
                        {step.metadata.images.map((img: any, idx: number) => (
                          <div
                            key={idx}
                            style={{
                              borderRadius: '4px',
                              overflow: 'hidden',
                              border: '1px solid var(--border-subtle)',
                              backgroundColor: 'var(--bg-surface)',
                              display: 'flex',
                              flexDirection: 'column',
                            }}
                          >
                            <div style={{ height: '70px', overflow: 'hidden', backgroundColor: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                              <img
                                src={img.preview_url || img.image_url}
                                alt={img.title || 'Candidate'}
                                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                                loading="lazy"
                              />
                            </div>
                            <div style={{ padding: '4px 6px', fontSize: '10px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                              <span style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {img.title || 'Image'}
                              </span>
                              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                                <span>{img.width}x{img.height}</span>
                                <span style={{ color: '#16a34a', fontWeight: 500 }}>Royalty-Free</span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      step.outputPreview && (
                        <div style={{ color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>
                          {step.outputPreview}
                        </div>
                      )
                    )}
                  </div>
                )}

                {/* Image Download Details */}
                {step.type === 'image_download' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      {step.metadata?.source_url && (
                        <div
                          style={{
                            width: '80px',
                            height: '56px',
                            borderRadius: '4px',
                            overflow: 'hidden',
                            backgroundColor: '#000',
                            flexShrink: 0,
                            border: '1px solid var(--border-subtle)',
                          }}
                        >
                          <img
                            src={step.metadata.source_url}
                            alt={step.metadata?.alt_text || 'Downloaded asset'}
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                          />
                        </div>
                      )}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span style={{ fontWeight: 600, color: 'var(--text-main)', fontFamily: 'var(--font-mono)' }}>
                            {step.metadata?.relative_path || step.targetPath || 'assets/images/image.jpg'}
                          </span>
                          <span
                            style={{
                              padding: '1px 5px',
                              borderRadius: '3px',
                              backgroundColor: 'rgba(22, 163, 74, 0.15)',
                              color: '#16a34a',
                              fontSize: '10px',
                              fontWeight: 600,
                            }}
                          >
                            ✓ VERIFIED
                          </span>
                        </div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '10px' }}>
                          {step.metadata?.width && step.metadata?.height ? `${step.metadata.width} x ${step.metadata.height} px` : ''}
                          {step.metadata?.size_bytes ? ` • ${(step.metadata.size_bytes / 1024).toFixed(1)} KB` : ''}
                          {step.metadata?.format ? ` • ${step.metadata.format.toUpperCase()}` : ''}
                        </div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '10px', marginTop: '2px' }}>
                          <strong>License:</strong> {step.metadata?.attribution?.license || 'Pixabay Content License (Free Commercial Use)'}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Web Fetch / Web Crawl / Research Bundle Details */}
                {(step.type === 'web_fetch' || step.type === 'web_crawl' || step.type === 'research_bundle') && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {step.outputPreview && (
                      <div
                        style={{
                          backgroundColor: 'rgba(0, 0, 0, 0.04)',
                          padding: '6px 10px',
                          borderRadius: '4px',
                          fontFamily: 'var(--font-mono)',
                          fontSize: '11px',
                          color: 'var(--text-main)',
                          maxHeight: '160px',
                          overflowY: 'auto',
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {step.outputPreview}
                      </div>
                    )}
                  </div>
                )}

                {/* Verification / Mission Completion Details */}
                {(step.type === 'verification' || step.type === 'mission_complete') && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <div style={{ color: 'var(--text-main)', fontWeight: 600 }}>
                      {step.headline}
                    </div>
                    {step.outputPreview && (
                      <div style={{ color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>
                        {step.outputPreview}
                      </div>
                    )}
                  </div>
                )}

                {/* Error / Failover Details */}
                {step.rawError && (
                  <div
                    style={{
                      marginTop: '4px',
                      backgroundColor: 'var(--bg-failure)',
                      color: 'var(--text-failure)',
                      padding: '6px 10px',
                      borderRadius: '4px',
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    {step.rawError}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {/* Active Working Pulse when isRunning is true and no step is explicitly running */}
      {isRunning && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '6px 12px',
            borderRadius: '6px',
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            fontSize: '12px',
            color: 'var(--color-forest)',
            fontWeight: 500,
          }}
        >
          <span
            style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: '#16a34a',
              boxShadow: '0 0 8px rgba(22, 163, 74, 0.8)',
              animation: 'pulse 1.2s infinite',
            }}
          />
          <span>Working...</span>
        </div>
      )}
    </div>
  );
};
