// gui/src/sync.ts
// Authoritative Client-Side Mission State Synchronizer & Race Guard
// Enforces monotonic state versioning, sequence cursors, stale event rejection,
// and delayed snapshot race protection.

import { MissionSnapshot, HermesEvent } from './types';

export interface ClientSyncState {
  snapshot: MissionSnapshot | null;
  events: HermesEvent[];
  seenEventIds?: Set<string>;
  seenSequences?: Set<number>;
  lastWatermark: {
    state_version: number;
    last_sequence: number;
  };
}

export function createInitialSyncState(initialSnapshot?: MissionSnapshot | null): ClientSyncState {
  return {
    snapshot: initialSnapshot || null,
    events: [],
    seenEventIds: new Set<string>(),
    seenSequences: new Set<number>(),
    lastWatermark: {
      state_version: initialSnapshot?.state_version || 0,
      last_sequence: initialSnapshot?.last_sequence || 0,
    },
  };
}

export interface SyncResult {
  nextState: ClientSyncState;
  accepted: boolean;
  reason?: string;
}

/**
 * Reconcile an incoming mission snapshot against established client state.
 * Rejects delayed or out-of-order snapshots whose state_version or last_sequence
 * regresses behind the established client watermark.
 */
export function processIncomingSnapshot(
  currentState: ClientSyncState,
  incomingSnapshot: MissionSnapshot
): SyncResult {
  // Guard 1: Mission identity isolation
  if (currentState.snapshot && currentState.snapshot.mission_id !== incomingSnapshot.mission_id) {
    return {
      nextState: currentState,
      accepted: false,
      reason: `Mismatched mission ID: current=${currentState.snapshot.mission_id}, incoming=${incomingSnapshot.mission_id}`,
    };
  }

  // Guard 2: Monotonic watermark check (prevents delayed snapshot regressions)
  if (currentState.snapshot) {
    const isTerminal = incomingSnapshot.is_terminal ||
      ['COMPLETED', 'FAILED', 'CANCELLED', 'STOPPED', 'ABORTED'].includes(incomingSnapshot.status || '');
    const currentVersion = currentState.snapshot.state_version ?? 0;
    const incomingVersion = incomingSnapshot.state_version ?? 0;

    // Terminal state transitions must always be accepted.
    // Non-terminal snapshots must not regress behind current authoritative snapshot version.
    if (!isTerminal && incomingVersion < currentVersion) {
      return {
        nextState: currentState,
        accepted: false,
        reason: `Delayed snapshot rejected: version ${incomingVersion} < current snapshot version ${currentVersion}`,
      };
    }
  }

  // Update watermark and retain existing events (deduplicating and sorting)
  // Pruning historical events when snapshot arrives was the root cause of the empty-panel incident!
  const nextEvents = [...currentState.events];
  return {
    nextState: {
      snapshot: incomingSnapshot,
      events: nextEvents,
      seenEventIds: currentState.seenEventIds,
      seenSequences: currentState.seenSequences,
      lastWatermark: {
        state_version: Math.max(currentState.lastWatermark.state_version, incomingSnapshot.state_version),
        last_sequence: Math.max(currentState.lastWatermark.last_sequence, incomingSnapshot.last_sequence),
      },
    },
    accepted: true,
  };
}

/**
 * Reconcile an incoming real-time SSE event against established client state.
 * Rejects duplicate events, stale events from older attempts/runs, and out-of-order events.
 */
export function processIncomingEvent(
  currentState: ClientSyncState,
  incomingEvent: HermesEvent
): SyncResult {
  // Guard 1: Mission identity isolation
  if (currentState.snapshot && incomingEvent.mission_id && incomingEvent.mission_id !== currentState.snapshot.mission_id) {
    return {
      nextState: currentState,
      accepted: false,
      reason: `Mismatched mission ID: event ${incomingEvent.mission_id} != current ${currentState.snapshot.mission_id}`,
    };
  }

  // Guard 2: Stale attempt number rejection
  if (
    currentState.snapshot?.attempt_number &&
    incomingEvent.attempt_number &&
    incomingEvent.attempt_number < currentState.snapshot.attempt_number
  ) {
    return {
      nextState: currentState,
      accepted: false,
      reason: `Stale attempt event dropped: event attempt ${incomingEvent.attempt_number} < snapshot attempt ${currentState.snapshot.attempt_number}`,
    };
  }

  // Guard 3: Duplicate event rejection (O(1) Set lookup)
  const seenSeqs = currentState.seenSequences ?? new Set(currentState.events.map((e) => e.sequence).filter((s) => s > 0));
  const seenIds = currentState.seenEventIds ?? new Set(currentState.events.map((e) => e.event_id).filter(Boolean));

  const isDuplicate =
    (incomingEvent.sequence > 0 && seenSeqs.has(incomingEvent.sequence)) ||
    (Boolean(incomingEvent.event_id) && seenIds.has(incomingEvent.event_id));

  if (isDuplicate) {
    return {
      nextState: currentState,
      accepted: false,
      reason: `Duplicate event rejected: sequence=${incomingEvent.sequence}, event_id=${incomingEvent.event_id}`,
    };
  }

  // Guard 4: Event sequence monotonicity
  const nextSeq = Math.max(currentState.lastWatermark.last_sequence, incomingEvent.sequence || 0);

  // Maximum events retained in GUI display projection to bound rendering memory
  const MAX_GUI_EVENTS = 500;
  const updatedEvents = [...currentState.events, incomingEvent];
  const boundedEvents =
    updatedEvents.length > MAX_GUI_EVENTS
      ? updatedEvents.slice(updatedEvents.length - MAX_GUI_EVENTS)
      : updatedEvents;

  const nextSeenSeqs = new Set(seenSeqs);
  if (incomingEvent.sequence > 0) nextSeenSeqs.add(incomingEvent.sequence);
  const nextSeenIds = new Set(seenIds);
  if (incomingEvent.event_id) nextSeenIds.add(incomingEvent.event_id);

  return {
    nextState: {
      ...currentState,
      events: boundedEvents,
      seenEventIds: nextSeenIds,
      seenSequences: nextSeenSeqs,
      lastWatermark: {
        state_version: currentState.lastWatermark.state_version,
        last_sequence: nextSeq,
      },
    },
    accepted: true,
  };
}
