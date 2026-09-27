# HERMES 2.x — TUI 2.x Architecture Specification

## 1. Executive Summary

Prompt 15 implements the **HERMES 2.x Terminal User Interface (TUI 2.x)** as an event-driven, strictly isolated projection layer over the authoritative agent runtime.

The design adheres to one central tenet:
> **TUI OBSERVES; TUI DOES NOT DECIDE.**  
> **UI FAILURE MUST NEVER EQUAL MISSION FAILURE.**

The TUI is not a monolithic console application that runs the agent loop or issues database updates; rather, it is a passive presentation layer that samples runtime snapshots, produces immutable view models, computes minimal ANSI diffs, and routes user keystrokes back to the authoritative services.

---

## 2. Unidirectional Data Flow

The rendering pipeline enforces strict unidirectional data flow:

```
┌─────────────────┐
│  AGENT RUNTIME  │ ◄─── (Headless, Autonomous, Resumable)
└────────┬────────┘
         │ emits HermesEvent
         ▼
┌─────────────────┐
│    EVENT BUS    │
└────────┬────────┘
         │ notifies
         ▼
┌─────────────────┐
│   STATE STORE   │ ◄─── (Authoritative SQLite & CAS Checkpoints)
└────────┬────────┘
         │ sampled
         ▼
┌─────────────────┐
│   VIEW MODELS   │ ◄─── (Immutable, Normalized, Pure Dataclasses)
└────────┬────────┘
         │ coalesced
         ▼
┌─────────────────┐
│ RENDER SCHEDULER│ ◄─── (Adaptive FPS, Frame Coalescing, Stale Rejection)
└────────┬────────┘
         │ builds frame
         ▼
┌─────────────────┐
│  SCREEN BUFFER  │ ◄─── (2D Cell Grid Canvas, Layout Engine)
└────────┬────────┘
         │ compares
         ▼
┌─────────────────┐
│   FRAME DIFF    │ ◄─── (Row-level skips, contiguous run calculation)
└────────┬────────┘
         │ emits ANSI
         ▼
┌─────────────────┐
│ TERMINAL WRITER │ ◄─── (Capability-aware, SGR style cache, IO containment)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  TERMINAL TTY   │
└─────────────────┘
```

### Input Pipeline
User input flows in an isolated reverse pipeline:
```
┌─────────────────┐
│  STDIN BYTES    │
└────────┬────────┘
         │ decode bytes
         ▼
┌─────────────────┐
│  INPUT DECODER  │ ◄─── (ANSI escape parsing, UTF-8, mouse, keys)
└────────┬────────┘
         │ typed events
         ▼
┌─────────────────┐
│  INPUT ROUTER   │ ◄─── (Modal routing: Security y/n, Rewind y/n, Slash cmd)
└────────┬────────┘
         │ dispatches
         ▼
┌─────────────────┐
│ AUTHORITATIVE   │ ◄─── (SessionManager, SecurityGate, MissionDriver)
│    SERVICE      │
└─────────────────┘
```

---

## 3. Strict Purity and Isolation Invariants

The TUI renderer and view models operate under verified structural constraints:
1. **NO NETWORK CALLS:** Never issues HTTP/TCP requests or calls remote APIs.
2. **NO MODEL INVOCATION:** Never calls LLM providers (Ollama, NIM, OpenAI, Anthropic).
3. **NO DIRECT DISK/FILESYSTEM WRITES:** Rendering emits ANSI to standard out; it never writes cache files, logs, or workspace files.
4. **NO DIRECT SQLITE QUERIES:** All runtime telemetry and task queues are projected from in-memory state snapshots or viewmodel inputs. No raw SQL `SELECT` or `UPDATE` queries execute during frame building.
5. **NO GIT COMMANDS:** Git operations are strictly confined to the backend checkpoint and recovery engines.
6. **NO SECURITY DECISIONS:** The TUI renders approval requests and collects user keystrokes (`'y'`, `'n'`); it does not evaluate policy or grant bypasses.
7. **HEADLESS DECOUPLING:** The backend runtime can run completely detached from the TUI (headless mode), with zero dependency on terminal libraries or curses.

---

## 4. Failure Containment & Circuit Breaker

To satisfy the invariant **"UI FAILURE MUST NEVER EQUAL MISSION FAILURE"**, rendering is managed by the `RenderSupervisor`:

```
               ┌───────────────┐
               │    PRIMARY    │
               │  TuiRenderer  │
               └───────┬───────┘
                       │ Exception caught
                       ▼
               ┌───────────────┐
               │   DEGRADED    │
               │ (Panel Fallback)
               └───────┬───────┘
                       │ Repeated crashes (>3)
                       ▼
               ┌───────────────┐
               │   FALLBACK    │
               │FallbackRenderer│
               └───────┬───────┘
                       │ Periodic probe (every 30 frames)
                       ▼
               ┌───────────────┐
               │    PROBING    │
               └───────────────┘
```

1. **Panel-Level Containment:** If an individual pane (e.g. Chat or Operations) raises an exception, the rest of the screen continues rendering normally, with an inline error banner replacing only that panel.
2. **Global Fallback:** If `TuiRenderer` fails catastrophically, `RenderSupervisor` immediately drops to `FallbackRenderer`, which emits a clean, truthful 4-line status summary showing mission ID, status, active task, and progress.
3. **Runtime Protection:** Under no circumstances does an unhandled UI exception terminate the `EventBus` or abort the running mission.

---

## 5. Performance and Scalability Guarantees

- **Virtualization:** The chat pane uses `VirtualList.slice_viewport` with $O(\text{viewport})$ computational and memory complexity. 10,000+ items slice in under 0.01 ms.
- **Adaptive Throttling:** `RenderScheduler` dynamically shifts between 0 FPS (idle), 30 FPS (active operations), and 60 FPS (streaming model deltas).
- **Frame Coalescing:** High-frequency event storms (1,000+ events/sec) coalesce into single render ticks, discarding intermediate states without tearing.
- **Minimal Diffing:** `FrameDiffer` skips unchanged rows and groups modified cells into contiguous ANSI runs, reducing terminal bandwidth by >95% during typical operations.
